---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#auth_disconnect
- kind: code
  role: implementation
  target: app/main.py#auth_account_remove
- kind: code
  role: implementation
  target: app/main.py#_deregister_or_502
domain: accounts
---

# Disconnect Audible account

Deregister a saved account with Audible and remove its local connection; the active account uses Disconnect and inactive accounts use removal.
