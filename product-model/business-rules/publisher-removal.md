---
appliesTo:
- type: entity
  id: publisher
  effect: removes
references:
- kind: code
  role: implementation
  target: app/static/pattern-settings.js
permits:
- actors:
  - library-owner
  when:
  - fact: Origin
    is: custom
- actors:
  - library-owner
  when:
  - fact: Origin
    is: learned
---

# The library owner removes only custom or learned publisher entries

The library owner removes custom entries and learned publishers. Shipped entries can be disabled and re-enabled.
