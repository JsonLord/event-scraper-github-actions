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

def test_real_berlin_buehnen_hylo_cards():
    html=Path('tests/fixtures/buehnen_live_listing.html').read_text()
    es=extract_cards(html,'https://www.berlin-buehnen.de/de/spielplan')
    assert len(es)==2
    assert es[0]['title']=='Es war einmal ein Zaubersmann'
    assert es[0]['venue']=='Pfefferberg Theater'
    assert es[0]['url'].endswith('/events/347405/')
    assert es[0]['date']=='2026-10-18' and es[0]['time']=='11:00'
    assert all('/events/' in e['url'] for e in es)

def test_real_ufa_calendar_uses_cell_date_but_only_row_prices():
    html=Path('tests/fixtures/ufa_live_listing.html').read_text()
    es=extract_cards(html,'https://ufafabrik.de/spielplan.html')
    assert len(es)==7
    assert es[0]['title']=='Verheldet' and es[0]['venue']=='Varieté Salon'
    assert es[0]['date']=='2026-10-16' and es[0]['time']=='09:30'
    assert es[0]['price']==9
    assert not enrich_evidence(es[0])['free_admission_confirmed']
    assert all('/veranstaltung/' in e['url'] for e in es)
