---
singleton: true
references:
- kind: code
  role: implementation
  target: app/main.py#save_abs_tract_settings
---

# Goodreads/Kindle settings

The abs-tract connection and Kindle marketplace used for Kindle cover lookups. Goodreads itself is read directly and needs neither.

## Information kept

- **URL** — Configured service address.
- **Kindle region** — Marketplace for cover lookup.
