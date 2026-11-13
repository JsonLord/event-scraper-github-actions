#!/usr/bin/env python3
"""Assemble the GitHub Pages artifact from the repository's source files.

The existing workflows built the site with a handful of ``cp`` commands
inlined in YAML. That works for one page and stops working the moment there
are two: the community page must be public while its candidate files must
not, and a rule expressed as "copy this directory" cannot express that.

So the artifact is assembled here, by an explicit allowlist. Two things follow
from that choice, and both are tested:

  * The root product keeps working exactly as before - same ``index.html``,
    same ``events_scored.json``, same ``.nojekyll``.
  * Only *approved* community data is copied. A candidate or reviewed file
    has no path into the artifact at all, so publication cannot happen by
    accident when a new staging file appears.

Usage:
    python scripts/build_pages_site.py --site-dir _site --scored-json docs/events_scored.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def copy_file(source: Path, destination: Path, required: bool = True,
              notes: Optional[List[str]] = None) -> bool:
    if not source.is_file():
        if required:
            raise FileNotFoundError(f"required source file is missing: {source}")
        if notes is not None:
            notes.append(f"skipped (absent): {source}")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def copy_tree(source: Path, destination: Path, notes: Optional[List[str]] = None) -> int:
    """Copy a directory's files; returns how many were copied."""
    if not source.is_dir():
        if notes is not None:
            notes.append(f"skipped (absent): {source}")
        return 0
    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def empty_latest() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "issue_week": {"start": None, "end": None, "timezone": "Europe/Berlin"},
        "generated_at": None,
        "published_at": None,
        "count": 0,
        "events": [],
    }


def build_site(
    repo_root: Path,
    site_dir: Path,
    scored_json: Optional[Path] = None,
    web_index: Optional[Path] = None,
    community_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Assemble the artifact and return a report describing what it contains."""
    notes: List[str] = []
    repo_root = Path(repo_root)
    site_dir = Path(site_dir)
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)

    # --- the existing product, unchanged -----------------------------------
    copy_file(web_index or (repo_root / "web" / "index.html"), site_dir / "index.html")
    if scored_json is not None:
        copy_file(Path(scored_json), site_dir / "events_scored.json")
    # Without .nojekyll, Pages runs Jekyll and drops paths beginning with an
    # underscore or a hash, which is how a built artifact silently loses files.
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    # --- the community product --------------------------------------------
    community = Path(community_root or (repo_root / "community"))
    community_out = site_dir / "community"
    community_out.mkdir(parents=True, exist_ok=True)

    copy_file(community / "index.html", community_out / "index.html")
    copy_file(community / "README.md", community_out / "README.md", required=False, notes=notes)
    copy_tree(community / "assets", community_out / "assets", notes=notes)

    # latest.json is the only event data the public page reads. If promotion
    # has never run, publish the empty state explicitly rather than letting
    # the page 404 into an ambiguous error.
    latest_source = community / "latest.json"
    if latest_source.is_file():
        copy_file(latest_source, community_out / "latest.json")
    else:
        (community_out / "latest.json").write_text(
            json.dumps(empty_latest(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        notes.append("latest.json was absent; published an empty issue")

    archive_source = community / "archive" / "index.json"
    if archive_source.is_file():
        copy_file(archive_source, community_out / "archive" / "index.json")
    else:
        (community_out / "archive").mkdir(parents=True, exist_ok=True)
        (community_out / "archive" / "index.json").write_text(
            json.dumps({"schema_version": "1.0", "issues": [], "count": 0,
                        "updated_at": None}, indent=2) + "\n",
            encoding="utf-8",
        )

    # The archive page enumerates the published issues the index points at.
    copy_file(community / "archive" / "index.html",
              community_out / "archive" / "index.html", required=False, notes=notes)

    # Per-week published issues, so archive links resolve. Only the approved
    # directory is ever walked.
    approved_dir = community / "approved"
    approved_copied = 0
    if approved_dir.is_dir():
        for path in sorted(approved_dir.glob("*.json")):
            copy_file(path, community_out / "archive" / path.name, required=False, notes=notes)
            approved_copied += 1
    notes.append(f"approved issues published to archive/: {approved_copied}")

    # The schema is public documentation of the contract and safe to serve.
    schema_copied = copy_tree(community / "schema", community_out / "schema", notes=notes)
    if schema_copied:
        notes.append(f"schemas published: {schema_copied}")

    report = {
        "site_dir": str(site_dir),
        "root_index": (site_dir / "index.html").is_file(),
        "root_scored_json": (site_dir / "events_scored.json").is_file(),
        "community_index": (site_dir / "community" / "index.html").is_file(),
        "community_latest": (site_dir / "community" / "latest.json").is_file(),
        "community_css": (site_dir / "community" / "assets" / "community.css").is_file(),
        "community_js": (site_dir / "community" / "assets" / "community.js").is_file(),
        "community_archive_index": (site_dir / "community" / "archive" / "index.json").is_file(),
        "community_archive_page": (site_dir / "community" / "archive" / "index.html").is_file(),
        "approved_issues": approved_copied,
        "notes": notes,
    }
    report["ok"] = all([
        report["root_index"],
        report["community_index"],
        report["community_latest"],
        report["community_css"],
        report["community_js"],
        report["community_archive_index"],
        report["community_archive_page"],
    ])
    return report


# Files that must never appear in a published artifact. Checked as a report
# rather than assumed, because a new staging directory is exactly the kind of
# thing a future change adds without noticing this module.
FORBIDDEN_SUFFIXES = ("/candidates/", "/reviewed/")
FORBIDDEN_EXACT = ("community/latest.json.bak",)


def find_leaks(site_dir: Path) -> List[str]:
    """Paths inside the artifact that should never be public."""
    leaks: List[str] = []
    site_dir = Path(site_dir)
    if not site_dir.is_dir():
        return leaks
    for path in site_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(site_dir).as_posix()
        probe = "/" + relative
        if any(fragment in probe for fragment in FORBIDDEN_SUFFIXES):
            leaks.append(relative)
        elif relative in FORBIDDEN_EXACT:
            leaks.append(relative)
    return leaks


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble the GitHub Pages artifact")
    parser.add_argument("--site-dir", default="_site")
    parser.add_argument("--scored-json", default=None,
                        help="Scored events JSON to publish at the site root")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--community-root", default=None)
    parser.add_argument("--report", default=None, help="Write the report JSON here")
    parser.add_argument("--check-only", action="store_true",
                        help="Fail if a forbidden file would be published")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    report = build_site(
        repo_root,
        Path(args.site_dir),
        scored_json=Path(args.scored_json) if args.scored_json else None,
        community_root=Path(args.community_root) if args.community_root else None,
    )
    leaks = find_leaks(Path(args.site_dir))
    report["forbidden_paths"] = leaks
    report["ok"] = report["ok"] and not leaks

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    for note in report["notes"]:
        print(f"  {note}")
    print(
        "Artifact: root index.html={root_index}, events_scored.json={root_scored_json}, "
        "community/index.html={community_index}, latest.json={community_latest}".format(**report)
    )
    if leaks:
        print("::error::forbidden paths in artifact: " + ", ".join(leaks))
        return 1
    if not report["ok"]:
        print("::error::artifact is incomplete")
        return 1
    if args.check_only:
        print("Artifact is complete and contains no candidate or reviewed files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
