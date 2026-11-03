---
scope: Core library preparation in the web tools and maintained matching, organization and selected maintenance
  commands, at 97779be92077839bc7b7fa3fd48e8cbf049634ab.
method: Static tracing of tracked source, UI, documentation and selected regression tests at the pinned
  upstream commit.
covered:
- description: Web tool handlers, request models and shared report/account/settings orchestration, excluding
    the subareas listed below.
  paths:
  - app/main.py
- description: Web interactions for matching, local review, conversion, chapters, organization, enrichment,
    purchasing and settings.
  paths:
  - app/static/
- description: Maintained metadata matching, grouping, field writes and suspicion review.
  paths:
  - app/fixer/
  - app/manual_review.py
  - app/manual_candidates.py
  - scripts/audible-metadata-fixer-v5.py
  - scripts/review-libraforge-report.py
- description: Maintained destination planning and movement.
  paths:
  - scripts/organize-audiobooks-by-metadata-v3_13.py
- description: Discovery and local book indexing used by the preparation tools.
  paths:
  - app/library_index.py
  - app/conversion_discovery.py
  - app/conversion_cache.py
  - app/folder_scan_cache.py
  - app/epub_metadata.py
  - app/m4b_naming.py
  - app/sidecar_ownership.py
- description: Enrichment compilation, batch review, voting, source evidence and genre collection synchronization.
  paths:
  - app/enrichment.py
  - app/enrichment_batch.py
  - app/enrichment_sources.py
  - app/genre_voting.py
  - app/genre_taxonomy.py
  - app/genre_collections.py
  - app/explicit_evidence.py
  - app/goodreads_shelves.py
  - app/source_matching.py
  - app/store_genres.py
- description: Chapter detection, persistence and remote/local inference orchestration.
  paths:
  - app/chaptering.py
  - app/chaptering_runner.py
- description: Provider metadata synchronization and documented legacy metadata migration, excluding periodic
    reconciliation.
  paths:
  - app/abs_client.py
  - scripts/migrate-legacy-metadata-json.py
- description: Persistent pattern policies, install defaults and local author-normalization command.
  paths:
  - app/author_names.py
  - app/title_noise_policy.py
  - app/publisher_policy.py
  - app/install_state.py
  - app/settings_paths.py
  - config/
  - scripts/normalize-author-names.py
exclusions:
- description: Build, deployment and dependency packaging rather than library preparation behavior.
  paths:
  - Dockerfile
  - Dockerfile.unified
  - Makefile
  - docker-compose.yml
  - docker-compose.dist.yml
  - .github/
- description: Developer benchmark and comparison tooling kept out of the published image.
  paths:
  - dev/
- description: Appearance preferences, styling, icons and demo media; appearance choices do not alter
    product workflow.
  paths:
  - app/static/ui-preferences.js
  - app/icons/
  - app/static/style.css
  - app/static/enrichment-forge.css
  - app/example_books/
- description: Test fixtures and regression infrastructure, consulted as supporting evidence rather than
    separate product resources.
  paths:
  - app/tests/
- description: Internal tracing and phase-label implementation, apart from the exposed tracing preference
    and progress behavior.
  paths:
  - app/debug_trace.py
  - app/progress_phases.py
unmapped:
- description: One-time series-number suffix backfill; historical migration beyond the core preparation
    workflow.
  paths:
  - scripts/fix-series-book-number-suffix.py
- description: Audiobookshelf author-record adoption and deletion in author normalization; specialist
    remote maintenance beyond the mapped local migration.
  paths:
  - scripts/normalize-author-names.py
- description: Standalone SoundOfSilence command options; Chapter Forge integration is covered, independent
    utility operation is peripheral.
  paths:
  - tools/ABS-scripts/
- description: Pocket FM show lookup; specialty lookup outside the main supported provider workflow.
  paths:
  - app/pocketfm.py
  - app/main.py
- description: Periodic bootstrap-file reconciliation; deferred integration subpath.
  paths:
  - app/abs_client.py
  - app/main.py
- description: Disconnected enrichment-file application; deferred integration subpath.
  paths:
  - app/main.py
  - app/enrichment.py
- description: Standalone organizer override files and explicit target-merging mode; specialist CLI extensions
    beyond default organization and exposed web options.
  paths:
  - scripts/organize-audiobooks-by-metadata-v3_13.py
limitations: []
---

# Coverage


