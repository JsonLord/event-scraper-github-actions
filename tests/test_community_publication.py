"""Publication completeness policy and image coverage reporting.

Two behaviours are pinned here.

**Completeness.** The default policy is ``require_complete=False``: publish
every eligible approved event, exclude the ones that break a rule, and report
each exclusion. The failure modes this guards against are at both extremes - an
ineligible event slipping through, and a whole week disappearing because one
approved event was broken.

**Coverage.** Image extraction is decoration, so its failures are silent unless
they are counted. These tests check that the counts distinguish "no artwork
found" from "artwork found but the URL failed" from "never checked", because
conflating them is how a healthy extractor gets read as a broken one.
"""

import json
from datetime import date

import pytest

from scripts.community_common import (
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_UNKNOWN,
)
from scripts.community_image_stats import image_stats, render_stats_block
from scripts.community_issue import (
    build_approved_issue,
    build_candidate_issue,
    build_reviewed_issue,
    publication_problems,
    public_latest,
)

WEEK_START = date(2026, 11, 16)
WEEK_END = date(2026, 11, 22)


def _verified(title, status, price, *, eid=None, image_url=None, image_verified=None,
              source_url="https://venue.de/programm"):
    return {
        "event_id": eid or ("ce-" + title.lower().replace(" ", "")[:24].ljust(24, "0")),
        "title": title,
        "date": "2026-11-20",
        "time": "20:00",
        "venue": "Kantine",
        "price_eur": price,
        "price_status": status,
        "price_note": None,
        "event_url": "https://venue.de/event/" + title.lower().replace(" ", "-"),
        "source_url": source_url,
        "image_url": image_url,
        "image_verified": image_verified,
        "verification": {
            "status": "matched",
            "checked_at": "2026-11-15T18:00:00+01:00",
            "official_source_url": "https://venue.de/event/x",
            "fields": {"title": "match", "date": "match", "time": "match",
                       "venue": "match", "price": "match", "availability": "not_confirmed"},
            "corrections": [],
            "notes": "",
        },
        "community": {"recommendation_reason": "x", "selection_score": 10,
                      "price_priority": "free", "selection_status": "approved"},
    }


def _approve_all(events):
    issue = build_candidate_issue(events, WEEK_START, WEEK_END, {})
    decisions = [{"event_id": e["event_id"], "decision": "approved"} for e in issue["events"]]
    return build_reviewed_issue(issue, decisions)


# --------------------------------------------------------------------------
# Partial publication is the default
# --------------------------------------------------------------------------

def test_the_rest_of_the_week_survives_one_unpublishable_event():
    """A single broken event must not blank the issue."""
    good = _verified("Good", PRICE_STATUS_CONFIRMED_FREE, 0.0)
    bad = _verified("Unpriced", PRICE_STATUS_UNKNOWN, None)
    approved = build_approved_issue(_approve_all([good, bad]), WEEK_START, WEEK_END)
    assert [e["event_id"] for e in approved["events"]] == [good["event_id"]]


def test_each_exclusion_is_reported_with_its_reason():
    good = _verified("Good", PRICE_STATUS_CONFIRMED_FREE, 0.0)
    bad = _verified("Expensive", PRICE_STATUS_CONFIRMED_PAID, 40.0)
    approved = build_approved_issue(_approve_all([good, bad]), WEEK_START, WEEK_END)
    assert len(approved["refused"]) == 1
    refused = approved["refused"][0]
    assert refused["event_id"] == bad["event_id"]
    assert "price_above_cap" in refused["problems"]


def test_completeness_status_is_recorded_on_the_issue():
    good = _verified("Good", PRICE_STATUS_CONFIRMED_FREE, 0.0)
    bad = _verified("Unpriced", PRICE_STATUS_UNKNOWN, None)
    approved = build_approved_issue(_approve_all([good, bad]), WEEK_START, WEEK_END)
    publication = approved["publication"]
    assert publication["approved_requested"] == 2
    assert publication["published"] == 1
    assert publication["excluded"] == 1
    assert publication["complete"] is False
    assert publication["policy"] == "partial"
    assert "price_unknown" in publication["exclusion_reasons"]


def test_a_clean_week_is_marked_complete():
    approved = build_approved_issue(
        _approve_all([_verified("Good", PRICE_STATUS_CONFIRMED_FREE, 0.0)]),
        WEEK_START, WEEK_END,
    )
    publication = approved["publication"]
    assert publication["complete"] is True
    assert publication["policy"] == "complete"
    assert publication["excluded"] == 0


def test_an_ineligible_event_is_never_silently_published():
    bad = _verified("Unpriced", PRICE_STATUS_UNKNOWN, None)
    approved = build_approved_issue(_approve_all([bad]), WEEK_START, WEEK_END)
    assert approved["events"] == []
    assert approved["refused"]


def test_all_or_nothing_still_fails_loudly_when_asked():
    bad = _verified("Unpriced", PRICE_STATUS_UNKNOWN, None)
    with pytest.raises(ValueError, match="is not publishable"):
        build_approved_issue(_approve_all([bad]), WEEK_START, WEEK_END,
                             allow_partial=False)


def test_public_latest_contains_only_published_events():
    good = _verified("Good", PRICE_STATUS_CONFIRMED_FREE, 0.0)
    bad = _verified("Unpriced", PRICE_STATUS_UNKNOWN, None)
    approved = build_approved_issue(_approve_all([good, bad]), WEEK_START, WEEK_END)
    latest = public_latest(approved)
    assert [e["event_id"] for e in latest["events"]] == [good["event_id"]]
    assert latest["count"] == 1


def test_the_public_payload_carries_no_draft_fields():
    approved = build_approved_issue(
        _approve_all([_verified("Good", PRICE_STATUS_CONFIRMED_FREE, 0.0)]),
        WEEK_START, WEEK_END,
    )
    event = public_latest(approved)["events"][0]
    for draft in ("verification", "community", "refused", "publication"):
        assert draft not in event


# --------------------------------------------------------------------------
# Image coverage
# --------------------------------------------------------------------------

def test_coverage_counts_every_outcome_separately():
    events = [
        {"image_url": "https://x.de/a.jpg", "image_verified": True},
        {"image_url": "https://x.de/b.jpg", "image_verified": False},
        {"image_url": "https://x.de/c.jpg", "image_verified": None},
        {"image_url": None},
        {"image_url": None},
    ]
    stats = image_stats(events)
    totals = stats["totals"]
    assert totals["events"] == 5
    assert totals["with_image"] == 3
    assert totals["verified"] == 1
    assert totals["rejected"] == 1
    assert totals["unchecked"] == 1
    assert totals["no_image"] == 2
    assert totals["coverage_percent"] == 60.0


def test_no_artwork_is_distinguishable_from_a_failed_url():
    """Conflating these is how a working extractor gets read as broken."""
    no_art = image_stats([{"image_url": None}])
    failed = image_stats([{"image_url": "https://x.de/a.jpg", "image_verified": False}])
    assert no_art["totals"]["no_image"] == 1
    assert no_art["totals"]["rejected"] == 0
    assert failed["totals"]["no_image"] == 0
    assert failed["totals"]["rejected"] == 1


def test_unchecked_is_not_counted_as_a_failure():
    stats = image_stats([{"image_url": "https://x.de/a.jpg", "image_verified": None}])
    assert stats["totals"]["verified"] == 0
    assert stats["totals"]["rejected"] == 0
    assert stats["totals"]["unchecked"] == 1


def test_coverage_is_grouped_per_source():
    events = [
        {"image_url": "https://x.de/a.jpg", "image_verified": True,
         "source_url": "https://venue-a.de/programm"},
        {"image_url": None, "source_url": "https://venue-a.de/programm"},
        {"image_url": None, "source_url": "https://venue-b.de/programm"},
    ]
    stats = image_stats(events)
    assert stats["per_source"]["venue-a.de"]["coverage_percent"] == 50.0
    assert stats["per_source"]["venue-b.de"]["coverage_percent"] == 0.0
    assert stats["sources_without_images"] == ["venue-b.de"]


def test_a_source_with_no_events_does_not_divide_by_zero():
    assert image_stats([])["totals"]["coverage_percent"] == 0.0


def test_raus_is_marked_as_using_a_dedicated_parser():
    """Its lower coverage is architectural, not a defect to chase."""
    stats = image_stats([
        {"image_url": None, "source_url": "https://rausgegangen.de/en/berlin/eventsbydate/"},
        {"image_url": None, "source_url": "https://venue.de/programm"},
    ])
    assert stats["per_source"]["rausgegangen.de"]["dedicated_parser"] is True
    assert stats["per_source"]["venue.de"]["dedicated_parser"] is False


def test_a_missing_image_never_invalidates_an_event():
    event = _verified("NoArt", PRICE_STATUS_CONFIRMED_FREE, 0.0, image_url=None)
    assert publication_problems(event, WEEK_START, WEEK_END) == []
    approved = build_approved_issue(_approve_all([event]), WEEK_START, WEEK_END)
    assert len(approved["events"]) == 1


def test_the_summary_block_states_all_three_image_outcomes():
    stats = image_stats([
        {"image_url": "https://x.de/a.jpg", "image_verified": False,
         "source_url": "https://venue.de/programm"},
        {"image_url": None, "source_url": "https://venue.de/programm"},
    ])
    lines = "\n".join(render_stats_block(stats))
    assert "Failed image URLs" in lines
    assert "Unchecked image URLs" in lines
    assert "No artwork found" in lines
    assert "venue.de" in lines


def test_the_summary_block_lists_sources_with_no_artwork():
    stats = image_stats([{"image_url": None, "source_url": "https://venue-b.de/programm"}])
    assert "venue-b.de" in "\n".join(render_stats_block(stats))


# --------------------------------------------------------------------------
# The two together, through JSON
# --------------------------------------------------------------------------

def test_an_approved_issue_with_exclusions_round_trips_through_json():
    good = _verified("Good", PRICE_STATUS_CONFIRMED_FREE, 0.0,
                     image_url="https://x.de/a.jpg", image_verified=True)
    bad = _verified("Unpriced", PRICE_STATUS_UNKNOWN, None)
    approved = build_approved_issue(_approve_all([good, bad]), WEEK_START, WEEK_END)
    decoded = json.loads(json.dumps(approved))
    assert decoded["publication"]["complete"] is False
    assert len(decoded["refused"]) == 1
    assert len(public_latest(decoded)["events"]) == 1
