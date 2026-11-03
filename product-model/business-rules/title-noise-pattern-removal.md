---
appliesTo:
- type: entity
  id: title-noise-pattern
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
---

# The library owner removes only custom title noise pattern entries

The library owner removes custom entries. Shipped entries can be disabled and re-enabled.
