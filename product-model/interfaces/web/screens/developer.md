---
entities:
- entity: developer-preferences
  shows:
  - Debug tracing
  - Trace destination
  collects:
  - Debug tracing
  - Trace destination
entryPoints:
- web: /settings#developer
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Developer

Switch debug tracing for later runs and choose where the trace is written.
