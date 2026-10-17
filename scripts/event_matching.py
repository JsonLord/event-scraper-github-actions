"""Conservative identity and semantic-HTML evidence without DOM attributes."""
import re
from urllib.parse import urlsplit, urlunsplit
from bs4 import BeautifulSoup
from scripts.ticket_evidence import folded
from scripts.event_utils import clean_text, parse_date, parse_time, normalize_date


def host(url):
    return (urlsplit(url).hostname or '').removeprefix('www.')


def event_url(url):
    """A specific public event path, never a listing or generic venue page."""
    p=urlsplit(url)
    path=p.path.rstrip('/')
    if p.scheme not in ('http','https') or not path: return ''
    if re.search(r'/(?:venues?|locations?|theaters?)(?:/|$)',path,re.I): return ''
    if path.lower().split('/')[-1] in ('de','en','events','programm','program','spielplan','spielplan.html','program.html','veranstaltungen'): return ''
    return urlunsplit((p.scheme,p.netloc,path,p.query,''))


def match_basis(event, candidate, final_url):
    if not event.get('title') or folded(event['title'])!=folded(candidate.get('title','')): return None
    if not event.get('date') or event['date']!=candidate.get('date'): return None
    if (event.get('time') or '')!=(candidate.get('time') or ''): return None
    a,b=event.get('venue'),candidate.get('venue')
    if a and b:
        return 'title_occurrence_venue' if folded(a)==folded(b) else None
    # Missing venue may use independent official identity; never override a mismatch.
    official=host(event.get('source_url',''))
    if not official or host(final_url)!=official: return None
    target=event_url(event.get('canonical_url') or event.get('url',''))
    if target and target==event_url(event.get('source_url','')): return None
    destination=event_url(candidate.get('canonical_url') or candidate.get('url','') or final_url)
    final=event_url(final_url)
    if target and destination==target and final==target: return 'official_canonical_occurrence'
    a,b=event.get('official_event_id'),candidate.get('official_event_id')
    if a and b and str(a)==str(b) and final: return 'official_id_occurrence'
    return None



def berlin_semantic_candidates(soup, final_url, expected_title):
    """Known captured semantic layout: selected hero + isolated accordion rows.

    The common page includes other performances and recommendations. Only the
    selected hero's literal date/time may be verified at this occurrence URL.
    Cancellation from another row must never propagate to this performance.
    """
    pages=soup.select('bb-page-detail')
    if len(pages)!=1: return []
    page=pages[0]
    headings=page.select('h1')
    if not headings or any(folded(h.get_text(' ',strip=True))!=folded(expected_title) for h in headings): return []
    sections={}
    for item in page.select('hylo-accordion-item'):
        header=item.select_one('hylo-accordion-item-header')
        body=item.select_one('hylo-accordion-item-body')
        if header and body:
            label=header.get_text(' ',strip=True)
            if label in sections: return []
            sections[label]=body
    if 'Termine' not in sections or 'Ort' not in sections: return []
    date_re=r'(?<!\d)\d{1,2}\.\s*\d{1,2}\.\s*\d{4}(?!\d)'
    # The selected hero precedes the performance accordion.
    prefix=page.get_text('\n',strip=True).split('Termine',1)[0]
    selected=re.search(date_re,prefix)
    if not selected: return []
    selected_date=parse_date(selected.group())
    selected_time=parse_time(prefix[selected.end():selected.end()+50])
    if not selected_time: return []
    venue=sections['Ort'].select_one('h5')
    if not venue: return []
    venue_text=clean_text(venue.get_text(' ',strip=True))
    timeline=sections['Termine'].get_text('\n',strip=True)
    dates=list(re.finditer(date_re,timeline))
    out=[]
    for i,match in enumerate(dates):
        segment=timeline[match.start():dates[i+1].start() if i+1<len(dates) else len(timeline)]
        day=parse_date(match.group());clock=parse_time(segment)
        if (day,clock)!=(selected_date,selected_time): continue
        price_text=sections['Tickets'].get_text(' ',strip=True) if 'Tickets' in sections else ''
        # Shared admission prices may enrich price, but never add inventory/status.
        from scripts.event_utils import PRICE_RANGE_RE, PRICE_RE
        span=PRICE_RANGE_RE.search(price_text) or PRICE_RE.search(price_text)
        admission=span.group() if span else ''
        out.append(dict(title=clean_text(headings[0].get_text(' ',strip=True)),date=day,time=clock,venue=venue_text,description=segment+'\n'+admission,url=final_url))
    return out if len(out)==1 else []

def semantic_candidates(html, final_url, expected_title):
    """Read a single event section; reject neighboring headings/performances.

    Semantic Fetch may remove classes, time attributes and scripts. Only literal
    dates/times and explicitly labelled venues in that same section are used.
    """
    soup=BeautifulSoup(html,'lxml')
    for tag in soup.select('nav,footer,header,aside,script,style'): tag.decompose()
    if host(final_url)=='berlin-buehnen.de' and soup.select_one('bb-page-detail'):
        return berlin_semantic_candidates(soup,final_url,expected_title)
    scopes=soup.select('article')
    if not scopes: scopes=[soup.select_one('main') or soup.body or soup]
    out=[]
    for scope in scopes:
        headings=scope.select('h1,h2,h3')
        if not headings or folded(headings[0].get_text(' ',strip=True))!=folded(expected_title): continue
        allowed={'termin','termine','datum','zeit','ort','veranstaltungsort','tickets','ticketsundpreise','ticketsandprices','preise','eintritt','beschreibung','informationen','information'}
        if any(folded(h.get_text(' ',strip=True)) not in allowed|{folded(expected_title)} for h in headings[1:]): continue
        text=scope.get_text('\n',strip=True)
        markers=scope.select('time[datetime]')
        # Explicit full dates are mandatory for attribute-free content; no year guessing.
        dates=set()
        for match in re.finditer(r'\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}\.\s*\d{1,2}\.\s*\d{4}\b|\b\d{1,2}\.?\s+(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+\d{4}\b',text,re.I):
            value=parse_date(match.group())
            if value: dates.add(value)
        for marker in markers:
            value=normalize_date(marker.get('datetime'))
            if value: dates.add(value)
        if len(dates)!=1: continue
        times=set(re.findall(r'(?<![\d:])(?:[01]\d|2[0-3]):[0-5]\d(?!\d)', text))
        times.update(parse_time(m.get('datetime','')) for m in markers if parse_time(m.get('datetime','')))
        if len(times)>1: continue
        venue=scope.select_one('[itemprop="location"],.venue,.location')
        venue_text=clean_text(venue.get_text(' ',strip=True)) if venue else ''
        if not venue_text:
            # Literal label only: do not treat any nearby address as the venue.
            match=re.search(r'(?:^|\n)(?:Ort|Veranstaltungsort|Venue|Location)\s*:\s*([^\n]+)',text,re.I)
            if match: venue_text=clean_text(match.group(1))
        if not venue_text and host(final_url)=='ufafabrik.de' and scope.name=='article':
            paragraphs=scope.find_all('p',recursive=False)
            if len(paragraphs)>=2 and paragraphs[1].find('time'):
                first=clean_text(paragraphs[0].get_text(' ',strip=True))
                if first and len(first)<80 and not re.search(r'€|\d|https?://',first):
                    venue_text=first
        explicit_available=any(re.fullmatch(r'(?:Tickets|Karten)\s+(?:sind\s+)?(?:verfügbar|available)[.!]?',line.strip(),re.I) for line in text.splitlines())
        out.append(dict(title=expected_title,date=next(iter(dates)),time=next(iter(times),''),venue=venue_text,description=text,url=final_url,_explicit_available=explicit_available))
    return out
