"""Range price handling, end to end.

``range`` means the source confirmed a low-to-high span. The entry price is the
**lower** bound, which is the number the €15 community cap applies to; the upper
bound describes the dearest option and is preserved so a reader can see it.

This was the one canonical state that was not wired through the community
selection pipeline when it was introduced. The status itself was handled by
publication rules, but selection scored it at 0 points, treated it as
ineligible, and described it as "entry price still to be confirmed" - so an
affordable range sank below unverified events, and a range above the cap was
selected while the equivalent single price was excluded.

Each boundary in the table is a test, because the cap is the rule that decides
what a reader is ever shown.
"""

import json
from datetime import date

import pytest

from scripts import price_status
from scripts.community_common import (
    COMMUNITY_MAX_PRICE,
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_DONATION,
    PRICE_STATUS_NEEDS_VERIFICATION,
    PRICE_STATUS_RANGE,
    PRICE_STATUS_UNKNOWN,
    is_confirmed_entry_price,
    price_priority,
)
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
from scripts.community_select import (
    build_recommendation_reason,
    is_eligible,
    price_band_distribution,
    price_points,
    select_community_events,
    selection_score,
)
from scripts.community_validate import structural_problems

WEEK_START = date(2026, 11, 16)
WEEK_END = date(2026, 11, 22)


def _event(title="Range Gig", status=PRICE_STATUS_RANGE, entry=5.0, upper=15.0, **kw):
    event = {
        "event_id": "ce-" + title.lower().replace(" ", "")[:24].ljust(24, "0"),
        "title": title,
        "date": "2026-11-20",
        "time": "20:00",
        "venue": "Kantine",
        "district": "Kreuzberg",
        "price_eur": entry,
        "price_max_eur": upper,
        "price_status": status,
        "category": "music",
        "description": "Ein Abend mit Livemusik und Gästen im Hinterhof.",
        "event_url": "https://x.de/" + title.lower().replace(" ", "-"),
        "has_detail_link": True,
        "verification": {"status": "matched", "fields": {}, "corrections": [], "notes": ""},
        "community": {"recommendation_reason": "x", "price_priority": "paid",
                      "selection_status": "proposed"},
    }
    event.update(kw)
    return event


def _issued(record):
    return {"schema_version": "1.0", "status": "candidates",
            "issue_week": {"start": "2026-11-16", "end": "2026-11-22",
                           "timezone": "Europe/Berlin"},
            "generated_at": "2026-11-15T18:00:00+01:00", "events": [record]}


def _verified_record(entry, upper=None, status=PRICE_STATUS_RANGE):
    raw = {"title": "Range Gig", "date": "2026-11-20", "time": "20:00",
           "venue": "Kantine", "url": "https://x.de/e", "source_url": "https://x.de/l",
           "description": "Konzert", "price": entry, "price_status": status}
    if upper is not None:
        raw["price_max"] = upper
    record = event_record(raw, week_start=WEEK_START, week_end=WEEK_END)
    record["verification"] = {"status": "matched", "fields": {"title": "match",
                                                              "date": "match"},
                              "corrections": [], "notes": ""}
    record["community"]["selection_status"] = "approved"
    return record


# --------------------------------------------------------------------------
# The cap, at every boundary
# --------------------------------------------------------------------------

def test_a_range_within_the_cap_is_eligible():
    assert is_eligible(PRICE_STATUS_RANGE, 5.0) is True
    assert is_confirmed_entry_price(PRICE_STATUS_RANGE, 5.0) is True


def test_a_range_exactly_at_the_cap_is_eligible():
    assert is_eligible(PRICE_STATUS_RANGE, COMMUNITY_MAX_PRICE) is True
    assert is_confirmed_entry_price(PRICE_STATUS_RANGE, COMMUNITY_MAX_PRICE) is True


def test_a_range_above_the_cap_is_not_eligible():
    assert is_eligible(PRICE_STATUS_RANGE, 15.01) is False
    assert is_confirmed_entry_price(PRICE_STATUS_RANGE, 15.01) is False


def test_a_range_with_no_entry_price_is_not_eligible():
    """A span with no lower bound establishes nothing to compare to the cap."""
    assert is_eligible(PRICE_STATUS_RANGE, None) is False
    assert is_confirmed_entry_price(PRICE_STATUS_RANGE, None) is False


def test_a_range_above_the_cap_is_not_selected():
    """This was the actual bug: it was selected while the single price was not."""
    selected, _ = select_community_events([_event(entry=16.0, upper=20.0)], target=5)
    assert selected == []


def test_a_range_within_the_cap_is_selected():
    selected, _ = select_community_events([_event(entry=5.0, upper=15.0)], target=5)
    assert len(selected) == 1


def test_the_upper_bound_never_decides_the_cap():
    """Entry is €5; the dearest option is €40. The cap applies to entry."""
    assert is_eligible(PRICE_STATUS_RANGE, 5.0) is True
    selected, _ = select_community_events([_event(entry=5.0, upper=40.0)], target=5)
    assert len(selected) == 1


def test_a_range_is_scored_on_par_with_a_single_price_at_the_same_entry():
    assert price_points(PRICE_STATUS_RANGE, 10.0) == price_points(PRICE_STATUS_CONFIRMED_PAID, 10.0)


def test_a_range_above_the_cap_scores_the_veto():
    assert price_points(PRICE_STATUS_RANGE, 16.0) == -1000


def test_a_range_ranks_above_an_unpriced_event():
    """Before this fix a range scored 0 and sank below `unknown`."""
    assert selection_score(_event(entry=5.0)) > selection_score(
        _event(status=PRICE_STATUS_UNKNOWN, entry=None, upper=None)
    )


def test_a_range_stays_distinct_from_adjacent_states():
    """Range is neither collapsed into paid nor into unknown."""
    assert price_priority(PRICE_STATUS_RANGE) == "paid"
    assert PRICE_STATUS_RANGE != PRICE_STATUS_CONFIRMED_PAID
    assert PRICE_STATUS_RANGE != PRICE_STATUS_UNKNOWN


# --------------------------------------------------------------------------
# Candidate generation
# --------------------------------------------------------------------------

def test_a_range_survives_candidate_generation_with_both_bounds():
    record = _verified_record(5.0, 15.03)
    assert record["price_status"] == PRICE_STATUS_RANGE
    assert record["price_eur"] == 5.0
    assert record["price_max_eur"] == 15.03


def test_a_single_price_gains_no_invented_span():
    """No range may be invented when the source gave one number."""
    record = _verified_record(10.0, status=PRICE_STATUS_CONFIRMED_PAID)
    assert record["price_status"] == PRICE_STATUS_CONFIRMED_PAID
    assert record["price_max_eur"] == 10.0


def test_a_bare_zero_in_a_range_does_not_become_free():
    """The bare-zero protection still holds for range rows."""
    raw = {"title": "X", "date": "2026-11-20", "venue": "Kantine",
           "url": "https://x.de/e", "description": "Ein Abend.", "price": 0.0}
    record = event_record(raw, week_start=WEEK_START, week_end=WEEK_END)
    assert record["price_status"] == PRICE_STATUS_UNKNOWN


def test_an_inverted_span_is_preserved_not_repaired():
    """The defect is reported, not erased.

    An earlier implementation rewrote the upper bound up to the entry price,
    which made a contradictory record look like a valid single-price event
    before validation ever saw it.
    """
    record = _verified_record(15.0, 5.0)
    assert record["price_eur"] == 15.0
    assert record["price_max_eur"] == 5.0, "source bounds must survive as stated"
    assert price_status.malformed_span_reason(record) is not None


# --------------------------------------------------------------------------
# Review summary and labels
# --------------------------------------------------------------------------

def test_the_review_summary_shows_the_span():
    record = _verified_record(5.0, 15.03)
    summary = render_review_summary(
        {"issue_week": {"start": "2026-11-16", "end": "2026-11-22"},
         "generated_at": "2026-11-15T18:00:00+01:00", "events": [record]},
        {},
    )
    assert "€5–€15.03" in summary
    assert "range" in summary, "a reviewer must see the status, not only the amount"
    assert "to be confirmed" not in summary.lower()


def test_the_price_label_renders_a_span():
    assert price_label({"price_status": PRICE_STATUS_RANGE, "price_eur": 5.0,
                        "price_max_eur": 15.03}) == "€5–€15.03"


def test_a_range_with_a_single_bound_is_labeled_as_an_entry_price():
    """Not `€5–€5`, which would imply a span the source never stated."""
    assert price_label({"price_status": PRICE_STATUS_RANGE, "price_eur": 5.0,
                        "price_max_eur": None}) == "€5 (entry)"
    assert price_label({"price_status": PRICE_STATUS_RANGE, "price_eur": 5.0,
                        "price_max_eur": 5.0}) == "€5 (entry)"


def test_the_recommendation_reason_states_the_span():
    reason = build_recommendation_reason(
        _event(entry=5.0, upper=15.03)
    )
    assert "€5" in reason and "€15.03" in reason
    assert "to be confirmed" not in reason.lower()


def test_a_range_lands_in_a_paid_price_band():
    bands = price_band_distribution([{"price_status": PRICE_STATUS_RANGE, "price_eur": 5.0}])
    assert bands["free"] == 0
    assert bands["unknown"] == 0
    assert bands["1-5"] == 1


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def test_a_range_record_passes_structural_validation():
    assert structural_problems(_issued(_verified_record(5.0, 15.03))) == []


def test_a_range_without_an_entry_price_fails_structural_validation():
    record = _verified_record(None, None)
    assert record["price_status"] == PRICE_STATUS_RANGE
    problems = structural_problems(_issued(record))
    assert any("no entry price" in p for p in problems), problems


def test_an_inverted_span_fails_structural_validation():
    record = _verified_record(5.0, 15.0)
    record["price_max_eur"] = 4.0
    problems = structural_problems(_issued(record))
    assert any("inverted price span" in p for p in problems), problems
    assert any("below the entry price" in p for p in problems), problems


def test_a_negative_upper_bound_fails_structural_validation():
    record = _verified_record(5.0, 15.0)
    record["price_max_eur"] = -1
    problems = structural_problems(_issued(record))
    assert any("price_max_eur" in p for p in problems), problems


# --------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------

def test_a_range_within_the_cap_is_publishable():
    assert publication_problems(_verified_record(5.0, 15.03), WEEK_START, WEEK_END) == []


def test_a_range_exactly_at_the_cap_is_publishable():
    assert publication_problems(_verified_record(15.0, 15.0), WEEK_START, WEEK_END) == []


def test_a_range_above_the_cap_is_not_publishable():
    assert "price_above_cap" in publication_problems(
        _verified_record(16.0, 20.0), WEEK_START, WEEK_END
    )


def test_a_range_with_no_entry_price_is_not_publishable():
    assert "price_unknown" in publication_problems(
        _verified_record(None, None), WEEK_START, WEEK_END
    )


def test_a_publishable_range_reaches_the_public_payload_with_its_span():
    record = _verified_record(5.0, 15.03)
    record["community"]["selection_status"] = "approved"
    issue = build_candidate_issue([record], WEEK_START, WEEK_END, {})
    reviewed = build_reviewed_issue(issue, [
        {"event_id": record["event_id"], "decision": "approved"},
    ])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    assert len(approved["events"]) == 1
    published = public_latest(approved)["events"][0]
    assert published["price_status"] == PRICE_STATUS_RANGE
    assert published["price_eur"] == 5.0
    assert published["price_max_eur"] == 15.03
    assert published["price_label"] == "€5–€15.03"


def test_an_over_cap_range_is_refused_at_promotion_not_published():
    record = _verified_record(16.0, 20.0)
    record["community"]["selection_status"] = "approved"
    issue = build_candidate_issue([record], WEEK_START, WEEK_END, {})
    reviewed = build_reviewed_issue(issue, [
        {"event_id": record["event_id"], "decision": "approved"},
    ])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    assert approved["events"] == []
    assert "price_above_cap" in approved["refused"][0]["problems"]


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------

def test_a_range_round_trips_through_json_without_losing_its_bounds():
    record = _verified_record(5.0, 15.03)
    decoded = json.loads(json.dumps(record))
    assert decoded["price_status"] == PRICE_STATUS_RANGE
    assert decoded["price_eur"] == 5.0
    assert decoded["price_max_eur"] == 15.03
    assert price_label(decoded) == "€5–€15.03"


def test_the_public_payload_round_trips_with_its_span():
    record = _verified_record(6.5, 12.0)
    issue = build_candidate_issue([record], WEEK_START, WEEK_END, {})
    reviewed = build_reviewed_issue(issue, [
        {"event_id": record["event_id"], "decision": "approved"},
    ])
    latest = json.loads(json.dumps(public_latest(
        build_approved_issue(reviewed, WEEK_START, WEEK_END)
    )))
    event = latest["events"][0]
    assert (event["price_eur"], event["price_max_eur"]) == (6.5, 12.0)
    assert event["price_label"] == "€6.50–€12"
