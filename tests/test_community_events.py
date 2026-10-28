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
 e=event();e.update(price_max=0,offers=[],free_admission_confirmed=True);assert decision(e,NOW)[0]
 e['free_admission_confirmed']=False;assert not decision(e,NOW)[0]

def test_sample_does_not_waste_budget_on_cancelled_or_ineligible_events():
 pool=[]
 for i,(day,desc,price) in enumerate([('2026-10-29','Abgesagt',0),('2026-10-29','Opera',5),('2026-11-04','Opera',10),('2026-10-30','Kinderprogramm',2),('2026-10-31','Opera',25)]):
  e=event();e.update(title='Show '+str(i),date=day,description=desc,price=price);pool.append(e)
 selected=choose_release_sample(pool,NOW)
 assert len(selected)==2 and {e['date'] for e in selected}=={'2026-10-29','2026-11-04'}
