#!/usr/bin/env python3
"""Community editorial selection, deliberately separate from personal ranking.

``scripts/score_events.py`` answers "which of these would *this one person*
like?", with Charlottenburg proximity, a favourite-source bonus and a
spectator penalty. A community shortlist is a different question: which
events would a broad Berlin audience find worth leaving the house for? Reusing
that scoring would import one person's preferences into a public page, so the
two policies live apart and share only the normalisation layer.

The policy, in order:

  * price first - free beats donation beats cheap; above EUR 15 is excluded
  * verifiability next - an unverified row cannot be published, so it ranks
    below anything already confirmed
  * then editorial quality signals that are true of the listing itself:
    a real event page, a stated time, a named venue, a description
  * then variety - each pick makes its category and district less valuable
    for the next one, so a shortlist cannot be ten techno nights in
    Friedrichshain

The output is at most ``COMMUNITY_TARGET_MAX`` events, and fewer when supply
is thin: the target is a ceiling, never a quota to pad towards.
"""

from __future__ import annotations

import os
import re
import sys

# Sibling modules are imported flat ("from community_common import ..."),
# matching the rest of scripts/, so the directory has to be on the path even
# when this file is imported as part of the package (tests, tooling).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Any, Dict, Iterable, List, Optional, Tuple

from community_common import (
    COMMUNITY_MAX_PRICE,
    COMMUNITY_TARGET_MAX,
    COMMUNITY_TARGET_MIN,
    DEFAULT_CATEGORY,
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_DONATION,
    PRICE_STATUS_NEEDS_VERIFICATION,
    PRICE_STATUS_UNKNOWN,
    SELECTION_PROPOSED,
    VERIFICATION_MATCHED,
    VERIFICATION_REJECTED,
    VERIFICATION_UNCONFIRMED,
    category_label,
    classify_category,
    district_from_text,
    price_priority,
)


# --------------------------------------------------------------------------
# Price
# --------------------------------------------------------------------------

PRICE_BASE = {
    PRICE_STATUS_CONFIRMED_FREE: 45,
    PRICE_STATUS_DONATION: 40,
    PRICE_STATUS_CONFIRMED_PAID: 30,
    PRICE_STATUS_UNKNOWN: 10,
    PRICE_STATUS_NEEDS_VERIFICATION: 5,
}


def price_points(price_status: str, price: Optional[float],
                 max_price: float = COMMUNITY_MAX_PRICE) -> int:
    """Ranking points for the price band, and the affordability veto.

    A confirmed price above the cap returns a large negative number rather
    than a low score: "expensive" and "disallowed" are different things, and
    the caller checks ``is_eligible`` rather than trusting a ranking number.
    """
    if price_status == PRICE_STATUS_CONFIRMED_PAID:
        if price is None:
            return 0
        if price > max_price:
            return -1000
        # Cheaper within the band is better, but only mildly: the difference
        # between EUR 3 and EUR 12 should not outweigh an extra category.
        return PRICE_BASE[price_status] - int(min(float(price), max_price))
    return PRICE_BASE.get(price_status, 0)


def is_eligible(price_status: str, price: Optional[float],
                max_price: float = COMMUNITY_MAX_PRICE) -> bool:
    """True when the price does not by itself disqualify the event.

    Unknown and needs-verification prices stay eligible for *selection* -
    they go into the shortlist to be resolved - but they are not eligible for
    *publication*, which ``community_publish.publication_problems`` enforces.
    """
    if price_status == PRICE_STATUS_CONFIRMED_PAID:
        return price is not None and 0 < float(price) <= max_price
    if price_status == PRICE_STATUS_CONFIRMED_FREE:
        return True
    if price_status in (PRICE_STATUS_DONATION, PRICE_STATUS_UNKNOWN,
                        PRICE_STATUS_NEEDS_VERIFICATION):
        # Nothing about the price rules these out at selection time.
        return True
    return False


# --------------------------------------------------------------------------
# Editorial quality
# --------------------------------------------------------------------------

SPECIFIC_HINTS = re.compile(
    r"\b(?:live|konzert|concert|ausstellung|exhibition|workshop|party|festival|"
    r"führung|fuehrung|tour|performance|screening|lesung|reading|jam|session|"
    r"meetup|markt|market|open\s+air|tanz|dance|theater|theatre|show)\b",
    re.IGNORECASE,
)

# Titles that describe a listing's furniture rather than an experience.
VAGUE_TITLE_RE = re.compile(
    r"^\s*(?:programm|program|kalender|calendar|veranstaltungen|events|"
    r"spielplan|übersicht|uebersicht|newsletter|aktuelles|details?)\s*$",
    re.IGNORECASE,
)


def quality_points(event: Dict[str, Any]) -> int:
    """How complete and specific the listing itself is.

    These are facts about the row, not claims about popularity: a title with a
    named act reads better than "Sommerfest", and an event with its own page
    can be checked by a reader. Nothing here guesses at attendance.
    """
    points = 0
    title = str(event.get("title") or "")
    if event.get("has_detail_link"):
        points += 12
    if event.get("time"):
        points += 6
    if event.get("venue"):
        points += 6
    description = str(event.get("description") or "")
    if len(description) >= 80:
        points += 6
    elif len(description) >= 30:
        points += 3
    if event.get("image_url"):
        points += 4
    if SPECIFIC_HINTS.search(title):
        points += 8
    if VAGUE_TITLE_RE.match(title):
        points -= 20
    if len(title) < 6:
        points -= 6
    return points


def verification_points(event: Dict[str, Any]) -> int:
    """Points for being independently confirmed against its official page."""
    verification = event.get("verification") or {}
    status = verification.get("status")
    if status == VERIFICATION_MATCHED:
        return 20
    if status == VERIFICATION_REJECTED:
        return -1000
    return 0


# --------------------------------------------------------------------------
# Diversity
# --------------------------------------------------------------------------

CATEGORY_REPEAT_PENALTY = 9
DISTRICT_REPEAT_PENALTY = 4
DAY_SATURATION_PENALTY = 3


def _diversity_penalty(event: Dict[str, Any], chosen: List[Dict[str, Any]]) -> int:
    """What picking this event would cost in variety, given what is picked."""
    penalty = 0
    category = event.get("category") or DEFAULT_CATEGORY
    district = event.get("district")
    same_category = sum(1 for e in chosen if (e.get("category") or DEFAULT_CATEGORY) == category)
    penalty += CATEGORY_REPEAT_PENALTY * same_category
    if district:
        same_district = sum(1 for e in chosen if e.get("district") == district)
        penalty += DISTRICT_REPEAT_PENALTY * same_district
    day = event.get("date")
    if day:
        same_day = sum(1 for e in chosen if e.get("date") == day)
        penalty += DAY_SATURATION_PENALTY * max(0, same_day - 3)
    return penalty


def selection_score(event: Dict[str, Any], chosen: Optional[List[Dict[str, Any]]] = None) -> int:
    """One ranking number for an event, in the context of what is picked.

    The floor is zero so a heavily penalised event still sorts below every
    unpenalised one without going negative, which keeps the score meaningful
    when it is published in the candidate file.
    """
    chosen = chosen or []
    total = (
        price_points(event.get("price_status", PRICE_STATUS_UNKNOWN), event.get("price_eur"))
        + quality_points(event)
        + verification_points(event)
        - _diversity_penalty(event, chosen)
    )
    return max(0, min(100, total))


# --------------------------------------------------------------------------
# Editorial reason
# --------------------------------------------------------------------------

DAY_PREFIX = r"^(?:mo|di|mi|do|fr|sa|so|mon|tue|wed|thu|fri|sat|sun)\b\.?,?\s*"


def _clean_title_for_prose(title: str) -> str:
    """Plain prose from a scraped sentence: no markup, no link URLs.

    Jina-sourced rows carry Markdown emphasis and inline links
    ("der **[INNOQ Technology Day](https://…)** statt"), which read as noise
    in a one-line editorial reason.
    """
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", str(title or ""))
    text = re.sub(r'https?://\S+', "", text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -–—:|,.")


def _trim_prose(text: str, limit: int = 150) -> str:
    text = re.sub(r"\s+", " ", text or "").strip(" -–—:|,.")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut.rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def _strip_generic_opening(description: str) -> str:
    """Drop a blurb's date/source preamble so the prose starts with content.

    Listing cards concatenate their chrome into the description, so a blurb
    routinely opens with a weekday-and-date stamp, a relative day, a numeric
    date, or a promo badge before the actual sentence. Two thirds of the
    aggregate's descriptions carry one of these, and leaving them in produces
    an editorial reason like "… at Kantine — Do, 15. Okt | 19:00 FREE ENTRY:
    JAM SESSION", which reads as scraped rather than written.

    Stripping is repeated until nothing matches, because a card can stack a
    badge on top of a date ("Today, 11. Okt | 10:00 …").
    """
    text = description or ""
    # German and English weekday names, abbreviated or full. The abbreviation
    # is why this needs an explicit list: "Do" and "Sa" are two letters, and a
    # generic \w{3,} rule silently skipped a third of the corpus.
    weekday = (
        r"mo|di|mi|do|fr|sa|so|"
        r"mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|"
        r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    )
    month = (
        r"jan|feb|mär|maer|mar|apr|mai|may|jun|jul|aug|sep|sept|okt|oct|nov|dez|dec"
        r"|januar|februar|märz|maerz|april|juni|juli|august|september|oktober|"
        r"november|dezember|january|february|march|june|july|october|december"
    )
    promo = (
        r"today|tomorrow|heute|morgen|pick\s+of\s+the\s+day|sponsored|anzeige|"
        r"featured|free\s+entry|eintritt\s+frei|free\s+admission|kostenlos|"
        r"gratis|sold\s+out|ausverkauft"
    )
    prefixes = (
        # "<weekday>, <d>. <Mon>[ <yyyy>] | <hh>:<mm>" and the dotless variants.
        rf"(?:{weekday})[a-zäöü]*\.?,?\s*\d{{1,2}}\.?\s*(?:{month})?[a-zäöü]*\.?\s*\d{{0,4}}"
        rf"[\s,|–-]*\d{{0,2}}[:.]\d{{2}}\s*(?:uhr)?\s*[|·:]?\s*",
        # "<d>. <Mon>[ <yyyy>], <hh>:<mm>" with no weekday.
        rf"\d{{1,2}}\.?\s*(?:{month})[a-zäöü]*\.?\s*\d{{0,4}}[\s,|–-]*\d{{0,2}}[:.]\d{{2}}\s*[|·:]?\s*",
        # "2026-11-11 19:00" / "11/11/26 - 19:00" / "2026-11-11T19:00".
        r"\d{4}-\d{1,2}-\d{1,2}(?:t\d{1,2}[:.]\d{2})?[\s,|–-]*",
        r"\d{1,2}/\d{1,2}/\d{2,4}\s*[-–|]?\s*\d{0,2}[:.]?\d{0,2}\s*[-–|]?\s*",
        # A promo or relative-day badge, with or without punctuation after it.
        rf"(?:{promo})\b[\s,:;|–-]*",
        # A bare leading time left over once a badge or date was removed:
        # "Tomorrow 20:00 …" and "2026-11-11 19:00 …" both strand one.
        r"\d{1,2}[:.]\d{2}\s*(?:uhr)?\s*[|·:–-]?\s*",
    )
    combined = re.compile("^(?:" + "|".join(prefixes) + ")", re.IGNORECASE)
    for _ in range(6):
        stripped = combined.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    return text


def build_recommendation_reason(event: Dict[str, Any]) -> str:
    """A short, honest reason this event is on the list.

    Every clause is derived from what the record actually states - the price,
    the district, the category, the title. Nothing asserts attendance,
    popularity or critical reception, because the pipeline has no way to know
    any of those and inventing them would be exactly the kind of claim the
    brief forbids.
    """
    price_status = event.get("price_status", PRICE_STATUS_UNKNOWN)
    price = event.get("price_eur")
    category = event.get("category") or DEFAULT_CATEGORY
    district = event.get("district")
    venue = str(event.get("venue") or "").strip()

    label = category_label(category).lower()
    generic = category == DEFAULT_CATEGORY

    # "Free other distinctive experiences at X" is grammatical but reads like
    # a template. For the catch-all bucket the category phrase is dropped and
    # the price stands on its own.
    if price_status == PRICE_STATUS_CONFIRMED_FREE:
        opening = "Free entry" if generic else f"Free {label}"
    elif price_status == PRICE_STATUS_DONATION:
        opening = "Donation-based entry" if generic else f"Donation-based {label}"
    elif price_status == PRICE_STATUS_CONFIRMED_PAID and price is not None:
        amount = f"{int(price)}" if float(price).is_integer() else f"{float(price):.2f}"
        opening = f"€{amount} entry" if generic else f"{label.capitalize()} for €{amount}"
    elif price_status == PRICE_STATUS_NEEDS_VERIFICATION:
        opening = ("Entry to be confirmed" if generic
                   else f"{label.capitalize()} with entry to be confirmed")
    else:
        opening = ("Entry price still to be confirmed" if generic
                   else f"{label.capitalize()} with entry price still to be confirmed")

    where = ""
    if venue and district:
        where = f" at {venue} in {district}"
    elif venue:
        where = f" at {venue}"
    elif district:
        where = f" in {district}"

    detail = ""
    description = _strip_generic_opening(str(event.get("description") or ""))
    title_words = set(re.findall(r"\w{4,}", str(event.get("title") or "").lower()))
    sentences = re.split(r"(?<=[.!?])\s+", description)
    for sentence in sentences:
        candidate = _clean_title_for_prose(sentence)
        if len(candidate) < 25:
            continue
        overlap = len(title_words & set(re.findall(r"\w{4,}", candidate.lower())))
        if overlap >= 3:
            continue  # restates the title, adds nothing
        detail = f" — {_trim_prose(candidate, 130)}"
        break

    reason = f"{opening}{where}{detail}"
    return _trim_prose(reason, 220)


# --------------------------------------------------------------------------
# The selection itself
# --------------------------------------------------------------------------

def prepare_events_for_selection(
    raw_events: Iterable[Dict[str, Any]],
    seen_previous_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Normalise raw aggregate rows into selection-shaped candidates.

    ``seen_previous_ids`` is provenance only - it marks an event as newly
    discovered for the weekly summary, and never removes a row: a recurring
    event legitimately re-appears every week under a new occurrence id.
    """
    seen = set(seen_previous_ids or [])
    prepared: List[Dict[str, Any]] = []
    for raw in raw_events or []:
        if not isinstance(raw, dict):
            continue
        event = dict(raw)
        event["category"] = event.get("category") or classify_category(
            str(event.get("title") or ""),
            str(event.get("venue") or ""),
            str(event.get("description") or ""),
        )
        if not event.get("district"):
            event["district"] = district_from_text(
                str(event.get("venue") or ""),
                str(event.get("address") or ""),
                str(event.get("description") or ""),
            )
        event["price_priority"] = price_priority(
            event.get("price_status", PRICE_STATUS_UNKNOWN)
        )
        previous = event.get("event_id") in seen
        event["_seen_before"] = previous
        event["_newly_discovered"] = not previous
        prepared.append(event)
    return prepared


def select_community_events(
    events: Iterable[Dict[str, Any]],
    target: int = COMMUNITY_TARGET_MAX,
    max_price: float = COMMUNITY_MAX_PRICE,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pick the weekly shortlist; returns (selected, unresolved).

    Greedy rather than globally optimal, on purpose: re-scoring the whole pool
    after every pick would let one cheap category dominate the count before
    the diversity penalty had a chance to matter. Taking the best current
    candidate each round and re-scoring what is left spreads the list across
    categories and districts, which is the actual goal.

    Rows whose price is unsettled are kept in a separate unresolved list
    rather than dropped: they are exactly what the verification pass exists
    for, and the review summary reports them as such.
    """
    pool = [dict(e) for e in events or [] if isinstance(e, dict)]
    eligible, excluded = [], []
    for event in pool:
        status = event.get("price_status", PRICE_STATUS_UNKNOWN)
        if status == PRICE_STATUS_CONFIRMED_PAID and not is_eligible(
            status, event.get("price_eur"), max_price
        ):
            excluded.append({**event, "_exclusion": "above_community_cap"})
            continue
        if (event.get("verification") or {}).get("status") == VERIFICATION_REJECTED:
            excluded.append({**event, "_exclusion": "rejected_by_verification"})
            continue
        eligible.append(event)

    target = max(0, min(int(target), COMMUNITY_TARGET_MAX))
    chosen: List[Dict[str, Any]] = []
    remaining = list(eligible)
    while remaining and len(chosen) < target:
        scored = [
            (selection_score(event, chosen), index)
            for index, event in enumerate(remaining)
        ]
        best_score, best_index = max(scored)
        event = remaining.pop(best_index)
        event["selection_score"] = best_score
        chosen.append(event)

    unresolved = [
        event for event in pool
        if event.get("price_status") in (PRICE_STATUS_UNKNOWN, PRICE_STATUS_NEEDS_VERIFICATION)
        and (event.get("verification") or {}).get("status") != VERIFICATION_REJECTED
        and event not in chosen
    ]
    return chosen, unresolved


def category_distribution(events: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for event in events or []:
        key = event.get("category") or DEFAULT_CATEGORY
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def price_band_distribution(events: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """How many events sit in each price band, for the review summary."""
    bands = {"free": 0, "donation": 0, "1-5": 0, "5.01-10": 0, "10.01-15": 0,
             "over_15": 0, "needs_verification": 0, "unknown": 0}
    for event in events or []:
        status = event.get("price_status", PRICE_STATUS_UNKNOWN)
        price = event.get("price_eur")
        if status == PRICE_STATUS_CONFIRMED_FREE:
            bands["free"] += 1
        elif status == PRICE_STATUS_DONATION:
            bands["donation"] += 1
        elif status == PRICE_STATUS_NEEDS_VERIFICATION:
            bands["needs_verification"] += 1
        elif status == PRICE_STATUS_UNKNOWN or price is None:
            bands["unknown"] += 1
        elif float(price) > COMMUNITY_MAX_PRICE:
            bands["over_15"] += 1
        elif float(price) <= 5:
            bands["1-5"] += 1
        elif float(price) <= 10:
            bands["5.01-10"] += 1
        else:
            bands["10.01-15"] += 1
    return bands


def apply_community_metadata(event: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the editorial fields the schema expects to one event."""
    event["community"] = {
        "recommendation_reason": build_recommendation_reason(event),
        "selection_score": event.get("selection_score"),
        "price_priority": price_priority(event.get("price_status", PRICE_STATUS_UNKNOWN)),
        "selection_status": SELECTION_PROPOSED,
    }
    for internal in ("_seen_before", "_newly_discovered", "_exclusion"):
        event.pop(internal, None)
    return event


def meets_weekly_target(selected: Sequence[Dict[str, Any]]) -> bool:
    """True when the shortlist reached its lower bound.

    Reported, never enforced: padding a thin week would trade the whole point
    of an editorial shortlist for a number.
    """
    return len(selected) >= COMMUNITY_TARGET_MIN
