---
appliesTo:
- type: capability
  id: preview-genre-collections
- type: capability
  id: create-genre-collections
- type: capability
  id: refresh-genre-collections
references:
- kind: code
  role: implementation
  target: app/genre_collections.py#plan_collections
- kind: code
  role: implementation
  target: app/genre_collections.py#split_parts
---

# A genre collection holds at most 600 books

A genre with more than 600 books becomes numbered parts of even size, cut between authors so a series stays in one part unless one author alone passes the limit. LitRPG and Cultivation books are left out of the Fantasy and Sci-Fi collections, since they have collections of their own. Progression Fantasy is never a collection.

## Rationale

Audiobookshelf has no paging inside a collection: opening one loads every book in full, and its Collections page loads the collections on screen with all their books.
