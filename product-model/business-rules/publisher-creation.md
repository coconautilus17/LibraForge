---
appliesTo:
- type: entity
  id: publisher
  effect: creates
references:
- kind: code
  role: implementation
  target: app/static/pattern-settings.js
- kind: code
  role: implementation
  target: app/publisher_policy.py
permits:
- actors:
  - library-owner
- unattended: true
---

# The library owner adds custom publishers and matching learns new publishers

The library owner can add a custom entry. Matching can also retain a newly learned publisher for review.
