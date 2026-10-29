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
