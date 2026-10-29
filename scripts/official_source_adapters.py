"""Occurrence-bound adapters for the two canonical official programmes."""
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup
import re
from scripts.event_utils import clean_text,normalize_date,parse_time,looks_synthetic_title,parse_price

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
