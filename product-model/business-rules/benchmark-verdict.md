---
appliesTo:
- type: entity
  id: audit-verdict
references:
- kind: code
  role: implementation
  target: dev/benchmark/audit.py
- kind: code
  role: implementation
  target: dev/benchmark/audit_check.py#checks
- kind: code
  role: implementation
  target: dev/benchmark/bench_data.py#result
---

# A verdict takes the book from the hand audit and the fields from the checks

Which book a tool chose, and whether it wrote, held or left it, is judged by hand: C the right book, E another
recording of it, W the wrong book, S or s a series-only write into the right or wrong series, H or h held with a
right or wrong pick, N nothing written. What the tool then left on the book is rebuilt by each tool's own way of
writing and checked field by field against the right answer and the file, by the same rules for every tool; a right
book with any field wrong or missing is P. The final verdict is the only verdict the page shows.

## Rationale

Which book a file is often needs judgment no rule captures (recordings, omnibuses, retitled editions); whether a
field is right needs the same check on every book.
