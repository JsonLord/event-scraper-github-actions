# Public official programme cards

Captured by direct, robots-checked HTTP on 29 October 2026, approximately 11:43 UTC:

- `berlin_museum_listing_2026-10-29.html`: first three event teasers from
  https://www.berlin.museum/programm
- `volksbuehne_listing_2026-10-29.html`: first three activity rows from
  https://www.volksbuehne-berlin.de/

The old official sites' `/robots.txt` responses supplied HTTP 301 Locations to
these new official hosts. Each new host's own robots policy was checked before
fetching its listing. No redirect restriction, access control or challenge was
bypassed. All scripts, image/media payloads and unnecessary attributes were
removed; class names, literal text, public hrefs and datetime attributes survive.
No event text, date, price or venue was invented.

Museum copy explicitly limits free entry to under-18s/concessions; the adapter
must not turn that prose into normal public admission. Volksbühne's 15:00 local
performance has `1400` in the URL; the displayed datetime, not the slug, determines
the local start. The third row's ticket warning must not bleed into the first row.
These are discovery fixtures; they do not independently qualify a newsletter item.

Additional targeted detail fixtures, captured by robots-checked direct HTTP on
29 October 2026:

- `volksbuehne_raw_voice_lab_detail_2026-10-30.html`: JSON-LD and literal activity
  rows from https://www.volksbuehne-berlin.de/produktionen/raw-voice-lab/20261030-1200/
- `museum_niewiedervereinigung_detail_2026-10-30.html`: JSON-LD from
  https://www.berlin.museum/veranstaltungen/niewiedervereinigung-paula-fuerstenberg

The museum listing's `Ausverkauft:` span is a status badge, not part of its
structured event name. Tests retain that negative evidence while matching the
actual title. No event facts were fabricated.

Berlin Bühnen follow-up fixtures, captured on 29 October 2026 using bounded,
robots-checked direct HTTP:

- `berlin_buehnen_listing_2026-11-01_captured_2026-10-29.html`: first three cards
  from https://www.berlin-buehnen.de/de/spielplan/?date=2026-11-01
- `berlin_buehnen_listing_2026-11-02_captured_2026-10-29.html`: first three cards
  from https://www.berlin-buehnen.de/de/spielplan/?date=2026-11-02

These are literal event-card fragments, not reconstructed event data. The outer
`hylo-router-link` elements' public hrefs, datetime markers, h3 titles, desktop
venue headings, subtitles and responsive duplicates are retained. Image/icon
payloads, scripts and unnecessary attributes were removed. Ticket-link query
strings were removed; those links are not used as event destinations. No event
title, performance, venue or price was invented. Mutation-based rejection tests
identify their changed fields explicitly and do not call those mutations live
evidence. Both full listing responses contained pagination, so these fragments
do not represent complete day coverage.
