---
singleton: true
references:
- kind: code
  role: implementation
  target: app/main.py#abs_save_config
- kind: code
  role: implementation
  target: app/main.py#abs_status
domain: audiobookshelf
---

# Audiobookshelf settings

The shared connection used for library lookup and metadata writes.

## Information kept

- **URL** — Audiobookshelf service address.
- **Key configured** — Whether an API key is available.
- **Key source** — Saved configuration or deployment environment.
- **Reachable** — Result of the latest connection check.
- **API key** — Credential supplied for the library connection.
