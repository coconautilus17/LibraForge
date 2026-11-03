---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#update_author_names_policy
- kind: code
  role: implementation
  target: app/install_state.py#init_install_state
- kind: code
  role: implementation
  target: app/author_names.py#output_author_credit
domain: author-names
---

# Change author name settings

Choose whether later metadata writes use the universal initials scheme. New installations default on; upgrades retain the previous naming behavior until enabled.
