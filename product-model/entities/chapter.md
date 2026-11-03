---
domain: chapter-forge
references:
- kind: code
  role: implementation
  target: app/main.py#save_chaptering
- kind: code
  role: implementation
  target: app/chaptering.py
- kind: code
  role: implementation
  target: app/static/chapter-forge.js
---

# Chapter

A named interval in a book that can be inspected, added, edited or removed.

## Information kept

- **Title** — Chapter label.
- **Timing** — Start and end in the audio.
- **Evidence** — Detection source, confidence, transcript or silence evidence and review reasons.
- **Manual** — Whether the entry has been manually saved.
