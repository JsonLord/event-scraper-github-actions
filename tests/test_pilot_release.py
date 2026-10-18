from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
import yaml
from scripts.pilot_release import candidate, PROFILE, ROOT, seal, validate, digest
from scripts.ticket_evidence import occurrence_id
from scripts.qualify_r14 import location
from scripts.verify_event_details import observation

NOW=datetime(2026,10,17,20,tzinfo=timezone.utc)


def fixtures():
    events=[];overlay={'events':{}}
    targets=json.loads((ROOT/'config/tinyfish_qualification_targets.json').read_text())
    for name,event in zip(('berlin_buehnen','ufafabrik'),targets):
        e=deepcopy(event);e.update(observed_at=NOW.isoformat(),claims_policy='verified_overlay_only')
        body=json.loads((ROOT/f'tests/fixtures/tinyfish_live/{name}_fetch.json').read_text())['results'][0]
        fields=observation(e,body['text'],body['final_url'],NOW.isoformat())
        assert fields
        campus=('https://ufafabrik.de/','<footer>Viktoriastraße 10, 12105 Berlin</footer>')
        e['pilot_location']=location(e,(body['final_url'],body['text']),campus,NOW)
        assert e['pilot_location']
        events.append(e);overlay['events'][occurrence_id(e)]={'outcome':'matched','checked_at':NOW.isoformat(),'fields':fields}
    return {'generated_at':NOW.isoformat(),'events':events},overlay


def test_pilot_actual_matcher_and_shared_builder_preserve_known_and_unknown():
    data,overlay=fixtures();before=deepcopy((data,overlay))
    site,quality=candidate(data,overlay,NOW)
    assert len(site['events'])==2 and quality['exact_publication_coverage']==1
    assert not quality['technical_go'] # One date per source is insufficient.
    assert (data,overlay)==before
    assert all(e['ticket_status']=='unknown' and e['venue'] for e in site['events'])
    assert any(e['student_discount_status']=='explicit' for e in site['events'])


@pytest.mark.parametrize('change',[
    {'source_url':'https://rausgegangen.de/events/'},
    {'source_url':'https://www.berlin-buehnen.de.evil.example/de/spielplan'},
])
def test_pilot_foreign_source_is_configuration_failure(change):
    data,overlay=fixtures();data['events'][0].update(change)
    with pytest.raises(ValueError): candidate(data,overlay,NOW)


def test_pilot_rejects_historical_discovery_and_future_stamps():
    data,overlay=fixtures()
    for stamp in ('2026-10-11T12:00:00Z',(NOW+timedelta(minutes=1)).isoformat()):
        data['generated_at']=stamp
        with pytest.raises(AssertionError): candidate(data,overlay,NOW)


@pytest.mark.parametrize('change',[{'date':'2026-10-16'},{'date':'2026-10-26'}, {'venue':'Wrong hall'}, {'time':''}])
def test_pilot_rejects_wrong_occurrence_or_location(change):
    data,overlay=fixtures();data['events'][0].update(change)
    site,quality=candidate(data,overlay,NOW)
    assert len(site['events'])==1 and quality['rejected']


def test_stale_status_and_unsupported_body_claims_cannot_reappear():
    data,overlay=fixtures();e=data['events'][0]
    e.update(description='Free admission. Sold out. Student tickets €1.',price=0,offers=[],ticket_status='sold_out')
    entry=overlay['events'][occurrence_id(e)]
    entry['fields'].pop('price',None);entry['fields'].pop('discount',None)
    entry['fields']['status']={'values':{'ticket_status':'available'},'observed_at':(NOW-timedelta(hours=13)).isoformat()}
    site,_=candidate(data,overlay,NOW)
    row=next(x for x in site['events'] if x['source_url']==e['source_url'])
    assert row['price'] is None and row['ticket_status']=='unknown' and row['student_discount_status']=='unknown'
    assert not row['free_admission_confirmed']


def artifact(tmp_path,monkeypatch):
    data,overlay=fixtures()
    # Lower only sample size in this offline gate fixture; live profile requires 2x2.
    monkeypatch.setitem(PROFILE,'minimum_events_per_source',1)
    monkeypatch.setitem(PROFILE,'minimum_dates_per_source',1)
    site,quality=candidate(data,overlay,NOW)
    assert quality['technical_go']
    (tmp_path/'site').mkdir();(tmp_path/'smoke').mkdir()
    for name,payload in [('discovery.json',data),('overlay.json',overlay),('site/events_scored.json',site),('smoke/report.json',dict(search='passed',ics_export='passed',responsive_render='passed',page_errors=[]))]:
        (tmp_path/name).write_text(json.dumps(payload))
    (tmp_path/'site/index.html').write_bytes((ROOT/'web/index.html').read_bytes());(tmp_path/'site/.nojekyll').touch()
    seal(tmp_path,'a'*40,NOW,'123',quality)
    return digest(tmp_path/'release-manifest.json')


def test_pinned_manifest_rebuilds_exact_artifact(tmp_path,monkeypatch):
    sha=artifact(tmp_path,monkeypatch)
    assert validate(tmp_path,sha,'a'*40,'123',NOW)['quality']['exact_publication_coverage']==1


@pytest.mark.parametrize('failure',['missing_manifest','digest','commit','run','expired','tampered','extra','symlink','profile','false_go'])
def test_manifest_gate_fails_closed(tmp_path,monkeypatch,failure):
    sha=artifact(tmp_path,monkeypatch);commit='a'*40;run='123';now=NOW
    if failure=='missing_manifest': (tmp_path/'release-manifest.json').unlink()
    if failure=='digest': sha='0'*64
    if failure=='commit': commit='b'*40
    if failure=='run': run='999'
    if failure=='expired': now=NOW+timedelta(hours=6)
    if failure=='tampered': (tmp_path/'site/events_scored.json').write_text('{}')
    if failure=='extra': (tmp_path/'site/other.json').write_text('{}')
    if failure=='symlink': (tmp_path/'site/link').symlink_to(tmp_path/'discovery.json')
    if failure in ('profile','false_go'):
        p=tmp_path/'release-manifest.json';m=json.loads(p.read_text())
        if failure=='profile': m['profile']='unrestricted'
        else: m['quality']['technical_go']=False
        p.write_text(json.dumps(m));sha=digest(p)
    with pytest.raises((AssertionError,FileNotFoundError)):
        validate(tmp_path,sha,commit,run,now)


def test_every_legacy_write_or_publish_job_is_isolated_from_pilot():
    for filename in ('weekly-event-scraper.yml','daily-event-verification.yml'):
        workflow=yaml.safe_load((ROOT/'.github/workflows'/filename).read_text())
        for job in workflow['jobs'].values():
            assert "vars.RELEASE_PROFILE == 'unrestricted'" in job['if']
            assert "vars.UNRESTRICTED_PUBLICATION_ENABLED == 'true'" in job['if']
    workflow=yaml.safe_load((ROOT/'.github/workflows/jekyll-gh-pages.yml').read_text())
    assert set(workflow.get('on',workflow.get(True)))=={'workflow_dispatch'}
    for job in workflow['jobs'].values():
        assert "vars.RELEASE_PROFILE == 'berlin-ufa-pilot-v1'" in job['if']
    build=workflow['jobs']['build']['steps']
    assert any('scripts/pilot_release.py' in s.get('run','') for s in build)
    assert not any('build_page_dataset.py' in s.get('run','') for s in build)
