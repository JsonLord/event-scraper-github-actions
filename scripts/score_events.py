#!/usr/bin/env python3
"""
Score, categorize and filter scraped Berlin events against a fixed preference
profile, then order them by day and, within each day, from free to dearest.

This is the deterministic reference implementation of the scoring spec Jules
is asked to (re)write in scripts/jules_event_scorer.py, and also the fallback
used when that Jules call is unavailable or fails - so the pipeline always
produces docs/events_scored.json.

Preference profile:
- Price: free is best, up to 10 EUR is preferred, up to 20 EUR is the hard
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

from event_utils import (  # noqa: E402
    DEFAULT_MAX_PRICE,
    day_sort_key,
    dedupe_events,
    format_price_label,
)

MAX_PRICE = DEFAULT_MAX_PRICE
PREFERRED_PRICE = 10.0
# Between the preferred band and the hard cutoff, so a mid-priced ticket
# still ranks below a cheap one without being treated as unaffordable.
MID_PRICE = 15.0

# Order defines display priority when multiple categories match.
CATEGORY_KEYWORDS = {
    "dancing": ["dance", "dancing", "tanz", "ballet", "ballett", "choreograph"],
    "music": ["concert", "konzert", "music", "musik", "band", "live music", "dj set", "festival", "gig",
              "techno", "house", "rave", "club night", "dj"],
    "outside events": ["outdoor", "open air", "openair", "freiluft", "garten", "garden", "biergarten",
                       "terrace", "picknick", "picnic"],
    # "business" on its own routed a comedy show called "Bad 4 Business" into
    # the networking table; the multi-word forms carry the actual intent.
    "entrepreneurial events": ["startup", "entrepreneur", "networking", "pitch night", "venture",
                               "founder", "coworking", "gründer", "gruender", "investor",
                               "demo day", "business networking", "business breakfast",
                               "business brunch", "freelancer"],
    "social gatherings": ["meetup", "social", "gathering", "community", "mixer", "stammtisch"],
    "theater": ["theater", "theatre", "schauspiel", "bühne", "buehne", "drama", "improv", "kabarett"],
    "culture": ["museum", "kultur", "culture", "exhibition", "ausstellung", "gallery", "kunst", "art"],
    "musical": ["musical"],
    "participating workshops": ["workshop", "seminar", "hands-on", "kurs", "participat", "mitmach", "class"],
    # Free guided tours are a category in their own right; see TOUR_FREE_WEIGHT.
    "guided tours": ["führung", "fuehrung", "guided tour", "rundgang", "kiezspaziergang", "stadtführung"],
    # Sport gets its own table, so it needs its own category to route on.
    "sport": ["running", "run club", "lauf", "jogging", "cycling", "radfahren", "bike ride", "yoga",
              "fitness", "bouldern", "climbing", "klettern", "swimming", "schwimmen", "marathon",
              "wandern", "hiking", "skate", "volleyball", "basketball", "football", "fußball",
              "tennis", "workout", "calisthenics", "pilates", "sport"],
}

# Confirmed preference order: dancing 20 > music 18 > culture 12, with
# workshops and free guided tours at 15. The unmarked weights are estimates.
CATEGORY_WEIGHTS = {
    "dancing": 20,                  # confirmed
    "music": 18,                    # confirmed
    "outside events": 16,           # estimate
    "participating workshops": 15,  # confirmed
    "guided tours": 15,             # confirmed, when free
    "social gatherings": 14,        # estimate
    "theater": 14,                  # estimate
    "sport": 14,                    # estimate
    "culture": 12,                  # confirmed
    "musical": 10,                  # estimate
    "entrepreneurial events": 10,   # estimate
}
# A guided tour is worth its full weight when free; a paid one much less.
TOUR_PAID_WEIGHT = 6

CHARLOTTENBURG_KEYWORDS = [
    "charlottenburg", "schloss charlottenburg", "kurfürstendamm", "kurfuerstendamm",
    "kudamm", "savignyplatz", "wilmersdorf", "halensee", "westend",
]

# Diminishing credit on *additional* categories: the strongest match carries
# its own weight, each further match a fraction of its weight. A description
# matching four categories is usually repeated listing chrome, not a richer
# event.
CATEGORY_FALLOFF = (1.0, 0.4, 0.15)
# A keyword found only in a long blurb is far weaker evidence than one in the
# title or venue. Weighting them equally let a row whose description happened
# to contain "Theater Musiktheater Tanz Performance Musical" outscore a
# cleanly titled concert - which is exactly how berlin-buehnen's listing
# chrome reached the top of the table.
# A keyword found only in a long blurb is far weaker evidence than one in the
# title or venue, so a description-only match earns a fraction of its weight.
SECONDARY_CATEGORY_SHARE = 0.35
# Cut from 20: at that size a free event merely near Charlottenburg outranked
# events that actually matched the preference, and it rated much too high.
PROXIMITY_BONUS = 8

PRICE_FREE_POINTS = 40
PRICE_PREFERRED_POINTS = 30
PRICE_UNKNOWN_POINTS = 24
PRICE_MID_POINTS = 18
PRICE_CUTOFF_POINTS = 12

# "Weekend evenings are the sweet spot": Friday to Sunday, starting after
# work. A weekday morning slot is actively worse than no signal at all.
WEEKEND_BONUS = 10
EVENING_BONUS = 12
MORNING_PENALTY = -8
EVENING_FROM_HOUR = 18
MORNING_BEFORE_HOUR = 12

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
    if price <= MID_PRICE:
        return PRICE_MID_POINTS
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
    """Categories the event matches, strongest and most title-relevant first."""
    primary, secondary, near = split_categories(event)
    price = event.get("price")
    primary = sorted(primary, key=lambda c: -category_weight(c, price))
    secondary = sorted(secondary, key=lambda c: -category_weight(c, price))
    matched = primary + secondary
    if near:
        matched.append("near Charlottenburg")
    return matched


# --------------------------------------------------------------------------
# Participation: the axis that actually separates a good evening from a bad one
# --------------------------------------------------------------------------
#
# Calibration against 23 real events showed category alone cannot express the
# preference. An opera *festival* and an opera *performance* score identically
# on category, yet one was rated right and the other much too high; a ballet
# *opening festival* was the only event rated too LOW. The distinction is
# whether you do something with other people or sit and watch - "social
# gathering, but with something happening".
#
# So passive consumption is penalised rather than participation being rewarded:
# that keeps dancing and festivals, which were already rated correctly, exactly
# where they are instead of inflating them further.

SPECTATOR_STRONG = [
    "lesung", "reading", "vortrag", "lecture", "screening", "vorstellung",
    "matinee", "revue", "show", "brunch", "konzertant", "podiumsdiskussion",
    "ausstellungseröffnung", "vernissage", "gala",
]
SPECTATOR_MILD = [
    "führung", "fuehrung", "guided tour", "rundgang", "stadtführung",
    "ausstellung", "exhibition", "museum",
]
# Political actions are not what "meeting people" means here.
NON_SOCIAL = ["protest", "demonstration", "kundgebung", "mahnwache", "vigil"]

# Comedy and stand-up are watched, not joined. Free or nearly free they are a
# cheap way to be out among people; at full price they rated very low.
COMEDY = ["comedy", "stand-up", "standup", "improv", "kleinkunst", "open mic"]
COMEDY_FREE_LIMIT = 5.0

# The positive half of the axis: a festival, an opening or a party is people
# gathered with something happening, which is the whole preference. The one
# event rated too LOW in calibration was a ballet *opening festival*.
# No bare "fest": keyword matching allows a trailing suffix, so it fired on
# the venue "Festsaal Kreuzberg" and handed a social bonus to every event in
# the building. The compounds that really mean a festival are listed instead.
SOCIAL_ACTIVE = [
    "festival", "sommerfest", "stadtfest", "hoffest", "straßenfest", "strassenfest",
    "eröffnungsfest", "eroeffnungsfest", "fest im", "eröffnung", "eroeffnung",
    "opening", "party", "jam", "meetup", "mixer", "mingle", "speed friending",
    "speed dating", "stammtisch", "kennenlernen", "tandem", "quiz", "karaoke",
    "open decks", "get-together",
]
SOCIAL_ACTIVE_BONUS = 12

SPECTATOR_STRONG_PENALTY = -26
SPECTATOR_MILD_PENALTY = -12
NON_SOCIAL_PENALTY = -22
COMEDY_PAID_PENALTY = -24

_SPECTATOR_STRONG_PATTERN = _keyword_pattern(SPECTATOR_STRONG)
_SPECTATOR_MILD_PATTERN = _keyword_pattern(SPECTATOR_MILD)
_NON_SOCIAL_PATTERN = _keyword_pattern(NON_SOCIAL)
_COMEDY_PATTERN = _keyword_pattern(COMEDY)
_SOCIAL_ACTIVE_PATTERN = _keyword_pattern(SOCIAL_ACTIVE)


def participation_score(event: Dict[str, Any]) -> int:
    """Net points for taking part rather than watching.

    Positive for a gathering with something happening, negative for something
    you sit and watch. This is the axis category alone could not express.
    """
    haystack = " ".join(
        str(event.get(f, "")) for f in ("title", "venue", "category", "description")
    )
    penalty = 0
    if _SOCIAL_ACTIVE_PATTERN.search(haystack):
        penalty += SOCIAL_ACTIVE_BONUS
    if _COMEDY_PATTERN.search(haystack):
        price = event.get("price")
        if price is not None and price > COMEDY_FREE_LIMIT:
            penalty += COMEDY_PAID_PENALTY
    elif _SPECTATOR_STRONG_PATTERN.search(haystack):
        penalty += SPECTATOR_STRONG_PENALTY
    elif _SPECTATOR_MILD_PATTERN.search(haystack):
        penalty += SPECTATOR_MILD_PENALTY
    if _NON_SOCIAL_PATTERN.search(haystack):
        penalty += NON_SOCIAL_PENALTY
    return penalty


# --------------------------------------------------------------------------
# Hard exclusions
# --------------------------------------------------------------------------
#
# Some things are not "rank them lower", they are "do not show me these":
# children's programming, film screenings, and retail or brand promotions.
# Excluding beats a large penalty because a demoted event still occupies a row.

EXCLUDE_KIDS = ["kinder", "kids", "familienprogramm", "jugendliche", "children",
                "kinderprogramm", "familienführung"]
EXCLUDE_FILM = ["film", "kino", "cinema", "screening", "filmfest", "omeu", "omdu",
                "freiluftkino", "arthouse", "dokumentarfilm"]
EXCLUDE_RETAIL = ["sale", "outlet", "rabatt", "flagship", "store", "open day",
                  "semesterbeginn", "sommerglück", "sommerglueck", "shopping"]
# "not suitable for children under 12" is an ADULT signal that a plain keyword
# read as family programming.
NOT_KIDS_RE = re.compile(
    r"\b(?:not suitable for children|nicht (?:geeignet )?f(?:ü|ue)r kinder|no children|"
    r"ab 18|18\+|adults only|nur f(?:ü|ue)r erwachsene|keine kinder)", re.IGNORECASE
)

EXCLUSIONS = {
    "kids": _keyword_pattern(EXCLUDE_KIDS),
    "film": _keyword_pattern(EXCLUDE_FILM),
    "retail": _keyword_pattern(EXCLUDE_RETAIL),
}


EXCLUDED_COUNTS: Dict[str, int] = {}


def exclusion_reason(event: Dict[str, Any]) -> Optional[str]:
    """Why this event should not be shown at all, or None to keep it."""
    haystack = " ".join(
        str(event.get(f, "")) for f in ("title", "venue", "category", "description")
    )
    for name, pattern in EXCLUSIONS.items():
        if not pattern.search(haystack):
            continue
        if name == "kids" and NOT_KIDS_RE.search(haystack):
            continue  # an explicitly adults-only event, not family programming
        return name
    return None


# The page renders one table per stream, because a running club and an opera
# are not alternatives to each other - putting them in one ranked list forces
# a comparison that is never useful.
STREAMS = ("sport", "network", "main")


def event_stream(primary: List[str], secondary: List[str]) -> str:
    """Route an event to its table.

    A title match wins over a description-only one, so a dance class whose
    blurb happens to say "workout" stays in the main table rather than being
    filed under sport.
    """
    if "sport" in primary:
        # A dance event that also mentions sport is dancing first: dancing is
        # the strongest stated preference, sport is a separate interest.
        if "dancing" in primary:
            return "main"
        return "sport"
    if "entrepreneurial events" in primary:
        return "network"
    if "sport" in secondary and not primary:
        return "sport"
    if "entrepreneurial events" in secondary and not primary:
        return "network"
    return "main"


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


def timing_score(event: Dict[str, Any]) -> int:
    """Weekend and evening bonus, morning penalty."""
    points = 0
    try:
        when = date.fromisoformat(event.get("date") or "")
    except (ValueError, TypeError):
        when = None
    if when and when.weekday() >= 4:  # Friday, Saturday, Sunday
        points += WEEKEND_BONUS
    start = str(event.get("time") or "")
    if len(start) >= 2 and start[:2].isdigit():
        hour = int(start[:2])
        if hour >= EVENING_FROM_HOUR:
            points += EVENING_BONUS
        elif hour < MORNING_BEFORE_HOUR:
            points += MORNING_PENALTY
    return points


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


def category_weight(name: str, price: Optional[float]) -> int:
    """Weight for one category, discounting a guided tour that is not free."""
    weight = CATEGORY_WEIGHTS.get(name, 10)
    if name == "guided tours" and price not in (None, 0):
        return TOUR_PAID_WEIGHT
    return weight


def category_score(primary: List[str], secondary: List[str],
                   price: Optional[float] = None) -> int:
    """Weighted credit, strongest category first and each further one less."""
    ranked = sorted((category_weight(c, price) for c in primary), reverse=True)
    score = sum(w * f for w, f in zip(ranked, CATEGORY_FALLOFF))
    ranked_secondary = sorted((category_weight(c, price) for c in secondary), reverse=True)
    score += SECONDARY_CATEGORY_SHARE * sum(
        w * f for w, f in zip(ranked_secondary, CATEGORY_FALLOFF)
    )
    return round(score)


def score_event(event: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    price = event.get("price")
    primary, secondary, near = split_categories(event)
    content_categories = primary + secondary
    matched = content_categories + (["near Charlottenburg"] if near else [])
    proximity_pts = PROXIMITY_BONUS if near else 0

    score = (
        price_score(price)
        + category_score(primary, secondary, price)
        + proximity_pts
        + imminence_score(event.get("date"), today)
        + completeness_score(event)
        + participation_score(event)
        + timing_score(event)
    )

    scored = dict(event)
    scored["stream"] = event_stream(primary, secondary)
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
    # Exclusions are applied after de-duplication so the reported counts match
    # what a reader would otherwise have seen.
    kept = []
    for event in deduped:
        reason = exclusion_reason(event)
        if reason:
            EXCLUDED_COUNTS[reason] = EXCLUDED_COUNTS.get(reason, 0) + 1
            continue
        kept.append(event)
    deduped = kept
    scored = [score_event(e, today) for e in deduped]
    # Day-grouped: earliest date first, and within each day free events first
    # then ascending by price. The rating stays on every row and remains
    # sortable in the page, but it no longer decides the reading order.
    scored.sort(key=day_sort_key)
    return scored


def main():
    parser = argparse.ArgumentParser(description="Score, categorize and filter events")
    parser.add_argument("--input", required=True, help="Aggregated events JSON file (list under 'events')")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--max-price", type=float, default=MAX_PRICE,
                        help=f"Hard price cutoff in EUR (default {MAX_PRICE:g})")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events", data if isinstance(data, list) else [])

    scored = score_and_filter_events(events, args.max_price)

    counts = {name: sum(1 for e in scored if e.get("stream") == name) for name in STREAMS}
    payload = {
        "count": len(scored),
        "generated_at": date.today().isoformat(),
        "stream_counts": counts,
        "events": scored,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Scored {len(scored)} events (from {len(events)} input events) to {args.output}")
    for name in STREAMS:
        print(f"  {counts[name]:4d}  {name}")
    # Never drop rows silently: an exclusion rule that starts over-matching is
    # only visible if the run says how much it removed.
    for reason, n in sorted(EXCLUDED_COUNTS.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  excluded ({reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
