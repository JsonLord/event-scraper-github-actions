"""Conservative card adapters for Berlin Bühnen and ufaFabrik.

A card must contain its own heading and date; no ancestor or neighbour price
borrowing. Returning None means unsupported layout, retaining generic fallback.
"""
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup
from scripts.event_utils import clean_text, normalize_date, parse_date, parse_time, looks_synthetic_title, parse_price


def extract_cards(html, source_url):
    host = urlsplit(source_url).hostname or ''
    if not any(host == h or host.endswith('.'+h) for h in ('berlin-buehnen.de','ufafabrik.de')):
        return None
    soup = BeautifulSoup(html, 'lxml')
    selectors = 'article, .event-card, .event-item, .views-row, .performance, .spielplan-item, [itemtype$="Event"], .event'
    candidates = soup.select(selectors)
    cards = [c for c in candidates if not c.select(selectors)]
    out = []
    for card in cards:
        heading = next((h for h in card.select('h1,h2,h3,h4,[itemprop="name"],.event-title,.title') if not looks_synthetic_title(clean_text(h.get_text(' ',strip=True)))), None)
        if not heading:
            continue
        text = card.get_text(' ',strip=True)
        marker = card.select_one('[datetime]')
        iso = normalize_date(marker.get('datetime')) if marker else parse_date(text)
        if not iso:
            # The date parameter is authoritative only for this per-day source.
            iso = normalize_date(parse_qs(urlsplit(source_url).query).get('date',[''])[0]) if 'berlin-buehnen.de' in host else None
        if not iso:
            continue
        title = clean_text(heading.get_text(' ',strip=True))
        anchor = heading if heading.name == 'a' and heading.get('href') else heading.find('a',href=True)
        if anchor is None:
            anchor = next((a for a in card.select('a[href]') if clean_text(a.get_text(' ',strip=True)) == title or '/event' in a['href'] or '/inszenierung' in a['href']), None)
        url = urljoin(source_url,anchor['href']) if anchor else source_url
        if urlsplit(url).scheme not in ('http','https'):
            url = source_url
        venue = card.select_one('[itemprop="location"],.venue,.location,.theatre,.theater')
        out.append(dict(title=title,date=iso,time=parse_time(marker.get('datetime','')) if marker else parse_time(text),
                        description=text,price=parse_price(text),venue=clean_text(venue.get_text(' ',strip=True)) if venue else '',url=url,source_url=source_url))
    return out if cards else None
