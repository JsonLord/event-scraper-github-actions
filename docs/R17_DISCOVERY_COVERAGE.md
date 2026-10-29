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
