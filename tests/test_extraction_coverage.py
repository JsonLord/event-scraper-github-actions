"""Recall tests: the extractor must find *all* events on a page, not some.

Each fixture reproduces a page shape that was measured losing real events
against the live source sites.
"""

import sys
from types import ModuleType

# The parsing paths under test make no HTTP calls; keep them runnable where
# the optional scraper runtime dependencies are absent.
sys.modules.setdefault("requests", ModuleType("requests"))

import pytest  # noqa: E402

pytest.importorskip("bs4")

from scripts.event_utils import parse_time  # noqa: E402
from scripts.generic_event_scraper import (  # noqa: E402
    _meetup_fee_from_next_data,
    _price_from_detail_page,
    _visible_text,
    enrich_missing_prices,
    extract_heuristic_events,
    extract_time_element_events,
    scrape_document,
)
from bs4 import BeautifulSoup  # noqa: E402

SOURCE = "https://example.de/programm"


def _listing(card_count: int) -> str:
    """A list container that itself carries an event-ish class, wrapping cards."""
    cards = "".join(
        f'''<div class="block block-teaser block-teaser-event">
              <h3>Konzert Nummer {i}</h3>
              <a href="/veranstaltung/konzert-{i}">Details</a>
              <span>0{(i % 9) + 1}.09.2026, 20:00 Uhr</span>
              <span>10,00 €</span>
            </div>'''
        for i in range(card_count)
    )
    return f'<html><body><div class="event-listing">{cards}</div></body></html>'


def test_every_card_in_a_listing_is_extracted():
    """"Outermost wins" kept the wrapper and discarded its children: 42
    stadtmuseum cards collapsed to 2, and 27 Eventbrite cards to 3."""
    events = extract_heuristic_events(_listing(12), SOURCE)
    assert len(events) == 12
    assert {e["title"] for e in events} == {f"Konzert Nummer {i}" for i in range(12)}


def test_extraction_is_not_truncated_at_sixty():
    """A hardcoded [:60] discarded 71% of rausgegangen's 205 candidates."""
    events = extract_heuristic_events(_listing(150), SOURCE)
    assert len(events) == 150


def test_max_events_is_still_honoured_as_a_guard():
    assert len(extract_heuristic_events(_listing(150), SOURCE, max_events=25)) == 25


def test_a_fragment_inside_a_card_does_not_become_its_own_event():
    """The container rule must not swing the other way and emit price/date
    fragments as separate events."""
    html = '''<html><body><div class="event-card">
        <h3>Solo Konzert</h3><a href="/veranstaltung/solo">Details</a>
        <div class="event-date">05.09.2026, 20:00 Uhr</div>
      </div></body></html>'''
    events = extract_heuristic_events(html, SOURCE)
    assert len(events) == 1
    assert events[0]["title"] == "Solo Konzert"


def test_time_datetime_markers_are_extracted():
    """Volksbuehne publishes 168 <time datetime> markers and 96 event links,
    but has no event-ish class names and no date text inside its cards - the
    class-hint scan found zero candidates there."""
    html = '''<html><body>
      <li><time datetime="2026-09-02T19:30">2. September</time>
          <h3>Der Untergang</h3><a href="/produktion/untergang">Karten</a></li>
      <li><time datetime="2026-09-03T20:00">3. September</time>
          <h3>Hamlet</h3><a href="/produktion/hamlet">Karten</a></li>
    </body></html>'''
    events = extract_time_element_events(html, SOURCE)
    assert [e["date"] for e in events] == ["2026-09-02", "2026-09-03"]
    assert [e["title"] for e in events] == ["Der Untergang", "Hamlet"]
    assert events[0]["time"] == "19:30"
    assert events[0]["url"].endswith("/produktion/untergang")


def test_strategies_are_merged_rather_than_first_one_winning():
    """A page whose JSON-LD describes one event used to have its remaining
    cards ignored entirely."""
    html = '''<html><head>
      <script type="application/ld+json">
      {"@type":"Event","name":"Featured Gala","startDate":"2026-09-04T19:00",
       "url":"https://example.de/veranstaltung/gala",
       "location":{"name":"Grosser Saal"},"offers":{"price":"12.00"}}
      </script></head><body>
      <div class="event-card"><h3>Spaetvorstellung</h3>
        <a href="/veranstaltung/spaet">Details</a>
        <span>05.09.2026, 22:00 Uhr</span></div>
    </body></html>'''
    titles = {e["title"] for e in scrape_document(html, SOURCE, "test")}
    assert "Featured Gala" in titles
    assert "Spaetvorstellung" in titles


def test_merge_fills_gaps_between_strategies():
    """JSON-LD carries price and venue; the card scan carries the same event.
    The merged row should keep the richer fields."""
    html = '''<html><head>
      <script type="application/ld+json">
      {"@type":"Event","name":"Gala","startDate":"2026-09-04T19:00",
       "url":"https://example.de/veranstaltung/gala",
       "location":{"name":"Grosser Saal"},"offers":{"price":"12.00"}}
      </script></head><body>
      <div class="event-card"><h3>Gala</h3>
        <a href="/veranstaltung/gala">Details</a></div></body></html>'''
    gala = next(e for e in scrape_document(html, SOURCE, "test") if e["title"] == "Gala")
    assert gala["venue"] == "Grosser Saal"
    assert gala["price"] == 12.0
    assert gala["date"] == "2026-09-04"


def test_german_day_month_is_not_read_as_a_start_time():
    """staatsoper's "Mo. 10.08. Tagesvorschau" produced a time of "10:08"."""
    assert parse_time("Mo. 10.08. Tagesvorschau") == ""
    assert parse_time("Beginn 19.30 Uhr") == "19:30"
    assert parse_time("20.00") == "20:00"


# --------------------------------------------------------------------------
# Price enrichment: listing cards omit price that the event's own page states
# --------------------------------------------------------------------------

def _meetup_page(fee_json: str) -> str:
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"event":{"title":"Hike","feeSettings":'
        + fee_json + '}}}}</script></body></html>'
    )


def test_meetup_null_fee_settings_means_free_to_rsvp():
    """meetup.com never puts price in its search/listing feed at all, but the
    event's own page embeds it in a __NEXT_DATA__ JSON blob. feeSettings:
    null means no Meetup-managed fee - 40 of 251 published rows showed
    "Check site" for exactly this reason."""
    assert _meetup_fee_from_next_data(_meetup_page("null")) == 0.0


def test_meetup_populated_fee_settings_reports_the_amount():
    html = _meetup_page('{"amount": 44, "currency": "EUR"}')
    assert _meetup_fee_from_next_data(html) == 44.0


def test_meetup_page_without_next_data_reports_unknown_not_free():
    """A parse failure must stay None, not silently become "free" - the same
    distinction validate_event() already draws elsewhere in the pipeline."""
    assert _meetup_fee_from_next_data("<html><body>no data here</body></html>") is None


def test_detail_page_json_ld_offers_price_is_used():
    """rausgegangen.de's schema.org "offers" block only exists on the
    event's own page, never in the listing feed."""
    html = '''<html><head><script type="application/ld+json">
      {"@type":"Event","name":"Auf nach Sachsen Anhalt","startDate":"2026-08-29",
       "offers":{"price":0,"priceCurrency":"EUR"}}
      </script></head><body></body></html>'''
    assert _price_from_detail_page(html, "https://rausgegangen.de/en/events/x/") == 0.0


def test_detail_page_prose_price_is_used_when_no_json_ld():
    """staatsoper-berlin.de and thf-berlin.de state price only as prose on
    the event's own page ("Kosten: 15 Euro pro Person")."""
    html = "<html><body><p>Kosten: 15 Euro pro Person</p></body></html>"
    assert _price_from_detail_page(html, "https://example.de/veranstaltungen/x") == 15.0


def test_visible_text_keeps_an_in_page_header_but_drops_nav_and_footer():
    """staatsballett-berlin.de's "Eintritt frei" badge lives inside
    <header id="info">, an in-page content header, not site navigation -
    stripping every <header> discarded the very marker being searched for."""
    html = '''<html><body>
      <nav>Home | Programm | 99 EUR Gutschein</nav>
      <header id="info"><span class="badge">Eintritt frei</span></header>
      <footer>Impressum | 5 EUR Newsletter-Bonus</footer>
    </body></html>'''
    text = _visible_text(BeautifulSoup(html, "lxml"))
    assert "Eintritt frei" in text
    assert "Gutschein" not in text
    assert "Newsletter" not in text


def test_detail_page_with_no_stated_price_stays_unknown():
    """theclubmap.com and deutschestheater.de genuinely don't publish price
    anywhere on the event page (deutschestheater links out to an external
    ticket shop) - enrichment must not invent a number."""
    html = "<html><body><p>Karten kaufen im Vorverkauf.</p></body></html>"
    assert _price_from_detail_page(html, "https://example.de/produktion/x") is None


def test_enrich_missing_prices_only_fetches_what_it_needs_to():
    events = [
        {"title": "Already priced", "price": 12.0,
         "url": "https://example.de/a", "source_url": "https://example.de/list"},
        {"title": "No detail link", "price": None,
         "url": "https://example.de/list", "source_url": "https://example.de/list"},
        {"title": "Free on its own page", "price": None,
         "url": "https://example.de/b", "source_url": "https://example.de/list"},
    ]
    fetched_urls = []

    def fake_fetch(url):
        fetched_urls.append(url)
        return "<html><body><p>Eintritt frei</p></body></html>"

    enrich_missing_prices(events, fetch=fake_fetch)

    assert fetched_urls == ["https://example.de/b"]
    assert events[0]["price"] == 12.0
    assert events[1]["price"] is None
    assert events[2]["price"] == 0.0


def test_enrich_missing_prices_respects_the_fetch_cap():
    events = [
        {"title": f"Event {i}", "price": None,
         "url": f"https://example.de/e{i}", "source_url": "https://example.de/list"}
        for i in range(5)
    ]
    enrich_missing_prices(events, max_fetches=2, fetch=lambda url: "<html></html>")
    assert sum(1 for e in events if e["price"] is not None) == 0
    # Only the first two were even attempted; the rest are untouched, not
    # incorrectly marked as "checked and found nothing".
    assert all(e["price"] is None for e in events)
