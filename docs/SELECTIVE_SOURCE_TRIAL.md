# Selective source repair, TinyFish trial and Camoufox/date qualification

Branch: `codex/restore-before-tinyfish-search`.
Live review: https://jsonlord.github.io/event-scraper-github-actions/
Published snapshot: `4e508a7d5ce7e804ce9a5daccf4a3bd5f3a338e4`.

## Direct source adapters

Stadtmuseum now uses `https://www.berlin.museum/programm`; Volksbühne uses
`https://www.volksbuehne-berlin.de/`. Both run through direct HTTP. The adapters
bind title, full date/time, event link and venue to one actual programme card.
Museum status badges are removed from the identity title while their sold-out or
cancelled evidence remains in the card. Exact destination negative evidence also
excludes only the matching performance from the public preview.

[Direct qualification 40961793285](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40961793285)
for 29 October–5 November matched two samples from each source (2/2 Stadtmuseum,
2/2 Volksbühne), with zero missing links/venues in eight museum and 27 theatre
occurrences. No provider calls were needed. The original Raw Voice Lab venue
error and the museum sold-out title badge have real-response regression fixtures.

## Bounded TinyFish trial

[Run 40961000600](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40961000600)
used **two Search calls and zero Fetch URLs**. Both Search requests returned HTTP
200 and valid schemas in 1.684 and 1.262 seconds; they returned ten and zero URL
results, respectively. The ten candidates produced no verified Raus occurrence.
All three checked destinations were denied by the hosted runner's fresh robots
policy, so Fetch was never invoked. Search snippets supplied no event facts.

The feature remains manual and disabled by default, allowlisted to official Raus
event paths. Caps are two Search calls, three destination Fetch URLs and eight
additional direct HTTP attempts. The client uses free Fetch/Search endpoints,
`ttl: 0`, bounded timeouts and fail-closed 401/402/403/429 handling. No Agent,
Browser, proxy, login or CAPTCHA-solving service is invoked. No subsequent live
TinyFish call was made during the parser/browser/date fixes.

## Camoufox and the requested date range

The optional renderer is **Camoufox 0.5.8 (Firefox)**. Chromium remains the UI test
browser for our own static page; it was never the Raus scraper's renderer.
Camoufox is selected with the manual workflow input `raus_browser=camoufox`.
Robots permission is checked before browser launch or browser-binary download.
The renderer permits at most one listing navigation, twenty same-host GET
requests, a 45-second navigation and a 1.5 MB resulting DOM. It blocks third-party
resources, non-GET requests and login/report/CAPTCHA/checkout paths, performs no
clicks or solver interaction, and keeps TLS verification enabled.

The supplied URL matches the configured public listing template. The tested
URL is:

<https://rausgegangen.de/en/berlin/eventsbydate/?geospatial_query_type=CITY&lat=52.5&lng=13.405&city=berlin&active_city_name=Berlin&start_date=2026-11-01&end_date=2026-11-07>

The URL has the expected HTTPS host, English Berlin `eventsbydate` path, CITY
geospatial parameters and ISO `start_date`/`end_date`. A separate cloud direct
check received HTTP 403, so correct structure is not proof of successful date
filtering by the destination. Public date/location query parameters are now
retained in diagnostics; sensitive query parameters are removed.

The manual workflow accepts `window_start` and `window_end`. Both must be set
together; the range is inclusive, bounded to eight dates and within thirty days.
If omitted, both derive from the current Berlin date (today through today+7).
The selected range drives listing parameters, daily schedule crawling, event
filtering and the report. This prevents a future range being silently crawled
from today's schedule instead.

[Camoufox/date run 40963157968](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40963157968)
selected **1–7 November 2026**, installed Camoufox, passed all **199 tests** and
published **341 review rows**. Every published date is inside that
range, and both date parameters survive in the artifact URL. The runner's robots
check stopped the browser: **zero navigations and zero browser requests**,
outcome `robots_denied_or_unknown`. This is not a successful live browser
qualification, and no Raus event was asserted verified.

The recorded policy explicitly allows named crawlers but assigns `Disallow: /`
to the wildcard group. Our identity is `BerlinEventEvidence/1.0`, not one of those
named crawlers. No allowed crawler identity is impersonated. A different browser
engine does not establish permission for this scraper.

For this different November window, Stadtmuseum had five occurrences and 2/2
sample matches; Volksbühne had eighteen occurrences and 1/2 sample matches.
The unmatched Mata Leão occurrence loaded successfully but did not pass the
strict structured identity check; it remains uncorroborated. These selected
samples differ from the earlier 29 October–5 November samples and must not be
reported as complete source verification.

## Publication and remaining limits

The site, dataset and evidence report served by Pages match the artifact SHA-256
checksums. Chromium checked the identical served files locally: all 341 rows
render, search/sorting/Free-only/ICS-download checks pass, and there are no JS
errors. Calendar timezone/stable IDs, mobile table width, Community/category
controls and broader identity/price/venue completeness remain as recorded in the
previous rendering review. Raus access requires an approved feed, permission or
permitted original venue pages; changing engine alone did not qualify access.

The source APIs and browser are opt-in. Production JSON, repository variables and
main were not changed. No schedule was enabled and no branch was merged. Existing
main Sunday automation remains able to overwrite a manually published branch
review, as documented previously.

## Latest per-source measurements

### Selected-window measurements

Commit: `4e508a7d5ce7e804ce9a5daccf4a3bd5f3a338e4`; baseline scraper: `70787ed`.
Run time: 2026-10-29T23:06:05.652918+01:00; date window 2026-11-01 through 2026-11-07.

Direct HTTP with robots checks. TinyFish is disabled; 0/2 Search calls and 0/3 Fetch URLs. No Jina or production-data writes. Camoufox: robots_denied_or_unknown, 0 navigation(s). Publication is a separate explicitly requested job. Counts include all prices; ≤€20 is the legacy price filter. Samples require bound occurrence identity, never Search snippets.

| Source | Window rows | ≤€20 | Links missing | Venues missing | Exact samples | Conclusion |
|---|---:|---:|---:|---:|---:|---|
| rausgegangen_de | 0 | 0 | 0 | 0 | 0/0 | robots_denied |
| meetup_com_find | 6 | 6 | 0 | 0 | 0/2 | candidates_only |
| meetup_running | 10 | 10 | 0 | 1 | 0/2 | candidates_only |
| meetup_cycling | 5 | 5 | 0 | 1 | 0/2 | candidates_only |
| meetup_yoga | 10 | 10 | 0 | 0 | 0/2 | candidates_only |
| meetup_hiking | 10 | 10 | 0 | 2 | 0/2 | candidates_only |
| meetup_startup | 5 | 5 | 0 | 3 | 0/2 | candidates_only |
| meetup_founders | 6 | 6 | 0 | 4 | 0/2 | candidates_only |
| berlin_buehnen | 302 | 302 | 302 | 153 | 0/0 | candidates_only |
| zku_berlin | 1 | 1 | 0 | 1 | 0/1 | candidates_only |
| ufafabrik | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| stadtmuseum | 5 | 5 | 0 | 0 | 2/2 | supported_sample |
| werk9 | 1 | 1 | 0 | 1 | 0/1 | candidates_only |
| lakestudios | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| theclubmap | 26 | 26 | 0 | 26 | 0/2 | candidates_only |
| deutsches_theater | 24 | 24 | 0 | 24 | 0/2 | candidates_only |
| staatsoper_berlin | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| staatsballett_berlin | 2 | 2 | 0 | 1 | 0/2 | candidates_only |
| volksbuehne | 18 | 18 | 0 | 0 | 1/2 | supported_sample |
| reinickendorf_classics | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| dice_fm_berlin | 4 | 2 | 0 | 4 | 0/0 | candidates_only |
| improfabrik | 0 | 0 | 0 | 0 | 0/0 | no_dated_event_evidence |
| oper_in_berlin | 21 | 21 | 0 | 7 | 0/2 | candidates_only |
| venturecafe_berlin | 1 | 1 | 0 | 1 | 0/1 | candidates_only |
| ritterbutzke | 2 | 2 | 0 | 2 | 0/0 | candidates_only |
| renaissance_theater | 6 | 6 | 0 | 6 | 0/2 | candidates_only |
| freilandlabor_britz | 3 | 3 | 0 | 3 | 0/2 | candidates_only |
| thf_berlin | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| ausland_berlin | 2 | 2 | 0 | 2 | 0/2 | candidates_only |
| hau_hebbel_am_ufer | 0 | 0 | 0 | 0 | 0/0 | outside_seven_day_window |
| savvy_contemporary | 1 | 1 | 0 | 1 | 0/1 | candidates_only |
| silent_green | 1 | 1 | 0 | 1 | 0/0 | candidates_only |
| orangerie_neukoelln | 4 | 4 | 0 | 4 | 0/2 | candidates_only |

HTTP: 90/136 listing attempts + 38/40 detail attempts. Duration 76.091 seconds.

### Measurement limitations

- Direct HTTP for all sources; optional free Fetch/Search allowlisted to Raus destinations only.
- Source-adapter repair and Raus detail matching do not qualify the complete corpus.
- Counts are date-window candidates, not guaranteed upcoming verified events.
- At most two occurrence samples per source; exact matches never imply all source records are verified.
- Unknown prices/inventory remain unsupported; no Community/newsletter eligibility is asserted.
