#!/usr/bin/env python3
"""
Compare fetch strategies against sites the plain scraper cannot reach.

Some sources sit behind an anti-bot layer: a Cloudflare managed challenge
(berlin-buehnen.de), a captcha interstitial (venturecafeberlin.org), or an
outright refusal of datacenter IPs (Eventbrite answers a hosted runner with
HTTP 405). For those, *how* the page is fetched decides whether there is
anything to extract at all.

This probe runs every strategy against every target and reports how many
events each actually yields - not how many bytes it returned, which is the
misleading measure: Jina's default markdown rendering of berlin-buehnen.de
comes back 21k and extracts nothing, while asking the same endpoint for HTML
comes back 220k and extracts 31 events.

It exists to be run in CI rather than locally, because the answer is
IP-dependent: a hosted runner and a developer machine get different responses
from exactly these sites. Run it, read the table, then wire the winner into
generic_event_scraper.py and stop paying for the rest.
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests  # noqa: E402

import generic_event_scraper as g  # noqa: E402
from event_utils import (  # noqa: E402
    dedupe_events,
    scrape_window,
    validate_events,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

JINA_ENDPOINT = "https://r.jina.ai/"

# Each strategy returns (body, is_html). Markdown bodies go through the line
# scanner; HTML bodies go through the full five-strategy document extractor,
# which is the whole reason asking Jina for HTML beats its default rendering.
JINA_VARIANTS: Dict[str, Dict[str, str]] = {
    "jina_markdown": {},
    "jina_html": {"X-Return-Format": "html"},
    "jina_html_nocache": {"X-Return-Format": "html", "X-No-Cache": "true"},
    "jina_html_browser": {"X-Return-Format": "html", "X-Engine": "browser"},
    "jina_html_proxy": {"X-Return-Format": "html", "X-Proxy": "auto"},
}


def fetch_direct(url: str, timeout: int) -> Tuple[Optional[str], bool]:
    """Tier 1 today: a plain browser-shaped GET."""
    return g.fetch_plain(url, timeout=timeout), True


def fetch_cloakbrowser(url: str, timeout: int) -> Tuple[Optional[str], bool]:
    """Tier 2 today: stealth headless Chromium."""
    return g.render_with_cloakbrowser(url), True


def make_jina_fetcher(extra_headers: Dict[str, str]) -> Callable[[str, int], Tuple[Optional[str], bool]]:
    is_html = extra_headers.get("X-Return-Format") == "html"

    def fetch(url: str, timeout: int) -> Tuple[Optional[str], bool]:
        api_key = os.environ.get("JINA_API_KEY")
        if not api_key:
            raise RuntimeError("JINA_API_KEY not set")
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "text/plain"}
        headers.update(extra_headers)
        response = requests.get(JINA_ENDPOINT + url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text, is_html

    return fetch


def build_strategies(names: Optional[List[str]] = None) -> Dict[str, Callable]:
    strategies: Dict[str, Callable] = {
        "direct": fetch_direct,
        "cloakbrowser": fetch_cloakbrowser,
    }
    for name, headers in JINA_VARIANTS.items():
        strategies[name] = make_jina_fetcher(headers)
    if names:
        missing = [n for n in names if n not in strategies]
        if missing:
            raise SystemExit(f"Unknown strategies: {', '.join(missing)}")
        strategies = {n: strategies[n] for n in names}
    return strategies


def events_from(body: str, url: str, is_html: bool, date_days: int,
                max_price: float) -> Tuple[int, int, int]:
    """(raw rows, kept in window, kept in 30 days) for one fetched body."""
    rows = (g.scrape_document(body, url, "probe") if is_html
            else g.extract_jina_events(body, url))

    def kept(days: int) -> int:
        window_start, window_end = scrape_window(days)
        keep, _ = validate_events(rows, source_url=url, window_start=window_start,
                                  window_end=window_end, max_price=max_price)
        return len(dedupe_events(keep))

    return len(rows), kept(date_days), kept(30)


def probe_one(name: str, url: str, strategy: str, fetch: Callable,
              date_days: int, max_price: float, timeout: int) -> Dict[str, Any]:
    result: Dict[str, Any] = {"site": name, "url": url, "strategy": strategy}
    started = time.time()
    try:
        body, is_html = fetch(url, timeout)
    except Exception as exc:  # noqa: BLE001 - a failing strategy is a result
        result.update(error=str(exc)[:80], bytes=0, raw=0, kept=0, kept30=0)
        result["seconds"] = round(time.time() - started, 1)
        return result

    if not body:
        result.update(error="no body", bytes=0, raw=0, kept=0, kept30=0)
        result["seconds"] = round(time.time() - started, 1)
        return result

    result["bytes"] = len(body)
    result["challenge"] = g.is_bot_challenge(body)
    try:
        raw, kept, kept30 = events_from(body, url, is_html, date_days, max_price)
        result.update(raw=raw, kept=kept, kept30=kept30, error="")
    except Exception as exc:  # noqa: BLE001
        result.update(raw=0, kept=0, kept30=0, error=f"extract: {str(exc)[:60]}")
    result["seconds"] = round(time.time() - started, 1)
    return result


def render_table(results: List[Dict[str, Any]]) -> str:
    lines = [f"{'site':22} {'strategy':18} {'bytes':>9} {'raw':>5} "
             f"{'kept':>5} {'k30':>5} {'secs':>6}  note"]
    for row in results:
        note = row.get("error") or ("CHALLENGE" if row.get("challenge") else "")
        lines.append(
            f"{row['site'][:22]:22} {row['strategy']:18} {row.get('bytes', 0):9} "
            f"{row.get('raw', 0):5} {row.get('kept', 0):5} {row.get('kept30', 0):5} "
            f"{row.get('seconds', 0):6}  {note}"
        )
    return "\n".join(lines)


def summarise(results: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Winner per site, and the strategy that wins most often overall."""
    by_site: Dict[str, List[Dict[str, Any]]] = {}
    for row in results:
        by_site.setdefault(row["site"], []).append(row)

    lines, winners, totals = ["", "Winner per site (most events kept in window):"], {}, {}
    for site, rows in by_site.items():
        best = max(rows, key=lambda r: (r.get("kept", 0), r.get("kept30", 0), -r.get("seconds", 0)))
        if best.get("kept", 0) == 0 and best.get("kept30", 0) == 0:
            lines.append(f"  {site:22} - nothing reached it")
            winners[site] = None
            continue
        winners[site] = best["strategy"]
        totals[best["strategy"]] = totals.get(best["strategy"], 0) + 1
        lines.append(f"  {site:22} {best['strategy']:18} "
                     f"{best.get('kept', 0)} kept ({best.get('kept30', 0)} in 30d)")

    for strategy in sorted({r["strategy"] for r in results}):
        rows = [r for r in results if r["strategy"] == strategy]
        lines.append(f"  total kept via {strategy:18} "
                     f"{sum(r.get('kept', 0) for r in rows):4}  "
                     f"(sites won: {totals.get(strategy, 0)})")
    return "\n".join(lines), winners


def main():
    parser = argparse.ArgumentParser(description="Compare fetch strategies per site")
    parser.add_argument("--sites", required=True,
                        help='JSON file or inline JSON of {"name": "url"}')
    parser.add_argument("--strategies", help="Comma-separated subset to run")
    parser.add_argument("--output", help="Write full results as JSON here")
    parser.add_argument("--date-days", type=int, default=7)
    parser.add_argument("--price-max", type=float, default=20.0)
    parser.add_argument("--timeout", type=int, default=120)

    args = parser.parse_args()

    raw_sites = args.sites
    if os.path.exists(raw_sites):
        with open(raw_sites, encoding="utf-8") as handle:
            sites = json.load(handle)
    else:
        sites = json.loads(raw_sites)

    names = [s.strip() for s in args.strategies.split(",")] if args.strategies else None
    strategies = build_strategies(names)

    if "JINA_API_KEY" not in os.environ:
        logger.warning("JINA_API_KEY is not set - every jina_* strategy will report an error. "
                       "Add it as a repository secret to compare them.")

    results = []
    for name, url in sites.items():
        for strategy, fetch in strategies.items():
            row = probe_one(name, url, strategy, fetch,
                            args.date_days, args.price_max, args.timeout)
            results.append(row)
            logger.info(f"{name} / {strategy}: {row.get('kept', 0)} kept "
                        f"({row.get('error') or 'ok'})")

    table = render_table(results)
    summary, winners = summarise(results)
    print()
    print(table)
    print(summary)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump({"results": results, "winners": winners}, handle,
                      indent=2, ensure_ascii=False)
        print(f"\nFull results -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
