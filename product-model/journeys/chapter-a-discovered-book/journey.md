---
actors:
- library-owner
references:
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#findCandidate
- kind: code
  role: implementation
  target: app/main.py#run_audible_chapters_backend
---

# Chapter a discovered book

## Goal

Take a single-file book found by Chapter Forge’s candidate search straight into chapter detection.

## Success criterion

Detected chapters are saved for the chosen book.
