#!/usr/bin/env python3
"""
Score, categorize and filter scraped events against a fixed preference
profile, then sort best-to-worst.

This is the deterministic reference implementation of the scoring spec Jules
is asked to (re)write in scripts/jules_event_scorer.py, and also the fallback
used when that Jules call is unavailable or fails - so the pipeline always
produces docs/events_scored.json.

Preference profile (see the "why" for each weight below):
- Price: free is best, up to 10 EUR is preferred, up to 15 EUR is the hard
  cutoff. Events with no detected price are kept (excluding them would drop
  a lot of legitimate free/community listings that just don't say "free"
  in a way our scraper can see) but scored neutrally.
- Categories: dancing, music, outside events, entrepreneurial events, social
  gatherings, theater, culture, musical, participating workshops - matched
  via keyword heuristics against title/description/category.
- Proximity to Charlottenburg: a location bonus, not a content category;
  matched via a keyword check since no geocoding is available.
"""

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

MAX_PRICE = 15.0
PREFERRED_PRICE = 10.0

# Order defines display priority when multiple categories match.
CATEGORY_KEYWORDS = {
    "dancing": ["dance", "dancing", "tanz", "ballet", "ballett", "choreograph"],
    "music": ["concert", "konzert", "music", "musik", "band", "live music", "dj set", "festival", "gig"],
    "outside events": ["outdoor", "open air", "openair", "freiluft", "garden", "biergarten", "terrace"],
    "entrepreneurial events": ["startup", "entrepreneur", "business", "networking", "pitch", "venture", "founder"],
    "social gatherings": ["meetup", "social", "gathering", "community", "mixer", "stammtisch"],
    "theater": ["theater", "theatre", "schauspiel", "bühne", "buehne", "drama"],
    "culture": ["museum", "kultur", "culture", "exhibition", "ausstellung", "gallery", "kunst", "art"],
    "musical": ["musical"],
    "participating workshops": ["workshop", "seminar", "hands-on", "kurs", "participat", "mitmach"],
}

CHARLOTTENBURG_KEYWORDS = ["charlottenburg", "schloss charlottenburg", "kurfürstendamm", "kudamm"]

MAX_MATCHED_CATEGORIES_SCORED = 3
POINTS_PER_CATEGORY = 15
PROXIMITY_BONUS = 20


def _keyword_pattern(keywords: List[str]) -> "re.Pattern":
    # Match at a leading word boundary but allow a trailing suffix, so German
    # compounds like "Tanzabend"/"Musikfestival" still match "tanz"/"musik" -
    # while a word boundary at the *start* still stops "art" from matching
    # inside "Startup" (no boundary exists between the "t" and "a" there).
    return re.compile(r'\b(?:' + '|'.join(re.escape(kw) for kw in keywords) + r')\w*', re.IGNORECASE)


_CATEGORY_PATTERNS = {name: _keyword_pattern(kws) for name, kws in CATEGORY_KEYWORDS.items()}
_CHARLOTTENBURG_PATTERN = _keyword_pattern(CHARLOTTENBURG_KEYWORDS)


def price_label(price: Optional[float]) -> str:
    if price is None:
        return "Check site"
    if price == 0:
        return "Free"
    return f"€{price:.2f}".rstrip("0").rstrip(".")


def price_score(price: Optional[float]) -> int:
    if price is None:
        return 5
    if price == 0:
        return 40
    if price <= PREFERRED_PRICE:
        return 25
    if price <= MAX_PRICE:
        return 10
    return 0


def match_categories(event: Dict[str, Any]) -> List[str]:
    haystack = " ".join(str(event.get(field, "")) for field in ("title", "description", "category"))
    matched = [name for name, pattern in _CATEGORY_PATTERNS.items() if pattern.search(haystack)]
    venue = str(event.get("venue", ""))
    if _CHARLOTTENBURG_PATTERN.search(haystack) or _CHARLOTTENBURG_PATTERN.search(venue):
        matched.append("near Charlottenburg")
    return matched


def score_event(event: Dict[str, Any]) -> Dict[str, Any]:
    price = event.get("price")
    matched = match_categories(event)
    content_categories = [c for c in matched if c != "near Charlottenburg"]
    category_pts = min(
        MAX_MATCHED_CATEGORIES_SCORED * POINTS_PER_CATEGORY,
        len(content_categories) * POINTS_PER_CATEGORY,
    )
    proximity_pts = PROXIMITY_BONUS if "near Charlottenburg" in matched else 0

    score = price_score(price) + category_pts + proximity_pts

    scored = dict(event)
    scored["price"] = price
    scored["price_label"] = price_label(price)
    scored["matched_categories"] = matched
    scored["category"] = ", ".join(content_categories) if content_categories else (event.get("category") or "general")
    scored["score"] = min(100, score)
    return scored


def score_and_filter_events(events: List[Dict[str, Any]], max_price: float = MAX_PRICE) -> List[Dict[str, Any]]:
    filtered = [e for e in events if e.get("price") is None or e.get("price", 0) <= max_price]

    seen = set()
    deduped = []
    for e in filtered:
        key = (str(e.get("title", "")).strip().lower(), str(e.get("date", "")).strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    scored = [score_event(e) for e in deduped]
    scored.sort(key=lambda e: (-e["score"], e["price"] if e["price"] is not None else 999, e["title"].lower()))
    return scored


def main():
    parser = argparse.ArgumentParser(description="Score, categorize and filter events")
    parser.add_argument("--input", required=True, help="Aggregated events JSON file (list under 'events')")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--max-price", type=float, default=MAX_PRICE, help="Hard price cutoff in EUR")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events", data if isinstance(data, list) else [])

    scored = score_and_filter_events(events, args.max_price)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"count": len(scored), "events": scored}, f, indent=2, ensure_ascii=False)

    print(f"Scored {len(scored)} events (from {len(events)} input events) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
