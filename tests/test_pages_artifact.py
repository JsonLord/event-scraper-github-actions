"""The published artifact: both endpoints exist, and nothing draft leaks.

A GitHub project site is served from a subpath
(``/event-scraper-github-actions/``), which is why every community asset
reference has to be relative: an absolute ``/assets/community.css`` resolves
against the domain root and 404s on the live site while working perfectly in
local testing. These tests check the paths in the source files, because that
is where the mistake is introduced.
"""

import json
import re
from pathlib import Path

import pytest

from scripts.build_pages_site import build_site, find_leaks

REPO = Path(__file__).resolve().parent.parent


def _prepare_repo(tmp_path, *, latest=True, approved=True):
    """A miniature repo with the files the assembler reads."""
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<!doctype html><title>root</title>")
    community = tmp_path / "community"
    community.mkdir()
    (community / "index.html").write_text("<!doctype html><title>community</title>")
    (community / "assets").mkdir()
    (community / "assets" / "community.css").write_text(":root{--x:1}")
    (community / "assets" / "community.js").write_text("console.log(1)")
    (community / "archive").mkdir()
    (community / "archive" / "index.html").write_text("<title>archive</title>")
    (community / "archive" / "index.json").write_text(json.dumps({"issues": []}))
    (community / "schema").mkdir()
    (community / "schema" / "community-event.schema.json").write_text("{}")
    if latest:
        (community / "latest.json").write_text(json.dumps(
            {"schema_version": "1.0", "events": [], "count": 0}))
    if approved:
        (community / "approved").mkdir()
        (community / "approved" / "2026-11-16.json").write_text(json.dumps({"events": []}))
    # Draft directories that must never reach the artifact.
    for name in ("candidates", "reviewed"):
        (community / name).mkdir()
        (community / name / "2026-11-16.json").write_text(json.dumps({"events": [{"secret": name}]}))
    scored = tmp_path / "scored.json"
    scored.write_text(json.dumps({"count": 0, "events": []}))
    return tmp_path, scored


def test_the_artifact_contains_both_pages(tmp_path):
    repo, scored = _prepare_repo(tmp_path)
    site = repo / "_site"
    report = build_site(repo, site, scored_json=scored)
    assert report["ok"] is True
    assert (site / "index.html").is_file()
    assert (site / "community" / "index.html").is_file()
    assert (site / "events_scored.json").is_file()
    assert (site / ".nojekyll").is_file()


def test_the_community_page_has_its_assets_and_data(tmp_path):
    repo, scored = _prepare_repo(tmp_path)
    site = repo / "_site"
    build_site(repo, site, scored_json=scored)
    assert (site / "community" / "latest.json").is_file()
    assert (site / "community" / "assets" / "community.css").is_file()
    assert (site / "community" / "assets" / "community.js").is_file()
    assert (site / "community" / "archive" / "index.json").is_file()
    assert (site / "community" / "archive" / "index.html").is_file()


def test_approved_issues_are_published_to_the_archive_but_candidates_are_not(tmp_path):
    repo, scored = _prepare_repo(tmp_path)
    site = repo / "_site"
    report = build_site(repo, site, scored_json=scored)
    assert report["approved_issues"] == 1
    assert (site / "community" / "archive" / "2026-11-16.json").is_file()
    assert not (site / "community" / "candidates").exists()
    assert not (site / "community" / "reviewed").exists()


def test_no_candidate_or_reviewed_file_reaches_the_artifact(tmp_path):
    repo, scored = _prepare_repo(tmp_path)
    site = repo / "_site"
    build_site(repo, site, scored_json=scored)
    assert find_leaks(site) == []


def test_find_leaks_detects_a_candidate_file(tmp_path):
    """The leak check has to fail when it should, or it proves nothing."""
    site = tmp_path / "_site"
    (site / "community" / "candidates").mkdir(parents=True)
    (site / "community" / "candidates" / "2026-11-16.json").write_text("{}")
    assert find_leaks(site) == ["community/candidates/2026-11-16.json"]


def test_find_leaks_detects_a_reviewed_file(tmp_path):
    site = tmp_path / "_site"
    (site / "community" / "reviewed").mkdir(parents=True)
    (site / "community" / "reviewed" / "2026-11-16.json").write_text("{}")
    assert find_leaks(site) == ["community/reviewed/2026-11-16.json"]


def test_a_missing_latest_json_is_replaced_with_a_clear_empty_issue(tmp_path):
    repo, scored = _prepare_repo(tmp_path, latest=False)
    site = repo / "_site"
    build_site(repo, site, scored_json=scored)
    payload = json.loads((site / "community" / "latest.json").read_text())
    assert payload["events"] == []
    assert payload["count"] == 0


def test_the_artifact_is_rebuilt_from_scratch(tmp_path):
    repo, scored = _prepare_repo(tmp_path)
    site = repo / "_site"
    build_site(repo, site, scored_json=scored)
    stale = site / "stale.html"
    stale.write_text("old")
    build_site(repo, site, scored_json=scored)
    assert not stale.exists()


# --------------------------------------------------------------------------
# Project-site relative paths
# --------------------------------------------------------------------------

def _local_refs(html):
    return re.findall(r'(?:href|src)="([^"]+)"', html)


def test_the_community_page_uses_only_relative_asset_paths():
    html = (REPO / "community" / "index.html").read_text(encoding="utf-8")
    refs = [ref for ref in _local_refs(html) if not ref.startswith(("#", "http"))]
    assert refs, "expected at least one local reference"
    for ref in refs:
        assert not ref.startswith("/"), f"absolute path breaks the project-site base: {ref}"


def test_the_archive_page_uses_only_relative_asset_paths():
    html = (REPO / "community" / "archive" / "index.html").read_text(encoding="utf-8")
    refs = [ref for ref in _local_refs(html) if not ref.startswith(("#", "http"))]
    for ref in refs:
        assert not ref.startswith("/"), f"absolute path breaks the project-site base: {ref}"


def test_the_frontend_fetches_latest_json_relatively():
    js = (REPO / "community" / "assets" / "community.js").read_text(encoding="utf-8")
    assert 'DATA_URL = "latest.json"' in js
    assert "fetch(DATA_URL" in js
    # The candidate file must never be a fetch target.
    assert "candidates/" not in js


def test_the_frontend_hardcodes_no_event_data():
    """Every event comes from latest.json; nothing is embedded in the script."""
    js = (REPO / "community" / "assets" / "community.js").read_text(encoding="utf-8")
    assert "event_id" not in js or "event_id:" not in js
    assert "2026-" not in js, "a hardcoded date means event data leaked into the frontend"


def test_the_css_references_no_absolute_urls():
    css = (REPO / "community" / "assets" / "community.css").read_text(encoding="utf-8")
    for match in re.finditer(r"url\(([^)]+)\)", css):
        value = match.group(1).strip("'\" ")
        assert not value.startswith("/"), f"absolute CSS url: {value}"


def test_pages_workflow_checks_both_endpoints():
    workflow = (REPO / ".github" / "workflows" / "jekyll-gh-pages.yml").read_text(encoding="utf-8")
    assert "_site/index.html" in workflow
    assert "_site/community/index.html" in workflow
    assert "candidates" in workflow  # the leak refusal is present


def test_pages_workflow_rebuilds_on_community_changes():
    workflow = (REPO / ".github" / "workflows" / "jekyll-gh-pages.yml").read_text(encoding="utf-8")
    for trigger in ("community/latest.json", "community/index.html",
                    "community/assets/**", "community/approved/**"):
        assert trigger in workflow, f"missing trigger: {trigger}"
