#!/usr/bin/env python3
"""Strict pilot candidate policy and offline, digest-pinned promotion gate."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.build_page_dataset import build, fresh
from scripts.event_matching import host, event_url
from scripts.ticket_evidence import occurrence_id, folded
from scripts.verify_event_details import utc, DEFAULT_POLICY
from scripts.tinyfish_client import public_url

ROOT=Path(__file__).resolve().parents[1]
PROFILE=json.loads((ROOT/'config/pilot_release.json').read_text())


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_name(event):
    url=event.get('source_url','')
    for name,base in PROFILE['sources'].items():
        if url.rstrip('/')==base.rstrip('/'): return name
    raise ValueError('Source outside pilot allowlist')


def future(event,now):
    now=utc(now);local=now.astimezone(ZoneInfo('Europe/Berlin'))
    try:
        day=datetime.strptime(event['date'],'%Y-%m-%d').date()
        clock=datetime.strptime(event['time'],'%H:%M').time()
    except (KeyError,ValueError,TypeError): return False
    start=datetime.combine(day,clock,tzinfo=ZoneInfo('Europe/Berlin'))
    return local<start and day<=local.date()+timedelta(days=PROFILE['window_days'])


def assert_location(event,now):
    evidence=event.get('pilot_location',{})
    assert evidence.get('city')=='Berlin' and event.get('venue'), 'Missing Berlin venue evidence'
    assert folded(evidence.get('venue',''))==folded(event['venue']), 'Venue evidence mismatch'
    assert fresh(evidence.get('observed_at'),utc(now),PROFILE['max_age_hours']), 'Stale location evidence'
    name=source_name(event)
    assert host(evidence.get('evidence_url',''))==host(PROFILE['sources'][name]), 'Wrong location evidence source'
    assert re.search(r'\b\d{5}\s+Berlin\b',evidence.get('address','')), 'Missing postal Berlin address'
    if name=='ufafabrik':
        assert evidence.get('evidence_url')==PROFILE['ufa_campus_url'], 'Wrong campus URL'
        assert event['venue'] in PROFILE['ufa_campus_venues'], 'Unknown campus room'
    else:
        assert event_url(evidence.get('evidence_url',''))==event_url(event['url']), 'Wrong event location URL'


def assert_event(event,now):
    name=source_name(event)
    assert future(event,now), 'Occurrence outside future window'
    assert fresh(event.get('observed_at'),utc(now),PROFILE['max_age_hours']), 'Stale discovery'
    url=event.get('url','');parsed=urlsplit(url)
    pattern=r'/de/spielplan/[^/]+/events/\d+/?' if name=='berlin_buehnen' else r'/veranstaltung/\d+/[^/]+/?'
    assert parsed.scheme=='https' and public_url(url,resolve=False) and not parsed.query and not parsed.fragment, 'Unsafe detail URL'
    assert host(url)==host(PROFILE['sources'][name]) and re.fullmatch(pattern,parsed.path), 'Wrong detail URL'
    assert_location(event,now)


def candidate(data,overlay,now):
    """Restrict inputs before shared normalization/scoring/build, then gate output."""
    now=utc(now)
    assert fresh(data.get('generated_at'),now,PROFILE['max_age_hours']), 'Stale discovery batch'
    eligible=[];rejected=[]
    for original in data['events']:
        e=deepcopy(original)
        # A foreign source is a configuration failure, not silent filtering.
        source_name(e)
        try:
            assert_event(e,now)
            entry=overlay.get('events',{}).get(occurrence_id(e),{})
            fields=entry.get('fields',{})
            link=fields.get('link',{})
            assert entry.get('outcome')=='matched' and fresh(link.get('observed_at'),now,PROFILE['max_age_hours']), 'No fresh exact match'
            assert link.get('match_basis')=='title_occurrence_venue', 'Pilot requires known matching venue'
            assert event_url(link.get('values',{}).get('url',''))==event_url(e['url']), 'Verified URL mismatch'
            assert fields.get('event_status',{}).get('values',{}).get('event_status') not in ('cancelled','postponed'), 'Cancelled/postponed occurrence'
            e['listing_ticket_status']=e.get('ticket_status','unknown')
            # No listing/body inference may silently recreate unsupported claims.
            e.update(claims_policy='verified_overlay_only',price=None,price_min=None,price_max=None,
                     price_status='unknown',price_label='Check site',offers=[],student_discount_status='unknown',
                     free_admission_confirmed=False,ticket_status='unknown',event_status='unknown')
            for group in ('price','discount','event_status'):
                record=fields.get(group,{})
                if fresh(record.get('observed_at'),now,min(PROFILE['max_age_hours'],DEFAULT_POLICY['ttl_hours'][group])):
                    e.update(record.get('values',{}))
            eligible.append(e)
        except AssertionError as error:
            rejected.append({'event_id':occurrence_id(e),'source':source_name(e),'reason':str(error)})
    site=build(dict(generated_at=data['generated_at'],events=eligible),overlay,now)
    for event in site['events']:
        if event.get('listing_ticket_status')=='sold_out' and fresh(event.get('observed_at'),now,PROFILE['max_age_hours']):
            # A detail page's silence cannot erase an exact fresh card warning.
            event['ticket_status']='sold_out'
            event.setdefault('field_observed_at',{})['status']=event['observed_at']
            event.setdefault('evidence',{})['status']=dict(source='fresh_exact_listing_card',observed_at=event['observed_at'],evidence_url=event['source_url'])
        assert_event(event,now)
        assert event['detail_link_status']=='verified' and event['verification_outcome']=='matched'
        assert fresh(event.get('field_observed_at',{}).get('link'),now,PROFILE['max_age_hours'])
        for field,group in [('ticket_status','status'),('event_status','event_status')]:
            if event.get(field,'unknown')!='unknown':
                assert fresh(event.get('field_observed_at',{}).get(group),now,PROFILE['max_age_hours']), 'Unsupported status'
        if event.get('price') is not None:
            assert fresh(event.get('field_observed_at',{}).get('price'),now,PROFILE['max_age_hours']), 'Unsupported price'
    expires=min([now+timedelta(hours=PROFILE['max_age_hours'])]+[datetime.combine(datetime.strptime(e['date'],'%Y-%m-%d').date(),datetime.strptime(e['time'],'%H:%M').time(),tzinfo=ZoneInfo('Europe/Berlin')).astimezone(timezone.utc) for e in site['events']])
    site.update(release_profile=PROFILE['id'],release_expires_at=expires.isoformat())
    for event in site['events']: event['claim_expires_at']=expires.isoformat()
    from scripts.community_events import decision
    for event in site['events']:
        event['community_eligible'],event['community_reason']=decision(event,now)
    counts=Counter(source_name(e) for e in site['events'])
    dates={name:sorted({e['date'] for e in site['events'] if source_name(e)==name}) for name in PROFILE['sources']}
    ready=all(counts[name]>=PROFILE['minimum_events_per_source'] and len(dates[name])>=PROFILE['minimum_dates_per_source'] for name in PROFILE['sources'])
    quality={'discovered_occurrences':len(data['events']),'verified_eligible':len(eligible),
             'published_occurrences':site['count'],'published_exact_matches':site['count'],
             'exact_publication_coverage':1.0 if site['count'] else 0.0,
             'discovery_to_publication_rate':site['count']/len(data['events']) if data['events'] else 0.0,
             'source_counts':{name:counts[name] for name in PROFILE['sources']},'source_dates':dates,
             'unknown_prices':sum(e.get('price') is None for e in site['events']),
             'explicit_student_discounts':sum(e.get('student_discount_status')=='explicit' for e in site['events']),
             'unknown_inventory':sum(e.get('ticket_status')=='unknown' for e in site['events']),
             'rejected':rejected,'scoring_exclusions':len(eligible)-site['count'],'technical_go':ready}
    return site,quality


def seal(root,commit,now,run_id,quality):
    root=Path(root);now=utc(now)
    dataset=json.loads((root/'site/events_scored.json').read_text())
    expires=min([now+timedelta(hours=PROFILE['max_age_hours'])]+[datetime.combine(datetime.strptime(e['date'],'%Y-%m-%d').date(),datetime.strptime(e['time'],'%H:%M').time(),tzinfo=ZoneInfo('Europe/Berlin')).astimezone(timezone.utc) for e in dataset['events']])
    files={p.relative_to(root).as_posix():digest(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='release-manifest.json'}
    manifest={'version':1,'profile':PROFILE['id'],'profile_sha256':digest(ROOT/'config/pilot_release.json'),
              'commit_sha':commit,'workflow_run_id':str(run_id),'created_at':now.isoformat(),
              'expires_at':expires.isoformat(),
              'quality':quality,'files':files,'authorization_to_release':False}
    (root/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


def validate(root,expected_digest,expected_commit,expected_run,now):
    root=Path(root);path=root/'release-manifest.json'
    assert re.fullmatch(r'[a-f0-9]{64}',expected_digest or '') and digest(path)==expected_digest, 'Manifest digest mismatch'
    manifest=json.loads(path.read_text());now=utc(now)
    assert manifest['version']==1 and manifest['profile']==PROFILE['id'], 'Wrong release profile'
    assert manifest['profile_sha256']==digest(ROOT/'config/pilot_release.json'), 'Profile drift'
    assert manifest['commit_sha']==expected_commit and re.fullmatch(r'[a-f0-9]{40}',expected_commit), 'Commit mismatch'
    assert manifest['workflow_run_id']==str(expected_run) and str(expected_run).isdigit(), 'Run mismatch'
    assert fresh(manifest['created_at'],now,PROFILE['max_age_hours']) and now<utc(manifest['expires_at'])<=utc(manifest['created_at'])+timedelta(hours=PROFILE['max_age_hours']), 'Expired candidate'
    assert manifest['authorization_to_release'] is False, 'Manifest is evidence, not authorization'
    files=manifest['files']
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p!=path}
    assert not any(p.is_symlink() for p in root.rglob('*')), 'Symlink in artifact'
    assert set(files)==actual and {'site/index.html','site/events_scored.json','site/.nojekyll','discovery.json','overlay.json','smoke/report.json'}<=actual, 'Missing or unexpected artifact file'
    for name,sha in files.items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts and digest(root/name)==sha, 'Artifact checksum mismatch'
    data=json.loads((root/'discovery.json').read_text());overlay=json.loads((root/'overlay.json').read_text())
    # Rebuild using original build timestamp for reproducibility, then check freshness now.
    site,quality=candidate(data,overlay,manifest['created_at'])
    assert json.loads((root/'site/events_scored.json').read_text())==site, 'Dataset differs from reproducible build'
    assert (root/'site/index.html').read_bytes()==(ROOT/'web/index.html').read_bytes(), 'Frontend drift'
    assert manifest['quality']==quality and quality['technical_go'], 'Qualification mismatch/NO-GO'
    smoke=json.loads((root/'smoke/report.json').read_text())
    assert smoke.get('search')=='passed' and smoke.get('ics_export')=='passed' and smoke.get('responsive_render')=='passed' and smoke.get('page_errors')==[] and smoke.get('categories')=='passed' and smoke.get('pilot_expiry')=='passed', 'Frontend qualification missing'
    for event in site['events']:
        assert_event(event,now)
        for stamp in event.get('field_observed_at',{}).values():
            assert fresh(stamp,now,PROFILE['max_age_hours']), 'Expired claim'
    from scripts.community_events import newsletter
    assert json.loads((root/'site/newsletter.json').read_text())==newsletter(site['events'],manifest['created_at']), 'Newsletter differs from validated occurrences'
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--artifact',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--commit',required=True);p.add_argument('--run-id',required=True)
    a=p.parse_args();validate(a.artifact,a.manifest_sha256,a.commit,a.run_id,datetime.now(timezone.utc));print('Pilot manifest, source isolation, freshness and checksums validated')
