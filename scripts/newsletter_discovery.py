"""Bounded, direct-only catalog discovery with capacity for every source.

Workers own a host/session. Robots, redirects, retries and public JSON requests
are charged; a host's blocking/robots decisions survive into detail verification.
No provider, browser or challenge-solving fallback is used here.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from scripts.event_utils import validate_events, dedupe_events
from scripts.generic_event_scraper import scrape_document, _from_eventon, _from_tribe
from scripts.verify_event_details import utc

ATTEMPTS_PER_SOURCE = 4
MAX_HOST_ATTEMPTS = 16
BYTES_PER_SOURCE = 2_000_000
DISCOVERY_SECONDS = 240


def discover(catalog, existing, now, verifier_http, client_factory=None):
    from scripts.qualify_r12 import RecordingHTTP
    client_factory = client_factory or RecordingHTTP
    day = utc(now).astimezone(ZoneInfo('Europe/Berlin')).date()
    end = day + timedelta(days=7)
    deadline = min(time.monotonic()+DISCOVERY_SECONDS,
                   (verifier_http.deadline or float('inf'))-60)
    groups = defaultdict(list)
    diagnostics = [None]*len(catalog)
    for index, source in enumerate(catalog):
        url = source['url'].replace('__START_DATE__', day.isoformat()).replace('__END_DATE__', end.isoformat())
        reused = [e for e in existing if e.get('source_url', '').rstrip('/') == url.rstrip('/')]
        if reused:
            for event in reused:
                event.setdefault('discovery_source_names', []).append(source['name'])
            diagnostics[index] = dict(name=source['name'], url=url, discovered=len(reused),
                                      outcome='fresh_discovery_reused', listing_received=True,
                                      raw_candidates=len(reused), http_attempts=0)
        else:
            groups[urlsplit(url).netloc].append((index, source['name'], url))

    def worker(entries):
        capacity = min(ATTEMPTS_PER_SOURCE*len(entries), MAX_HOST_ATTEMPTS)
        policy = dict(verifier_http.policy, max_http_requests_per_run=capacity,
                      max_requests_per_host=capacity,
                      max_total_response_bytes=BYTES_PER_SOURCE*len(entries))
        client = client_factory(policy, deadline=deadline)
        found_all = []
        results = []
        for index, name, url in entries:
            start = client.requests
            # A redirect/retry-heavy source cannot consume its sibling's slots.
            client.policy['max_http_requests_per_run'] = min(capacity, start+ATTEMPTS_PER_SOURCE)
            diagnostic = dict(name=name, url=url, discovered=0, listing_received=False, raw_candidates=0)
            page = client.fetch(url)
            if not page:
                diagnostic.update(outcome=client.reason, http_attempts=client.requests-start)
                if client.reason == 'robots_denied_or_unknown':
                    origin = urlsplit(url).scheme+'://'+urlsplit(url).netloc
                    diagnostic['robots_policy'] = 'unknown' if client.robots.get(origin) is None else 'denied'
                    diagnostic['robots_http_status'] = next((d['http_status'] for d in reversed(client.diagnostics) if d['operation']=='robots'), None)
                results.append((index, diagnostic))
                continue
            diagnostic['listing_received'] = True
            raw = scrape_document(page[1], url, 'Full-list newsletter discovery')
            # This listing's public WordPress event plugin is already supported
            # by the production scraper; use only its public, robots-checked API.
            if not raw and urlsplit(url).hostname in ('theclubmap.com', 'www.theclubmap.com'):
                origin = urlsplit(url).scheme+'://'+urlsplit(url).netloc
                for endpoint in ('/wp-json/wp/v2/ajde_events?per_page=100',
                                 '/wp-json/tribe/events/v1/events?per_page=50'):
                    api = client.fetch(origin+endpoint, accept_json=True)
                    if not api:
                        diagnostic['structured_fallback'] = client.reason
                        continue
                    try:
                        payload = json.loads(api[1])
                    except (ValueError, TypeError):
                        diagnostic['structured_fallback'] = 'invalid_json'
                        continue
                    if isinstance(payload, list):
                        # WordPress publication dates are not performance dates.
                        payload = [r for r in payload if isinstance(r, dict) and
                                   isinstance(r.get('meta'), dict) and r['meta'].get('evcal_srow')]
                        raw = _from_eventon(payload, url)
                    elif isinstance(payload, dict):
                        raw = _from_tribe(payload, url)
                    diagnostic['structured_fallback'] = 'public_wordpress_events'
                    if raw:
                        break
            found, _ = validate_events(raw, url, day, end, max_price=float('inf'))
            found = dedupe_events(found)
            for event in found:
                event['observed_at'] = utc(now).isoformat()
                event['discovery_source_names'] = [name]
            found_all.extend(found)
            diagnostic.update(discovered=len(found), raw_candidates=len(raw),
                              outcome='discovered' if found else 'no_occurrences_in_window' if raw else 'no_event_evidence',
                              http_attempts=client.requests-start)
            results.append((index, diagnostic))
        return found_all, results, client

    added = []
    clients = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for found, results, client in pool.map(worker, groups.values()):
            added.extend(found)
            clients.append(client)
            for index, diagnostic in results:
                diagnostics[index] = diagnostic
    # Same-run evidence/permission reuse, with distinct discovery/verification
    # counters. Do not lose a 403 decision and retry that host for every detail.
    for client in clients:
        verifier_http.robots.update(client.robots)
        verifier_http.blocked.update(client.blocked)
        if hasattr(verifier_http, 'documents'):
            verifier_http.documents.update(getattr(client, 'documents', {}))
    usage = dict(http_attempts=sum(c.requests for c in clients),
                 http_bytes=sum(c.bytes for c in clients),
                 max_http_attempts=sum(min(ATTEMPTS_PER_SOURCE*len(g), MAX_HOST_ATTEMPTS) for g in groups.values()),
                 max_response_bytes=verifier_http.policy['max_response_bytes'],
                 max_total_response_bytes=sum(BYTES_PER_SOURCE*len(g) for g in groups.values()),
                 max_seconds=DISCOVERY_SECONDS, max_concurrent_hosts=2,
                 calls=[d for c in clients for d in c.diagnostics])
    return added, diagnostics, usage
