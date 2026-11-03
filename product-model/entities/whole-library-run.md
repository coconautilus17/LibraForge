---
domain: enrichment-forge
references:
- kind: code
  role: implementation
  target: app/enrichment_batch.py#run_batch
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_status
---

# Whole-library run

The resumable Enrichment Forge compilation of every series and standalone book.

## Information kept

- **Subjects** — Ordered series and standalone books.
- **Progress** — Current subject and counts by result state.
- **Timing** — Start and most recent change.
- **Results** — Saved compiled results and apply outcomes.

## States

### Idle

No compilation is active.

### Running

Compiling subjects one at a time.

### Stopping

Stop requested; the current subject can finish.

### Stopped

Paused or interrupted and resumable.

### Done

All subjects due for compilation have been attempted.
