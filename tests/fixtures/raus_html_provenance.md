# Raus HTML pipeline fixture provenance

Retrieved from the existing sanitized artifact `scrape-rausgegangen_de` of
[main run 40225678325](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40225678325).
Its raw extraction timestamp is 25 October 2026, 19:22:49, as recorded by main.

- `raus_main_extracted_rows_2026-10-25.json`: eight unmodified extracted records
  (first two rows on each of October 25/26/31 and November 1). Contains the original
  raw-file SHA-256 and source URL. These are listing extraction results, not
  verified admission, inventory or current events. They are never used as fresh
  live discovery inputs or committed into production data.
- `raus_main_saved_challenge_2026-10-25.html`: main's actual saved response,
  sanitized by removing scripts/styles/links and all attributes. Text and DOM
  nesting remain. It is a challenge/failure fixture, not a successful listing.

`test_raus_html.py` deliberately reconstructs simple card relationships from the
captured records, and constructs synthetic schema.org detail nodes to test exact
identity, city, offers, statuses and failure cases. The tests say so explicitly.
No reconstructed markup is claimed to be the original provider/source HTML.
Clock-frozen October 25 replay cannot be presented as fresh October 31 evidence.
Other source fixtures keep their original provenance notes and are unchanged.
