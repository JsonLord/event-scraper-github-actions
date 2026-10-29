# Discovery coverage repair — 29 October 2026

The previous newsletter run deferred fifteen catalog entries because listing
requests shared the pilot verifier's 40-request allowance. An unchanged zero on
`fresh_discovery_reused` also concealed the actual fresh ufaFabrik/Bühnen count.

Catalog discovery now owns a separate direct-HTTP budget, using at most two host
workers. Every source receives up to four attempts, including robots, redirects,
retries and public structured endpoints. Host groups share robots and blocking
state and are capped at sixteen attempts. For the current 33-entry catalog the
absolute discovery bound is 132 attempts/66 MB, reduced by reused sources and
shared hosts; the discovery deadline is 240 seconds within the existing 600-second
pipeline deadline. Each response remains capped at 1.5 MB. No discovery provider
calls are made. The existing 40 direct verifier attempts and six TinyFish Fetch
URLs/zero Search calls remain capped separately. Both phases' actual consumption
is reported, rather than concealing discovery in verifier counters.

Successful discovery's robots decisions, blocked hosts and documents transfer to
the production verifier. A 403 host is not probed again for each event. Different
hosts cannot spend one another's discovery allowance. Failure of robots retrieval
still fails closed; diagnostics distinguish unknown policy from an explicit ban.
No proxy, CAPTCHA handling, paid endpoint or browser retrieval is introduced.

The Clubmap's public WordPress event API is now reached through that same bounded,
robots-checked client. Only actual EventON performance timestamps are eligible;
WordPress publication dates cannot substitute. Unix timestamps use Berlin time,
including date rollover/DST. The API yields candidates, not verified admission.

Diagnostics distinguish received listings, raw candidates, occurrences in the
future window, detail-URL candidates, fresh exact matches and publishable
newsletter events. A fetched page or discovered record cannot make source
coverage complete. Sanitized Meetup queries retain distinct named-source
provenance through deduplication, avoiding attribution of one search result to
every search variant.

Initial local direct-only probe: 60 HTTP attempts, about 7.6 MB, zero provider
calls. It retrieved 30/33 listing pages and found upcoming candidates from 26/33
entries, including previously deferred HAU, SAVVY, silent green, Tempelhofer Feld,
Renaissance-Theater and ausland. The Clubmap contributed 32 candidates through
its public API. Lake Studios and Freilandlabor had raw dated records but none
inside this week's permitted window; Improfabrik and Venture Café supplied no
extractable dated event evidence. Rausgegangen returned 403; Stadtmuseum and
Volksbühne had unavailable/denied robots policy. These are extraction observations,
not verified source coverage or eligible newsletter counts.

The two-source general pilot, manifest checks, freshness, public €0–5 normal
admission and venue/access requirements remain enforced. Broader discovered events
can enter only the independent Community feed after production verification.
No canonical production data, feature flag, schedule or merge is changed.

## GitHub integration evidence and canonical-site repair

Read-only run [40866973179](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40866973179)
on `b39dd9d` completed successfully: 262 normalized input occurrences, 30/33
listing sources received, 26 with discovered occurrences, 241 detail-URL candidates,
six exact matched occurrences across two sources, zero eligible newsletter rows.
It used 55 discovery HTTP attempts plus 18 pilot/detail HTTP attempts (73 total),
six free Fetch URLs and zero Search calls, in 78.689 seconds of pipeline time.
One provider URL returned a target HTTP error; five returned valid documents.
A valid provider document did not imply an occurrence match. Five pilot publication
rows passed exact verification (three Bühnen, two ufaFabrik), across two dates per
source. Unknown inventory remained unknown. Browser and overlay replay passed.
Both CI runs on that commit passed all 293 tests.

This run made the last two robots failures actionable: both old URLs returned
HTTP 301 to different official domains. Direct checks confirmed Stadtmuseum's
new `https://www.berlin.museum/programm` and Volksbühne's new
`https://www.volksbuehne-berlin.de/`, using each destination's own robots policy.
The catalog now uses these canonical URLs. The client's prohibition on arbitrary
cross-host redirects remains unchanged.

Production discovery adapters read each site's actual programme cards. Museum
rows now retain their event-specific link and named museum; Volksbühne rows retain
exact title, room and local datetime, rather than mistaking a workshop subtitle
for a venue or interpreting the URL's UTC hour as local time. Prices remain
candidate evidence until destination verification; child/concession prose cannot
establish a regular public price. Replay of the captured full pages yields eight
museum and 32 Volksbühne occurrences in the window, all with specific links and
venues. These stricter counts replace generic duplicate/ambiguous candidates.
Sanitized real-card fixtures and regression tests preserve these findings.

295 Python tests, Node checks and offline Chromium search/categories/Community/
responsive/ICS checks pass. A fresh read-only candidate must be generated from the
final commit before promotion through the existing SHA/digest/freshness gates.
The first run's empty newsletter remains a verification limitation, not a claim
that the additional fetched sources contain no affordable public events.
