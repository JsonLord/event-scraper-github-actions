"""End-to-end tests for the prepare -> review -> promote -> publish chain.

These drive the real CLI entry points against a temporary community root, so
they exercise the parts an operator actually runs: the files written, the
files refused, and the fact that a public file only ever appears after an
explicit approval.

No network: verification is handed a fake fetcher.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import community_prepare, community_promote
from scripts.community_common import (
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_UNKNOWN,
    stable_event_id,
)

WEEK_START = "2026-11-16"
WEEK_END = "2026-11-22"

OFFICIAL_PAGE = """<html><head>
<meta property="og:image" content="/media/poster.jpg">
<script type="application/ld+json">
{"@type":"Event","name":"%(title)s","startDate":"%(date)sT%(time)s:00+01:00",
 "offers":{"price":%(price)s,"priceCurrency":"EUR"},
 "location":{"@type":"Place","name":"%(venue)s"}}
</script></head><body><h1>%(title)s</h1></body></html>"""


def _raw_event(index, *, title=None, day="2026-11-20", price=0.0, venue="Kantine",
               detail=True, source="https://venue.de/programm", evidence="free"):
    """One aggregate row.

    ``evidence`` defaults to ``free`` because that is what the scraping
    pipeline writes for a row whose entry is *proven* free: a bare ``price: 0``
    with no proof is classified ``unknown`` by both implementations, since
    several sources emit zero when they simply failed to find a price. A
    fixture that wants an unpriced row passes ``price=None``.
    """
    title = title or f"Kiez Konzert {index}"
    row = {
        "title": title,
        "date": day,
        "time": "20:00",
        "price": price,
        "category": "",
        "description": f"Ein Abend mit Livemusik und Gästen, Nummer {index}.",
        "url": f"https://venue.de/event/{index}" if detail else source,
        "venue": venue,
        "source_url": source,
        "has_detail_link": detail,
        "image_url": None,
    }
    if evidence is not None:
        row["price_status"] = evidence
    return row


def _aggregate(events):
    return {"events": events, "count": len(events)}


def _fake_fetch(mapping):
    def fetch(url):
        for fragment, html in mapping.items():
            if fragment in url:
                return html
        return None
    return fetch


def _official_for(event, price=0.0, time="20:00"):
    return OFFICIAL_PAGE % {
        "title": event["title"],
        "date": event["date"],
        "time": time,
        "price": price,
        "venue": event["venue"],
    }


# --------------------------------------------------------------------------
# Candidate preparation
# --------------------------------------------------------------------------

def test_prepare_writes_a_candidate_issue_and_a_review_summary(tmp_path):
    events = [_raw_event(i) for i in range(6)]
    candidates, summary, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=False,
    )
    assert candidates["status"] == "candidates"
    assert candidates["issue_week"]["timezone"] == "Europe/Berlin"
    assert stats["proposed_count"] == 6
    assert "Community review - week of 2026-11-16" in summary
    assert "Nothing is published without it" in summary


def test_prepare_drops_events_outside_the_issue_week(tmp_path):
    events = [_raw_event(1, day="2026-11-20"), _raw_event(2, day="2026-11-30")]
    candidates, _, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=False,
    )
    assert stats["discovery_pool"] == 1
    assert all(e["date"] == "2026-11-20" for e in candidates["events"])


def test_prepare_keeps_unknown_prices_for_verification(tmp_path):
    """An unpriced row is a question for verification, not a row to drop."""
    events = [_raw_event(1, price=None, evidence=None)]
    _, _, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=False,
    )
    assert stats["discovery_pool"] == 1
    assert stats["price_bands"]["unknown"] == 1


def test_prepare_drops_a_confirmed_price_above_the_cap(tmp_path):
    events = [_raw_event(1, price=40.0)]
    _, _, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=False,
    )
    assert stats["discovery_pool"] == 0


def test_prepare_deduplicates_the_same_occurrence_from_two_sources(tmp_path):
    first = _raw_event(1)
    second = dict(first, source_url="https://other.de/list")
    _, _, stats = community_prepare.prepare_issue(
        [first, second], _aggregate([first, second]),
        date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=False,
    )
    assert stats["discovery_pool"] == 1


def test_prepare_verifies_against_the_official_page(tmp_path):
    events = [_raw_event(1)]
    fetch = _fake_fetch({"venue.de/event/1": _official_for(events[0])})
    candidates, _, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=True, fetch=fetch,
    )
    assert stats["verified_count"] == 1
    assert candidates["events"][0]["verification"]["status"] == "matched"


def test_prepare_marks_an_unreachable_event_unresolved(tmp_path):
    events = [_raw_event(1)]
    candidates, summary, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=True, fetch=lambda url: None,
    )
    assert stats["unresolved_count"] == 1
    assert candidates["events"][0]["verification"]["status"] == "not_confirmed"
    assert "Unresolved" in summary


def test_prepare_marks_a_cancelled_event_rejected(tmp_path):
    events = [_raw_event(1)]
    cancelled = "<html><body><h1>Abgesagt</h1><p>Die Veranstaltung wurde abgesagt.</p></body></html>"
    candidates, _, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=True, fetch=lambda url: cancelled,
    )
    assert stats["rejected_count"] == 1
    assert candidates["events"][0]["community"]["selection_status"] == "rejected"


def test_prepare_never_writes_a_public_file(tmp_path):
    events = [_raw_event(1)]
    fetch = _fake_fetch({"venue.de/event/1": _official_for(events[0])})
    community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=True, fetch=fetch,
    )
    assert not (tmp_path / "latest.json").exists()
    assert not (tmp_path / "approved").exists()


def test_prepare_counts_a_previously_published_occurrence_as_not_new(tmp_path):
    events = [_raw_event(1)]
    event_id = stable_event_id(events[0]["title"], events[0]["url"], "2026-11-20",
                               venue="Kantine", time="20:00")
    approved_dir = tmp_path / "approved"
    approved_dir.mkdir(parents=True)
    (approved_dir / "2026-11-09.json").write_text(json.dumps({"events": [{"event_id": event_id}]}))
    _, _, stats = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=False,
    )
    assert stats["newly_discovered"] == 0


# --------------------------------------------------------------------------
# Promotion
# --------------------------------------------------------------------------

def _prepared_root(tmp_path, count=3):
    events = [_raw_event(i) for i in range(count)]
    fetch = _fake_fetch({
        f"venue.de/event/{i}": _official_for(events[i]) for i in range(count)
    })
    candidates, _, _ = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=True, fetch=fetch,
    )
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates" / f"{WEEK_START}.json").write_text(json.dumps(candidates))
    (tmp_path / "reviewed").mkdir(parents=True, exist_ok=True)
    return candidates, tmp_path


def _write_decisions(root, decisions, week=WEEK_START):
    payload = {"issue_week_start": week, "decisions": decisions}
    (root / "reviewed" / f"{week}.json").write_text(json.dumps(payload))


def test_promotion_without_decisions_is_refused(tmp_path):
    _prepared_root(tmp_path)
    with pytest.raises(ValueError, match="no review decisions"):
        community_promote.promote(str(tmp_path), WEEK_START)


def test_promotion_without_candidates_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no candidate issue"):
        community_promote.promote(str(tmp_path), WEEK_START)


def test_promotion_refuses_a_decision_for_an_unknown_id(tmp_path):
    _prepared_root(tmp_path)
    _write_decisions(tmp_path, [{"event_id": "ce-" + "f" * 24, "decision": "approved"}])
    with pytest.raises(ValueError, match="unknown event id"):
        community_promote.promote(str(tmp_path), WEEK_START)


def test_promotion_refuses_a_decision_for_the_wrong_week(tmp_path):
    _prepared_root(tmp_path)
    candidates = json.loads((tmp_path / "candidates" / f"{WEEK_START}.json").read_text())
    # A decision file whose declared week disagrees with the candidate it is
    # applied to means the reviewer was looking at a different issue.
    (tmp_path / "reviewed" / f"{WEEK_START}.json").write_text(json.dumps({
        "issue_week_start": "2026-11-23",
        "decisions": [{"event_id": candidates["events"][0]["event_id"],
                       "decision": "approved"}],
    }))
    with pytest.raises(ValueError, match="but the candidate issue is"):
        community_promote.promote(str(tmp_path), WEEK_START)


def test_promotion_publishes_only_the_approved_events(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    approved_id = candidates["events"][0]["event_id"]
    rejected_id = candidates["events"][1]["event_id"]
    _write_decisions(root, [
        {"event_id": approved_id, "decision": "approved"},
        {"event_id": rejected_id, "decision": "rejected"},
    ])

    report = community_promote.promote(str(root), WEEK_START)
    assert report["published"] == 1

    latest = json.loads((root / "latest.json").read_text())
    assert [e["event_id"] for e in latest["events"]] == [approved_id]
    assert latest["count"] == 1

    approved = json.loads((root / "approved" / f"{WEEK_START}.json").read_text())
    assert approved["status"] == "approved"
    assert all(e["community"]["selection_status"] == "approved" for e in approved["events"])


def test_promotion_never_publishes_an_unapproved_candidate(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    # Approve one, leave the rest undecided.
    _write_decisions(root, [
        {"event_id": candidates["events"][0]["event_id"], "decision": "approved"},
    ])
    community_promote.promote(str(root), WEEK_START)
    latest = json.loads((root / "latest.json").read_text())
    assert latest["count"] == 1
    undecided = {e["event_id"] for e in candidates["events"][1:]}
    assert not undecided & {e["event_id"] for e in latest["events"]}


def test_promotion_refuses_an_approved_event_that_fails_a_rule(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    bad_id = candidates["events"][0]["event_id"]
    # Break the price after verification: above the community cap.
    for event in candidates["events"]:
        if event["event_id"] == bad_id:
            event["price_eur"] = 22.0
            event["price_status"] = PRICE_STATUS_CONFIRMED_PAID
    (root / "candidates" / f"{WEEK_START}.json").write_text(json.dumps(candidates))
    _write_decisions(root, [{"event_id": bad_id, "decision": "approved"}])

    report = community_promote.promote(str(root), WEEK_START)
    assert report["published"] == 0
    assert report["refused"][0]["event_id"] == bad_id
    assert "price_above_cap" in report["refused"][0]["problems"]


def test_promotion_all_or_nothing_fails_loudly(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    bad_id = candidates["events"][0]["event_id"]
    for event in candidates["events"]:
        if event["event_id"] == bad_id:
            event["price_eur"] = 99.0
            event["price_status"] = PRICE_STATUS_CONFIRMED_PAID
    (root / "candidates" / f"{WEEK_START}.json").write_text(json.dumps(candidates))
    _write_decisions(root, [{"event_id": bad_id, "decision": "approved"}])
    with pytest.raises(ValueError, match="is not publishable"):
        community_promote.promote(str(root), WEEK_START, require_complete=True)


def test_promotion_dry_run_writes_nothing(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    _write_decisions(root, [
        {"event_id": candidates["events"][0]["event_id"], "decision": "approved"},
    ])
    report = community_promote.promote(str(root), WEEK_START, dry_run=True)
    assert report["dry_run"] is True
    assert not (root / "latest.json").exists()
    assert not (root / "approved").exists()


def test_promotion_updates_the_archive_index(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    _write_decisions(root, [
        {"event_id": candidates["events"][0]["event_id"], "decision": "approved"},
    ])
    community_promote.promote(str(root), WEEK_START)
    archive = json.loads((root / "archive" / "index.json").read_text())
    assert archive["count"] == 1
    assert archive["issues"][0]["week_start"] == WEEK_START
    assert archive["issues"][0]["url"].endswith(f"/{WEEK_START}.json")


def test_republishing_a_week_replaces_its_archive_entry(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    _write_decisions(root, [
        {"event_id": candidates["events"][0]["event_id"], "decision": "approved"},
    ])
    community_promote.promote(str(root), WEEK_START)
    community_promote.promote(str(root), WEEK_START)
    archive = json.loads((root / "archive" / "index.json").read_text())
    assert archive["count"] == 1


def test_an_approved_issue_has_no_draft_fields_in_latest(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    _write_decisions(root, [
        {"event_id": candidates["events"][0]["event_id"], "decision": "approved"},
    ])
    community_promote.promote(str(root), WEEK_START)
    latest = json.loads((root / "latest.json").read_text())
    event = latest["events"][0]
    assert "verification" not in event
    assert "community" not in event
    assert event["price_label"]


def test_price_labels_never_call_an_absent_price_free(tmp_path):
    candidates, root = _prepared_root(tmp_path)
    _write_decisions(root, [])
    # Build a public payload directly to check the label function's behaviour.
    from scripts.community_issue import price_label

    assert price_label({"price_status": PRICE_STATUS_UNKNOWN, "price_eur": None}) != "Free"
    assert price_label({"price_status": "needs_verification", "price_eur": None}) != "Free"
    assert price_label({"price_status": PRICE_STATUS_CONFIRMED_FREE, "price_eur": 0.0}) == "Free"


def test_the_recommendation_reason_reflects_verified_values(tmp_path):
    """The reason is written after verification, not before it.

    A correction can move the venue or the price; a reason built from the
    scraped values would then contradict the record it sits next to.
    """
    events = [_raw_event(1, venue="Michelberger Hotel")]
    # The official page names a different venue and a price.
    official = OFFICIAL_PAGE % {
        "title": events[0]["title"],
        "date": events[0]["date"],
        "time": "20:00",
        "price": 9.0,
        "venue": "Kantine",
    }
    candidates, _, _ = community_prepare.prepare_issue(
        events, _aggregate(events), date(2026, 11, 16), date(2026, 11, 22),
        newsletter_root=str(tmp_path), verify=True,
        fetch=lambda url: official,
    )
    event = candidates["events"][0]
    reason = event["community"]["recommendation_reason"]
    assert "Kantine" in reason
    assert "Michelberger" not in reason
