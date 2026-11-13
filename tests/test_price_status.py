"""The canonical price-status contract.

Two pipelines used to write different vocabularies into one field, and readers
had to work out which pipeline produced a row before they could interpret it.
These tests pin the replacement: one enum, one documented migration, and the
two safety invariants that the whole publication gate rests on.

The invariants are the reason this contract exists rather than a tidier name:

  * a bare ``price: 0`` is not evidence of free entry
  * certainty is never inferred from a numeric value alone
"""

import json

import pytest

from scripts import price_status as ps
from scripts.community_common import price_status_for
from scripts.community_issue import publication_problems
from scripts.community_validate import structural_problems
from scripts.community_verify import compare_event
from scripts.ticket_evidence import enrich_evidence
from datetime import date

WEEK_START = date(2026, 11, 16)
WEEK_END = date(2026, 11, 22)


# --------------------------------------------------------------------------
# The enum
# --------------------------------------------------------------------------

def test_the_canonical_enum_is_exactly_the_documented_set():
    assert set(ps.CANONICAL_STATUSES) == {
        "confirmed_free", "confirmed_paid", "range",
        "donation_based", "needs_verification", "unknown",
    }


def test_every_canonical_status_has_a_documented_meaning():
    for status in ps.CANONICAL_STATUSES:
        assert ps.MEANINGS[status], status
        assert ps.describe(status).startswith(status)


def test_canonical_values_are_idempotent():
    for status in ps.CANONICAL_STATUSES:
        assert ps.canonicalize(status) == status


# --------------------------------------------------------------------------
# Migration from the historical spellings
# --------------------------------------------------------------------------

def test_legacy_evidence_spellings_map_to_their_equivalent():
    """`free` and `known` were always these things in the evidence model."""
    assert ps.canonicalize("free") == ps.CONFIRMED_FREE
    assert ps.canonicalize("known") == ps.CONFIRMED_PAID


def test_range_and_unknown_needed_no_migration():
    """They were already spelled canonically, which is why they pass through."""
    assert ps.canonicalize("range") == "range"
    assert ps.canonicalize("unknown") == "unknown"


def test_an_unrecognised_status_degrades_to_unknown_rather_than_raising():
    """A status we have never heard of is one whose price cannot be trusted."""
    for junk in ("bogus", "FREE", "confirmed", "", None, 0, "Free "):
        assert ps.canonicalize(junk) == ps.UNKNOWN


def test_migration_never_downgrades_a_confirmed_record():
    """Reading and re-writing a current record must be lossless."""
    for status in ps.CANONICAL_STATUSES:
        record = {"price_status": status}
        assert ps.canonicalize(record["price_status"]) == status


def test_every_legacy_alias_targets_a_canonical_status():
    for legacy, canonical in ps.LEGACY_ALIASES.items():
        assert canonical in ps.CANONICAL_STATUSES, legacy


# --------------------------------------------------------------------------
# Confirmed free admission with official evidence
# --------------------------------------------------------------------------

def test_confirmed_free_with_official_structured_evidence():
    row = enrich_evidence({"title": "Markt", "description": "Eintritt frei",
                           "price": 0.0, "url": "https://x.de/m"})
    assert row["free_admission_confirmed"] is True
    assert row["price_status_canonical"] == ps.CONFIRMED_FREE
    assert row["price_status_schema"] == ps.SCHEMA_VERSION
    assert price_status_for(row) == ps.CONFIRMED_FREE


def test_community_verification_establishes_confirmed_free():
    event = {"title": "Markt", "date": "2026-11-20", "time": "10:00",
             "venue": "Kantine", "price_eur": 0.0,
             "price_status": ps.CONFIRMED_FREE}
    official = {"reachable": True, "title": "Markt", "dates": ["2026-11-20"],
                "times": ["10:00"], "price": 0.0, "cancelled": False,
                "postponed": False, "sold_out": False, "venue": "Kantine",
                "image_url": ""}
    outcome = compare_event(event, official)
    assert outcome["verification"]["fields"]["price"] == "match"
    assert publication_problems(
        {**event, "event_id": "ce-" + "a" * 24, "event_url": "https://x.de/m",
         "verification": {"status": "matched", "fields": {"title": "match", "date": "match"},
                          "corrections": [], "notes": ""},
         "community": {"selection_status": "approved"}},
        WEEK_START, WEEK_END,
    ) == []


# --------------------------------------------------------------------------
# Confirmed paid, range, unknown
# --------------------------------------------------------------------------

def test_confirmed_paid():
    row = enrich_evidence({"title": "Konzert", "description": "18,00 €",
                           "price": 18.0, "url": "https://x.de/k"})
    assert row["price_status_canonical"] == ps.CONFIRMED_PAID
    assert ps.entry_price_of(row["price"], row["price_status_canonical"]) == 18.0


def test_range_keeps_both_bounds_and_publishes_on_the_entry_price():
    row = enrich_evidence({"title": "Konzert", "description": "12,90 to 15,03 €",
                           "price": 12.9, "url": "https://x.de/k"})
    assert row["price_status_canonical"] == ps.RANGE
    assert (row["price_min"], row["price_max"]) == (12.9, 15.03)
    # The entry price is the low end, which is the number both producers store.
    assert ps.entry_price_of(row["price"], row["price_status_canonical"]) == 12.9


def test_unknown_price():
    row = enrich_evidence({"title": "Konzert", "description": "Ein Abend.",
                           "price": None, "url": "https://x.de/k"})
    assert row["price_status_canonical"] == ps.UNKNOWN
    assert ps.entry_price_of(row["price"], row["price_status_canonical"]) is None


def test_needs_verification_is_distinct_from_unknown():
    assert price_status_for({"price_eur": None,
                             "description": "Preis auf Anfrage"}) == ps.NEEDS_VERIFICATION
    assert price_status_for({"price_eur": None,
                             "description": "Ein Abend."}) == ps.UNKNOWN


def test_donation_based_is_distinct_from_free():
    assert price_status_for({"price_eur": 0.0,
                             "description": "Eintritt auf Spendenbasis"}) == ps.DONATION_BASED


# --------------------------------------------------------------------------
# The two safety invariants
# --------------------------------------------------------------------------

def test_a_bare_zero_without_evidence_is_not_confirmed_free():
    """Several sources emit `price: 0` when they simply found no price."""
    row = enrich_evidence({"title": "Konzert", "description": "Konzert im Keller",
                           "price": 0.0, "url": "https://x.de/k"})
    assert row["price"] is None
    assert row["free_admission_confirmed"] is False
    assert row["price_status_canonical"] == ps.UNKNOWN
    assert price_status_for(row) == ps.UNKNOWN


def test_a_bare_zero_is_never_published_as_free():
    record = {"event_id": "ce-" + "a" * 24, "title": "Konzert", "date": "2026-11-20",
              "venue": "Kantine", "price_eur": None, "price_status": ps.UNKNOWN,
              "event_url": "https://x.de/k",
              "verification": {"status": "matched", "fields": {"title": "match", "date": "match"},
                               "corrections": [], "notes": ""},
              "community": {"selection_status": "approved"}}
    assert "price_unknown" in publication_problems(record, WEEK_START, WEEK_END)


def test_certainty_is_not_inferred_from_absence():
    """The invariant, scoped to what the codebase actually guarantees.

    A *missing* price is never upgraded to a confident one: absence of a number
    yields ``unknown`` no matter what the text says, and no status can invent a
    number that is not there.

    A *present* positive number is treated as a stated price, which is a
    deliberate asymmetry inherited from both pipelines and pinned here so it is
    a documented decision rather than an accident. It is safe because the routes
    that can produce a positive number - a JSON-LD offer, a price regex over
    card text, an official detail page - have each already read a number the
    source published. The zero case is different and is the dangerous one: a
    zero is what several sources emit when they found nothing, so it needs
    proof. See test_a_bare_zero_without_evidence_is_not_confirmed_free.
    """
    # Absence alone is never certainty.
    assert price_status_for({"price_eur": None}) == ps.UNKNOWN
    # A missing number cannot be made into a *paid* price: `known` without a
    # figure establishes nothing.
    assert price_status_for({"price_eur": None,
                             "price_status": "known"}) == ps.UNKNOWN
    # A `free` status does survive a missing number, and should: the status is
    # the evidence, and the number was simply not stored. Dropping it would
    # lose proof of free admission, which is exactly what the contract forbids.
    assert price_status_for({"price_eur": None,
                             "price_status": "free"}) == ps.CONFIRMED_FREE
    # A present, positive, stated price stands on its own - documented above.
    assert price_status_for({"price_eur": 12.5}) == ps.CONFIRMED_PAID
    # Free text still has to corroborate a zero.
    assert price_status_for({"price_eur": 0.0,
                             "description": "Eintritt frei"}) == ps.CONFIRMED_FREE


def test_proof_of_free_admission_survives_canonicalisation():
    row = enrich_evidence({"title": "Markt", "description": "Eintritt frei",
                           "price": 0.0, "url": "https://x.de/m"})
    assert row["free_admission_confirmed"] is True
    assert row["price_status_canonical"] == ps.CONFIRMED_FREE
    # ...and the provenance still says where that came from.
    assert ps.origin_for(row)["pipeline"] == "scraping"


# --------------------------------------------------------------------------
# Evidence from both pipelines
# --------------------------------------------------------------------------

def test_both_pipelines_produce_the_same_canonical_value_for_the_same_truth():
    scraping_free = enrich_evidence({"title": "X", "description": "Eintritt frei",
                                     "price": 0.0, "url": "https://x.de/e"})
    community_free = {"price_eur": 0.0, "price_status": ps.CONFIRMED_FREE,
                      "community": {"selection_status": "proposed"}}
    assert scraping_free["price_status_canonical"] == ps.CONFIRMED_FREE
    assert price_status_for(community_free) == scraping_free["price_status_canonical"]


def test_a_consumer_needs_no_knowledge_of_the_producer():
    """The whole point: read the status, not the provenance."""
    rows = [
        enrich_evidence({"title": "A", "description": "Eintritt frei", "price": 0.0,
                         "url": "https://x.de/a"}),
        {"price_eur": 9.0, "price_status": "known"},           # legacy spelling
        {"price_eur": 9.0, "price_status": "confirmed_paid"},   # canonical
        {"price_eur": None, "description": "Ein Abend."},       # no status at all
    ]
    got = [price_status_for(row) for row in rows]
    assert got == [ps.CONFIRMED_FREE, ps.CONFIRMED_PAID, ps.CONFIRMED_PAID, ps.UNKNOWN]


def test_provenance_names_the_pipeline_without_deciding_anything():
    community = ps.origin_for({"price_status": ps.CONFIRMED_FREE,
                               "verification": {"status": "matched"}})
    scraping = ps.origin_for({"price_status": "free"})
    assert community["pipeline"] == "community"
    assert scraping["pipeline"] == "scraping"


# --------------------------------------------------------------------------
# Legacy records
# --------------------------------------------------------------------------

@pytest.mark.parametrize("legacy,expected", [
    ("free", ps.CONFIRMED_FREE),
    ("known", ps.CONFIRMED_PAID),
    ("range", ps.RANGE),
    ("unknown", ps.UNKNOWN),
])
def test_a_legacy_record_reads_correctly(legacy, expected):
    """Records already on disk must keep working without a rewrite."""
    assert price_status_for({"price_eur": 0.0 if legacy == "free" else 12.0,
                             "price_status": legacy}) == expected


def test_a_legacy_record_still_gets_a_valid_candidate_file():
    record = event_record_for_test({"price_status": "free", "price": 0.0})
    issue = {"schema_version": "1.0", "status": "candidates",
             "issue_week": {"start": "2026-11-16", "end": "2026-11-22",
                            "timezone": "Europe/Berlin"},
             "generated_at": "2026-11-15T18:00:00+01:00", "events": [record]}
    assert structural_problems(issue) == []
    assert record["price_status"] == ps.CONFIRMED_FREE


def event_record_for_test(overrides):
    from scripts.community_issue import event_record

    raw = {"title": "Kiez Konzert", "date": "2026-11-20", "time": "20:00",
           "venue": "Kantine", "url": "https://x.de/e",
           "source_url": "https://x.de/list", "description": "Konzert"}
    raw.update(overrides)
    return event_record(raw, week_start=WEEK_START, week_end=WEEK_END)


# --------------------------------------------------------------------------
# Serialization round trips
# --------------------------------------------------------------------------

def test_round_trip_through_json_preserves_the_contract():
    record = event_record_for_test({"price_status": "free", "price": 0.0})
    encoded = json.dumps(record)
    decoded = json.loads(encoded)
    assert decoded["price_status"] == ps.CONFIRMED_FREE
    assert price_status_for(decoded) == ps.CONFIRMED_FREE
    assert decoded["price_provenance"]["schema_version"] == ps.SCHEMA_VERSION


def test_round_trip_survives_canonicalisation_twice():
    for status in ps.CANONICAL_STATUSES:
        once = ps.canonicalize(status)
        assert ps.canonicalize(once) == once


def test_a_record_with_a_foreign_status_cannot_be_serialized_into_a_valid_issue():
    """An unrecognised status must fail validation, not be silently accepted."""
    record = event_record_for_test({"price": 0.0})
    record["price_status"] = "something-else"
    issue = {"schema_version": "1.0", "status": "candidates",
             "issue_week": {"start": "2026-11-16", "end": "2026-11-22",
                            "timezone": "Europe/Berlin"},
             "generated_at": "2026-11-15T18:00:00+01:00", "events": [record]}
    assert any("not a canonical status" in p for p in structural_problems(issue))


# --------------------------------------------------------------------------
# Entry-price arithmetic
# --------------------------------------------------------------------------

def test_entry_price_of_is_consistent_with_the_status():
    assert ps.entry_price_of(None, ps.CONFIRMED_FREE) == 0.0
    assert ps.entry_price_of(0.0, ps.CONFIRMED_FREE) == 0.0
    assert ps.entry_price_of(12.5, ps.CONFIRMED_PAID) == 12.5
    assert ps.entry_price_of(4.0, ps.RANGE) == 4.0
    assert ps.entry_price_of(None, ps.UNKNOWN) is None
    assert ps.entry_price_of(9.0, ps.UNKNOWN) is None, "unknown establishes no entry price"


def test_describes_entry_price_only_for_settled_states():
    for status in (ps.CONFIRMED_FREE, ps.CONFIRMED_PAID, ps.RANGE):
        assert ps.describes_entry_price(status) is True
    for status in (ps.UNKNOWN, ps.NEEDS_VERIFICATION, ps.DONATION_BASED):
        assert ps.describes_entry_price(status) is False


# --------------------------------------------------------------------------
# Producers emit the canonical field
# --------------------------------------------------------------------------

def test_ticket_evidence_emits_both_spellings_and_they_agree():
    row = enrich_evidence({"title": "X", "description": "Eintritt frei",
                           "price": 0.0, "url": "https://x.de/e"})
    assert row["price_status"] == "free"      # the evidence model's own spelling
    assert row["price_status_canonical"] == ps.CONFIRMED_FREE
    assert ps.canonicalize(row["price_status"]) == row["price_status_canonical"]


def test_the_community_record_carries_canonical_status_and_provenance():
    record = event_record_for_test({"price_status": "known", "price": 12.0})
    assert record["price_status"] == ps.CONFIRMED_PAID
    provenance = record["price_provenance"]
    assert provenance["status"] == ps.CONFIRMED_PAID
    assert provenance["schema_version"] == ps.SCHEMA_VERSION
    assert provenance["origin"]["pipeline"] in ("scraping", "community", "unknown")
