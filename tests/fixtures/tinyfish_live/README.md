# Live qualification captures

Source: manual read-only Fetch Strategy Probe run
https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39065395186
at 2026-10-17 20:07:48 UTC (22:07 Europe/Berlin).

Exactly two Fetch URLs and two Search calls used the existing Actions secret.
`qualification_report.json` preserves the original run's outcomes, including the
initial unmatched Berlin Bühnen result. Do not rewrite it to reflect later fixes.
The present parser is replayed against the captured data by offline tests.

The two Fetch fixtures retain the documented `results`/`errors` envelope and
observed URL, final URL, format and text fields. They are **sanitized extracts**,
not byte-for-byte full provider responses: scripts, styling, navigation,
forms, images, personal/session attributes and all URL query/fragment data were
removed; original non-script content and structural tags were retained. Optional
provider metadata and Search snippets were not saved. No attributes were invented.
The sanitizer preserves existing `datetime` attributes: none are present here.
Because scripts were deliberately removed, these fixtures do not establish
whether the original provider response contained JSON-LD.

Artifact storage access from the cloud machine failed. Evidence-only recovery
runs 39065574438 and 39074656872 read the **same** artifact and exposed sanitized
JSON through check annotations; the latter chunked the larger fixture below
GitHub's annotation truncation limit. They made zero provider calls. All chunks
were recovered before JSON parsing; no partial fixture was treated as complete.

Berlin Bühnen includes multiple performances and recommended events. Its
25 October cancellation must never propagate to the selected 18 October
11:00 occurrence. ufaFabrik keeps venue/date/time/prices in a single article,
with prices of €26 regular / €22 reduced / €12 students (advance sale).
Neither page's ticket link constitutes positive availability evidence.
