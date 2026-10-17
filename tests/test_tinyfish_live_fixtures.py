"""Real sanitized Fetch captures from the one 2+2 qualification, not live tests."""
import json
from pathlib import Path
from scripts.verify_event_details import observation

ROOT=Path('tests/fixtures/tinyfish_live')
TARGETS=json.loads(Path('config/tinyfish_qualification_targets.json').read_text())
NOW='2026-10-17T20:07:48Z'


def test_real_ufa_semantic_response_retains_occurrence_prices_and_venue():
    payload=json.loads((ROOT/'ufafabrik_fetch.json').read_text())
    result=payload['results'][0]
    assert payload['errors']==[] and result['format']=='html'
    assert 'datetime=' not in result['text'] and '<script' not in result['text']
    obs=observation(TARGETS[1],result['text'],result['final_url'],NOW)
    assert obs['link']['match_basis']=='title_occurrence_venue'
    assert obs['price']['values']['price_min']==12
    assert obs['price']['values']['price_max']==26
    assert obs['discount']['values']['student_discount_status']=='explicit'
    assert [o['kind'] for o in obs['discount']['values']['offers']]==['regular','reduced','student']
    assert 'status' not in obs  # Karten kaufen is not inventory evidence.


def test_real_ufa_title_date_venue_and_url_mutations_fail_closed():
    r=json.loads((ROOT/'ufafabrik_fetch.json').read_text())['results'][0]
    for field,value in [('title','Another show'),('date','2026-10-19'),('time','21:00'),('venue','Another venue')]:
        assert observation(dict(TARGETS[1],**{field:value}),r['text'],r['final_url'],NOW) is None
    assert observation(TARGETS[1],r['text'],'https://ufafabrik.de/spielplan.html',NOW) is None


def test_recorded_provider_qualification_counts_and_schema():
    report=json.loads((ROOT/'qualification_report.json').read_text())
    assert (report['fetch_urls'],report['search_requests'])==(2,2)
    assert [c['operation'] for c in report['provider_calls']]==['search','fetch','search','fetch']
    assert all(c['http_status']==200 and c['schema_valid'] for c in report['provider_calls'])
    assert all(c['duration_seconds']>0 for c in report['provider_calls'])

def test_real_berlin_selected_performance_excludes_other_cancellation():
    r=json.loads((ROOT/'berlin_buehnen_fetch.json').read_text())['results'][0]
    assert 'datetime=' not in r['text'] and '<script' not in r['text']
    assert 'Abgesagt' in r['text']  # The 25 October performance, not 18 October.
    obs=observation(TARGETS[0],r['text'],r['final_url'],NOW)
    assert obs['link']['match_basis']=='title_occurrence_venue'
    assert obs['price']['values']['price_min']==12
    assert obs['price']['values']['price_max']==14
    assert 'status' not in obs and 'event_status' not in obs
    # This URL selected 18 October: a different row is not this occurrence.
    assert observation(dict(TARGETS[0],date='2026-10-25'),r['text'],r['final_url'],NOW) is None
    assert observation(dict(TARGETS[0],venue='Another theatre'),r['text'],r['final_url'],NOW) is None


def test_real_berlin_selected_row_cancellation_is_observed():
    from bs4 import BeautifulSoup
    r=json.loads((ROOT/'berlin_buehnen_fetch.json').read_text())['results'][0]
    soup=BeautifulSoup(r['text'],'lxml')
    first_row=soup.find('time',string=lambda s:s and '18.10.2026' in s).find_parent('p')
    first_row.append(soup.new_tag('bb-label'))
    first_row.find_all('bb-label')[-1].string='Abgesagt'
    obs=observation(TARGETS[0],str(soup),r['final_url'],NOW)
    assert obs['event_status']['values']['event_status']=='cancelled'
    assert 'status' not in obs
