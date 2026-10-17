from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import yaml
from scripts.qualify_r12 import integration, safe_artifact, choose_sample
from scripts.ticket_evidence import enrich_evidence
from scripts.verify_event_details import DEFAULT_POLICY


def test_staging_workflow_has_no_production_authority():
    doc=yaml.safe_load(Path('.github/workflows/fetch-strategy-probe.yml').read_text())
    trigger=doc.get('on',doc.get(True))
    assert set(trigger)=={'workflow_dispatch'}
    assert doc['permissions']=={'contents':'read'}
    for job in doc['jobs'].values():
        assert 'environment' not in job and 'permissions' not in job
        for step in job['steps']:
            assert not any(x in step.get('uses','') for x in ('deploy-pages','upload-pages','configure-pages'))
            assert not any(x in step.get('run','') for x in ('git push','git commit','gh workflow','gh api'))
    assert 'runner.temp' in doc['jobs']['qualify']['steps'][-1]['with']['path']


def test_production_jobs_fail_closed_without_activation_flags():
    daily=yaml.safe_load(Path('.github/workflows/daily-event-verification.yml').read_text())
    condition=daily['jobs']['verify-build-publish']['if']
    assert "vars.DAILY_VERIFICATION_ENABLED == 'true'" in condition
    assert "vars.PAGES_DEPLOYMENT_ENABLED == 'true'" in condition
    manual=yaml.safe_load(Path('.github/workflows/jekyll-gh-pages.yml').read_text())
    for job in manual['jobs'].values():
        assert "github.event_name == 'workflow_dispatch'" in job['if']
        assert "vars.PAGES_DEPLOYMENT_ENABLED == 'true'" in job['if']
    weekly=yaml.safe_load(Path('.github/workflows/weekly-event-scraper.yml').read_text())
    assert "vars.PAGES_DEPLOYMENT_ENABLED == 'true'" in weekly['jobs']['publish-pages']['if']


def test_diagnostics_drop_query_credentials_and_key(monkeypatch):
    monkeypatch.setenv('TINYFISH_API_KEY','fixture-key')
    output=safe_artifact({'url':'https://user:pass@example.org/event?token=secret#fragment','nested':['fixture-key']})
    assert output=={'url':'https://example.org/event','nested':['[REDACTED]']}


def test_actual_pipeline_with_real_semantic_responses_and_second_run(tmp_path):
    targets=json.loads(Path('config/tinyfish_qualification_targets.json').read_text())
    documents={}
    for name in ('berlin_buehnen','ufafabrik'):
        result=json.loads(Path(f'tests/fixtures/tinyfish_live/{name}_fetch.json').read_text())['results'][0]
        documents[result['url']]=(result['final_url'],result['text'])
    class HTTP:
        requests=bytes=0;permitted=True;reason='ok'
        def __init__(self): self.documents=documents
        def fetch(self,url): self.requests+=1;return self.documents[url]
    class Provider:
        fetch_urls=search_queries=0;diagnostic='offline_fixture';documents={}
        def fetch(self,urls): raise AssertionError('No provider transport in offline test')
        def search(self,query): raise AssertionError('No provider transport in offline test')
    sample=[enrich_evidence(e) for e in targets];original=deepcopy(sample)
    overlay,second,site,expired,checks=integration(sample,datetime(2026,10,17,20,tzinfo=timezone.utc),DEFAULT_POLICY,HTTP(),Provider(),tmp_path/'overlay.json')
    assert len(overlay['events'])==2 and overlay==second and original==sample
    assert all(e['outcome']=='matched' for e in overlay['events'].values())
    assert checks['fresh_second_run_preserved_state'] and checks['ttl_expiration_passed'] and checks['disk_overlay_roundtrip']
    assert checks['multi_performance_pages'][0]['contains_cancellation_marker']
    assert checks['multi_performance_pages'][0]['selected_event_status']=='unknown'
    assert all(r['matched'] for r in checks['missing_venue_replays'])
    assert all(e['ticket_status']=='unknown' for e in expired['events'])

def test_missing_venue_accepts_official_www_redirect_with_exact_occurrence():
    from scripts.event_matching import match_basis
    event={'title':'A real show','date':'2026-10-19','time':'19:00','venue':'',
           'url':'https://ufafabrik.de/veranstaltung/123/show','source_url':'https://ufafabrik.de/spielplan.html'}
    final='https://www.ufafabrik.de/veranstaltung/123/show'
    candidate=dict(event,url=final,venue='Theatersaal')
    assert match_basis(event,candidate,final)=='official_canonical_occurrence'
    assert match_basis(event,dict(candidate,date='2026-10-20'),final) is None
    assert match_basis(event,candidate,'https://www.ufafabrik.de/veranstaltung/124/other') is None
    assert match_basis(event,candidate,'https://unrelated.example/veranstaltung/123/show') is None

def test_raus_semantic_detail_discovery_requires_fetched_title_and_occurrence():
    from scripts.generic_event_scraper import scrape_document
    html='<main><h1>A real Berlin event</h1><p>18.10.2026 19:00</p><h2>Location</h2><p>Berlin Venue</p><p>Eintritt €12</p></main>'
    es=scrape_document(html,'https://rausgegangen.de/events/a-real-event/','offline test')
    assert es[0]['title']=='A real Berlin event' and es[0]['date']=='2026-10-18'
    assert es[0]['venue']=='Berlin Venue'
    # A bleached listing with only dates/venues cannot fabricate an event title.
    assert scrape_document('<p>18.10.2026 19:00 Berlin Venue €12</p>','https://rausgegangen.de/en/berlin/eventsbydate/','offline test')==[]

def test_search_discovery_rejects_lookalike_hosts_and_snippet_facts():
    from scripts.qualify_r12 import discover
    good='https://rausgegangen.de/events/a-real-event/'
    bad='https://rausgegangen.de.unrelated.example/events/a-real-event/'
    html='<main><h1>A real Berlin event</h1><p>18.10.2026 19:00</p><h2>Location</h2><p>Berlin Venue</p><p>Eintritt €12</p></main>'
    class HTTP:
        permitted=True;reason='ok';bytes=0;policy=DEFAULT_POLICY
        def __init__(self): self.urls=[]
        def fetch(self,url): self.urls.append(url);return url,html
    class Provider:
        def search(self,query): return [bad,good]
        def fetch(self,urls): raise AssertionError('Direct content should suffice')
    http=HTTP()
    sample,sources=discover(datetime(2026,10,17,20,tzinfo=timezone.utc),http,Provider(),'raus-search')
    assert http.urls==[good] and len(sample)==1
    assert sample[0]['title']=='A real Berlin event' and sample[0]['price']==12
