#!/usr/bin/env python3
"""Manual read-only qualification: at most TWO Search calls and TWO Fetch URLs.

Uses only existing environment credentials, never deploys or edits canonical data.
Artifacts contain compact sanitized public HTML and whitelisted diagnostics only.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bs4 import BeautifulSoup
import requests
from scripts.tinyfish_client import TinyFishClient, public_url
from scripts.verify_event_details import observation


def safe_url(url):
    if not public_url(url,resolve=False): return ''
    p=urlsplit(url)
    return urlunsplit((p.scheme,p.netloc,p.path,'',''))


def sanitized_html(html):
    soup=BeautifulSoup(html,'lxml')
    for tag in soup.select('script,style,nav,footer,header,aside,form,input,button,iframe,img,picture,source'): tag.decompose()
    for tag in soup.find_all(True):
        for key in list(tag.attrs):
            # Do not synthesize attributes lost during semantic extraction.
            if key!='datetime': del tag[key]
    text=str(soup)
    text=re.sub(r'https?://[^\s<>"\']+',lambda m:safe_url(m.group()),text)
    return text[:40000]


def qualify(targets, output):
    if len(targets)!=2: raise ValueError('Qualification requires exactly two pre-reviewed public event targets')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    client=TinyFishClient(max_fetch=2,max_search=2,deadline=time.monotonic()+480)
    report={'captured_at':datetime.now(timezone.utc).isoformat(),'key_present':bool(client.key),'targets':[], 'provider_calls':[]}
    for i,event in enumerate(targets):
        query=' '.join(event.get(k,'') for k in ('title','venue','date'))+' Berlin site:'+urlsplit(event['source_url']).hostname
        candidates=client.search(query)
        item={'target':{k:event.get(k) for k in ('title','date','time','venue')},'requested_url':safe_url(event['url']), 'search_candidate_count':len(candidates),'search_contains_target':safe_url(event['url']) in [safe_url(u) for u in candidates]}
        # A documented source policy remains a prerequisite, also for hosted Fetch.
        root=urlsplit(event['source_url']);robots_url=root.scheme+'://'+root.netloc+'/robots.txt'
        allowed=False
        try:
            r=requests.get(robots_url,timeout=(8,12),allow_redirects=False)
            if r.status_code in (200,404):
                parser=RobotFileParser();parser.parse(r.text.splitlines() if r.status_code==200 else [])
                allowed=parser.can_fetch('BerlinEventEvidence/1.0',event['url'])
        except requests.RequestException: pass
        item['robots_allowed']=allowed
        result=client.fetch([event['url']]).get(event['url']) if allowed else None
        if result:
            html=sanitized_html(result['html'])
            final=safe_url(result['final_url'])
            # Re-evaluate exactly the representation committed as a fixture.
            obs=observation(event,html,final,report['captured_at'])
            fixture={'results':[{'url':safe_url(event['url']),'final_url':final,'format':'html','text':html}], 'errors':[]}
            (output/f'fetch-{i+1}.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n')
            item.update(final_url=final,semantic_html_bytes=len(html.encode()),has_script='script' in html.lower(),has_datetime='datetime=' in html,matched=bool(obs),observed_fields=sorted(obs or {}),match_basis=(obs or {}).get('link',{}).get('match_basis'))
        else: item.update(matched=False,outcome=client.diagnostic)
        report['targets'].append(item)
    report.update(fetch_urls=client.fetch_urls,search_requests=client.search_queries,provider_calls=client.diagnostics)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--targets',default='config/tinyfish_qualification_targets.json');p.add_argument('--output',default='qualification');a=p.parse_args()
    qualify(json.loads(Path(a.targets).read_text()),a.output)
