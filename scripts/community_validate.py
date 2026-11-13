#!/usr/bin/env python3
"""Validate a community issue against its schema and its publication rules.

Two layers, because they catch different mistakes:

  * **Schema** - types, enums, date and id shapes. This is the published
    contract, and a candidate that violates it would break the frontend or
    the promotion tool.
  * **Business rules** - the things a schema cannot express: dates inside the
    issue week, no unknown price presented as free, no duplicate occurrence,
    no approved event that fails a publication rule.

The schema check uses ``jsonschema`` when it is installed and falls back to a
hand-written structural check otherwise, so the workflow does not gain a hard
dependency for a check it can perform itself. The business-rule check always
runs, and is the one that actually protects publication.

Usage:
    python scripts/community_validate.py --issue community/candidates/2026-11-16.json --kind candidates
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from community_common import (  # noqa: E402
    COMMUNITY_MAX_PRICE,
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_DONATION,
    PRICE_STATUSES,
    SCHEMA_VERSION,
    VERIFICATION_MATCHED,
    VERIFICATION_REJECTED,
    in_issue_week,
)
from community_issue import publication_problems  # noqa: E402
import price_status  # noqa: E402

KINDS = ("candidates", "reviewed", "approved")

EVENT_ID_RE = None
DATE_RE = None
TIME_RE = None


def _regexes():
    import re

    global EVENT_ID_RE, DATE_RE, TIME_RE
    EVENT_ID_RE = re.compile(r"^ce-[0-9a-f]{24}$")
    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def structural_problems(issue: Dict[str, Any]) -> List[str]:
    """The schema's contract, checked without a third-party validator.

    Mirrors ``community/schema/community-event.schema.json``. Kept deliberately
    small: it checks what the frontend and the promotion tool actually depend
    on, not every optional field.
    """
    _regexes()
    problems: List[str] = []
    if not isinstance(issue, dict):
        return ["issue is not a JSON object"]
    if issue.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION!r}")
    week = issue.get("issue_week") or {}
    if not isinstance(week, dict):
        problems.append("issue_week is not an object")
    else:
        for key in ("start", "end"):
            value = week.get(key)
            if not value or not DATE_RE.match(str(value)):
                problems.append(f"issue_week.{key} is not a YYYY-MM-DD date")
        if week.get("timezone") != "Europe/Berlin":
            problems.append("issue_week.timezone must be 'Europe/Berlin'")
    if issue.get("status") is not None and issue.get("status") not in KINDS:
        problems.append(f"status must be one of {KINDS}")
    if not isinstance(issue.get("generated_at"), (str, type(None))):
        problems.append("generated_at must be a string or null")
    events = issue.get("events")
    if not isinstance(events, list):
        return problems + ["events is not a list"]

    seen_ids = set()
    for index, event in enumerate(events):
        where = f"events[{index}]"
        if not isinstance(event, dict):
            problems.append(f"{where} is not an object")
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not EVENT_ID_RE.match(event_id):
            problems.append(f"{where}.event_id is not a stable id (ce-<24 hex>)")
        elif event_id in seen_ids:
            problems.append(f"{where}.event_id {event_id} appears more than once")
        else:
            seen_ids.add(event_id)
        if not str(event.get("title") or "").strip():
            problems.append(f"{where}.title is empty")
        if not DATE_RE.match(str(event.get("date") or "")):
            problems.append(f"{where}.date is not a YYYY-MM-DD date")
        for field in ("time", "end_time"):
            value = event.get(field)
            if value is not None and not TIME_RE.match(str(value)):
                problems.append(f"{where}.{field} is not HH:MM or null")
        status = event.get("price_status")
        if not price_status.is_canonical(status):
            problems.append(
                f"{where}.price_status {status!r} is not a canonical status; "
                f"expected one of {', '.join(price_status.CANONICAL_STATUSES)}"
            )
        price = event.get("price_eur")
        if price is not None and (not isinstance(price, (int, float)) or float(price) < 0):
            problems.append(f"{where}.price_eur must be a non-negative number or null")
        if status == PRICE_STATUS_CONFIRMED_FREE and price not in (None, 0, 0.0):
            problems.append(f"{where} is confirmed_free but price_eur is {price}")
        if status in (price_status.UNKNOWN, price_status.NEEDS_VERIFICATION) and price == 0:
            problems.append(f"{where} claims price 0 while its price is {status}")
        # Range bounds must describe a real, ordered span around the entry
        # price. An inverted span is a rejection, not something to repair: the
        # two numbers contradict each other, so the evidence is wrong and
        # silently "fixing" it would hide that from every later reader.
        upper = event.get("price_max_eur")
        if upper is not None and (not isinstance(upper, (int, float)) or float(upper) < 0):
            problems.append(f"{where}.price_max_eur must be a non-negative number or null")
        span_problem = price_status.malformed_span_reason(event)
        if span_problem:
            problems.append(
                f"{where} has an inverted price span: {span_problem}"
            )
        if status == price_status.RANGE and price is None:
            problems.append(
                f"{where} is a range with no entry price; a span that establishes "
                "no lower bound cannot be compared to the cap"
            )
        for field in ("event_id", "title", "date", "venue", "price_eur", "price_status",
                      "category", "event_url", "verification", "community"):
            if field not in event:
                problems.append(f"{where} is missing required field {field!r}")
        verification = event.get("verification") or {}
        if not isinstance(verification, dict):
            problems.append(f"{where}.verification is not an object")
        else:
            if "status" not in verification:
                problems.append(f"{where}.verification has no status")
            fields = verification.get("fields")
            if fields is not None and not isinstance(fields, dict):
                problems.append(f"{where}.verification.fields is not an object")
        community = event.get("community") or {}
        if not isinstance(community, dict):
            problems.append(f"{where}.community is not an object")
        elif community.get("selection_status") not in (
            "proposed", "approved", "rejected", "unresolved"
        ) and community.get("selection_status") is not None:
            problems.append(f"{where}.community.selection_status is invalid")
    return problems


def schema_problems(issue: Dict[str, Any], schema_path: Optional[Path]) -> List[str]:
    """Full JSON Schema validation when jsonschema is available, else []."""
    if not schema_path or not Path(schema_path).is_file():
        return []
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(issue), key=lambda e: list(e.absolute_path))
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors[:40]
    ]


def business_problems(issue: Dict[str, Any], kind: str,
                      max_price: float = COMMUNITY_MAX_PRICE) -> List[str]:
    """Rules the schema cannot express, checked for every issue kind."""
    problems: List[str] = []
    week = issue.get("issue_week") or {}
    try:
        start = date.fromisoformat(str(week.get("start")))
        end = date.fromisoformat(str(week.get("end")))
    except (TypeError, ValueError):
        return ["issue_week start/end are not usable dates, so no rule can be checked"]
    if end < start:
        problems.append("issue_week.end is before issue_week.start")
    if (end - start).days > 6:
        problems.append("issue week spans more than seven days")

    seen_occurrences = {}
    for event in issue.get("events", []):
        if not isinstance(event, dict):
            continue
        event_id = event.get("event_id")
        occurrence = (event.get("date"), str(event.get("venue") or "").lower(),
                      event.get("event_url"))
        if occurrence in seen_occurrences and seen_occurrences[occurrence] != event_id:
            problems.append(
                f"duplicate occurrence: {event_id} and {seen_occurrences[occurrence]} "
                f"describe the same event on {event.get('date')}"
            )
        seen_occurrences[occurrence] = event_id

        if not in_issue_week(event.get("date"), start, end):
            problems.append(f"{event_id}: date {event.get('date')} is outside the issue week")

        status = event.get("price_status")
        price = event.get("price_eur")
        if status == PRICE_STATUS_CONFIRMED_PAID and price is not None \
                and float(price) > max_price:
            label = "published" if kind == "approved" else "proposed"
            problems.append(
                f"{event_id}: {label} with a price of EUR {price} above the "
                f"EUR {max_price:g} community cap"
            )

        verification = event.get("verification") or {}
        verification_status = verification.get("status")
        if verification_status == VERIFICATION_REJECTED:
            if kind == "approved":
                problems.append(f"{event_id}: approved but verification rejected it")
            elif kind == "candidates":
                # Allowed in a candidate file (it is a record of the check),
                # but it must not be presented as a proposal.
                selection = (event.get("community") or {}).get("selection_status")
                if selection != "rejected":
                    problems.append(
                        f"{event_id}: verification rejected it but selection_status is "
                        f"{selection!r}"
                    )

    if kind == "approved":
        for event in issue.get("events", []):
            if not isinstance(event, dict):
                continue
            event_id = event.get("event_id")
            selection = (event.get("community") or {}).get("selection_status")
            if selection != "approved":
                problems.append(
                    f"{event_id}: present in an approved issue with selection_status "
                    f"{selection!r}"
                )
            for problem in publication_problems(event, start, end, max_price):
                problems.append(f"{event_id}: not publishable ({problem})")
    return problems


def validate_issue(
    issue: Dict[str, Any],
    kind: str,
    schema_path: Optional[Path] = None,
    max_price: float = COMMUNITY_MAX_PRICE,
    check_schema: bool = True,
) -> Tuple[List[str], List[str], List[str]]:
    """Returns (schema problems, structural problems, business problems)."""
    schema = schema_problems(issue, schema_path) if check_schema else []
    structural = structural_problems(issue)
    business = business_problems(issue, kind, max_price)
    return schema, structural, business


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a community issue file")
    parser.add_argument("--issue", required=True, help="Path to the issue JSON")
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--schema", default="community/schema/community-event.schema.json")
    parser.add_argument("--max-price", type=float, default=COMMUNITY_MAX_PRICE)
    parser.add_argument("--no-schema", action="store_true",
                        help="Skip the JSON Schema layer (structural checks still run)")
    args = parser.parse_args()

    try:
        issue = json.loads(Path(args.issue).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::could not read {args.issue}: {exc}")
        return 2

    schema, structural, business = validate_issue(
        issue, args.kind, Path(args.schema), args.max_price,
        check_schema=not args.no_schema,
    )
    label = f"{args.issue} ({args.kind})"
    if not (schema or structural or business):
        events = len(issue.get("events", []))
        print(f"{label}: valid, {events} events.")
        return 0

    for problem in schema:
        print(f"::error::{label} schema: {problem}")
    for problem in structural:
        print(f"::error::{label}: {problem}")
    for problem in business:
        print(f"::error::{label}: {problem}")
    print(
        f"{label}: {len(schema) + len(structural) + len(business)} problem(s) "
        f"(schema {len(schema)}, structure {len(structural)}, rules {len(business)})"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
