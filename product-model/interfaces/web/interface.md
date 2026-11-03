---
type: web
actors:
- library-owner
entryPoints:
- web: /
references:
- kind: code
  role: implementation
  target: app/main.py#start_here_page
- kind: code
  role: implementation
  target: app/static/start-here.html
---

# Web

The shared browser workspace for preparing local books, running the tools and configuring saved provider connections. Audible sign-in connects an external account used by these tools.
