---
id: libraforge
summary: Prepare a personal audiobook library through metadata matching, review, conversion, chapter curation,
  organization, enrichment and purchased-library downloads.
category: media-management
tags:
- audiobooks
- metadata
- self-hosted
- library-organization
authors:
- name: coconautilus17
  url: https://github.com/coconautilus17
license: AGPL-3.0-or-later
languages:
- en
limitations:
- Local preparation works on media made available in the mounted library.
- Library Downloader obtains purchases from a connected Audible account.
- Enrichment series discovery uses books already indexed by Audiobookshelf.
- Hybrid and Full transcription chapter detection require the optional speech-recognition runtime; Audible
  chapter lookup works without it.
references:
- kind: doc
  role: intent
  target: README.md
- kind: doc
  role: context
  target: docs/features.md
- kind: doc
  role: context
  target: LICENSE
---

# LibraForge

LibraForge is a self-hosted toolkit for preparing an audiobook library. A library owner matches and reviews metadata, merges audio into M4B, curates chapters, previews and applies file organization, enriches library genres and downloads Audible purchases. The web tools share local media, saved connections and reports; maintained command-line tools support matching, organization and selected migrations.

## Intent

The project describes its purpose as “Self-hosted Audible metadata matching, M4B conversion, Audiobookshelf-style library organisation, series-wide metadata enrichment, and direct Audible downloading”. Its workflow favors reviewing proposed metadata and moves before applying them, with clear per-book results and manual correction when an automatic match is uncertain.
