import json
from scripts.audit_events import normalize_records, metrics, gate

def test_frozen_baseline_and_honest_after():
    events=json.load(open('tests/fixtures/events_scored_2026-10-11.json'))['events']
    m=metrics(events)
    assert [m[k] for k in ('records','unknown_prices','zero_prices','missing_links','blank_venues','past')]==[475,255,96,148,298,353]
    after,q=normalize_records(events,'2026-10-11')
    gate(after)
    assert len(q)==9 and len(after)==464
    assert all(e['price_label']!='Free' for e in after if '0-45€' in e['description'])
    assert metrics(after)['verified_links']==0
