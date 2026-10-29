"""Raus-only bounded discovery: Search candidates require permitted destinations."""
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
import re
from scripts.event_utils import clean_text
from scripts.ticket_evidence import folded

def raus_semantic_candidates(soup, final_url, expected_title):
    """Raus detail header and literal Location/Venue block only.

    Exclude organizer prose, related cards and date-dependent shared pricing.
    An end time in the single header interval is not a second performance.
    """
    if not re.fullmatch(r'/(?:en/)?events/[^/]+/?',urlsplit(final_url).path): return []
    headings=soup.select('h1')
    if len(headings)!=1 or folded(headings[0].get_text(' ',strip=True))!=folded(expected_title): return []
    lines=[clean_text(x) for x in soup.get_text('\n',strip=True).splitlines() if clean_text(x)]
    title=clean_text(headings[0].get_text(' ',strip=True))
    if title not in lines: return []
    lines=lines[lines.index(title)+1:]
    stops=[i for i,x in enumerate(lines) if x in ("In the organizer's words:",'In den Worten der Veranstaltenden:','Location','Ort')]
    if not stops: return []
    header='\n'.join(lines[:min(stops)])
    months={'jan':1,'feb':2,'mär':3,'mar':3,'apr':4,'mai':5,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'okt':10,'oct':10,'nov':11,'dez':12,'dec':12}
    dates=list(re.finditer(r'(?<!\d)(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\.?\s+(20\d{2})(?!\d)',header))
    intervals=re.findall(r'(?<![\d:])([0-2]\d:[0-5]\d)\s*[-–]\s*([0-2]\d:[0-5]\d)(?!\d)',header)
    if len(dates)!=1 or len(intervals)!=1: return []
    d=dates[0];month=months.get(d[2].lower()[:3])
    if not month: return []
    from datetime import date
    try: day=date(int(d[3]),month,int(d[1])).isoformat()
    except ValueError: return []
    location=re.search(r'(?:^|\n)Location\nVenue\n([^\n]+)\n(.+?)(?=\n(?:FOLLOW|Navigate|Artist|Organizer|Our app|You might)|$)','\n'.join(lines),re.S)
    if not location or not re.search(r'\bBerlin\b',location[2]): return []
    # Prices and statuses are deliberately unknown: shared date-dependent prices
    # and organizer copy are not occurrence-bound inventory or admission evidence.
    return [dict(title=title,date=day,time=intervals[0][0],venue=location[1],
                 description=location[2],location_city='Berlin',url=final_url,canonical_url=final_url)]


def candidate_url(url):
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname!='rausgegangen.de' or p.username or p.password or p.port not in (None,443) or p.query or p.fragment:return ''
        match=re.fullmatch(r'/(?:en/)?events/([a-zA-Z0-9-]+)/?',p.path)
        return match[1] if match else ''
    except ValueError:return ''


def detail_candidates(html,url):
    """Structured data first; isolated literal Raus detail header second."""
    from scripts.generic_event_scraper import extract_jsonld_events
    result=extract_jsonld_events(html,url)
    for event in result:event['_representation']='jsonld'
    if candidate_url(url):
        soup=BeautifulSoup(html,'lxml')
        for tag in soup.select('nav,footer,header,aside,script,style'):tag.decompose()
        headings=soup.select('h1')
        if len(headings)==1:
            semantic=raus_semantic_candidates(soup,url,headings[0].get_text(' ',strip=True))
            for event in semantic:event['_representation']='isolated_raus_header'
            result.extend(semantic)
    return result


def discover(now,http,deadline,provider=None):
    """At most two Search queries and three permitted official destination URLs.

    The provider validator and this caller both enforce the one-domain allowlist.
    Search titles/snippets never enter the returned event records.
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from scripts.event_utils import validate_events,dedupe_events
    from scripts.tinyfish_client import TinyFishClient,public_url
    from scripts.qualify_restored_branch import AGENT,origin
    day=now.astimezone(ZoneInfo('Europe/Berlin')).date();end=day+timedelta(days=7)
    if provider is None:
        provider=TinyFishClient(max_fetch=3,max_search=2,deadline=deadline,
                               validator=lambda u:bool(candidate_url(u)) and public_url(u))
    first=day+timedelta(days=1 if now.astimezone(ZoneInfo('Europe/Berlin')).hour>=18 else 0)
    queries=[f'site:rausgegangen.de/events/ Berlin "{first.strftime("%d.%m.%Y")}"',
             f'site:rausgegangen.de/en/events/ Berlin "{first.strftime("%d. %b %Y")}"']
    urls=[];seen=set()
    for query in queries:
        for url in provider.search(query):
            slug=candidate_url(url)
            if slug and slug not in seen:seen.add(slug);urls.append(url)
    events=[];attempts=[]
    for url in urls[:3]:
        before=http.requests;doc=http.fetch(url);method='direct_http'
        policy=http.robots.get(origin(url))
        permitted=policy is not None and policy.can_fetch(AGENT,url)
        reason=http.reason
        if not doc and permitted:
            fetched=provider.fetch([url]).get(url)
            if fetched:
                final=fetched['final_url']
                # A hosted response is useful only at the same official event,
                # with the destination path permitted by the fresh policy too.
                if candidate_url(final)==candidate_url(url) and policy.can_fetch(AGENT,final):
                    doc=(final,fetched['html']);method='tinyfish_fetch'
                    http.documents[url]=doc;http.documents[final]=doc
                else:reason='provider_destination_rejected'
            else:reason=getattr(provider,'diagnostic','provider_failed')
        attempt=dict(url=url,robots_permitted=permitted,transport=method,
                     direct_http_attempts=http.requests-before,outcome='received' if doc else reason,extracted_occurrences=0)
        if doc and candidate_url(doc[0])==candidate_url(url):
            raw=[e for e in detail_candidates(doc[1],doc[0]) if
                 e.get('location_city','').strip().casefold()=='berlin' and
                 candidate_url(e.get('url',''))==candidate_url(doc[0]) and e.get('title') and e.get('time') and e.get('venue')]
            # Prefer structured records; do not merge disconnected body prices.
            clean,_=validate_events(raw,'https://rausgegangen.de/en/berlin/eventsbydate/',day,end,max_price=float('inf'))
            for e in clean:
                e['source_url']='https://rausgegangen.de/en/berlin/eventsbydate/'
                e['observed_at']=now.isoformat();e['destination_city']='Berlin'
            events.extend(clean);attempt['extracted_occurrences']=len(clean)
            if not clean:attempt['outcome']='no_exact_berlin_occurrence'
        attempts.append(attempt)
    diagnostics=dict(enabled=True,allowed_source='rausgegangen.de',search_calls=provider.search_queries,
                     fetch_urls=provider.fetch_urls,search_limit=2,fetch_limit=3,candidate_urls=len(urls),
                     attempted_destinations=attempts,provider_calls=provider.diagnostics,
                     provider_outcome=provider.diagnostic,http_attempts=http.requests,http_limit=http.limit)
    return dedupe_events(events),diagnostics
