"""Bounded public Rausgegangen URL discovery; Search supplies no event facts."""
from datetime import timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

BASE='https://rausgegangen.de/en/berlin/eventsbydate/'


def candidate_urls(urls):
    """Collapse locale aliases before spending Fetch allowance."""
    out=[];seen=set()
    for url in urls:
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname!='rausgegangen.de' or p.query or p.fragment: continue
        match=re.fullmatch(r'/(?:en/)?events/([^/]+)/?',p.path)
        if not match or match[1] in seen: continue
        seen.add(match[1]);out.append(url)
    return out


def discover(now,http,provider,documents=None,max_candidates=3,queries=None,seed_urls=()):
    """One shared bounded HTTP/provider context, with same-run document reuse.

    Return candidates with destination facts, never Search titles/snippets.
    The caller must run the production verifier before asserting verification.
    """
    from scripts.generic_event_scraper import scrape_document
    from scripts.event_utils import validate_events, dedupe_events
    today=now.astimezone(ZoneInfo('Europe/Berlin')).date()
    end=today+timedelta(days=7)
    queries=queries or [f'site:rausgegangen.de/events/ Berlin "{today.strftime("%d.%m.%Y")}"',
                        f'site:rausgegangen.de/en/events/ Berlin "{today.strftime("%d.%m.%Y")}"']
    urls=list(seed_urls)
    for query in queries[:2]: urls.extend(provider.search(query))
    urls=candidate_urls(urls);events=[];attempts=[]
    documents=documents if documents is not None else {}
    for url in urls[:max_candidates]:
        document=documents.get(url) or http.fetch(url);method='direct_http'
        if not document and http.permitted:
            result=provider.fetch([url]).get(url)
            if result and http.bytes+len(result['html'].encode())<=http.policy['max_total_response_bytes']:
                document=(result['final_url'],result['html']);method='tinyfish_fetch'
                http.bytes+=len(document[1].encode())
        attempt={'transport':method,'outcome':'received' if document else http.reason,
                 'candidate_url':url,'search_candidates':len(urls)}
        attempts.append(attempt)
        if not document: continue
        # No off-source redirect becomes source evidence.
        if not candidate_urls([document[0]]):
            attempt['outcome']='rejected_destination';continue
        documents[url]=documents[document[0]]=document
        raw=scrape_document(document[1],document[0],'Raus public destination')
        raw=[e for e in raw if re.search(r'\bBerlin\b',str(e.get('description',''))+' '+str(e.get('venue','')),re.I)]
        cleaned,_=validate_events(raw,BASE,today,end,max_price=float('inf'))
        for event in cleaned:
            event['observed_at']=now.isoformat();event['url']=document[0]
        events.extend(cleaned)
        attempt.update(destination_url=document[0],extracted_occurrences=len(cleaned))
        if not cleaned:
            from bs4 import BeautifulSoup
            attempt['rejected_structure']=BeautifulSoup(document[1],'lxml').get_text(' | ',strip=True)[:2200]
    return dedupe_events(events),attempts


_RUN_EVENTS=None


def scrape_public_listing():
    """Production entry: one bounded discovery batch per scraper process.

    Fail closed on robots/provider failure. Never enter the generic browser or
    challenge-handling fallback for this source. Cached failures cost no retries.
    """
    global _RUN_EVENTS
    if _RUN_EVENTS is not None: return [dict(e) for e in _RUN_EVENTS]
    from datetime import datetime, timezone
    import time
    from scripts.verify_event_details import BoundedHTTP, DEFAULT_POLICY, observation
    from scripts.tinyfish_client import TinyFishClient
    policy=dict(DEFAULT_POLICY,max_http_requests_per_run=8,max_requests_per_host=8,max_run_seconds=540)
    deadline=time.monotonic()+540
    http=BoundedHTTP(policy,deadline=deadline)
    provider=TinyFishClient(max_fetch=3,max_search=2,deadline=deadline)
    now=datetime.now(timezone.utc);documents={}
    events,_=discover(now,http,provider,documents)
    _RUN_EVENTS=[]
    for event in events:
        document=documents.get(event['url'])
        if document and observation(event,document[1],document[0],now.isoformat()):
            _RUN_EVENTS.append(event)
    return [dict(e) for e in _RUN_EVENTS]
