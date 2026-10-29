from datetime import date
import pytest
from scripts.event_utils import looks_synthetic_title, dedupe_events, validate_event
from scripts.ticket_evidence import enrich_evidence, occurrence_id, structured_offers

@pytest.mark.parametrize('title', ['Ausverkauft Theater', 'Theater Comedy & Kabarett', 'Ermäßigt €17,00', 'Studenten (nur im VVK) €12,00'])
def test_pseudo_titles(title):
    assert looks_synthetic_title(title)

@pytest.mark.parametrize('title', ['Theater', 'Free', 'Straße – Grüße!', 'Ausverkauft: das Musical'])
def test_real_names(title):
    assert not looks_synthetic_title(title)

def test_range_and_unknown_are_not_free():
    e = enrich_evidence({'description': '0–45€', 'price': 0})
    assert (e['price_min'], e['price_max']) == (0, 45)
    assert e['price_label'] != 'Free' and not e['free_admission_confirmed']
    assert enrich_evidence({'description':'keine Preisangabe', 'price':0})['price'] is None

def test_discount_kind_and_tickets_are_not_inventory():
    e = enrich_evidence({'description':'Ermäßigt €17,00; Studenten (nur im VVK) €12,00 Tickets'})
    assert [o['kind'] for o in e['offers']] == ['reduced', 'student']
    assert e['ticket_status'] == 'unknown'
    assert enrich_evidence({'description':'Ermäßigt €12'})['student_discount_status'] == 'unknown'

def test_multi_offers_and_cancellation():
    offers = structured_offers([{'price':12,'name':'Studenten','availability':'https://schema.org/InStock'}, {'price':18,'availability':'https://schema.org/SoldOut'}])
    assert len(offers) == 2
    e = enrich_evidence({'offers':offers, 'description':'Abgesagt'})
    assert e['event_status'] == 'cancelled' and e['ticket_status'] == 'unknown'

def test_occurrences_do_not_collapse():
    events = [dict(title='Grüße!',date=d,time=t,url='https://a.de/show',has_detail_link=True) for d,t in [('2026-10-17','19:00'),('2026-10-18','19:00'),('2026-10-18','21:00')]]
    assert len(dedupe_events(events)) == 3
    assert len({occurrence_id(e) for e in events}) == 3

def test_candidate_is_not_verified():
    e = validate_event(dict(title='Grüße!',date='2026-10-17',url='https://a.de/show'), 'https://a.de/',date(2026,10,17),date(2026,10,18))
    assert e['has_detail_link'] and e['detail_link_status'] == 'candidate'

def test_partial_price_in_legacy_title_does_not_destroy_range():
    e=enrich_evidence(dict(title='46 Quadratmeter THEATER THIKWA 18,40 to',description='Today | 18:00 46 Quadratmeter THEATER THIKWA 18,40 to 28,70 €',price=18.4))
    assert e['price_min']==18.4 and e['price_max']==28.7

def test_show_named_free_is_not_admission_proof():
    e=enrich_evidence(dict(title='Free',description='Today | Free keine Preisangabe',price=0))
    assert not e['free_admission_confirmed'] and e['price'] is None
