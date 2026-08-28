#!/usr/bin/env python3
"""
Generic multi-strategy event scraper.

Used as the fallback scraper for any site in the weekly matrix that doesn't
have a hand-written scraper (see scripts/rausgegangen_scraper.py,
scripts/eventbrite_scraper.py, scripts/meetup_scraper.py for site-specific
examples). Since the target sites are heterogeneous (Cloudflare-protected,
plain server-rendered HTML, JS single-page apps) and cannot all be
individually reverse-engineered up front, this tries progressively heavier
strategies and keeps the first one that finds anything:

  1. Plain HTTP GET + schema.org JSON-LD ("@type": "Event") extraction.
  2. Plain HTTP GET + generic heuristic scan (elements whose class hints at
     an event/listing row, containing a date or price pattern).
  3. CloakBrowser (stealth headless Chromium) render, then re-run 1 and 2
     against the rendered DOM - needed for Cloudflare challenges and JS SPAs.
  4. Jina Reader markdown fallback (only attempted if JINA_API_KEY is set;
     anonymous Jina requests are unreliably blocked by IP reputation).

Real-world extraction quality will vary a lot by site. Sites that keep
returning zero events are expected to be picked up by the existing
autonomous_repair.py + Jules analysis loop, which generates a dedicated
scraper once this generic one has repeatedly failed.
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from event_utils import (  # noqa: E402
    DATE_DE_RE,
    DATE_ISO_RE,
    DATE_TEXT_RE,
    FREE_RE,
    PRICE_RE,
    TIME_RE,
    clean_text,
    clean_url,
    dedupe_events,
    normalize_date,
    parse_date,
    parse_price,
    parse_time,
    scrape_window,
    title_from_slug,
    title_looks_noisy,
    validate_events,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BOT_CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "cf-browser-verification",
    "checking your browser",
    "access denied",
)

EVENT_CLASS_HINTS = (
    "event", "teaser", "views-row", "card", "listing", "termin",
    "veranstaltung", "programme-item", "program-item", "spielplan",
    "show-item",
)

# Hrefs that lead to a real event page rather than back into site navigation.
DETAIL_HREF_HINTS = (
    "/event", "/events/", "/veranstaltung", "/termin", "/programm/", "/show/",
    "/produktion", "/stueck", "/konzert", "/spielplan/event", "/e/", "/tickets",
)

# Navigation and utility links that must never be mistaken for an event link.
NON_DETAIL_HREF_RE = re.compile(
    r'(?:^#|^mailto:|^tel:|/(?:impressum|datenschutz|kontakt|newsletter|login|'
    r'anmelden|search|suche|cart|warenkorb|agb|privacy|cookie)\b)',
    re.IGNORECASE,
)


def _best_detail_url(scopes, source_url: str) -> str:
    """Pick the most event-like link near a card, falling back to the listing.

    Taking the first <a> in scope returned navigation chrome as often as an
    event page, which is why 36 published rows linked straight back to the
    listing they came from.
    """
    best = ""
    for scope in scopes:
        if not scope:
            continue
        for anchor in scope.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or NON_DETAIL_HREF_RE.search(href):
                continue
            absolute = urljoin(source_url, href)
            if any(hint in absolute.lower() for hint in DETAIL_HREF_HINTS):
                return clean_url(absolute)
            if not best:
                best = clean_url(absolute)
    return best or source_url


def is_bot_challenge(html: str) -> bool:
    head = html[:2000].lower()
    return any(marker in head for marker in BOT_CHALLENGE_MARKERS)


def fetch_plain(url: str, timeout: int = 20) -> Optional[str]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        logger.warning(f"Plain GET failed for {url}: {e}")
        return None


def _walk_jsonld_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.get("@graph", []) or []:
            yield from _walk_jsonld_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_jsonld_nodes(item)


def extract_jsonld_events(html: str, source_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    events = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.text
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_jsonld_nodes(data):
            node_type = node.get("@type", "")
            types = node_type if isinstance(node_type, list) else [node_type]
            if not any("event" in str(t).lower() for t in types):
                continue

            location = node.get("location") or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            venue = location.get("name", "") if isinstance(location, dict) else str(location)

            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = None
            if isinstance(offers, dict) and offers.get("price") is not None:
                try:
                    price = float(offers["price"])
                except (TypeError, ValueError):
                    price = None

            start_date = node.get("startDate", "") or ""

            offer_url = offers.get("url") if isinstance(offers, dict) else None
            event_url = node.get("url") or offer_url or source_url

            events.append({
                "title": clean_text(node.get("name")),
                # schema.org dates arrive as "2026-8-29" or with a time and
                # offset attached; publish a single zero-padded ISO form.
                "date": normalize_date(start_date) or "",
                "time": parse_time(start_date),
                "price": price,
                "category": clean_text(node.get("eventAttendanceMode") or ""),
                "description": clean_text(node.get("description"), max_length=400),
                "url": clean_url(urljoin(source_url, str(event_url))),
                "venue": clean_text(venue),
                "source_url": source_url,
            })
    return events


def extract_heuristic_events(html: str, source_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    for el in soup.find_all(True):
        classes = " ".join(el.get("class", [])).lower()
        if not any(hint in classes for hint in EVENT_CLASS_HINTS):
            continue
        text = el.get_text(" ", strip=True)
        if len(text) < 15 or len(text) > 3000:
            continue
        if not (PRICE_RE.search(text) or FREE_RE.search(text) or DATE_ISO_RE.search(text)
                or DATE_DE_RE.search(text) or DATE_TEXT_RE.search(text)):
            continue
        candidates.append((el, text))

    # Drop candidates that are nested inside another candidate, keeping the
    # outermost matching element so a whole event card is captured together
    # rather than a price/date fragment nested within it.
    kept = []
    for el, text in candidates:
        if any(el is not other and other in el.parents for other, _ in candidates):
            continue
        kept.append((el, text))

    events = []
    seen_titles = set()
    for el, text in kept[:60]:
        # Titles and links are often siblings of the matched fragment rather
        # than inside it (e.g. a Drupal "views-row" wrapping separate title,
        # image and price fields) - widen the search to nearby ancestors.
        search_scopes = [el, el.parent, getattr(el.parent, "parent", None)]

        event_url = _best_detail_url(search_scopes, source_url)

        title = ""
        for scope in search_scopes:
            if not scope:
                continue
            heading = scope.find(["h1", "h2", "h3", "h4", "h5"])
            if heading and heading.get_text(strip=True):
                title = heading.get_text(strip=True)
                break
            link_text = scope.find("a", href=True)
            link_text = link_text.get_text(strip=True) if link_text else ""
            if link_text and not PRICE_RE.search(link_text) and not TIME_RE.search(link_text):
                title = link_text
                break
        if not title:
            title = text[:120]
        title = title.strip() or "Untitled event"

        # When the card text is concatenated listing noise (badges, dates,
        # times), a clean slug from the event-detail link reads far better.
        if title_looks_noisy(title):
            slug_title = title_from_slug(event_url)
            if slug_title:
                title = slug_title

        dedup_key = title.lower()
        if dedup_key in seen_titles:
            continue
        seen_titles.add(dedup_key)

        # A date often only appears once, on an ancestor "day group" heading
        # (e.g. a calendar table cell), not repeated on each event fragment -
        # widen the date search to nearby ancestor text as a fallback.
        # The card's own text wins; ancestor text is appended, not prepended.
        # parse_date returns the first match it finds, so prepending the
        # listing's day heading made every card inherit that heading's date -
        # 67 rows in the last run were stamped with the page date instead of
        # their own ("So, 30. Aug" published as 27 Aug).
        date_context = text
        anc = el
        for _ in range(5):
            anc = getattr(anc, "parent", None)
            if not anc:
                break
            date_context = date_context + " " + anc.get_text(" ", strip=True)[:60]

        description = clean_text(text, max_length=400)
        events.append({
            "title": title[:200],
            "date": parse_date(date_context) or "",
            "time": parse_time(text),
            "price": parse_price(text),
            "category": "",
            "description": description,
            "url": event_url,
            # Venue is recovered from the card text by validate_event(); the
            # extractors used to hardcode "" and leave the Location column
            # blank on nearly two thirds of published rows.
            "venue": "",
            "source_url": source_url,
        })
    return events


def render_with_cloakbrowser(url: str) -> Optional[str]:
    try:
        from cloakbrowser import launch
    except ImportError:
        logger.warning("CloakBrowser not installed; skipping rendered-DOM tier")
        return None

    browser = None
    context = None
    try:
        browser = launch(headless=True, humanize=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        return page.content()
    except Exception as e:
        logger.warning(f"CloakBrowser render failed for {url}: {e}")
        return None
    finally:
        if context:
            context.close()
        if browser:
            browser.close()


def fetch_jina_content(url: str) -> Optional[str]:
    api_key = os.environ.get("JINA_API_KEY")
    if not api_key:
        logger.info("No JINA_API_KEY set; skipping Jina fallback (anonymous calls are unreliable)")
        return None
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        logger.warning(f"Jina Reader fetch failed for {url}: {e}")
        return None


def extract_jina_events(markdown: str, source_url: str) -> List[Dict[str, Any]]:
    events = []
    seen = set()
    for line in markdown.splitlines():
        text = line.strip()
        if len(text) < 8:
            continue
        if not (PRICE_RE.search(text) or FREE_RE.search(text) or DATE_ISO_RE.search(text)
                or DATE_DE_RE.search(text) or DATE_TEXT_RE.search(text)):
            continue
        link_match = re.search(r'\[([^\]]{5,160})\]\((https?://[^)]+)\)', text)
        title = link_match.group(1).strip() if link_match else re.sub(r'[#*_`>-]', '', text).strip()
        event_url = link_match.group(2) if link_match else source_url
        if len(title) < 5 or title.lower() in seen:
            continue
        seen.add(title.lower())
        events.append({
            "title": clean_text(title, max_length=200),
            "date": parse_date(text) or "",
            "time": parse_time(text),
            "price": parse_price(text),
            "category": "",
            "description": clean_text(text, max_length=400),
            "url": clean_url(event_url),
            "venue": "",
            "source_url": source_url,
        })
        if len(events) >= 60:
            break
    return events


def scrape(url: str) -> List[Dict[str, Any]]:
    html = fetch_plain(url)
    if html and not is_bot_challenge(html):
        events = extract_jsonld_events(html, url)
        if events:
            logger.info(f"Found {len(events)} events via JSON-LD (plain HTML)")
            return events
        events = extract_heuristic_events(html, url)
        if events:
            logger.info(f"Found {len(events)} events via heuristic scan (plain HTML)")
            return events
    else:
        logger.info("Plain GET returned a bot challenge or failed; escalating to CloakBrowser")

    rendered = render_with_cloakbrowser(url)
    if rendered:
        events = extract_jsonld_events(rendered, url)
        if events:
            logger.info(f"Found {len(events)} events via JSON-LD (rendered DOM)")
            return events
        events = extract_heuristic_events(rendered, url)
        if events:
            logger.info(f"Found {len(events)} events via heuristic scan (rendered DOM)")
            return events

    markdown = fetch_jina_content(url)
    if markdown:
        events = extract_jina_events(markdown, url)
        if events:
            logger.info(f"Found {len(events)} events via Jina Reader fallback")
            return events

    logger.warning(f"No events could be extracted from {url}")
    return []


def main():
    parser = argparse.ArgumentParser(description="Generic multi-strategy event scraper")
    parser.add_argument("--url", required=True, help="URL to scrape")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--price-max", type=float, default=15.0, help="Max event price")
    parser.add_argument("--date-days", type=int, default=7,
                        help="Only keep events starting within this many days from today")
    parser.add_argument("--save-html", action="store_true", help="Save a page snapshot for analysis")
    parser.add_argument("--html-output", help="Path where fetched page content should be saved")

    args = parser.parse_args()

    try:
        events = scrape(args.url)
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        events = []

    window_start, window_end = scrape_window(args.date_days)
    kept, rejected = validate_events(
        events,
        source_url=args.url,
        window_start=window_start,
        window_end=window_end,
        max_price=args.price_max,
    )
    filtered = dedupe_events(kept)
    logger.info(
        f"{len(filtered)} events kept for {window_start}..{window_end} "
        f"({rejected} rejected as unusable or out of window)"
    )

    if args.save_html:
        html_output = args.html_output or "data/html/generic.html"
        os.makedirs(os.path.dirname(html_output), exist_ok=True)
        snapshot = fetch_plain(args.url) or ""
        with open(html_output, "w", encoding="utf-8") as f:
            f.write(snapshot)

    output = {
        "source": args.url,
        "scraped_at": datetime.now().isoformat(),
        "event_count": len(filtered),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "events": filtered,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Scraped {len(filtered)} events to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
