---
appliesTo:
- type: capability
  id: preview-metadata
- type: capability
  id: apply-metadata
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#search_item
- kind: code
  role: implementation
  target: docs/features.md
---

# A book is looked up in a fixed order until one step finds a confident full match

Audiobook Guild first, for a book by an author the store sells; then GraphicAudio or SoundBooth Theater, when the book names that publisher; then the book's own ASIN; then Audible's search, by title and author and then by keywords; then the other books of the book's own series on Audible; then AudioSilo's community database; and last Goodreads, when the run turns its fallback on. A later step runs only while no earlier one has found a confident full match, and whatever is found passes the same review gates before anything is written.

## Rationale

Audible's search leaves out books that can't be bought where the search comes from, while looking a book up by its ASIN still returns it. The series and AudioSilo steps find such a book's ASIN another way, so a book the search hides is still matched.
