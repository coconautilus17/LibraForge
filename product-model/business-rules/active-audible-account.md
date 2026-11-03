---
appliesTo:
- type: entity
  id: audible-account
references:
- kind: code
  role: implementation
  target: app/main.py#auth_login_complete
- kind: code
  role: implementation
  target: app/main.py#auth_account_activate
- kind: code
  role: implementation
  target: app/main.py#auth_disconnect
---

# The tools share one active Audible account

Connecting or activating a saved account selects it for the shared tools. Renaming preserves the connection; disconnecting the active account removes that selection rather than automatically activating another saved account.
