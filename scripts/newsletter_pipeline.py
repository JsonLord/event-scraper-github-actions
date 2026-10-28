"""Full-corpus newsletter materialization, independent of pilot/personal scoring."""
from copy import deepcopy
from datetime import timedelta
from urllib.parse import urlsplit
import json
from pathlib import Path
from scripts.event_matching import match_basis
from scripts.ticket_evidence import folded,occurrence_id
from scripts.verify_event_details import utc

CULTURAL_TYPES={'PerformingArtsTheater','Theater','OperaHouse','CommunityCenter','CulturalCenter','Museum','Library','Park','PublicSquare'}
EXCLUDED_TYPES={'BarOrPub','CafeOrCoffeeShop','NightClub','Restaurant'}


def destination_proof(event,html,url,now):
    """Only a matching Event's structured location supplies generic city/type proof."""
    from scripts.generic_event_scraper import extract_jsonld_events
    for candidate in extract_jsonld_events(html,url):
        if not match_basis(event,candidate,url) or folded(candidate.get('location_city',''))!='berlin': continue
        types={t.rsplit('/',1)[-1] for t in candidate.get('location_types',[]) if isinstance(t,str)}
        if types & EXCLUDED_TYPES: return None
        return dict(city='Berlin',venue=event.get('venue') or candidate.get('venue',''),observed_at=utc(now).isoformat(),evidence_url=url,
                    kind='matched_event_jsonld_location',host_types=sorted(types))
    return None


def build_newsletter(data,overlay,now):
    from scripts.audit_events import normalize_records
    from scripts.build_page_dataset import merge_overlay
    from scripts.community_events import newsletter
    rows,_=normalize_records(data.get('events',[]),data.get('generated_at'))
    # Deliberately no score_and_filter_events(), source profile, or selected-row slice.
    rows=merge_overlay(rows,overlay,now)
    for event in rows:
        if event.get('listing_ticket_status')=='sold_out': event['ticket_status']='sold_out'
    result=newsletter(rows,now)
    result.update(scope='full_source_catalog',input_occurrences=len(rows),sources_considered=sorted({e.get('source_url','') for e in rows}),source_catalog=data.get('source_catalog',[]),source_diagnostics=data.get('source_diagnostics',[]),source_coverage_complete=bool(data.get('source_diagnostics')) and all(s['outcome'] in ('fresh_discovery_reused','discovered') for s in data.get('source_diagnostics',[])))
    return result


def collect(data,overlay,now,http,provider,documents):
    """Consider every configured source; preserve explicit budget/host failures."""
    import yaml
    from scripts.generic_event_scraper import scrape_document,extract_jsonld_events
    from scripts.event_utils import validate_events,dedupe_events
    from scripts.qualify_r14 import document
    from scripts.verify_event_details import run
    from scripts.community_events import CULTURAL_VENUES,PUBLIC_SPACES
    root=Path(__file__).resolve().parents[1]
    catalog=yaml.safe_load((root/'.github/workflows/weekly-event-scraper.yml').read_text())['jobs']['scrape']['strategy']['matrix']['include']
    from zoneinfo import ZoneInfo
    day=utc(now).astimezone(ZoneInfo('Europe/Berlin')).date();end=day+timedelta(days=7)
    rows=deepcopy(data['events']);diagnostics=[]
    existing={e.get('source_url','').rstrip('/') for e in rows}
    for source in catalog:
        url=source['url'].replace('__START_DATE__',day.isoformat()).replace('__END_DATE__',end.isoformat())
        diagnostic=dict(name=source['name'],url=url,discovered=0)
        if url.rstrip('/') in existing:
            diagnostic['outcome']='fresh_discovery_reused';diagnostics.append(diagnostic);continue
        if http.requests>=http.policy['max_http_requests_per_run']-4:
            diagnostic['outcome']='listing_budget_reserved_for_verification';diagnostics.append(diagnostic);continue
        # Direct-only listing discovery reserves free Fetch allowance for details.
        page=http.fetch(url)
        if not page:
            diagnostic['outcome']=http.reason;diagnostics.append(diagnostic);continue
        found,_=validate_events(scrape_document(page[1],url,'Full-list newsletter discovery'),url,day,end,max_price=float('inf'))
        for event in found: event['observed_at']=utc(now).isoformat()
        rows.extend(found);diagnostic.update(discovered=len(found),outcome='discovered' if found else 'no_event_evidence')
        diagnostics.append(diagnostic)
    rows=dedupe_events(rows)
    # Discovery prices/words are candidates only; production matching remains mandatory.
    def priority(e):
        price=e.get('price')
        host_hint=folded(e.get('venue','')) in CULTURAL_VENUES|PUBLIC_SPACES or bool(set(e.get('location_types',[])) & CULTURAL_TYPES)
        cheap=price is not None and price<=5
        return (0 if cheap and host_hint else 1 if host_hint else 2 if cheap else 3,e['date'],e.get('time',''),e.get('title',''))
    candidates=[e for e in rows if occurrence_id(e) not in overlay.get('events',{}) and e.get('ticket_status')!='sold_out' and (e.get('price') is None or e['price']<=5)]
    candidates.sort(key=priority)
    # Fairly spread scarce verification slots across sources, not just the pilot.
    from collections import defaultdict,deque
    groups=defaultdict(deque)
    for event in candidates: groups[urlsplit(event.get('source_url','')).hostname].append(event)
    selected=[]
    while any(groups.values()) and len(selected)<6:
        for queue in sorted((q for q in groups.values() if q),key=lambda q:priority(q[0])):
            selected.append(queue.popleft())
            if len(selected)==6: break
    addition,usage=run(selected,{'version':1,'events':{}},now,dict(http.policy,max_events_per_run=6),http,provider)
    combined=deepcopy(overlay);combined.setdefault('events',{}).update(addition.get('events',{}))
    cached=dict(getattr(provider,'documents',{}));cached.update(getattr(http,'documents',{}));cached.update(documents)
    for event in rows:
        doc=cached.get(event.get('url'))
        if doc:
            proof=destination_proof(event,doc[1],doc[0],now)
            if proof:
                event['location_evidence']=proof
                event['venue']=event.get('venue') or proof['venue']
    return dict(generated_at=utc(now).isoformat(),events=rows,source_diagnostics=diagnostics,source_catalog=[dict(name=s['name'],url=s['url']) for s in catalog]),combined,dict(sources=diagnostics,additional_verification=usage,selected_candidates=[dict(title=e['title'],url=e['url'],source_url=e['source_url'],outcome=addition.get('events',{}).get(occurrence_id(e),{}).get('outcome','not_selected')) for e in selected])
