---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#build_m4b_command
- kind: code
  role: implementation
  target: app/main.py#resolve_m4b_input_files
- kind: code
  role: implementation
  target: app/main.py#run_m4b_worker
domain: m4b-tool
---

# Convert audiobook

Convert or merge selected source audio into one M4B with chosen audio settings, metadata and chapter handling. Starting conversion performs the work.
