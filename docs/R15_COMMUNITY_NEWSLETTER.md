# R1.5 — iterative discovery repair and Community newsletter

28 October 2026. Technical GO for the bounded two-source pilot; no merge,
publication, schedule activation or repository-variable changes. Production
JSON and overlay are unchanged. The R1.4 release/manifest controls remain active.

## Cycles and evidence

| Run | Change tested | Published exact matches | ufaFabrik | Community export | HTTP / Fetch / Search |
|---|---|---|---|---|---|
| 40762582963 | Starting failure | 1/1 | 0 | not implemented | 14 / 3 / 0 |
| 40763906601 | Eligible candidates, date diversity | 3/3 | 0 | 0 | 12 / 2 / 0 |
| 40764423731 | Explicit ufa weekday/date/price rows | 5/5 | 2 | 1, subsequently rejected | 12 / 1 / 0 |
| 40764857340 | Preserve/exclude sold-out source warnings | 5/5 | 2 | **0** | 12 / 0 / 0 |

[Final run](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40764857340)
— [preview artifact 12849449339](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40764857340/artifacts/12849449339),
`r14-pilot-release-candidate`, 268200 bytes, seven-day retention. It includes
`site/newsletter.json`, the Community-enabled site, diagnostic evidence, overlay,
manifest/checksums, screenshots, browser results and ICS. Generated release data
is retained in artifacts/temporary storage, not committed to production datasets.
The intermediate cycle-2 export must not be used: it exposed the sold-out conflict.

Each new cycle discovered 51 occurrences, not 153 unique events. Final output is
three Berlin Bühnen occurrences (28/29 October and 4 November), and two ufaFabrik
GardiZero performances (30/31 October, 20:00). Exact publication coverage is 5/5;
discovery-to-publication coverage is only 5/51 (9.80%). The sample is deliberately
bounded; these metrics do not establish complete city-wide/source coverage.
Final inventory is UNKNOWN for all five published rows; three prices are UNKNOWN.
The two GardiZero performances have matched €12–25 tiers, including explicitly
conditional student admission; regular admission is €25.

Across the three improvement cycles: 36 direct attempts, three Fetch URLs, zero
Search requests. Per-run host and provider caps were unchanged. No paid endpoints,
login, CAPTCHA solving or circumvention proxies were used.

## Discovery and matching changes

The old sampler prioritized cancellation/status variants, wasting scarce live
verification slots on cancelled events, excluded children's programming and
above-budget events. The release sampler now applies the existing preference
exclusions first, avoids cancelled/postponed/sold-out candidates, prefers eligible
price hints and distinct dates, and uses remaining slots for additional events.
Introduction/free-access wording is only a discovery hint: destination verification
still determines prices, dates, venues and inventory. No title or URL reconstruction
is used as evidence.

GardiZero's actual detail page declares a date range and “Fr.–Sa. 20:00 Uhr”, with
scoped price rows. The general single-date matcher rejected it. A strict ufaFabrik
adapter now binds those explicit weekday/time rows to dates inside the declared
range (bounded to seven days), keeping each row's own prices. Unknown layouts,
missing weekday/time associations and duplicated occurrences fail closed. It does
not infer schedules from promotional prose or spread prices across unrelated
performances. Buy buttons do not assert availability. Both real dates and wrong-
date/title cases are regression tested against a sanitized real capture from run
40763906601; provenance is beside the fixture.

The structured adapter depends on the captured public DOM fields. A differently
cleaned provider representation that lacks those fields may remain UNKNOWN; no
claim is made that every ufa layout is supported.

## Community eligibility

As explicitly requested by the owner, **€5 means ordinary public admission**, not
student-only, child-only or membership pricing. €5 events are not labelled free.

An event needs a fresh exact occurrence match, verified event-specific URL, future
performance within the Berlin coming-week window, fresh matched price evidence,
Berlin venue proof and a reviewed host. Current host identities cover the approved
ufaFabrik campus rooms and reviewed theatres/opera houses. Explicit reviewed public
spaces (Bebelplatz, Tempelhofer Feld and Alexanderplatz) support public-space events
when the same evidence requirements are met. No street-event occurrence was live
qualified in this sample. The pilot's two-source allowlist is not expanded.

Venue identity is exact/curated, not a substring such as “theatre” in café branding.
Small cafés, bars, independent lounges and unreviewed hosts do not qualify. A
Varieté Salon performance at the large ufaFabrik cultural campus is treated by its
reviewed host identity, not mistaken for a standalone lounge. Explicit private,
members-only and invitation-only access is rejected.

Only unconditional regular offers whose upper price bound is at most €5 qualify.
Free admission requires independent unconditional structured free-price evidence;
free words or a companion/student exception alone are insufficient. Ambiguous,
missing and stale evidence is excluded, not converted to zero. Exact ordinary
labels such as Standard/Eintritt may qualify; restricted labels do not.

A live iteration found “Vor-Führung” at Staatsoper with a matched €5 price, but its
fresh listing card explicitly said Ausverkauft while the detail omitted inventory.
The old materialization reset that negative listing signal to UNKNOWN. The fix
preserves an exact, fresh listing sold-out warning and refuses it for Community;
selection also avoids known sold-out slots. Negative source text additionally
blocks newsletter eligibility. Silence on a detail page never proves availability.
Expired provider claims and fresh listing warnings now have separate regressions.

## Presentation and newsletter output

The interface adds **Community · validated €0–5**, alongside the existing Free
only filter. It preserves search, category chips, date/price ordering, responsive
tables, past-event handling and ICS export. Community and Free only can be combined.
Eligibility expires with fresh price/link evidence and the pilot's claim deadline.
A download link exposes the separate `newsletter.json` in the built site.

Both the shared production builder and pilot producer write that file. The manifest
requires/checksums it, and promotion recomputes its exact content from the validated
published rows. The export includes event identity, title, date/time, venue, canonical
URL, public price/range and EUR label, category/description, evidence timestamps,
expiry and explicit inventory caveats. Public price fields are recalculated from
regular admission rather than accidentally presenting a student-only minimum.
An empty export is valid and states why candidates did not qualify. It is ready
for downstream formatting, **not automatically sent** to anyone.

Final export count is **zero**: the real €5 opportunity was sold out, the ufaFabrik
regular price is €25, and the remaining published prices are unknown. This is not
proof that no affordable community events exist in Berlin. More independently
verified cheap events/hosts can expand the export in future bounded runs; the
policy must not be loosened to manufacture newsletter content.

## Verification and release status

274 Python tests passed. Node checks passed. Chromium smoke on the final candidate
passed search, categories, Community count/filter consistency, newsletter count,
responsive rendering, ICS and simulated expiry, without JS errors. Offline shared
build/schema and frozen browser behavior were retained (112 upcoming/464 total
rows at the frozen reference clock). CI reruns on the final follow-up commit.

One intermediate legacy test expected a fresh sold-out listing warning to vanish
alongside an expired provider claim; it was corrected to distinguish the two
requirements, while retaining stale-claim coverage and adding a separate negative-
listing regression. The complete final suite passes.

Technical GO is limited to the tested pilot and filtering logic. The newsletter
currently has no eligible items; unrestricted coverage and production activation
are not qualified. The final preview is from the PR branch and cannot be promoted
as a main release. After any separately approved merge, generate a new main-commit
candidate, review its actual manifest/counts/freshness, then obtain explicit
publication approval using the unchanged R1.4 owner-controlled sequence.
