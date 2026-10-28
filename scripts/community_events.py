"""Conservative newsletter eligibility from fresh, occurrence-bound evidence."""
from datetime import timedelta
from scripts.event_matching import host
from scripts.ticket_evidence import folded
from scripts.verify_event_details import utc

# Curated host/venue identities, not keywords in promotional descriptions.
CULTURAL_VENUES={folded(x) for x in ('Staatsoper Unter den Linden','Deutsche Oper Berlin','Komische Oper Berlin','Berliner Ensemble','Deutsches Theater Berlin','GRIPS Theater','Pfefferberg Theater','Theater Jaro')}
PUBLIC_SPACES={folded(x) for x in ('Bebelplatz','Tempelhofer Feld','Alexanderplatz')}
UFA_ROOMS={folded(x) for x in ('Theatersaal','Wolfgang Neuss Salon','Varieté Salon')}


def unconditional(offer):
    return folded(offer.get('eligibility','')) in {'','eintritt','standard','normalpreis','regular','adult','erwachsene','freierEintritt'.lower(),'freeadmission'}


def decision(event,now):
    from scripts.build_page_dataset import fresh
    now=utc(now)
    if event.get('verification_outcome')!='matched' or event.get('detail_link_status')!='verified': return False,'unverified_occurrence'
    stamps=event.get('field_observed_at',{})
    if not all(fresh(stamps.get(k),now,6) for k in ('link','price')): return False,'stale_or_missing_evidence'
    if event.get('claim_expires_at') and now>=utc(event['claim_expires_at']): return False,'expired_candidate'
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        start=datetime.fromisoformat(event['date']+'T'+event['time']).replace(tzinfo=ZoneInfo('Europe/Berlin'))
        if not now<start or start.date()>now.astimezone(ZoneInfo('Europe/Berlin')).date()+timedelta(days=7): return False,'outside_future_window'
    except (KeyError,ValueError,TypeError): return False,'missing_performance'
    if event.get('listing_ticket_status')=='sold_out': return False,'listing_reports_sold_out'
    if event.get('event_status') in ('cancelled','postponed') or event.get('ticket_status')=='sold_out': return False,'not_attendable'
    proof=event.get('pilot_location',{})
    if proof.get('city')!='Berlin' or folded(proof.get('venue',''))!=folded(event.get('venue','')) or not fresh(proof.get('observed_at'),now,6): return False,'missing_berlin_evidence'
    import re
    if re.search(r'\b(?:ausverkauft|sold out|abgesagt|cancelled|fällt aus)\b',event.get('description',''),re.I): return False,'negative_source_evidence'
    if re.search(r'\b(?:members? only|invitation only|private event|geschlossene veranstaltung|nur für mitglieder|nur auf einladung|nur für schulklassen)\b',event.get('title','')+' '+event.get('description',''),re.I): return False,'restricted_access'
    source=host(event.get('source_url',''));venue=folded(event.get('venue',''))
    if not ((source=='ufafabrik.de' and venue in UFA_ROOMS) or (source=='berlin-buehnen.de' and venue in CULTURAL_VENUES|PUBLIC_SPACES)):
        return False,'host_not_reviewed_public_cultural_venue'
    if event.get('free_admission_confirmed') is True and event.get('price_max')==0 and any(o.get('kind')=='regular' and o.get('amount_eur')==0 and o.get('source')=='jsonld_offer' and unconditional(o) for o in event.get('offers',[])): return True,'verified_free_public_cultural_event'
    # Require regular public admission, never a student/child/member-only minimum.
    regular=[o for o in event.get('offers',[]) if o.get('kind')=='regular' and unconditional(o) and o.get('amount_eur') is not None]
    if not regular: return False,'no_unconditional_regular_price'
    ceilings=[o.get('price_max',o['amount_eur']) for o in regular]
    if not all(isinstance(n,(int,float)) and 0<n<=5 for n in ceilings): return False,'regular_price_above_five_or_unknown'
    if event.get('price_status') in ('unknown','conflicted'): return False,'uncertain_price'
    return True,'verified_regular_admission_up_to_five'


def newsletter(events,now):
    from collections import Counter
    included=[];reasons=Counter()
    for event in events:
        yes,reason=decision(event,now);reasons[reason]+=1
        if yes:
            included.append({k:event.get(k) for k in ('event_id','title','date','time','venue','url','source_url','description','category','matched_categories','price_min','price_max','price_label','ticket_status','event_status','field_observed_at','claim_expires_at','evidence','pilot_location','offers')})
            regular=[o for o in event.get('offers',[]) if o.get('kind')=='regular' and unconditional(o) and o.get('amount_eur') is not None]
            low=min(o['amount_eur'] for o in regular);high=max(o.get('price_max',o['amount_eur']) for o in regular)
            included[-1].update(price_min=low,price_max=high,price_label='Free public admission' if high==0 else f'€{low:g} regular public admission' if low==high else f'€{low:g}–{high:g} regular public admission',currency='EUR')
            included[-1].update(community_reason=reason,availability_note='Ticket inventory unknown' if event.get('ticket_status')=='unknown' else 'Check official ticket page')
    return dict(version=1,generated_at=utc(now).isoformat(),maximum_regular_admission_eur=5,count=len(included),events=included,exclusion_counts=dict(reasons),eligibility_policy='Public cultural/community hosts; regular public admission only; no student-only qualification. An empty export means no validated eligible events.')
