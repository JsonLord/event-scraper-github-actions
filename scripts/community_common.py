#!/usr/bin/env python3
"""Shared vocabulary for the community pipeline.

Everything in the community track - selection, verification, candidate
generation, promotion, the frontend's JSON contract - agrees on the names in
this module. Keeping them in one file is what stops the price vocabulary from
drifting apart between the code that classifies a price and the code that
decides whether an event may be published.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "1.0"
ISSUE_TIMEZONE = "Europe/Berlin"

# The community cap. Deliberately *not* tied to event_utils.DEFAULT_MAX_PRICE:
# the personal table's €20 ceiling is its own policy, and changing one must
# never silently move the other.
COMMUNITY_MAX_PRICE = 15.0

# A weekly issue wants a real shortlist, not everything that parsed. The upper
# bound is a ceiling, never a target to pad towards.
COMMUNITY_TARGET_MIN = 20
COMMUNITY_TARGET_MAX = 35


def berlin_tz() -> ZoneInfo:
    return ZoneInfo(ISSUE_TIMEZONE)


def now_berlin() -> datetime:
    return datetime.now(berlin_tz())


def iso_now() -> str:
    """Timezone-aware ISO timestamp in the issue's own timezone."""
    return now_berlin().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Calendar week
# --------------------------------------------------------------------------

def week_bounds(any_day: date) -> Tuple[date, date]:
    """The Monday and Sunday of the ISO week containing ``any_day``.

    Europe/Berlin is the calendar the newsletter is written for, and its week
    is Monday-Sunday. Doing this with ``isoweekday()`` arithmetic rather than
    locale-dependent helpers keeps it correct on a runner whose locale is
    anything at all.
    """
    monday = any_day - timedelta(days=any_day.isoweekday() - 1)
    return monday, monday + timedelta(days=6)


def next_week_bounds(any_day: Optional[date] = None) -> Tuple[date, date]:
    """Monday-Sunday of the week after the one containing ``any_day``.

    The newsletter is published for the week that has not started yet: a
    candidate file generated on a Sunday evening covers the Monday that
    follows it.
    """
    today = any_day or now_berlin().date()
    start, _ = week_bounds(today)
    return start + timedelta(days=7), start + timedelta(days=13)


def issue_week_payload(start: date, end: Optional[date] = None) -> Dict[str, str]:
    end = end or (start + timedelta(days=6))
    return {"start": start.isoformat(), "end": end.isoformat(), "timezone": ISSUE_TIMEZONE}


def in_issue_week(iso_date: Optional[str], start: date, end: date) -> bool:
    if not iso_date:
        return False
    try:
        parsed = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return False
    return start <= parsed <= end


# --------------------------------------------------------------------------
# Stable identity
# --------------------------------------------------------------------------

CANONICAL_URL_DROP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "recid", "recsource", "searchid", "eventorigin",
    "mc_cid", "mc_eid", "ref", "aff", "lang", "locale",
}


def canonical_url(url: str) -> str:
    """A URL stripped of tracking, fragment, trailing slash and case noise."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        parsed = urlparse(raw)
    except ValueError:
        return raw.lower()
    query = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in CANONICAL_URL_DROP_PARAMS
    ]
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", urlencode(query), ""))


def identity_text(value: str) -> str:
    """Lowercase, diacritic-free, punctuation-free form for matching."""
    decomposed = unicodedata.normalize("NFKD", str(value or "").lower())
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", folded)).strip()


def stable_event_id(
    title: str,
    canonical: str,
    occurrence_date: str,
    *,
    venue: str = "",
    time: str = "",
) -> str:
    """Deterministic id for one *occurrence* of an event.

    The date is part of the identity on purpose: a weekly club night is the
    same event on 20 November and 27 November, and an approval for one must
    never promote the other. The hash is over a readable fingerprint so the
    same event scraped twice - in any source order - lands on the same id.
    """
    parts = [
        identity_text(title),
        canonical_url(canonical),
        str(occurrence_date or "")[:10],
        identity_text(venue),
        str(time or ""),
    ]
    digest = hashlib.sha256("\u001f".join(parts).encode("utf-8")).hexdigest()
    return f"ce-{digest[:24]}"


# --------------------------------------------------------------------------
# Price status
# --------------------------------------------------------------------------

PRICE_STATUS_CONFIRMED_FREE = "confirmed_free"
PRICE_STATUS_CONFIRMED_PAID = "confirmed_paid"
PRICE_STATUS_DONATION = "donation_based"
PRICE_STATUS_UNKNOWN = "unknown"
PRICE_STATUS_NEEDS_VERIFICATION = "needs_verification"

PRICE_STATUSES = (
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_DONATION,
    PRICE_STATUS_UNKNOWN,
    PRICE_STATUS_NEEDS_VERIFICATION,
)

DONATION_RE = re.compile(
    r"\b(?:spende[n]?|spendenbasis|auf\s+spendenbasis|donation|pay\s+what\s+you\s+want|"
    r"eintritt\s+freiwillig|freiwilliger\s+eintritt|solidarisch(?:e[snr]?)?\s+(?:preis|beitrag|ticket)|"
    r"sliding\s+scale)\b",
    re.IGNORECASE,
)
FREE_TEXT_RE = re.compile(
    r"\b(?:eintritt\s+frei|freier\s+eintritt|kostenlos|kostenfrei|gratis|free\s+(?:entry|admission)|"
    r"no\s+cover|ohne\s+eintritt|umsonst)\b",
    re.IGNORECASE,
)
PRICE_NEEDS_CHECK_RE = re.compile(
    r"\b(?:preis\s+auf\s+anfrage|auf\s+anfrage|k\.?\s?a\.?|tba|tbd|"
    r"siehe\s+website|see\s+website|preise?\s+siehe|informationen?\s+folgen)\b",
    re.IGNORECASE,
)


def classify_price(price: Optional[float], text: str = "") -> str:
    """Which of the five price states a row is in.

    An unknown price never becomes a free one: ``price is None`` resolves to
    ``unknown`` unless the text says explicitly that entry is free, and a
    stated price of exactly 0 with no free marker is still treated as
    confirmed free only because 0 is what the source said - never because a
    missing value was coerced to 0 somewhere upstream.
    """
    haystack = str(text or "")
    if price is None:
        if PRICE_NEEDS_CHECK_RE.search(haystack):
            return PRICE_STATUS_NEEDS_VERIFICATION
        if DONATION_RE.search(haystack):
            return PRICE_STATUS_DONATION
        if FREE_TEXT_RE.search(haystack):
            return PRICE_STATUS_CONFIRMED_FREE
        return PRICE_STATUS_UNKNOWN
    if DONATION_RE.search(haystack) and float(price) <= 0:
        return PRICE_STATUS_DONATION
    if float(price) <= 0:
        return PRICE_STATUS_CONFIRMED_FREE
    return PRICE_STATUS_CONFIRMED_PAID


def price_priority(price_status: str) -> str:
    return {
        PRICE_STATUS_CONFIRMED_FREE: "free",
        PRICE_STATUS_DONATION: "donation",
        PRICE_STATUS_CONFIRMED_PAID: "paid",
        PRICE_STATUS_NEEDS_VERIFICATION: "needs_verification",
        PRICE_STATUS_UNKNOWN: "unknown",
    }.get(price_status, "unknown")


def is_confirmed_entry_price(price_status: str, price: Optional[float],
                             max_price: float = COMMUNITY_MAX_PRICE) -> bool:
    """True when the entry price is confirmed and inside the community cap.

    Only the two confirmed states qualify. ``unknown`` and
    ``needs_verification`` are unsettled questions, and ``donation_based``
    has no single entry price to compare against a cap at all.
    """
    if price_status == PRICE_STATUS_CONFIRMED_FREE:
        return True
    if price_status == PRICE_STATUS_CONFIRMED_PAID:
        return price is not None and 0 < float(price) <= max_price
    return False


# The evidence model's status vocabulary, mapped onto this one.
#
# ``ticket_evidence.enrich_evidence()`` (the scraping pipeline's own model)
# already classifies price with more proof than a bare number: it separates a
# 0 that a page proves is free from a legacy 0 that proves nothing, and it
# reports a range separately. Where its status is present it is *more*
# informed than re-deriving from ``price`` alone, so it is consulted first and
# the text-derived classification is the fallback.
#
# ``range`` is deliberately absent: the entry price is the low end, so a range
# whose minimum is 0 genuinely is free entry from a pay-more tier. That case
# falls through to the text/model check rather than being flattened here.
EVIDENCE_STATUS_MAP = {
    "free": PRICE_STATUS_CONFIRMED_FREE,
    "known": PRICE_STATUS_CONFIRMED_PAID,
    "unknown": PRICE_STATUS_UNKNOWN,
}


def price_status_for(event: Dict[str, Any]) -> str:
    """The community price status for an aggregated event row.

    Precedence, most-informed first:

      1. an explicit community ``price_status`` already on the row
      2. the scraping pipeline's evidence status (``free``/``known``/``unknown``)
      3. a classification derived from the price and the row's own text

    Step 2 matters because the pipeline's ``free`` is a *confirmed* free: it
    required independent proof, so a legacy ``price: 0`` arrives here as
    ``unknown`` rather than being mistaken for free entry. Step 3 is what
    keeps an unstamped row safe: ``price is None`` stays unknown, never zero.

    One field name, two vocabularies: ``ticket_evidence.enrich_evidence()``
    writes its own status into a field also called ``price_status``. The two
    vocabularies are disjoint - community uses ``confirmed_free`` /
    ``confirmed_paid`` / ``donation_based`` / ``unknown`` /
    ``needs_verification``; evidence uses ``free`` / ``known`` / ``range`` /
    ``unknown`` - so a value can be attributed to the right model without
    guessing. An evidence ``free`` must be read as confirmed free, not as an
    unrecognised value to re-derive, because re-deriving from a bare 0 would
    discard the proof that made it free in the first place.
    """
    if not isinstance(event, dict):
        return PRICE_STATUS_UNKNOWN
    explicit = str(event.get("price_status") or "").strip()
    if explicit in PRICE_STATUSES:
        return explicit
    # An evidence-vocabulary value may arrive in either field: `price_status`
    # when the scoring pass stamped the row, `evidence_status` when it was
    # read straight from the aggregate.
    evidence_value = ""
    for field in ("evidence_status", "price_status"):
        candidate = str(event.get(field) or "").strip()
        if candidate in EVIDENCE_STATUS_MAP or candidate == "range":
            evidence_value = candidate
            break
    evidence = EVIDENCE_STATUS_MAP.get(evidence_value)
    price = event.get("price_eur", event.get("price"))
    if evidence == PRICE_STATUS_CONFIRMED_PAID and price is None:
        # "known" without a number cannot be a confirmed paid price.
        evidence = None
    if evidence is not None:
        if evidence == PRICE_STATUS_CONFIRMED_FREE:
            return evidence
        if evidence == PRICE_STATUS_CONFIRMED_PAID and price is not None \
                and float(price) > 0:
            return evidence
    text = " ".join(
        str(event.get(field) or "")
        for field in ("title", "description", "price_note")
    )
    try:
        numeric = float(price) if price is not None else None
    except (TypeError, ValueError):
        numeric = None
    derived = classify_price(numeric, text)
    # A bare zero is not proof of free entry.
    #
    # This is the same rule the scraping pipeline's evidence model applies, and
    # it exists for the same reason: several sources emit `price: 0` when they
    # simply failed to find a price, so treating a zero with no corroborating
    # text as "free" would publish an unverified price as a confirmed one - the
    # exact failure the publication gate is meant to prevent. A zero that a
    # page does prove free already arrived as evidence status `free` (step 2)
    # and never reaches here.
    if derived == PRICE_STATUS_CONFIRMED_FREE and numeric == 0 and not (
        FREE_TEXT_RE.search(text) or DONATION_RE.search(text)
    ):
        return PRICE_STATUS_UNKNOWN
    return derived


# --------------------------------------------------------------------------
# Verification vocabulary
# --------------------------------------------------------------------------

FIELD_MATCH = "match"
FIELD_CORRECTED = "corrected"
FIELD_NOT_CONFIRMED = "not_confirmed"
FIELD_REJECTED = "rejected"
FIELD_STATUSES = (FIELD_MATCH, FIELD_CORRECTED, FIELD_NOT_CONFIRMED, FIELD_REJECTED)

VERIFICATION_MATCHED = "matched"
VERIFICATION_CORRECTED = "corrected"
VERIFICATION_UNCONFIRMED = "not_confirmed"
VERIFICATION_REJECTED = "rejected"

SELECTION_PROPOSED = "proposed"
SELECTION_APPROVED = "approved"
SELECTION_REJECTED = "rejected"
SELECTION_UNRESOLVED = "unresolved"

DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"


# --------------------------------------------------------------------------
# Broad, non-personal categories
# --------------------------------------------------------------------------

# Ordered: the first match wins, so the more specific bucket is listed before
# the bucket that would otherwise swallow it (electronic music before the
# general music umbrella, markets before the general community one).
COMMUNITY_CATEGORIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("electronic", (
        "techno", "house", "electro", "drum and bass", "dnb", "rave", "club night",
        "dj set", "dj", "ambient", "ebm", "synth", "berlin techno",
        # German compounds are written as one word; see the note on
        # _CATEGORY_PATTERNS for why they are listed rather than derived.
        "technonacht", "technoparty", "technofestival", "technoklub",
    )),
    ("music", (
        "konzert", "concert", "live music", "musik", "band", "gig", "jazz",
        "klassik", "classical", "orchestra", "orchester", "choir", "chor",
        "singer", "songwriter", "open mic", "jam session", "vinyl",
    )),
    ("nightlife", (
        "party", "club", "bar night", "afterhour", "after hour", "kneipen",
        "drag show", "burlesque",
    )),
    ("arts", (
        "ausstellung", "exhibition", "vernissage", "galerie", "gallery", "kunst",
        "art show", "installation", "fotografie", "photography", "skulptur",
    )),
    ("culture", (
        "theater", "theatre", "schauspiel", "bühne", "buehne", "oper", "opera",
        "ballet", "ballett", "tanz", "dance", "performance", "kabarett", "comedy",
        "lesung", "reading", "poetry", "film screening", "kino", "cinema",
    )),
    ("workshops", (
        "workshop", "kurs", "course", "seminar", "class", "lerne", "learning",
        "mitmachen", "hands-on", "tutorial", "masterclass", "training",
        # The hyphenated form appears in listings; the spaced form is already
        # covered by "workshop".
        "workshop-reihe", "workshop-woche", "workshop-abend",
    )),
    ("outdoor", (
        "outdoor", "open air", "openair", "freiluft", "park", "garten", "garden",
        "picknick", "picnic", "spaziergang", "walk", "wanderung", "hiking",
        "fahrradtour", "bike ride", "klettern", "climbing", "bouldern",
    )),
    ("sports", (
        "sport", "running", "run club", "lauf", "jogging", "yoga", "pilates",
        "fitness", "workout", "volleyball", "basketball", "football", "fußball",
        "tennis", "skate", "swimming", "schwimmen", "marathon",
    )),
    ("markets", (
        "markt", "market", "flohmarkt", "fleamarket", "festival", "fest", "messe",
        "fair", "basar", "weihnachtsmarkt", "street food",
    )),
    ("community", (
        # "meetup" is deliberately absent: it appears in the title of nearly
        # every Meetup-sourced row, so matching it filed a coding conference
        # under "community and neighbourhood" purely because of its platform.
        "community", "nachbarschaft", "neighbourhood", "neighborhood", "kiez",
        "stammtisch", "gathering", "mixer", "tandem", "ehrenamt", "volunteer",
        "verein", "quartier", "nachbarschaftsfest",
    )),
)

DEFAULT_CATEGORY = "other"

# Whole-word matching only.
#
# The personal scorer matches r"\b(kw)\w*", which lets a short keyword match
# inside an unrelated longer word: "techno" matched "Technology" and filed a
# coding meetup under electronic music, and "market" would match "Marketing".
# Allowing a suffix above some length threshold does not fix that, because
# "Marketing" and "Marketplatz" are the same shape - there is no automatic
# rule that separates an English derivative from a German compound.
#
# So compounds are listed explicitly instead. That keeps the classifier
# predictable - a token either matches a declared word or it does not - and
# an unlisted compound falls into "other", which is a visible, harmless
# outcome rather than a confidently wrong category.
_CATEGORY_PATTERNS = tuple(
    (
        name,
        re.compile(r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE),
    )
    for name, keywords in COMMUNITY_CATEGORIES
)


def classify_category(*texts: str) -> str:
    """Broad community bucket for an event, from its title/description/venue.

    Title and venue are passed first so a concert at "Kulturhaus" files under
    music rather than being dragged into culture by the venue name; callers
    control priority purely through argument order.

    Categories are tried in declaration order, which is what makes the more
    specific bucket win: an event titled "Techno-Ausstellung" is electronic
    music before it is an exhibition, because that list is ordered first.
    """
    for text in texts:
        if not text:
            continue
        haystack = str(text)
        for name, pattern in _CATEGORY_PATTERNS:
            if pattern.search(haystack):
                return name
    return DEFAULT_CATEGORY


CATEGORY_LABELS = {
    "electronic": "Electronic music & dance",
    "music": "Music & nightlife",
    "nightlife": "Music & nightlife",
    "arts": "Arts & exhibitions",
    "culture": "Culture & performance",
    "workshops": "Workshops & learning",
    "outdoor": "Outdoor activities",
    "sports": "Sports",
    "markets": "Markets & festivals",
    "community": "Community & neighbourhood",
    DEFAULT_CATEGORY: "Other distinctive experiences",
}

# Display order for the frontend's category sections.
CATEGORY_ORDER = (
    "electronic", "music", "nightlife", "arts", "culture", "workshops",
    "outdoor", "sports", "markets", "community", DEFAULT_CATEGORY,
)


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, CATEGORY_LABELS[DEFAULT_CATEGORY])


# --------------------------------------------------------------------------
# Venue / district
# --------------------------------------------------------------------------

# Locality names, plus the alternative spellings sites actually print
# (transliterated umlauts, compound forms).
_DISTRICT_ALIASES = {
    "Mitte": ("mitte",),
    "Kreuzberg": ("kreuzberg", "so36", "xo36"),
    "Neukölln": ("neukölln", "neukoelln", "neukoeln"),
    "Friedrichshain": ("friedrichshain", "f'hain", "fhain"),
    "Prenzlauer Berg": ("prenzlauer berg", "prenzlauerberg", "prenzelberg"),
    "Charlottenburg": ("charlottenburg",),
    "Wilmersdorf": ("wilmersdorf",),
    "Wedding": ("wedding",),
    "Moabit": ("moabit",),
    "Schöneberg": ("schöneberg", "schoeneberg", "schoneberg"),
    "Tempelhof": ("tempelhof",),
    "Treptow": ("treptow",),
    "Köpenick": ("köpenick", "koepenick"),
    "Lichtenberg": ("lichtenberg",),
    "Pankow": ("pankow",),
    "Spandau": ("spandau",),
    "Steglitz": ("steglitz",),
    "Zehlendorf": ("zehlendorf",),
    "Reinickendorf": ("reinickendorf",),
    "Marzahn": ("marzahn",),
    "Hellersdorf": ("hellersdorf",),
    "Gesundbrunnen": ("gesundbrunnen",),
    "Rummelsburg": ("rummelsburg",),
    "Adlershof": ("adlershof",),
    "Tiergarten": ("tiergarten",),
}

_DISTRICT_PATTERNS = tuple(
    (district, re.compile(
        r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b", re.IGNORECASE
    ))
    for district, aliases in _DISTRICT_ALIASES.items()
)

BERLIN_DISTRICTS = tuple(_DISTRICT_ALIASES)

# Berlin postcodes, by range, down to the locality a reader would recognise.
# Ranges rather than a full 1:1 table: the goal is a useful district badge, not
# an address-level geocode, and every range below is a real Berlin postcode
# area rather than a guess.
_POSTCODE_RANGES = (
    ((10115, 10179), "Mitte"),
    ((10179, 10249), "Friedrichshain"),
    ((10249, 10439), "Prenzlauer Berg"),
    ((10435, 10559), "Moabit"),
    ((10551, 10629), "Moabit"),
    ((10623, 10719), "Charlottenburg"),
    ((10707, 10719), "Wilmersdorf"),
    ((10777, 10829), "Schöneberg"),
    ((10961, 10999), "Kreuzberg"),
    ((12043, 12059), "Neukölln"),
    ((12099, 12109), "Tempelhof"),
    ((12101, 12107), "Tempelhof"),
    ((12203, 12209), "Steglitz"),
    ((12435, 12439), "Treptow"),
    ((12459, 12489), "Adlershof"),
    ((12555, 12559), "Köpenick"),
    ((12619, 12629), "Hellersdorf"),
    ((12679, 12689), "Marzahn"),
    ((13051, 13059), "Lichtenberg"),
    ((13156, 13159), "Pankow"),
    ((13347, 13359), "Wedding"),
    ((13347, 13355), "Gesundbrunnen"),
    ((13403, 13409), "Reinickendorf"),
    ((13581, 13599), "Spandau"),
    ((14161, 14169), "Zehlendorf"),
    ((10315, 10319), "Lichtenberg"),
    ((10365, 10369), "Rummelsburg"),
)

_POSTCODE_RE = re.compile(r"\b(1[0-4]\d{3})\b")


def _district_for_postcode(code: int) -> Optional[str]:
    for (low, high), district in _POSTCODE_RANGES:
        if low <= code <= high:
            return district
    return None


def district_from_text(*texts: str) -> Optional[str]:
    """The Berlin district the supplied text names, if it names one.

    A named locality wins over a postcode, because a listing that bothers to
    write "in Kreuzberg" is more specific than the postcode of the venue's
    postal address, which sometimes belongs to a neighbouring locality.
    """
    haystack = " ".join(str(t or "") for t in texts)
    if not haystack.strip():
        return None
    for district, pattern in _DISTRICT_PATTERNS:
        if pattern.search(haystack):
            return district
    for match in _POSTCODE_RE.finditer(haystack):
        district = _district_for_postcode(int(match.group(1)))
        if district:
            return district
    return None


# Two districts whose separation is what a reader means by "spread across the
# city"; used only for the diversity check, never to reject an event.
def distinct_districts(events: Iterable[Dict[str, Any]]) -> int:
    return len({
        ev.get("district") for ev in events
        if isinstance(ev, dict) and ev.get("district")
    })


def distinct_categories(events: Iterable[Dict[str, Any]]) -> int:
    return len({
        ev.get("category") for ev in events
        if isinstance(ev, dict) and ev.get("category")
    })
