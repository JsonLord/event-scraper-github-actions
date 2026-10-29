"""Conservative adapters for literal, occurrence-bound official event cards.

A card must contain its own heading and date; no ancestor or neighbour price
borrowing. Returning None means unsupported layout, retaining generic fallback.
"""
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup
from scripts.event_utils import clean_text, normalize_date, parse_date, parse_time, looks_synthetic_title, parse_price
import re


def official_programme_cards(html, source_url):
    """Canonical museum/theatre layouts; never use subtitle text as venue."""
    host=(urlsplit(source_url).hostname or '').removeprefix('www.')
    if host not in ('volksbuehne-berlin.de','berlin.museum'): return None
    soup=BeautifulSoup(html,'lxml')
    if host=='volksbuehne-berlin.de':
        cards=soup.select('li.activity')
    elif host=='berlin.museum':
        cards=soup.select('a.teaser')
    else:
        return None
    if not cards: return None
    out=[]
    for card in cards:
        if host=='volksbuehne-berlin.de':
            heading=card.select_one('.activity__title a[href]')
            marker=card.select_one('time[datetime]')
            venue=card.select_one('.activity__stage')
            note=card.select_one('.tickets')
            if not heading or not marker: continue
            stamp=marker['datetime'];url=urljoin(source_url,heading['href'])
            price=parse_price(note.get_text(' ',strip=True)) if note else None
        else:
            heading=card.select_one('.teaser-header h3')
            metadata=card.select('.teaser-copy > .row:first-child .zeplin-metadata')
            if not heading or len(metadata)!=2 or not card.get('href'): continue
            venue=metadata[0];stamp=metadata[1].get_text(' ',strip=True)
            url=urljoin(source_url,card['href'])
            # Copy may say free only for children/concessions. No public-price
            # inference from promotional prose or neighbouring event cards.
            price=None
        if not re.search(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',stamp): continue
        if (urlsplit(url).hostname or '').removeprefix('www.')!=host: continue
        title=clean_text(heading.get_text(' ',strip=True))
        if looks_synthetic_title(title): continue
        out.append(dict(title=title,date=normalize_date(stamp),time=parse_time(stamp),
                        venue=clean_text(venue.get_text(' ',strip=True)) if venue else '',
                        url=url,source_url=source_url,price=price,
                        description=card.get_text(' ',strip=True)))
    return out


def extract_cards(html, source_url):
    official=official_programme_cards(html,source_url)
    if official is not None: return official
    host = urlsplit(source_url).hostname or ''
    if not any(host == h or host.endswith('.'+h) for h in ('berlin-buehnen.de','ufafabrik.de')):
        return None
    soup = BeautifulSoup(html, 'lxml')
    selectors = 'hylo-router-link.event-list-item, li.calendar-view-day__row, article, .event-card, .event-item, .views-row, .performance, .spielplan-item, [itemtype$="Event"], .event'
    candidates = soup.select(selectors)
    cards = [c for c in candidates if not c.select(selectors)]
    out = []
    for card in cards:
        preferred = card.select_one('[slot="end"] h3')
        heading = preferred or next((h for h in card.select('h1,h2,h3,h4,[itemprop="name"],.event-title,.title,.views-field-title') if not looks_synthetic_title(clean_text(h.get_text(' ',strip=True)))), None)
        if not heading:
            continue
        text = card.get_text(' ',strip=True)
        marker = card.select_one('[datetime]')
        iso = normalize_date(marker.get('datetime')) if marker else parse_date(text)
        if not iso and 'calendar-view-day__row' in card.get('class',[]):
            cell = card.find_parent('td')
            day = cell.select_one('time[datetime]') if cell else None
            iso = normalize_date(day.get('datetime')) if day else None
        if not iso:
            # The date parameter is authoritative only for this per-day source.
            iso = normalize_date(parse_qs(urlsplit(source_url).query).get('date',[''])[0]) if 'berlin-buehnen.de' in host else None
        if not iso:
            continue
        title = clean_text(heading.get_text(' ',strip=True))
        anchor = card if card.name == 'hylo-router-link' and card.get('href') else heading if heading.name == 'a' and heading.get('href') else heading.find('a',href=True)
        if anchor is None:
            anchor = next((a for a in card.select('a[href]') if clean_text(a.get_text(' ',strip=True)) == title or '/event' in a['href'] or '/inszenierung' in a['href']), None)
        url = urljoin(source_url,anchor['href']) if anchor else source_url
        if urlsplit(url).scheme not in ('http','https'):
            url = source_url
        venue = card.select_one('[itemprop="location"],.venue,.location,.theatre,.theater,.views-field-field-venue,[slot="end"] h4 span')
        out.append(dict(title=title,date=iso,time=parse_time(marker.get('datetime','')) if marker else parse_time(text),
                        description=text,price=parse_price(text),venue=clean_text(venue.get_text(' ',strip=True)) if venue else '',url=url,source_url=source_url))
    return out if cards else None
