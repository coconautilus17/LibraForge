---
references:
- kind: code
  role: implementation
  target: app/main.py#write_final_report
- kind: code
  role: implementation
  target: app/main.py#get_latest_run_log
---

# Run log

The output and report for a run that the library owner can inspect and download.

## Information kept

- **Tool** — The originating tool.
- **Timing** — When the run started and finished.
- **Outcome** — Completion state, counts and per-book results.
- **Output** — Recorded progress, warnings and error details.
