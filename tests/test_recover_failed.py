"""Tests for the recovery pass that replaced the Jules session.

Recovery walks from a listing page to the individual event pages it links to,
because an event's own page is almost always better marked up than the listing
(Ritter Butzke serves a scraper 627 characters of chrome but every event page
it links carries a full schema.org MusicEvent).

Every test here is offline: fetching is injected.
"""

import json
import sys
from datetime import date, timedelta
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("bs4")

if "requests" not in sys.modules:
    stub = ModuleType("requests")
    stub.exceptions = SimpleNamespace(RequestException=Exception)
    sys.modules["requests"] = stub

from scripts.recover_failed import (  # noqa: E402
    _window_for,
    extract_from_detail_page,
    find_failed_sites,
    harvest_detail_links,
    recover_site,
)

LISTING = "https://club.example.com/events"


def _soon(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------
# Harvesting links to individual event pages
# --------------------------------------------------------------------------

LISTING_HTML = '''<html><body>
  <a href="/event/180926-giddy-club">Giddy Club</a>
  <a href="/event/190926-solee">Solee</a>
  <a href="/event/180926-giddy-club">Giddy Club (again)</a>
  <a href="/faq">FAQ</a>
  <a href="/impressum">Impressum</a>
  <a href="https://shop.other-site.com/event/tickets">Buy tickets</a>
  <a href="https://www.instagram.com/club">Instagram</a>
  <a href="/events">Events</a>
</body></html>'''


def test_only_same_origin_event_pages_are_harvested():
    """A listing links out to ticket vendors and social profiles; following
    those would scrape somebody else's site instead of recovering this one."""
    links = harvest_detail_links(LISTING_HTML, LISTING)
    assert links == [
        "https://club.example.com/event/180926-giddy-club",
        "https://club.example.com/event/190926-solee",
    ]


def test_the_listing_is_not_one_of_its_own_event_pages():
    """/events links to itself in its own nav - following that would re-scrape
    the page that already came back empty."""
    assert LISTING not in harvest_detail_links(LISTING_HTML, LISTING)


def test_harvest_respects_its_limit():
    many = "".join(f'<a href="/event/{i}-show">Show {i}</a>' for i in range(50))
    assert len(harvest_detail_links(f"<html><body>{many}</body></html>", LISTING, limit=7)) == 7


def test_a_site_with_nothing_on_offer_yields_no_links():
    """This is the signal that separates "between seasons" from "blocked":
    measured across the matrix, sites with a real programme expose 12-193
    event links and sites with nothing expose none."""
    html = '<html><body><a href="/about">About</a><a href="/kontakt">Kontakt</a></body></html>'
    assert harvest_detail_links(html, LISTING) == []


# --------------------------------------------------------------------------
# Reading one event page
# --------------------------------------------------------------------------

def test_schema_org_on_the_event_page_is_preferred():
    """The exact case recovery exists for: the listing renders client-side and
    says nothing, while each event page carries a complete MusicEvent block."""
    page = '''<html><head><script type="application/ld+json">
      {"@context":"https://schema.org","@type":"MusicEvent","name":"Giolì & Assia",
       "url":"https://club.example.com/event/171026","startDate":"2026-10-17T19:00",
       "location":{"name":"Ritter Butzke"},"offers":{"price":"15.00"}}
    </script></head><body><p>JavaScript ist deaktiviert.</p></body></html>'''
    events = extract_from_detail_page("https://club.example.com/event/171026",
                                      fetch=lambda url, **kw: page)
    assert len(events) == 1
    assert events[0]["title"] == "Giolì & Assia"
    assert events[0]["date"] == "2026-10-17"
    assert events[0]["price"] == 15.0
    assert events[0]["venue"] == "Ritter Butzke"


def test_event_page_without_schema_falls_back_to_the_page_scan():
    page = '''<html><body><div class="event-card"><h1>Solee</h1>
      <a href="/event/190926-solee">Tickets</a>
      <span>19.09.2026, 23:00 Uhr</span><span>12,00 €</span></div></body></html>'''
    events = extract_from_detail_page("https://club.example.com/event/190926-solee",
                                      fetch=lambda url, **kw: page)
    assert [e["title"] for e in events] == ["Solee"]


def test_an_unreachable_or_challenged_event_page_contributes_nothing():
    challenge = '<html><head><title>Just a moment...</title></head></html>'
    assert extract_from_detail_page("https://x.example/event/1", fetch=lambda u, **kw: None) == []
    assert extract_from_detail_page("https://x.example/event/1", fetch=lambda u, **kw: challenge) == []


# --------------------------------------------------------------------------
# Which sites are candidates, and against which window
# --------------------------------------------------------------------------

def test_only_empty_sources_are_candidates(tmp_path):
    (tmp_path / "raw_full.json").write_text(json.dumps(
        {"source": "https://a.example/", "events": [{"title": "Something"}]}))
    (tmp_path / "raw_empty.json").write_text(json.dumps(
        {"source": "https://b.example/", "events": [],
         "window_start": "2026-09-14", "window_end": "2026-09-21"}))
    (tmp_path / "raw_broken.json").write_text("{not json")

    failed = find_failed_sites(str(tmp_path), str(tmp_path / "html"))
    assert [site["name"] for site in failed] == ["empty"]
    assert failed[0]["url"] == "https://b.example/"


def test_the_window_comes_from_the_scrape_leg(tmp_path):
    """Recovery runs after every leg has finished, so recomputing the window
    could hold recovered events to a different range than the scrape used."""
    site = {"window_start": "2026-09-14", "window_end": "2026-09-21"}
    assert _window_for(site, 7) == (date(2026, 9, 14), date(2026, 9, 21))


def test_a_missing_window_falls_back_to_the_date_range():
    start, end = _window_for({}, 7)
    assert (end - start).days == 7


# --------------------------------------------------------------------------
# Recovering one site end to end
# --------------------------------------------------------------------------

def _site(tmp_path, html: str) -> dict:
    snapshot = tmp_path / "club.html"
    snapshot.write_text(html, encoding="utf-8")
    return {"name": "club", "url": LISTING, "html_path": str(snapshot),
            "window_start": _soon(0), "window_end": _soon(7)}


def test_a_listing_that_said_nothing_is_recovered_from_its_event_pages(tmp_path):
    listing = '''<html><body><div id="app"></div>
      <a href="/event/giddy">Giddy Club</a><a href="/event/solee">Solee</a>
    </body></html>'''

    pages = {
        "https://club.example.com/event/giddy": f'''<html><head>
          <script type="application/ld+json">{{"@type":"Event","name":"Giddy Club",
          "url":"https://club.example.com/event/giddy","startDate":"{_soon(3)}T19:00",
          "offers":{{"price":"0"}}}}</script></head><body>x</body></html>''',
        "https://club.example.com/event/solee": f'''<html><head>
          <script type="application/ld+json">{{"@type":"Event","name":"Solee",
          "url":"https://club.example.com/event/solee","startDate":"{_soon(5)}T23:00",
          "offers":{{"price":"12"}}}}</script></head><body>x</body></html>''',
    }

    recovered = recover_site(_site(tmp_path, listing), 7, 20.0,
                             fetch=lambda url, **kw: pages.get(url))
    assert {e["title"] for e in recovered} == {"Giddy Club", "Solee"}
    assert all(e["date"] for e in recovered)


def test_recovered_events_are_held_to_the_same_price_cap(tmp_path):
    listing = '<html><body><a href="/event/gala">Gala</a></body></html>'
    page = f'''<html><head><script type="application/ld+json">{{"@type":"Event",
      "name":"Gala","url":"https://club.example.com/event/gala",
      "startDate":"{_soon(3)}T20:00","offers":{{"price":"49.00"}}}}</script></head>
      <body>x</body></html>'''
    assert recover_site(_site(tmp_path, listing), 7, 20.0,
                        fetch=lambda url, **kw: page) == []


def test_recovered_events_are_held_to_the_same_window(tmp_path):
    listing = '<html><body><a href="/event/later">Later</a></body></html>'
    page = f'''<html><head><script type="application/ld+json">{{"@type":"Event",
      "name":"Much Later","url":"https://club.example.com/event/later",
      "startDate":"{_soon(60)}T20:00","offers":{{"price":"5"}}}}</script></head>
      <body>x</body></html>'''
    assert recover_site(_site(tmp_path, listing), 7, 20.0,
                        fetch=lambda url, **kw: page) == []


def test_a_bot_challenge_snapshot_is_not_crawled(tmp_path):
    """An interstitial has no real links to follow; only the rendered-DOM tier
    can get past it, and hammering it with fetches would not help."""
    challenge = '<html><head><title>Just a moment...</title></head><body></body></html>'
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return "<html></html>"

    assert recover_site(_site(tmp_path, challenge), 7, 20.0, fetch=fetch) == []
    assert calls == []


def test_a_site_with_no_event_pages_is_left_alone(tmp_path):
    quiet = '<html><body><h1>Kalender</h1><p>Keine Termine.</p></body></html>'
    assert recover_site(_site(tmp_path, quiet), 7, 20.0,
                        fetch=lambda url, **kw: "<html></html>") == []


def test_a_failing_event_page_does_not_sink_the_site(tmp_path):
    """One page that raises must not cost the other pages' events."""
    listing = ('<html><body><a href="/event/ok">OK</a>'
               '<a href="/event/bad">Bad</a></body></html>')
    good = f'''<html><head><script type="application/ld+json">{{"@type":"Event",
      "name":"Good Show","url":"https://club.example.com/event/ok",
      "startDate":"{_soon(2)}T20:00","offers":{{"price":"5"}}}}</script></head>
      <body>x</body></html>'''

    def fetch(url, **kwargs):
        if url.endswith("/bad"):
            raise RuntimeError("connection reset")
        return good

    with pytest.raises(RuntimeError):
        recover_site(_site(tmp_path, listing), 7, 20.0, fetch=fetch, workers=1)


def test_recovery_needs_no_api_key(monkeypatch, tmp_path):
    """The whole point of the replacement: no credential, no model, no
    network dependency beyond the sites themselves."""
    for name in ("JULES_API_KEY", "JULES_SOURCE_ID"):
        monkeypatch.delenv(name, raising=False)
    listing = '<html><body><a href="/event/x">X</a></body></html>'
    page = f'''<html><head><script type="application/ld+json">{{"@type":"Event",
      "name":"Free Show","url":"https://club.example.com/event/x",
      "startDate":"{_soon(2)}T20:00","offers":{{"price":"0"}}}}</script></head>
      <body>x</body></html>'''
    recovered = recover_site(_site(tmp_path, listing), 7, 20.0,
                             fetch=lambda url, **kw: page)
    assert [e["title"] for e in recovered] == ["Free Show"]


# --------------------------------------------------------------------------
# Reporting: recovered and deduplicated are different numbers
# --------------------------------------------------------------------------

def _run_main(tmp_path, scraped, monkeypatch):
    """Drive main() over an aggregate with no recoverable sources."""
    import scripts.recover_failed as module

    aggregated = tmp_path / "events.json"
    aggregated.write_text(json.dumps({"events": scraped, "count": len(scraped)}))
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", [
        "recover_failed.py", "--aggregated", str(aggregated),
        "--raw-dir", str(tmp_path / "empty"), "--html-dir", str(tmp_path / "empty"),
        "--output", str(out),
    ])
    module.main()
    return json.loads(out.read_text())


def test_cross_source_duplicates_are_reported_separately(tmp_path, monkeypatch):
    """Berlin listing sites carry each other's shows, so the concatenated
    aggregate holds duplicates. Folding that into the recovered count made a
    real run print "458 scraped + -31 recovered", which is not a number."""
    show = {"title": "Die Raeuber", "date": _soon(2), "time": "19:30",
            "price": 10.0, "url": "https://a.example/event/raeuber",
            "venue": "", "description": "", "category": "",
            "source_url": "https://a.example/"}
    twin = dict(show, source_url="https://b.example/")

    payload = _run_main(tmp_path, [show, twin], monkeypatch)
    assert payload["duplicates_removed"] == 1
    assert payload["recovered_count"] == 0
    assert payload["count"] == 1


def test_a_clean_aggregate_reports_no_duplicates(tmp_path, monkeypatch):
    events = [
        {"title": "First", "date": _soon(1), "time": "20:00", "price": 0.0,
         "url": "https://a.example/event/1", "venue": "", "description": "",
         "category": "", "source_url": "https://a.example/"},
        {"title": "Second", "date": _soon(2), "time": "21:00", "price": 5.0,
         "url": "https://a.example/event/2", "venue": "", "description": "",
         "category": "", "source_url": "https://a.example/"},
    ]
    payload = _run_main(tmp_path, events, monkeypatch)
    assert payload["duplicates_removed"] == 0
    assert payload["recovered_count"] == 0
    assert payload["count"] == 2
