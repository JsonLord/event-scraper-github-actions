#!/usr/bin/env python3
"""One materialization path for weekly, daily and manual Pages builds."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.audit_events import normalize_records, gate
from scripts.ticket_evidence import occurrence_id
from scripts.verify_event_details import utc, DEFAULT_POLICY
from scripts.score_events import score_and_filter_events


def fresh(observed, now, hours):
    try: return timedelta(0) <= now-utc(observed) < timedelta(hours=hours)
    except (TypeError,ValueError,AttributeError): return False


def merge_overlay(events, overlay, now):
    now=utc(now); out=[]
    for original in events:
        e=deepcopy(original)
        entry=overlay.get('events',{}).get(occurrence_id(e),{})
        e['field_observed_at']={}
        historical_link=entry.get('fields',{}).get('link',{})
        if historical_link: e['last_verified_at']=historical_link.get('observed_at')
        # Discovery observations expire too; old snapshots cannot assert inventory.
        stamp=e.get('observed_at')
        ticket=e.get('ticket_status','unknown')
        if not fresh(stamp,now,DEFAULT_POLICY['ttl_hours'].get(ticket,12)): e['ticket_status']='unknown'
        if not fresh(stamp,now,48):
            e.update(free_admission_confirmed=False,price_status='unknown',price_label='Historical price · check site' if e.get('price') is not None else 'Check site')
        if not fresh(stamp,now,168): e['student_discount_status']='unknown'; e['offers']=[]
        if not fresh(stamp,now,24): e['event_status']='unknown'
        for group,record in entry.get('fields',{}).items():
            values=record.get('values',{})
            ttl=DEFAULT_POLICY['ttl_hours'].get(values.get('ticket_status'),12) if group=='status' else DEFAULT_POLICY['ttl_hours'].get(group,0)
            observed=record.get('observed_at')
            # Older overlay cannot displace a newer discovery observation.
            if stamp and observed and utc(observed)<utc(stamp): continue
            if not fresh(observed,now,ttl): continue
            allowed={
                'link':('url','detail_link_status','last_verified_at'),
                'status':('ticket_status',), 'event_status':('event_status',),
                'price':('price','price_min','price_max','price_status','price_label','free_admission_confirmed'),
                'discount':('offers','student_discount_status'),
            }.get(group,())
            e.update({k:v for k,v in values.items() if k in allowed})
            e['field_observed_at'][group]=observed
            e.setdefault('evidence',{})[group]={k:record.get(k) for k in ('source','observed_at','evidence_url')}
        if e.get('event_status') in ('cancelled','postponed'): e['ticket_status']='unknown'
        # Available evidence is never supported by a cancelled discovery occurrence.
        e['verification_checked_at']=entry.get('checked_at')
        e['verification_outcome']=entry.get('outcome','not_checked')
        out.append(e)
    return out


def build(data, overlay, now):
    normalized,q=normalize_records(data.get('events',[]),data.get('generated_at'))
    # Score canonical discovery once, then apply observations without mutating it.
    scored=score_and_filter_events(normalized,today=utc(now).date())
    events=merge_overlay(scored,overlay,now)
    gate(events)
    from scripts.community_events import decision
    for event in events:
        event['community_eligible'],event['community_reason']=decision(event,now)
    return dict(generated_at=data.get('generated_at'),built_at=utc(now).isoformat(),count=len(events),quarantined_count=len(q),events=events)


def newsletter_payload(data,overlay,now):
    from scripts.newsletter_pipeline import build_newsletter
    return build_newsletter(data,overlay,now)


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='data/events.json');p.add_argument('--overlay',default='data/event_verifications.json');p.add_argument('--output-dir',default='_site');p.add_argument('--now');a=p.parse_args()
    data=json.loads(Path(a.input).read_text()); overlay=json.loads(Path(a.overlay).read_text()) if Path(a.overlay).exists() else dict(events={})
    payload=build(data,overlay,a.now or datetime.now(timezone.utc));output=Path(a.output_dir);output.mkdir(parents=True,exist_ok=True)
    (output/'events_scored.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    from scripts.community_events import newsletter
    (output/'newsletter.json').write_text(json.dumps(newsletter_payload(data,overlay,a.now or datetime.now(timezone.utc)),ensure_ascii=False,indent=2)+'\n')
    shutil.copyfile(Path(__file__).resolve().parents[1]/'web/index.html',output/'index.html')
    (output/'.nojekyll').touch()
    print(f"Built {len(payload['events'])} events; quarantined {payload['quarantined_count']}")

if __name__=='__main__': main()
