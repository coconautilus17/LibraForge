---
domain: benchmark
references:
- kind: code
  role: implementation
  target: dev/benchmark/audit.py
- kind: code
  role: implementation
  target: dev/benchmark/audit_check.py
---

# Audit verdict

The judgment of every tool's result on one benchmark book.

## Information kept

- **Hand verdict** — Per tool, one code judged by hand: which book it chose (the right one, another recording of it, the wrong one), and whether it wrote, held or left it.
- **Note** — Why, in words: the book's identity and recording, and what each tool did.
- **Field problems** — Per tool, each field the book ends up with wrong or missing.
- **Final verdict** — Per tool, the hand verdict's identity with the field checks' outcome; what the page shows.
