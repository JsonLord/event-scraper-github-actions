#!/usr/bin/env python3
"""Offline quality audit. Counts describe stored evidence, never live inventory."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.event_utils import looks_synthetic_title, dedupe_events, extract_venue
from scripts.ticket_evidence import enrich_evidence


def normalize_records(events, observed_at=None):
    kept, quarantine = [], []
    for e in events:
        if looks_synthetic_title(e.get('title','')):
            quarantine.append(dict(title=e.get('title'),date=e.get('date'),source_url=e.get('source_url'),reason='badge_category_or_offer_title'))
            continue
        row = dict(e)
        row['venue'] = row.get('venue') or extract_venue(row.get('description',''),row.get('title',''))
        row.setdefault('observed_at', observed_at)
        kept.append(enrich_evidence(row))
    return dedupe_events(kept), quarantine


def metrics(events, now='2026-10-17'):
    return dict(records=len(events),unknown_prices=sum(e.get('price') is None for e in events),zero_prices=sum(e.get('price')==0 for e in events),
                free_labels=sum(e.get('price_label')=='Free' for e in events),verified_free=sum(e.get('free_admission_confirmed') is True for e in events),
                missing_links=sum(not e.get('has_detail_link') for e in events),verified_links=sum(e.get('detail_link_status')=='verified' for e in events),
                blank_venues=sum(not e.get('venue') for e in events),past=sum((e.get('date') or '')<now for e in events),
                student_evidence=sum(e.get('student_discount_status')=='explicit' for e in events),
                generic_reduced=sum(any(o.get('kind')=='reduced' for o in e.get('offers',[])) for e in events),
                reported_sold_out=sum(e.get('ticket_status')=='sold_out' for e in events),reported_cancelled=sum(e.get('event_status')=='cancelled' for e in events))


def report(events, now):
    sources=defaultdict(list)
    for e in events: sources[urlsplit(e.get('source_url','')).hostname or 'unknown'].append(e)
    return dict(total=metrics(events,now),sources={s:metrics(es,now) for s,es in sorted(sources.items())})


def gate(events):
    for e in events:
        assert not looks_synthetic_title(e.get('title','')), 'pseudo-title'
        assert e.get('event_id','').startswith('sha256:'), 'missing occurrence ID'
        assert e.get('detail_link_status') in ('missing','candidate','verified','invalid'), 'link status'
        assert e.get('ticket_status') in ('available','sold_out','unknown','not_applicable'), 'ticket status'
        assert e.get('event_status') in ('scheduled','cancelled','postponed','unknown'), 'event status'
        assert e.get('price_status') in ('known','free','range','unknown','conflicted'), 'price status'
        assert e.get('price_label')!='Free' or (e.get('free_admission_confirmed') and e.get('price_max')==0), 'unsupported Free'
        assert not (e.get('event_status')=='cancelled' and e.get('ticket_status')=='available'), 'cancelled inventory'
        assert e.get('detail_link_status')!='verified' or e.get('last_verified_at'), 'verification timestamp'


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='data/events_scored.json');p.add_argument('--output');p.add_argument('--now',default='2026-10-17');p.add_argument('--gate',action='store_true');a=p.parse_args()
    raw=Path(a.input).read_bytes();data=json.loads(raw);events=data['events'] if isinstance(data,dict) else data
    after,q=normalize_records(events,data.get('generated_at') if isinstance(data,dict) else None)
    if a.gate: gate(events)
    result=dict(input_sha256=hashlib.sha256(raw).hexdigest(),as_of=a.now,evidence_scope='frozen stored data; no live verification',before=report(events,a.now),after=report(after,a.now),quarantine=q,deduplicated=len(events)-len(q)-len(after))
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output: Path(a.output).write_text(text+'\n')
    else: print(text)

if __name__=='__main__': main()
