---
appliesTo:
- type: entity
  id: audiobook
  facts:
  - Series
references:
- kind: code
  role: implementation
  target: app/abs_client.py#merge_series_entries
- kind: code
  role: implementation
  target: app/abs_client.py#sync_book_metadata
---

# Metadata synchronization preserves other series memberships

Updating one named series merges it with the current Audiobookshelf series list instead of dropping distinct alternative series memberships.
