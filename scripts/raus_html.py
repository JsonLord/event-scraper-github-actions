"""Raus direct HTML -> bound cards -> detail observations -> publication gate.

No provider or browser fallback. A retrieved card is a candidate, never a
verified occurrence. Both the CLI and review builder use the functions here.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from scripts.event_utils import clean_text, looks_synthetic_title
from scripts.raus_selective import candidate_url
from scripts.ticket_evidence import folded, structured_offers

BERLIN = ZoneInfo('Europe/Berlin')
OBSERVATION_TTL = timedelta(hours=6)
MONTHS = {'jan': 1, 'feb': 2, 'mär': 3, 'mar': 3, 'apr': 4, 'mai': 5,
          'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'okt': 10,
          'oct': 10, 'nov': 11, 'dez': 12, 'dec': 12}


def is_listing(url):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.netloc == 'rausgegangen.de' and
                p.path.rstrip('/') in ('/en/berlin/eventsbydate', '/berlin/eventsbydate')
                and not p.fragment)
    except ValueError:
        return False


def sort_key(event):
    # Exact strings break ties after accent/case folding; input order never does.
    return (event.get('date', ''), event.get('time', ''), folded(event.get('title', '')),
            folded(event.get('venue', '')), candidate_url(event.get('url', '')),
            event.get('url', ''), event.get('title', ''), event.get('venue', ''))


def identity(event):
    return (candidate_url(event.get('url', '')), event.get('date'),
            event.get('time'), folded(event.get('title', '')))


def stable_candidates(events):
    """Collapse locale/responsive copies; reject conflicting names or venues."""
    groups = defaultdict(list)
    for event in events:
        if candidate_url(event.get('url', '')):
            groups[(candidate_url(event['url']), event.get('date'), event.get('time'))].append(event)
    out = []
    for rows in groups.values():
        if len({folded(e.get('title', '')) for e in rows}) != 1:
            continue
        venues = {folded(e['venue']) for e in rows if e.get('venue')}
        if len(venues) > 1:
            continue
        # Prefer an explicit venue; then a total deterministic value order.
        chosen = min(rows, key=lambda e: (not bool(e.get('venue')), sort_key(e),
                     json.dumps(e, sort_keys=True, ensure_ascii=False)))
        out.append(deepcopy(chosen))
    return sorted(out, key=sort_key)


def _window(url):
    q = parse_qs(urlsplit(url).query)
    try:
        first, last = (date.fromisoformat(q[k][0]) for k in ('start_date', 'end_date'))
        if first <= last and (last-first).days <= 7:
            return first, last
    except (KeyError, ValueError, IndexError):
        pass
    return None


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        if not re.search(r'[T ]\d{2}:\d{2}', value):
            return None
        local = stamp.astimezone(BERLIN) if stamp.tzinfo else stamp.replace(tzinfo=BERLIN)
        return local.date().isoformat(), local.strftime('%H:%M')
    except (ValueError, TypeError):
        return None


def _card_when(card, window):
    markers = [t.get('datetime') or t.get('content') for t in
               card.select('time[datetime], [itemprop="startDate"][content]')]
    if markers:
        stamps = {_stamp(m) for m in markers}
        return next(iter(stamps)) if None not in stamps and len(stamps) == 1 else None
    text = card.get_text(' ', strip=True)
    days = set()
    for raw in re.findall(r'(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)', text):
        try:
            days.add(date.fromisoformat(raw))
        except ValueError:
            return None
    # Decimal prices such as 4.00 EUR are not abbreviated numeric dates.
    for raw_day, raw_month, raw_year in re.findall(r'(?<!\d)(\d{1,2})\.(\d{1,2})\.(20\d{2})(?!\d)', text):
        try:
            days.add(date(int(raw_year), int(raw_month), int(raw_day)))
        except ValueError:
            return None
    pattern = r'(?<!\d)(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\.?(?:\s+(20\d{2}))?'
    for match in re.finditer(pattern, text):
        day, month, year = match.groups()
        month = int(month) if month.isdigit() else MONTHS.get(month.casefold()[:3])
        if not month:
            continue
        years = [int(year)] if year else range(window[0].year, window[1].year+1) if window else []
        for y in years:
            try:
                d = date(y, month, int(day))
                if year or window and window[0] <= d <= window[1]:
                    days.add(d)
            except ValueError:
                return None
    times = re.findall(r'(?<![\d:])((?:[01]?\d|2[0-3]):[0-5]\d)(?![\d:])', text)
    unique = list(dict.fromkeys(t.zfill(5) for t in times))
    if len(unique) == 2 and re.search(re.escape(times[0])+r'\s*[-–]\s*'+re.escape(times[1]), text):
        unique = unique[:1]  # A single literal start/end interval.
    return (next(iter(days)).isoformat(), unique[0]) if len(days) == len(unique) == 1 else None


def parse_listing(html, source_url):
    """Only card-local headings, dates and official event anchors; no slug titles.

    Short dates may inherit a year only from the explicit bounded URL range.
    Never use a listing-wide day, nearby event or generic venue as identity.
    """
    from scripts.generic_event_scraper import is_bot_challenge
    if not is_listing(source_url) or is_bot_challenge(html):
        return []
    soup = BeautifulSoup(html, 'lxml')
    for tag in soup.select('nav, footer, aside, script, style'):
        tag.decompose()
    events = []
    window = _window(source_url)
    for link in soup.select('a[href]'):
        url = urljoin(source_url, link['href'])
        if not candidate_url(url):
            continue
        card = link
        for _ in range(4):
            slugs = {candidate_url(urljoin(source_url, a['href'])) for a in card.select('a[href]')}
            slugs.discard('')
            if len(slugs) > 1:
                break
            headings = card.select('h2,h3,h4,h5,[itemprop="name"]')
            # A heading inside the event link wins over unrelated card labels.
            headings = link.select('h2,h3,h4,h5,[itemprop="name"]') or headings
            titles = {clean_text(h.get_text(' ', strip=True)) for h in headings}
            when = _card_when(card, window)
            if len(titles) == 1 and when:
                title = next(iter(titles))
                if not title or looks_synthetic_title(title):
                    break
                venue = card.select_one('.venue,.event-venue,[itemprop="location"]')
                if not window or window[0].isoformat() <= when[0] <= window[1].isoformat():
                    events.append(dict(title=title, date=when[0], time=when[1], url=url,
                        venue=clean_text(venue.get_text(' ', strip=True)) if venue else '',
                        source_url=source_url, description=card.get_text(' ', strip=True), price=None))
                break
            if card.parent is None or card.parent.name in ('body', 'html'):
                break
            card = card.parent
    return stable_candidates(events)


def _structured_details(html, final_url, observed_at):
    from scripts.generic_event_scraper import _walk_jsonld_nodes
    soup = BeautifulSoup(html, 'lxml')
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for node in _walk_jsonld_nodes(data):
            types = node.get('@type', [])
            types = types if isinstance(types, list) else [types]
            if not any(str(t).rsplit('/', 1)[-1].endswith('Event') for t in types):
                continue
            stamp = _stamp(node.get('startDate', ''))
            url = urljoin(final_url, str(node.get('url') or final_url))
            if not stamp or candidate_url(url) != candidate_url(final_url):
                continue
            place = node.get('location') or {}
            address = place.get('address') if isinstance(place, dict) else None
            if not isinstance(address, dict) or folded(address.get('addressLocality', '')) != 'berlin':
                continue
            venue = clean_text(place.get('name', ''))
            if not venue or folded(venue) in ('berlin','venue','buhne','various','tba','unknown'):
                continue
            raw_offers = node.get('offers') or []
            raw_offers = raw_offers if isinstance(raw_offers, list) else [raw_offers]
            offers = []
            for offer in raw_offers:
                if not isinstance(offer, dict) or offer.get('priceCurrency') != 'EUR':
                    continue
                try:
                    stamp_now = datetime.fromisoformat(observed_at) if observed_at else datetime.now(timezone.utc)
                    valid = True
                    validity = {}
                    for field, after in (('validFrom', True), ('validThrough', False), ('priceValidUntil', False)):
                        if not offer.get(field):continue
                        boundary = datetime.fromisoformat(str(offer[field]).replace('Z','+00:00'))
                        if len(str(offer[field])) == 10 and not after:
                            boundary = boundary.replace(hour=23,minute=59,second=59,microsecond=999999)
                        boundary = boundary if boundary.tzinfo else boundary.replace(tzinfo=BERLIN)
                        key = 'valid_from' if after else 'valid_until'
                        if key not in validity or (after and boundary > validity[key]) or (not after and boundary < validity[key]):
                            validity[key] = boundary
                        if after and stamp_now < boundary or not after and stamp_now > boundary:
                            valid = False
                    if not valid:continue
                except (ValueError, TypeError):
                    continue
                # Conditional free/companion admission is not ordinary admission.
                label = clean_text(str(offer.get('name') or '')+' '+str(offer.get('description') or ''))
                restrictions = any(offer.get(key) is not None for key in
                    ('eligibleCustomerType','eligibleQuantity','eligibleRegion','eligibleDuration','eligibleTransactionVolume'))
                parsed = structured_offers(offer, final_url)
                for item in parsed:
                    item.update({k:v.isoformat() for k,v in validity.items()})
                    item['eligibility'] = label
                    if re.search(r'student|studierend', label, re.I):
                        item['kind'] = 'student'
                    elif restrictions or re.search(r'companion|begleit|\bonly\b|\bnur\b|member|mitglied|child|kinder|ermäß|reduced|senior', label, re.I):
                        item['kind'] = 'conditional'
                    if item.get('price_max') is not None and item.get('amount_eur') is not None and item['price_max'] < item['amount_eur']:
                        continue
                    offers.append(item)
            # Provider/DOM order must not change the serialized publication.
            offers = sorted({json.dumps(o,sort_keys=True):o for o in offers}.values(),
                key=lambda o:(o['kind'],o.get('amount_eur') is None,o.get('amount_eur') or 0,
                              o.get('price_max') or 0,folded(o.get('eligibility','')),
                              json.dumps(o,sort_keys=True)))
            regular = [o for o in offers if o['kind'] == 'regular']
            states = {o['availability'] for o in regular}
            yield dict(title=clean_text(node.get('name', '')), date=stamp[0], time=stamp[1],
                       venue=venue, url=final_url, location_city='Berlin', regular_offers=regular,
                       student_offers=[o for o in offers if o['kind'] == 'student'],
                       event_status={'EventCancelled':'cancelled','EventPostponed':'postponed',
                                     'EventScheduled':'scheduled'}.get(str(node.get('eventStatus','')).rsplit('/',1)[-1], 'unknown'),
                       ticket_status='sold_out' if states == {'sold_out'} else 'available' if states == {'available'} else 'unknown',
                       representation='jsonld')


def match_detail(event, html, final_url, observed_at=None):
    """Bind structured offers/status to one official Berlin performance only."""
    result = {k:event.get(k) for k in ('title','date','time','venue','url')}
    result.update(matched=False, outcome='no_matching_structured_event', final_url=final_url,
                  observed_at=observed_at)
    from scripts.generic_event_scraper import is_bot_challenge
    if (not candidate_url(event.get('url','')) or
        candidate_url(event['url']) != candidate_url(final_url) or is_bot_challenge(html)):
        result['outcome'] = 'destination_rejected'
        return result
    headings = {folded(h.get_text(' ',strip=True)) for h in BeautifulSoup(html,'lxml').select('h1')}
    if headings and headings != {folded(event.get('title',''))}:
        result['outcome'] = 'detail_heading_mismatch'
        return result
    matches = []
    for detail in _structured_details(html, final_url, observed_at):
        if identity(detail) != identity(event):
            continue
        if event.get('venue') and folded(event['venue']) != folded(detail['venue']):
            continue
        matches.append(detail)
    # Duplicate conflicting Event nodes cannot select a favorable price/status.
    unique = {json.dumps(d, sort_keys=True, ensure_ascii=False) for d in matches}
    if len(unique) == 1:
        detail = matches[0]
        result.update(detail, url=event['url'], matched=True, outcome='exact_structured_occurrence',
                      match_basis='title_date_time_venue' if event.get('venue') else 'official_canonical_title_date_time')
    elif len(unique) > 1:
        result['outcome'] = 'conflicting_structured_events'
    return result


def is_raus_record(event):
    for key in ('url', 'source_url'):
        try:
            if urlsplit(str(event.get(key) or '')).hostname == 'rausgegangen.de':
                return True
        except ValueError:
            continue
    return False


def publication_gate(event, observation, now, first, last, max_price=20):
    """Fail closed on identity, city, freshness, negative state and ordinary price.

    Unknown price is publishable as unknown, never as free/affordable. Only
    occurrence-bound normal admission offers may set the public numeric price.
    """
    if not observation or not observation.get('matched') or identity(event) != identity(observation):
        return None
    if (observation.get('representation') != 'jsonld' or
        candidate_url(observation.get('final_url', '')) != candidate_url(event.get('url', ''))):
        return None
    if observation.get('location_city') != 'Berlin' or not observation.get('venue'):
        return None
    if event.get('venue') and folded(event['venue']) != folded(observation['venue']):
        return None
    try:
        stamp = datetime.fromisoformat(observation['observed_at'])
        if not stamp.tzinfo or not timedelta(0) <= now-stamp <= OBSERVATION_TTL:
            return None
        local = now.astimezone(BERLIN)
        performance = datetime.fromisoformat(event['date']+'T'+event['time']).replace(tzinfo=BERLIN)
        if not first <= performance.date() <= last or performance <= local:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    if observation.get('event_status') in ('cancelled','postponed') or observation.get('ticket_status') == 'sold_out':
        return None
    def current(offer):
        try:
            return (not offer.get('valid_from') or now >= datetime.fromisoformat(offer['valid_from'])) and (
                not offer.get('valid_until') or now <= datetime.fromisoformat(offer['valid_until']))
        except (ValueError, TypeError):
            return False
    current_regular = [o for o in observation.get('regular_offers', []) if current(o)]
    students = [deepcopy(o) for o in observation.get('student_offers', []) if current(o)]
    regular = [deepcopy(o) for o in current_regular if o.get('amount_eur') is not None]
    availability = {o.get('availability','unknown') for o in current_regular}
    low = min((o['amount_eur'] for o in regular), default=None)
    high = max((o.get('price_max') if o.get('price_max') is not None else o['amount_eur'] for o in regular), default=None)
    if low is not None and low > max_price:
        return None
    free = low == high == 0
    out = deepcopy(event)
    out.update(price=low, price_min=low, price_max=high, offers=regular,
               price_status='unknown' if low is None else 'free' if free else 'range' if low != high else 'known',
               price_label='Check admission on site' if low is None else 'Free · matched structured offer' if free else f'€{low:g}–{high:g}' if low != high else f'€{low:g}',
               free_admission_confirmed=free, venue=observation['venue'],
               student_offers=students,
               student_discount_status='explicit' if students else 'unknown',
               ticket_status='available' if availability == {'available'} else 'unknown', event_status=observation.get('event_status','unknown'),
               observed_at=observation['observed_at'], last_verified_at=observation['observed_at'],
               verification_status='verified', has_detail_link=True, detail_link_status='verified',
               evidence={field:dict(source='matched_jsonld_event',url=observation['final_url'],observed_at=observation['observed_at']) for field in ('price','status')})
    return out


def direct_http():
    """Main's negotiation headers/session behavior, with our actual crawler ID."""
    from scripts.qualify_restored_branch import HTTP
    return HTTP(10, time.monotonic()+180, 10_000_000,
                browser_headers=True, preserve_cookies=True)


def direct_pipeline(url, now, first, last, http=None, max_details=6, max_price=20):
    """Production direct path, reused by the standalone live qualification."""
    if not is_listing(url):
        raise ValueError('Expected an official Raus Berlin listing URL')
    if http is None:
        http = direct_http()
    doc = http.fetch(url)
    candidates = parse_listing(doc[1], doc[0]) if doc and is_listing(doc[0]) else []
    listing_cards = len(candidates)
    url_candidates = set()
    if doc and is_listing(doc[0]):
        for anchor in BeautifulSoup(doc[1],'lxml').select('a[href]'):
            slug = candidate_url(urljoin(doc[0],anchor['href']))
            if slug:url_candidates.add(slug)
    candidates = [e for e in candidates if first.isoformat() <= e['date'] <= last.isoformat() and
                  datetime.fromisoformat(e['date']+'T'+e['time']).replace(tzinfo=BERLIN) > now.astimezone(BERLIN)]
    observations, published = [], []
    for event in candidates[:max(0,min(max_details,6))]:
        detail = http.fetch(event['url'])
        observation = match_detail(event, detail[1], detail[0], now.isoformat()) if detail else dict(event,matched=False,outcome=http.reason)
        observations.append(observation)
        accepted = publication_gate(event, observation, now, first, last, max_price)
        if accepted:
            published.append(accepted)
    diagnostic = dict(listing_received=bool(doc), listing_outcome='received' if doc else http.reason,
                      listing_discovery_success=bool(listing_cards), listing_card_occurrences=listing_cards,
                      candidate_url_discovery_success=bool(url_candidates), candidate_urls=len(url_candidates),
                      candidates=len(candidates), attempted_details=len(observations),
                      exact_matches=sum(o['matched'] for o in observations), publishable=len(published),
                      exact_match_rate=sum(o['matched'] for o in observations)/len(observations) if observations else None,
                      verified_source_presence=any(o['matched'] for o in observations),
                      detail_limit=6, observations=observations)
    return stable_candidates(published), diagnostic
