---
appliesTo:
- type: capability
  id: preview-metadata
- type: capability
  id: apply-metadata
references:
- kind: code
  role: implementation
  target: app/fixer/scoring.py#with_preferred_series
- kind: code
  role: implementation
  target: app/fixer/scoring.py#get_primary_series
- kind: code
  role: implementation
  target: app/fixer/parsing.py#semicolon_layout_series
- kind: code
  role: implementation
  target: app/fixer/clues.py#apply_structured_path_override
---

# A book in several series is written under the series its own file names

When a matched listing names several series, the book is written under the first of these that names one series: the series the file's series clue names exactly; the series its folder names (an `Author/Series/Book N` folder, or an `Author; Series; Book NN; Title` folder whose first part is the book's author); the only series the book's number fits, when that number came from its path; the series tag's name with a trailing number split off ("Discworld: Ankh-Morpork City Watch, Book #3"), when the listing's number fits it; the only series the book's number fits; the series its title names, the most specific first. Of several series that read alike, the one the book's number fits wins, then the one written exactly as the file writes it. Otherwise a numbered series comes before an unnumbered one, and then the series names decide. A file gets the same series whatever order the listing names them in. The folder's series also names the series search when no confident full match is found, and never changes a listing's score.

## Rationale

Audible returns a listing's series in no fixed order, and many books sit in a sub-series and its umbrella series at once (Discworld and its City Watch books, The Malcontents and War Machine). The library's own folders and tags say which one the owner files the book under, so a rerun never moves a book to another series.
