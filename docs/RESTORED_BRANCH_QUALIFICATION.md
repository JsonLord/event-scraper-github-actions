# Restored branch: live scrape and rendering review

Live site: https://jsonlord.github.io/event-scraper-github-actions/

Successful run: https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40958376586

Artifact: `restored-branch-website-qualification` (14-day retention).
Published snapshot: `0c5e033963131db8851bae15c492f842035ac40d`. The production extraction, normalization,
scoring and frontend files are unchanged from `70787ed`; the harness bounds direct
HTTP and adds review labels. The subsequent documentation commit does not change
the published snapshot.

**Published for review. NO-GO for unattended operation or complete source verification.**

## Measured results

- 32/33 configured listings fetched; Rausgegangen explicitly denies the crawler.
- 525 per-source date-window occurrences before cross-source deduplication/personal filters; 376 published review rows.
- Three exact structured matches among 38 sampled occurrences: Stadtmuseum 2/2 and Volksbühne 1/2. Every other source remains candidate-only or empty/blocked in this check.
- 94/136 listing HTTP attempts and 40/40 detail attempts; 72.171 seconds of scraping/qualification. Zero TinyFish, Jina, browser or other provider calls.
- Twenty-four unsupported free claims suppressed; known sold-out/cancelled/postponed rows excluded from publication. Positive prices are labelled listing estimates. No positive inventory availability is asserted.
- All 158 restored tests passed on GitHub. Production JSON remained unchanged. Publication validated exact commit, two-hour freshness and site-file checksums.
- Live page, dataset and evidence-report SHA-256 hashes match the reviewed artifact. Chromium checked identical served files locally.

## Rendering and behaviour

All 376 rows render without JavaScript errors. Search, Free only,
sorting and ICS download passed the browser check.

| Published data gap | Rows |
|---|---:|
| Unknown price | 355 |
| Missing venue | 223 |
| Missing event-detail link | 197 |
| Missing time | 6 |
| Already started at inspection | 13 |
| Sufficiently supported zero-price row | 0 |

Zero sufficiently supported free rows does not establish that Berlin has no free events.

## Optimisation priorities

1. **Occurrence identity and adapters:** all 300 Berlin Bühnen candidates lacked detail links; ufaFabrik had five missing links and seven missing venues among seven rows. Recover links and locations from exact event sections; avoid nearby cards or title fragments. Keep insufficient evidence UNKNOWN.
2. **Upcoming filter:** hide already-started performances by default; expose a separate past-events option and explain missing time. Thirteen published rows had already started at inspection.
3. **Mobile layout:** at 390px, a 372px wrapper contains the 1,414px-wide culture table. Date/price columns are off-screen. Use cards with title, date, venue and price visible, and expandable descriptions. The document itself does not overflow.
4. **Filters:** this snapshot lacks Community/newsletter and category filters. Restore Community from the full corpus using validated normal public admission up to €5 and eligible public hosts; student-only prices must not qualify. Add source, date and known/unknown price filters.
5. **ICS portability:** downloads work, but there is no `TZID=Europe/Berlin`, and `Date.now()` changes UIDs on every export. Add an explicit timezone, stable occurrence IDs and required calendar timestamps.
6. **Accessibility:** all 376 row-selection checkboxes lack accessible names. Sorting uses clickable table headings without keyboard controls. Add labels and keyboard-operable sorting.

## Release state

The owner explicitly authorized this branch publication. No production JSON,
repository variable or default branch was changed, and no weekly writer was
dispatched. The branch's new qualification/publisher is manual-only, with
publication explicitly opted in for this exact branch.

**Existing default-branch automation remains active:** the repository's legacy
Weekly Event Scraper is configured for Sundays at 17:00 UTC (18:00 Berlin in
winter; next 1 November 2026). Its writes/publication and the main publisher can
overwrite this review build. They were not enabled or changed by this task.
The historical main workflows do not inherit guards from unmerged PR branches.

## Each website: interpretation

Candidate counts describe extraction, not verified event content. A zero exact
match can reflect missing metadata, wrong extracted identity or a failed detail
request. A zero sample count can reflect missing links/times, already-started
candidates or the shared detail budget. Supported samples do not qualify all rows
from a source. The table includes all 33 configured source entries, including the
seven Meetup searches.

### Source measurement table

Commit: `0c5e033963131db8851bae15c492f842035ac40d`; baseline scraper: `70787ed`.
Run time: 2026-10-29T22:31:29.933422+01:00; seven-day date window ends 2026-11-05.

Direct HTTP with robots checks; no TinyFish, Jina, browser or production-data writes during scraping. The separate explicitly requested publication job subsequently deployed the review build. Counts include all prices; ≤€20 is the legacy price filter. A supported sample requires exact structured title/date/time and venue or official canonical identity. This is sample evidence, not complete verification.

| Source | Window rows | ≤€20 | Links missing | Venues missing | Exact samples | Conclusion |
|---|---:|---:|---:|---:|---:|---|
| rausgegangen_de | 0 | 0 | 0 | 0 | 0/0 | robots_denied |
| meetup_com_find | 8 | 8 | 0 | 0 | 0/2 | candidates_only |
| meetup_running | 14 | 14 | 0 | 1 | 0/2 | candidates_only |
| meetup_cycling | 6 | 6 | 0 | 1 | 0/2 | candidates_only |
| meetup_yoga | 15 | 15 | 0 | 2 | 0/2 | candidates_only |
| meetup_hiking | 11 | 11 | 0 | 2 | 0/2 | candidates_only |
| meetup_startup | 5 | 5 | 0 | 3 | 0/2 | candidates_only |
| meetup_founders | 6 | 6 | 0 | 4 | 0/2 | candidates_only |
| berlin_buehnen | 300 | 300 | 300 | 153 | 0/0 | candidates_only |
| zku_berlin | 2 | 2 | 0 | 2 | 0/2 | candidates_only |
| ufafabrik | 7 | 3 | 5 | 7 | 0/2 | candidates_only |
| stadtmuseum | 12 | 12 | 1 | 12 | 2/2 | supported_sample |
| werk9 | 1 | 1 | 0 | 1 | 0/1 | candidates_only |
| lakestudios | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| theclubmap | 32 | 32 | 0 | 32 | 0/2 | candidates_only |
| deutsches_theater | 24 | 24 | 0 | 24 | 0/2 | candidates_only |
| staatsoper_berlin | 10 | 10 | 0 | 10 | 0/2 | candidates_only |
| staatsballett_berlin | 2 | 2 | 0 | 1 | 0/1 | candidates_only |
| volksbuehne | 27 | 27 | 0 | 25 | 1/2 | supported_sample |
| reinickendorf_classics | 1 | 1 | 0 | 0 | 0/1 | candidates_only |
| dice_fm_berlin | 1 | 1 | 0 | 1 | 0/0 | candidates_only |
| improfabrik | 0 | 0 | 0 | 0 | 0/0 | no_dated_event_evidence |
| oper_in_berlin | 21 | 21 | 0 | 4 | 0/1 | candidates_only |
| venturecafe_berlin | 0 | 0 | 0 | 0 | 0/0 | no_dated_event_evidence |
| ritterbutzke | 1 | 1 | 0 | 1 | 0/1 | candidates_only |
| renaissance_theater | 7 | 7 | 0 | 7 | 0/1 | candidates_only |
| freilandlabor_britz | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| thf_berlin | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| ausland_berlin | 2 | 2 | 0 | 2 | 0/1 | candidates_only |
| hau_hebbel_am_ufer | 2 | 2 | 0 | 2 | 0/1 | candidates_only |
| savvy_contemporary | 1 | 1 | 0 | 1 | 0/1 | candidates_only |
| silent_green | 2 | 2 | 0 | 2 | 0/0 | candidates_only |
| orangerie_neukoelln | 5 | 5 | 0 | 5 | 0/1 | candidates_only |

HTTP: 94/136 listing attempts + 40/40 detail attempts. Duration 72.171 seconds.

### Measurement limitations

- Direct HTTP only; provider/browser fallbacks disabled.
- Restored extraction and price enrichment are not the later production verification overlay.
- Counts are date-window candidates, not guaranteed upcoming verified events.
- At most two occurrence samples per source; exact structured matches never imply all source records are verified.
- Unknown prices/inventory remain unsupported; no Community/newsletter eligibility is asserted.
