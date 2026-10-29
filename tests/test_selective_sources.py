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
