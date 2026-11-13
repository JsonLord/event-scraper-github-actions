"""Inverted price ranges are reported, never silently repaired.

A span runs low-to-high. When the upper bound is *below* the entry price the two
numbers contradict each other, so the evidence is wrong - not the presentation.

The behaviour this replaced is the reason these tests exist. `event_record()`
used to rewrite the upper bound up to the entry price:

    if price_max < price:
        price_max = price

That made the record look like a valid single-price event *before* the
structural validator ever ran, so a malformed range could reach publication with
its defect erased. Worse, an inverted span whose entry price happened to sit
under the €15 cap passed `publication_problems` - the only check that looked at
the bounds was the one being bypassed.

The fix is a detection function (`price_status.malformed_span_reason`) used by
a gate that reads the *record*, not its builder, because an inversion can be
introduced after construction by a verification correction or a human review
correction. Those paths never pass through `event_record()`, which is exactly
why changing that function alone would not have been sufficient.
"""

import json
from datetime import date

import pytest

from scripts import price_status
from scripts.community_common import PRICE_STATUS_RANGE
from scripts.community_issue import (
    build_approved_issue,
    build_candidate_issue,
    build_reviewed_issue,
    event_record,
    price_label,
    publication_problems,
    public_latest,
    render_review_summary,
)
from scripts.community_validate import structural_problems

WEEK_START = date(2026, 11, 16)
WEEK_END = date(2026, 11, 22)
EVENT_ID = "ce-" + "a" * 24


def _candidate(entry=5.0, upper=15.0):
    return {
        "event_id": EVENT_ID,
        "title": "Inverted Gig",
        "date": "2026-11-20",
        "time": "20:00",
        "venue": "Kantine",
        "district": "Kreuzberg",
        "price_eur": entry,
        "price_max_eur": upper,
        "price_status": PRICE_STATUS_RANGE,
        "price_note": None,
        "category": "music",
        "description": "Ein Abend mit Livemusik.",
        "event_url": "https://x.de/e",
        "verification": {"status": "matched", "fields": {"title": "match",
                                                          "date": "match"},
                         "corrections": [], "notes": ""},
        "community": {"recommendation_reason": "x", "selection_score": 10,
                      "price_priority": "paid", "selection_status": "proposed"},
    }


def _issued(record):
    return {"schema_version": "1.0", "status": "candidates",
            "issue_week": {"start": "2026-11-16", "end": "2026-11-22",
                           "timezone": "Europe/Berlin"},
            "generated_at": "2026-11-15T18:00:00+01:00", "events": [record]}


def _approve(record, corrections=None):
    issue = build_candidate_issue([record], WEEK_START, WEEK_END, {})
    decision = {"event_id": record["event_id"], "decision": "approved"}
    if corrections:
        decision["corrections"] = corrections
    return build_approved_issue(build_reviewed_issue(issue, [decision]),
                                WEEK_START, WEEK_END)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def test_an_inverted_span_is_detected():
    reason = price_status.malformed_span_reason({"price_eur": 15.0, "price_max_eur": 5.0})
    assert reason is not None
    assert "below the entry price" in reason


def test_a_valid_span_is_not_flagged():
    assert price_status.malformed_span_reason({"price_eur": 5.0, "price_max_eur": 15.0}) is None


def test_an_equal_span_is_not_flagged():
    """A single price is stored as entry == upper; that is not inverted."""
    assert price_status.malformed_span_reason({"price_eur": 12.0, "price_max_eur": 12.0}) is None


def test_a_missing_bound_is_not_flagged():
    assert price_status.malformed_span_reason({"price_eur": 12.0, "price_max_eur": None}) is None
    assert price_status.malformed_span_reason({"price_eur": None, "price_max_eur": 5.0}) is None


def test_detection_is_read_from_the_record_not_its_builder():
    """It must work on a record mutated after construction."""
    record = _candidate(5.0, 15.0)
    assert not price_status.has_malformed_span(record)
    record["price_eur"] = 20.0          # as a correction would
    assert price_status.has_malformed_span(record)


# --------------------------------------------------------------------------
# Candidate generation preserves the evidence
# --------------------------------------------------------------------------

def test_candidate_generation_does_not_repair_an_inverted_range():
    bad = event_record(
        {"title": "Y", "date": "2026-11-20", "venue": "K", "url": "https://x.de/e2",
         "description": "d", "price": 15.0, "price_max": 5.0, "price_status": "range"},
        week_start=WEEK_START, week_end=WEEK_END,
    )
    assert bad["price_eur"] == 15.0
    assert bad["price_max_eur"] == 5.0
    assert price_status.has_malformed_span(bad)


def test_the_inverted_numbers_survive_a_json_round_trip():
    bad = event_record(
        {"title": "Y", "date": "2026-11-20", "venue": "K", "url": "https://x.de/e2",
         "description": "d", "price": 15.0, "price_max": 5.0, "price_status": "range"},
        week_start=WEEK_START, week_end=WEEK_END,
    )
    decoded = json.loads(json.dumps(bad))
    assert (decoded["price_eur"], decoded["price_max_eur"]) == (15.0, 5.0)
    assert price_status.has_malformed_span(decoded)


# --------------------------------------------------------------------------
# Structural validation rejects
# --------------------------------------------------------------------------

def test_structural_validation_rejects_an_inverted_span():
    record = _candidate(12.0, 8.0)
    problems = structural_problems(_issued(record))
    assert any("inverted price span" in p for p in problems), problems


# --------------------------------------------------------------------------
# Publication is refused, including under the cap
# --------------------------------------------------------------------------

def test_an_inverted_span_is_not_publishable():
    assert "price_span_inverted" in publication_problems(
        _candidate(12.0, 8.0), WEEK_START, WEEK_END
    )


def test_an_inverted_span_under_the_cap_is_still_not_published():
    """The case that used to slip through.

    Entry €12 is inside the €15 cap, so the cap check passes. Only the span
    check catches it - and before this fix there was no span check on the
    publication path at all.
    """
    approved = _approve(_candidate(12.0, 8.0))
    assert approved["events"] == []
    assert "price_span_inverted" in approved["refused"][0]["problems"]
    assert public_latest(approved)["events"] == []


def test_a_review_correction_that_inverts_a_span_is_refused():
    """The reachable path: a human correction moves the entry above the upper."""
    approved = _approve(_candidate(5.0, 8.0), corrections={"price_eur": 12.0})
    assert approved["events"] == []
    assert "price_span_inverted" in approved["refused"][0]["problems"]


def test_a_verification_correction_that_inverts_a_span_is_refused():
    """The other reachable path: an official page states a higher price."""
    from scripts.community_verify import apply_corrections

    record = _candidate(5.0, 15.0)
    apply_corrections(record, {"price_eur": 20.0})
    assert price_status.has_malformed_span(record)
    assert "price_span_inverted" in publication_problems(record, WEEK_START, WEEK_END)
    approved = _approve(record)
    assert approved["events"] == []


def test_partial_publication_reports_the_inverted_event():
    good = _candidate(5.0, 15.0)
    good["event_id"] = "ce-" + "b" * 24
    good["title"] = "Good Gig"
    good["community"]["selection_status"] = "approved"
    bad = _candidate(12.0, 8.0)
    approval = _approve(good)
    assert len(approval["events"]) == 1, "a valid range must still publish"
    issue = build_candidate_issue([good, bad], WEEK_START, WEEK_END, {})
    reviewed = build_reviewed_issue(issue, [
        {"event_id": good["event_id"], "decision": "approved"},
        {"event_id": bad["event_id"], "decision": "approved"},
    ])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    assert len(approved["events"]) == 1
    assert approved["publication"]["complete"] is False
    assert "price_span_inverted" in approved["publication"]["exclusion_reasons"]


# --------------------------------------------------------------------------
# The reader is told why
# --------------------------------------------------------------------------

def test_the_review_summary_flags_the_inconsistency():
    summary = render_review_summary(
        {"issue_week": {"start": "2026-11-16", "end": "2026-11-22"},
         "generated_at": "2026-11-15T18:00:00+01:00", "events": [_candidate(12.0, 8.0)]},
        {},
    )
    assert "Price evidence inconsistent" in summary
    assert "below the entry price" in summary


def test_the_price_label_never_masks_an_inverted_span_as_a_single_price():
    """A tidy "€12" would present contradictory evidence as a settled figure."""
    label = price_label(_candidate(12.0, 8.0))
    assert label != "€12"
    assert "lower" in label
    assert "€8" in label and "€12" in label


# --------------------------------------------------------------------------
# Everything else is unchanged
# --------------------------------------------------------------------------

def test_a_valid_range_still_publishes_with_its_span():
    approved = _approve(_candidate(5.0, 15.03))
    assert len(approved["events"]) == 1
    published = public_latest(approved)["events"][0]
    assert (published["price_eur"], published["price_max_eur"]) == (5.0, 15.03)
    assert published["price_label"] == "€5–€15.03"


def test_the_cap_still_applies_to_the_lower_bound():
    """Entry €5, upper €40: eligible, because entry is what it costs to get in."""
    assert publication_problems(_candidate(5.0, 40.0), WEEK_START, WEEK_END) == []
    assert publication_problems(_candidate(16.0, 40.0), WEEK_START, WEEK_END) == [
        "price_above_cap"
    ]


def test_a_single_price_event_is_untouched():
    record = _candidate(10.0, 10.0)
    record["price_status"] = "confirmed_paid"
    assert not price_status.has_malformed_span(record)
    assert publication_problems(record, WEEK_START, WEEK_END) == []
    approved = _approve(record)
    assert len(approved["events"]) == 1
    assert public_latest(approved)["events"][0]["price_label"] == "€10"


def test_bare_zero_protection_is_unchanged():
    record = event_record(
        {"title": "Z", "date": "2026-11-20", "venue": "K", "url": "https://x.de/e3",
         "description": "Ein Abend.", "price": 0.0},
        week_start=WEEK_START, week_end=WEEK_END,
    )
    assert record["price_status"] == price_status.UNKNOWN
    assert "price_unknown" in publication_problems(record, WEEK_START, WEEK_END)
