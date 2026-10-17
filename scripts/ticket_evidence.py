"""Deterministic, occurrence-scoped evidence. Inputs must belong to one card/Event."""
from __future__ import annotations
import hashlib
import math
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit


def folded(value):
    text = unicodedata.normalize('NFKD', str(value).casefold().replace('ß', 'ss'))
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in text if not unicodedata.combining(c)))


def occurrence_id(event):
    # Candidate URLs may be corrected later: retain an assigned identity thereafter.
    if event.get('event_id'):
        return event['event_id']
    url = event.get('url', '')
    identity = url if url and url != event.get('source_url') else '|'.join(
        str(event.get(k) or '') for k in ('title', 'venue', 'source_url'))
    key = '|'.join((identity, str(event.get('date') or ''), str(event.get('time') or '')))
    return 'sha256:' + hashlib.sha256(key.encode()).hexdigest()


def amount(value):
    try:
        n = float(str(value).replace(',', '.'))
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def structured_offers(raw, url='', observed_at=None):
    out = []
    for offer in raw if isinstance(raw, list) else [raw]:
        if not isinstance(offer, dict):
            continue
        if offer.get('offers'):
            out.extend(structured_offers(offer['offers'], url, observed_at))
        if offer.get('priceCurrency', 'EUR') != 'EUR':
            continue
        low = amount(offer.get('price', offer.get('lowPrice')))
        high = amount(offer.get('highPrice', low))
        label = str(offer.get('name') or '')
        kind = 'student' if re.search(r'student|studierend', label, re.I) else 'reduced' if re.search(r'ermäß|reduced', label, re.I) else 'regular'
        state = str(offer.get('availability', '')).rsplit('/', 1)[-1]
        if low is not None or state:
            out.append(dict(kind=kind, amount_eur=low, price_max=high, eligibility=label,
                            availability={'InStock': 'available', 'SoldOut': 'sold_out'}.get(state, 'unknown'),
                            evidence_url=url, observed_at=observed_at, source='jsonld_offer'))
    return out


def enrich_evidence(event, observed_at=None):
    from scripts.event_utils import PRICE_RANGE_RE, PRICE_RE, FREE_RE, format_price_label
    result = dict(event)
    text = str(event.get('description') or '')
    title = str(event.get('title') or '')
    if title and text.startswith(title):
        text = text[len(title):].lstrip()
    stamp = observed_at or event.get('observed_at')
    url = event.get('url') or event.get('source_url') or ''
    offers = [dict(o) for o in event.get('offers', []) if isinstance(o, dict)]
    span = PRICE_RANGE_RE.search(text)
    if not offers:
        if span:
            a, b = sorted(amount(g) for g in span.groups())
            offers.append(dict(kind='regular', amount_eur=a, price_max=b, eligibility='', availability='unknown', evidence_url=url, observed_at=stamp, source='listing_card'))
        else:
            for match in PRICE_RE.finditer(text):
                prefix = text[max(0, match.start()-55):match.start()]
                kind = 'student' if re.search(r'(?:student\w*|studierende\w*)[^€]*$', prefix, re.I) else 'reduced' if re.search(r'(?:ermäßigt|reduced)[^€]*$', prefix, re.I) else 'regular'
                n = amount(next(g for g in match.groups() if g))
                offers.append(dict(kind=kind, amount_eur=n, price_max=n, eligibility=prefix.strip() if kind != 'regular' else '', availability='unknown', evidence_url=url, observed_at=stamp, source='listing_card'))
    values = [o['amount_eur'] for o in offers if o.get('amount_eur') is not None]
    highs = [o.get('price_max', o.get('amount_eur')) for o in offers if o.get('price_max', o.get('amount_eur')) is not None]
    price = min(values) if values else amount(event.get('price'))
    maximum = max(highs) if highs else price
    # Legacy numeric zero has no independent proof. Positive prices are retained.
    free_proof = bool(FREE_RE.search(text)) or any(o.get('source') == 'jsonld_offer' and o.get('amount_eur') == 0 for o in offers)
    if price == 0 and not free_proof and not values:
        price = maximum = None
    confirmed = free_proof and maximum in (None, 0)
    if price is None and confirmed:
        price = maximum = 0.0
    status = 'unknown' if price is None else 'range' if maximum != price else 'free' if confirmed else 'known'
    label = 'Check site' if price is None else 'Free' if confirmed else f'From €{price:g} · paid tiers' if maximum != price else format_price_label(price) if price else '€0 · conditions apply'
    source_status = {'EventScheduled':'scheduled','EventCancelled':'cancelled','EventPostponed':'postponed'}.get(event.get('event_status'), event.get('event_status', 'unknown'))
    state_text = text + ' ' + source_status
    event_status = 'cancelled' if re.search(r'\b(?:abgesagt|cancelled|EventCancelled)\b', state_text, re.I) else 'postponed' if re.search(r'\b(?:verschoben|postponed|EventPostponed)\b', state_text, re.I) else source_status
    states = {o.get('availability') for o in offers}
    ticket = 'sold_out' if re.search(r'\b(?:ausverkauft|sold out)\b', text, re.I) or 'sold_out' in states else 'available' if 'available' in states else 'unknown'
    if event_status in ('cancelled', 'postponed'):
        ticket = 'unknown'
    evidence = dict(event.get('evidence') or {})
    for field in ('price', 'status'):
        evidence.setdefault(field, dict(source='jsonld_offer' if any(o.get('source') == 'jsonld_offer' for o in offers) else 'listing_card', url=url, observed_at=stamp))
    result.update(price=price, price_min=price, price_max=maximum, price_status=status, price_label=label,
                  free_admission_confirmed=confirmed, offers=offers, student_discount_status='explicit' if any(o.get('kind') == 'student' for o in offers) else 'unknown',
                  event_status=event_status, ticket_status=ticket, evidence=evidence, observed_at=stamp,
                  detail_link_status=event.get('detail_link_status') or ('candidate' if event.get('has_detail_link') else 'missing'),
                  last_verified_at=event.get('last_verified_at'))
    result['event_id'] = occurrence_id(result)
    return result
