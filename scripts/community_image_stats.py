#!/usr/bin/env python3
"""Image coverage reporting, per source.

Image extraction is decoration: nothing about it may invalidate an event. The
corollary is that its failures are silent unless something counts them, so this
module produces the counts - per source, because coverage varies enormously
between a venue whose cards carry posters and a listings site whose cards carry
nothing.

The distinction that matters operationally is between the three ways an image
ends up missing:

  * no image was **discovered** - the card and the detail page both said
    nothing. Expected for some sources; a parser gap for others.
  * an image was discovered but its URL **failed validation** - the organiser
    rotated the artwork or blocks hotlinking.
  * the URL was never **checked** - the run's check budget was smaller than the
    number of images, so absence of a verdict means nothing.

Reporting all three separately is what stops "0% coverage" from being read as
"the extractor is broken" when it means "nobody checked".

Raus is reported for what it is. Its listings are parsed by a dedicated card
parser that never runs the generic image hooks, so its coverage is structurally
lower and the architecture is deliberately not being rewritten to change that.
The report says so rather than implying a defect.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

# Sources whose events come from a dedicated parser rather than the generic
# extractors. Their coverage is reported but annotated, not failed on.
DEDICATED_PARSER_HOSTS = ("rausgegangen.de", "berlin-buehnen.de", "berlin.museum",
                          "volksbuehne-berlin.de")


def _source_of(event: Dict[str, Any]) -> str:
    """The listing an event came from, as a host, for grouping."""
    for field in ("source_url", "listing_url", "url"):
        raw = str(event.get(field) or "")
        if not raw.startswith(("http://", "https://")):
            continue
        host = (urlparse(raw).hostname or "").removeprefix("www.")
        if host:
            return host
    return "unknown"


def _uses_dedicated_parser(host: str) -> bool:
    return any(host == known or host.endswith("." + known) for known in DEDICATED_PARSER_HOSTS)


def image_stats(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Coverage for one batch of events, overall and per source."""
    events = [e for e in events or [] if isinstance(e, dict)]
    per_source: Dict[str, Dict[str, int]] = {}
    for event in events:
        host = _source_of(event)
        bucket = per_source.setdefault(host, {
            "events": 0,
            "with_image": 0,
            "verified": 0,
            "rejected": 0,
            "unchecked": 0,
            "no_image": 0,
        })
        bucket["events"] += 1
        url = event.get("image_url")
        if not url:
            bucket["no_image"] += 1
            continue
        bucket["with_image"] += 1
        verdict = event.get("image_verified")
        if verdict is True:
            bucket["verified"] += 1
        elif verdict is False:
            bucket["rejected"] += 1
        else:
            bucket["unchecked"] += 1

    for host, bucket in per_source.items():
        total = bucket["events"] or 1
        bucket["coverage_percent"] = round(100.0 * bucket["with_image"] / total, 1)
        bucket["dedicated_parser"] = _uses_dedicated_parser(host)

    totals = {
        "events": sum(b["events"] for b in per_source.values()),
        "with_image": sum(b["with_image"] for b in per_source.values()),
        "verified": sum(b["verified"] for b in per_source.values()),
        "rejected": sum(b["rejected"] for b in per_source.values()),
        "unchecked": sum(b["unchecked"] for b in per_source.values()),
        "no_image": sum(b["no_image"] for b in per_source.values()),
    }
    totals["coverage_percent"] = round(
        100.0 * totals["with_image"] / (totals["events"] or 1), 1
    )

    return {
        "totals": totals,
        "per_source": dict(sorted(per_source.items(), key=lambda kv: -kv[1]["events"])),
        # Sources with events but no artwork at all, so a silent parser gap is
        # visible in the weekly summary instead of only in the raw counts.
        "sources_without_images": sorted(
            host for host, b in per_source.items() if b["events"] and not b["with_image"]
        ),
        "notes": [
            "An image count of 0 means no artwork was found; failures are never "
            "a reason to reject an event.",
            "Coverage depends on the extraction route, not only on the source: "
            "Raus and the official programme adapters use dedicated card parsers "
            "that the generic image hooks do not see.",
        ],
    }


def render_stats_block(stats: Dict[str, Any], limit: int = 12) -> List[str]:
    """Markdown lines for the review summary's coverage section."""
    totals = stats.get("totals", {})
    lines = [
        "## Image coverage",
        "",
        f"- Events with artwork: {totals.get('with_image', 0)}/{totals.get('events', 0)} "
        f"({totals.get('coverage_percent', 0.0)}%)",
        f"- Verified image URLs: {totals.get('verified', 0)}",
        f"- Failed image URLs: {totals.get('rejected', 0)}",
        f"- Unchecked image URLs: {totals.get('unchecked', 0)}",
        f"- No artwork found: {totals.get('no_image', 0)}",
        "",
    ]
    per_source = list(stats.get("per_source", {}).items())[:limit]
    if per_source:
        lines.append("| source | events | with image | coverage | verified | failed | unchecked |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for host, bucket in per_source:
            marker = " (dedicated parser)" if bucket.get("dedicated_parser") else ""
            lines.append(
                f"| {host}{marker} | {bucket['events']} | {bucket['with_image']} | "
                f"{bucket['coverage_percent']}% | {bucket['verified']} | "
                f"{bucket['rejected']} | {bucket['unchecked']} |"
            )
        lines.append("")
    missing = stats.get("sources_without_images") or []
    if missing:
        lines.append("Sources with no artwork on any event this week: "
                     + ", ".join(missing))
        lines.append("")
    for note in stats.get("notes", []):
        lines.append(f"_Note: {note}_")
        lines.append("")
    return lines
