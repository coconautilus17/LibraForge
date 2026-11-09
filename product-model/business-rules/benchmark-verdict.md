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
  target: dev/benchmark/audit_check.py#field_problems
- kind: code
  role: implementation
  target: dev/benchmark/bench_data.py#result
---

# A verdict follows from what the tool left on the book

Which book a tool chose, and whether it wrote, held or left it, decides the verdict's kind: the right book, another
recording of it, the wrong book, a series-only write into the right or wrong series, held with a right or wrong
pick, or nothing written. A tool that chose any of the confirmed edition's IDs chose the right book; any other choice,
a write that carries no ID included, is judged by hand. What the tool then left on the book is rebuilt by each tool's own way of writing and checked field
by field against the right answer, by the same rules for every tool; a right book with any field wrong or missing
is partly right. Two tools that leave the same book with the same listing and the same fields get the same verdict.
The final verdict is the only verdict the page shows.

## Rationale

Which book a file is often needs judgment no rule captures (recordings, omnibuses, retitled editions); whether a
field is right needs the same check on every book.
