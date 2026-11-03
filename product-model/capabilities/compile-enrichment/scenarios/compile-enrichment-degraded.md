---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner compiles the selected subject.
  entities: []
  contexts:
    web:
      place: web::enrichment-forge
- kind: product
  text: The Product creates a Compiled enrichment result from available sources and identifies the degraded
    sources and their found, failed or skipped counts.
  entities:
  - entity: enrichment-result
    effect: creates
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
    to: Compiled
  contexts:
    web:
      place: web::enrichment-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#_compile_unit
- kind: code
  role: implementation
  target: app/enrichment.py#compile_series_enrichment
- kind: code
  role: implementation
  target: app/genre_voting.py
---

# Retain a partially answered proposal

## Trigger

A source is paused, rate-limited or fails.

## Outcome

The Product creates a Compiled enrichment result from available sources and identifies the degraded sources and their found, failed or skipped counts.
