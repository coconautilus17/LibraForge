---
references:
- kind: code
  role: implementation
  target: app/main.py#RunState
- kind: code
  role: implementation
  target: app/main.py#get_run
---

# Run

One requested metadata, conversion, chapter, organizer or download operation.

## Information kept

- **Tool** — The tool and operation requested.
- **Target** — Source and destination scope.
- **Options** — Preview or apply and the chosen processing options.
- **Progress** — Phase, current book, counts and progress.
- **Results** — Per-book results, review reasons and failures.
- **Timing** — Start and finish times.

## States

### Queued

Accepted and waiting for work.

### Running

Processing the requested scope.

### Completed

Finished successfully.

### Completed with errors

A download batch finished with individual failures.

### Failed

Stopped with an error.

### Cancelled

Cancellation has been requested or processing stopped.
