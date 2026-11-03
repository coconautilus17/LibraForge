---
domain: publishers
references:
- kind: code
  role: implementation
  target: app/publisher_policy.py
---

# Publisher

A recognized publisher or imprint used to clean metadata clues.

## Information kept

- **Name** — Canonical publisher name and aliases.
- **Special provider** — Optional dedicated GraphicAudio or Soundbooth Theater lookup.
- **Origin** — Shipped, custom or learned during a run.
- **Enabled** — Whether the publisher participates in cleanup and detection.
