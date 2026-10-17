#!/usr/bin/env python3
"""Bounded, public read-only observation. Network failures mean unknown.

No browser, login, cookies, forms, purchase flows, or paid endpoints. Robots
fetches, redirects and retries all consume the same HTTP/host/byte budgets.
"""
from __future__ import annotations
import argparse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from urllib3.exceptions import HTTPError
from bs4 import BeautifulSoup
from scripts.ticket_evidence import folded, enrich_evidence, occurrence_id
from scripts.tinyfish_client import TinyFishClient, public_url
from scripts.event_utils import normalize_date, parse_date, parse_time, clean_url, looks_synthetic_title

DEFAULT_POLICY = json.loads((Path(__file__).resolve().parents[1]/'config/verification_policy.json').read_text())
AGENT = 'BerlinEventEvidence/1.0'


def utc(value):
    parsed = datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def policy_from(path):
    raw = json.loads(Path(path).read_text())
    result = dict(DEFAULT_POLICY)
    for k,v in raw.items():
        if k == 'ttl_hours':
            result[k] = {f:min(max(0,float(v.get(f,n))),n) for f,n in DEFAULT_POLICY[k].items()}
        elif k in DEFAULT_POLICY:
            result[k] = min(max(0,int(v)), DEFAULT_POLICY[k])
    return result


class BoundedHTTP:
    def __init__(self, policy=None, session=None, validator=public_url, deadline=None, clock=time.monotonic):
        self.policy = policy or DEFAULT_POLICY
        self.session = session or requests.Session()
        self.validator = validator
        self.requests = self.bytes = 0
        self.hosts = defaultdict(int)
        self.blocked = set()
        self.robots = {}
        self.reason = 'unknown'
        self.permitted = False
        self.deadline,self.clock=deadline,clock

    def _get(self, url, robots=False):
        retries = 0
        while self.validator(url):
            if self.deadline is not None and self.clock()+20>self.deadline:
                self.reason='run_deadline'; return None
            host = urlsplit(url).netloc
            if host in self.blocked or self.requests >= self.policy['max_http_requests_per_run'] or self.hosts[host] >= self.policy['max_requests_per_host'] or self.bytes >= self.policy['max_total_response_bytes']:
                self.reason = 'http_budget_or_host_blocked'
                return None
            self.requests += 1; self.hosts[host] += 1
            try:
                self.session.cookies.clear()
                response = self.session.get(url, headers={'User-Agent':AGENT, 'Accept':'text/html,text/plain'}, timeout=(self.policy['connect_timeout_seconds'], self.policy['read_timeout_seconds']), allow_redirects=False, stream=True)
                with response:
                    status = response.status_code
                    if status in (403,429):
                        self.blocked.add(host); self.reason = 'http_'+str(status); return None
                    if status in (301,302,303,307,308):
                        redirected = urljoin(url,response.headers.get('Location',''))
                        if urlsplit(redirected).netloc != host:
                            self.reason = 'cross_host_redirect_unverified'; return None
                        parser = self.robots.get(urlsplit(url).scheme+'://'+host)
                        if not robots and (parser is None or not parser.can_fetch(AGENT,redirected)):
                            self.reason = 'robots_redirect_denied'; return None
                        url = redirected
                        continue  # Each hop is checked and charged separately.
                    if status >= 500 and retries < 1:
                        retries += 1
                        continue
                    if status != 200:
                        self.reason = 'http_'+str(status); return None
                    mime = response.headers.get('Content-Type','').split(';')[0].lower()
                    if mime not in (('text/plain','text/html') if robots else ('text/html','application/xhtml+xml')):
                        self.reason = 'unsupported_mime'; return None
                    chunks, size = [], 0
                    while True:
                        if self.deadline is not None and self.clock()+12>self.deadline:
                            self.reason='run_deadline'; return None
                        remaining = min(self.policy['max_response_bytes']-size, self.policy['max_total_response_bytes']-self.bytes)
                        if remaining <= 0:
                            self.reason = 'byte_budget'; return None
                        chunk = response.raw.read(min(16384,remaining), decode_content=True)
                        if not chunk: break
                        size += len(chunk); self.bytes += len(chunk)
                        chunks.append(chunk)
                    text = b''.join(chunks).decode('utf-8',errors='replace')
                    from scripts.generic_event_scraper import is_bot_challenge
                    if not robots and is_bot_challenge(text):
                        self.reason = 'challenge'; return None
                    self.reason = 'ok'
                    return url, text
            except (requests.exceptions.RequestException, OSError, HTTPError):
                self.reason = 'network_failed'
                if retries >= 1: return None
                retries += 1
        self.reason = 'unsafe_url'
        return None

    def fetch(self, url):
        self.permitted = False
        if not self.validator(url):
            self.reason = 'unsafe_url'; return None
        p = urlsplit(url); origin = p.scheme+'://'+p.netloc
        if origin not in self.robots:
            raw = self._get(origin+'/robots.txt', robots=True)
            # Unknown robots policy fails closed; absence (404) means no rules.
            if raw:
                parser = RobotFileParser(); parser.parse(raw[1].splitlines()); self.robots[origin] = parser
            elif self.reason == 'http_404':
                parser = RobotFileParser(); parser.parse([]); self.robots[origin] = parser
            else:
                self.robots[origin] = None
        parser = self.robots[origin]
        if parser is None or not parser.can_fetch(AGENT,url):
            self.reason = 'robots_denied_or_unknown'; return None
        self.permitted = True
        return self._get(url)


def matches(event, candidate):
    from scripts.event_matching import match_basis
    return bool(match_basis(event,candidate,candidate.get('url','')))


def observation(event, html, final_url, now):
    from scripts.generic_event_scraper import extract_jsonld_events, is_bot_challenge
    if is_bot_challenge(html) or not public_url(final_url,resolve=False): return None
    from scripts.event_matching import event_url, match_basis, semantic_candidates
    if not event_url(final_url) or event_url(final_url)==event_url(event.get('source_url','')): return None
    candidates = extract_jsonld_events(html,final_url)
    candidates += semantic_candidates(html,final_url,event.get('title',''))
    matching = [c for c in candidates if match_basis(event,c,final_url)]
    if not matching: return None
    enriched = [enrich_evidence(c, now) for c in matching]
    for candidate, item in zip(matching,enriched):
        if candidate.get('_explicit_available') and item['ticket_status']=='unknown' and item['event_status'] not in ('cancelled','postponed'):
            item['ticket_status']='available' 
    # Conflicting bound records cannot assert inventory or choose cheap prices.
    prices = {(e['price_min'],e['price_max']) for e in enriched if e['price'] is not None}
    states = {e['ticket_status'] for e in enriched} - {'unknown'}
    chosen = enriched[0]
    if len(prices)>1:
        chosen.update(price=None,price_min=None,price_max=None,price_status='conflicted',price_label='Conflicting prices · check site',free_admission_confirmed=False)
    if len(states)>1: chosen['ticket_status']='unknown'
    if any(e['event_status']=='cancelled' for e in enriched): chosen.update(event_status='cancelled',ticket_status='unknown')
    fields = {
        'link': {'url':clean_url(final_url),'detail_link_status':'verified','last_verified_at':now},
        'status': {'ticket_status':chosen['ticket_status']},
        'event_status': {'event_status':chosen['event_status']},
    }
    if chosen['price'] is not None or chosen['price_status']=='conflicted':
        fields['price']={k:chosen[k] for k in ('price','price_min','price_max','price_status','price_label','free_admission_confirmed')}
        fields['discount']={k:chosen[k] for k in ('offers','student_discount_status')}
    fields = {k:v for k,v in fields.items() if k not in ('status','event_status') or 'unknown' not in v.values() or (k=='status' and len(states)>1)}
    return {k:dict(values=v,observed_at=now,evidence_url=clean_url(final_url),source='matched_event_page',match_basis=match_basis(event,matching[0],final_url)) for k,v in fields.items()}


def select_targets(events, now, overlay, policy):
    today=now.astimezone(ZoneInfo('Europe/Berlin')).date()
    buckets = [defaultdict(list),defaultdict(list)]
    seen=set()
    for event in events:
        eid=occurrence_id(event)
        if eid in seen: continue
        seen.add(eid)
        try:
            d=datetime.fromisoformat(event['date']).date(); days=(d-today).days
        except (ValueError,KeyError): continue
        if not 0<=days<=7: continue
        if days==0 and event.get('time') and event['time']<now.astimezone(ZoneInfo('Europe/Berlin')).strftime('%H:%M'): continue
        checked=overlay.get(eid,{}).get('checked_at')
        if checked and timedelta(0)<=now-utc(checked)<timedelta(hours=12): continue
        if looks_synthetic_title(event.get('title','')): continue
        host=urlsplit(event.get('source_url') or event.get('url','')).hostname or ''
        performance=datetime.combine(d,datetime.strptime(event.get('time') or '23:59','%H:%M').time(),tzinfo=ZoneInfo('Europe/Berlin'))
        buckets[0 if performance<=now+timedelta(hours=48) else 1][host].append(event)
    result=[]
    for bucket in buckets:
        queues={h:deque(sorted(es,key=lambda e:(e['date'],-e.get('score',0),e.get('title',''),e.get('time','')))) for h,es in sorted(bucket.items())}
        while any(queues.values()) and len(result)<policy['max_events_per_run']:
            for queue in queues.values():
                if queue and len(result)<policy['max_events_per_run']: result.append(queue.popleft())
    return result


def run(events, overlay, now, policy=None, http=None, tinyfish=None, dry_run=False):
    policy=policy or DEFAULT_POLICY
    now=utc(now); stamp=now.isoformat().replace('+00:00','Z')
    records=dict(overlay.get('events',{}))
    targets=select_targets(events,now,records,policy)
    usage=dict(targets=len(targets),http_attempts=0,http_bytes=0,tinyfish_fetch_urls=0,tinyfish_search_queries=0)
    if dry_run: return overlay,usage
    deadline=time.monotonic()+policy.get('max_run_seconds',900)
    http=http or BoundedHTTP(policy,deadline=deadline)
    tinyfish=tinyfish or TinyFishClient(max_fetch=policy['max_tinyfish_fetch_urls_per_run'],max_search=policy['max_tinyfish_search_queries_per_run'],deadline=deadline)
    for event in targets:
        if time.monotonic()>=deadline: break
        eid=occurrence_id(event); previous=records.get(eid,{})
        if previous.get('checked_at') and utc(previous['checked_at'])>now:
            continue
        found=None; reason='unverified'
        candidate=event.get('url','')
        good_link=event.get('has_detail_link') and candidate!=event.get('source_url')
        candidates=[candidate] if good_link else []
        if not candidates:
            host=urlsplit(event.get('source_url','')).hostname or ''
            query=' '.join(str(event.get(k) or '') for k in ('title','venue','date'))+' Berlin'+(' site:'+host if host else '')
            candidates=tinyfish.search(query)[:2]
        for candidate in candidates:
            raw=http.fetch(candidate); reason=http.reason
            if raw:
                found=observation(event,raw[1],raw[0],stamp)
                if not found: reason='content_mismatch'
            # Honour robots even for hosted retrieval. No provider challenge solving.
            if not found and http.permitted:
                rendered=tinyfish.fetch([candidate]).get(candidate)
                if rendered:
                    size=len(rendered['html'].encode())
                    if size<=policy['max_response_bytes'] and http.bytes+size<=policy['max_total_response_bytes']:
                        http.bytes+=size
                        found=observation(event,rendered['html'],rendered['final_url'],stamp)
            if found: break
        row=dict(previous)
        fields=dict(previous.get('fields',{}))
        for field,value in (found or {}).items():
            if field not in fields or utc(value['observed_at'])>=utc(fields[field]['observed_at']): fields[field]=value
        row.update(checked_at=stamp,outcome='matched' if found else reason,fields=fields)
        records[eid]=row
    usage.update(http_attempts=http.requests,http_bytes=http.bytes,tinyfish_fetch_urls=tinyfish.fetch_urls,tinyfish_search_queries=tinyfish.search_queries,tinyfish_diagnostic=tinyfish.diagnostic)
    # Compact retention: keep only occurrences still in canonical discovery data.
    ids={occurrence_id(e) for e in events}
    return dict(version=1,events={k:v for k,v in records.items() if k in ids}), usage


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='data/events_scored.json');p.add_argument('--overlay',default='data/event_verifications.json');p.add_argument('--policy',default='config/verification_policy.json');p.add_argument('--now');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    data=json.loads(Path(a.input).read_text());overlay=json.loads(Path(a.overlay).read_text()) if Path(a.overlay).exists() else dict(version=1,events={})
    output,usage=run(data['events'],overlay,a.now or datetime.now(timezone.utc),policy_from(a.policy),dry_run=a.dry_run)
    if not a.dry_run and output!=overlay: Path(a.overlay).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(usage,sort_keys=True))

if __name__=='__main__': main()
