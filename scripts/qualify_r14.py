#!/usr/bin/env python3
"""Manual-only fresh pilot candidate build. Never writes inside the checkout."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bs4 import BeautifulSoup
from scripts.qualify_r12 import RecordingHTTP, RecordingTinyFish, choose_sample, fingerprints, write_json
from scripts.generic_event_scraper import build_date_url, scrape_document
from scripts.event_utils import validate_events, dedupe_events
from scripts.ticket_evidence import occurrence_id, folded
from scripts.event_matching import host
from scripts.verify_event_details import DEFAULT_POLICY, run
from scripts.pilot_release import PROFILE, ROOT, candidate, seal, digest, validate


def document(url,http,provider):
    result=http.fetch(url)
    if not result and http.permitted:
        fetched=provider.fetch([url]).get(url)
        if fetched and http.bytes+len(fetched['html'].encode())<=http.policy['max_total_response_bytes']:
            result=(fetched['final_url'],fetched['html']);http.bytes+=len(result[1].encode())
    return result


def location(event,document,campus,now):
    if not document: return None
    page=BeautifulSoup(document[1],'lxml');venue=event.get('venue','')
    if 'berlin-buehnen.de' in event['source_url']:
        for item in page.select('hylo-accordion-item'):
            header=item.select_one('hylo-accordion-item-header');body=item.select_one('hylo-accordion-item-body')
            if not header or not body or header.get_text(strip=True)!='Ort': continue
            name=body.select_one('h5')
            if not name or folded(name.get_text(' ',strip=True))!=folded(venue): return None
            text=body.get_text(' ',strip=True)
            if not re.search(r'\b\d{5}\s+Berlin\b',text): return None
            return dict(city='Berlin',venue=venue,address=text,evidence_url=document[0],observed_at=now.isoformat(),kind='matched_event_location')
    elif campus and host(campus[0])=='ufafabrik.de' and venue in PROFILE['ufa_campus_venues']:
        text=BeautifulSoup(campus[1],'lxml').get_text(' ',strip=True)
        match=re.search(r'Viktoria\s*(?:straße|strasse|str\.)\s*10.{0,100}?12105\s+Berlin',text,re.I)
        if match:
            return dict(city='Berlin',venue=venue,address=match.group(),evidence_url=PROFILE['ufa_campus_url'],observed_at=now.isoformat(),kind='official_campus_and_matched_room')
    return None


def choose_release_sample(events,now,limit=3):
    """Prefer publishable candidates and distinct dates, never cancellations."""
    from scripts.score_events import exclusion_reason
    from scripts.pilot_release import future
    pool=[e for e in events if future(e,now) and not exclusion_reason(e) and e.get('ticket_status')!='sold_out'
          and (e.get('price') is None or e['price']<=20)
          and not re.search(r'\b(abgesagt|fällt aus|cancelled|verschoben)\b',e.get('description',''),re.I)]
    def priority(e):
        price=e.get('price')
        hint=bool(re.search(r'eintritt frei|kostenlos|vor[- ]?führung|einführung|öffentliche probe',e['title']+' '+e.get('description',''),re.I))
        return (not (price is not None and price<=5),not hint,e['date'],e.get('time',''),e['title'])
    pool.sort(key=priority);picked=[];dates=set()
    for e in pool:
        if e['date'] not in dates:
            picked.append(e);dates.add(e['date'])
            if len(picked)==limit: return picked
    for e in pool:
        if e not in picked: picked.append(e)
        if len(picked)==limit: break
    return picked


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    output=Path(a.output).resolve()
    assert output!=ROOT and ROOT not in output.parents, 'Output must be outside checkout'
    output.mkdir(parents=True,exist_ok=False)
    before=fingerprints(ROOT);now=datetime.now(timezone.utc);started=time.monotonic()
    day=now.astimezone(ZoneInfo('Europe/Berlin')).date();end=day+timedelta(days=PROFILE['window_days'])
    policy=dict(DEFAULT_POLICY,max_events_per_run=6,max_tinyfish_fetch_urls_per_run=6,max_tinyfish_search_queries_per_run=0,max_run_seconds=600)
    deadline=started+600;http=RecordingHTTP(policy,deadline=deadline)
    provider=RecordingTinyFish(max_fetch=6,max_search=0,deadline=deadline);http.provider=provider
    all_events=[];selected=[];listing=[]
    for name,base in PROFILE['sources'].items():
        urls=[build_date_url(base,day),build_date_url(base,end)] if name=='berlin_buehnen' else [base]
        events=[]
        for url in urls:
            page=document(url,http,provider)
            listing.append(dict(source=name,date=day.isoformat() if url==urls[0] else end.isoformat(),received=bool(page)))
            if not page: continue
            rows,_=validate_events(scrape_document(page[1],url,'R1.4 '+name),base,day,end,max_price=float('inf'))
            for e in rows: e.update(source_url=base,observed_at=now.isoformat())
            events.extend(rows)
        events=dedupe_events(events);all_events.extend(events)
        selected.extend(choose_release_sample(events,now))
    campus=document(PROFILE['ufa_campus_url'],http,provider)
    initial={'version':1,'events':{}}
    overlay,usage=run(selected,initial,now,policy,http,provider)
    documents=dict(provider.documents);documents.update(http.documents)
    for event in all_events:
        proof=location(event,documents.get(event['url']),campus,now)
        if proof: event['pilot_location']=proof
    data=dict(generated_at=now.isoformat(),events=all_events)
    # Sanitization precedes manifest sealing and reproducible offline rebuild.
    write_json(output/'discovery.json',data);write_json(output/'overlay.json',overlay)
    data=json.loads((output/'discovery.json').read_text());overlay=json.loads((output/'overlay.json').read_text())
    site,quality=candidate(data,overlay,now)
    site_dir=output/'site';site_dir.mkdir()
    (site_dir/'events_scored.json').write_text(json.dumps(site,ensure_ascii=False,indent=2)+'\n')
    from scripts.community_events import newsletter
    write_json(site_dir/'newsletter.json',newsletter(site['events'],now))
    shutil.copyfile(ROOT/'web/index.html',site_dir/'index.html');(site_dir/'.nojekyll').touch()
    if site['count']:
        subprocess.run([sys.executable,str(ROOT/'scripts/smoke_pages.py'),'--site',str(site_dir),'--output',str(output/'smoke'),'--now',now.isoformat()],check=True)
    else:
        (output/'smoke').mkdir();write_json(output/'smoke/report.json',{'status':'not_run_empty_candidate'})
    second,second_usage=run(selected,overlay,now+timedelta(minutes=5),policy,http,provider)
    assert overlay==second and second_usage['targets']==0, 'Overlay changed on fresh second run'
    assert fingerprints(ROOT)==before, 'Production data changed'
    diagnostics=dict(listings=listing,verification=usage,second_execution_targets=second_usage['targets'],
                     http_calls=http.diagnostics,tinyfish_calls=provider.diagnostics,
                     http_per_host=dict(http.hosts),http_attempts=http.requests,http_bytes=http.bytes,
                     tinyfish_fetch_urls=provider.fetch_urls,tinyfish_search_calls=provider.search_queries,
                     pipeline_seconds=round(time.monotonic()-started,3),production_files_unchanged=True)
    write_json(output/'diagnostics.json',diagnostics)
    evidence=[]
    for event in selected:
        doc=documents.get(event['url'])
        if doc:
            soup=BeautifulSoup(doc[1],'lxml')
            section=soup.select_one('article,bb-page-detail') or soup
            for tag in section.select('script,style,form,input,img,nav,footer'): tag.decompose()
            for tag in section.find_all(True): tag.attrs={k:v for k,v in tag.attrs.items() if k in ('class','datetime')}
            doc=(doc[0],str(section))
        evidence.append(dict(url=event['url'],title=event['title'],date=event['date'],time=event.get('time'),document=doc,representation='Sanitized event DOM; scripts, forms and URL attributes removed'))
    write_json(output/'source-evidence.json',evidence)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    run_id=__import__('os').environ.get('GITHUB_RUN_ID','0')
    manifest=seal(output,commit,now,run_id,quality)
    if quality['technical_go']:
        validate(output,digest(output/'release-manifest.json'),commit,run_id,now)
    summary=dict(manifest_sha256=digest(output/'release-manifest.json'),manifest=manifest,
                 diagnostics=diagnostics,events=[{k:e.get(k) for k in ('title','date','time','venue','url','source_url','price_min','price_max','price_status','student_discount_status','ticket_status','event_status','matched_categories')} for e in site['events']])
    # Check evidence contains no artifact signed URLs or credentials.
    from scripts.qualify_r12 import safe_artifact
    summary=safe_artifact(summary)
    encoded=__import__('base64').b64encode(json.dumps(summary,ensure_ascii=False).encode()).decode()
    chunks=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    assert len(chunks)<=10
    for i,chunk in enumerate(chunks,1): print(f'::notice title=R14 report chunk {i}/{len(chunks)}::{chunk}')
    print('Technical GO' if quality['technical_go'] else 'Technical NO-GO; diagnostic artifact retained')

if __name__=='__main__': main()
