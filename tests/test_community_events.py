from copy import deepcopy
from datetime import datetime,timezone
import pytest
from scripts.community_events import decision,newsletter
from scripts.qualify_r14 import choose_release_sample

NOW=datetime(2026,10,28,20,tzinfo=timezone.utc)

def event():
 return dict(title='Public opera introduction',date='2026-10-29',time='18:15',venue='Staatsoper Unter den Linden',source_url='https://www.berlin-buehnen.de/de/spielplan',url='https://www.berlin-buehnen.de/de/spielplan/show/events/1/',verification_outcome='matched',detail_link_status='verified',field_observed_at={'price':NOW.isoformat(),'link':NOW.isoformat()},pilot_location={'city':'Berlin','venue':'Staatsoper Unter den Linden','observed_at':NOW.isoformat()},price_max=5,price_status='known',ticket_status='unknown',offers=[dict(kind='regular',eligibility='',amount_eur=5,price_max=5)])

def test_regular_public_five_euro_event_qualifies_without_promising_inventory():
 e=event();assert decision(e,NOW)[0]
 out=newsletter([e],NOW);assert out['count']==1 and out['events'][0]['availability_note']=='Ticket inventory unknown'

@pytest.mark.parametrize('patch',[{'venue':'Small café'}, {'venue':'Private Bar Lounge'},{'offers':[dict(kind='student',amount_eur=3)]},{'offers':[dict(kind='child',amount_eur=3)]},{'offers':[dict(kind='regular',amount_eur=6,eligibility='')]},{'offers':[dict(kind='regular',amount_eur=2,price_max=10,eligibility='')]},{'price_status':'conflicted'},{'ticket_status':'sold_out'},{'description':'Members only'},{'verification_outcome':'content_mismatch'},{'field_observed_at':{}},{'date':'2026-10-27'},{'claim_expires_at':'2026-10-28T19:00:00Z'}])
def test_unvalidated_restricted_expensive_or_small_host_events_do_not_qualify(patch):
 e=event();e.update(patch);assert not decision(e,NOW)[0]

def test_free_requires_independent_proof():
 e=event();e.update(price_max=0,offers=[dict(kind="regular",amount_eur=0,source="jsonld_offer",eligibility="")],free_admission_confirmed=True);assert decision(e,NOW)[0]
 e['free_admission_confirmed']=False;assert not decision(e,NOW)[0]

def test_sample_does_not_waste_budget_on_cancelled_or_ineligible_events():
 pool=[]
 for i,(day,desc,price) in enumerate([('2026-10-29','Abgesagt',0),('2026-10-29','Opera',5),('2026-11-04','Opera',10),('2026-10-30','Kinderprogramm',2),('2026-10-31','Opera',25)]):
  e=event();e.update(title='Show '+str(i),date=day,description=desc,price=price);pool.append(e)
 selected=choose_release_sample(pool,NOW)
 assert len(selected)==2 and {e['date'] for e in selected}=={'2026-10-29','2026-11-04'}

def test_newsletter_uses_public_price_not_student_minimum():
 e=event();e.update(price_min=1,price_label='From €1',offers=e['offers']+[dict(kind='student',amount_eur=1)])
 row=newsletter([e],NOW)['events'][0]
 assert row['price_min']==5 and row['price_label']=='€5 regular public admission'

def test_conditional_free_words_are_not_enough():
 e=event();e.update(free_admission_confirmed=True,price_max=0,offers=[])
 assert not decision(e,NOW)[0]

def test_real_ufa_declared_multi_performance_schedule_has_isolated_evidence():
 from pathlib import Path
 from scripts.event_matching import semantic_candidates
 from scripts.verify_event_details import observation
 html=Path('tests/fixtures/ufa_gardizero_2026-10-28.html').read_text()
 url='https://ufafabrik.de/veranstaltung/39876/gardizero'
 rows=semantic_candidates(html,url,'GardiZero')
 assert {(r['date'],r['time']) for r in rows}=={('2026-10-30','20:00'),('2026-10-31','20:00')}
 for row in rows:
  result=observation(dict(row,source_url='https://ufafabrik.de/spielplan.html'),html,url,NOW.isoformat())
  assert result['price']['values']['price_min']==12 and result['price']['values']['price_max']==25
  assert 'status' not in result
  assert observation(dict(row,date='2026-11-01',source_url='https://ufafabrik.de/spielplan.html'),html,url,NOW.isoformat()) is None
 assert semantic_candidates(html,url,'Wrong show')==[]
 assert semantic_candidates(html.replace('Fr.-Sa. 20:00 Uhr','20:00 Uhr'),url,'GardiZero')==[]

def test_reviewed_public_square_event_and_named_regular_admission():
 e=event();e['venue']='Bebelplatz';e['pilot_location']['venue']='Bebelplatz';e['offers'][0]['eligibility']='Standard'
 assert decision(e,NOW)[0]
 e['offers'][0]['eligibility']='Members only';assert not decision(e,NOW)[0]

def test_listing_sold_out_warning_prevents_newsletter_despite_silent_detail():
 e=event();e.update(listing_ticket_status='sold_out',ticket_status='unknown')
 assert not decision(e,NOW)[0]
 e.pop('listing_ticket_status');e['description']='Ausverkauft';assert not decision(e,NOW)[0]
