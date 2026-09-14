#!/usr/bin/env python3
"""
Second-pass recovery for sources whose scrape came back empty.

This replaces a Jules API session that never worked. The session was handed
the failed sites' URLs plus truncated HTML snapshots and asked to return JSON;
in every run on record it hit its timeout and recovered nothing, at a cost of
15 minutes of runner time per week.

The replacement needs no API key and no model. It exploits a property of
venue websites that the listing-page scraper cannot use: **an event's own page
is almost always far better marked up than the listing that links to it.**
Ritter Butzke is the canonical case - its listing renders client-side and
serves a scraper 627 characters of chrome, but every /event/<slug> page it
links to carries a complete schema.org MusicEvent block, startDate included.

So recovery walks the other way round:

  1. Re-read the HTML snapshot the scrape leg already saved (no refetch).
  2. Harvest same-origin links that look like one event's own page.
  3. Fetch a bounded number of them and extract each individually, preferring
     their schema.org markup.
  4. Validate against the same date window and price cap the leg used, then
     merge into the aggregate.

Sites with genuinely nothing on offer stay empty, which is the point: measured
across the matrix, sites between seasons (werk9, improfabrik) expose zero
detail links, while every site with a real programme exposes 12-193 of them.

Best-effort and never fatal: any failure leaves --output containing exactly
the input events.
"""

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup  # noqa: E402

from generic_event_scraper import (  # noqa: E402
    _links_to_detail,
    extract_jsonld_events,
    fetch_plain,
    is_bot_challenge,
    scrape_document,
)
from event_utils import (  # noqa: E402
    DEFAULT_MAX_PRICE,
    clean_url,
    dedupe_events,
    scrape_window,
    validate_events,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Bounds. Recovery runs after every weekly run and must stay a tail cost, not
# a second scrape: at most this many sites, this many of each site's event
# pages, fetched this many at a time.
MAX_SITES = 12
MAX_PAGES_PER_SITE = 24
MAX_WORKERS = 6

# An event page describes one event, but some of the links harvested are
# themselves small listings (Ritter Butzke's /events is one). Allow a page to
# contribute several rows rather than truncating those, and let validation and
# dedupe do the filtering - a row with no date never survives either way.
MAX_ROWS_PER_PAGE = 40


def find_failed_sites(raw_dir: str, html_dir: str) -> List[Dict[str, Any]]:
    """Every raw_*.json that came back with no events, with its own window.

    The window is read back from the raw file rather than recomputed, so
    recovered events are held to exactly the same range the leg used even if
    recovery runs either side of midnight.
    """
    failed = []
    for raw_path in sorted(Path(raw_dir).glob("raw_*.json")):
        try:
            data = json.loads(raw_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("events"):
            continue
        name = raw_path.stem[len("raw_"):]
        failed.append({
            "name": name,
            "url": data.get("source", ""),
            "html_path": os.path.join(html_dir, f"{name}.html"),
            "window_start": data.get("window_start"),
            "window_end": data.get("window_end"),
        })
    return failed


def harvest_detail_links(html: str, source_url: str,
                         limit: int = MAX_PAGES_PER_SITE) -> List[str]:
    """Same-origin links from a listing page that lead to one event's page.

    Restricted to the source's own host: a listing links out to ticket
    vendors, maps and social profiles, and following those would scrape
    somebody else's site rather than recover this one.
    """
    host = urlparse(source_url).netloc
    if not host:
        return []
    soup = BeautifulSoup(html, "lxml")
    seen, links = set(), []
    for anchor in soup.find_all("a", href=True):
        absolute = clean_url(urljoin(source_url, anchor["href"].strip()))
        if urlparse(absolute).netloc != host:
            continue
        if not _links_to_detail(absolute):
            continue
        # The listing itself is not one of its own event pages.
        if absolute.rstrip("/") == source_url.rstrip("/"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
        if len(links) >= limit:
            break
    return links


def extract_from_detail_page(url: str, fetch=fetch_plain) -> List[Dict[str, Any]]:
    """Everything one event page has to say, schema.org first."""
    html = fetch(url)
    if not html or is_bot_challenge(html):
        return []
    # A page's own JSON-LD is authoritative for it - it carries the exact
    # start date, and often the price and venue the listing omitted.
    jsonld = extract_jsonld_events(html, url)
    if jsonld:
        return jsonld[:MAX_ROWS_PER_PAGE]
    return scrape_document(html, url, f"recovery {url}")[:MAX_ROWS_PER_PAGE]


def _read_snapshot(site: Dict[str, Any], fetch=fetch_plain) -> Optional[str]:
    """The leg's saved page, or a fresh fetch when no snapshot was written."""
    path = site.get("html_path") or ""
    if path and os.path.exists(path):
        try:
            html = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            html = ""
        if html.strip():
            return html
    return fetch(site["url"]) if site.get("url") else None


def _window_for(site: Dict[str, Any], date_days: int) -> Tuple[date, date]:
    try:
        return (date.fromisoformat(site["window_start"]),
                date.fromisoformat(site["window_end"]))
    except (KeyError, TypeError, ValueError):
        return scrape_window(date_days)


def recover_site(site: Dict[str, Any], date_days: int, max_price: float,
                 max_pages: int = MAX_PAGES_PER_SITE,
                 workers: int = MAX_WORKERS,
                 fetch=fetch_plain) -> List[Dict[str, Any]]:
    """Recover whatever one empty source's event pages still have to offer."""
    name, url = site.get("name", "?"), site.get("url", "")
    if not url:
        return []

    html = _read_snapshot(site, fetch=fetch)
    if not html:
        logger.info(f"  {name}: no page to work from")
        return []
    if is_bot_challenge(html):
        # The snapshot is an anti-bot interstitial, so it has no real links to
        # follow; only the rendered-DOM tier can get past this.
        logger.info(f"  {name}: snapshot is a bot challenge, nothing to harvest")
        return []

    links = harvest_detail_links(html, url, limit=max_pages)
    if not links:
        logger.info(f"  {name}: no event pages linked - the source is empty, not blocked")
        return []

    def extract(link: str) -> List[Dict[str, Any]]:
        return extract_from_detail_page(link, fetch=fetch)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        batches = list(pool.map(extract, links))
    rows = [event for batch in batches for event in batch]

    window_start, window_end = _window_for(site, date_days)
    kept, _ = validate_events(rows, source_url=url, window_start=window_start,
                              window_end=window_end, max_price=max_price)
    kept = dedupe_events(kept)
    logger.info(
        f"  {name}: {len(links)} event pages -> {len(rows)} rows -> "
        f"{len(kept)} kept for {window_start}..{window_end}"
    )
    return kept


def main():
    parser = argparse.ArgumentParser(
        description="Recover events for sources whose scrape returned nothing")
    parser.add_argument("--aggregated", required=True, help="Aggregated events JSON (input)")
    parser.add_argument("--raw-dir", default="data", help="Directory with raw_<name>.json outputs")
    parser.add_argument("--html-dir", default="data/html", help="Directory with <name>.html snapshots")
    parser.add_argument("--output", required=True, help="Output JSON (aggregated + recovered)")
    parser.add_argument("--date-days", type=int, default=7,
                        help="Fallback window when a raw file records none")
    parser.add_argument("--price-max", type=float, default=DEFAULT_MAX_PRICE)
    parser.add_argument("--max-sites", type=int, default=MAX_SITES)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES_PER_SITE,
                        help="Event pages fetched per site (0 disables recovery)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)

    args = parser.parse_args()

    try:
        with open(args.aggregated, encoding="utf-8") as handle:
            aggregated = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error(f"Could not read {args.aggregated}: {exc}")
        return 1
    events = aggregated.get("events", [])

    recovered: List[Dict[str, Any]] = []
    failed = find_failed_sites(args.raw_dir, args.html_dir)
    logger.info(f"{len(failed)} site(s) returned 0 events and are candidates for recovery")

    if args.max_pages > 0:
        for site in failed[:args.max_sites]:
            try:
                recovered.extend(
                    recover_site(site, args.date_days, args.price_max,
                                 max_pages=args.max_pages, workers=args.workers)
                )
            except Exception as exc:  # noqa: BLE001 - recovery is never fatal
                logger.warning(f"  {site.get('name')}: recovery failed ({exc})")

    # Two separate things happen here, and they used to be reported as one
    # number that could come out negative ("458 scraped + -31 recovered").
    #
    #  1. The aggregate is a plain concatenation of the per-source files, so
    #     it still holds cross-source duplicates - Berlin listing sites carry
    #     each other's shows. Deduping is this step's job because it is the
    #     first point where every source is in one list.
    #  2. Recovered rows are merged in, deduped against the scraped set too,
    #     so a partly-recovered site cannot double-publish an event.
    scraped = dedupe_events(events)
    duplicates = len(events) - len(scraped)
    merged = dedupe_events(events + recovered)
    added = len(merged) - len(scraped)

    payload = dict(aggregated)
    payload["events"] = merged
    payload["count"] = len(merged)
    payload["recovered_count"] = added
    payload["duplicates_removed"] = duplicates
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    print(f"Recovery done: {len(events)} scraped - {duplicates} duplicates "
          f"+ {added} recovered = {len(merged)} total -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
