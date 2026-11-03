---
singleton: true
domain: author-names
references:
- kind: code
  role: implementation
  target: app/install_state.py
- kind: code
  role: implementation
  target: app/author_names.py
---

# Author name settings

The installation’s author-name scheme and upgrade notice.

## Information kept

- **Universal scheme** — Whether output author initials are unified.
- **Origin** — Fresh installation or upgrade.
- **Notice pending** — Whether the upgrade notice remains to be acknowledged.
