from pathlib import Path
import pytest
from scripts.source_adapters import extract_cards
from scripts.ticket_evidence import enrich_evidence

@pytest.mark.parametrize('host',['ufafabrik.de','www.berlin-buehnen.de'])
def test_card_relationships(host):
    events = extract_cards(Path('tests/fixtures/source_cards.html').read_text(),f'https://{host}/spielplan')
    assert [e['title'] for e in events] == ['Grüße – Straße!','Free']
    first, second = map(enrich_evidence, events)
    assert first['venue'] == 'Theater Berlin' and len(first['offers']) == 3
    assert first['ticket_status'] == 'sold_out'
    assert second['price'] is None and second['offers'] == []
    assert first['url'].endswith('/events/gruesse')

def test_per_day_horizon():
    e = extract_cards('<article><h3>Grüße</h3><p>19:00</p></article>','https://www.berlin-buehnen.de/de/spielplan?date=2026-10-18')
    assert e[0]['date'] == '2026-10-18'
