from datetime import datetime,timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser
import json
from scripts.generic_event_scraper import scrape_document
from scripts.raus_selective import candidate_url,discover,detail_candidates
from scripts.qualify_restored_branch import sample_one

FIXTURES=Path(__file__).parent/'fixtures'
NOW=datetime(2026,10,29,12,tzinfo=timezone.utc)
RAUS='https://rausgegangen.de/en/events/real-occurrence-1/'


def test_museum_exact_event_link_venue_and_conditional_price():
 rows=scrape_document((FIXTURES/'berlin_museum_listing_2026-10-29.html').read_text(),'https://www.berlin.museum/programm','fixture')
 e=next(e for e in rows if e['title']=='Sonntag im Nikolaiviertel')
 assert e['venue']=='Ephraim-Palais' and e['url'].endswith('/veranstaltungen/sonntag-im-nikolaiviertel-november')
 assert (e['date'],e['time'],e['price'])==('2026-11-01','10:00',None)


def test_volks_room_is_not_workshop_subtitle_and_other_card_price_does_not_bleed():
 rows=scrape_document((FIXTURES/'volksbuehne_listing_2026-10-29.html').read_text(),'https://www.volksbuehne-berlin.de/','fixture')
 raw=next(e for e in rows if e['title']=='Raw Voice Lab')
 assert (raw['venue'],raw['time'],raw['price'])==('Grüner Salon','15:00',0)
 other=next(e for e in rows if e['title']=='Mata Leão')
 assert other['venue']=='Große Bühne' and other['price'] is None


def test_official_adapter_does_not_affect_unrelated_source():
 html=(FIXTURES/'volksbuehne_listing_2026-10-29.html').read_text()
 from scripts.official_source_adapters import official_programme_cards
 assert official_programme_cards(html,'https://other.example/list') is None


def jsonld(city='Berlin'):
 node={'@type':'Event','name':'Real occurrence','startDate':'2026-10-30T19:00:00','url':RAUS,'location':{'name':'Public Theatre','address':{'addressLocality':city}}}
 return '<script type="application/ld+json">'+json.dumps(node)+'</script>'

class Provider:
 search_queries=0;fetch_urls=0;diagnostics=[];diagnostic='fixture'
 def __init__(self,urls=None,html=None):self.urls=urls or [RAUS];self.html=html or jsonld();self.fetched=[]
 def search(self,query):
  assert 'site:rausgegangen.de/' in query and 'Berlin' in query
  self.search_queries+=1;return self.urls
 def fetch(self,urls):
  self.fetch_urls+=len(urls);self.fetched.extend(urls)
  return {u:dict(final_url=u,html=self.html) for u in urls}

class HTTP:
 requests=0;limit=8;documents={};reason='http_403'
 def __init__(self,allowed=True,direct=None):
  r=RobotFileParser();r.parse(['User-agent: *','Disallow: '+('' if allowed else '/')])
  self.robots={'https://rausgegangen.de':r};self.documents={};self.direct=direct
 def fetch(self,url):
  self.requests+=1;return (url,self.direct) if self.direct else None


def test_raus_only_fallback_never_sends_other_hosts_or_listing_urls_to_fetch():
 provider=Provider([RAUS,'https://www.berlin.museum/event/1','https://rausgegangen.de/en/berlin/eventsbydate/','https://rausgegangen.de/en/events/real-occurrence-1/?token=x'])
 events,d=discover(NOW,HTTP(),1000,provider)
 assert len(events)==1 and events[0]['title']=='Real occurrence'
 assert provider.fetched==[RAUS] and provider.search_queries==2
 assert d['fetch_urls']==1 and events[0]['destination_city']=='Berlin'


def test_robots_denial_never_reaches_provider_fetch():
 provider=Provider()
 events,d=discover(NOW,HTTP(allowed=False),1000,provider)
 assert events==[] and provider.fetch_urls==0
 assert d['attempted_destinations'][0]['robots_permitted'] is False


def test_three_destination_limit_and_locale_deduplication():
 urls=[RAUS,RAUS.replace('/en/','/'),*[f'https://rausgegangen.de/events/event-{i}/' for i in range(8)]]
 provider=Provider(urls)
 _,d=discover(NOW,HTTP(),1000,provider)
 assert len(d['attempted_destinations'])==3 and provider.fetch_urls==3 and provider.search_queries==2
 assert len(set(provider.fetched))==3


def test_direct_success_does_not_spend_fetch_allowance():
 provider=Provider()
 events,d=discover(NOW,HTTP(direct=jsonld()),1000,provider)
 assert len(events)==1 and provider.fetch_urls==0
 assert d['attempted_destinations'][0]['transport']=='direct_http'


def test_search_candidates_and_non_berlin_detail_are_not_events():
 provider=Provider(html=jsonld('Hamburg'))
 events,d=discover(NOW,HTTP(),1000,provider)
 assert events==[] and d['attempted_destinations'][0]['outcome']=='no_exact_berlin_occurrence'


def test_official_destination_redirect_to_different_event_is_rejected():
 class Redirect(Provider):
  def fetch(self,urls):
   self.fetch_urls+=1
   return {urls[0]:dict(final_url='https://rausgegangen.de/events/other-show/',html=jsonld())}
 events,d=discover(NOW,HTTP(),1000,Redirect())
 assert events==[] and d['attempted_destinations'][0]['outcome']=='provider_destination_rejected'


def test_semantic_detail_reads_header_and_venue_without_adopting_body_prices():
 html='''<h1>Real occurrence</h1><p>Fr, 30. Oct 2026</p><p>19:00 – 22:00</p><p>In the organizer's words:</p><p>Free companion; €42; unrelated content.</p><p>Location</p><p>Venue</p><p>Public Theatre</p><p>Street 1, 10115 Berlin</p><p>FOLLOW</p>'''
 events=detail_candidates(html,RAUS)
 assert len(events)==1 and (events[0]['date'],events[0]['time'],events[0]['venue'])==('2026-10-30','19:00','Public Theatre')
 assert '42' not in events[0]['description'] and events[0].get('price') is None


def test_candidate_domain_path_and_secret_allowlist():
 for url in ['https://rausgegangen.de.evil.example/events/show/','http://rausgegangen.de/events/show/','https://rausgegangen.de/events/show/?auth=x','https://rausgegangen.de/venues/place/']:
  assert not candidate_url(url)


def test_real_raw_voice_lab_detail_matches_correct_room_and_rejects_subtitle_or_neighbour_date():
 html=(FIXTURES/'volksbuehne_raw_voice_lab_detail_2026-10-30.html').read_text()
 url='https://www.volksbuehne-berlin.de/produktionen/raw-voice-lab/20261030-1200/'
 class Direct:
  aliases={};reason='fixture'
  def fetch(self,target):return url,html
 e=dict(title='Raw Voice Lab',date='2026-10-30',time='13:00',venue='Grüner Salon',url=url,source_url='https://www.volksbuehne-berlin.de/')
 assert sample_one(e,Direct())['matched'] is True
 assert sample_one(dict(e,venue='mit Sarmen Almond Workshop'),Direct())['matched'] is False
 assert sample_one(dict(e,date='2026-10-31'),Direct())['matched'] is False


def test_museum_status_badge_is_not_title_and_negative_listing_evidence_survives():
 from scripts.event_utils import validate_events
 from datetime import date
 rows=scrape_document((FIXTURES/'berlin_museum_listing_2026-10-29.html').read_text(),'https://www.berlin.museum/programm','fixture')
 e=next(e for e in rows if 'Niewiedervereinigung' in e['title'])
 assert e['title']=='„Niewiedervereinigung“' and 'Ausverkauft' in e['description']
 normalized,_=validate_events([e],e['source_url'],date(2026,10,29),date(2026,11,5))
 assert normalized[0]['ticket_status']=='sold_out'
 html=(FIXTURES/'museum_niewiedervereinigung_detail_2026-10-30.html').read_text()
 class Direct:
  aliases={};reason='fixture'
  def fetch(self,target):return e['url'],html
 assert sample_one(e,Direct())['matched'] is True


def test_destination_sold_out_excludes_only_its_exact_performance():
 from scripts.qualify_restored_branch import publication_observations
 event=dict(date='2026-10-30',time='19:00',url=RAUS,ticket_status='unknown')
 sample=dict(event,matched=True,ticket_status='sold_out')
 assert publication_observations(event,[sample])[1] is True
 assert publication_observations(dict(event,date='2026-10-31'),[sample])[1] is False
 assert publication_observations(event,[dict(sample,matched=False)])[1] is False


def test_supplied_raus_url_and_date_window_are_preserved_without_secret_parameters():
 from scripts.raus_selective import listing_url
 from scripts.qualify_restored_branch import date_window,sanitized
 from urllib.parse import urlsplit,parse_qs
 first,last=date_window(NOW,'2026-11-01','2026-11-07')
 url=listing_url(first,last)
 q=parse_qs(urlsplit(url).query)
 assert q=={'geospatial_query_type':['CITY'],'lat':['52.5'],'lng':['13.405'],'city':['berlin'],'active_city_name':['Berlin'],'start_date':['2026-11-01'],'end_date':['2026-11-07']}
 output=sanitized(url+'&auth_token=private')
 assert 'private' not in output and parse_qs(urlsplit(output).query)==q


def test_date_window_uses_berlin_day_and_rejects_partial_reversed_or_unbounded_ranges():
 from scripts.qualify_restored_branch import date_window
 import pytest
 first,last=date_window(datetime(2026,10,29,23,30,tzinfo=timezone.utc))
 assert first.isoformat()=='2026-10-30'
 for start,end in [('2026-11-01',''),('2026-11-07','2026-11-01'),('2026-10-28','2026-11-01'),('2026-11-01','2026-12-01')]:
  with pytest.raises(ValueError):date_window(NOW,start,end)


def test_explicit_window_drives_each_daily_schedule_url(monkeypatch):
 import scripts.generic_event_scraper as generic
 from datetime import date
 from urllib.parse import urlsplit,parse_qs
 calls=[]
 monkeypatch.setattr(generic,'scrape',lambda url:calls.append(url) or [])
 generic.scrape_date_horizon('https://www.berlin-buehnen.de/de/spielplan',6,start_day=date(2026,11,1))
 assert [parse_qs(urlsplit(u).query)['date'][0] for u in calls]==[f'2026-11-{i:02}' for i in range(1,8)]


def test_camoufox_never_launches_for_denied_or_unknown_robots_or_other_sources():
 import time
 from scripts.raus_browser import render_listing
 from scripts.raus_selective import listing_url
 from datetime import date
 url=listing_url(date(2026,11,1),date(2026,11,7))
 def forbidden(**kwargs):raise AssertionError('Browser launched despite policy')
 for h in (HTTP(allowed=False),HTTP()):
  if h.robots['https://rausgegangen.de'].can_fetch('*',url):h.robots={}
  doc,d=render_listing(url,h,time.monotonic()+600,launch=forbidden)
  assert doc is None and d['navigations']==0 and d['outcome']=='robots_denied_or_unknown'
 doc,d=render_listing('https://other.example/en/berlin/eventsbydate/',HTTP(),time.monotonic()+600,launch=forbidden)
 assert doc is None and d['outcome']=='source_not_allowlisted'


def test_camoufox_permitted_navigation_is_one_bounded_listing_without_interaction(monkeypatch):
 import time
 from scripts.raus_browser import render_listing
 from scripts.raus_selective import listing_url
 from datetime import date
 url=listing_url(date(2026,11,1),date(2026,11,7));seen={}
 class Page:
  def route(self,pattern,handler):seen['route']=pattern
  def goto(self,target,**kwargs):seen['goto']=(target,kwargs);return type('Response',(),{'status':200})()
  def content(self):return '<h1>Public programme</h1>'
  def wait_for_timeout(self,n):assert n==1500
  @property
  def url(self):return url
 class Context:
  def new_page(self):return Page()
 class Browser:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def new_context(self,**kwargs):assert kwargs['ignore_https_errors'] is False;return Context()
 def launch(**kwargs):
  assert kwargs['headless'] and kwargs['humanize'] is False and kwargs['geoip'] is False
  return Browser()
 doc,d=render_listing(url,HTTP(),time.monotonic()+600,launch=launch)
 assert doc[0]==url and d['navigations']==1 and seen['goto'][1]['timeout']==45000
