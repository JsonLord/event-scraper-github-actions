#!/usr/bin/env python3
"""
Score, categorize and filter scraped Berlin events against a fixed preference
profile, then sort best-to-worst.

This is the deterministic reference implementation of the scoring spec Jules
is asked to (re)write in scripts/jules_event_scorer.py, and also the fallback
used when that Jules call is unavailable or fails - so the pipeline always
produces docs/events_scored.json.

Preference profile:
- Price: free is best, up to 10 EUR is preferred, up to 15 EUR is the hard
  cutoff. An undetected price scores *neutrally*, between the preferred and
  cutoff bands. It used to score 5 against 40 for free, which mattered
  enormously because two thirds of real listings never state a price in a
  form the scrapers can see: every genuine Berlin event carried a 35-point
  penalty, while any scraper that defaulted an unknown price to 0 sent its
  rows - placeholders included - straight to the top of the page.
- Categories: dancing, music, outside events, entrepreneurial events, social
  gatherings, theater, culture, musical, participating workshops. Credit has
  diminishing returns per additional category, because matching *more*
  categories signals a noisy description rather than a better event; flat
  per-category points ranked concatenated listing chrome above clean rows.
- Soon is better than later: an event this weekend beats one next week.
- Completeness: a row missing its link, venue or description is worth less
  than a complete one, so thin rows sink instead of floating on a lucky
  category match.
- Proximity to Charlottenburg: a location bonus, not a content category;
  matched via keywords against the venue and text.
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from event_utils import dedupe_events, format_price_label  # noqa: E402

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

CHARLOTTENBURG_KEYWORDS = [
    "charlottenburg", "schloss charlottenburg", "kurfürstendamm", "kurfuerstendamm",
    "kudamm", "savignyplatz", "wilmersdorf", "halensee", "westend",
]

# Diminishing credit: the strongest match is worth most, each further match
# much less. A description that matches four categories is almost always
# repeated listing chrome, not an unusually rich event.
CATEGORY_POINTS = (20, 8, 3)
# A keyword found only in a long blurb is far weaker evidence than one in the
# title or venue. Weighting them equally let a row whose description happened
# to contain "Theater Musiktheater Tanz Performance Musical" outscore a
# cleanly titled concert - which is exactly how berlin-buehnen's listing
# chrome reached the top of the table.
SECONDARY_CATEGORY_POINTS = (6, 2)
PROXIMITY_BONUS = 20

PRICE_FREE_POINTS = 40
PRICE_PREFERRED_POINTS = 30
PRICE_UNKNOWN_POINTS = 24
PRICE_CUTOFF_POINTS = 18

# Soonness, keyed by whole days between today and the event.
IMMINENCE_BANDS = ((1, 18), (3, 14), (7, 8))
IMMINENCE_DEFAULT = 2

COMPLETENESS_PENALTIES = {
    "has_detail_link": -12,
    "venue": -6,
    "description": -4,
    "time": -3,
}


def _keyword_pattern(keywords: List[str]) -> "re.Pattern":
    # Match at a leading word boundary but allow a trailing suffix, so German
    # compounds like "Tanzabend"/"Musikfestival" still match "tanz"/"musik" -
    # while a word boundary at the *start* still stops "art" from matching
    # inside "Startup" (no boundary exists between the "t" and "a" there).
    return re.compile(r'\b(?:' + '|'.join(re.escape(kw) for kw in keywords) + r')\w*', re.IGNORECASE)


_CATEGORY_PATTERNS = {name: _keyword_pattern(kws) for name, kws in CATEGORY_KEYWORDS.items()}
_CHARLOTTENBURG_PATTERN = _keyword_pattern(CHARLOTTENBURG_KEYWORDS)


def price_label(price: Optional[float]) -> str:
    """Kept as a thin alias so existing callers and tests keep working."""
    return format_price_label(price)


def price_score(price: Optional[float]) -> int:
    if price is None:
        return PRICE_UNKNOWN_POINTS
    if price <= 0:
        return PRICE_FREE_POINTS
    if price <= PREFERRED_PRICE:
        return PRICE_PREFERRED_POINTS
    if price <= MAX_PRICE:
        return PRICE_CUTOFF_POINTS
    return 0


def split_categories(event: Dict[str, Any]) -> "tuple[List[str], List[str], bool]":
    """Split matches into (title/venue matches, description-only matches, near).

    Title and venue matches describe what the event *is*; a keyword buried in
    a blurb only hints at it. Keeping them apart lets the ranking weight them
    differently.
    """
    title_text = " ".join(str(event.get(f, "")) for f in ("title", "category", "venue"))
    body_text = str(event.get("description", ""))

    primary, secondary = [], []
    for name, pattern in _CATEGORY_PATTERNS.items():
        if pattern.search(title_text):
            primary.append(name)
        elif pattern.search(body_text):
            secondary.append(name)

    near = bool(_CHARLOTTENBURG_PATTERN.search(f"{title_text} {body_text}"))
    return primary, secondary, near


def match_categories(event: Dict[str, Any]) -> List[str]:
    """Categories the event matches, most title-relevant first."""
    primary, secondary, near = split_categories(event)
    matched = primary + secondary
    if near:
        matched.append("near Charlottenburg")
    return matched


def imminence_score(event_date: Optional[str], today: Optional[date] = None) -> int:
    """Points for how soon the event is; distant events sink.

    The previous model ignored dates entirely, so a listing mis-dated two
    years out ranked identically to one happening tonight.
    """
    if not event_date:
        return 0
    try:
        parsed = date.fromisoformat(event_date)
    except (ValueError, TypeError):
        return 0
    days_out = (parsed - (today or date.today())).days
    if days_out < 0:
        return 0
    for limit, points in IMMINENCE_BANDS:
        if days_out <= limit:
            return points
    return IMMINENCE_DEFAULT


def completeness_score(event: Dict[str, Any]) -> int:
    """Negative points for fields the scrape could not fill.

    Keeps thin rows - no deep link, no venue - below complete ones instead of
    letting them tie on a category match alone.
    """
    penalty = 0
    for field, points in COMPLETENESS_PENALTIES.items():
        if not event.get(field):
            penalty += points
    return penalty


def category_score(primary: List[str], secondary: List[str]) -> int:
    """Diminishing credit, with description-only matches worth much less."""
    return (
        sum(points for points, _ in zip(CATEGORY_POINTS, primary))
        + sum(points for points, _ in zip(SECONDARY_CATEGORY_POINTS, secondary))
    )


def score_event(event: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    price = event.get("price")
    primary, secondary, near = split_categories(event)
    content_categories = primary + secondary
    matched = content_categories + (["near Charlottenburg"] if near else [])
    proximity_pts = PROXIMITY_BONUS if near else 0

    score = (
        price_score(price)
        + category_score(primary, secondary)
        + proximity_pts
        + imminence_score(event.get("date"), today)
        + completeness_score(event)
    )

    scored = dict(event)
    scored["price"] = price
    scored["price_label"] = format_price_label(price)
    scored["matched_categories"] = matched
    scored["category"] = ", ".join(content_categories) if content_categories else (event.get("category") or "general")
    scored["score"] = max(0, min(100, score))
    return scored


def score_and_filter_events(
    events: List[Dict[str, Any]],
    max_price: float = MAX_PRICE,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    filtered = [e for e in events if e.get("price") is None or e.get("price", 0) <= max_price]
    deduped = dedupe_events(filtered)
    scored = [score_event(e, today) for e in deduped]
    scored.sort(
        key=lambda e: (
            -e["score"],
            e.get("date") or "9999-12-31",
            e.get("time") or "99:99",
            str(e.get("title", "")).lower(),
        )
    )
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

    payload = {
        "count": len(scored),
        "generated_at": date.today().isoformat(),
        "events": scored,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Scored {len(scored)} events (from {len(events)} input events) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
