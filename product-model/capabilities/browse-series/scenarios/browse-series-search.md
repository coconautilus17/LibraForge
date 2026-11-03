---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner searches the library’s series and standalone books.
  entities:
  - entity: series
    effect: reads
    facts:
    - Name
    - Authors
    - Books
    - Shared metadata
  contexts:
    web:
      place: web::enrichment-forge
- kind: product
  text: The Product presents series names, author groups and book counts for compilation.
  entities:
  - entity: series
    effect: reads
    facts:
    - Name
    - Authors
    - Books
    - Shared metadata
  contexts:
    web:
      place: web::enrichment-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/enrichment.py#list_series_summary
- kind: code
  role: implementation
  target: app/enrichment.py#split_group_by_author
- kind: code
  role: implementation
  target: app/main.py#enrichment_series
---

# Find an indexed series

## Trigger

Audiobookshelf is connected.

## Outcome

The Product presents series names, author groups and book counts for compilation.

## Edge cases

- Same-named series with disjoint author groups remain separate; connected coauthor groups stay together.
