#!/usr/bin/env python3
"""Read-only bounded Raus qualification; never writes into the checkout."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.qualify_restored_branch import ROOT, date_window, fingerprints, sanitized
from scripts.raus_html import direct_pipeline, direct_http
from scripts.raus_selective import listing_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--window-start', default='')
    parser.add_argument('--window-end', default='')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Qualification output must be outside the checkout')
    output.mkdir(parents=True, exist_ok=False)
    before = fingerprints()
    now = datetime.now(timezone.utc)
    first, last = date_window(now, args.window_start, args.window_end)
    http = direct_http()
    events, diagnostic = direct_pipeline(listing_url(first,last), now, first,last,http=http)
    result = dict(observed_at=now.isoformat(), window_start=first.isoformat(),window_end=last.isoformat(),
                  events=events, qualification=diagnostic, http_calls=http.calls,
                  robots_evidence=http.robot_evidence, http_limit=10, detail_limit=6,
                  tinyfish_calls=0, browser_calls=0, production_data_unchanged=fingerprints()==before)
    assert result['production_data_unchanged']
    (output/'results.json').write_text(json.dumps(sanitized(result),ensure_ascii=False,indent=2)+'\n')
    (output/'REPORT.md').write_text('# Raus direct-HTML qualification\n\n'+
        f'Observed: {now.isoformat()}; Berlin dates: {first} through {last}.\n\n'+
        'The production direct pipeline and matcher were used. No deployment or production data write.\n\n'+
        '```json\n'+json.dumps({k:v for k,v in diagnostic.items() if k != 'observations'},indent=2)+'\n```\n\n'+
        f'HTTP: {len(http.calls)}/10 requests; at most six detail URLs. TinyFish/browser calls: 0.\n\n'+
        'Zero retrieved occurrences means no live extraction qualification, even if offline tests pass.\n')
    print(json.dumps(dict(listing_outcome=diagnostic['listing_outcome'],candidates=diagnostic['candidates'],
        exact_matches=diagnostic['exact_matches'],publishable=len(events),http_requests=len(http.calls))))


if __name__ == '__main__':
    main()
