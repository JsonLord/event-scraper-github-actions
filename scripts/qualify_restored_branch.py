#!/usr/bin/env python3
"""Read-only qualification with optional Raus-only, bounded provider discovery.

Direct HTTP remains the default. The explicitly enabled Raus adapter alone may
use free Fetch/Search. No generic provider/browser fallback. Outputs outside git.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime,timedelta,timezone
import argparse,hashlib,ipaddress,json,logging,os,re,shutil,socket,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit,urljoin,urlunsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo
import requests,yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import generic_event_scraper as scraper
from scripts.event_utils import validate_events,dedupe_events,clean_url
from scripts.ticket_evidence import folded,enrich_evidence

ROOT=Path(__file__).resolve().parents[1]
AGENT='BerlinEventEvidence/1.0'
MIGRATIONS={'www.stadtmuseum.de':'www.berlin.museum','www.volksbuehne.berlin':'www.volksbuehne-berlin.de'}


def origin(url):
 p=urlsplit(url);return p.scheme+'://'+p.netloc


def public(url):
 try:
  p=urlsplit(url)
  if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):return False
  if any(word in p.query.lower() for word in ('token=','password=','secret=','session=','auth=')):return False
  addresses=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
  return bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses)
 except (ValueError,OSError):return False


def sanitized(value):
 if isinstance(value,dict):return {k:sanitized(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [sanitized(v) for v in value]
 if not isinstance(value,str):return value
 key=os.environ.get('TINYFISH_API_KEY','')
 if key:value=value.replace(key,'[REDACTED]')
 def strip(m):
  try:
   p=urlsplit(m.group());return urlunsplit((p.scheme,p.hostname or '',p.path,'',''))
  except ValueError:return '[invalid URL]'
 return re.sub(r'https?://[^\s<>"\']+',strip,value)


class HTTP:
 def __init__(self,limit,deadline,byte_limit=2_000_000):
  self.limit=limit;self.deadline=deadline;self.byte_limit=byte_limit
  self.requests=0;self.bytes=0;self.calls=[];self.robots={};self.aliases={};self.blocked=set();self.documents={};self.reason='not_attempted'
  self.robot_evidence={}
  self.session=requests.Session()
 def get(self,url,robots=False):
  while public(url):
   if self.requests>=self.limit:self.reason='http_budget';return None
   if time.monotonic()+20>self.deadline:self.reason='deadline';return None
   if urlsplit(url).netloc in self.blocked:self.reason='host_blocked_cached';return None
   self.requests+=1;start=time.monotonic();call=dict(url=url,operation='robots' if robots else 'page',http_status=None)
   try:
    self.session.cookies.clear()
    with self.session.get(url,headers={'User-Agent':AGENT,'Accept':'text/html,text/plain,application/json'},timeout=(8,12),allow_redirects=False,stream=True) as r:
     call['http_status']=r.status_code
     if r.status_code in (403,429):self.blocked.add(urlsplit(url).netloc);self.reason='http_'+str(r.status_code);return None
     if r.status_code in (301,302,303,307,308):
      target=urljoin(url,r.headers.get('Location',''));a,b=urlsplit(url),urlsplit(target)
      if origin(target)!=origin(url):
       alias=(a.hostname or '').removeprefix('www.')==(b.hostname or '').removeprefix('www.')
       migration=MIGRATIONS.get(a.hostname)==b.hostname
       if robots:
        if b.scheme!='https' or b.path!='/robots.txt' or b.query or b.fragment or not (alias or migration):self.reason='unapproved_robots_redirect';return None
       elif self.aliases.get(origin(url))!=origin(target):self.reason='unapproved_host_redirect';return None
      if not robots:
       parser=self.robots.get(origin(target))
       if parser is None or not parser.can_fetch(AGENT,target):self.reason='robots_redirect_denied';return None
      url=target;continue
     if r.status_code!=200:self.reason='http_'+str(r.status_code);return None
     mime=r.headers.get('Content-Type','').split(';')[0].lower()
     if mime not in ('text/html','text/plain','application/xhtml+xml','application/json','application/ld+json'):self.reason='unsupported_mime';return None
     parts=[];size=0
     for chunk in r.iter_content(16384):
      size+=len(chunk);self.bytes+=len(chunk)
      if size>1_500_000 or self.bytes>self.byte_limit:self.reason='byte_budget';return None
      if time.monotonic()+5>self.deadline:self.reason='deadline';return None
      parts.append(chunk)
     text=b''.join(parts).decode('utf-8',errors='replace')
     if scraper.is_bot_challenge(text):self.reason='challenge';return None
     if robots and re.search(r'<(?:html|!doctype)',text,re.I):self.reason='robots_not_policy_document';return None
     self.reason='ok';return url,text
   except (requests.RequestException,OSError):self.reason='network_error';return None
   finally:
    call.update(seconds=round(time.monotonic()-start,3),outcome=self.reason);self.calls.append(call)
  self.reason='unsafe_or_unresolved_url';return None
 def fetch(self,url):
  if url in self.documents:self.reason='same_run_cached';return self.documents[url]
  if not public(url):self.reason='unsafe_or_unresolved_url';return None
  base=origin(url)
  if base not in self.robots:
   policy=self.get(base+'/robots.txt',robots=True)
   parser=None
   if policy:
    if base=='https://rausgegangen.de':
     self.robot_evidence[base]=dict(url=policy[0],sha256=hashlib.sha256(policy[1].encode()).hexdigest(),policy_excerpt=policy[1][:4000],agent=AGENT)
    parser=RobotFileParser();parser.parse(policy[1].splitlines())
    if origin(policy[0])!=base:
     self.aliases[base]=origin(policy[0]);self.robots[origin(policy[0])]=parser
   elif self.reason=='http_404':parser=RobotFileParser();parser.parse([])
   self.robots[base]=parser
  parser=self.robots[base]
  if parser is None:self.reason='robots_policy_unknown';return None
  if not parser.can_fetch(AGENT,url):self.reason='robots_denied';return None
  page=self.get(url)
  if page:self.documents[url]=page;self.documents[page[0]]=page
  return page
 def plain(self,url,**kwargs):
  result=self.fetch(url);return result[1] if result else None


def listing_worker(task):
 sources,stamp,deadline=task;now=datetime.fromisoformat(stamp);day=now.astimezone(ZoneInfo('Europe/Berlin')).date();end=day+timedelta(days=7)
 capacity=20 if any(s.get('date_horizon') for s in sources) else min(4*len(sources),16)
 http=HTTP(capacity,deadline,2_000_000*len(sources));reports=[]
 scraper.fetch_plain=http.plain
 scraper.fetch_jina_html=lambda *a,**k:None
 scraper.render_with_cloakbrowser=lambda *a,**k:None
 for source in sources:
  start=http.requests;http.limit=min(capacity,start+(20 if source.get('date_horizon') else 4));began=time.monotonic()
  url=source['url'].replace('__START_DATE__',day.isoformat()).replace('__END_DATE__',end.isoformat())
  try:
   raw=scraper.scrape_date_horizon(url,7) if source.get('date_horizon') else scraper.scrape(url)
   keep,_=validate_events(raw,url,day,end,max_price=float('inf'));keep=dedupe_events(keep)
   cheap,_=validate_events(raw,url,day,end,max_price=20);cheap=dedupe_events(cheap)
   month,_=validate_events(raw,url,day,day+timedelta(days=30),max_price=float('inf'));month=dedupe_events(month)
   page=next((v for k,v in http.documents.items() if k==url or (source.get('date_horizon') and k.startswith(url+'?'))),None)
   report=dict(name=source['name'],url=url,listing_received=bool(page),final_url=page[0] if page else None,
               raw_candidates=len(raw),window_occurrences=len(keep),under_twenty=len(cheap),thirty_day_occurrences=len(month),
               missing_detail_links=sum(not e.get('has_detail_link') for e in keep),missing_venues=sum(not e.get('venue') for e in keep),
               unknown_prices=sum(e.get('price') is None for e in keep),unknown_inventory=sum(e.get('ticket_status')=='unknown' for e in keep),
               with_times=sum(bool(e.get('time')) for e in keep),events=keep,detail_samples=[])
   report['outcome']='extracted_candidates' if keep else 'outside_seven_day_window' if raw else 'no_dated_event_evidence' if page else http.reason
  except Exception as exc:
   report=dict(name=source['name'],url=url,listing_received=False,raw_candidates=0,window_occurrences=0,under_twenty=0,thirty_day_occurrences=0,events=[],detail_samples=[],outcome='extractor_exception_'+type(exc).__name__)
  report.update(http_attempts=http.requests-start,seconds=round(time.monotonic()-began,3));reports.append(report)
 return reports,dict(robots=http.robots,robot_evidence=http.robot_evidence,aliases=http.aliases,blocked=http.blocked,documents=http.documents,calls=http.calls,requests=http.requests,bytes=http.bytes,capacity=capacity)


def canonical(url,http):
 p=urlsplit(url);base=http.aliases.get(origin(url),origin(url));q=urlsplit(base)
 return urlunsplit((q.scheme,q.netloc,p.path.rstrip('/'),p.query,''))


def sample_one(event,http):
 url=event['url'];doc=http.fetch(url)
 result={k:event.get(k) for k in ('title','date','time','venue','url')};result.update(matched=False,outcome=http.reason)
 if not doc:return result
 final,html=doc;result.update(final_url=final,http_success=True,outcome='no_matching_structured_event')
 from scripts.raus_selective import detail_candidates
 for candidate in detail_candidates(html,final):
  if not event.get('time') or (event.get('date'),event.get('time'),folded(event.get('title','')))!=(candidate.get('date'),candidate.get('time'),folded(candidate.get('title',''))):continue
  if canonical(candidate.get('url',''),http)!=canonical(final,http):continue
  a,b=event.get('venue'),candidate.get('venue')
  if a and b and folded(a)!=folded(b):continue
  if not (a and b) and (canonical(url,http)!=canonical(final,http) or urlsplit(canonical(event.get('source_url',''),http)).hostname!=urlsplit(final).hostname):continue
  item=enrich_evidence(candidate)
  result.update(matched=True,outcome='exact_structured_occurrence' if candidate.get('_representation','jsonld')=='jsonld' else 'exact_bound_occurrence',match_basis='title_date_time_venue' if a and b else 'official_canonical_title_date_time',
                representation=candidate.get('_representation','jsonld'),
                regular_offers=[o for o in item.get('offers',[]) if o.get('kind')=='regular'],student_offers=[o for o in item.get('offers',[]) if o.get('kind')=='student'],
                ticket_status=item.get('ticket_status','unknown'),event_status=item.get('event_status','unknown'),venue=candidate.get('venue') or a)
  break
 return result


def publication_observations(event,samples):
 matches=[s for s in samples if s.get('matched') and (s.get('date'),s.get('time'),s.get('url'))==(event.get('date'),event.get('time'),event.get('url'))]
 negative=lambda e:e.get('ticket_status')=='sold_out' or e.get('event_status') in ('cancelled','postponed')
 return matches,negative(event) or any(negative(s) for s in matches)


def fingerprints():
 return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data').glob('*.json')}


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--raus-tinyfish',action='store_true');a=parser.parse_args()
 output=Path(a.output).resolve();assert output!=ROOT and ROOT not in output.parents
 output.mkdir(parents=True,exist_ok=False);before=fingerprints();start=time.monotonic();now=datetime.now(timezone.utc);deadline=start+600
 catalog=yaml.safe_load((ROOT/'.github/workflows/weekly-event-scraper.yml').read_text())['jobs']['scrape']['strategy']['matrix']['include']
 groups=defaultdict(list)
 for source in catalog:groups[urlsplit(source['url']).netloc].append(source)
 results=[];states=[]
 with ProcessPoolExecutor(max_workers=2) as pool:
  for reports,state in pool.map(listing_worker,[(v,now.isoformat(),deadline-90) for v in groups.values()]):results.extend(reports);states.append(state)
 order={s['name']:i for i,s in enumerate(catalog)};results.sort(key=lambda s:order[s['name']])
 http=HTTP(40,deadline,25_000_000)
 for state in states:
  http.robots.update(state['robots']);http.aliases.update(state['aliases']);http.blocked.update(state['blocked']);http.documents.update(state['documents'])
  http.robot_evidence.update(state['robot_evidence'])
 provider_diagnostics=dict(enabled=False,search_calls=0,fetch_urls=0,provider_calls=[])
 if a.raus_tinyfish:
  from scripts.raus_selective import discover
  raus_http=HTTP(8,deadline,4_500_000)
  raus_http.robots.update(http.robots);raus_http.blocked.update(http.blocked)
  raus_http.documents.update(http.documents)
  discovered,provider_diagnostics=discover(now,raus_http,deadline)
  http.documents.update(raus_http.documents);http.robots.update(raus_http.robots);http.blocked.update(raus_http.blocked)
  report=next(r for r in results if r['name']=='rausgegangen_de')
  report['listing_outcome']=report['outcome']
  report['events']=dedupe_events(report['events']+discovered)
  report.update(window_occurrences=len(report['events']),under_twenty=sum(e.get('price') is None or e['price']<=20 for e in report['events']),
                missing_detail_links=sum(not e.get('has_detail_link') for e in report['events']),missing_venues=sum(not e.get('venue') for e in report['events']))
  if discovered:report['outcome']='permitted_destination_discovery'
  provider_diagnostics['http_calls']=raus_http.calls
  (output/'raus-tinyfish-diagnostics.json').write_text(json.dumps(sanitized(provider_diagnostics),ensure_ascii=False,indent=2)+'\n')
 local=now.astimezone(ZoneInfo('Europe/Berlin'))
 def eligible(e):
  return e.get('has_detail_link') and e.get('time') and (e['date']>local.date().isoformat() or (e['date']==local.date().isoformat() and e['time']>local.strftime('%H:%M'))) and not re.search(r'/(?:login|checkout|cart|account|webticket)(?:/|$)',urlsplit(e['url']).path,re.I)
 queues={r['name']:sorted([e for e in r['events'] if eligible(e)],key=lambda e:(e['date'],e.get('time',''),e['title'])) for r in results}
 focus=[r for r in results if r['name'] in ('rausgegangen_de','stadtmuseum','volksbuehne')]
 others=[r for r in results if r not in focus]
 for group in (focus,others):
  for round_number in range(2):
   for report in group:
    queue=queues[report['name']]
    if not queue:continue
    if http.requests>=40 or time.monotonic()+20>deadline:break
    report['detail_samples'].append(sample_one(queue.pop(0),http))
 for report in results:
  report['exact_sample_matches']=sum(s['matched'] for s in report['detail_samples']);report['sampled_occurrences']=len(report['detail_samples'])
  report['conclusion']='supported_sample' if report['exact_sample_matches'] else 'candidates_only' if report['window_occurrences'] else report['outcome']
 assert fingerprints()==before,'Production data changed'
 summary=dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),scraper_baseline='70787edd3d4b99124e38a179b7737f27c60ba229',
              generated_at=now.isoformat(),window_end=(local.date()+timedelta(days=7)).isoformat(),environment='GitHub Actions' if os.getenv('GITHUB_ACTIONS') else 'cloud executor',
              sources=results,listing_http_attempts=sum(s['requests'] for s in states),listing_http_limit=sum(s['capacity'] for s in states),detail_http_attempts=http.requests,detail_http_limit=40,
              response_bytes=sum(s['bytes'] for s in states)+http.bytes,seconds=round(time.monotonic()-start,3),tinyfish_calls=len(provider_diagnostics['provider_calls']),tinyfish=provider_diagnostics,robots_evidence=http.robot_evidence,other_provider_calls=0,browser_calls=0,production_data_unchanged=True,
              caveats=['Direct HTTP for all sources; optional free Fetch/Search allowlisted to Raus destinations only.','Source-adapter repair and Raus detail matching do not qualify the complete corpus.','Counts are date-window candidates, not guaranteed upcoming verified events.','At most two occurrence samples per source; exact matches never imply all source records are verified.','Unknown prices/inventory remain unsupported; no Community/newsletter eligibility is asserted.'],
              calls=[c for s in states for c in s['calls']]+http.calls)
 (output/'results.json').write_text(json.dumps(sanitized(summary),ensure_ascii=False,indent=2)+'\n')
 for r in results:(output/(r['name']+'.json')).write_text(json.dumps(sanitized(dict(source=r['url'],events=r['events'],samples=r['detail_samples'])),ensure_ascii=False,indent=2)+'\n')
 lines=['# Restored branch: website conclusiveness','',f"Commit: `{summary['commit']}`; baseline scraper: `70787ed`.",f"Run time: {now.astimezone(ZoneInfo('Europe/Berlin')).isoformat()}; seven-day date window ends {summary['window_end']}.",'',
        f"Direct HTTP with robots checks. TinyFish is {'enabled for Rausgegangen only' if a.raus_tinyfish else 'disabled'}; {provider_diagnostics['search_calls']}/2 Search calls and {provider_diagnostics['fetch_urls']}/3 Fetch URLs. No Jina, browser or production-data writes. Publication is a separate explicitly requested job. Counts include all prices; ≤€20 is the legacy price filter. Samples require bound occurrence identity, never Search snippets.",'',
        '| Source | Window rows | ≤€20 | Links missing | Venues missing | Exact samples | Conclusion |','|---|---:|---:|---:|---:|---:|---|']
 for r in results:lines.append(f"| {r['name']} | {r['window_occurrences']} | {r['under_twenty']} | {r.get('missing_detail_links',0)} | {r.get('missing_venues',0)} | {r['exact_sample_matches']}/{r['sampled_occurrences']} | {r['conclusion']} |")
 lines+=['',f"HTTP: {summary['listing_http_attempts']}/{summary['listing_http_limit']} listing attempts + {http.requests}/40 detail attempts. Duration {summary['seconds']} seconds.",'','## Limitations','']+['- '+c for c in summary['caveats']]
 (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
 # Materialize the actual restored scoring/frontend path, with explicit
 # qualification labels. Never promote a listing-only zero as validated free.
 from scripts.score_events import score_and_filter_events
 from copy import deepcopy
 rows=[];unsupported_free=0
 for report in results:
  for original in report['events']:
   event=deepcopy(original)
   matches,negative=publication_observations(event,report['detail_samples'])
   # Neither listing warnings nor exact destination warnings may be erased.
   if negative:
    continue
   regular=[o for s in matches for o in s.get('regular_offers',[]) if o.get('amount_eur') is not None and folded(o.get('eligibility','')) in ('','standard','normalpreis','regular','adult','erwachsene')]
   proven_free=bool(regular) and all(o.get('amount_eur')==0 and o.get('price_max',0)==0 for o in regular)
   event['_qualification_free_proven']=proven_free
   if event.get('price')==0 and not proven_free:
    unsupported_free+=1
    event.update(price=None,price_min=None,price_max=None,price_status='unknown',price_label='Check admission on site',free_admission_confirmed=False,offers=[])
   event.update(ticket_status='unknown')
   rows.append(event)
 published=score_and_filter_events(rows,20,today=local.date())
 for event in published:
  if event.get('price')==0 and not event.pop('_qualification_free_proven',False):
   event.update(price=None,price_min=None,price_max=None,free_admission_confirmed=False,price_status='unknown',offers=[])
  event.pop('_qualification_free_proven',None)
  event['price_label']='Free · matched structured offer' if event.get('price')==0 else f"€{event['price']:g} · listing estimate" if event.get('price') is not None else 'Check admission on site'
  event['ticket_status']='unknown'
 from scripts.score_events import day_sort_key
 published.sort(key=day_sort_key)
 site=output/'site';site.mkdir()
 payload=dict(count=len(published),generated_at=now.isoformat(),events=published,qualification_only=True,source_commit=summary['commit'])
 (site/'events_scored.json').write_text(json.dumps(sanitized(payload),ensure_ascii=False,indent=2)+'\n')
 html=(ROOT/'web/index.html').read_text()
 banner='<aside style="padding:12px 24px;background:#fff3cd;color:#332701;font-size:14px">Restored scraper review · Prices marked “listing estimate” are unverified. Check official event pages before attending. <a href="qualification-report.html">Website evidence report</a></aside>'
 (site/'index.html').write_text(html.replace('<body>','<body>'+banner,1));(site/'.nojekyll').touch()
 import html as html_module
 (site/'qualification-report.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Website evidence report</title><pre style="white-space:pre-wrap;font:14px/1.5 system-ui">'+html_module.escape('\n'.join(lines))+f'\n\nPublished preview rows: {len(published)}; unsupported free claims suppressed: {unsupported_free}.</pre>')
 checksums={str(p.relative_to(site)):hashlib.sha256(p.read_bytes()).hexdigest() for p in site.rglob('*') if p.is_file()}
 (output/'site-manifest.json').write_text(json.dumps(dict(commit=summary['commit'],generated_at=now.isoformat(),files=checksums,count=len(published),unsupported_free_suppressed=unsupported_free),indent=2)+'\n')
 assert fingerprints()==before,'Production data changed while building site'
 print('\n'.join(lines))

if __name__=='__main__':main()
