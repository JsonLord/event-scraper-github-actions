import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.robotparser import RobotFileParser
import pytest
import requests
from scripts.verify_event_details import BoundedHTTP, DEFAULT_POLICY, observation, run, select_targets
from scripts.build_page_dataset import merge_overlay, build
from scripts.ticket_evidence import occurrence_id

NOW='2026-10-17T07:17:00Z'
EVENT=dict(title='Grüße – Straße!',date='2026-10-18',time='19:00',venue='Theater Berlin',url='https://a.example/events/show',source_url='https://a.example/events',has_detail_link=True)

class Response:
    def __init__(self,status=200,body='<html>ok</html>',headers=None):
        self.status_code=status;self.headers=headers or {'Content-Type':'text/html'};self.raw=self
        self.body=io.BytesIO(body.encode())
    def read(self,n,**kw): return self.body.read(n)
    def __enter__(self): return self
    def __exit__(self,*args): pass

class Session:
    def __init__(self,responses): self.responses=iter(responses);self.calls=[];self.cookies=SimpleNamespace(clear=lambda:None)
    def get(self,url,**kw): self.calls.append((url,kw));return next(self.responses)

def http(responses,**caps):
    policy=dict(DEFAULT_POLICY,**caps);s=Session(responses);h=BoundedHTTP(policy,s,validator=lambda _:True)
    p=RobotFileParser();p.parse([]);h.robots['https://a.example']=p
    return h,s

@pytest.mark.parametrize('cap',[1,3,8])
def test_redirects_retries_count_and_stop(cap):
    h,s=http([Response(302,headers={'Location':'/next'})]*10,max_http_requests_per_run=cap)
    assert h.fetch(EVENT['url']) is None
    assert h.requests==cap and len(s.calls)==cap
    assert all(call[1]['allow_redirects'] is False for call in s.calls)

def test_per_host_retry_and_no_auth_cookies():
    h,s=http([Response(500),Response(200)],max_requests_per_host=2)
    assert h.fetch(EVENT['url']) and h.requests==2
    assert h.fetch(EVENT['url']) is None and h.requests==2
    assert s.calls[0][1]['timeout']==(8,12)

@pytest.mark.parametrize('status',[403,429])
def test_denials_not_retried(status):
    h,s=http([Response(status)])
    assert not h.fetch(EVENT['url']) and not h.fetch(EVENT['url'])
    assert h.requests==1

def test_challenge_and_mime_and_bytes():
    h,_=http([Response(body='<title>Just a moment...</title>')]); assert not h.fetch(EVENT['url'])
    h,_=http([Response(headers={'Content-Type':'image/png'})]);assert not h.fetch(EVENT['url'])
    h,_=http([Response(body='a'*101)],max_response_bytes=100);assert not h.fetch(EVENT['url']) and h.bytes==100
    h,_=http([Response(body='a'*99),Response(body='b'*99)],max_total_response_bytes=150)
    assert h.fetch(EVENT['url']);assert not h.fetch(EVENT['url']);assert h.bytes==150

def test_robots_uses_budget_and_denies_provider_fallback():
    s=Session([Response(body='User-agent: *\nDisallow: /events',headers={'Content-Type':'text/plain'})])
    h=BoundedHTTP(DEFAULT_POLICY,s,validator=lambda _:True)
    assert not h.fetch(EVENT['url']) and h.requests==1 and not h.permitted

def test_unsafe_and_cross_host_redirect():
    h,s=http([Response(302,headers={'Location':'http://127.0.0.1/'})])
    assert not h.fetch(EVENT['url']) and h.requests==1
    h=BoundedHTTP(DEFAULT_POLICY,s,validator=lambda _:False)
    assert not h.fetch('http://localhost/') and h.requests==0

def page(**changes):
    node=dict({'@type':'Event','name':EVENT['title'],'startDate':'2026-10-18T19:00','location':{'name':EVENT['venue']},'offers':{'price':12,'priceCurrency':'EUR','availability':'https://schema.org/InStock'}},**changes)
    return '<script type="application/ld+json">'+json.dumps(node)+'</script>'

def test_matching_date_title_venue_required_not_http200():
    assert observation(EVENT,page(),EVENT['url'],NOW)['status']['values']['ticket_status']=='available'
    for change in [dict(name='Other show'),dict(startDate='2026-10-19T19:00'),dict(startDate='2026-10-18T21:00'),dict(location={'name':'Other theatre'})]:
        assert observation(EVENT,page(**change),EVENT['url'],NOW) is None
    assert observation(EVENT,page(),'https://a.example/',NOW) is None
    assert observation(EVENT,'<nav>Sold out Free Tickets</nav>',EVENT['url'],NOW) is None

def test_semantic_html_scoped_no_neighbour_status():
    html='<nav>Ausverkauft</nav><article><h1>Grüße – Straße!</h1><time datetime="2026-10-18T19:00"></time><p class="venue">Theater Berlin</p><p>Tickets</p></article>'
    obs=observation(EVENT,html,EVENT['url'],NOW)
    assert 'status' not in obs and 'price' not in obs

def test_status_conflict_and_cancellation_precedence():
    html=page()+page(offers={'price':15,'availability':'https://schema.org/SoldOut'})
    obs=observation(EVENT,html,EVENT['url'],NOW)
    assert obs['status']['values']['ticket_status']=='unknown'
    assert obs['price']['values']['price_status']=='conflicted'
    obs=observation(EVENT,page(eventStatus='https://schema.org/EventCancelled'),EVENT['url'],NOW)
    assert obs['event_status']['values']['event_status']=='cancelled'
    assert 'status' not in obs

def test_ttl_and_newer_discovery_precedence():
    obs=observation(EVENT,page(),EVENT['url'],NOW)
    overlay={'events':{occurrence_id(EVENT):{'fields':obs}}}
    current=merge_overlay([EVENT],overlay,NOW)[0]
    assert current['ticket_status']=='available' and current['detail_link_status']=='verified'
    later=merge_overlay([EVENT],overlay,'2026-10-18T00:00:00Z')[0]
    assert later['ticket_status']=='unknown' and later['price']==12
    stale=merge_overlay([EVENT],overlay,'2026-10-25T00:00:00Z')[0]
    assert stale['ticket_status']=='unknown' and stale.get('detail_link_status')!='verified'
    newer=dict(EVENT,observed_at='2026-10-17T08:00:00Z',ticket_status='sold_out')
    assert merge_overlay([newer],overlay,'2026-10-17T09:00:00Z')[0]['ticket_status']=='sold_out'

def test_dry_run_fairness_dedup_targets_and_no_network():
    events=[dict(EVENT,title=f'Show {i}',url=f'https://a.example/events/{i}') for i in range(100)]
    events += [dict(EVENT,title='Second host',source_url='https://b.example/events')]
    result,usage=run(events,{'events':{}},NOW,dry_run=True)
    assert usage['targets']==40 and usage['http_attempts']==usage['tinyfish_fetch_urls']==0
    selected=select_targets(events,datetime(2026,10,17,tzinfo=timezone.utc),{},DEFAULT_POLICY)
    assert any(e['title']=='Second host' for e in selected[:2])

def test_failure_preserves_history_keyless(monkeypatch):
    monkeypatch.delenv('TINYFISH_API_KEY',raising=False)
    obs=observation(EVENT,page(),EVENT['url'],'2026-10-16T00:00:00Z')
    previous={'events':{occurrence_id(EVENT):{'fields':obs}}}
    h,s=http([Response(403)])
    result,usage=run([EVENT],previous,NOW,http=h)
    assert result['events'][occurrence_id(EVENT)]['fields']==obs
    assert usage['tinyfish_fetch_urls']==usage['tinyfish_search_queries']==0

def test_shared_build_offline_quality():
    data=json.load(open('data/events.json'))
    result=build(data,{'events':{}},NOW)
    assert result['count']==len(result['events'])>0
    assert all(e['ticket_status']!='available' for e in result['events'])

def test_provider_caps_are_independent_of_targets_and_http(monkeypatch):
    from scripts.tinyfish_client import TinyFishClient
    monkeypatch.setenv('TINYFISH_API_KEY','fixture-secret')
    class Transport:
        def get(self,url,**kw):
            return SimpleNamespace(status_code=200,json=lambda:{'results':[{'url':'https://a.example/events/candidate'}]})
        def post(self,url,**kw):
            return SimpleNamespace(status_code=200,json=lambda:{'results':[],'errors':[{'url':kw['json']['urls'][0]}]})
    class HTTP:
        requests=bytes=0;permitted=True;reason='blocked'
        def fetch(self,url): return None
    t=TinyFishClient(Transport(),sleep=lambda _:None,validator=lambda _:True)
    events=[dict(EVENT,title=f'Event occurrence {i}',url=f'https://a.example/events/{i}') for i in range(40)]
    output,usage=run(events,{'events':{}},NOW,http=HTTP(),tinyfish=t)
    assert usage['targets']==40 and usage['tinyfish_fetch_urls']==30 and usage['http_attempts']==0
    missing=[dict(e,url=e['source_url'],has_detail_link=False) for e in events]
    t=TinyFishClient(Transport(),sleep=lambda _:None,validator=lambda _:True)
    _,usage=run(missing,{'events':{}},NOW,http=HTTP(),tinyfish=t)
    assert usage['tinyfish_search_queries']==12 and usage['tinyfish_fetch_urls']==12
    assert len(output['events'])==40

def test_ambiguous_unknown_time_cannot_confirm_performance():
    assert observation(dict(EVENT,time=''),page(),EVENT['url'],NOW) is None

def test_policy_cannot_raise_hard_caps(tmp_path):
    from scripts.verify_event_details import policy_from
    path=tmp_path/'policy.json';path.write_text(json.dumps({'max_http_requests_per_run':1000,'max_tinyfish_fetch_urls_per_run':999,'ttl_hours':{'available':999}}))
    policy=policy_from(path)
    assert policy['max_http_requests_per_run']==40 and policy['max_tinyfish_fetch_urls_per_run']==30 and policy['ttl_hours']['available']==12

def test_missing_venue_requires_official_identity_not_just_title_date():
    target=dict(EVENT,venue='')
    obs=observation(target,page(),EVENT['url'],NOW)
    assert obs['link']['match_basis']=='official_canonical_occurrence'
    assert observation(target,page(),'https://a.example/events/other',NOW) is None
    assert observation(target,page(),'https://third-party.example/events/show',NOW) is None
    assert observation(EVENT,page(location={'name':'Wrong venue'}),EVENT['url'],NOW) is None

def test_official_id_hierarchy_still_requires_performance_and_official_host():
    from scripts.event_matching import match_basis
    target=dict(EVENT,venue='',official_event_id='performance-42')
    candidate=dict(EVENT,venue='',url='https://a.example/events/new',official_event_id='performance-42')
    assert match_basis(target,candidate,candidate['url'])=='official_id_occurrence'
    assert match_basis(target,dict(candidate,date='2026-10-19'),candidate['url']) is None
    assert match_basis(target,candidate,'https://unrelated.example/events/new') is None

def test_attribute_free_semantic_html_and_neighbour_rejection():
    html='<main><h1>Grüße – Straße!</h1><p>18.10.2026 19:00</p><p>Ort: Theater Berlin</p><p>Eintritt: €12,00</p><p>Tickets verfügbar</p></main>'
    obs=observation(EVENT,html,EVENT['url'],NOW)
    assert obs['link']['match_basis']=='title_occurrence_venue'
    assert obs['price']['values']['price']==12
    assert obs['status']['values']['ticket_status']=='available'
    for changed in [html.replace('Ort: Theater Berlin','Ort: Wrong venue'),html.replace('18.10.2026','19.10.2026'),html.replace('</main>','<h2>Nearby event</h2><p>Ausverkauft €3</p></main>')]:
        assert observation(EVENT,changed,EVENT['url'],NOW) is None
    negative=observation(EVENT,html.replace('Tickets verfügbar','Keine Tickets verfügbar'),EVENT['url'],NOW)
    assert 'status' not in negative

def test_http_deadline_stops_without_spending_request_budget():
    h,s=http([Response()]);h.deadline=10;h.clock=lambda:0
    assert not h.fetch(EVENT['url']) and h.requests==0 and h.reason=='run_deadline'
