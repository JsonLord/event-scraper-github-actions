"""Captured main records + explicitly reconstructed DOM and synthetic JSON-LD.

No reconstructed markup is represented as the original Raus listing/detail DOM.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path

import pytest

from scripts import generic_event_scraper as generic
from scripts.raus_html import (direct_pipeline, identity, match_detail, parse_listing,
    publication_gate, sort_key, stable_candidates)
from scripts.qualify_restored_branch import sample_one

FIXTURES = Path(__file__).parent/'fixtures'
CAPTURE = json.loads((FIXTURES/'raus_main_extracted_rows_2026-10-25.json').read_text())
SOURCE = CAPTURE['source']
NOW = datetime(2026,10,25,8,tzinfo=timezone.utc)
FIRST, LAST = date(2026,10,25), date(2026,11,1)


def reconstructed_card(event, short_date=False):
    """Reconstruct relationships from extracted records, not the lost live DOM."""
    when = ('<p>'+escape(event['description'])+'</p>' if short_date else
            f'<time datetime="{event["date"]}T{event["time"]}"></time>')
    return (f'<article class="event-card"><a href="{escape(event["url"])}">'
            f'<h3>{escape(event["title"])}</h3></a>{when}'
            f'<span class="venue">{escape(event.get("venue", ""))}</span>'
            '<p>Free companion / student €3; normal price must be checked.</p></article>')


def event():
    return parse_listing(reconstructed_card(CAPTURE['events'][0]), SOURCE)[0]


def offer(price=12, **extra):
    return dict({'@type':'Offer','price':price,'priceCurrency':'EUR','name':'Regular'},**extra)


def detail(e=None, offers=None, **extra):
    e = e or event()
    node = {'@type':'Event','name':e['title'],'url':e['url'],
            'startDate':e['date']+'T'+e['time']+':00+01:00',
            'location':{'@type':'Place','name':e['venue'] or 'Public Theatre',
                        'address':{'addressLocality':'Berlin'}},
            'offers':offers if offers is not None else [offer()]}
    node.update(extra)
    return '<script type="application/ld+json">'+json.dumps(node)+'</script>'


def observation(e=None, html=None):
    e = e or event()
    return match_detail(e, html or detail(e), e['url'], NOW.isoformat())


def gate(e=None, obs=None, now=NOW):
    e = e or event()
    return publication_gate(e, obs if obs is not None else observation(e), now, FIRST, LAST)


def test_captured_main_records_have_deterministic_card_identity_without_price_claims():
    records = CAPTURE['events']
    a = parse_listing(''.join(map(reconstructed_card, records)), SOURCE)
    b = parse_listing(''.join(map(reconstructed_card, reversed(records))), SOURCE)
    assert a == b and len(a) == len(records)
    assert a == sorted(a, key=sort_key)
    assert {identity(e) for e in a} == {identity(e) for e in records}
    assert all(e['price'] is None for e in a)


def test_abbreviated_date_inherits_year_only_from_the_explicit_source_window():
    e = CAPTURE['events'][0]
    rows = parse_listing(reconstructed_card(e, short_date=True), SOURCE)
    assert len(rows) == 1 and rows[0]['date'] == e['date']
    assert parse_listing(reconstructed_card(e, short_date=True), SOURCE.split('?')[0]) == []


def test_cards_cannot_borrow_another_cards_title_time_or_price():
    e, other = CAPTURE['events'][:2]
    broken = reconstructed_card(e).replace(f'<h3>{escape(e["title"])}</h3>', '')
    rows = parse_listing('<main>'+broken+reconstructed_card(other)+'</main>', SOURCE)
    assert [r['title'] for r in rows] == [other['title']]


def test_slug_navigation_challenge_and_listing_text_are_not_event_content():
    html = (FIXTURES/'raus_main_saved_challenge_2026-10-25.html').read_text()
    assert parse_listing(html, SOURCE) == []
    assert parse_listing('<a href="/events/invented-title/">Tickets</a>', SOURCE) == []
    assert parse_listing(reconstructed_card(CAPTURE['events'][0]), 'https://other.example/list') == []


def test_locale_duplicates_collapse_and_conflicting_titles_or_venues_fail_closed():
    a = event(); b = dict(a,url=a['url'].replace('/en/events/', '/events/'))
    assert stable_candidates([a,b]) == stable_candidates([b,a])
    assert len(stable_candidates([a,b])) == 1
    assert stable_candidates([a,dict(b,title='Different identity')]) == []
    assert stable_candidates([a,dict(b,venue='Other venue')]) == []


@pytest.mark.parametrize('mutation', ['date','time','title','venue','url','city','h1'])
def test_detail_identity_and_city_mismatches_cannot_verify(mutation):
    e = event()
    changes = {'date':{'startDate':'2026-10-26T10:00:00+01:00'},
               'time':{'startDate':'2026-10-25T11:00:00+01:00'},
               'title':{'name':'Different event'},'url':{'url':'https://rausgegangen.de/events/other/'},
               'venue':{'location':{'name':'Other hall','address':{'addressLocality':'Berlin'}}},
               'city':{'location':{'name':e['venue'],'address':{'addressLocality':'Hamburg'}}}}
    html = '<h1>Another event</h1>'+detail(e) if mutation == 'h1' else detail(e,**changes[mutation])
    assert observation(e,html)['matched'] is False


def test_missing_listing_venue_requires_exact_canonical_performance_and_detail_berlin_location():
    e = dict(event(),venue='')
    obs = observation(e)
    assert obs['matched'] and obs['match_basis'] == 'official_canonical_title_date_time'
    assert gate(e,obs)['venue'] == 'Public Theatre'


def test_regular_and_student_offers_are_kept_separate_and_listing_free_does_not_override():
    obs = observation(html=detail(offers=[offer(12),offer(3,name='Student')]))
    published = gate(obs=obs)
    assert published['price'] == published['price_max'] == 12
    assert not published['free_admission_confirmed']
    assert published['student_discount_status'] == 'explicit'
    assert published['student_offers'][0]['amount_eur'] == 3


@pytest.mark.parametrize('offers', [[],[offer(0,name='Student')],
    [offer(0,name='Free companion only')],[offer(0,priceCurrency='USD')],
    [offer(0,validThrough='2026-10-24T20:00:00+02:00')],
    [offer(0,priceValidUntil='2026-10-24')],
    [offer(0,eligibleCustomerType='Members')]])
def test_unproven_ordinary_admission_stays_unknown(offers):
    published = gate(obs=observation(html=detail(offers=offers)))
    assert published['price'] is None and published['price_status'] == 'unknown'
    assert published['free_admission_confirmed'] is False
    assert published['ticket_status'] == 'unknown'


def test_explicit_normal_free_and_range_are_supported():
    assert gate(obs=observation(html=detail(offers=[offer(0)])))['free_admission_confirmed']
    pub = gate(obs=observation(html=detail(offers=[{'@type':'AggregateOffer',
        'lowPrice':4,'highPrice':12,'priceCurrency':'EUR'}])))
    assert (pub['price_min'],pub['price_max'],pub['price_status']) == (4,12,'range')
    assert not pub['free_admission_confirmed']


def test_offer_order_is_deterministic_and_price_valid_until_includes_the_local_day():
    offers=[offer(18),offer(12),offer(3,name='Student')]
    assert observation(html=detail(offers=offers)) == observation(html=detail(offers=list(reversed(offers))))
    assert gate(obs=observation(html=detail(offers=[offer(0,priceValidUntil='2026-10-25')])))[
        'free_admission_confirmed']


def test_offer_expiration_between_observation_and_build_removes_free_and_inventory_claims():
    html=detail(offers=[offer(0,availability='https://schema.org/InStock',
                             validThrough=(NOW+timedelta(minutes=15)).isoformat())])
    obs=observation(html=html)
    assert gate(obs=obs)['free_admission_confirmed']
    final=gate(obs=obs,now=NOW+timedelta(minutes=30))
    assert final['price'] is None and final['ticket_status'] == 'unknown'
    assert not final['free_admission_confirmed']


@pytest.mark.parametrize('changes', [{'eventStatus':'https://schema.org/EventCancelled'},
    {'eventStatus':'https://schema.org/EventPostponed'},
    {'offers':[offer(12,availability='https://schema.org/SoldOut')]}])
def test_negative_structured_states_are_not_publishable(changes):
    assert gate(obs=observation(html=detail(**changes))) is None


def test_multi_performance_prices_and_status_do_not_contaminate_current_performance():
    e = event()
    current = detail(e,offers=[offer(12)])
    other = detail(e,offers=[offer(0,availability='https://schema.org/SoldOut')],
                   startDate='2026-10-26T10:00:00+01:00')
    pub = gate(obs=observation(e,current+other))
    assert pub['price'] == 12 and pub['ticket_status'] == 'unknown'
    assert observation(e,current+detail(e,offers=[offer(0)]))['outcome'] == 'conflicting_structured_events'


def test_unknown_unmatched_expired_future_observations_and_past_events_cannot_publish():
    e = event(); obs = observation(e)
    assert publication_gate(e,None,NOW,FIRST,LAST) is None
    assert gate(obs=dict(obs,matched=False)) is None
    assert gate(obs=dict(obs,observed_at=(NOW-timedelta(hours=7)).isoformat())) is None
    assert gate(obs=dict(obs,observed_at=(NOW+timedelta(seconds=1)).isoformat())) is None
    assert gate(now=NOW+timedelta(hours=2)) is None  # Already started.
    assert gate(obs=dict(obs,regular_offers=[dict(obs['regular_offers'][0],amount_eur=30,price_max=30)])) is None


def test_utc_detail_time_is_converted_to_berlin_before_matching():
    e = event()
    assert observation(e,detail(e,startDate='2026-10-25T09:00:00Z'))['matched']


class Documents:
    reason = 'fixture'
    def __init__(self,docs):self.docs=docs;self.calls=[]
    def fetch(self,url):
        self.calls.append(url)
        return self.docs.get(url)


def test_production_direct_pipeline_verifies_every_published_row_and_reuses_staging_matcher():
    e = event()
    h = Documents({SOURCE:(SOURCE,reconstructed_card(CAPTURE['events'][0])),e['url']:(e['url'],detail(e))})
    rows,diagnostic = direct_pipeline(SOURCE,NOW,FIRST,LAST,http=h)
    assert len(rows) == diagnostic['exact_matches'] == diagnostic['publishable'] == 1
    assert rows[0]['verification_status'] == 'verified' and len(h.calls) == 2
    assert sample_one(e,h,NOW.isoformat())['regular_offers'] == diagnostic['observations'][0]['regular_offers']
    unverified,diag = direct_pipeline(SOURCE,NOW,FIRST,LAST,http=Documents(h.docs),max_details=0)
    assert not unverified and diag['candidates'] == 1


def test_direct_pipeline_cannot_exceed_six_details_and_reversed_listing_order_is_stable():
    raw = CAPTURE['events']; html = ''.join(map(reconstructed_card,raw))
    docs = {SOURCE:(SOURCE,html)}
    for candidate in parse_listing(html,SOURCE):
        docs[candidate['url']] = (candidate['url'],detail(candidate))
    a,diag = direct_pipeline(SOURCE,NOW,FIRST,LAST,http=Documents(docs),max_details=100)
    docs[SOURCE] = (SOURCE,''.join(map(reconstructed_card,reversed(raw))))
    b,other = direct_pipeline(SOURCE,NOW,FIRST,LAST,http=Documents(docs),max_details=100)
    assert a == b and diag['attempted_details'] == other['attempted_details'] == 6


def test_generic_listing_path_never_escalates_to_legacy_jina_or_browser(monkeypatch):
    monkeypatch.setattr(generic,'fetch_plain',lambda url:None)
    def forbidden(*args,**kwargs):raise AssertionError('Legacy fallback reached')
    monkeypatch.setattr(generic,'fetch_jina_html',forbidden)
    monkeypatch.setattr(generic,'render_with_cloakbrowser',forbidden)
    assert generic.scrape(SOURCE) == []


def test_generic_recovery_cannot_republish_unverified_raus_or_repeat_denied_host_requests():
    from scripts.recover_failed import recover_site,extract_from_detail_page
    def forbidden(*args,**kwargs):raise AssertionError('Unbounded Raus recovery reached')
    assert recover_site({'url':SOURCE},7,20,fetch=forbidden) == []
    assert extract_from_detail_page(event()['url'],fetch=forbidden) == []


def test_scoring_cannot_resurrect_unverified_free_or_student_only_admission():
    from scripts.score_events import score_and_filter_events
    e = event()
    obs = observation(e,detail(e,offers=[offer(0,name='Student')]))
    accepted = gate(e,obs)
    scored = score_and_filter_events([accepted],today=FIRST)
    assert len(scored) == 1
    # Shared legacy enrichment can inspect promotional text; the final gate
    # must reapply the occurrence-bound evidence after that shared step.
    final = gate(scored[0],obs)
    assert final['price'] is None and not final['free_admission_confirmed']


def test_empty_url_candidates_do_not_imply_positive_source_coverage():
    docs = Documents({SOURCE:(SOURCE,'<a href="/events/url-only/">Tickets</a>')})
    rows,d = direct_pipeline(SOURCE,NOW,FIRST,LAST,http=docs)
    assert not rows and d['candidate_url_discovery_success']
    assert d['candidate_urls'] == 1 and not d['listing_discovery_success']
    assert d['exact_match_rate'] is None and not d['verified_source_presence']


class FrozenDateTime(datetime):
    @classmethod
    def now(cls,tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class BoundedFixtureHTTP:
    """Bounded transport stand-in; all document content is synthetic/replayed."""
    def __init__(self,limit,deadline,byte_limit=0,**kwargs):
        self.limit=limit;self.requests=0;self.bytes=0;self.calls=[]
        self.robots={};self.robot_evidence={};self.aliases={};self.blocked=set();self.documents={}
        self.reason='fixture'
    def fetch(self,url):
        if url in self.documents:return self.documents[url]
        if self.requests >= self.limit:return None
        e=event()
        html = reconstructed_card(CAPTURE['events'][0]) if url == SOURCE else detail(e) if url == e['url'] else None
        self.requests+=1;self.calls.append({'url':url,'http_status':200 if html else 404})
        if html is None:return None
        self.bytes+=len(html.encode());self.documents[url]=(url,html)
        return self.documents[url]
    def plain(self,url,**kwargs):
        doc=self.fetch(url)
        return doc[1] if doc else None


def test_production_cli_applies_gates_after_shared_normalization_without_refetching_snapshot(monkeypatch,tmp_path):
    import sys
    import scripts.raus_html as raus
    h=BoundedFixtureHTTP(10,0)
    monkeypatch.setattr(raus,'direct_http',lambda:h)
    monkeypatch.setattr(generic,'datetime',FrozenDateTime)
    monkeypatch.setattr(generic,'scrape_window',lambda days:(FIRST,LAST))
    output=tmp_path/'raw.json';snapshot=tmp_path/'snapshot.html'
    monkeypatch.setattr(sys,'argv',['scraper','--url',SOURCE,'--output',str(output),
        '--save-html','--html-output',str(snapshot)])
    assert generic.main() == 0
    result=json.loads(output.read_text())
    assert result['event_count'] == result['raus_qualification']['publishable'] == 1
    assert result['events'][0]['price'] == 12
    assert result['events'][0]['verification_status'] == 'verified'
    assert h.requests == 2 and 'event-card' in snapshot.read_text()


def test_full_review_builder_reuses_parser_matcher_scoring_and_checksum_manifest(monkeypatch,tmp_path):
    import hashlib
    import sys
    import scripts.qualify_restored_branch as review
    class InlinePool:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def map(self,fn,tasks):return map(fn,tasks)
    catalog={'jobs':{'scrape':{'strategy':{'matrix':{'include':[
        {'name':'rausgegangen_de','url':SOURCE}]}}}}}
    monkeypatch.setattr(review,'datetime',FrozenDateTime)
    monkeypatch.setattr(review,'HTTP',BoundedFixtureHTTP)
    monkeypatch.setattr(review,'ProcessPoolExecutor',InlinePool)
    monkeypatch.setattr(review.yaml,'safe_load',lambda text:catalog)
    # listing_worker mutates these process-local functions in production.
    for name in ('fetch_plain','fetch_jina_html','render_with_cloakbrowser'):
        monkeypatch.setattr(generic,name,getattr(generic,name))
    output=tmp_path/'review'
    monkeypatch.setattr(sys,'argv',['review','--output',str(output)])
    review.main()
    payload=json.loads((output/'site/events_scored.json').read_text())
    assert payload['count'] == 1
    row=payload['events'][0]
    assert row['price'] == 12 and row['verification_status'] == 'verified'
    assert '_qualification_free_proven' not in row and '/events/' in row['url']
    manifest=json.loads((output/'site-manifest.json').read_text())
    for name,checksum in manifest['files'].items():
        assert hashlib.sha256((output/'site'/name).read_bytes()).hexdigest() == checksum
    report=json.loads((output/'results.json').read_text())
    assert report['production_data_unchanged']
    assert report['raus_publication']['exact_publication_coverage'] == 1.0


def test_raus_only_workflow_scope_cannot_deploy_even_with_publish_input():
    import yaml
    workflow=yaml.safe_load((Path(__file__).parents[1]/'.github/workflows/fetch-strategy-probe.yml').read_text())
    assert workflow['permissions'] == {'contents':'read'}
    assert "inputs.scope != 'raus_direct'" in workflow['jobs']['deploy']['if']


def test_main_style_transport_preserves_session_but_not_a_false_crawler_identity_and_caches_403(monkeypatch):
    import time
    import scripts.qualify_restored_branch as transport
    monkeypatch.setattr(transport,'public',lambda url:True)
    class Response:
        headers={'Content-Type':'text/plain'}
        def __init__(self,robots):self.status_code=200 if robots else 403
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,n):yield b'User-agent: *\nDisallow:\n'
    class Cookies:
        def clear(self):raise AssertionError('Raus session cookies discarded')
    class Session:
        cookies=Cookies()
        def __init__(self):self.calls=[]
        def get(self,url,**kwargs):
            self.calls.append((url,kwargs))
            return Response(url.endswith('/robots.txt'))
    http=transport.HTTP(10,time.monotonic()+120,browser_headers=True,preserve_cookies=True)
    http.session=Session()
    assert http.fetch(SOURCE) is None
    assert http.fetch(event()['url']) is None
    assert http.reason == 'host_blocked_cached' and http.requests == 2
    for url,kwargs in http.session.calls:
        assert kwargs['headers']['User-Agent'] == transport.AGENT
        assert kwargs['headers']['Accept-Language'].startswith('de-DE')
        assert kwargs['timeout'] == (8,12) and kwargs['allow_redirects'] is False
