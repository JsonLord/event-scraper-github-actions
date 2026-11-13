"""Community pipeline: discovery, selection, verification, approval, publication.

The tests are organised by the question a failure would answer:

  * identity and calendar - is the same event addressable the same way, and is
    the week the one the newsletter claims?
  * price policy - is an unknown price kept unknown, and is the EUR 15
    boundary inclusive on 15.00 and exclusive on 15.01?
  * verification - does a correction win over the scraped value, and does an
    unreachable page stay unconfirmed rather than becoming a pass?
  * approval - can anything be published without a human decision saying so?
"""

import json
from datetime import date

import pytest

from scripts.community_common import (
    COMMUNITY_MAX_PRICE,
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_DONATION,
    PRICE_STATUS_NEEDS_VERIFICATION,
    PRICE_STATUS_UNKNOWN,
    classify_category,
    classify_price,
    district_from_text,
    in_issue_week,
    is_confirmed_entry_price,
    next_week_bounds,
    stable_event_id,
    week_bounds,
)
from scripts.community_issue import (
    build_approved_issue,
    build_candidate_issue,
    build_reviewed_issue,
    publication_problems,
    public_latest,
    event_record,
)
from scripts.community_select import (
    build_recommendation_reason,
    is_eligible,
    select_community_events,
    selection_score,
)
from scripts.community_verify import compare_event, extract_official_fields, verify_event

WEEK_START = date(2026, 11, 16)
WEEK_END = date(2026, 11, 22)


# --------------------------------------------------------------------------
# Calendar week in Europe/Berlin
# --------------------------------------------------------------------------

def test_a_monday_starts_its_own_week():
    assert week_bounds(date(2026, 11, 16)) == (date(2026, 11, 16), date(2026, 11, 22))


def test_a_sunday_belongs_to_the_week_that_started_six_days_before():
    """A Sunday is the last day of its week, not the first day of the next.

    ``weekday() >= 4`` thinking makes Sunday start a new week; an ISO week
    does not, and the newsletter covers Monday-Sunday.
    """
    assert week_bounds(date(2026, 11, 22)) == (date(2026, 11, 16), date(2026, 11, 22))


def test_a_midweek_day_resolves_to_its_own_monday():
    assert week_bounds(date(2026, 11, 19)) == (date(2026, 11, 16), date(2026, 11, 22))


def test_next_week_covers_the_week_that_has_not_started():
    start, end = next_week_bounds(date(2026, 11, 15))  # a Sunday
    assert (start, end) == (date(2026, 11, 16), date(2026, 11, 22))


def test_week_filtering_is_inclusive_on_both_ends():
    assert in_issue_week("2026-11-16", WEEK_START, WEEK_END)
    assert in_issue_week("2026-11-22", WEEK_START, WEEK_END)
    assert not in_issue_week("2026-11-15", WEEK_START, WEEK_END)
    assert not in_issue_week("2026-11-23", WEEK_START, WEEK_END)


def test_unparseable_dates_are_not_in_the_week():
    assert not in_issue_week("", WEEK_START, WEEK_END)
    assert not in_issue_week(None, WEEK_START, WEEK_END)
    assert not in_issue_week("not-a-date", WEEK_START, WEEK_END)


# --------------------------------------------------------------------------
# Stable identity
# --------------------------------------------------------------------------

def test_identity_is_stable_across_calls():
    a = stable_event_id("Kiez Konzert", "https://x.de/e/1", "2026-11-20", venue="Kantine")
    b = stable_event_id("Kiez Konzert", "https://x.de/e/1", "2026-11-20", venue="Kantine")
    assert a == b
    assert a.startswith("ce-")


def test_tracking_parameters_do_not_change_identity():
    a = stable_event_id("Kiez Konzert", "https://x.de/e/1?utm_source=x", "2026-11-20")
    b = stable_event_id("Kiez Konzert", "https://x.de/e/1", "2026-11-20")
    assert a == b


def test_a_recurring_event_on_a_different_date_is_a_different_id():
    """A weekly club night must be separately addressable and approvable."""
    first = stable_event_id("Clubnacht", "https://club.de/e", "2026-11-20")
    second = stable_event_id("Clubnacht", "https://club.de/e", "2026-11-27")
    assert first != second


def test_different_events_do_not_collide():
    a = stable_event_id("Kiez Konzert", "https://x.de/e/1", "2026-11-20")
    b = stable_event_id("Kiez Konzert", "https://x.de/e/2", "2026-11-20")
    assert a != b


def test_title_noise_does_not_change_identity():
    a = stable_event_id("KIEZ KONZERT!", "https://x.de/e/1", "2026-11-20")
    b = stable_event_id("Kiez  Konzert", "https://x.de/e/1", "2026-11-20")
    assert a == b


# --------------------------------------------------------------------------
# Price status
# --------------------------------------------------------------------------

def test_unknown_price_is_never_free():
    assert classify_price(None, "Ein Abend mit Musik") == PRICE_STATUS_UNKNOWN
    assert classify_price(None, "") == PRICE_STATUS_UNKNOWN


def test_explicit_free_text_confirms_free():
    assert classify_price(None, "Eintritt frei") == PRICE_STATUS_CONFIRMED_FREE
    assert classify_price(None, "Free admission") == PRICE_STATUS_CONFIRMED_FREE
    assert classify_price(0.0, "") == PRICE_STATUS_CONFIRMED_FREE


def test_donation_based_is_its_own_status():
    assert classify_price(None, "Eintritt auf Spendenbasis") == PRICE_STATUS_DONATION
    assert classify_price(0.0, "donation") == PRICE_STATUS_DONATION


def test_price_on_request_needs_verification():
    assert classify_price(None, "Preis auf Anfrage") == PRICE_STATUS_NEEDS_VERIFICATION
    assert classify_price(None, "TBA") == PRICE_STATUS_NEEDS_VERIFICATION


def test_stated_price_is_confirmed_paid():
    assert classify_price(12.5, "12,50 €") == PRICE_STATUS_CONFIRMED_PAID


def test_euro_fifteen_is_included_and_fifteen_oh_one_is_not():
    assert is_confirmed_entry_price(PRICE_STATUS_CONFIRMED_PAID, 15.0)
    assert not is_confirmed_entry_price(PRICE_STATUS_CONFIRMED_PAID, 15.01)


def test_free_is_always_inside_the_cap():
    assert is_confirmed_entry_price(PRICE_STATUS_CONFIRMED_FREE, 0.0)


def test_unsettled_prices_are_not_confirmed_entry_prices():
    """They stay eligible for selection but cannot be published unchanged."""
    assert not is_confirmed_entry_price(PRICE_STATUS_UNKNOWN, None)
    assert not is_confirmed_entry_price(PRICE_STATUS_NEEDS_VERIFICATION, None)
    assert is_eligible(PRICE_STATUS_UNKNOWN, None)
    assert is_eligible(PRICE_STATUS_NEEDS_VERIFICATION, None)


def test_the_community_cap_is_its_own_policy():
    assert COMMUNITY_MAX_PRICE == 15.0


# --------------------------------------------------------------------------
# Categories and districts
# --------------------------------------------------------------------------

def test_short_keywords_do_not_match_inside_unrelated_words():
    """"techno" must not match "Technology", or a coding meetup becomes a rave."""
    assert classify_category("INNOQ Technology Day") != "electronic"
    assert classify_category("Techno Nacht im Keller") == "electronic"


def test_declared_german_compounds_match():
    assert classify_category("Technonacht") == "electronic"
    assert classify_category("Workshop-Reihe für Anfänger") == "workshops"


def test_an_unrecognised_word_is_other_rather_than_a_wrong_category():
    """Falling into "other" is a visible, harmless miss.

    "Marketing" is one character away from "market" and "Workshopreihe" is a
    real German compound; no automatic suffix rule separates those two cases,
    so the classifier prefers to miss rather than to file a marketing meetup
    under markets.
    """
    assert classify_category("Marketing Meetup") == "other"
    assert classify_category("Workshopreihe") == "other"


def test_meetup_platform_name_is_not_a_community_category():
    """Nearly every Meetup row contains "Meetup"; it cannot imply community."""
    assert classify_category("Coding Agents & Architecture Meetup") != "community"
    assert classify_category("Kiez-Nachbarschaftsstammtisch") == "community"


def test_district_is_read_from_a_named_locality():
    assert district_from_text("Kantine, Kreuzberg") == "Kreuzberg"
    assert district_from_text("Prenzlauer Berg") == "Prenzlauer Berg"


def test_district_is_inferred_from_a_berlin_postcode():
    assert district_from_text("Weserstraße 5, 12047 Berlin") == "Neukölln"


def test_an_unknown_location_has_no_district():
    assert district_from_text("irgendwo") is None


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def _candidate(**overrides):
    base = {
        "event_id": stable_event_id("Event", "https://x.de/e", "2026-11-20"),
        "title": "Kiez Konzert",
        "date": "2026-11-20",
        "time": "20:00",
        "venue": "Kantine",
        "district": "Kreuzberg",
        "price_eur": 0.0,
        "price_status": PRICE_STATUS_CONFIRMED_FREE,
        "category": "music",
        "description": "Ein Abend mit Livemusik und Gästen im Hinterhof.",
        "event_url": "https://x.de/e",
        "has_detail_link": True,
        "verification": {"status": "not_confirmed", "fields": {}},
    }
    base.update(overrides)
    return base


def test_free_events_outrank_paid_ones():
    free = _candidate()
    paid = _candidate(price_eur=12.0, price_status=PRICE_STATUS_CONFIRMED_PAID)
    assert selection_score(free) > selection_score(paid)


def test_events_above_the_cap_are_excluded_from_selection():
    expensive = _candidate(price_eur=15.01, price_status=PRICE_STATUS_CONFIRMED_PAID)
    selected, _ = select_community_events([expensive])
    assert selected == []


def test_fifteen_euro_event_is_eligible():
    ok = _candidate(price_eur=15.0, price_status=PRICE_STATUS_CONFIRMED_PAID)
    selected, _ = select_community_events([ok])
    assert len(selected) == 1


def test_selection_is_capped_and_never_padded():
    events = [_candidate(event_id=f"ce-{i:024x}", title=f"Event {i}",
                         event_url=f"https://x.de/e{i}") for i in range(60)]
    selected, _ = select_community_events(events, target=35)
    assert len(selected) == 35


def test_a_thin_week_selects_only_what_exists():
    events = [_candidate(event_id=f"ce-{i:024x}", title=f"Event {i}",
                         event_url=f"https://x.de/e{i}") for i in range(3)]
    selected, _ = select_community_events(events, target=35)
    assert len(selected) == 3


def test_selection_spreads_across_categories():
    """Ten identical techno nights must not fill the shortlist."""
    techno = [_candidate(event_id=f"ce-{i:024x}", title=f"Techno Nacht {i}",
                         category="electronic", event_url=f"https://x.de/t{i}",
                         district="Friedrichshain") for i in range(10)]
    varied = [_candidate(event_id=f"ce-{i + 20:024x}", title=f"Markt {i}",
                         category="markets", event_url=f"https://x.de/m{i}",
                         district="Mitte") for i in range(5)]
    selected, _ = select_community_events(techno + varied, target=8)
    categories = {event["category"] for event in selected}
    assert len(categories) >= 2, categories


def test_unsettled_prices_are_reported_as_unresolved_not_dropped():
    unknown = _candidate(price_eur=None, price_status=PRICE_STATUS_UNKNOWN)
    selected, unresolved = select_community_events([unknown], target=5)
    assert len(selected) == 1
    assert all(e["event_id"] != unknown["event_id"] for e in unresolved)


def test_verification_rejection_removes_an_event_from_selection():
    rejected = _candidate(verification={"status": "rejected", "fields": {}})
    selected, _ = select_community_events([rejected])
    assert selected == []


def test_recommendation_reason_states_only_what_the_record_states():
    reason = build_recommendation_reason(_candidate())
    assert "Free" in reason
    assert "Kantine" in reason
    # Nothing about attendance, popularity or quality may be asserted.
    for claim in ("popular", "sold out", "best", "must-see", "legendary"):
        assert claim not in reason.lower()


def test_recommendation_reason_strips_markdown_from_the_blurb():
    event = _candidate(description="Der **[Technology Day](https://x.de)** findet statt.")
    assert "https://x.de" not in build_recommendation_reason(event)
    assert "**" not in build_recommendation_reason(event)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def _official(**overrides):
    base = {
        "reachable": True,
        "title": "Kiez Konzert",
        "dates": ["2026-11-20"],
        "times": ["20:00"],
        "price": 0.0,
        "price_text": "0",
        "cancelled": False,
        "postponed": False,
        "sold_out": False,
        "venue": "Kantine",
        "image_url": "",
    }
    base.update(overrides)
    return base


def test_a_matching_official_page_verifies():
    outcome = compare_event(_candidate(), _official())
    assert outcome["verification"]["status"] == "matched"


def test_an_unreachable_page_is_not_confirmed_not_a_pass():
    outcome = compare_event(_candidate(), {"reachable": False, "reason": "timeout"})
    assert outcome["verification"]["status"] == "not_confirmed"
    assert outcome["verification"]["fields"]["title"] == "not_confirmed"


def test_an_official_correction_wins_over_the_scraped_value():
    outcome = compare_event(_candidate(), _official(times=["21:00"]))
    assert outcome["verification"]["status"] == "corrected"
    assert outcome["corrected_fields"]["time"] == "21:00"
    assert outcome["verification"]["fields"]["time"] == "corrected"
    assert outcome["verification"]["corrections"][0]["field"] == "time"


def test_a_corrected_price_updates_the_price_status():
    event = _candidate(price_eur=12.0, price_status=PRICE_STATUS_CONFIRMED_PAID)
    outcome = compare_event(event, _official(price=9.5))
    assert outcome["corrected_fields"]["price_eur"] == 9.5


def test_a_cancelled_event_is_rejected():
    outcome = compare_event(_candidate(), _official(cancelled=True))
    assert outcome["verification"]["status"] == "rejected"
    assert outcome["rejected"] is True


def test_a_postponed_event_is_rejected():
    outcome = compare_event(_candidate(), _official(postponed=True))
    assert outcome["verification"]["status"] == "rejected"


def test_a_page_that_states_no_price_leaves_price_unconfirmed():
    outcome = compare_event(_candidate(), _official(price=None))
    assert outcome["verification"]["fields"]["price"] == "not_confirmed"


def test_a_page_with_no_time_leaves_time_unconfirmed():
    outcome = compare_event(_candidate(), _official(times=[]))
    assert outcome["verification"]["fields"]["time"] == "not_confirmed"


def test_sold_out_is_recorded_but_absence_is_not_availability():
    sold_out = compare_event(_candidate(), _official(sold_out=True))
    assert sold_out["verification"]["fields"]["availability"] == "match"
    normal = compare_event(_candidate(), _official())
    assert normal["verification"]["fields"]["availability"] == "not_confirmed"


def test_official_page_fields_are_extracted_from_schema_org():
    html = '''<html><head><script type="application/ld+json">
      {"@type":"Event","name":"Kiez Konzert","startDate":"2026-11-20T20:00:00+01:00",
       "offers":{"price":"9.50","priceCurrency":"EUR"},
       "location":{"name":"Kantine"},
       "image":"https://x.de/poster.jpg"}
      </script></head><body></body></html>'''
    fields = extract_official_fields(html, "https://x.de/e")
    assert fields["title"] == "Kiez Konzert"
    assert fields["dates"] == ["2026-11-20"]
    assert fields["price"] == 9.5
    assert fields["venue"] == "Kantine"
    assert fields["image_url"] == "https://x.de/poster.jpg"


def test_official_page_prose_is_read_when_there_is_no_markup():
    html = "<html><body><h1>Kiez Konzert</h1><p>Am 20. November 2026, 20:00 Uhr. Eintritt frei.</p></body></html>"
    fields = extract_official_fields(html, "https://x.de/e")
    assert fields["reachable"] is True
    assert "2026-11-20" in fields["dates"]
    assert "20:00" in fields["times"]
    assert fields["price"] == 0.0


def test_a_bot_challenge_page_is_not_readable():
    html = "<html><head><title>Just a moment...</title></head><body></body></html>"
    assert extract_official_fields(html, "https://x.de/e")["reachable"] is False


def test_verification_survives_a_fetch_exception():
    def boom(url):
        raise RuntimeError("connection reset")

    event = _candidate()
    verify_event(event, boom)
    assert event["verification"]["status"] == "not_confirmed"


# --------------------------------------------------------------------------
# Publication rules
# --------------------------------------------------------------------------

def _verified_candidate(**overrides):
    event = _candidate(**overrides)
    event["verification"] = {
        "status": "matched",
        "checked_at": "2026-11-15T18:00:00+01:00",
        "official_source_url": event["event_url"],
        "fields": {"title": "match", "date": "match", "time": "match",
                   "venue": "match", "price": "match", "availability": "not_confirmed"},
        "corrections": [],
        "notes": "",
    }
    event["community"] = {"recommendation_reason": "Free music",
                          "selection_score": 80, "price_priority": "free",
                          "selection_status": "approved"}
    return event


def test_a_clean_verified_event_is_publishable():
    assert publication_problems(_verified_candidate(), WEEK_START, WEEK_END) == []


def test_an_unverified_event_is_not_publishable():
    event = _candidate()
    assert "unverified" in publication_problems(event, WEEK_START, WEEK_END)


def test_an_unknown_price_is_not_publishable():
    event = _verified_candidate(price_eur=None, price_status=PRICE_STATUS_UNKNOWN)
    assert "price_unknown" in publication_problems(event, WEEK_START, WEEK_END)


def test_an_event_above_the_cap_is_not_publishable():
    event = _verified_candidate(price_eur=16.0, price_status=PRICE_STATUS_CONFIRMED_PAID)
    assert "price_above_cap" in publication_problems(event, WEEK_START, WEEK_END)


def test_an_event_outside_the_week_is_not_publishable():
    event = _verified_candidate(date="2026-11-23")
    assert "outside_issue_week" in publication_problems(event, WEEK_START, WEEK_END)


def test_a_cancelled_event_is_not_publishable():
    event = _verified_candidate()
    event["verification"]["fields"]["cancellation"] = "rejected"
    assert "cancelled" in publication_problems(event, WEEK_START, WEEK_END)


def test_a_free_event_with_a_venue_is_publishable_without_a_stated_time():
    event = _verified_candidate(time=None)
    event["verification"]["fields"]["time"] = "not_confirmed"
    assert publication_problems(event, WEEK_START, WEEK_END) == []


# --------------------------------------------------------------------------
# Approval gate
# --------------------------------------------------------------------------

def _candidate_issue(events):
    return build_candidate_issue(events, WEEK_START, WEEK_END, {"proposed_count": len(events)})


def test_an_approved_issue_contains_only_approved_events():
    approved_event = _verified_candidate(event_id="ce-" + "a" * 24, title="A")
    rejected_event = _verified_candidate(event_id="ce-" + "b" * 24, title="B")
    issue = _candidate_issue([approved_event, rejected_event])
    reviewed = build_reviewed_issue(issue, [
        {"event_id": approved_event["event_id"], "decision": "approved"},
        {"event_id": rejected_event["event_id"], "decision": "rejected"},
    ])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    assert [e["event_id"] for e in approved["events"]] == [approved_event["event_id"]]


def test_nothing_is_published_without_a_decision():
    issue = _candidate_issue([_verified_candidate()])
    reviewed = build_reviewed_issue(issue, [])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    assert approved["events"] == []


def test_high_scores_do_not_imply_approval():
    """Scoring is a suggestion; only a decision file can approve."""
    scored = _verified_candidate()
    scored["community"]["selection_score"] = 100
    issue = _candidate_issue([scored])
    reviewed = build_reviewed_issue(issue, [])
    assert build_approved_issue(reviewed, WEEK_START, WEEK_END)["events"] == []


def test_a_decision_for_an_unknown_id_is_an_error():
    issue = _candidate_issue([_verified_candidate()])
    with pytest.raises(ValueError, match="unknown event ids"):
        build_reviewed_issue(issue, [{"event_id": "ce-" + "f" * 24, "decision": "approved"}])


def test_an_unpublishable_approved_event_is_refused_and_reported():
    bad = _verified_candidate(price_eur=None, price_status=PRICE_STATUS_UNKNOWN)
    issue = _candidate_issue([bad])
    reviewed = build_reviewed_issue(issue, [{"event_id": bad["event_id"], "decision": "approved"}])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    assert approved["events"] == []
    assert approved["refused"][0]["event_id"] == bad["event_id"]
    assert "price_unknown" in approved["refused"][0]["problems"]


def test_promotion_can_be_all_or_nothing():
    bad = _verified_candidate(price_eur=None, price_status=PRICE_STATUS_UNKNOWN)
    issue = _candidate_issue([bad])
    reviewed = build_reviewed_issue(issue, [{"event_id": bad["event_id"], "decision": "approved"}])
    with pytest.raises(ValueError, match="not publishable"):
        build_approved_issue(reviewed, WEEK_START, WEEK_END, allow_partial=False)


def test_public_latest_drops_review_internals():
    event = _verified_candidate()
    issue = _candidate_issue([event])
    reviewed = build_reviewed_issue(issue, [{"event_id": event["event_id"], "decision": "approved"}])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    latest = public_latest(approved)
    payload = latest["events"][0]
    assert payload["recommendation_reason"] == "Free music"
    assert "verification" not in payload
    assert "community" not in payload
    assert latest["count"] == 1


def test_public_latest_never_renders_an_unknown_price_as_free():
    previous = _verified_candidate(price_eur=None, price_status=PRICE_STATUS_UNKNOWN)
    issue = _candidate_issue([previous])
    reviewed = build_reviewed_issue(issue, [{"event_id": previous["event_id"], "decision": "approved"}])
    approved = build_approved_issue(reviewed, WEEK_START, WEEK_END)
    # Nothing publishable, so nothing labelled at all.
    assert public_latest(approved)["events"] == []


# --------------------------------------------------------------------------
# Candidate records
# --------------------------------------------------------------------------

def test_event_record_refuses_a_row_with_no_date_or_title():
    assert event_record({"title": "", "date": "2026-11-20"}, week_start=WEEK_START, week_end=WEEK_END) is None
    assert event_record({"title": "X", "date": ""}, week_start=WEEK_START, week_end=WEEK_END) is None


def test_event_record_computes_a_stable_id_when_one_is_missing():
    record = event_record(
        {"title": "Kiez Konzert", "date": "2026-11-20", "url": "https://x.de/e/1",
         "source_url": "https://x.de/list", "venue": "Kantine", "price": None},
        week_start=WEEK_START, week_end=WEEK_END,
    )
    assert record["event_id"].startswith("ce-")
    assert record["price_status"] == PRICE_STATUS_UNKNOWN
    assert record["price_eur"] is None
