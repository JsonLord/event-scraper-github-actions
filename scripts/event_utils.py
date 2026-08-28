#!/usr/bin/env python3
"""
Shared normalisation, validation and Berlin-scoping helpers for the event
pipeline.

Every scraper in scripts/ produces event dicts with the same shape, and every
scraper used to normalise (or fail to normalise) them differently: three
different date parsers, two time regexes that matched dotted dates, raw HTML
left in descriptions, and placeholder rows ("Event 12", price 0, venue
"Online") emitted whenever a selector missed. This module is the single place
those decisions live, so a fix lands once for all sources.

The guiding rule is *no invented data*: a field the page did not state is
None or "" and is scored accordingly, never a plausible-looking guess. A row
that cannot be made trustworthy is dropped by validate_event() rather than
published with holes in it.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# --------------------------------------------------------------------------
# Date / time
# --------------------------------------------------------------------------

DATE_ISO_RE = re.compile(r'(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)')
DATE_DE_RE = re.compile(r'\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{2,4})?\b')
DATE_TEXT_RE = re.compile(
    r'\b(\d{1,2})\.?\s*'
    r'(Jan(?:uar)?|Feb(?:ruar)?|M(?:ä|ae)r(?:z)?|Apr(?:il)?|Mai|Jun(?:i)?|Jul(?:i)?|'
    r'Aug(?:ust)?|Sep(?:t(?:ember)?)?|Okt(?:ober)?|Nov(?:ember)?|Dez(?:ember)?|'
    r'January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\.?\s*(?:(\d{4})(?!\d))?\b',
    re.IGNORECASE,
)

# Hour and minute are range-bounded so a dotted date can never be read as a
# time: the old r'\b(\d{1,2}[:.]\d{2})\b' turned "27.08.2026" into "27:08" on
# every berlin-buehnen row. The lookbehind stops a match starting mid-number
# ("08.20" inside "27.08.2026") and the lookahead rejects a third date group.
TIME_RE = re.compile(
    r'(?<![\d.:])([01]?\d|2[0-3])[:.]([0-5]\d)(?!\.\d)(?!\d)\s*(?:(am|pm)\b)?',
    re.IGNORECASE,
)
# "20 Uhr" / "8pm" - an hour with no minutes.
HOUR_ONLY_RE = re.compile(r'(?<![\d.:])([01]?\d|2[0-3])\s*(?:Uhr\b|(am|pm)\b)', re.IGNORECASE)

MONTH_NAME_TO_NUM = {
    "jan": 1, "januar": 1, "january": 1,
    "feb": 2, "februar": 2, "february": 2,
    "mar": 3, "mär": 3, "maer": 3, "märz": 3, "maerz": 3, "march": 3,
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


def _month_from_name(name: str) -> Optional[int]:
    name = name.lower().rstrip(".")
    for key, num in MONTH_NAME_TO_NUM.items():
        if name.startswith(key):
            return num
    return None


def normalize_date(value: Any) -> Optional[str]:
    """Coerce a date-ish value to zero-padded ISO ``YYYY-MM-DD``, or None.

    schema.org ``startDate`` values arrive in every shape a site feels like
    emitting ("2026-8-29", "2026-08-29T21:00+02:00"). Passing those through
    unnormalised broke both the frontend's string date sort and its .ics
    export, which requires exactly 8 digits.
    """
    if not value:
        return None
    text = str(value).strip()
    match = DATE_ISO_RE.match(text) or DATE_ISO_RE.search(text)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_date(text: str, today: Optional[date] = None) -> Optional[str]:
    """Best-effort ISO date from free text, or None when nothing parses.

    Returning None matters: the previous implementation fell back to
    ``datetime.now()``, which turned every unparseable listing into a
    confident-looking event dated today. A missing date is now visible as
    missing and gets dropped by validate_event().
    """
    if not text:
        return None
    today = today or date.today()

    iso = DATE_ISO_RE.search(text)
    if iso:
        found = normalize_date(iso.group(0))
        if found:
            return found

    de = DATE_DE_RE.search(text)
    if de:
        day, month, year_raw = de.group(1), de.group(2), de.group(3)
        try:
            day, month = int(day), int(month)
            if year_raw:
                year = int(year_raw)
                if year < 100:
                    year += 2000
                return date(year, month, day).isoformat()
            return _nearest_occurrence(month, day, today)
        except ValueError:
            pass

    textual = DATE_TEXT_RE.search(text)
    if textual:
        month = _month_from_name(textual.group(2))
        if month:
            try:
                day = int(textual.group(1))
                if textual.group(3):
                    return date(int(textual.group(3)), month, day).isoformat()
                return _nearest_occurrence(month, day, today)
            except ValueError:
                pass
    return None


def _nearest_occurrence(month: int, day: int, today: date) -> Optional[str]:
    """Resolve a year-less date to whichever year puts it closest to today.

    A listing that says "30 Jun" means the nearest 30 June, not "this year,
    and if that already passed then definitely next year" - the old rule
    pushed a 2023 archive page's dates out to 2027.
    """
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - today).days)).isoformat()


def parse_time(text: str) -> str:
    """Extract a 24-hour ``HH:MM`` start time, or "" when none is stated."""
    if not text:
        return ""
    match = TIME_RE.search(text)
    if match:
        hour, minute, meridiem = int(match.group(1)), match.group(2), match.group(3)
        hour = _apply_meridiem(hour, meridiem)
        return f"{hour:02d}:{minute}" if hour is not None else ""

    hour_only = HOUR_ONLY_RE.search(text)
    if hour_only:
        hour = _apply_meridiem(int(hour_only.group(1)), hour_only.group(2))
        if hour is not None:
            return f"{hour:02d}:00"
    return ""


def _apply_meridiem(hour: int, meridiem: Optional[str]) -> Optional[int]:
    if not meridiem:
        return hour
    meridiem = meridiem.lower()
    if hour > 12:
        return hour
    if meridiem == "pm":
        return hour if hour == 12 else hour + 12
    return 0 if hour == 12 else hour


def within_window(iso_date: Optional[str], start: date, end: date) -> bool:
    """True if ``iso_date`` falls inside the inclusive [start, end] window."""
    if not iso_date:
        return False
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return False
    return start <= parsed <= end


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

TAG_RE = re.compile(r'<[^>]+>')
BLOCK_TAG_RE = re.compile(r'<\s*/?\s*(?:p|br|div|li|tr|h[1-6])\b[^>]*>', re.IGNORECASE)

# Listing chrome that carries no information about the event itself.
BOILERPLATE_RE = re.compile(
    r'\b(?:'
    r'zur\s+veranstaltung|zum\s+spielplan|mehr\s+(?:erfahren|infos?)|weiterlesen|'
    r'tickets?\s+kaufen|jetzt\s+buchen|read\s+more|learn\s+more|buy\s+tickets?|'
    r'pick\s+of\s+the\s+day|sponsored|anzeige'
    r')\b[\s:\u2192>-]*',
    re.IGNORECASE,
)


def clean_text(raw: Any, max_length: Optional[int] = None) -> str:
    """Turn scraped markup or concatenated listing text into readable prose.

    Handles the three ways descriptions arrived broken: raw HTML from
    schema.org ``description`` fields ("<p>Guille Pinet is...<br />"),
    numeric entities that survived one unescape pass ("&#8211;", "&#038;"),
    and phrase-level duplication produced by ``get_text(" ")`` over nested
    markup ("Theater Theater Musiktheater Musiktheater").
    """
    if not raw:
        return ""
    text = str(raw)

    # Entities are frequently double-encoded ("&amp;#8211;"); unescape twice.
    text = html.unescape(html.unescape(text))
    text = BLOCK_TAG_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    text = BOILERPLATE_RE.sub(" ", text)
    text = re.sub(r'[\u200b\u00ad]', '', text)
    text = re.sub(r'\s+', ' ', text).lstrip(" \t\n\u2192|").rstrip(" \t\n\u2192|;,:-")
    text = collapse_repeated_phrases(text)

    if max_length and len(text) > max_length:
        text = text[:max_length].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return text


def collapse_repeated_phrases(text: str, max_phrase: int = 6) -> str:
    """Collapse immediately repeated word runs ("Theater Theater" -> "Theater").

    Only *adjacent* repetitions are removed, and a single repeated word must
    be at least 4 characters, so "Bye Bye" survives while listing markup that
    renders each tag label twice does not. A genuine doubled name like
    "New York New York" would be collapsed; that is rare enough to accept in
    exchange for readable descriptions on every theatre and club source.
    """
    tokens = text.split()
    changed = True
    while changed:
        changed = False
        for n in range(max_phrase, 0, -1):
            i = 0
            while i + 2 * n <= len(tokens):
                first = [t.lower() for t in tokens[i:i + n]]
                second = [t.lower() for t in tokens[i + n:i + 2 * n]]
                if first == second and len("".join(first)) >= 4:
                    del tokens[i + n:i + 2 * n]
                    changed = True
                else:
                    i += 1
    return " ".join(tokens)


def strip_title_from_description(title: str, description: str) -> str:
    """Drop a leading repetition of the title from its own description."""
    if not title or not description:
        return description
    lowered_title = title.lower().strip()
    lowered_desc = description.lower()
    if lowered_desc.startswith(lowered_title):
        remainder = description[len(title):].lstrip(" -–—:|,.")
        if len(remainder) >= 20:
            return remainder
    return description


# --------------------------------------------------------------------------
# Titles
# --------------------------------------------------------------------------

SYNTHETIC_TITLE_RE = re.compile(r'^(?:event|veranstaltung|item|result)\s*[#-]?\s*\d+$', re.IGNORECASE)
URL_TITLE_RE = re.compile(r'^(?:url\s+source|title|source)\s*:|^https?://', re.IGNORECASE)
DATE_TITLE_RE = re.compile(r'^\s*(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})')

# Navigation and page furniture that the heuristic scan picks up as "events".
JUNK_TITLES = {
    "warning", "highlights", "programm", "program", "spielplan", "zum spielplan",
    "kalender", "calendar", "events", "veranstaltungen", "tickets", "newsletter",
    "impressum", "datenschutz", "kontakt", "menu", "home", "startseite",
    "more", "mehr", "alle events", "all events", "comment", "kommentar",
    "untitled event", "unknown event",
}


def looks_synthetic_title(title: str) -> bool:
    """True for placeholder, navigational or non-title strings.

    ``f"Event {i+1}"`` fallbacks in the Meetup and Eventbrite scrapers put 12
    contentless rows straight onto the front page; Jina's "URL Source: ..."
    header line became two more.
    """
    if not title:
        return True
    stripped = title.strip()
    if len(stripped) < 3:
        return True
    if SYNTHETIC_TITLE_RE.match(stripped) or URL_TITLE_RE.match(stripped):
        return True
    if stripped.lstrip("#").strip().lower() in JUNK_TITLES:
        return True
    # A title that is only a date/time and punctuation carries no name.
    if DATE_TITLE_RE.match(stripped) and not re.search(r'[A-Za-zÄÖÜäöüß]{4,}', stripped):
        return True
    return False


def title_looks_noisy(title: str) -> bool:
    """True if a title reads as concatenated listing text rather than a name."""
    if not title:
        return True
    if len(title) > 90:
        return True
    if DATE_TITLE_RE.match(title.strip()):
        return True
    if TIME_RE.search(title) or DATE_ISO_RE.search(title) or DATE_DE_RE.search(title):
        return True
    low = title.lower()
    return any(b in low for b in ("pick of the day", "sponsored", "today,", "tomorrow,"))


def title_from_slug(url: str) -> Optional[str]:
    """Derive a readable title from an event-detail URL slug."""
    if not url:
        return None
    path = urlparse(url).path.rstrip("/")
    segment = path.rsplit("/", 1)[-1]
    if "-" not in segment:
        return None
    segment = re.sub(r'-\d+$', '', segment)
    segment = re.sub(r'-tickets?$', '', segment, flags=re.IGNORECASE)
    words = [w for w in segment.split("-") if w and not w.isdigit()]
    if len(words) < 2:
        return None
    return " ".join(w.capitalize() for w in words)


# Listing rows shaped "27.08.2026, 19:30| Theater am Potsdamer Platz" put the
# date and venue where the name belongs; the real name follows in the card
# text. Recover both rather than publishing the date as the title.
DATE_VENUE_TITLE_RE = re.compile(
    r'^\s*\d{1,2}\.\d{1,2}\.\d{2,4},?\s*\d{1,2}[:.]\d{2}\s*\|\s*(?P<venue>.+?)\s*$'
)


def split_date_venue_title(title: str) -> Optional[str]:
    """Return the venue embedded in a "<date>, <time>| <venue>" pseudo-title."""
    match = DATE_VENUE_TITLE_RE.match(title or "")
    return match.group("venue").strip() if match else None


def recover_title_from_description(description: str, venue: str) -> Optional[str]:
    """Pull the event name out of a card whose title slot held date + venue.

    Listing markup repeats the event name (once as the card heading, once as
    the link label, once above the blurb) while the surrounding chrome varies,
    so the longest phrase occurring more than once is a reliable pick for the
    name. Anchoring on the venue and reading to the next sentence break
    instead swallowed the blurb ("Emil und die Detektive Nach dem
    Kinderbuch-Klassiker von Erich Kaestner").
    """
    if not description:
        return None
    tokens = description.split()
    venue_tokens = [t.lower() for t in (venue or "").split()]

    best: Optional[str] = None
    for length in range(min(12, len(tokens) // 2), 1, -1):
        for start in range(len(tokens) - length + 1):
            phrase = tokens[start:start + length]
            lowered = [t.lower() for t in phrase]
            if lowered == venue_tokens:
                continue
            occurrences = sum(
                1 for i in range(len(tokens) - length + 1)
                if [t.lower() for t in tokens[i:i + length]] == lowered
            )
            if occurrences < 2:
                continue
            candidate = " ".join(phrase).strip(" -\u2013\u2014:|,.")
            # The repeated run often leads with the venue ("BlueMax Theater
            # Sister Act"); the venue belongs in its own column, not the name.
            if venue and candidate.lower().startswith(venue.lower()):
                candidate = candidate[len(venue):].strip(" -\u2013\u2014:|,.")
            if looks_synthetic_title(candidate) or title_looks_noisy(candidate):
                continue
            best = candidate
            break
        if best:
            break
    return best


# --------------------------------------------------------------------------
# Venue
# --------------------------------------------------------------------------

# A venue is only read where a delimiter actually closes it. Guessing the
# extent of an unterminated run reliably swallowed the event name after it
# ("Luftschloss Tempelhofer Feld Emil und die Detektive"), so both patterns
# below require a hard right-hand boundary and return "" otherwise.
VENUE_BETWEEN_PIPES_RE = re.compile(
    r'\d{1,2}[:.]\d{2}\s*(?:Uhr)?\s*\|\s*(?P<venue>[^|]{3,60}?)\s*\|'
)
# "<title> Deutsche Oper Berlin Sa, 29. Aug 2026, 12:00" - the venue sits
# between the event name and the weekday-qualified date.
VENUE_BEFORE_WEEKDAY_RE = re.compile(
    r'(?P<venue>.{3,60}?)\s*(?:Mo|Di|Mi|Do|Fr|Sa|So|Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,\s*\d{1,2}\.',
    re.IGNORECASE,
)
VENUE_BEFORE_PRICE_RE = re.compile(
    r'(?P<venue>.{3,60}?)\s*(?:'
    r'\d+(?:[.,]\d{2})?\s*(?:€|EUR)|free\s+admission|freier\s+eintritt|kostenlos|eintritt\s+frei'
    r')',
    re.IGNORECASE,
)
VENUE_STOPWORDS = {"online", "various", "verschiedene", "tba", "tbd", "berlin", "n/a", "-"}


def extract_venue(description: str = "", title: str = "") -> str:
    """Recover a venue name from listing text, or "" when it is not stated.

    Both the heuristic and Jina extractors hardcoded ``"venue": ""``, leaving
    the Location column blank on 62% of published rows even though the venue
    sat in text they had already captured. Two shapes are recognised:
    a pipe-delimited "| <venue> |" run, and - on listing rows shaped
    "<title> <venue> <price>" - the text between the event's own title and
    its price marker.
    """
    if description:
        match = VENUE_BETWEEN_PIPES_RE.search(description)
        if match:
            venue = _clean_venue_candidate(match.group("venue"))
            if venue:
                return venue

    if description and title:
        after_title = re.split(re.escape(title), description, maxsplit=1, flags=re.IGNORECASE)
        if len(after_title) > 1:
            remainder = after_title[1].lstrip(" -|,")
            for pattern in (VENUE_BEFORE_PRICE_RE, VENUE_BEFORE_WEEKDAY_RE):
                match = pattern.match(remainder)
                if match:
                    venue = _clean_venue_candidate(match.group("venue"))
                    if venue:
                        return venue
    return ""


def _clean_venue_candidate(raw: str) -> str:
    venue = clean_text(raw)
    if not venue or venue.lower() in VENUE_STOPWORDS:
        return ""
    # Venue names are short; a long run is listing text, not a place.
    if len(venue.split()) > 6:
        return ""
    return venue[:80]


def normalize_venue(venue: Any) -> str:
    """Blank out placeholder venues so they are not published as facts."""
    cleaned = clean_text(venue)
    if not cleaned or cleaned.lower() in VENUE_STOPWORDS:
        return ""
    return cleaned[:80]


# --------------------------------------------------------------------------
# Price
# --------------------------------------------------------------------------

PRICE_RE = re.compile(
    r'(?:€\s*(\d+(?:[.,]\d{1,2})?)|(\d+(?:[.,]\d{1,2})?)\s*€|(\d+(?:[.,]\d{1,2})?)\s*EUR)',
    re.IGNORECASE,
)
FREE_RE = re.compile(
    r'\b(?:free\s+(?:admission|entry)|free|gratis|kostenlos|eintritt\s+frei|freier\s+eintritt|umsonst)\b',
    re.IGNORECASE,
)


def parse_price(text: str) -> Optional[float]:
    """Price in EUR, 0.0 when explicitly free, or None when not stated.

    None is meaningful and must not be coerced to 0.0: the Meetup and
    Eventbrite scrapers defaulted unknown prices to 0, which labelled every
    placeholder row "Free" and sent it to the top of the ranking.
    """
    if not text:
        return None
    match = PRICE_RE.search(text)
    if match:
        raw = next(g for g in match.groups() if g)
        try:
            value = float(raw.replace(',', '.'))
        except ValueError:
            return None
        # "0,00 € to 15,00 €" ranges read as free at the low end.
        return value
    if FREE_RE.search(text):
        return 0.0
    return None


def format_price_label(price: Optional[float]) -> str:
    """Human-readable price. Keeps cents intact - the old rstrip("0") chain
    rendered €12.10 as "€12.1" and €9.50 as "€9.5"."""
    if price is None:
        return "Check site"
    if price <= 0:
        return "Free"
    if float(price).is_integer():
        return f"€{int(price)}"
    return f"€{price:.2f}"


# --------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------

TRACKING_PARAMS = {
    "recid", "recsource", "searchid", "eventorigin", "gclid", "fbclid", "mc_cid",
    "mc_eid", "ref", "aff", "_ga",
}


def clean_url(url: str) -> str:
    """Drop tracking query parameters while keeping functional ones."""
    if not url:
        return ""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    if not parts.scheme.startswith("http"):
        return url
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunparse(parts._replace(query=urlencode(kept)))


def is_detail_link(url: str, source_url: str) -> bool:
    """True if ``url`` points at an event page rather than back at the listing."""
    if not url or not url.startswith("http"):
        return False
    return clean_url(url).rstrip("/") != clean_url(source_url).rstrip("/")


# --------------------------------------------------------------------------
# Berlin scoping
# --------------------------------------------------------------------------

BERLIN_DISTRICTS = (
    "berlin", "kreuzberg", "neukölln", "neukoelln", "friedrichshain", "prenzlauer berg",
    "charlottenburg", "wilmersdorf", "wedding", "moabit", "schöneberg", "schoeneberg",
    "tempelhof", "treptow", "köpenick", "koepenick", "lichtenberg", "pankow", "spandau",
    "steglitz", "zehlendorf", "reinickendorf", "marzahn", "hellersdorf", "mitte",
    "alexanderplatz", "potsdamer platz", "kurfürstendamm", "kudamm", "kottbusser",
    "warschauer", "oberbaum", "tiergarten", "gesundbrunnen", "rummelsburg", "adlershof",
)
_BERLIN_RE = re.compile(r'\b(?:' + '|'.join(re.escape(d) for d in BERLIN_DISTRICTS) + r')', re.IGNORECASE)
_BERLIN_POSTCODE_RE = re.compile(r'\b1[0-4]\d{3}\b')


def has_berlin_signal(event: Dict[str, Any]) -> bool:
    """True if anything about the event ties it to Berlin.

    Applied only to the global platforms (Meetup, Eventbrite), whose "popular
    nearby" carousels geolocate the US-hosted runner: the last published run
    led with Golden Gate Park, North Beach and 555 Mission Street under a
    ``userFreeform=Berlin`` query. Berlin-specific sources are trusted by
    construction, so an event genuinely titled "Amsterdam Techno Records" at
    ://about blank is not thrown away.
    """
    # source_url is deliberately excluded: every Meetup/Eventbrite listing URL
    # already contains "Berlin" as its query, so including it made this gate
    # pass exactly the San Francisco rows it exists to reject.
    haystack = " ".join(
        str(event.get(field) or "")
        for field in ("title", "description", "venue", "category", "url")
    )
    if _BERLIN_RE.search(haystack) or _BERLIN_POSTCODE_RE.search(haystack):
        return True
    return ".de/" in haystack or haystack.endswith(".de")


# --------------------------------------------------------------------------
# Validation and de-duplication
# --------------------------------------------------------------------------

def validate_event(
    event: Dict[str, Any],
    source_url: str,
    window_start: date,
    window_end: date,
    max_price: float = 15.0,
    require_berlin_signal: bool = False,
) -> Optional[Dict[str, Any]]:
    """Normalise one scraped row, or return None if it cannot be trusted.

    A row is rejected when it has no usable name, no date inside the target
    week, a price above the cutoff, or - for the global platforms - nothing
    tying it to Berlin. Everything that survives has normalised, zero-padded
    dates, 24-hour times, cleaned text and honest None/"" for anything the
    page did not state.
    """
    title = clean_text(event.get("title"), max_length=180)
    description = clean_text(event.get("description"), max_length=400)
    url = clean_url(str(event.get("url") or "").strip())
    source_url = clean_url(source_url or str(event.get("source_url") or ""))

    venue = normalize_venue(event.get("venue"))

    # "27.08.2026, 19:30| Uferstudios" is a date plus a venue, not a name.
    embedded_venue = split_date_venue_title(title)
    if embedded_venue:
        venue = venue or normalize_venue(embedded_venue)
        recovered = recover_title_from_description(description, embedded_venue)
        title = recovered or ""

    if title_looks_noisy(title):
        title = title_from_slug(url) or title

    if looks_synthetic_title(title):
        return None

    if not venue:
        venue = extract_venue(description, title)

    iso_date = normalize_date(event.get("date")) or parse_date(str(event.get("date") or ""))
    if not iso_date:
        iso_date = parse_date(description)
    if not within_window(iso_date, window_start, window_end):
        return None

    event_time = (
        parse_time(str(event.get("time") or ""))
        or parse_time(str(event.get("date") or ""))
        or parse_time(description)
    )

    price = event.get("price")
    if isinstance(price, str):
        price = parse_price(price)
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
    if price is not None and price > max_price:
        return None

    description = strip_title_from_description(title, description)

    normalized = {
        "title": title,
        "date": iso_date,
        "time": event_time,
        "price": price,
        "category": clean_text(event.get("category"), max_length=80),
        "description": description,
        "url": url if url.startswith("http") else source_url,
        "venue": venue,
        "source_url": source_url,
        "has_detail_link": is_detail_link(url, source_url),
    }

    # A row with neither a name we trust nor a link to verify it is not worth
    # publishing; one with a real name but no deep link is kept and penalised.
    if not normalized["has_detail_link"] and title_looks_noisy(title):
        return None

    if require_berlin_signal and not has_berlin_signal(normalized):
        return None

    return normalized


def validate_events(
    events: Iterable[Dict[str, Any]],
    source_url: str,
    window_start: date,
    window_end: date,
    max_price: float = 15.0,
    require_berlin_signal: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """Validate a batch; returns (kept, rejected_count)."""
    kept, rejected = [], 0
    for raw in events or []:
        cleaned = validate_event(
            raw, source_url, window_start, window_end, max_price, require_berlin_signal
        )
        if cleaned:
            kept.append(cleaned)
        else:
            rejected += 1
    return kept, rejected


def dedupe_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicates by detail URL, then by (normalised title, date).

    Keying on the raw title and date alone let the same event through twice
    whenever two sources formatted the date differently ("2026-8-29" vs
    "2026-08-29"); normalisation upstream plus a URL key closes both gaps.
    """
    seen_urls, seen_keys, out = set(), set(), []
    for event in events or []:
        url = event.get("url") or ""
        if event.get("has_detail_link") and url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        key = (re.sub(r'\W+', '', str(event.get("title", "")).lower()), event.get("date"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(event)
    return out


def scrape_window(days: int, today: Optional[date] = None) -> Tuple[date, date]:
    """The inclusive date window a run should publish.

    ``--date-days`` was previously accepted and documented as
    "informational", so nothing filtered on it: the last run shipped events
    from 2019, 2023 and 2027 under a heading promising the coming week.
    """
    today = today or date.today()
    return today, today + timedelta(days=max(0, days))
