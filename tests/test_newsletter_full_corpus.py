from copy import deepcopy
from datetime import datetime,timezone
from scripts.ticket_evidence import occurrence_id
from scripts.newsletter_pipeline import build_newsletter,destination_proof
from scripts.build_page_dataset import build,newsletter_payload

NOW=datetime(2026,10,28,20,tzinfo=timezone.utc)


def corpus():
 e=dict(title='Public family workshop',description='Kinderprogramm',date='2026-10-29',time='18:00',venue='Community Center West',source_url='https://events.example.org/list',url='https://events.example.org/event/workshop',observed_at=NOW.isoformat(),price=2,location_evidence=dict(city='Berlin',venue='Community Center West',host_types=['CommunityCenter'],observed_at=NOW.isoformat(),evidence_url='https://events.example.org/event/workshop'))
 fields={
  'link':{'url':e['url'],'detail_link_status':'verified'},
  'price':dict(price=2,price_min=2,price_max=2,price_status='known',price_label='€2',free_admission_confirmed=False),
  'discount':{'offers':[dict(kind='regular',amount_eur=2,price_max=2,eligibility='')],'student_discount_status':'unknown'},
 }
 overlay={'events':{occurrence_id(e):{'outcome':'matched','fields':{k:{'values':v,'observed_at':NOW.isoformat()} for k,v in fields.items()}}}}
 return {'generated_at':NOW.isoformat(),'events':[e]},overlay


def test_newsletter_uses_full_input_before_personal_filters_and_pilot_source_selection():
 data,overlay=corpus();before=deepcopy(data)
 assert build(data,overlay,NOW)['count']==0
 result=newsletter_payload(data,overlay,NOW)
 assert result['count']==1 and result['events'][0]['source_url']=='https://events.example.org/list'
 assert result['scope']=='full_source_catalog' and result['input_occurrences']==1
 assert result['events'][0]['detail_link_status']=='verified'
 assert data==before


def test_third_source_host_is_not_rejected_because_of_its_listing_domain():
 data,overlay=corpus()
 e=data['events'][0];e['venue']='Staatsoper Unter den Linden';e['location_evidence']['venue']=e['venue'];e['location_evidence']['host_types']=['Place']
 assert build_newsletter(data,overlay,NOW)['count']==1


def test_typed_cafe_cannot_claim_community_center_eligibility():
 data,overlay=corpus();data['events'][0]['location_evidence']['host_types']=['CommunityCenter','CafeOrCoffeeShop']
 assert build_newsletter(data,overlay,NOW)['count']==0


def test_full_catalog_does_not_make_unverified_discovery_newsletter_ready():
 data,_=corpus()
 result=build_newsletter(data,{'events':{}},NOW)
 assert result['count']==0 and result['exclusion_counts']['unverified_occurrence']==1


def test_generic_location_proof_must_belong_to_exact_performance():
 import json
 data,_=corpus();e=data['events'][0]
 node={'@type':'Event','name':e['title'],'startDate':'2026-10-29T18:00:00','url':e['url'],'location':{'@type':'CommunityCenter','name':e['venue'],'address':{'addressLocality':'Berlin'}}}
 html='<script type="application/ld+json">'+json.dumps(node)+'</script>'
 assert destination_proof(e,html,e['url'],NOW)['host_types']==['CommunityCenter']
 assert destination_proof(dict(e,date='2026-10-30'),html,e['url'],NOW) is None


def test_full_catalog_coverage_does_not_claim_success_for_unvisited_sources():
 data,overlay=corpus()
 data['source_catalog']=[{'name':'outside_pilot','url':'https://events.example.org/list'},{'name':'budget_limited','url':'https://other.example/list'}]
 data['source_diagnostics']=[{'outcome':'discovered'},{'outcome':'listing_budget_reserved_for_verification'}]
 result=build_newsletter(data,overlay,NOW)
 assert result['count']==1 and result['source_coverage_complete'] is False
 assert len(result['source_catalog'])==2


def test_cafe_name_cannot_inherit_park_eligibility():
 data,overlay=corpus();e=data['events'][0]
 e['venue']='Park Café';e['location_evidence'].update(venue='Park Café',host_types=['Park'])
 assert build_newsletter(data,overlay,NOW)['count']==0
