#!/usr/bin/env python3
"""Promote a reviewed candidate issue into the public community issue.

This is the approval gate, and it is deliberately a separate, explicit
operation: nothing about scraping, scoring or verification publishes an event,
and no rule here infers approval from a high score. The only input that can
approve an event is a human-written decision naming its id.

What it does, in order:

  1. Reads the candidate issue for a week and the reviewer's decision file.
  2. Refuses unknown ids rather than ignoring them - a decision naming an id
     that is not in the candidate file means the reviewer was looking at a
     different week.
  3. Re-checks every *approved* event against the publication rules
     (in-week, confirmed price at or under the cap, verified identity and
     date, not cancelled). A failing event is reported and, by default,
     excluded - never silently published.
  4. Writes the immutable approved issue, the public latest.json, and the
     archive index.

Refusing is always louder than publishing: an ambiguous or incomplete review
exits non-zero with the reason, so a scheduled run cannot half-publish a week.

Usage:
    python scripts/community_promote.py \
        --newsletter-root community \
        --week-start 2026-11-16 \
        --require-complete
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from community_common import (  # noqa: E402
    COMMUNITY_MAX_PRICE,
    DECISION_APPROVED,
    DECISION_REJECTED,
    SELECTION_APPROVED,
    iso_now,
)
from community_issue import (  # noqa: E402
    EMPTY_ARCHIVE,
    build_approved_issue,
    build_reviewed_issue,
    public_latest,
    update_archive,
)

# Where the published issue files are linked from on the project site. Kept
# relative so the page works under /event-scraper-github-actions/community/.
DEFAULT_ARCHIVE_BASE = "archive"


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def validate_decisions(candidates: Dict[str, Any], decisions: Dict[str, Any]) -> List[str]:
    """Structural problems with a decision file, as human-readable strings."""
    problems: List[str] = []
    known = {event.get("event_id") for event in candidates.get("events", [])}
    week = (candidates.get("issue_week") or {}).get("start")
    declared = decisions.get("issue_week_start")
    if declared and week and declared != week:
        problems.append(
            f"decision file is for week {declared}, but the candidate issue is {week}"
        )
    seen = set()
    for index, decision in enumerate(decisions.get("decisions") or []):
        event_id = decision.get("event_id")
        verdict = decision.get("decision")
        if not event_id:
            problems.append(f"decision #{index + 1} has no event_id")
            continue
        if event_id in seen:
            problems.append(f"decision for {event_id} appears more than once")
        seen.add(event_id)
        if event_id not in known:
            problems.append(f"decision names unknown event id {event_id}")
        if verdict not in (DECISION_APPROVED, DECISION_REJECTED):
            problems.append(f"decision for {event_id} has invalid verdict {verdict!r}")
    if problems:
        return problems
    if not seen:
        problems.append("decision file contains no decisions")
    return problems


def promote(
    newsletter_root: str,
    week_start: str,
    *,
    max_price: float = COMMUNITY_MAX_PRICE,
    require_complete: bool = False,
    archive_base: str = DEFAULT_ARCHIVE_BASE,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the promotion and return a report; raises ValueError on refusal."""
    root = Path(newsletter_root)
    candidate_path = root / "candidates" / f"{week_start}.json"
    decision_path = root / "reviewed" / f"{week_start}.json"
    candidates = load_json(candidate_path)
    if not candidates:
        raise ValueError(f"no candidate issue at {candidate_path}")
    decisions = load_json(decision_path)
    if not decisions:
        raise ValueError(
            f"no review decisions at {decision_path} - nothing is approved, "
            "so nothing is published"
        )

    problems = validate_decisions(candidates, decisions)
    if problems:
        raise ValueError("invalid review decisions: " + "; ".join(problems))

    reviewed = build_reviewed_issue(candidates, decisions["decisions"])
    approved = build_approved_issue(
        reviewed, max_price=max_price,
        published_at=iso_now(),
        allow_partial=not require_complete,
    )

    approved_ids = {event["event_id"] for event in approved.get("events", [])}
    requested = {
        d["event_id"] for d in decisions["decisions"]
        if d.get("decision") == DECISION_APPROVED
    }
    missing = requested - approved_ids
    if missing and require_complete:
        raise ValueError(
            "approved events failed publication rules: "
            + ", ".join(sorted(missing))
        )

    report = {
        "week_start": week_start,
        "approved_requested": len(requested),
        "published": len(approved.get("events", [])),
        "refused": approved.get("refused", []),
        "status": approved.get("status"),
        "publication": approved.get("publication", {}),
    }
    if dry_run:
        report["dry_run"] = True
        return report

    approved_dir = root / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    approved_path = approved_dir / f"{week_start}.json"
    approved_path.write_text(
        json.dumps(approved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    latest = public_latest(approved)
    (root / "latest.json").write_text(
        json.dumps(latest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    archive_path = root / "archive" / "index.json"
    archive = load_json(archive_path, dict(EMPTY_ARCHIVE)) or dict(EMPTY_ARCHIVE)
    archive = update_archive(archive, approved, archive_base)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(
        json.dumps(archive, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    report["approved_file"] = str(approved_path)
    report["latest_file"] = str(root / "latest.json")
    report["archive_file"] = str(archive_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote reviewed community candidates into the public issue"
    )
    parser.add_argument("--newsletter-root", default="community")
    parser.add_argument("--week-start", required=True,
                        help="Issue week start (YYYY-MM-DD), matching the candidate file")
    parser.add_argument("--max-price", type=float, default=COMMUNITY_MAX_PRICE)
    parser.add_argument("--require-complete", action="store_true",
                        help="Fail the whole promotion if any approved event is "
                             "unpublishable, instead of excluding it and reporting")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be published without writing anything")
    args = parser.parse_args()

    try:
        date.fromisoformat(args.week_start)
    except ValueError:
        print(f"::error::--week-start {args.week_start!r} is not a YYYY-MM-DD date")
        return 2

    try:
        report = promote(
            args.newsletter_root, args.week_start,
            max_price=args.max_price,
            require_complete=args.require_complete,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"::error::{exc}")
        return 1

    if report.get("dry_run"):
        print(f"Dry run: would publish {report['published']} of "
              f"{report['approved_requested']} approved events for {report['week_start']}")
    else:
        print(f"Published {report['published']} of {report['approved_requested']} "
              f"approved events for {report['week_start']}")
        print(f"  approved -> {report['approved_file']}")
        print(f"  latest   -> {report['latest_file']}")
        print(f"  archive  -> {report['archive_file']}")
    publication = report.get("publication") or {}
    if publication and not publication.get("complete", True):
        # Loud on purpose: this is the visible signal that a run published
        # less than the reviewer asked for, without failing the publication.
        print(
            f"::warning::Incomplete publication: {publication.get('excluded', 0)} approved "
            f"event(s) were excluded for {', '.join(publication.get('exclusion_reasons', []))}"
        )
    for refused in report.get("refused", []):
        print(f"  refused {refused['event_id']}: {', '.join(refused['problems'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
