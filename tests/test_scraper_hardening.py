"""Tests for the strategies and fetch behaviour added to reach every source.

Each case reproduces a page shape or a network response that was measured
producing zero events against the live matrix.
"""

import sys
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("bs4")

# The extraction paths make no HTTP calls, but the module imports `requests`
# at top level; stub it where the runtime dependency is absent, exactly as
# tests/test_extraction_coverage.py does.
if "requests" not in sys.modules:
    stub = ModuleType("requests")
    stub.exceptions = SimpleNamespace(RequestException=Exception)
    sys.modules["requests"] = stub

from scripts.generic_event_scraper import (  # noqa: E402
    BROWSER_HEADERS,
    _from_eventon,
    _from_tribe,
    extract_block_events,
    extract_calendar_events,
    extract_heuristic_events,
    is_bot_challenge,
    is_wordpress,
    render_with_cloakbrowser,
)

SOURCE = "https://example.de/programm"


# --------------------------------------------------------------------------
# Calendar headings: the month is printed once, each row carries only a day
# --------------------------------------------------------------------------

HAU_SHAPED = '''<html><body><div class="month">
  <h3>September 2026</h3>
  <ul>
    <li class="day module">
      <h2 class="big">Sat 12</h2>
      <ul>
        <li class="item"><div class="date"><strong>18:00</strong></div>
          <div class="info"><h3>Theresa Reiwer</h3>
            <a href="/en/programme/pdetail/internet-explorer/">Details</a></div></li>
        <li class="item"><div class="date"><strong>20:00</strong></div>
          <div class="info"><h3>Sophia Suessmilch</h3>
            <a href="/en/programme/pdetail/cannibal-woman/">Details</a></div></li>
      </ul>
    </li>
    <li class="day module">
      <h2 class="big">Sun 13</h2>
      <ul>
        <li class="item"><div class="date"><strong>16:00</strong></div>
          <div class="info"><h3>Sister Queens</h3>
            <a href="/en/programme/pdetail/sisterqueens/">Details</a></div></li>
      </ul>
    </li>
  </ul></div></body></html>'''


def test_day_headings_inherit_the_month_heading():
    """HAU publishes 35 events under one "September 2026" heading with a bare
    "Sat 12" per day. No card states a date, so every strategy found nothing
    and the whole venue extracted zero events."""
    events = extract_calendar_events(HAU_SHAPED, SOURCE)
    assert [e["date"] for e in events] == ["2026-09-12", "2026-09-12", "2026-09-13"]
    assert [e["title"] for e in events] == [
        "Theresa Reiwer", "Sophia Suessmilch", "Sister Queens",
    ]
    assert [e["time"] for e in events] == ["18:00", "20:00", "16:00"]
    assert events[0]["url"].endswith("/en/programme/pdetail/internet-explorer/")


def test_day_number_inside_the_card_is_used():
    """The Renaissance-Theater prints the day number inside the row itself
    ("13" then "So"), not in a heading above it."""
    html = '''<html><body><h1>Oktober</h1>
      <div class="rt-spielplan-day">
        <div class="rt-sp-day">7</div><div class="rt-sp-wday">Di</div>
        <div class="rt-sp-times">
          <div class="rt-sp-date"><div class="rt-sp-time">19.30</div>
            <div class="rt-sp-teaser"><a href="/produktion/nebenan/"><h4>Nebenan</h4></a></div>
          </div>
        </div></div></body></html>'''
    events = extract_calendar_events(html, SOURCE)
    assert len(events) == 1
    assert events[0]["date"].endswith("-10-07")
    assert events[0]["title"] == "Nebenan"


def test_month_rollover_is_tracked():
    """Days after a second month heading belong to that month, not the first."""
    html = '''<html><body>
      <h2>September 2026</h2>
      <div class="event-card"><h3>Im September</h3>
        <div class="date">20</div><a href="/event/sep">Details</a><span>19:00</span></div>
      <h2>Oktober 2026</h2>
      <div class="event-card"><h3>Im Oktober</h3>
        <div class="date">3</div><a href="/event/okt">Details</a><span>19:00</span></div>
    </body></html>'''
    dates = {e["title"]: e["date"] for e in extract_calendar_events(html, SOURCE)}
    assert dates == {"Im September": "2026-09-20", "Im Oktober": "2026-10-03"}


def test_calendar_strategy_leaves_fully_dated_cards_alone():
    """A card that states its own date is the other strategies' business;
    stamping it from a heading could only overwrite a better answer."""
    html = '''<html><body><h2>September 2026</h2>
      <div class="date">20</div>
      <div class="event-card"><h3>Konzert</h3>
        <a href="/event/k">Details</a><span>05.09.2026, 20:00</span></div>
    </body></html>'''
    assert extract_calendar_events(html, SOURCE) == []


def test_calendar_strategy_needs_both_kinds_of_heading():
    """Day numbers with no month anywhere cannot be resolved, and guessing
    would publish confidently wrong dates."""
    html = '''<html><body>
      <div class="event-card"><h3>Konzert</h3><div class="date">20</div>
        <a href="/event/k">Details</a><span>20:00</span></div></body></html>'''
    assert extract_calendar_events(html, SOURCE) == []


def test_a_time_is_never_read_as_a_day_number():
    """"12:00" and "18.00" are times; reading either as a day of the month
    would date every row in the listing wrongly."""
    html = '''<html><body><h2>September 2026</h2>
      <div class="date">12:00</div><div class="date">18.00</div>
      <div class="event-card"><h3>Konzert</h3><a href="/event/k">Details</a>
        <span>20:00</span></div></body></html>'''
    assert extract_calendar_events(html, SOURCE) == []


# --------------------------------------------------------------------------
# Class-agnostic date blocks
# --------------------------------------------------------------------------

def test_events_are_found_without_any_event_ish_class():
    """Divi names every block after itself ("et_pb_text"), so a class-keyed
    scan saw nothing on reinickendorf-classics.de even though each event
    states its date in plain text under the title."""
    html = '''<html><body>
      <div class="et_pb_row"><div class="et_pb_text_inner">
        <h2>Nicole &amp; Band</h2>
        <p><strong>Samstag, 19.09.2026 &#8211; 20:00 Uhr</strong></p></div>
        <a class="et_pb_button" href="/?page_id=34923">Details &amp; Tickets</a></div>
      <div class="et_pb_row"><div class="et_pb_text_inner">
        <h2>MAITE ITOIZ</h2>
        <p><strong>Samstag, 27.09.2026 &#8211; 19:00 Uhr</strong></p></div>
        <a class="et_pb_button" href="/maite-2026">Details &amp; Tickets</a></div>
    </body></html>'''
    assert extract_heuristic_events(html, SOURCE) == []
    events = extract_block_events(html, SOURCE)
    assert [e["title"] for e in events] == ["Nicole & Band", "MAITE ITOIZ"]
    assert [e["date"] for e in events] == ["2026-09-19", "2026-09-27"]
    assert [e["time"] for e in events] == ["20:00", "19:00"]


def test_block_scan_ignores_navigation_and_scripts():
    """Archive menus and inline JSON carry dates too; neither is an event."""
    html = '''<html><body>
      <nav><ul><li><a href="/archiv-2019-20/">Archiv 19.09.2019</a></li></ul></nav>
      <script>var next = "19.09.2026";</script>
      <footer><a href="/impressum">Stand 01.01.2026</a></footer>
    </body></html>'''
    assert extract_block_events(html, SOURCE) == []


def test_block_scan_keeps_the_card_not_the_whole_listing():
    html = '''<html><body><main>
      <article><h2>Erstes Konzert</h2><p>05.10.2026 20:00</p>
        <a href="/event/eins">Tickets</a></article>
      <article><h2>Zweites Konzert</h2><p>06.10.2026 20:00</p>
        <a href="/event/zwei">Tickets</a></article>
    </main></body></html>'''
    events = extract_block_events(html, SOURCE)
    assert [e["title"] for e in events] == ["Erstes Konzert", "Zweites Konzert"]


# --------------------------------------------------------------------------
# Widened class hints
# --------------------------------------------------------------------------

def test_list_item_cards_are_candidates():
    """ZK/U and SAVVY Contemporary build their whole programme out of
    ".list-item", which "listing" does not match - both extracted nothing."""
    html = '''<html><body>
      <div class="list-item"><h2>OPENHAUS SEPTEMBER 2026</h2>
        <p class="date">24 SEPTEMBER 2026 / 19:00 - 23:00</p>
        <a class="list-item__link" href="/de/timeline/openhaus/">mehr</a></div>
    </body></html>'''
    events = extract_heuristic_events(html, SOURCE)
    assert len(events) == 1
    assert events[0]["title"] == "OPENHAUS SEPTEMBER 2026"
    assert events[0]["date"] == "2026-09-24"
    assert events[0]["url"].endswith("/de/timeline/openhaus/")


# --------------------------------------------------------------------------
# Fetch layer
# --------------------------------------------------------------------------

def test_browser_headers_go_beyond_a_user_agent():
    """A UA-only GET was answered with 403 by rausgegangen.de - the single
    biggest source in the matrix - on every run."""
    assert BROWSER_HEADERS["Accept-Language"].startswith("de-DE")
    for header in ("Accept", "Sec-Fetch-Mode", "Upgrade-Insecure-Requests"):
        assert header in BROWSER_HEADERS


def test_bunny_shield_is_recognised_as_a_challenge():
    """Bunny Shield's interstitial says neither "just a moment" nor
    "checking your browser", so it read as a normal (empty) page."""
    html = ('<html><head><title>Establishing a secure connection ...</title>'
            '<script src="/.bunny-shield/assets/shield-challenge.js"></script></head></html>')
    assert is_bot_challenge(html)


def test_a_cloudflare_challenge_is_still_recognised():
    assert is_bot_challenge('<html><head><title>Just a moment...</title></head></html>')


def test_a_real_listing_is_not_a_challenge():
    assert not is_bot_challenge('<html><body><h1>Spielplan September</h1></body></html>')


def test_fetch_keeps_a_challenge_body_but_drops_an_error_page(monkeypatch):
    """The status code does not decide usability: an anti-bot interstitial
    arrives as 403 with a real body the caller must be able to recognise,
    while a 404 error page has nothing in it."""
    from scripts import generic_event_scraper as module

    class Response:
        def __init__(self, status, text):
            self.status_code, self.text = status, text

    def respond(status, body):
        monkeypatch.setattr(
            module, "get_session",
            lambda: SimpleNamespace(get=lambda *a, **k: Response(status, body)),
        )

    respond(403, '<html><head><title>Just a moment...</title></head></html>')
    assert "Just a moment" in (module.fetch_plain(SOURCE) or "")

    respond(404, '<html><body><h1>Seite nicht gefunden</h1></body></html>')
    assert module.fetch_plain(SOURCE) is None

    respond(200, '<html><body><h1>Spielplan</h1></body></html>')
    assert "Spielplan" in (module.fetch_plain(SOURCE) or "")


def test_a_native_crash_in_the_render_tier_is_not_fatal(monkeypatch):
    """CloakBrowser's binary bootstrap raises through native code, and a pyo3
    PanicException derives from BaseException - it sailed past `except
    Exception` and took the whole source down instead of falling through."""
    class Panic(BaseException):
        pass

    fake = ModuleType("cloakbrowser")

    def explode(*args, **kwargs):
        raise Panic("Python API call failed")

    fake.launch = explode
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake)
    assert render_with_cloakbrowser(SOURCE) is None


def test_keyboard_interrupt_still_propagates(monkeypatch):
    fake = ModuleType("cloakbrowser")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    fake.launch = interrupt
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake)
    with pytest.raises(KeyboardInterrupt):
        render_with_cloakbrowser(SOURCE)


# --------------------------------------------------------------------------
# WordPress REST
# --------------------------------------------------------------------------

def test_eventon_records_become_events():
    """theclubmap.com renders its calendar over AJAX - 0 events from the HTML
    on every run - while /wp-json/wp/v2/ajde_events lists all of them."""
    events = _from_eventon([{
        "title": {"rendered": "Slutty Sunday"},
        "link": "https://www.theclubmap.com/events/slutty-sunday/",
        "content": {"rendered": "<p>Techno all night. Eintritt 12,00 &euro;</p>"},
        "meta": {"evcal_srow": "1789934400", "_evcal_location_name": "Ritter Butzke"},
    }], SOURCE)
    assert len(events) == 1
    assert events[0]["title"] == "Slutty Sunday"
    assert events[0]["date"]  # resolved from the Unix start timestamp
    assert events[0]["price"] == 12.0
    assert events[0]["venue"] == "Ritter Butzke"


def test_tribe_records_become_events():
    events = _from_tribe({"events": [{
        "title": "Lesung",
        "url": "https://example.de/event/lesung/",
        "start_date": "2026-10-05 19:30:00",
        "cost": "8 EUR",
        "description": "<p>Eine Lesung</p>",
        "venue": {"venue": "Kleiner Saal"},
    }]}, SOURCE)
    assert events[0]["date"] == "2026-10-05"
    assert events[0]["time"] == "19:30"
    assert events[0]["price"] == 8.0
    assert events[0]["venue"] == "Kleiner Saal"


def test_wordpress_detection():
    assert is_wordpress('<link href="/wp-content/themes/x/style.css">')
    assert not is_wordpress('<html><body><h1>Spielplan</h1></body></html>')


# --------------------------------------------------------------------------
# The Jina Reader tier
# --------------------------------------------------------------------------

def test_jina_tier_asks_for_html_not_markdown(monkeypatch):
    """Measured with scripts/fetch_strategy_probe.py against a Cloudflare-
    challenged source: the default markdown rendering came back 9k and
    yielded 0 events; the same URL as HTML came back 220k and yielded 31.
    An HTML body goes through all five document extractors; markdown only
    ever got a line scanner that produced nothing usable from any source."""
    from scripts import generic_event_scraper as module

    seen = {}

    class Response:
        status_code, text = 200, "<html><body>ok</body></html>"

        def raise_for_status(self):
            return None

    def fake_get(url, headers=None, timeout=None, **kwargs):
        seen["url"] = url
        seen["headers"] = headers or {}
        return Response()

    monkeypatch.setenv("JINA_API_KEY", "test-key")
    monkeypatch.setattr(module.requests, "get", fake_get, raising=False)

    assert module.fetch_jina_html("https://example.de/programm") == Response.text
    assert seen["url"] == "https://r.jina.ai/https://example.de/programm"
    assert seen["headers"]["X-Return-Format"] == "html"
    assert seen["headers"]["Authorization"] == "Bearer test-key"


def test_jina_tier_sends_only_the_header_that_earned_its_place(monkeypatch):
    """The probe measured the alternatives: X-Engine, X-Proxy and X-Locale
    matched plain HTML exactly, and X-No-Cache matched it everywhere but one
    site, which it lost, at double the request time. None are sent."""
    from scripts import generic_event_scraper as module

    seen = {}

    class Response:
        text = "<html></html>"

        def raise_for_status(self):
            return None

    monkeypatch.setenv("JINA_API_KEY", "test-key")
    monkeypatch.setattr(
        module.requests, "get",
        lambda url, headers=None, **kw: (seen.update(headers=headers or {}), Response())[1],
        raising=False,
    )
    module.fetch_jina_html("https://example.de/")
    for header in ("X-No-Cache", "X-Engine", "X-Proxy", "X-Locale"):
        assert header not in seen["headers"], header


def test_jina_tier_is_skipped_without_a_key(monkeypatch):
    """Anonymous Jina calls are unreliably blocked by IP reputation, so with
    no key the tier reports that it is skipping rather than trying."""
    from scripts import generic_event_scraper as module

    monkeypatch.delenv("JINA_API_KEY", raising=False)
    assert module.fetch_jina_html("https://example.de/") is None


def test_a_challenge_returned_through_jina_is_not_treated_as_content(monkeypatch):
    """Eventbrite serves its "Human Verification" interstitial to Jina too.
    Extracting from that would publish nothing but produce a misleading
    "the tier worked" reading."""
    from scripts import generic_event_scraper as module

    challenge = ('<html><head><title>Human Verification</title></head>'
                 '<body>verify</body></html>')
    monkeypatch.setattr(module, "fetch_plain", lambda url, **kw: None)
    monkeypatch.setattr(module, "render_with_cloakbrowser", lambda url: None)
    monkeypatch.setattr(module, "fetch_jina_html", lambda url, **kw: challenge)
    assert module.scrape("https://www.eventbrite.de/d/germany/berlin/events/") == []


def test_eventbrite_interstitial_is_recognised():
    assert is_bot_challenge('<html><head><title>Human Verification</title></head></html>')


def test_jina_is_tried_before_the_render_tier(monkeypatch):
    """Ordering is a measurement, not a preference. Probe run 34825099038:
    venturecafeberlin.org refused the runner, CloakBrowser got its challenge
    page and 0 events, the Jina tier got the real page and the event. Across
    the probe set Jina kept 33 to CloakBrowser's 32 at a twentieth of the
    time, so a site that fails a plain GET must reach Jina first."""
    from scripts import generic_event_scraper as module

    order = []

    def jina(url, **kwargs):
        order.append("jina")
        return ('<html><body><div class="event-card"><h3>Recovered Show</h3>'
                '<a href="/event/x">Details</a><span>05.10.2026 20:00</span>'
                '</div></body></html>')

    def render(url):
        order.append("cloakbrowser")
        return "<html></html>"

    monkeypatch.setattr(module, "fetch_plain", lambda url, **kw: None)
    monkeypatch.setattr(module, "fetch_jina_html", jina)
    monkeypatch.setattr(module, "render_with_cloakbrowser", render)

    events = module.scrape("https://blocked.example/programm")
    assert [e["title"] for e in events] == ["Recovered Show"]
    # Jina answered, so the slow tier is never reached at all.
    assert order == ["jina"]


def test_the_render_tier_still_runs_when_jina_is_unavailable(monkeypatch):
    """No key, no quota, or the service is down: CloakBrowser is what is
    left, which is why it is kept rather than deleted."""
    from scripts import generic_event_scraper as module

    monkeypatch.setattr(module, "fetch_plain", lambda url, **kw: None)
    monkeypatch.setattr(module, "fetch_jina_html", lambda url, **kw: None)
    monkeypatch.setattr(
        module, "render_with_cloakbrowser",
        lambda url: ('<html><body><div class="event-card"><h3>Rendered Show</h3>'
                     '<a href="/event/y">Details</a><span>06.10.2026 20:00</span>'
                     '</div></body></html>'),
    )
    assert [e["title"] for e in module.scrape("https://blocked.example/programm")] == ["Rendered Show"]
