# Full-corpus Community newsletter — 28 October 2026

The newsletter is now independent of the two-source pilot's published rows and
of the main page's personal scoring exclusions. Its input is every discovered
record from the full 33-entry source catalog in the existing weekly matrix.
All records are assessed against the same fresh, verified €0–5 ordinary-public-
admission policy; no ufaFabrik/Berlin Bühnen source allowlist limits the newsletter.
The main pilot dataset remains isolated to its two approved sources.

The read-only pilot producer reuses its fresh discovery, considers all remaining
catalog entries and records explicit robots, HTTP, extraction and budget outcomes.
A single shared 40-HTTP/six-Fetch/zero-Search budget covers both pilot and newsletter
work. It reserves HTTP attempts for detail verification. Therefore “full catalog”
does not mean every source succeeded or every discovered occurrence was verified.
Budget-deferred/blocked sources are reported, never counted as complete coverage.
The first expanded run assessed 181 input occurrences; the subsequent run assessed
178. Both considered all 33 source entries, with incomplete live coverage explicitly
reported. Neither produced an eligible event with sufficient evidence.

Verification slots are shared fairly across sources. Past/cancelled/sold-out
records and generic/listing URLs cannot occupy a newsletter slot. Production
verification/matching and overlay functions remain the sole verification algorithm.
A destination's matching JSON-LD Event may supply a missing venue and Berlin city/
location-type proof; a known venue disagreement still rejects the candidate.

Host classification uses the actual host, not the listing provider's domain:
reviewed venue identities or matching structured cultural/community/public-space
location types can qualify across sources. Mixed café/bar/restaurant/nightclub types
and café/bar/lounge venue names are rejected. Generic Place/EventVenue metadata
alone does not prove an eligible large/public host. Prices must be fresh regular
public admission up to €5; student/child/member-only prices do not qualify. Free
words alone, private access, missing proof and negative ticket evidence remain
excluded. Unknown inventory is never presented as available tickets.

The Community checkbox now reads the independently validated `newsletter.json`
feed, not the pilot's five-row event array. Its source labels, search, categories,
price labels and ICS export work across sources. Selection IDs are separate and
selection clears when switching between the two corpora. A positive browser test
uses a clearly synthetic external-source event to prove cross-source display/ICS;
no synthetic event is inserted into live artifacts.

The export contains scope, input count, complete source catalog, per-source outcomes,
coverage status and exclusion counts. It includes canonical event URLs, regular
public prices and evidence/expiry timestamps. The manifest checksums separate
`newsletter-discovery.json` and `newsletter-overlay.json`; promotion recomputes the
export from that full corpus and checks included occurrences for freshness. Foreign
newsletter sources cannot silently enter the general pilot dataset.

282 tests and Node checks passed before this report. Regressions cover an eligible
third-source event omitted by personal scoring, source-independent reviewed hosts,
restricted hospitality types/names, unverified records and misleading positive
coverage. Browser checks exercise a Community item absent from the pilot, including
ICS export, alongside the existing search/responsive/expiry behavior.

No canonical production dataset, repository variable or schedule is changed. The
previously authorized manual branch deployment route is used for publication only
after fresh candidate/manifest/CI validation. An empty newsletter means no included
record satisfied every criterion; it is not evidence that Berlin has no affordable
community events.
