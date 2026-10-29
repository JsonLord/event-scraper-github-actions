from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from scripts import generic_event_scraper as scraper
from scripts.event_utils import validate_events

FIXTURES = Path(__file__).parent / 'fixtures'
SOURCE = 'https://www.berlin-buehnen.de/de/spielplan'


def fixture(day):
    return (FIXTURES / f'berlin_buehnen_listing_{day}_captured_2026-10-29.html').read_text()


def test_custom_component_links_are_bound_to_their_own_title_time_and_venue():
    rows = scraper.scrape_document(fixture('2026-11-01'), SOURCE, 'captured fixture')
    assert len(rows) == 3  # Mobile/desktop copies are one occurrence.
    expected = [
        ('Keine Panik! Resilienz in der Polykrise – FIfF-Konferenz 2026', '10:00',
         'Theater im Delphi', '376780'),
        ('Die große Zaubershow des Ala Labama', '11:00', 'Pfefferberg Theater', '281573'),
        ('Krakenkarussell', '11:00', 'Theater der kleinen Form', '350371'),
    ]
    for row, (title, time, venue, identifier) in zip(rows, expected):
        assert (row['title'], row['date'], row['time'], row['venue']) == (title, '2026-11-01', time, venue)
        assert row['url'].startswith(SOURCE + '/') and row['url'].endswith(f'/events/{identifier}/')
        assert row['source_url'] == SOURCE and row['price'] is None
    clean, _ = validate_events(rows, SOURCE, date(2026, 11, 1), date(2026, 11, 7))
    assert len(clean) == 3 and all(row['has_detail_link'] for row in clean)


def test_second_date_keeps_room_names_and_never_uses_subtitles_as_venues():
    rows = scraper.scrape_document(fixture('2026-11-02'), SOURCE, 'captured fixture')
    assert len(rows) == 3
    assert [(row['title'], row['venue']) for row in rows] == [
        ('aneinander-vorbei', 'GRIPS Theater | GRIPS Podewil'),
        ('Die Verwandlung', 'ATZE Musiktheater | Großer Saal'),
        ('Pippi Langstrumpf', 'Komische Oper Berlin | Schillertheater - Großer Saal'),
    ]
    assert all(row['date'] == '2026-11-02' and row['price'] is None for row in rows)


def test_unsafe_missing_or_non_event_card_links_are_not_replaced_with_other_links():
    for href in (None, '/de/spielplan/', '/de/spielplan/show/events/376780/?token=x',
                 'https://other.example/de/spielplan/show/events/376780/',
                 'https://user@www.berlin-buehnen.de/de/spielplan/show/events/376780/'):
        soup = BeautifulSoup(fixture('2026-11-01'), 'lxml')
        card = soup.select('hylo-router-link.event-list-item')[0]
        # Keep the card selector for a missing/empty href; never search ticket siblings.
        card['href'] = href or ''
        rows = scraper.scrape_document(str(soup), SOURCE, 'mutated fixture')
        assert len(rows) == 2 and all('376780' not in row['url'] for row in rows)


def test_conflicting_performance_or_title_and_missing_venue_fail_closed():
    for mutation in ('time', 'title', 'venue'):
        soup = BeautifulSoup(fixture('2026-11-01'), 'lxml')
        card = soup.select('hylo-router-link.event-list-item')[0]
        if mutation == 'time':
            card.select('time[datetime]')[-1]['datetime'] = '2026-11-01 11:00'
        elif mutation == 'title':
            card.select('h3')[-1].string = 'Another performance'
        else:
            for heading in card.select('[slot="end"] h4'):
                heading.decompose()
        rows = scraper.scrape_document(str(soup), SOURCE, 'mutated fixture')
        assert len(rows) == 2 and all('376780' not in row['url'] for row in rows)


def test_date_horizon_keeps_exact_event_urls_across_days(monkeypatch):
    def captured(url):
        day = '2026-11-02' if '2026-11-02' in url else '2026-11-01'
        return scraper.scrape_document(fixture(day), url, 'captured fixture')
    monkeypatch.setattr(scraper, 'scrape', captured)
    rows = scraper.scrape_date_horizon(SOURCE, 1, start_day=date(2026, 11, 1))
    assert len(rows) == 6
    assert {row['date'] for row in rows} == {'2026-11-01', '2026-11-02'}
    assert all('/events/' in row['url'] and row['source_url'] == SOURCE for row in rows)


def test_source_specific_component_adapter_is_not_used_on_other_hosts():
    from scripts.official_source_adapters import official_programme_cards
    assert official_programme_cards(fixture('2026-11-01'), 'https://other.example/list') is None
