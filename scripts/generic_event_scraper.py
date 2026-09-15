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
  3. Jina Reader, asked for HTML and re-run through 1 and 2 (only attempted
     if JINA_API_KEY is set; anonymous Jina requests are unreliably blocked
     by IP reputation). This is what gets past an anti-bot interstitial that
     refuses this network but not Jina's, and it is measurably the better of
     the two fallbacks - see scripts/fetch_strategy_probe.py.
  4. CloakBrowser (stealth headless Chromium) render, then re-run 1 and 2
     against the rendered DOM. Last because it is slower and has not
     uniquely rescued a site in any probe run; kept because it is the only
     fallback that needs no third-party service.

Real-world extraction quality will vary a lot by site. Sites that still come
back empty are picked up afterwards by scripts/recover_failed.py, which walks
from the listing to the individual event pages it links to and reads those
instead - an event's own page is usually better marked up than the listing.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from event_utils import (  # noqa: E402
    DATE_DE_RE,
    DATE_ISO_RE,
    DATE_TEXT_RE,
    DAY_HEADING_RE,
    FREE_RE,
    MONTH_HEADING_RE,
    PRICE_RE,
    TIME_RE,
    DEFAULT_MAX_PRICE,
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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# A bare User-Agent is not enough to look like a browser any more. Several
# sources answered a UA-only GET with 403 and nothing else - rausgegangen.de,
# the single biggest source in the matrix, returned a Bunny Shield challenge
# on every run. Sending the header set a real Chrome navigation sends (Accept,
# Accept-Language, Sec-Fetch-*) gets the same URL back as a 200 with the full
# listing. Verified live against rausgegangen.de: 403 -> 200.
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    # German first: several Berlin sites serve a different (and richer)
    # listing to a de-DE client than to an unspecified one.
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

BOT_CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "cf-browser-verification",
    "checking your browser",
    "access denied",
    # Bunny Shield's proof-of-work interstitial (rausgegangen.de).
    "establishing a secure connection",
    ".bunny-shield",
    "enable javascript and cookies to continue",
    # Eventbrite's interstitial, which it serves to datacenter IPs and to
    # Jina's proxy alike - the page title is the only thing that says so.
    "human verification",
)

# Upper bound on rows taken from one source. Generous rather than tight: it
# exists to stop a pathological page from ballooning a run, not to trim
# results, and the date window plus validation do the real filtering.
MAX_EVENTS_PER_SOURCE = 400

# Cap on extra per-event detail-page fetches for price enrichment (see
# enrich_missing_prices below). Bounds one source's run time; the date window
# and validation still do the real filtering afterwards.
MAX_PRICE_ENRICH_FETCHES = 40

EVENT_CLASS_HINTS = (
    "event", "teaser", "views-row", "card", "listing", "termin",
    "veranstaltung", "programme-item", "program-item", "spielplan",
    "show-item",
    # Added after measuring live: ZK/U and SAVVY Contemporary both build their
    # whole programme out of ".list-item" and yielded nothing at all, because
    # "listing" does not match "list-item".
    "list-item", "listitem", "agenda", "kalender", "calendar",
    "vorstellung", "produktion", "spieltag",
)

# Hrefs that lead to a real event page rather than back into site navigation.
DETAIL_HREF_HINTS = (
    "/event", "/events/", "/veranstaltung", "/termin", "/programm", "/show/",
    "/produktion", "/stueck", "/konzert", "/spielplan/event", "/e/", "/tickets",
    # "/programm/" missed HAU's English detail links ("/en/programme/pdetail/"),
    # which is why a page full of events produced no candidates at all.
    "/programme", "/timeline/", "/detail", "/agenda/", "/vorstellung",
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
    head = html[:4000].lower()
    return any(marker in head for marker in BOT_CHALLENGE_MARKERS)


# One shared session per process, so the listing fetch and every detail-page
# fetch that follows it reuse the same cookies and connection. Built on first
# use rather than at import, so the parsing paths stay importable without the
# HTTP stack (the extraction tests stub `requests` out entirely).
_SESSION = None


def get_session():
    """A session that presents itself as a browser and keeps its cookies.

    Cookies matter as much as the headers: sites that set a consent or
    session cookie on the listing page hand the detail pages fetched during
    price enrichment a different (often blocked) response without it.
    """
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(BROWSER_HEADERS)
    return _SESSION


def fetch_plain(url: str, timeout: int = 20, retries: int = 2, quiet: bool = False) -> Optional[str]:
    """GET a page as a browser would, returning the body or None.

    A non-2xx response is not discarded outright: sites behind an anti-bot
    interstitial answer 403 with a real HTML body, and it is
    is_bot_challenge() - not the status code - that decides whether the body
    is usable. Handing the body back also lets the caller escalate to the
    rendered-DOM tier for the right reason.
    """
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = get_session().get(url, timeout=timeout, allow_redirects=True)
        except requests.exceptions.RequestException as e:
            # Connection resets are common enough on these hosts that a single
            # attempt turns a working source into a silent zero.
            last_error = e
            if attempt < retries:
                time.sleep(attempt)
            continue

        if resp.status_code >= 400:
            # quiet=True for endpoints we probe speculatively (the WordPress
            # REST paths), where a 404 just means "this plugin isn't here".
            (logger.debug if quiet else logger.warning)(
                f"GET {url} returned HTTP {resp.status_code}"
            )
            body = resp.text or ""
            # A 4xx/5xx body is only worth keeping when it is a challenge page
            # the caller needs to recognise; an error page has nothing in it.
            return body if body and is_bot_challenge(body) else None
        return resp.text

    logger.warning(f"Plain GET failed for {url}: {last_error}")
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


def extract_time_element_events(
    html: str, source_url: str, max_events: int = MAX_EVENTS_PER_SOURCE
) -> List[Dict[str, Any]]:
    """Build events from ``<time datetime="...">`` markers and their cards.

    ``<time datetime>`` is the standard machine-readable date carrier and is
    far more reliable than scraping a rendered date string, but nothing in the
    pipeline looked at it. Several theatre sites publish their whole programme
    this way and yielded nothing at all: Volksbuehne exposes 168 such markers
    (and 96 event links) yet the class-hint scan found zero candidates,
    because its cards carry no event-ish class and no date text inside them.
    """
    soup = BeautifulSoup(html, "lxml")
    events = []
    for marker in soup.find_all(attrs={"datetime": True}):
        iso = normalize_date(marker.get("datetime"))
        if not iso:
            continue

        # Walk up to the smallest ancestor that also carries a link, which is
        # the event card; stop before swallowing the whole listing.
        card, link = marker, None
        for _ in range(6):
            card = card.parent
            if card is None:
                break
            link = card.find("a", href=True)
            if link is not None:
                break
        if card is None:
            continue

        card_text = card.get_text(" ", strip=True)
        if len(card_text) > 3000:
            continue

        title = ""
        heading = card.find(["h1", "h2", "h3", "h4", "h5"])
        if heading:
            title = heading.get_text(" ", strip=True)
        if not title and link is not None:
            title = link.get_text(" ", strip=True)
        if not title:
            title = card_text[:120]
        if title_looks_noisy(title):
            title = title_from_slug(urljoin(source_url, link["href"]) if link else "") or title

        events.append({
            "title": clean_text(title, max_length=200),
            "date": iso,
            "time": parse_time(marker.get("datetime")) or parse_time(card_text),
            "price": parse_price(card_text),
            "category": "",
            "description": clean_text(card_text, max_length=400),
            "url": _best_detail_url([card, card.parent], source_url),
            "venue": "",
            "source_url": source_url,
        })
        if len(events) >= max_events:
            break
    return events


def _has_date_text(text: str) -> bool:
    return bool(
        DATE_ISO_RE.search(text) or DATE_DE_RE.search(text) or DATE_TEXT_RE.search(text)
    )


def _subtree_span(element, positions: Dict[int, int]) -> int:
    """Document position of the last node inside ``element``.

    Used to decide whether a marker sits inside a card (a day number printed
    on the card itself) rather than before it.
    """
    last = positions.get(id(element), -1)
    for descendant in element.find_all(True):
        last = max(last, positions.get(id(descendant), last))
    return last


# Elements allowed to act as a calendar heading. Restricting markers to real
# headings and date-ish containers keeps a stray "12" in a footer from being
# read as a day of the month.
MARKER_CLASS_HINTS = (
    "day", "tag", "date", "datum", "month", "monat", "kalender", "calendar",
    "week", "woche", "heading", "headline",
)


def _is_marker_element(element) -> bool:
    if element.name in ("h1", "h2", "h3", "h4", "h5", "h6", "th", "caption", "time"):
        return True
    classes = " ".join(element.get("class", [])).lower()
    return any(hint in classes for hint in MARKER_CLASS_HINTS)


def extract_calendar_events(
    html: str, source_url: str, max_events: int = MAX_EVENTS_PER_SOURCE
) -> List[Dict[str, Any]]:
    """Read calendars that print the month once and only a day number per row.

    This is the standard German theatre/venue programme layout and nothing in
    the pipeline could read it: HAU Hebbel am Ufer publishes 35 events under a
    single "September 2026" heading with "Sat 12" day headings, and the
    Renaissance-Theater 137 showtimes the same way. Every card states a time
    and a title but no date at all, so parse_date found nothing on the card,
    nothing on its ancestors, and both sites extracted zero events.

    The fix is to carry the heading context down: walk the document in order,
    remember the most recent month and day heading, and stamp each card with
    the date they spell out together.
    """
    soup = BeautifulSoup(html, "lxml")
    elements = soup.find_all(True)
    positions = {id(el): i for i, el in enumerate(elements)}

    month_markers: List[tuple] = []   # (position, month_name, year or None)
    day_markers: List[tuple] = []     # (position, day number)
    for element in elements:
        if not _is_marker_element(element):
            continue
        text = element.get_text(" ", strip=True)
        if not text or len(text) > 30:
            continue
        month = MONTH_HEADING_RE.match(text)
        if month:
            month_markers.append((positions[id(element)], month.group(1), month.group(2)))
            continue
        day = DAY_HEADING_RE.match(text)
        if day and 1 <= int(day.group(1)) <= 31:
            day_markers.append((positions[id(element)], int(day.group(1))))

    if not month_markers or not day_markers:
        return []

    cards = _calendar_cards(soup)
    events = []
    for card in cards[:max_events]:
        text = card.get_text(" ", strip=True)
        # A card that states its own full date needs no heading context, and
        # the other strategies already handle it.
        if parse_date(text):
            continue
        span = _subtree_span(card, positions)
        day_marker = _latest_before(day_markers, span)
        month_marker = _latest_before(month_markers, span)
        if not day_marker or not month_marker:
            continue
        (day,), (month_name, year) = day_marker, month_marker
        iso = parse_date(f"{day}. {month_name} {year}" if year else f"{day}. {month_name}")
        if not iso:
            continue

        scopes = [card, card.parent]
        event_url = _best_detail_url(scopes, source_url)
        title = _title_from_scopes(scopes, text, event_url)
        events.append({
            "title": clean_text(title, max_length=200),
            "date": iso,
            "time": parse_time(text),
            "price": parse_price(text),
            "category": "",
            "description": clean_text(text, max_length=400),
            "url": event_url,
            "venue": "",
            "source_url": source_url,
        })
    return events


def _latest_before(markers: List[tuple], position: int) -> Optional[tuple]:
    """The payload of the last marker at or before ``position``, or None.

    ``markers`` is in document order, so the scan can stop at the first one
    that sits past the card.
    """
    best = None
    for marker in markers:
        if marker[0] > position:
            break
        best = marker
    return best[1:] if best else None


def _links_to_detail(href: str) -> bool:
    """True for an href that leads to one event's own page."""
    href = (href or "").strip().lower()
    if not href or NON_DETAIL_HREF_RE.search(href):
        return False
    return any(hint in href for hint in DETAIL_HREF_HINTS)


def _calendar_cards(soup) -> List[Any]:
    """Innermost elements that look like one row of a calendar.

    A row qualifies on either an event-ish class or a link into the site's own
    event pages, and must state a time, date or price - which is what keeps
    navigation menus and footers out.
    """
    candidates = []
    for element in soup.find_all(["li", "div", "article", "tr", "section"]):
        classes = " ".join(element.get("class", [])).lower()
        if not any(hint in classes for hint in EVENT_CLASS_HINTS):
            if not any(_links_to_detail(anchor["href"]) for anchor
                       in element.find_all("a", href=True)):
                continue
        text = element.get_text(" ", strip=True)
        if not (15 <= len(text) <= 2000):
            continue
        if not (TIME_RE.search(text) or PRICE_RE.search(text) or FREE_RE.search(text)
                or _has_date_text(text)):
            continue
        candidates.append(element)

    return _innermost(candidates)


def _innermost(candidates: List[Any]) -> List[Any]:
    """Keep only candidates that wrap no other candidate.

    Stricter than the class-hint scan's "two or more children means a list"
    rule, and deliberately so: on a calendar a wrapper very often holds
    exactly one row (HAU's <li class="day"> around a single <li class="item">
    on a quiet evening), and keeping the wrapper took the day heading -
    "Sun 13" - as the event's name. The row is always the more specific
    element, and candidacy here already requires a time, date or price, so a
    nested candidate is a real row rather than a stray fragment.
    """
    candidate_ids = {id(el) for el in candidates}
    return [
        element for element in candidates
        if not any(
            id(descendant) in candidate_ids and descendant is not element
            for descendant in element.find_all(True)
        )
    ]


def _title_from_scopes(scopes, fallback_text: str, event_url: str) -> str:
    """Best available name for a card: a heading, else a link, else its text."""
    for scope in scopes:
        if not scope:
            continue
        for heading in scope.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            text = heading.get_text(" ", strip=True)
            if text and not title_looks_noisy(text):
                return text
    for scope in scopes:
        if not scope:
            continue
        for anchor in scope.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True)
            if text and len(text) > 3 and not title_looks_noisy(text):
                return text
    slug = title_from_slug(event_url)
    return slug or fallback_text[:120]


def extract_block_events(
    html: str, source_url: str, max_events: int = MAX_EVENTS_PER_SOURCE
) -> List[Dict[str, Any]]:
    """Find dated events in pages whose markup carries no event-ish class.

    Page builders name everything after themselves: every block on
    reinickendorf-classics.de is an "et_pb_text" (Divi), so a scan keyed on
    class names saw nothing, even though each event plainly states
    "Samstag, 19.09.2026 - 20:00 Uhr" right under its title. This strategy
    ignores classes entirely: it starts from the date text itself and walks
    out to the smallest block that also carries a title or a link.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "footer", "head"]):
        tag.decompose()

    cards, seen = [], set()
    for text_node in soup.find_all(string=True):
        raw = str(text_node).strip()
        if len(raw) < 6 or len(raw) > 200 or not _has_date_text(raw):
            continue
        node = text_node.parent
        for _ in range(6):
            if node is None or node.name in ("body", "html", "[document]"):
                break
            block_text = node.get_text(" ", strip=True)
            if len(block_text) > 1200:
                break
            has_name = node.find(["h1", "h2", "h3", "h4", "h5", "h6"]) or node.find("a", href=True)
            if has_name and len(block_text) >= 20:
                if id(node) not in seen:
                    seen.add(id(node))
                    cards.append(node)
                break
            node = node.parent

    events = []
    for card in _innermost(cards)[:max_events]:
        text = card.get_text(" ", strip=True)
        iso = parse_date(text)
        if not iso:
            continue
        scopes = [card, card.parent, getattr(card.parent, "parent", None)]
        event_url = _best_detail_url(scopes, source_url)
        title = _title_from_scopes(scopes, text, event_url)
        events.append({
            "title": clean_text(title, max_length=200),
            "date": iso,
            "time": parse_time(text),
            "price": parse_price(text),
            "category": "",
            "description": clean_text(text, max_length=400),
            "url": event_url,
            "venue": "",
            "source_url": source_url,
        })
    return events


def extract_heuristic_events(html: str, source_url: str, max_events: int = MAX_EVENTS_PER_SOURCE) -> List[Dict[str, Any]]:
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

    # Keep whole event cards, not fragments - but a *list container* usually
    # carries an event-ish class too, and "outermost wins" then collapsed a
    # whole listing into one row: stadtmuseum went from 42 candidates to 2 and
    # Eventbrite from 27 to 3. An element holding two or more other candidates
    # is a container, so prefer its children; one holding at most a single
    # candidate is a card, so prefer it over its fragments.
    candidate_set = {id(el) for el, _ in candidates}
    kept = []
    for el, text in candidates:
        contained = sum(
            1 for descendant in el.find_all(True)
            if id(descendant) in candidate_set and descendant is not el
        )
        if contained >= 2:
            continue  # a list of events, not an event
        if any(
            el is not other
            and other in el.parents
            and sum(1 for d in other.find_all(True) if id(d) in candidate_set and d is not other) < 2
            for other, _ in candidates
        ):
            continue  # a fragment inside a card that was itself kept
        kept.append((el, text))

    events = []
    seen_titles = set()
    # rausgegangen's date view yields 205 valid candidates; a hardcoded [:60]
    # silently discarded 71% of the biggest source in the matrix.
    for el, text in kept[:max_events]:
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
        # The card's own text is authoritative. Ancestor text is consulted only
        # when the card states no date at all (a calendar cell whose day
        # heading sits on a parent), never merged in alongside it.
        event_date = parse_date(text)
        if not event_date:
            anc = el
            for _ in range(5):
                anc = getattr(anc, "parent", None)
                if not anc:
                    break
                event_date = parse_date(anc.get_text(" ", strip=True)[:120])
                if event_date:
                    break

        description = clean_text(text, max_length=400)
        events.append({
            "title": title[:200],
            "date": event_date or "",
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


# WordPress event plugins publish the whole programme through the REST API,
# fully structured, even when the page itself renders its calendar in
# JavaScript and serves a scraper nothing. theclubmap.com is exactly that
# case: the listing is an EventON widget loaded over AJAX (0 events from the
# HTML, every run), while /wp-json/wp/v2/ajde_events returns every event with
# a Unix start timestamp.
WORDPRESS_EVENT_ENDPOINTS = (
    "/wp-json/wp/v2/ajde_events?per_page=100",      # EventON
    "/wp-json/tribe/events/v1/events?per_page=50",  # The Events Calendar
)


def _from_eventon(records: List[Dict[str, Any]], source_url: str) -> List[Dict[str, Any]]:
    events = []
    for record in records:
        if not isinstance(record, dict):
            continue
        meta = record.get("meta") or {}
        start = meta.get("evcal_srow") or record.get("date")
        iso, start_time = "", ""
        try:
            moment = datetime.fromtimestamp(int(start))
            iso, start_time = moment.date().isoformat(), moment.strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            iso = normalize_date(start) or ""
            start_time = parse_time(str(start or ""))
        title = (record.get("title") or {}).get("rendered") or ""
        body = BeautifulSoup((record.get("content") or {}).get("rendered") or "", "lxml")
        description = body.get_text(" ", strip=True)
        events.append({
            "title": clean_text(title, max_length=200),
            "date": iso,
            "time": start_time,
            "price": parse_price(description),
            "category": "",
            "description": clean_text(description, max_length=400),
            "url": clean_url(record.get("link") or source_url),
            "venue": clean_text(meta.get("_evcal_location_name") or ""),
            "source_url": source_url,
        })
    return events


def _from_tribe(payload: Dict[str, Any], source_url: str) -> List[Dict[str, Any]]:
    events = []
    for record in payload.get("events") or []:
        if not isinstance(record, dict):
            continue
        venue = record.get("venue") or {}
        cost = record.get("cost")
        events.append({
            "title": clean_text(record.get("title"), max_length=200),
            "date": normalize_date(record.get("start_date")) or "",
            "time": parse_time(str(record.get("start_date") or "")),
            "price": parse_price(str(cost)) if cost not in (None, "") else None,
            "category": "",
            "description": clean_text(
                BeautifulSoup(record.get("description") or "", "lxml").get_text(" ", strip=True),
                max_length=400,
            ),
            "url": clean_url(record.get("url") or source_url),
            "venue": clean_text(venue.get("venue") if isinstance(venue, dict) else ""),
            "source_url": source_url,
        })
    return events


def fetch_wordpress_events(url: str) -> List[Dict[str, Any]]:
    """Read a WordPress site's events straight out of its REST API."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return []
    origin = f"{parsed.scheme}://{parsed.netloc}"

    for endpoint in WORDPRESS_EVENT_ENDPOINTS:
        body = fetch_plain(origin + endpoint, timeout=25, retries=1, quiet=True)
        if not body:
            continue
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, list):
            events = _from_eventon(payload, url)
        elif isinstance(payload, dict):
            events = _from_tribe(payload, url)
        else:
            continue
        events = [e for e in events if e.get("title") and e.get("date")]
        if events:
            logger.info(f"WordPress REST ({endpoint}) returned {len(events)} events")
            return events
    return []


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
    # Not `except Exception`: CloakBrowser's binary bootstrap raises through
    # native code, and a pyo3 PanicException (seen here verifying this tier)
    # derives from BaseException, so it sailed straight past the handler and
    # took the whole source down. A render tier that cannot render is a
    # missing fallback, never a failed scrape.
    except (Exception, BaseException) as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        logger.warning(f"CloakBrowser render failed for {url}: {type(e).__name__}: {e}")
        return None
    finally:
        for resource in (context, browser):
            try:
                if resource:
                    resource.close()
            except Exception:  # noqa: BLE001 - teardown must never mask the result
                pass


# Ask Jina Reader for the page's HTML, not its default markdown rendering.
# Measured with scripts/fetch_strategy_probe.py against a Cloudflare-challenged
# source (berlin-buehnen.de) from a blocked network: the markdown rendering
# came back 9k and yielded 0 events, the same URL as HTML came back 220k and
# yielded 31. The difference is not the fetch - it is that an HTML body goes
# through all five document extractors, while markdown only ever got a
# line scanner that no source ever produced a usable event from.
#
# The probe also measured the alternatives and none of them earn their cost:
# X-Engine: browser, X-Proxy: auto and X-Locale all matched plain HTML
# exactly, and X-No-Cache matched it on every site but one, which it lost,
# while doubling the request time. So this sends the one header that matters.
JINA_ENDPOINT = "https://r.jina.ai/"
JINA_HEADERS = {"X-Return-Format": "html", "Accept": "text/plain"}


# Jina bills by the content it returns, and asking for HTML returns the whole
# page: berlin-buehnen.de comes back as 1.2MB of HTML against 9KB of markdown.
# That is ~130x the tokens per fetch, and with a date horizon multiplying
# fetches by eight it emptied a fresh account's balance inside a day
# (InsufficientBalanceError, regular_balance -4,432,325). This caps how many
# Jina fetches one scraper process will make; the tier is a fallback for
# blocked sources, not a bulk fetcher.
JINA_FETCH_BUDGET = int(os.environ.get("JINA_FETCH_BUDGET", "2"))
_jina_fetches = 0


def fetch_jina_html(url: str, timeout: int = 60) -> Optional[str]:
    """Fetch a page through Jina Reader, as HTML. None if unavailable.

    This is the last tier, reached only when a direct GET and the rendered-DOM
    tier have both produced nothing - typically an anti-bot interstitial that
    Jina's own infrastructure is not subject to.
    """
    global _jina_fetches
    api_key = os.environ.get("JINA_API_KEY")
    if not api_key:
        logger.info("No JINA_API_KEY set; skipping the Jina tier "
                    "(anonymous calls are unreliably blocked by IP reputation)")
        return None
    if _jina_fetches >= JINA_FETCH_BUDGET:
        logger.info(f"Jina fetch budget spent ({JINA_FETCH_BUDGET}); skipping the tier. "
                    "Raise JINA_FETCH_BUDGET if the account has balance to spare.")
        return None
    _jina_fetches += 1
    headers = dict(JINA_HEADERS)
    headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = requests.get(JINA_ENDPOINT + url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 402:
            logger.error(
                "Jina returned 402 Payment Required - the account balance is "
                "exhausted, so this tier is unavailable until it is topped up. "
                "Blocked sources will fall through to CloakBrowser.")
        else:
            logger.warning(f"Jina Reader fetch failed for {url}: {e}")
        return None


def _merge(*batches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine strategy outputs, preferring the richest row per event URL.

    Strategies see different parts of a page: JSON-LD carries prices and
    venues, <time datetime> carries exact dates, the class-hint scan carries
    cards the other two miss. Merging keeps all three contributions instead of
    discarding two of them.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for batch in batches:
        for event in batch:
            key = (event.get("url") or "") + "|" + str(event.get("title", "")).lower()
            if key not in merged:
                merged[key] = event
                order.append(key)
                continue
            existing = merged[key]
            for field, value in event.items():
                if value not in (None, "") and existing.get(field) in (None, ""):
                    existing[field] = value
    return [merged[k] for k in order]


def scrape_document(html: str, url: str, label: str) -> List[Dict[str, Any]]:
    """Run every extraction strategy over one document and merge the results.

    Previously the first strategy that returned anything won outright, so a
    page whose JSON-LD described four events never had its remaining fifty
    cards scanned.
    """
    jsonld = extract_jsonld_events(html, url)
    timed = extract_time_element_events(html, url)
    heuristic = extract_heuristic_events(html, url)
    calendar = extract_calendar_events(html, url)
    blocks = extract_block_events(html, url)
    logger.info(
        f"{label}: JSON-LD {len(jsonld)}, <time datetime> {len(timed)}, "
        f"heuristic scan {len(heuristic)}, calendar headings {len(calendar)}, "
        f"date blocks {len(blocks)}"
    )
    # Order matters only for which strategy's value wins a field: the earlier
    # strategies read structured markup, so they lead.
    return _merge(jsonld, timed, heuristic, calendar, blocks)


def _meetup_fee_from_next_data(html: str) -> Optional[float]:
    """Meetup's server-rendered page embeds the full event record, including
    ``feeSettings``, in a ``__NEXT_DATA__`` JSON blob that the search/listing
    page never surfaces at all. ``feeSettings: null`` means no Meetup-managed
    fee (free to RSVP - the common case); a populated block carries the
    actual amount, e.g. {"amount": 44, "currency": "EUR", ...}.

    Returns None (not 0.0) when the blob can't be found or parsed at all, so
    callers can tell "confirmed free" from "couldn't check".
    """
    match = re.search(r'__NEXT_DATA__"\s*type="application/json">(.*?)</script>', html, re.S)
    if not match:
        return None
    try:
        event = json.loads(match.group(1))["props"]["pageProps"]["event"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    fee = event.get("feeSettings")
    if fee is None:
        return 0.0
    try:
        return float(fee.get("amount"))
    except (TypeError, ValueError, AttributeError):
        return None


def _visible_text(soup: BeautifulSoup) -> str:
    """Page text with nav/footer chrome stripped, so a price regex doesn't
    latch onto an unrelated figure in a cookie banner or sitemap.

    ``<header>`` is deliberately left alone: sites commonly reuse it for an
    in-page content header (staatsballett-berlin.de's "Eintritt frei" badge
    lives in ``<header id="info">``, not site navigation), so stripping it
    discarded the very price/free marker being searched for.
    """
    for tag in soup.find_all(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def _price_from_detail_page(html: str, url: str) -> Optional[float]:
    """Best-effort price for one event's own page.

    Listing cards frequently omit price even though the event's own page
    states it plainly: rausgegangen.de's schema.org "offers" block only
    exists on the detail page, and sites like staatsoper-berlin.de and
    thf-berlin.de write it as prose ("Kosten: 15 Euro pro Person") that
    never appears in the listing feed either.
    """
    if "meetup.com" in url:
        return _meetup_fee_from_next_data(html)
    for node in extract_jsonld_events(html, url):
        if node.get("price") is not None:
            return node["price"]
    soup = BeautifulSoup(html, "lxml")
    return parse_price(_visible_text(soup))


def enrich_missing_prices(
    events: List[Dict[str, Any]],
    max_fetches: int = MAX_PRICE_ENRICH_FETCHES,
    fetch=fetch_plain,
) -> List[Dict[str, Any]]:
    """Fill in price for events whose listing card didn't state one, by
    fetching each event's own detail page and checking there instead.

    Only events with a detail link distinct from the listing page are worth
    fetching - a source like berlin-buehnen.de that never links off its own
    listing has nothing further to fetch.
    """
    fetched = 0
    for event in events:
        if event.get("price") is not None:
            continue
        url = event.get("url") or ""
        if not url or url == event.get("source_url"):
            continue
        if fetched >= max_fetches:
            break
        fetched += 1
        html = fetch(url)
        if not html or is_bot_challenge(html):
            continue
        price = _price_from_detail_page(html, url)
        if price is not None:
            event["price"] = price
    return events


def is_wordpress(html: str) -> bool:
    return "/wp-content/" in html or "/wp-json/" in html or "wp-includes" in html


# Query parameters a schedule site might use to select one day, in the order
# an existing one is preferred. Ported from JsonLord/Events' buildDateUrl,
# which crawls berlin-buehnen.de a day at a time rather than fetching its
# listing once.
DATE_PARAM_FORMATS = (
    ("date", "%Y-%m-%d"),
    ("datum", "%d.%m.%Y"),
    ("day", "%Y-%m-%d"),
    ("zeitraum", "%Y-%m-%d"),
)

# Deliberately NOT here: start_date/end_date and other range parameters.
# Rewriting one half of a range leaves the other behind - setting
# start_date on rausgegangen's URL while its end_date stayed put produced
# an inverted range asking for events after the window had closed. A source
# that already expresses a range does not need a per-day horizon anyway.
RANGE_PARAMS = ("start_date", "end_date", "from", "to", "bis", "von")

# A week is the scrape window, and the reference implementation caps its own
# horizon at 7 days too. Beyond that the extra requests buy nothing the
# window would keep.
MAX_HORIZON_DAYS = 7


def build_date_url(base_url: str, target: date) -> str:
    """Point a listing URL at one specific day.

    Reuses whichever date parameter the URL already carries, and otherwise
    adds ``date``. Blindly adding one is only worth doing where the site is
    known to honour it - measured across six of this matrix's sources,
    appending ``?date=`` changed neither the page nor the event count, so
    doing it everywhere would multiply requests for nothing. Hence the
    per-source opt-in in the workflow rather than applying this by default.
    """
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if any(name in query for name in RANGE_PARAMS):
        return base_url
    for name, fmt in DATE_PARAM_FORMATS:
        if name in query:
            query[name] = target.strftime(fmt)
            break
    else:
        query["date"] = target.isoformat()
    return urlunparse(parsed._replace(query=urlencode(query)))


def scrape_date_horizon(url: str, days: int) -> List[Dict[str, Any]]:
    """Crawl a schedule one day at a time and merge the days.

    Sites that render a single day per request hide most of their programme
    from a one-shot fetch. berlin-buehnen.de is the case this was ported for:
    measured on a hosted runner, its undated listing yields 32 events while
    the same URL with ``?date=`` four days out yields 36 - a different page
    with different rows, not a superset.

    Each day goes through the ordinary scrape(), so it inherits the whole
    tier chain and all six extractors. There is no model in this path: the
    reference implementation used an LLM to reassemble events from markdown
    fragments, which is unnecessary when the HTML is parsed directly.
    """
    days = max(0, min(days, MAX_HORIZON_DAYS))
    today = date.today()
    batches, seen_urls = [], set()

    for offset in range(days + 1):
        day_url = build_date_url(url, today + timedelta(days=offset))
        if day_url in seen_urls:
            continue
        seen_urls.add(day_url)
        try:
            found = scrape(day_url)
        except Exception as e:  # noqa: BLE001 - one bad day must not lose the rest
            logger.warning(f"Date horizon: day +{offset} failed ({e})")
            continue
        logger.info(f"Date horizon: day +{offset} ({day_url}) -> {len(found)} candidates")
        # Every row keeps the listing it came from as its source, not the
        # dated URL, so downstream grouping still sees one source.
        for event in found:
            event["source_url"] = url
        batches.append(found)

    merged = _merge(*batches) if batches else []
    logger.info(f"Date horizon: {len(merged)} candidates across {len(batches)} day(s)")
    return merged


def scrape(url: str) -> List[Dict[str, Any]]:
    html = fetch_plain(url)
    if html and not is_bot_challenge(html):
        events = scrape_document(html, url, "plain HTML")
        # A WordPress site's REST API is worth asking even when the page did
        # parse: plugin calendars render client-side, so the HTML shows a
        # fraction of what the API lists (theclubmap.com: 0 from the page,
        # 100 from the API). Merged, not preferred - the page carries prices
        # and venues the API often leaves empty.
        if is_wordpress(html):
            events = _merge(events, fetch_wordpress_events(url))
        if events:
            logger.info(f"Found {len(events)} candidate events from plain HTML")
            return events
    else:
        logger.info("Plain GET returned a bot challenge or failed; escalating")

    # Jina before CloakBrowser, on measurement rather than taste. Probe run
    # 34825099038 on a hosted runner: venturecafeberlin.org refused the
    # runner that day (169 bytes) and CloakBrowser got its challenge page
    # (11.8k, 0 events), while this tier came back with the real page and the
    # event. Across the probe set it kept 33 events to CloakBrowser's 32,
    # won two sites to CloakBrowser's none, and took 0.5-1.7s per site
    # against 5-24s. Note the same site answered the *previous* runner
    # normally - the block is intermittent, which is precisely what makes a
    # second route worth having rather than a nice-to-have.
    via_jina = fetch_jina_html(url)
    if via_jina and not is_bot_challenge(via_jina):
        events = scrape_document(via_jina, url, "Jina Reader HTML")
        if events:
            logger.info(f"Found {len(events)} candidate events via the Jina Reader tier")
            return events

    # Last resort, and the only one that needs no third party. It has not
    # uniquely rescued a single site in any probe run so far, but it is what
    # remains if the Jina key is missing, out of quota, or the service is
    # down, so it stays.
    rendered = render_with_cloakbrowser(url)
    if rendered:
        events = scrape_document(rendered, url, "rendered DOM")
        if events:
            logger.info(f"Found {len(events)} candidate events from the rendered DOM")
            return events

    logger.warning(f"No events could be extracted from {url}")
    return []


def main():
    parser = argparse.ArgumentParser(description="Generic multi-strategy event scraper")
    parser.add_argument("--url", required=True, help="URL to scrape")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--price-max", type=float, default=DEFAULT_MAX_PRICE,
                        help=f"Max event price in EUR (default {DEFAULT_MAX_PRICE:g})")
    parser.add_argument("--date-days", type=int, default=7,
                        help="Only keep events starting within this many days from today")
    parser.add_argument("--save-html", action="store_true", help="Save a page snapshot for analysis")
    parser.add_argument("--html-output", help="Path where fetched page content should be saved")
    parser.add_argument(
        "--date-horizon", action="store_true",
        help="Crawl one page per day across the window, injecting the date into "
             "the URL. Only for sources known to honour a date parameter: "
             "appending one to a site that ignores it multiplies requests for "
             "nothing.")
    parser.add_argument(
        "--price-enrich-limit", type=int, default=MAX_PRICE_ENRICH_FETCHES,
        help="Max per-event detail-page fetches for events with no listed price "
             f"(default {MAX_PRICE_ENRICH_FETCHES}; 0 disables)",
    )

    args = parser.parse_args()

    try:
        events = (scrape_date_horizon(args.url, args.date_days)
                  if args.date_horizon else scrape(args.url))
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        events = []

    if args.price_enrich_limit > 0 and events:
        missing = sum(1 for e in events if e.get("price") is None)
        enrich_missing_prices(events, max_fetches=args.price_enrich_limit)
        found = missing - sum(1 for e in events if e.get("price") is None)
        logger.info(f"Price enrichment: found a price for {found}/{missing} previously unpriced events")

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
