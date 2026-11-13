#!/usr/bin/env python3
"""Independent verification of a discovered event against its official page.

Discovery and confirmation are different claims, and the community page may
only publish the second. A listing site that says "19:00, EUR 10" is evidence
that *something* advertised that; only the organiser's own event page can
confirm it is still on, at that time, at that price.

So this module does not "improve" a scraped row. It fetches the row's own
detail URL, extracts what that page states, and then compares the two field by
field, recording one of four outcomes per field:

  match         - the official page agrees with the scraped value
  corrected     - the official page states something different (its value wins)
  not_confirmed - the page could not be read, or does not state the field
  rejected      - the page positively contradicts the event being usable
                  (cancelled, not an event page)

``not_confirmed`` is deliberately *not* a soft ``match``: an unreachable page
means the field is unknown, and a publishable candidate must have confirmed
identity and date fields.

Nothing here guesses. If the page does not state a price, the price stays
unconfirmed even when the listing was confident about it.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime

# Sibling modules are imported flat ("from community_common import ..."),
# matching the rest of scripts/, so the directory has to be on the path even
# when this file is imported as part of the package (tests, tooling).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Any, Dict, List, Optional

from community_common import (
    FIELD_CORRECTED,
    FIELD_MATCH,
    FIELD_NOT_CONFIRMED,
    FIELD_REJECTED,
    VERIFICATION_CORRECTED,
    VERIFICATION_MATCHED,
    VERIFICATION_REJECTED,
    VERIFICATION_UNCONFIRMED,
    canonical_url,
    classify_price,
    identity_text,
    iso_now,
)

# Bounds. Verification runs over the shortlist only, and the shortlist is
# small; these caps exist so a pathological source cannot turn the weekly
# handoff into an unbounded crawl.
MAX_VERIFICATIONS = 40

CANCELLED_RE = re.compile(
    r"\b(?:abgesagt|entfällt|entfaellt|cancell?ed|cancell?ation|"
    r"no\s+longer\s+taking\s+place)\b",
    re.IGNORECASE,
)
POSTPONED_RE = re.compile(r"\b(?:verschoben|postponed|rescheduled)\b", re.IGNORECASE)
SOLD_OUT_RE = re.compile(
    r"\b(?:ausverkauft|sold\s+out|no\s+tickets?\s+left)\b", re.IGNORECASE
)

# The handful of German/English month names an event page prints as a date.
_MONTHS = {
    "jan": 1, "januar": 1, "january": 1,
    "feb": 2, "februar": 2, "february": 2,
    "mär": 3, "maer": 3, "märz": 3, "maerz": 3, "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "mai": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dez": 12, "dezember": 12, "dec": 12, "december": 12,
}

CONFIRMABLE_FIELDS = ("title", "date", "time", "venue", "price", "availability")


def _parse_iso_date(value: str) -> Optional[str]:
    text = str(value or "").strip()
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _dates_in_text(text: str) -> List[str]:
    """Every ISO or German-formatted date mentioned in a block of text."""
    found: List[str] = []
    for match in re.finditer(r'(\d{4})-(\d{1,2})-(\d{1,2})', text or ""):
        try:
            found.append(
                date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
            )
        except ValueError:
            continue
    for match in re.finditer(
        r'\b(\d{1,2})\.\s*(Jan(?:uar)?|Feb(?:ruar)?|M(?:ä|ae)r(?:z)?|Apr(?:il)?|Mai|'
        r'Jun(?:i)?|Jul(?:i)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Okt(?:ober)?|'
        r'Nov(?:ember)?|Dez(?:ember)?)\b\.?\s*(\d{4})?',
        text or "", re.IGNORECASE,
    ):
        month = _MONTHS.get(match.group(2).lower().rstrip("."))
        if not month:
            continue
        year = int(match.group(3)) if match.group(3) else datetime.now().year
        try:
            found.append(date(year, month, int(match.group(1))).isoformat())
        except ValueError:
            continue
    return found


def _times_in_text(text: str) -> List[str]:
    times = []
    for match in re.finditer(r'\b([01]?\d|2[0-3])[:.]([0-5]\d)\b(?!\d)', text or ""):
        times.append(f"{int(match.group(1)):02d}:{match.group(2)}")
    for match in re.finditer(r'\b([01]?\d|2[0-3])\s*Uhr\b', text or "", re.IGNORECASE):
        times.append(f"{int(match.group(1)):02d}:00")
    return times


def titles_agree(scraped: str, verified: str) -> bool:
    """Loose title agreement: normalised containment either way.

    A page routinely prefixes the event with its venue ("HAU2: Title") or
    suffixes it with a ticket note ("Title - Tickets"), so demanding equality
    would flag every such page as a correction. Containment of the normalised
    forms is the right test at this precision.
    """
    left, right = identity_text(scraped), identity_text(verified)
    if not left or not right:
        return False
    if left == right:
        return True
    return left in right or right in left


def extract_official_fields(html: str, url: str) -> Dict[str, Any]:
    """What an official event page states, in the pipeline's vocabulary.

    Reads schema.org first because it is unambiguous, and falls back to the
    page's visible text for the many venue sites that publish prose only.
    Returns ``{"reachable": False}`` when the body looks like an anti-bot
    interstitial - the caller must treat that as "not confirmed", never as
    "the page agrees".
    """
    if not html:
        return {"reachable": False, "reason": "empty"}
    try:
        from generic_event_scraper import extract_jsonld_events, is_bot_challenge
        from bs4 import BeautifulSoup
    except Exception:  # noqa: BLE001
        return {"reachable": False, "reason": "no_parser"}

    if is_bot_challenge(html):
        return {"reachable": False, "reason": "bot_challenge"}

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    fields: Dict[str, Any] = {
        "reachable": True,
        "title": "",
        "dates": [],
        "times": [],
        "price": None,
        "price_text": "",
        "cancelled": bool(CANCELLED_RE.search(text)),
        "postponed": bool(POSTPONED_RE.search(text)),
        "sold_out": bool(SOLD_OUT_RE.search(text)),
        "venue": "",
        "image_url": "",
    }

    # JSON-LD is authoritative when present: one node describes this page.
    try:
        nodes = extract_jsonld_events(html, url)
    except Exception:  # noqa: BLE001 - a broken blob must not fail verification
        nodes = []
    if nodes:
        node = nodes[0]
        fields["title"] = str(node.get("title") or "")
        iso = _parse_iso_date(str(node.get("date") or ""))
        if iso:
            fields["dates"] = [iso]
        if node.get("time"):
            fields["times"] = [str(node["time"])]
        if node.get("price") is not None:
            try:
                fields["price"] = float(node["price"])
                fields["price_text"] = str(node["price"])
            except (TypeError, ValueError):
                fields["price"] = None
        fields["venue"] = str(node.get("venue") or "")
        fields["image_url"] = str(node.get("image_url") or "")

    if not fields["title"]:
        heading = soup.find(["h1", "h2"])
        if heading:
            fields["title"] = heading.get_text(" ", strip=True)
    if not fields["title"]:
        match = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        if match:
            fields["title"] = match.group(1)
    if not fields["dates"]:
        fields["dates"] = _dates_in_text(text)[:6]
    if not fields["times"]:
        fields["times"] = _times_in_text(text)[:6]
    if fields["price"] is None:
        price = price_from_text(text)
        if price is not None:
            fields["price"] = price
            fields["price_text"] = str(price)
    if not fields["image_url"]:
        try:
            from image_utils import best_document_image

            declared = best_document_image(html, url)
            if declared:
                fields["image_url"] = declared["url"]
        except Exception:  # noqa: BLE001 - images are decoration
            pass

    return fields


def price_from_text(text: str) -> Optional[float]:
    """A price only when the text states one; otherwise None.

    Reuses the pipeline's price parser through the normalisation layer rather
    than a second regex, so verification cannot disagree with discovery about
    what "12,50 EUR" means.
    """
    try:
        from event_utils import parse_price
    except Exception:  # noqa: BLE001
        return None
    return parse_price(text or "")


def compare_event(event: Dict[str, Any], official: Dict[str, Any]) -> Dict[str, Any]:
    """Field-by-field comparison, with the official page winning conflicts.

    Returns ``{"verification", "rejected", "corrected_fields"}`` - the last
    carrying the values the candidate record should adopt.
    """
    if not official.get("reachable"):
        return {
            "verification": {
                "status": VERIFICATION_UNCONFIRMED,
                "checked_at": iso_now(),
                "official_source_url": event.get("event_url") or event.get("url"),
                "fields": {name: FIELD_NOT_CONFIRMED for name in CONFIRMABLE_FIELDS},
                "corrections": [],
                "notes": f"official page not readable ({official.get('reason', 'unavailable')})",
            },
            "rejected": False,
            "corrected_fields": {},
        }

    corrections: List[Dict[str, Any]] = []
    fields: Dict[str, str] = {}
    corrected_values: Dict[str, Any] = {}

    # --- title -------------------------------------------------------------
    scraped_title = str(event.get("title") or "")
    official_title = str(official.get("title") or "")
    if official_title and titles_agree(scraped_title, official_title):
        fields["title"] = FIELD_MATCH
    elif official_title:
        fields["title"] = FIELD_CORRECTED
        corrections.append({"field": "title", "scraped": scraped_title, "verified": official_title})
        corrected_values["title"] = official_title
    else:
        fields["title"] = FIELD_NOT_CONFIRMED

    # --- date --------------------------------------------------------------
    scraped_date = _parse_iso_date(str(event.get("date") or ""))
    official_dates = [d for d in official.get("dates") or [] if d]
    if official_dates and scraped_date in official_dates:
        fields["date"] = FIELD_MATCH
    elif official_dates:
        fields["date"] = FIELD_CORRECTED
        corrections.append(
            {"field": "date", "scraped": scraped_date, "verified": official_dates[0]}
        )
        corrected_values["date"] = official_dates[0]
    else:
        fields["date"] = FIELD_NOT_CONFIRMED

    # --- time --------------------------------------------------------------
    scraped_time = str(event.get("time") or "")
    official_times = [t for t in official.get("times") or [] if t]
    if not scraped_time:
        fields["time"] = FIELD_NOT_CONFIRMED
    elif scraped_time in official_times:
        fields["time"] = FIELD_MATCH
    elif official_times:
        fields["time"] = FIELD_CORRECTED
        corrections.append(
            {"field": "time", "scraped": scraped_time, "verified": official_times[0]}
        )
        corrected_values["time"] = official_times[0]
    else:
        fields["time"] = FIELD_NOT_CONFIRMED

    # --- venue -------------------------------------------------------------
    scraped_venue = str(event.get("venue") or "")
    official_venue = str(official.get("venue") or "")
    if not official_venue:
        fields["venue"] = FIELD_NOT_CONFIRMED
    elif (
        not scraped_venue
        or identity_text(scraped_venue) in identity_text(official_venue)
        or identity_text(official_venue) in identity_text(scraped_venue)
    ):
        fields["venue"] = FIELD_MATCH
        if not scraped_venue:
            corrected_values["venue"] = official_venue
    else:
        fields["venue"] = FIELD_CORRECTED
        corrections.append(
            {"field": "venue", "scraped": scraped_venue, "verified": official_venue}
        )
        corrected_values["venue"] = official_venue

    # --- price -------------------------------------------------------------
    scraped_price = event.get("price_eur")
    official_price = official.get("price")
    if official_price is None:
        fields["price"] = FIELD_NOT_CONFIRMED
    elif scraped_price is None:
        fields["price"] = FIELD_CORRECTED
        corrections.append({"field": "price", "scraped": None, "verified": official_price})
        corrected_values["price_eur"] = official_price
    elif abs(float(scraped_price) - float(official_price)) <= 0.01:
        fields["price"] = FIELD_MATCH
    else:
        fields["price"] = FIELD_CORRECTED
        corrections.append(
            {"field": "price", "scraped": scraped_price, "verified": official_price}
        )
        corrected_values["price_eur"] = official_price

    # --- availability / cancellation ---------------------------------------
    notes: List[str] = []
    rejected = False
    if official.get("cancelled"):
        fields["cancellation"] = FIELD_REJECTED
        rejected = True
        notes.append("official page states the event is cancelled")
    elif official.get("postponed"):
        fields["cancellation"] = FIELD_REJECTED
        rejected = True
        notes.append("official page states the event is postponed")
    else:
        fields["cancellation"] = FIELD_MATCH if official.get("dates") else FIELD_NOT_CONFIRMED
    if official.get("sold_out"):
        fields["availability"] = FIELD_MATCH
        notes.append("official page states it is sold out")
    else:
        # Absence of a sold-out marker is not evidence that tickets exist.
        fields["availability"] = FIELD_NOT_CONFIRMED

    # The overall verdict is about the *event*, not about whether every field
    # could be pinned down. Identity, date, time, venue and price are the
    # fields publication depends on; availability is deliberately excluded,
    # because an event with no sold-out marker has not thereby confirmed that
    # tickets remain, and requiring it would mark every event unverified.
    decisive = ("title", "date", "time", "venue", "price")
    decisive_outcomes = [fields.get(name) for name in decisive]
    if rejected:
        overall = VERIFICATION_REJECTED
    elif FIELD_REJECTED in fields.values():
        overall = VERIFICATION_REJECTED
    elif FIELD_CORRECTED in decisive_outcomes:
        overall = VERIFICATION_CORRECTED
    elif FIELD_NOT_CONFIRMED in decisive_outcomes:
        overall = VERIFICATION_UNCONFIRMED
    else:
        overall = VERIFICATION_MATCHED

    return {
        "verification": {
            "status": overall,
            "checked_at": iso_now(),
            "official_source_url": event.get("event_url") or event.get("url"),
            "fields": fields,
            "corrections": corrections,
            "notes": "; ".join(notes),
        },
        "rejected": rejected,
        "corrected_fields": corrected_values,
    }


def apply_corrections(event: Dict[str, Any], corrected: Dict[str, Any]) -> Dict[str, Any]:
    """Adopt official values, keeping the price state consistent with them."""
    for field, value in (corrected or {}).items():
        if field == "price_eur":
            event["price_eur"] = value
            event["price_status"] = classify_price(value, str(event.get("price_note") or ""))
        else:
            event[field] = value
    return event


def verify_event(event: Dict[str, Any], fetch, page_url: Optional[str] = None) -> Dict[str, Any]:
    """Verify one event against its official page and return it updated.

    ``fetch`` is injected so the comparison logic is testable without a
    network, and so the workflow can hand in a session that already presents
    browser headers.
    """
    url = page_url or event.get("event_url") or event.get("url") or ""
    if not url or not str(url).startswith("http"):
        outcome = compare_event(event, {"reachable": False, "reason": "no_source"})
        event["verification"] = outcome["verification"]
        return event
    try:
        html = fetch(url)
    except Exception:  # noqa: BLE001 - any transport failure is "unconfirmed"
        html = None
    official = extract_official_fields(html or "", url)
    outcome = compare_event(event, official)
    apply_corrections(event, outcome["corrected_fields"])
    event["verification"] = outcome["verification"]

    # An official page's own image is stronger evidence than the listing's.
    declared = official.get("image_url")
    if declared and not event.get("image_url"):
        event["image_url"] = declared
        event["image_source"] = "official_page_image"
        event["image_verified"] = None
    return event


def verify_events(
    events: List[Dict[str, Any]],
    fetch,
    max_verifications: int = MAX_VERIFICATIONS,
) -> List[Dict[str, Any]]:
    """Verify a shortlist, bounded; each event is updated in place."""
    for index, event in enumerate(events or []):
        if index >= max_verifications:
            event.setdefault("verification", {
                "status": VERIFICATION_UNCONFIRMED,
                "checked_at": None,
                "official_source_url": event.get("event_url") or event.get("url"),
                "fields": {},
                "corrections": [],
                "notes": "verification budget exhausted",
            })
            continue
        verify_event(event, fetch)
    return events


def official_url_for(event: Dict[str, Any]) -> str:
    """The URL to verify against, or "" when there is no distinct event page."""
    url = canonical_url(event.get("event_url") or event.get("url") or "")
    if not url or url == canonical_url(event.get("source_url") or ""):
        return ""
    return url
