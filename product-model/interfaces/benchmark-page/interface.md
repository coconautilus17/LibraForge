---
type: web
actors:
- page-visitor
entryPoints:
- web: https://coconautilus17.github.io/LibraForge/
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
- kind: code
  role: implementation
  target: dev/benchmark/publish_pages.sh
---

# Benchmark page

The public comparison page, a static page anyone can open: the results of every tool, each book's details and
verdicts, and the downloads. Requests and reports open an issue on the project's GitHub.
