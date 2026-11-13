#!/usr/bin/env python3
"""Generate the weekly community candidate issue from the persisted aggregate.

This is the discovery side of the community pipeline, and it is a *reader* of
the scraper's output: it never re-scrapes, never changes the personal
scorer's semantics, and never touches ``data/events.json``. It loads the raw
aggregate, keeps a deliberately broad pool (an unpriced event is a question
for verification, not a reason to drop it), builds the Monday-Sunday issue,
runs bounded official-page verification, and writes one candidate file plus a
human-readable review summary.

The result is *only* a proposal. Nothing written here is public until a
reviewer's decisions are promoted through ``community_promote.py``.

Usage:
    python scripts/community_prepare.py \
        --events data/events.json \
        --scored data/events_scored.json \
        --newsletter-root community \
        --week-start 2026-11-16
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from community_common import (  # noqa: E402
    COMMUNITY_MAX_PRICE,
    COMMUNITY_TARGET_MAX,
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_DONATION,
    PRICE_STATUS_UNKNOWN,
    VERIFICATION_MATCHED,
    VERIFICATION_REJECTED,
    canonical_url,
    classify_price,
    in_issue_week,
    iso_now,
    next_week_bounds,
    now_berlin,
    price_status_for,
    classify_category,
    district_from_text,
    stable_event_id,
    week_bounds,
)
from community_issue import (  # noqa: E402
    build_candidate_issue,
    event_record,
    render_review_summary,
)
from community_select import (  # noqa: E402
    apply_community_metadata,
    category_distribution,
    meets_weekly_target,
    price_band_distribution,
    select_community_events,
)
from community_verify import official_url_for, verify_events  # noqa: E402
from community_image_stats import image_stats  # noqa: E402


def load_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def events_from(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        events = payload.get("events")
        return events if isinstance(events, list) else []
    return payload if isinstance(payload, list) else []


def _upper_bound(raw: Dict[str, Any], entry: Optional[float]) -> Optional[float]:
    """The upper bound of a price span, or the entry price for a single price.

    The upstream evidence model records ``price_max`` for a range and leaves it
    equal to ``price`` otherwise. A missing upper bound is never invented: when
    the source gave one number, that number is both bounds, and when the source
    gave nothing there is no span at all.
    """
    raw_max = raw.get("price_max", raw.get("price_max_eur"))
    if raw_max is None:
        return entry
    try:
        value = float(raw_max)
    except (TypeError, ValueError):
        return entry
    if entry is not None and value < float(entry):
        # An inverted span is a parsing error; the entry price is authoritative.
        return entry
    return value


def previous_event_ids(newsletter_root: str, limit: int = 4) -> set:
    """Ids from recently published issues, for the "newly discovered" count.

    Provenance only: a recurring club night is a genuinely new *occurrence*
    each week, so this never removes a row.
    """
    seen: set = set()
    approved_dir = Path(newsletter_root) / "approved"
    if not approved_dir.is_dir():
        return seen
    files = sorted(approved_dir.glob("*.json"), reverse=True)[:limit]
    for path in files:
        payload = load_json(str(path), {}) or {}
        for event in payload.get("events", []) or []:
            if isinstance(event, dict) and event.get("event_id"):
                seen.add(event["event_id"])
    return seen


def discovery_pool(
    raw_events: Sequence[Dict[str, Any]],
    week_start: date,
    week_end: date,
    max_price: float = COMMUNITY_MAX_PRICE,
) -> List[Dict[str, Any]]:
    """Every row worth taking to verification, including unpriced ones.

    The personal pipeline's job is to publish a priced list now; this pool's
    job is to give verification something to confirm. So an event with no
    stated price stays in - it is exactly the row an official page can settle -
    while an event whose *confirmed* price is over the cap is dropped, since
    no verification can change that.

    Deduplication here is on canonical URL plus occurrence, not on title:
    two different sources listing the same show should collapse, but two
    differently-named events in one venue must not.
    """
    pool: List[Dict[str, Any]] = []
    seen = set()
    for raw in raw_events or []:
        if not isinstance(raw, dict):
            continue
        occurrence = str(raw.get("date") or "")[:10]
        if not in_issue_week(occurrence, week_start, week_end):
            continue
        title = " ".join(str(raw.get("title") or "").split())
        if not title:
            continue
        event_url = canonical_url(str(raw.get("url") or raw.get("event_url") or ""))
        source_url = canonical_url(str(raw.get("source_url") or ""))
        key = (event_url or title.lower(), occurrence, str(raw.get("time") or ""))
        if key in seen:
            continue
        seen.add(key)

        price_raw = raw.get("price")
        price = None
        if price_raw is not None:
            try:
                price = float(price_raw)
            except (TypeError, ValueError):
                price = None
        # `price_status_for` reads both vocabularies, so a row stamped by the
        # scoring pass arrives with its evidence already honoured, and a raw
        # row is classified from its own price and text.
        price_status = price_status_for({**raw, "price_eur": price})
        # A *confirmed* price above the community cap is final; an unknown one
        # is not, and must survive to verification.
        if price is not None and price > max_price:
            continue

        event = {
            # Always a community id. The aggregate may carry an `event_id` from
            # the scraping pipeline (ticket_evidence assigns `sha256:...`), and
            # adopting that would put a foreign namespace into the candidate
            # file where the schemas and the promotion tool require `ce-...`.
            # Discovery is also the wrong place to inherit an approval-facing
            # identifier: the id has to mean one thing across all three files.
            "event_id": stable_event_id(
                title, event_url or source_url, occurrence,
                venue=str(raw.get("venue") or ""), time=str(raw.get("time") or ""),
            ),
            "title": title,
            "date": occurrence,
            "time": str(raw.get("time") or "") or None,
            "venue": str(raw.get("venue") or ""),
            "district": raw.get("district"),
            "address": raw.get("address"),
            "price_eur": price,
            # Both bounds are carried from discovery onward. A range whose
            # upper bound is dropped here becomes indistinguishable from a
            # single price by the time it reaches review, which is exactly
            # the information a reviewer needs to see.
            "price_max_eur": _upper_bound(raw, price),
            "price_status": price_status,
            "price_note": None,
            "category": "",
            "description": str(raw.get("description") or ""),
            "event_url": event_url,
            "listing_url": source_url or None,
            "source_url": source_url or None,
            "scraped_at": raw.get("scraped_at"),
            "image_url": raw.get("image_url"),
            "image_source": raw.get("image_source"),
            "image_verified": raw.get("image_verified"),
            "image_checked_at": raw.get("image_checked_at"),
            "verification": {
                "status": "pending",
                "checked_at": None,
                "official_source_url": event_url or None,
                "fields": {},
                "corrections": [],
                "notes": "",
            },
        }
        pool.append(event)
    return pool


def prepare_issue(
    raw_events: Sequence[Dict[str, Any]],
    scored_payload: Any,
    week_start: date,
    week_end: date,
    *,
    newsletter_root: str = "community",
    fetch=None,
    verify: bool = True,
    max_verifications: int = 40,
    target: int = COMMUNITY_TARGET_MAX,
    max_price: float = COMMUNITY_MAX_PRICE,
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    """Build (candidate_issue, review_summary_markdown, stats)."""
    seen_before = previous_event_ids(newsletter_root)
    pool = discovery_pool(raw_events, week_start, week_end, max_price)

    # Categories/districts are needed before selection, so that the diversity
    # penalty has something to work with.
    for event in pool:
        event["category"] = classify_category(
            event["title"], event.get("venue") or "", event.get("description") or ""
        )
        if not event.get("district"):
            event["district"] = district_from_text(
                event.get("venue") or "", event.get("address") or "",
                event.get("description") or "",
            )
        # The pool is built before verification, so its price status comes from
        # the row as aggregated - including the scraping pipeline's evidence
        # status when the row carries one.
        event["price_status"] = price_status_for(event)

    selected, _ = select_community_events(pool, target=target, max_price=max_price)

    for event in selected:
        apply_community_metadata(event)

    verified_count = 0
    rejected_count = 0
    unresolved_ids: List[str] = []
    if verify and selected:
        if fetch is None:
            from generic_event_scraper import fetch_plain

            fetch = fetch_plain
        verify_events(selected, fetch, max_verifications=max_verifications)
        for event in selected:
            status = (event.get("verification") or {}).get("status")
            if status in (VERIFICATION_MATCHED, "corrected"):
                verified_count += 1
            if status == VERIFICATION_REJECTED:
                rejected_count += 1
                (event["community"] or {})["selection_status"] = "rejected"
            if status in ("not_confirmed", "pending"):
                unresolved_ids.append(event["event_id"])

    proposed = [
        event for event in selected
        if (event.get("community") or {}).get("selection_status") != "rejected"
    ]
    # The reason is rebuilt *after* verification, not before it. A verified
    # correction can move the venue, the price or the time, and a reason
    # written from the scraped values would then contradict the record it
    # sits next to - "Free at Michelberger Hotel" on a card that reads
    # "Kantine" in the list above it.
    from community_select import build_recommendation_reason

    for event in proposed:
        event.setdefault("community", {})["recommendation_reason"] = build_recommendation_reason(event)

    stats: Dict[str, Any] = {
        "raw_inspected": len(raw_events or []),
        "scored_inspected": len(events_from(scored_payload)),
        "discovery_pool": len(pool),
        "selected_count": len(selected),
        "proposed_count": len(proposed),
        "verified_count": verified_count,
        "rejected_count": rejected_count,
        "unresolved_count": len(unresolved_ids),
        "unresolved_ids": unresolved_ids,
        "newly_discovered": sum(
            1 for event in proposed if event.get("event_id") not in seen_before
        ),
        "price_bands": price_band_distribution(proposed),
        "categories": category_distribution(proposed),
        "meets_target": meets_weekly_target(proposed),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "generated_at": iso_now(),
        # The coverage of the input aggregate, so a request for a week the
        # scraper has never covered can say so instead of looking empty.
        "aggregate_start": min(
            (str(e.get("date"))[:10] for e in raw_events or []
             if e.get("date")), default=None),
        "aggregate_end": max(
            (str(e.get("date"))[:10] for e in raw_events or []
             if e.get("date")), default=None),
        # Coverage is reported over the whole discovery pool, not just the
        # shortlist: the point is whether the scrape is finding artwork, and a
        # pool-wide count answers that. Failures here never affect selection.
        "images": image_stats(pool),
    }

    issue_events = []
    for event in selected:
        record = event_record(event, week_start=week_start, week_end=week_end)
        if record:
            # Keep the review verdict and verification work this run produced.
            record["community"] = event.get("community") or record["community"]
            record["verification"] = event.get("verification") or record["verification"]
            issue_events.append(record)

    candidates = build_candidate_issue(issue_events, week_start, week_end, stats)
    summary = render_review_summary(candidates, stats)
    return candidates, summary, stats


def resolve_week(start_arg: Optional[str], end_arg: Optional[str]) -> Tuple[date, date]:
    """Explicit range wins; otherwise the week after the current one."""
    if start_arg:
        start = date.fromisoformat(start_arg)
    else:
        start = next_week_bounds()[0]
    if end_arg:
        end = date.fromisoformat(end_arg)
    else:
        from datetime import timedelta

        end = start + timedelta(days=6)
    if end < start:
        raise SystemExit(f"--week-end {end} is before --week-start {start}")
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the weekly community candidate issue"
    )
    parser.add_argument("--events", default="data/events.json",
                        help="Persisted raw aggregate (default data/events.json)")
    parser.add_argument("--scored", default="data/events_scored.json",
                        help="Scored output, read for reference counts only")
    parser.add_argument("--newsletter-root", default="community",
                        help="Community folder root (default community)")
    parser.add_argument("--week-start", help="First day of the issue window (YYYY-MM-DD)")
    parser.add_argument("--week-end", help="Last day of the issue window (YYYY-MM-DD)")
    parser.add_argument("--target", type=int, default=COMMUNITY_TARGET_MAX,
                        help=f"Shortlist ceiling (default {COMMUNITY_TARGET_MAX})")
    parser.add_argument("--max-price", type=float, default=COMMUNITY_MAX_PRICE,
                        help=f"Community recommendation cap (default {COMMUNITY_MAX_PRICE:g})")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip official-page verification (offline runs, tests)")
    parser.add_argument("--max-verifications", type=int, default=40,
                        help="Upper bound on official pages fetched (default 40)")
    parser.add_argument("--output", help="Candidate file path (default candidates/<start>.json)")
    parser.add_argument("--summary-output", help="Review summary path (default reviewed/<start>.md)")
    args = parser.parse_args()

    week_start, week_end = resolve_week(args.week_start, args.week_end)
    raw = load_json(args.events, {}) or {}
    scored = load_json(args.scored, {}) or {}
    raw_events = events_from(raw)

    candidates, summary, stats = prepare_issue(
        raw_events, scored, week_start, week_end,
        newsletter_root=args.newsletter_root,
        verify=not args.no_verify,
        max_verifications=args.max_verifications,
        target=args.target,
        max_price=args.max_price,
    )

    root = Path(args.newsletter_root)
    output = Path(args.output) if args.output else root / "candidates" / f"{week_start.isoformat()}.json"
    summary_path = (Path(args.summary_output) if args.summary_output
                    else root / "reviewed" / f"{week_start.isoformat()}.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_path.write_text(summary, encoding="utf-8")

    print(
        f"Community candidates for {week_start}..{week_end}: "
        f"{stats['proposed_count']} proposed from {stats['discovery_pool']} discovered "
        f"({stats['verified_count']} verified, {stats['unresolved_count']} unresolved, "
        f"{stats['rejected_count']} rejected)"
    )
    print(f"  candidates -> {output}")
    print(f"  review summary -> {summary_path}")
    images = stats.get("images", {}).get("totals", {})
    if images:
        print(
            f"  image coverage: {images.get('with_image', 0)}/{images.get('events', 0)} "
            f"({images.get('coverage_percent', 0.0)}%), "
            f"{images.get('rejected', 0)} failed, {images.get('unchecked', 0)} unchecked"
        )
    if not stats["discovery_pool"]:
        # Loud, because the alternative is a silently empty week: the
        # aggregate only covers the window the scraper last ran for, so a
        # request for a future week needs a scrape covering that week first.
        print(
            f"  warning: no events discovered for {week_start}..{week_end}. "
            f"The persisted aggregate covers {stats.get('aggregate_start', '?')}.."
            f"{stats.get('aggregate_end', '?')}; re-run the scraper for this window "
            "before reviewing."
        )
    if not stats["meets_target"]:
        print(
            f"  note: fewer than 20 events passed verification this week; "
            "the shortlist was not padded"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
