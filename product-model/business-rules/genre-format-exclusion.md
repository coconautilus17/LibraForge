---
appliesTo:
- type: capability
  id: compile-enrichment
- type: capability
  id: apply-enrichment
- type: capability
  id: apply-whole-library-results
- type: capability
  id: preview-genre-collections
references:
- kind: code
  role: implementation
  target: app/genre_taxonomy.py
- kind: code
  role: implementation
  target: app/main.py#enrichment_apply
- kind: code
  role: implementation
  target: app/genre_collections.py#genre_counts
- kind: code
  role: implementation
  target: app/store_genres.py
---

# Enrichment genres exclude format labels

Enrichment suggestions and writes drop scrap labels: format words such as Audiobook, store umbrella shelves, keyword lists and pieces of a genre a source cut apart. Every other source label is kept, as a subgenre under the source’s own spelling when the controlled genre list does not name it. Compound store names, and store names glued to more words, are split into library genres; store umbrella shelves are not collection genres. A foreign Audible store category counts as its English category and that category’s top level, using names learned from Audible and refreshed monthly; a foreign category with no English counterpart is left out.
