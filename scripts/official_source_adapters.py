"""Occurrence-bound adapters for canonical official programmes."""
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup
import re
from scripts.event_utils import clean_text,normalize_date,parse_time,looks_synthetic_title,parse_price


def berlin_buehnen_cards(soup, source_url):
    """Read public Hylo component hrefs, never neighbouring ticket links.

    Mobile and desktop markup repeat the same title/time within each card.
    Require those copies to agree rather than treating them as performances.
    """
    cards=soup.select('hylo-router-link.event-list-item[href]')
    if not cards:return None
    out=[]
    for card in cards:
        url=urljoin(source_url,card['href']);parsed=urlsplit(url)
        if (parsed.scheme!='https' or parsed.username or parsed.password or
            parsed.netloc not in ('www.berlin-buehnen.de','berlin-buehnen.de') or
            parsed.query or parsed.fragment or
            not re.fullmatch(r'/de/spielplan/[^/]+/events/\d+/',parsed.path)):
            continue
        titles={clean_text(h.get_text(' ',strip=True)) for h in card.select('h3')}
        stamps={t['datetime'].strip() for t in card.select('time[datetime]')}
        # The first desktop h4 is the venue; later h4s can be subtitles.
        venue=card.select_one('[slot="end"] h4')
        if len(titles)!=1 or len(stamps)!=1 or venue is None:continue
        title=next(iter(titles));stamp=next(iter(stamps))
        if not title or looks_synthetic_title(title) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}',stamp):continue
        day=normalize_date(stamp);start=parse_time(stamp)
        venue_name=clean_text(venue.get_text(' ',strip=True))
        if not day or not start or not venue_name:continue
        out.append(dict(title=title,date=day,time=start,venue=venue_name,
                        url=url,source_url=source_url,price=None,
                        description=card.get_text(' ',strip=True)))
    return out


def official_programme_cards(html, source_url):
    """Canonical programme layouts; never use subtitle text as venue."""
    host=(urlsplit(source_url).hostname or '').removeprefix('www.')
    if host not in ('volksbuehne-berlin.de','berlin.museum','berlin-buehnen.de'): return None
    soup=BeautifulSoup(html,'lxml')
    if host=='berlin-buehnen.de':return berlin_buehnen_cards(soup,source_url)
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
        title_heading=BeautifulSoup(str(heading),'lxml')
        if host=='berlin.museum':
            # Availability badges are not part of the Event's name. Keep the
            # untouched card text below so negative evidence is retained.
            for badge in title_heading.select('span'):
                if re.fullmatch(r'(?:Ausverkauft|Abgesagt)\s*:',badge.get_text(' ',strip=True),re.I):badge.decompose()
        title=clean_text(title_heading.get_text(' ',strip=True))
        if looks_synthetic_title(title): continue
        out.append(dict(title=title,date=normalize_date(stamp),time=parse_time(stamp),
                        venue=clean_text(venue.get_text(' ',strip=True)) if venue else '',
                        url=url,source_url=source_url,price=price,
                        description=card.get_text(' ',strip=True)))
    return out
