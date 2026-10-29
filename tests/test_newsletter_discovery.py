"""Discovery must not starve catalog tail entries or weaken verification."""
from datetime import datetime,timezone
from io import BytesIO
from types import SimpleNamespace
import json
from urllib.parse import urlsplit

from scripts.newsletter_discovery import discover
from scripts.qualify_r12 import RecordingHTTP
from scripts.verify_event_details import DEFAULT_POLICY,BoundedHTTP
from scripts.newsletter_pipeline import build_newsletter
from scripts.ticket_evidence import occurrence_id

NOW=datetime(2026,10,29,10,tzinfo=timezone.utc)

class Response:
 def __init__(self,text='',status=200,mime='text/html',headers=None):
  self.status_code=status;self.headers=headers or {'Content-Type':mime};self.body=BytesIO(text.encode());self.raw=self
 def read(self,n,**kw): return self.body.read(n)
 def __enter__(self): return self
 def __exit__(self,*args): pass

class Session:
 def __init__(self,handler): self.handler=handler;self.calls=[];self.cookies=SimpleNamespace(clear=lambda:None)
 def get(self,url,**kw): self.calls.append(url);return self.handler(url)

def event_html(url):
 return '<script type="application/ld+json">'+json.dumps({'@type':'Event','name':'Public programme','startDate':'2026-10-30T18:00:00','url':url+'/event/public','location':{'name':'Community Center','address':{'addressLocality':'Berlin'}}})+'</script>'

def clients(handler):
 made=[]
 def factory(policy,**kw):
  client=RecordingHTTP(policy,session=Session(handler),validator=lambda _:True,**kw);made.append(client);return client
 return made,factory

def handler(url):
 return Response('User-agent: *\nDisallow:',mime='text/plain') if url.endswith('/robots.txt') else Response(event_html(url))

def test_all_33_sources_get_listing_capacity_even_when_verifier_budget_exhausted():
 verifier=RecordingHTTP(DEFAULT_POLICY);verifier.requests=40
 catalog=[{'name':str(i),'url':f'https://host{i}.example/list'} for i in range(33)]
 made,factory=clients(handler)
 rows,diagnostics,usage=discover(catalog,[],NOW,verifier,factory)
 assert len(rows)==33 and all(d['discovered']==1 for d in diagnostics)
 assert usage['http_attempts']==66 and usage['http_attempts']<=usage['max_http_attempts']==132
 assert verifier.requests==40 and len(made)==33
 assert usage['max_concurrent_hosts']==2

def test_same_host_searches_share_robots_and_receive_fair_capacity():
 catalog=[{'name':str(i),'url':f'https://host.example/list?q={i}'} for i in range(7)]
 made,factory=clients(handler)
 rows,diagnostics,usage=discover(catalog,[],NOW,RecordingHTTP(DEFAULT_POLICY),factory)
 assert all(d['listing_received'] for d in diagnostics)
 assert len(made)==1 and usage['http_attempts']==8
 assert sum(u.endswith('/robots.txt') for u in made[0].session.calls)==1

def test_reused_source_reports_actual_occurrences_without_network():
 e=dict(title='Existing',source_url='https://a.example/list')
 _,factory=clients(lambda _: (_ for _ in ()).throw(AssertionError('network used')))
 rows,diagnostics,usage=discover([{'name':'ufa','url':e['source_url']}],[e],NOW,RecordingHTTP(DEFAULT_POLICY),factory)
 assert rows==[] and diagnostics[0]['discovered']==1 and diagnostics[0]['listing_received']
 assert diagnostics[0]['outcome']=='fresh_discovery_reused' and usage['http_attempts']==0

def test_blocked_host_is_cached_for_later_sources_and_detail_verification():
 def blocked(url):
  return handler(url) if url.endswith('/robots.txt') else Response(status=403)
 verifier=RecordingHTTP(DEFAULT_POLICY)
 made,factory=clients(blocked)
 _,diagnostics,usage=discover([{'name':str(i),'url':f'https://host.example/list{i}'} for i in range(2)],[],NOW,verifier,factory)
 assert usage['http_attempts']==2
 assert 'host.example' in verifier.blocked
 assert not verifier.fetch('https://host.example/detail') and verifier.requests==0
 assert diagnostics[0]['outcome']=='http_403'

def test_robots_denial_never_fetches_listing_or_structured_fallback():
 made,factory=clients(lambda _:Response('User-agent: *\nDisallow: /',mime='text/plain'))
 _,d,u=discover([{'name':'club','url':'https://www.theclubmap.com/list'}],[],NOW,RecordingHTTP(DEFAULT_POLICY),factory)
 assert u['http_attempts']==1 and d[0]['robots_policy']=='denied'
 assert not d[0]['listing_received']

def test_public_api_fallback_uses_performance_timestamp_not_wordpress_publication_date():
 def api(url):
  if url.endswith('/robots.txt'): return handler(url)
  if '/wp-json/wp/v2/' in url:
   return Response(json.dumps([{'date':'2026-10-30T18:00:00','title':{'rendered':'Publication only'}}]),mime='application/json')
  if '/wp-json/tribe/' in url:
   return Response(json.dumps({'events':[{'title':'Actual public event','start_date':'2026-10-30 18:00:00','url':'https://www.theclubmap.com/event/public','venue':{'venue':'Theater'}}]}),mime='application/json')
  return Response('<h1>Calendar</h1>')
 made,factory=clients(api)
 rows,d,u=discover([{'name':'club','url':'https://www.theclubmap.com/list'}],[],NOW,RecordingHTTP(DEFAULT_POLICY),factory)
 assert [e['title'] for e in rows]==['Actual public event']
 assert u['http_attempts']==4 and d[0]['structured_fallback']=='public_wordpress_events'
 assert not any('/wp-json/' in url for url in made[0].session.calls[:2])

def test_http_json_is_opt_in_and_rejects_html_challenge():
 s=Session(lambda url: handler(url) if url.endswith('/robots.txt') else Response('{}',mime='application/json'))
 http=BoundedHTTP(DEFAULT_POLICY,session=s,validator=lambda _:True)
 assert http.fetch('https://a.example/api') is None and http.reason=='unsupported_mime'
 assert http.fetch('https://a.example/api',accept_json=True)
 s.handler=lambda _:Response('<h1>Just a moment...</h1>')
 assert http.fetch('https://a.example/api',accept_json=True) is None

def test_zero_verified_occurrences_cannot_be_complete_source_coverage():
 event=dict(title='Public programme',date='2026-10-30',time='18:00',venue='Theater',url='https://a.example/event/1',source_url='https://a.example/list')
 data=dict(events=[event],source_catalog=[{'name':'a','url':event['source_url']}],source_diagnostics=[dict(name='a',url=event['source_url'],outcome='discovered',discovered=1,listing_received=True)])
 result=build_newsletter(data,{'events':{}},NOW)
 assert result['source_coverage_complete'] is False
 assert result['coverage_metrics']['listing_sources_received']==1
 assert result['coverage_metrics']['candidate_url_occurrences']==1
 assert result['coverage_metrics']['exact_matched_occurrences']==0

def test_query_sanitization_does_not_attribute_one_search_result_to_every_source():
 event=dict(title='Public programme',date='2026-10-30',time='18:00',venue='Theater',url='https://a.example/event/1',source_url='https://a.example/list',discovery_source_names=['running'])
 data=dict(events=[event],source_catalog=[{'name':'running'},{'name':'yoga'}],source_diagnostics=[dict(name=n,url=event['source_url'],outcome='discovered',discovered=1) for n in ('running','yoga')])
 result=build_newsletter(data,{'events':{}},NOW)
 assert [d['candidate_url_occurrences'] for d in result['source_diagnostics']]==[1,0]


def test_deduplication_retains_all_discovery_source_names():
 from scripts.event_utils import dedupe_events
 a=dict(title='Public event',date='2026-10-30',time='18:00',venue='Theater',url='https://a.example/event/1',source_url='https://a.example/list',has_detail_link=True,discovery_source_names=['running'])
 b=dict(a,discovery_source_names=['find'])
 assert dedupe_events([a,b])[0]['discovery_source_names']==['find','running']


def test_eventon_unix_time_is_berlin_local_including_dst():
 from scripts.generic_event_scraper import _from_eventon
 timestamp=int(datetime(2026,10,30,23,30,tzinfo=timezone.utc).timestamp())
 rows=_from_eventon([{'meta':{'evcal_srow':timestamp},'title':{'rendered':'Night performance'}}],'https://a.example/list')
 assert (rows[0]['date'],rows[0]['time'])==('2026-10-31','00:30')
