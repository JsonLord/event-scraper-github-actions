#!/usr/bin/env python3
"""Building, validating and rendering community issues.

This module owns the *data contract* side of the community pipeline: turning a
scraped aggregate into a schema-shaped candidate issue, deciding whether an
event may be published, and rendering the review summary a human editor reads.
The discovery side (which rows exist) and the editorial side (which rows a
human wants) live elsewhere.

Two rules are load-bearing here and are enforced rather than described:

  1. An unsettled price is never published. ``publication_problems`` refuses
     ``unknown`` and ``needs_verification`` outright, so no amount of scoring
     can push an unverified price onto the public page.
  2. Only explicitly approved event ids are published. ``build_approved_issue``
     takes the decision file, not the candidate file, as the source of
     approval, and refuses unknown ids rather than silently ignoring them.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta

# Sibling modules are imported flat ("from community_common import ..."),
# matching the rest of scripts/, so the directory has to be on the path even
# when this file is imported as part of the package (tests, tooling).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from community_common import (
    COMMUNITY_MAX_PRICE,
    FIELD_MATCH,
    ISSUE_TIMEZONE,
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_DONATION,
    PRICE_STATUS_NEEDS_VERIFICATION,
    PRICE_STATUS_UNKNOWN,
    SCHEMA_VERSION,
    SELECTION_APPROVED,
    SELECTION_PROPOSED,
    SELECTION_REJECTED,
    SELECTION_UNRESOLVED,
    VERIFICATION_MATCHED,
    VERIFICATION_CORRECTED,
    VERIFICATION_REJECTED,
    VERIFICATION_UNCONFIRMED,
    canonical_url,
    category_label,
    in_issue_week,
    issue_week_payload,
    price_priority,
    stable_event_id,
)

# Fields a public event must have actually been confirmed against its own
# official page. Availability is deliberately excluded: "no sold-out marker"
# is not proof that tickets exist, so requiring it would block every event.
REQUIRED_VERIFIED_FIELDS = ("title", "date")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _iso_date(value: Any) -> Optional[str]:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


COMMUNITY_EVENT_ID_RE = re.compile(r"^ce-[0-9a-f]{24}$")


def is_community_event_id(value: Any) -> bool:
    """True for an id this pipeline minted, false for a foreign namespace."""
    return bool(COMMUNITY_EVENT_ID_RE.match(str(value or "")))


def event_record(
    raw: Dict[str, Any],
    *,
    week_start: date,
    week_end: date,
    source_provenance: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Turn one aggregate row into a schema-shaped community event record.

    Returns None when the row cannot even be described - no title, no usable
    date, or a date outside the issue week. Everything else is preserved with
    honest nulls rather than guesses, so verification has something to check
    instead of something to re-derive.
    """
    if not isinstance(raw, dict):
        return None
    title = _clean(raw.get("title"))
    occurrence = _iso_date(raw.get("date"))
    if not title or not occurrence:
        return None

    event_url = canonical_url(str(raw.get("event_url") or raw.get("url") or ""))
    source_url = canonical_url(str(raw.get("source_url") or ""))
    listing_url = canonical_url(str(raw.get("listing_url") or source_url or ""))
    time_value = _clean(raw.get("time")) or None

    # Only a community id is carried through. A row from the aggregate may
    # carry the scraping pipeline's own identity (`sha256:...`), which has no
    # meaning in the candidate/reviewed/approved files and would fail schema
    # validation if adopted.
    existing_id = raw.get("event_id")
    event_id = existing_id if is_community_event_id(existing_id) else stable_event_id(
        title, event_url or source_url, occurrence,
        venue=_clean(raw.get("venue")), time=time_value or "",
    )

    price = raw.get("price_eur", raw.get("price"))
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
    # Normalised through the shared resolver rather than copied, because the
    # aggregate may carry the other pipeline's vocabulary in this same field
    # (`free` / `known` / `range`) and a record may only ever hold a community
    # status. See community_common.price_status_for.
    from community_common import price_status_for

    price_status = price_status_for({**raw, "price_eur": price})

    from community_common import classify_category, district_from_text

    category = str(raw.get("category") or "") or classify_category(
        title, _clean(raw.get("venue")), _clean(raw.get("description"))
    )
    district = _clean(raw.get("district")) or district_from_text(
        _clean(raw.get("venue")), _clean(raw.get("address")), _clean(raw.get("description"))
    )

    record: Dict[str, Any] = {
        "event_id": event_id,
        "title": title[:200],
        "date": occurrence,
        "time": time_value,
        "end_time": _clean(raw.get("end_time")) or None,
        "venue": _clean(raw.get("venue")),
        "district": district,
        "address": _clean(raw.get("address")) or None,
        "price_eur": price,
        "price_status": price_status,
        "price_note": _clean(raw.get("price_note")) or None,
        "category": category,
        "description": _clean(raw.get("description"))[:600],
        "event_url": event_url,
        "listing_url": listing_url or None,
        "source_url": source_url or None,
        "scraped_at": str(raw.get("scraped_at") or "") or None,
        "image_url": str(raw.get("image_url") or "") or None,
        "image_source": str(raw.get("image_source") or "") or None,
        "image_verified": raw.get("image_verified"),
        "image_checked_at": str(raw.get("image_checked_at") or "") or None,
        "verification": raw.get("verification") or {
            "status": "pending",
            "checked_at": None,
            "official_source_url": event_url or None,
            "fields": {},
            "corrections": [],
            "notes": "",
        },
        "community": raw.get("community") or {
            "recommendation_reason": "",
            "selection_score": raw.get("selection_score"),
            "price_priority": price_priority(price_status),
            "selection_status": SELECTION_PROPOSED,
        },
    }
    if source_provenance:
        record["provenance"] = dict(source_provenance)
    return record


# --------------------------------------------------------------------------
# Publication rules
# --------------------------------------------------------------------------

def publication_problems(event: Dict[str, Any], week_start: date, week_end: date,
                         max_price: float = COMMUNITY_MAX_PRICE) -> List[str]:
    """Every reason this event may not be published; empty when it may.

    Returns all problems rather than the first, so a reviewer fixing one issue
    does not discover the next one on the following run.
    """
    problems: List[str] = []
    if not event.get("event_id"):
        problems.append("missing_event_id")
    if not _clean(event.get("title")):
        problems.append("missing_title")
    occurrence = _iso_date(event.get("date"))
    if not occurrence:
        problems.append("missing_or_invalid_date")
    elif not in_issue_week(occurrence, week_start, week_end):
        problems.append("outside_issue_week")

    verification = event.get("verification") or {}
    status = verification.get("status")
    fields = verification.get("fields") or {}
    if status == VERIFICATION_REJECTED:
        problems.append("verification_rejected")
    if status not in (VERIFICATION_MATCHED, VERIFICATION_CORRECTED):
        problems.append("unverified")
    for field in REQUIRED_VERIFIED_FIELDS:
        outcome = fields.get(field)
        if outcome not in (FIELD_MATCH, "corrected"):
            problems.append(f"unverified_{field}")
    if fields.get("cancellation") == "rejected":
        problems.append("cancelled")

    price_status = event.get("price_status")
    price = event.get("price_eur")
    if price_status in (PRICE_STATUS_UNKNOWN, PRICE_STATUS_NEEDS_VERIFICATION):
        problems.append("price_unknown")
    elif price_status == PRICE_STATUS_CONFIRMED_FREE:
        pass
    elif price_status == PRICE_STATUS_DONATION:
        # A donation has no entry price to cap, but it must be stated.
        if not _clean(event.get("price_note")):
            problems.append("donation_amount_unstated")
    elif price_status == PRICE_STATUS_CONFIRMED_PAID:
        if price is None:
            problems.append("price_unknown")
        elif float(price) > max_price:
            problems.append("price_above_cap")
        elif float(price) <= 0:
            problems.append("price_status_mismatch")
    else:
        problems.append("price_status_invalid")

    if not _clean(event.get("event_url")):
        problems.append("missing_event_url")
    if not _clean(event.get("venue")):
        problems.append("missing_venue")
    return problems


def is_publishable(event: Dict[str, Any], week_start: date, week_end: date,
                   max_price: float = COMMUNITY_MAX_PRICE) -> bool:
    return not publication_problems(event, week_start, week_end, max_price)


# --------------------------------------------------------------------------
# Issue payloads
# --------------------------------------------------------------------------

def build_issue(
    events: Sequence[Dict[str, Any]],
    week_start: date,
    week_end: date,
    *,
    status: str,
    generated_at: Optional[str] = None,
    summary: Optional[Dict[str, Any]] = None,
    published_at: Optional[str] = None,
) -> Dict[str, Any]:
    from community_common import iso_now

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "issue_week": issue_week_payload(week_start, week_end),
        "generated_at": generated_at or iso_now(),
        "status": status,
        "events": list(events),
    }
    if published_at:
        payload["published_at"] = published_at
    if summary is not None:
        payload["summary"] = summary
    return payload


def build_candidate_issue(
    events: Sequence[Dict[str, Any]],
    week_start: date,
    week_end: date,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """The weekly handoff file: everything proposed, plus its verification."""
    for event in events:
        event.setdefault("community", {})
        event["community"].setdefault("selection_status", SELECTION_PROPOSED)
    return build_issue(events, week_start, week_end, status="candidates", summary=summary)


def build_reviewed_issue(
    candidates: Dict[str, Any],
    decisions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply human decisions to a candidate issue, in place of guessing.

    A decision naming an id that is not in the candidate file is an error, not
    a no-op: it means the reviewer was looking at a different week, and
    promoting "whatever matched" would publish the wrong events.
    """
    by_id = {event["event_id"]: event for event in candidates.get("events", [])}
    unknown = [d.get("event_id") for d in decisions if d.get("event_id") not in by_id]
    if unknown:
        raise ValueError(f"decisions reference unknown event ids: {', '.join(unknown)}")

    reviewed_events: List[Dict[str, Any]] = []
    for decision in decisions:
        event = dict(by_id[decision["event_id"]])
        community = dict(event.get("community") or {})
        verdict = decision.get("decision")
        community["selection_status"] = (
            SELECTION_APPROVED if verdict == "approved" else SELECTION_REJECTED
        )
        if decision.get("note"):
            community["review_note"] = str(decision["note"])
        event["community"] = community
        for field, value in (decision.get("corrections") or {}).items():
            if field in ("title", "date", "time", "venue", "district", "address",
                         "description", "event_url", "image_url"):
                event[field] = value
            elif field == "price_eur":
                from community_common import classify_price

                event["price_eur"] = value
                event["price_status"] = classify_price(
                    value, str(decision.get("corrections", {}).get("price_note") or "")
                )
        reviewed_events.append(event)

    week = candidates.get("issue_week", {})
    week_start = date.fromisoformat(_iso_date(week.get("start")))
    week_end = date.fromisoformat(
        _iso_date(week.get("end")) or (week_start + timedelta(days=6)).isoformat()
    )
    return build_issue(
        reviewed_events, week_start, week_end,
        status="reviewed",
        generated_at=candidates.get("generated_at"),
    )


def build_approved_issue(
    reviewed: Dict[str, Any],
    week_start: Optional[date] = None,
    week_end: Optional[date] = None,
    *,
    max_price: float = COMMUNITY_MAX_PRICE,
    published_at: Optional[str] = None,
    allow_partial: bool = True,
) -> Dict[str, Any]:
    """The immutable public issue: approved events that pass every rule.

    ``allow_partial`` controls what happens when an approved event fails a
    publication rule. The default keeps the rest of the issue and reports the
    refusal, because one broken event should not blank a whole week; setting
    it to False makes any problem fatal, which is what the promotion CLI uses
    when a human has asked for an all-or-nothing promotion.
    """
    from community_common import iso_now

    week = reviewed.get("issue_week", {})
    if week_start is None:
        raw_start = _iso_date(week.get("start"))
        week_start = date.fromisoformat(raw_start) if raw_start else date.today()
    if week_end is None:
        raw_end = _iso_date(week.get("end"))
        week_end = date.fromisoformat(raw_end) if raw_end else week_start + timedelta(days=6)
    start, end = week_start, week_end

    approved, refused = [], []
    for event in reviewed.get("events", []):
        status = (event.get("community") or {}).get("selection_status")
        if status != SELECTION_APPROVED:
            continue
        problems = publication_problems(event, start, end, max_price)
        if problems:
            refused.append({"event_id": event.get("event_id"), "problems": problems})
            if not allow_partial:
                raise ValueError(
                    f"approved event {event.get('event_id')} is not publishable: "
                    + ", ".join(problems)
                )
            continue
        approved.append(event)

    approved.sort(key=lambda e: (e.get("date") or "9999-12-31", e.get("time") or "99:99",
                                 str(e.get("title") or "").lower()))
    payload = build_issue(
        approved, start, end,
        status="approved",
        generated_at=reviewed.get("generated_at"),
        published_at=published_at or iso_now(),
        summary=reviewed.get("summary"),
    )
    payload["refused"] = refused
    payload["public_count"] = len(approved)
    return payload


def public_latest(approved: Dict[str, Any]) -> Dict[str, Any]:
    """The copy the browser fetches: approved events and nothing about review.

    Draft-only fields (refusals, per-field verification notes, internal
    provenance) are dropped here rather than in the frontend, so a value that
    should not be public is never sent.
    """
    public_events = []
    for event in approved.get("events", []):
        public_events.append({
            "event_id": event.get("event_id"),
            "title": event.get("title"),
            "date": event.get("date"),
            "time": event.get("time"),
            "end_time": event.get("end_time"),
            "venue": event.get("venue"),
            "district": event.get("district"),
            "price_eur": event.get("price_eur"),
            "price_status": event.get("price_status"),
            "price_label": price_label(event),
            "category": event.get("category"),
            "category_label": category_label(event.get("category") or ""),
            "description": event.get("description"),
            "event_url": event.get("event_url"),
            "image_url": event.get("image_url"),
            "recommendation_reason": (event.get("community") or {}).get("recommendation_reason"),
            "verified_at": (event.get("verification") or {}).get("checked_at"),
            "official_source_url": (event.get("verification") or {}).get("official_source_url"),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "issue_week": approved.get("issue_week"),
        "generated_at": approved.get("generated_at"),
        "published_at": approved.get("published_at"),
        "count": len(public_events),
        "events": public_events,
    }


def price_label(event: Dict[str, Any]) -> str:
    """Human price label that never turns an unknown price into "Free"."""
    status = event.get("price_status")
    price = event.get("price_eur")
    if status == PRICE_STATUS_CONFIRMED_FREE:
        return "Free"
    if status == PRICE_STATUS_DONATION:
        return "Donation"
    if status == PRICE_STATUS_NEEDS_VERIFICATION:
        return "Entry to be confirmed"
    if status == PRICE_STATUS_UNKNOWN or price is None:
        return "Price not confirmed"
    value = float(price)
    return f"€{int(value)}" if value.is_integer() else f"€{value:.2f}"


def archive_entry(approved: Dict[str, Any], url_base: str) -> Dict[str, Any]:
    week = approved.get("issue_week", {})
    start = week.get("start") or ""
    return {
        "week_start": start,
        "week_end": week.get("end"),
        "published_at": approved.get("published_at"),
        "count": len(approved.get("events", [])),
        "url": f"{url_base.rstrip('/')}/{start}.json",
    }


def update_archive(index: Dict[str, Any], approved: Dict[str, Any], url_base: str) -> Dict[str, Any]:
    """Merge one published issue into the archive index, newest first.

    Re-publishing the same week replaces its entry rather than duplicating it,
    so a corrected issue does not leave two rows pointing at one file.
    """
    entry = archive_entry(approved, url_base)
    issues = [i for i in index.get("issues", []) if i.get("week_start") != entry["week_start"]]
    issues.append(entry)
    issues.sort(key=lambda i: i.get("week_start") or "", reverse=True)
    updated = dict(index)
    updated["schema_version"] = SCHEMA_VERSION
    updated["issues"] = issues
    updated["count"] = len(issues)
    from community_common import iso_now

    updated["updated_at"] = iso_now()
    return updated


EMPTY_ARCHIVE = {
    "schema_version": SCHEMA_VERSION,
    "issues": [],
    "count": 0,
    "updated_at": None,
}


# --------------------------------------------------------------------------
# Editorial review summary
# --------------------------------------------------------------------------

def _verification_phrase(event: Dict[str, Any]) -> str:
    verification = event.get("verification") or {}
    status = verification.get("status")
    fields = verification.get("fields") or {}
    corrected = sorted(k for k, v in fields.items() if v == "corrected")
    unconfirmed = sorted(k for k, v in fields.items() if v == "not_confirmed")
    if status == VERIFICATION_MATCHED:
        phrase = "matched official page"
    elif status == VERIFICATION_CORRECTED:
        phrase = "corrected from official page: " + ", ".join(corrected)
    elif status == VERIFICATION_REJECTED:
        phrase = "rejected by official page"
    elif status == VERIFICATION_UNCONFIRMED:
        phrase = "not confirmed"
    else:
        phrase = "not yet verified"
    if unconfirmed:
        phrase += " (unconfirmed: " + ", ".join(unconfirmed) + ")"
    return phrase


def _date_phrase(event: Dict[str, Any]) -> str:
    occurrence = _iso_date(event.get("date"))
    start = event.get("time") or ""
    if not occurrence:
        return "date unknown"
    try:
        weekday = datetime.fromisoformat(occurrence).strftime("%a")
    except ValueError:
        weekday = ""
    return f"{weekday} {occurrence}" + (f" {start}" if start else "")


def render_review_summary(
    candidates: Dict[str, Any],
    stats: Optional[Dict[str, Any]] = None,
) -> str:
    """Markdown a human editor can act on without opening the JSON.

    Every proposed event appears with the facts a decision needs, and the
    unresolved list is kept separate so an editor is never asked to approve
    something the pipeline could not check.
    """
    stats = stats or {}
    week = candidates.get("issue_week", {})
    events = candidates.get("events", [])
    proposed = [e for e in events if (e.get("community") or {}).get("selection_status")
                not in (SELECTION_REJECTED,)]
    unresolved_ids = set(stats.get("unresolved_ids") or [])
    proposed = [e for e in proposed if e.get("event_id") not in unresolved_ids]

    lines: List[str] = []
    lines.append(f"# Community review - week of {week.get('start', '?')} to {week.get('end', '?')}")
    lines.append("")
    lines.append(f"Timezone: {ISSUE_TIMEZONE}. Generated: {candidates.get('generated_at', '?')}.")
    lines.append("")

    lines.append("## Run counts")
    lines.append("")
    for label, key in (
        ("Raw events inspected", "raw_inspected"),
        ("Scored candidates inspected", "scored_inspected"),
        ("Newly discovered events", "newly_discovered"),
        ("Independently verified events", "verified_count"),
        ("Rejected", "rejected_count"),
        ("Requiring additional verification", "unresolved_count"),
        ("Proposed for publication", "proposed_count"),
    ):
        if key in stats:
            lines.append(f"- {label}: {stats[key]}")
    lines.append("")

    if stats.get("price_bands"):
        lines.append("## Price bands")
        lines.append("")
        for band, count in stats["price_bands"].items():
            lines.append(f"- {band}: {count}")
        lines.append("")

    if stats.get("categories"):
        lines.append("## Categories")
        lines.append("")
        for name, count in stats["categories"].items():
            lines.append(f"- {category_label(name)} ({name}): {count}")
        lines.append("")

    lines.append("## Proposed selection")
    lines.append("")
    if not proposed:
        lines.append("_No events passed verification for this week._")
        lines.append("")
    for index, event in enumerate(proposed, start=1):
        price = price_label(event)
        verification = _verification_phrase(event)
        image = "yes" if event.get("image_url") else "no"
        venue = event.get("venue") or "venue unknown"
        district = event.get("district") or "district unknown"
        lines.append(f"### {index}. {event.get('title') or 'Untitled'}")
        lines.append("")
        lines.append(f"- When: {_date_phrase(event)}")
        lines.append(f"- Category: {category_label(event.get('category') or '')}")
        lines.append(f"- Where: {venue} ({district})")
        lines.append(f"- Price: {price} ({event.get('price_status')})")
        lines.append(f"- Why: {(event.get('community') or {}).get('recommendation_reason') or '-'}")
        lines.append(f"- Official link: {event.get('event_url') or 'none'}")
        lines.append(f"- Image: {image}")
        lines.append(f"- Verification: {verification}")
        lines.append(f"- Event id: `{event.get('event_id')}`")
        lines.append("")

    if unresolved_ids:
        lines.append("## Unresolved - need another look before they can be proposed")
        lines.append("")
        for event in events:
            if event.get("event_id") not in unresolved_ids:
                continue
            reason = (event.get("verification") or {}).get("notes") or "not confirmed"
            lines.append(
                f"- {event.get('title')} ({_date_phrase(event)}, {price_label(event)}) - "
                f"{reason} - `{event.get('event_id')}`"
            )
        lines.append("")

    lines.append("## How to review")
    lines.append("")
    lines.append(
        f"Create `community/reviewed/{week.get('start', 'YYYY-MM-DD')}.json` with one decision "
        "per event id above, then run the promotion workflow. Nothing is published without it."
    )
    lines.append("")
    return "\n".join(lines)
