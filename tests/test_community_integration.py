"""Integration of the community pipeline with the TinyFish/search implementation.

The two implementations were written against the same aggregate but by
different routes, so the interesting failures are not textual merge conflicts -
they are semantic ones at the seams:

  * the scraping pipeline stamps rows with its own ``price_status`` vocabulary
    and, after scoring, with ``enrich_evidence()``; the community pipeline has a
    different vocabulary in the same field name
  * the scraping pipeline assigns ``sha256:`` occurrence ids; the community
    files require ``ce-`` ids
  * the newer scraper has dedicated card parsers (Raus listing, official
    programme adapters) that return dicts the generic image hooks never see
  * the Raus path has its own window, identity and publication gate that the
    community image pass must not disturb

These tests pin those seams. They deliberately exercise the *real* modules on
both sides rather than stubs, so a future refactor of either side that breaks
the other fails here.
"""

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("bs4")

from scripts.community_common import (
    PRICE_STATUS_CONFIRMED_FREE,
    PRICE_STATUS_CONFIRMED_PAID,
    PRICE_STATUS_DONATION,
    PRICE_STATUS_UNKNOWN,
    price_status_for,
)
from scripts.community_issue import (
    event_record,
    is_community_event_id,
    publication_problems,
)
from scripts.community_validate import structural_problems
from scripts.ticket_evidence import enrich_evidence

WEEK_START = date(2026, 11, 16)
WEEK_END = date(2026, 11, 22)
ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# Price vocabularies
# --------------------------------------------------------------------------

def test_the_pipelines_evidence_model_classifies_free_with_proof():
    """Sanity-check the other side of the seam we are mapping onto."""
    row = enrich_evidence({"title": "Konzert", "description": "Eintritt frei",
                           "price": 0.0, "url": "https://x.de/e"})
    assert row["price_status"] == "free"
    assert row["price"] == 0.0
    assert row["free_admission_confirmed"] is True


def test_the_pipelines_legacy_zero_is_not_proof_of_free_entry():
    """A bare 0 with no text stays unpriced on both sides of the seam."""
    row = enrich_evidence({"title": "Konzert", "description": "Ein Abend.",
                           "price": 0.0, "url": "https://x.de/e"})
    assert row["price"] is None
    assert row["price_status"] == "unknown"
    assert row["free_admission_confirmed"] is False


def test_community_reads_the_evidence_vocabulary_without_discarding_it():
    for evidence, expected in (
        ("free", PRICE_STATUS_CONFIRMED_FREE),
        ("known", PRICE_STATUS_CONFIRMED_PAID),
        ("unknown", PRICE_STATUS_UNKNOWN),
    ):
        row = {"price_eur": 0.0 if evidence == "free" else 12.5,
               "price_status": evidence, "description": "Konzert"}
        assert price_status_for(row) == expected, evidence


def test_evidence_status_and_community_status_share_a_field_name():
    """The two vocabularies are disjoint, so attribution needs no guessing."""
    community_only = {"price_eur": 0.0, "price_status": "confirmed_free"}
    evidence_only = {"price_eur": 0.0, "price_status": "free"}
    assert price_status_for(community_only) == PRICE_STATUS_CONFIRMED_FREE
    assert price_status_for(evidence_only) == PRICE_STATUS_CONFIRMED_FREE
    # ...and a community `unknown` is not mistaken for evidence `unknown`
    # (same spelling, same meaning, so either attribution is correct).
    assert price_status_for({"price_eur": None, "price_status": "unknown"}) == PRICE_STATUS_UNKNOWN


def test_a_real_enriched_row_survives_the_community_classifier():
    """End to end: the scraping pipeline's own output, classified by us."""
    free_row = enrich_evidence({"title": "Markt", "description": "Eintritt frei",
                                "price": 0.0, "url": "https://x.de/m"})
    paid_row = enrich_evidence({"title": "Konzert", "description": "18,00 €",
                                "price": 18.0, "url": "https://x.de/k"})
    assert price_status_for(free_row) == PRICE_STATUS_CONFIRMED_FREE
    assert price_status_for(paid_row) == PRICE_STATUS_CONFIRMED_PAID


def test_donation_stays_distinct_from_free():
    row = {"price_eur": 0.0, "description": "Eintritt auf Spendenbasis"}
    assert price_status_for(row) == PRICE_STATUS_DONATION


def test_an_unpriced_row_is_never_published_as_free():
    """The seam that matters: neither side may turn absence into zero."""
    unpriced = enrich_evidence({"title": "Konzert", "description": "Ein Abend.",
                                "price": 0.0, "url": "https://x.de/e"})
    record = event_record(
        {**unpriced, "date": "2026-11-20", "time": "20:00", "venue": "Kantine",
         "source_url": "https://x.de/l"},
        week_start=WEEK_START, week_end=WEEK_END,
    )
    assert record["price_status"] == PRICE_STATUS_UNKNOWN
    assert "price_unknown" in publication_problems(record, WEEK_START, WEEK_END)


# --------------------------------------------------------------------------
# Identity namespaces
# --------------------------------------------------------------------------

def test_a_foreign_occurrence_id_is_not_adopted():
    """ticket_evidence assigns `sha256:` ids; community files require `ce-`."""
    raw = {"title": "Kiez Konzert", "date": "2026-11-20", "time": "20:00",
           "venue": "Kantine", "price": 0.0, "price_status": "free",
           "url": "https://x.de/e", "source_url": "https://x.de/l",
           "event_id": "sha256:abc123def456", "description": "Konzert"}
    record = event_record(raw, week_start=WEEK_START, week_end=WEEK_END)
    assert is_community_event_id(record["event_id"])
    assert record["event_id"].startswith("ce-")


def test_a_community_id_is_preserved_through_the_record():
    wanted = "ce-" + "b" * 24
    raw = {"title": "Kiez Konzert", "date": "2026-11-20", "venue": "Kantine",
           "url": "https://x.de/e", "event_id": wanted, "description": "Konzert"}
    assert event_record(raw, week_start=WEEK_START, week_end=WEEK_END)["event_id"] == wanted


def test_the_community_id_namespace_is_accepted_by_the_validator():
    record = event_record(
        {"title": "Kiez Konzert", "date": "2026-11-20", "venue": "Kantine",
         "url": "https://x.de/e", "price": 0, "price_status": "free"},
        week_start=WEEK_START, week_end=WEEK_END,
    )
    issue = {"schema_version": "1.0", "status": "candidates",
             "issue_week": {"start": WEEK_START.isoformat(),
                            "end": WEEK_END.isoformat(), "timezone": "Europe/Berlin"},
             "generated_at": "2026-11-15T18:00:00+01:00", "events": [record]}
    assert structural_problems(issue) == []


# --------------------------------------------------------------------------
# Scraper seams: images in the newer extraction architecture
# --------------------------------------------------------------------------

def test_image_helpers_are_importable_from_the_integrated_scraper():
    from scripts import generic_event_scraper as scraper

    for name in ("_attach_card_image", "_attach_listing_images",
                 "_attach_document_images", "enrich_missing_images"):
        assert callable(getattr(scraper, name)), name


def test_the_generic_listing_parser_keeps_its_images():
    """A generic card with lazy artwork still yields an image after the merge."""
    from scripts.generic_event_scraper import extract_heuristic_events

    html = """<html><body><div class="event-listing">
      <div class="block block-teaser block-teaser-event">
        <h3>Konzert Nummer 1</h3>
        <a href="/veranstaltung/konzert-1">Details</a>
        <img data-src="/media/poster.jpg" alt="Konzert Poster">
        <span>01.09.2026, 20:00 Uhr</span>
      </div></div></body></html>"""
    events = extract_heuristic_events(html, "https://example.de/programm")
    assert events and events[0]["image_url"] == "https://example.de/media/poster.jpg"


def test_a_dedicated_listing_parser_gets_images_attached():
    """Rows from a card parser the generic hooks never see still get artwork."""
    from scripts.generic_event_scraper import _attach_listing_images

    html = """<html><body>
      <article class="card">
        <a href="/events/giddy-club">
          <img src="/media/giddy.jpg" alt="Giddy Club">
          <h3>Giddy Club</h3>
        </a>
      </article></body></html>"""
    rows = [{"title": "Giddy Club", "date": "2026-11-20", "url": "https://x.de/events/giddy-club"}]
    out = _attach_listing_images(rows, html, "https://x.de/events")
    assert out[0]["image_url"] == "https://x.de/media/giddy.jpg"
    assert out[0]["image_source"] == "event_card_image"


def test_official_adapter_rows_get_images_matched_by_event_link():
    from scripts.generic_event_scraper import _attach_document_images

    html = """<html><body>
      <a class="teaser" href="/veranstaltung/abend">
        <img src="/media/abend.jpg" alt="Abendvorstellung">
        <h3>Abendvorstellung</h3>
      </a></body></html>"""
    rows = [{"title": "Abendvorstellung", "url": "https://x.de/veranstaltung/abend"}]
    out = _attach_document_images(rows, html, "https://x.de/programm")
    assert out[0]["image_url"] == "https://x.de/media/abend.jpg"


def test_image_attachment_never_invents_and_never_raises():
    from scripts.generic_event_scraper import _attach_listing_images

    rows = [{"title": "No artwork", "url": "https://x.de/events/none"}]
    out = _attach_listing_images(rows, "<html><body></body></html>", "https://x.de/events")
    assert "image_url" not in out[0]
    # Malformed markup must not blow up a whole source.
    assert _attach_listing_images(rows, "<html", "https://x.de") == rows


def test_the_logo_next_to_artwork_is_still_rejected_after_the_merge():
    from scripts.generic_event_scraper import _attach_listing_images

    html = """<html><body><div class="card">
        <a href="/events/x"><img src="/static/logo.svg" alt="Site logo">
        <h3>X</h3></a></div></body></html>"""
    rows = [{"title": "X", "url": "https://x.de/events/x"}]
    assert "image_url" not in _attach_listing_images(rows, html, "https://x.de/events")[0]


# --------------------------------------------------------------------------
# Raus path untouched by the community pass
# --------------------------------------------------------------------------

def test_raus_listing_detection_is_intact():
    from scripts.raus_html import is_listing

    assert is_listing("https://rausgegangen.de/en/berlin/eventsbydate/?start_date=2026-11-16")
    assert not is_listing("https://www.stadtmuseum.de/programm")


def test_raus_records_are_recognised_for_exclusion_from_generic_paths():
    from scripts.raus_html import is_raus_record

    assert is_raus_record({"url": "https://rausgegangen.de/en/events/x/"})
    assert not is_raus_record({"url": "https://www.deutschestheater.de/programm/x"})


def test_the_raus_window_comes_from_the_url_not_scrape_window():
    """The image pass must not run on a path whose window is URL-derived."""
    from scripts.raus_html import _window

    window = _window("https://rausgegangen.de/en/berlin/eventsbydate/"
                     "?start_date=2026-11-16&end_date=2026-11-22")
    assert window is not None
    assert window[0].isoformat() == "2026-11-16"


def test_raus_identity_is_its_own_namespace():
    from scripts.raus_html import identity

    first = identity({"title": "Giddy Club", "date": "2026-11-20", "time": "23:00",
                      "url": "https://rausgegangen.de/en/events/giddy-club-1/"})
    second = identity({"title": "Giddy Club", "date": "2026-11-27", "time": "23:00",
                       "url": "https://rausgegangen.de/en/events/giddy-club-1/"})
    assert first != second, "a recurring occurrence must stay separately addressable"


def test_raus_publication_gate_still_refuses_an_unproven_occurrence():
    from scripts.raus_html import BERLIN, publication_gate

    now = datetime(2026, 11, 15, 18, 0, tzinfo=BERLIN)
    event = {"title": "Giddy Club", "date": "2026-11-20", "time": "23:00",
             "url": "https://rausgegangen.de/en/events/giddy-club-1/",
             "source_url": "https://rausgegangen.de/en/berlin/eventsbydate/", "price": 0.0}
    # No matching observation evidence, so the gate must refuse it.
    assert publication_gate(event, None, now, date(2026, 11, 16), date(2026, 11, 22), 20) is None


# --------------------------------------------------------------------------
# Price limits stay separate
# --------------------------------------------------------------------------

def test_the_personal_cap_is_still_twenty():
    from scripts.event_utils import DEFAULT_MAX_PRICE
    from scripts.score_events import MAX_PRICE

    assert DEFAULT_MAX_PRICE == 20.0
    assert MAX_PRICE == 20.0


def test_the_community_cap_is_still_fifteen_and_independent():
    from scripts.community_common import COMMUNITY_MAX_PRICE

    assert COMMUNITY_MAX_PRICE == 15.0


def test_the_community_selection_does_not_import_personal_scoring():
    """Editorial policy must not depend on one person's preference profile."""
    import ast

    source = (ROOT / "scripts" / "community_select.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    assert not any("score_events" in name for name in imported), imported
    # The personal profile's constants must not appear as code either.
    tree_names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
    tree_names |= {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}
    for forbidden in ("CHARLOTTENBURG_KEYWORDS", "FAVORITE_SOURCES", "PREFERRED_PRICE",
                      "PROXIMITY_BONUS"):
        assert forbidden not in tree_names, f"community selection uses personal policy: {forbidden}"


def test_personal_scoring_is_unchanged():
    """The personal scorer's behaviour on this branch, pinned as-is.

    A bare ``price: 0`` with no corroborating text is already treated as
    unpriced by this branch's evidence model, so this asserts the branch's
    actual behaviour rather than the older "0 is free" reading.
    """
    from scripts.score_events import score_event

    scored = score_event({"title": "Techno Nacht", "date": "2026-11-20", "time": "23:00",
                          "price": 0.0, "venue": "Kantine", "category": "music",
                          "description": "Tanznacht", "url": "https://x.de/e",
                          "has_detail_link": True})
    assert 0 <= scored["score"] <= 100
    assert scored["stream"] in ("main", "network", "sport")
    assert scored["price_label"] == "Check site"
    assert scored["price"] is None

    proven_free = score_event({"title": "Techno Nacht", "date": "2026-11-20", "time": "23:00",
                               "price": 0.0, "venue": "Kantine", "category": "music",
                               "description": "Eintritt frei", "url": "https://x.de/e",
                               "has_detail_link": True})
    assert proven_free["price_label"] == "Free"


# --------------------------------------------------------------------------
# Workflow compatibility
# --------------------------------------------------------------------------

def test_the_weekly_workflow_keeps_both_sides():
    workflow = (ROOT / ".github" / "workflows" / "weekly-event-scraper.yml").read_text(encoding="utf-8")
    # TinyFish/search side: corrected source URLs and Berlin-local dates.
    assert "https://www.berlin.museum/programm" in workflow
    assert "https://www.volksbuehne-berlin.de/" in workflow
    assert "TZ=Europe/Berlin" in workflow
    # Community side: image enrichment and the allowlisted artifact.
    assert "--image-enrich-limit" in workflow
    assert "build_pages_site.py" in workflow
    assert "path: ./_site" in workflow


def test_the_weekly_workflow_keeps_its_schedule():
    workflow = (ROOT / ".github" / "workflows" / "weekly-event-scraper.yml").read_text(encoding="utf-8")
    assert "cron: '0 17 * * 0'" in workflow


def test_the_fetch_probe_workflow_is_untouched():
    """The TinyFish fetch-strategy probe is search-side only; community must not alter it."""
    probe = (ROOT / ".github" / "workflows" / "fetch-strategy-probe.yml").read_text(encoding="utf-8")
    assert "community" not in probe.lower()


def test_community_workflows_exist_and_are_manual():
    root = ROOT / ".github" / "workflows"
    for name in ("community-prepare.yml", "community-promote.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert "workflow_dispatch" in text, name
        assert "TINYFISH" not in text, name


def test_the_pages_workflow_builds_both_endpoints_from_the_allowlist():
    workflow = (ROOT / ".github" / "workflows" / "jekyll-gh-pages.yml").read_text(encoding="utf-8")
    assert "build_pages_site.py" in workflow
    assert "_site/index.html" in workflow
    assert "_site/community/index.html" in workflow


def test_no_candidate_or_reviewed_data_reaches_the_published_artifact(tmp_path):
    from scripts.build_pages_site import build_site, find_leaks

    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    (repo / "web" / "index.html").write_text("<!doctype html><title>root</title>")
    community = repo / "community"
    for sub in ("assets", "archive", "approved", "candidates", "reviewed", "schema"):
        (community / sub).mkdir(parents=True)
    (community / "index.html").write_text("<title>community</title>")
    (community / "assets" / "community.css").write_text(":root{}")
    (community / "assets" / "community.js").write_text("1")
    (community / "archive" / "index.html").write_text("<title>archive</title>")
    (community / "archive" / "index.json").write_text('{"issues":[]}')
    (community / "latest.json").write_text('{"events":[]}')
    (community / "approved" / "2026-11-16.json").write_text('{"events":[]}')
    (community / "candidates" / "2026-11-16.json").write_text('{"draft":true}')
    (community / "reviewed" / "2026-11-16.json").write_text('{"draft":true}')
    scored = tmp_path / "scored.json"
    scored.write_text('{"events":[]}')

    report = build_site(repo, tmp_path / "site", scored_json=scored)
    assert report["ok"] is True
    assert find_leaks(tmp_path / "site") == []
    assert not (tmp_path / "site" / "community" / "candidates").exists()
    assert not (tmp_path / "site" / "community" / "reviewed").exists()


# --------------------------------------------------------------------------
# Editorial prose on data the search branch actually produces
# --------------------------------------------------------------------------

def test_listing_card_chrome_is_stripped_from_the_recommendation_reason():
    """Two thirds of this branch's aggregate descriptions open with date chrome.

    A reason that begins "… at Kantine — Do, 15. Okt | 19:00 FREE ENTRY:"
    reads as scraped rather than written, so the preamble is removed before a
    sentence is chosen.
    """
    from scripts.community_select import build_recommendation_reason

    reason = build_recommendation_reason({
        "title": "Jam Session", "price_eur": 0.0, "price_status": "confirmed_free",
        "category": "music", "venue": "Kantine", "district": "Kreuzberg",
        "description": "Do, 15. Okt | 19:00 FREE ENTRY: JAM SESSION - CLUB SPECIAL DNA. "
                       "CLUB Free admission",
    })
    assert "Do, 15. Okt" not in reason
    assert "FREE ENTRY" not in reason
    assert "at Kantine" in reason


def test_german_weekday_abbreviations_are_stripped():
    from scripts.community_select import _strip_generic_opening

    for raw, expected in (
        ("Sa, 12. Okt | 20:00 Konzert im Hinterhof", "Konzert im Hinterhof"),
        ("Today, 11. Okt | 10:00 TAG DER CLUBKULTUR", "TAG DER CLUBKULTUR"),
        ("11/11/26 - 19:00 Sphagnum russowii", "Sphagnum russowii"),
        ("Freitag, 20. November 2026 - 19:00 Lesung", "Lesung"),
        ("Tomorrow 20:00 Late night jazz", "Late night jazz"),
    ):
        assert _strip_generic_opening(raw) == expected, raw


def test_ordinary_prose_is_left_alone():
    from scripts.community_select import _strip_generic_opening

    text = "Ein Abend mit Livemusik und Gästen im Hinterhof."
    assert _strip_generic_opening(text) == text


def test_a_raus_listing_parsed_via_plain_fetch_also_gets_images(monkeypatch):
    """Both Raus entry points must agree about image fields.

    ``scrape()`` handles a staging/plain-fetch listing while ``main()`` runs the
    dedicated direct pipeline. Artwork should not depend on which one ran, and
    nothing else about the rows may change.
    """
    from scripts import generic_event_scraper as scraper

    html = """<html><body>
      <article class="card">
        <a href="https://rausgegangen.de/en/events/giddy-club-1/">
          <img src="https://rausgegangen.de/media/giddy.jpg" alt="Giddy Club">
          <h3>Giddy Club</h3>
        </a>
        <time datetime="2026-11-20 23:00">20 Nov</time>
      </article></body></html>"""
    monkeypatch.setattr(scraper, "fetch_plain", lambda url: html)
    rows = scraper.scrape(
        "https://rausgegangen.de/en/berlin/eventsbydate/"
        "?start_date=2026-11-16&end_date=2026-11-22"
    )
    assert rows, "the listing parser should still find the card"
    assert all(row["price"] is None for row in rows), "no price may be invented"
    assert any(
        row.get("image_url") == "https://rausgegangen.de/media/giddy.jpg" for row in rows
    ), rows
