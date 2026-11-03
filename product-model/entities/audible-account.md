---
domain: accounts
references:
- kind: code
  role: implementation
  target: app/main.py#auth_login_complete
- kind: code
  role: implementation
  target: app/main.py#auth_account_activate
---

# Audible account

A named saved Audible account used by the tools.

## Information kept

- **Name** — Owner-chosen label and Audible profile name.
- **Marketplace** — Audible marketplace.
- **Connection** — Saved connection usable for catalog and purchase access.

## States

### Inactive

Saved but not currently selected.

### Active

Selected for the shared tools.
