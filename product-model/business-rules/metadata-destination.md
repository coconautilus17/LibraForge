---
appliesTo:
- type: capability
  id: apply-metadata
- type: capability
  id: apply-metadata-match
- type: capability
  id: edit-audiobook
- type: capability
  id: apply-ebook-metadata
references:
- kind: code
  role: implementation
  target: app/abs_client.py#sync_book_metadata
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_ebook_target
---

# Known library items receive direct metadata synchronization

A corresponding known Audiobookshelf item receives the selected metadata through its library record. An audiobook not yet known, or without a configured connection, receives local bootstrap metadata. Ebooks retain local book metadata when no matching library item is available.
