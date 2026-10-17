#!/usr/bin/env python3
"""Manual staging harness around production discovery, verifier and builder.

No production writes, publication or workflow dispatch. One shared network budget
covers discovery and verification. Only sanitized JSON/static diagnostics persist.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.audit_events import gate
from scripts.build_page_dataset import build
from scripts.event_utils import validate_events, dedupe_events
from scripts.generic_event_scraper import scrape_document, build_date_url
from scripts.ticket_evidence import occurrence_id
from scripts.tinyfish_client import TinyFishClient
from scripts.verify_event_details import BoundedHTTP, DEFAULT_POLICY, run, observation, utc

SOURCES={
    'berlin_buehnen':'https://www.berlin-buehnen.de/de/spielplan',
    'ufafabrik':'https://ufafabrik.de/spielplan.html',
    'rausgegangen':'https://rausgegangen.de/en/berlin/eventsbydate/',
}
PRODUCTION_FILES=('data/events.json','data/events_scored.json','data/event_verifications.json')


def fingerprints(root):
    return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in PRODUCTION_FILES}


def safe_artifact(value):
    """Drop all URL queries/fragments and the injected key, including nested text."""
    if isinstance(value,dict): return {k:safe_artifact(v) for k,v in value.items()}
    if isinstance(value,list): return [safe_artifact(v) for v in value]
    if not isinstance(value,str): return value
    key=os.environ.get('TINYFISH_API_KEY','')
    if key: value=value.replace(key,'[REDACTED]')
    def strip(match):
        p=urlsplit(match.group())
        return urlunsplit((p.scheme,p.hostname or '',p.path,'',''))
    return re.sub(r'https?://[^\s<>"\']+',strip,value)


def write_json(path,value):
    path.write_text(json.dumps(safe_artifact(value),ensure_ascii=False,indent=2)+'\n')


class RecordingHTTP(BoundedHTTP):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.documents={}
    def fetch(self,url):
        if url in self.documents:
            self.reason='cached_same_run'; self.permitted=True;return self.documents[url]
        provider=getattr(self,'provider',None)
        if provider and url in provider.documents:
            self.reason='cached_same_run_tinyfish';self.permitted=True;return provider.documents[url]
        result=super().fetch(url)
        if result: self.documents[url]=result
        return result


class RecordingTinyFish(TinyFishClient):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.documents={}
    def fetch(self,urls):
        result=super().fetch(urls)
        for url,r in result.items():
            self.documents[url]=(r['final_url'],r['html'])
            self.documents[r['final_url']]=(r['final_url'],r['html'])
        return result


def choose_sample(events,now,per_source=3):
    """Deterministic source coverage, status/discount variants, then date/time."""
    today=now.astimezone(ZoneInfo('Europe/Berlin')).date().isoformat()
    clock=now.astimezone(ZoneInfo('Europe/Berlin')).strftime('%H:%M')
    upcoming=[e for e in events if e['date']>today or (e['date']==today and (not e.get('time') or e['time']>=clock))]
    def priority(e):
        status=e.get('event_status') in ('cancelled','postponed') or e.get('ticket_status')=='sold_out'
        variation=e.get('student_discount_status')=='explicit' or e.get('price_status')=='range'
        affordable=e.get('price') is None or e['price']<=20
        return (not status,not variation,not affordable,e['date'],e.get('time',''),e['title'])
    return sorted(upcoming,key=priority)[:per_source]


def discover(now,http,provider,phase='full'):
    today=now.astimezone(ZoneInfo('Europe/Berlin')).date();end=today+timedelta(days=7)
    sample=[];sources={}
    selected_sources=SOURCES if phase in ('full','r13') else {'rausgegangen':SOURCES['rausgegangen']}
    for name,base in selected_sources.items():
        urls=[base]
        if phase=='raus-search' or (phase=='r13' and name=='rausgegangen'): urls=[]
        if name=='berlin_buehnen': urls=[build_date_url(base,today)] if phase=='r13' else [build_date_url(base,today),build_date_url(base,end)]
        if name=='rausgegangen' and phase not in ('raus-search','r13'):
            urls=[base+'?geospatial_query_type=CITY&lat=52.5&lng=13.405&city=berlin&active_city_name=Berlin&start_date='+today.isoformat()+'&end_date='+end.isoformat()]
        found=[];attempts=[];document=None
        for url in urls:
            document=http.fetch(url);method='direct_http'
            if not document and http.permitted:
                result=provider.fetch([url]).get(url)
                if result and http.bytes+len(result['html'].encode())<=http.policy['max_total_response_bytes']:
                    document=(result['final_url'],result['html']);method='tinyfish_fetch'
                    http.bytes+=len(document[1].encode())
            attempts.append({'transport':method,'outcome':http.reason if not document else 'received'})
            if not document: continue
            raw=scrape_document(document[1],url,'R1.2 '+name)
            cleaned,_=validate_events(raw,url,today,end,max_price=float('inf'))
            for e in cleaned: e['observed_at']=now.isoformat()
            found.extend(cleaned)
        if phase=='raus-search' or (phase=='r13' and name=='rausgegangen'):
            # Search only discovers candidate URLs. Event facts must come from
            # the fetched destination and the production extraction functions.
            candidates=[]
            for query in [f'site:rausgegangen.de/events/ Berlin "{today.strftime("%d.%m.%Y")}"',
                          f'site:rausgegangen.de/en/events/ Berlin "{today.strftime("%d.%m.%Y")}"']:
                candidates.extend(provider.search(query))
            candidates=list(dict.fromkeys(u for u in candidates if (urlsplit(u).hostname or '').removeprefix('www.')=='rausgegangen.de' and '/events/' in urlsplit(u).path and len(urlsplit(u).path.strip('/').split('/'))>=2))
            for candidate in candidates[:3 if phase=='r13' else 1]:
                document=http.fetch(candidate);method='direct_http'
                if not document and http.permitted:
                    result=provider.fetch([candidate]).get(candidate)
                    if result and http.bytes+len(result['html'].encode())<=http.policy['max_total_response_bytes']:
                        document=(result['final_url'],result['html']);method='tinyfish_fetch';http.bytes+=len(document[1].encode())
                attempts.append({'transport':method,'outcome':http.reason if not document else 'received','search_candidates':len(candidates)})
                if document:
                    raw=scrape_document(document[1],document[0],'R1.2 Raus Search candidate')
                    raw=[e for e in raw if re.search(r'\bBerlin\b',str(e.get('description',''))+' '+str(e.get('venue','')),re.I)]
                    cleaned,_=validate_events(raw,base,today,end,max_price=float('inf'))
                    for e in cleaned:
                        e['observed_at']=now.isoformat()
                        # Fetch destination is the proven transport identity.
                        e['url']=document[0]
                    found.extend(cleaned)
                    attempts[-1]['candidate_url']=candidate
                    attempts[-1]['destination_url']=document[0]
                    attempts[-1]['extracted_occurrences']=len(cleaned)
                    if not cleaned:
                        from bs4 import BeautifulSoup
                        page=BeautifulSoup(document[1],'lxml')
                        attempts[-1]['rejected_structure']=page.get_text(' | ',strip=True)[:2200]
        if document and not found:
            from bs4 import BeautifulSoup
            page=BeautifulSoup(document[1],'lxml')
            attempts[-1]['empty_extraction_structure']={'headings':[h.get_text(' ',strip=True)[:150] for h in page.select('h1,h2,h3')[:12]],'text_excerpt':page.get_text(' ',strip=True)[:1600],'event_links':sum('/events/' in (x.get('href') or '') for x in page.select('a[href]'))}
        found=dedupe_events(found)
        chosen=choose_sample(found,now,per_source=(3 if name=='rausgegangen' else 1) if phase=='r13' else (3 if phase=='full' else 1))
        sources[name]={'listing_results':attempts,'discovered_upcoming_window':len(found),'sample_events':len(chosen),
                       'missing_links':sum(not e.get('has_detail_link') for e in chosen),'missing_venues':sum(not e.get('venue') for e in chosen)}
        sample.extend(chosen)
    return sample,sources


def integration(sample,now,policy,http,provider,overlay_path=None):
    initial={'version':1,'events':{}}
    overlay,usage=run(sample,initial,now,policy,http,provider)
    frozen=deepcopy(overlay)
    persisted=overlay
    if overlay_path is not None:
        overlay_path.write_text(json.dumps(overlay,ensure_ascii=False))
        persisted=json.loads(overlay_path.read_text())
        assert persisted==frozen,'Overlay storage round-trip changed observations'
    counters=(http.requests,http.bytes,provider.fetch_urls,provider.search_queries)
    second,second_usage=run(sample,persisted,now+timedelta(minutes=5),policy,http,provider)
    preserved=(second==frozen and overlay==frozen and counters==(http.requests,http.bytes,provider.fetch_urls,provider.search_queries))
    if not preserved: raise AssertionError('Fresh second execution mutated observations or made network calls')
    payload={'generated_at':now.isoformat(),'events':sample}
    before=deepcopy(payload)
    materialized=build(payload,overlay,now)
    expired=build(payload,overlay,now+timedelta(days=8,hours=1))
    gate(materialized['events']);gate(expired['events'])
    assert payload==before and overlay==frozen,'Materialization mutated canonical input/overlay'
    assert all(e['ticket_status']=='unknown' and not e['free_admission_confirmed'] and e['detail_link_status']!='verified' for e in expired['events'])
    details=[];fallback=[];multi=[]
    for e in sample:
        eid=occurrence_id(e);entry=overlay['events'].get(eid,{})
        fields=entry.get('fields',{})
        details.append({'event_id':eid,'title':e['title'],'date':e['date'],'time':e.get('time'),'source_url':e['source_url'],'url':e['url'],'venue':e.get('venue',''),
                        'matched':entry.get('outcome')=='matched','outcome':entry.get('outcome','not_selected'),
                        'confirmed':{k:v['values'] for k,v in fields.items()},
                        'match_basis':fields.get('link',{}).get('match_basis')})
        document=http.documents.get(e['url']) or provider.documents.get(e['url'])
        if document:
            result=observation(dict(e,venue=''),document[1],document[0],now.isoformat())
            fallback.append({'event_id':eid,'counterfactual_missing_venue':True,'matched':bool(result),
                             'match_basis':(result or {}).get('link',{}).get('match_basis')})
            from bs4 import BeautifulSoup
            page=BeautifulSoup(document[1],'lxml')
            section=next((x for x in page.select('hylo-accordion-item') if x.select_one('hylo-accordion-item-header') and x.select_one('hylo-accordion-item-header').get_text(strip=True)=='Termine'),None)
            if section and len(section.select('time'))>1:
                multi.append({'event_id':eid,'performance_rows':len(section.select('time')),
                              'contains_cancellation_marker':'Abgesagt' in section.get_text(),
                              'selected_event_status':fields.get('event_status',{}).get('values',{}).get('event_status','unknown')})
    return overlay,second,materialized,expired,{'first_usage':usage,'second_usage':second_usage,'fresh_second_run_preserved_state':preserved,
                'ttl_expiration_passed':True,'disk_overlay_roundtrip':overlay_path is not None,'input_immutability_passed':True,'details':details,'missing_venue_replays':fallback,'multi_performance_pages':multi}


def coverage_metrics(sources, details, published):
    """Discovery and successful HTTP are never verified source coverage."""
    from scripts.event_matching import host
    result={}
    for name,base in SOURCES.items():
        rows=[d for d in details if host(d.get('source_url',''))==host(base)]
        matched=sum(bool(d.get('matched')) for d in rows)
        attempts=sources.get(name,{}).get('listing_results',[])
        result[name]={
            'listing_discovery_success':any(a.get('outcome')=='received' and 'candidate_url' not in a and 'search_candidates' not in a for a in attempts) and sources.get(name,{}).get('discovered_upcoming_window',0)>0,
            'candidate_url_discovery_success':any(a.get('search_candidates',0)>0 for a in attempts) or bool(rows),
            'selected_occurrences':len(rows),'exact_occurrence_matches':matched,
            'exact_occurrence_match_rate':matched/len(rows) if rows else None,
            'verified_source_coverage':matched>0,
            'final_publishable_events':sum(host(e.get('source_url',''))==host(base) for e in published)}
    return {'sources':result,'verified_source_coverage_complete':all(r['verified_source_coverage'] for r in result.values())}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--now');p.add_argument('--phase',choices=('full','raus-completion','raus-search','r13'),default='full');a=p.parse_args()
    root=Path(__file__).resolve().parents[1];output=Path(a.output).resolve()
    if output==root or root in output.parents: raise ValueError('Staging outputs must be outside the checkout')
    output.mkdir(parents=True,exist_ok=True)
    original=fingerprints(root);now=utc(a.now or datetime.now(timezone.utc));started=time.monotonic()
    policy=dict(DEFAULT_POLICY,max_events_per_run=9,max_tinyfish_fetch_urls_per_run=6,max_tinyfish_search_queries_per_run=4,max_run_seconds=600)
    if a.phase=='raus-completion':
        policy.update(max_events_per_run=1,max_tinyfish_fetch_urls_per_run=2,max_tinyfish_search_queries_per_run=4,max_http_requests_per_run=4,max_requests_per_host=4)
    if a.phase=='raus-search':
        policy.update(max_events_per_run=1,max_tinyfish_fetch_urls_per_run=1,max_tinyfish_search_queries_per_run=2,max_http_requests_per_run=2,max_requests_per_host=2)
    deadline=time.monotonic()+600
    http=RecordingHTTP(policy,deadline=deadline)
    provider=RecordingTinyFish(max_fetch=policy['max_tinyfish_fetch_urls_per_run'],max_search=policy['max_tinyfish_search_queries_per_run'],deadline=deadline)
    http.provider=provider
    sample,sources=discover(now,http,provider,a.phase)
    data={'generated_at':now.isoformat(),'events':sample}
    with TemporaryDirectory(prefix='r12-state-',dir=output.parent) as work:
        overlay,second,site,expired,checks=integration(sample,now,policy,http,provider,Path(work)/'overlay.json')
    network_elapsed=round(time.monotonic()-started,3)
    write_json(output/'sample.json',data);write_json(output/'overlay-first.json',overlay);write_json(output/'overlay-second.json',second)
    write_json(output/'expired-dataset.json',expired)
    subprocess.run([sys.executable,str(root/'scripts/build_page_dataset.py'),'--input',str(output/'sample.json'),'--overlay',str(output/'overlay-first.json'),'--output-dir',str(output/'site'),'--now',now.isoformat()],check=True)
    if site['count']:
        subprocess.run([sys.executable,str(root/'scripts/smoke_pages.py'),'--site',str(output/'site'),'--output',str(output/'smoke'),'--now',now.isoformat()],check=True)
        smoke=json.loads((output/'smoke/report.json').read_text())
    else:
        smoke={'status':'not_run_empty_materialization'}
    assert fingerprints(root)==original,'Production data changed'
    assert http.requests<=40 and all(n<=8 for n in http.hosts.values()) and http.bytes<=25_000_000
    assert provider.fetch_urls<=6 and provider.search_queries<=4
    matched=sum(x['matched'] for x in checks['details'])
    report={'version':'R1.2','phase':a.phase,'observed_at':now.isoformat(),'sources':sources,'total_discovered':sum(s['discovered_upcoming_window'] for s in sources.values()),
            'sample_events':len(sample),'matched_events':matched,'exact_match_rate':matched/len(sample) if sample else None,
            'materialized_events':site['count'],'source_coverage_complete':coverage_metrics(sources,checks['details'],site['events'])['verified_source_coverage_complete'],
            'coverage':coverage_metrics(sources,checks['details'],site['events']),
            'checks':checks,'http_attempts':http.requests,'http_bytes':http.bytes,'http_per_host':dict(http.hosts),'http_calls':http.diagnostics,
            'tinyfish_fetch_urls':provider.fetch_urls,'tinyfish_search_calls':provider.search_queries,'tinyfish_calls':provider.diagnostics,
            'network_wall_seconds':network_elapsed,'pipeline_wall_seconds':round(time.monotonic()-started,3),'budgets':policy,'production_files_unchanged':True,
            'frontend_smoke':smoke}
    write_json(output/'report.json',report)
    # Keep remote check evidence below GitHub's ten-notice-per-step cap.
    summary={k:v for k,v in report.items() if k not in ('checks','http_calls','budgets')}
    summary['integration']={k:v for k,v in checks.items() if k not in ('details','first_usage','second_usage')}
    summary['second_run_targets']=checks['second_usage']['targets']
    summary['events']=[]
    for item in checks['details']:
        confirmed=item['confirmed']
        summary['events'].append({k:v for k,v in item.items() if k!='confirmed'} | {
            'price':confirmed.get('price',{}),'student_discount_status':confirmed.get('discount',{}).get('student_discount_status','unknown'),
            'ticket_status':confirmed.get('status',{}).get('ticket_status','unknown'),
            'event_status':confirmed.get('event_status',{}).get('event_status','unknown')})
    write_json(output/'summary.json',summary)
    encoded=__import__('base64').b64encode(json.dumps(safe_artifact(summary),ensure_ascii=False).encode()).decode()
    chunks=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    assert len(chunks)<=10,'Summary exceeds GitHub check evidence capacity'
    for i,chunk in enumerate(chunks,1):
        print(f'::notice title=R12 report chunk {i}/{len(chunks)}::{chunk}')

if __name__=='__main__': main()
