---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner refreshes the audio profiles of cached candidates.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product refreshes audiobook audio properties and presents whether stream-copy is recommended.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Audio
  contexts:
    web:
      place: web::m4b-tool
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#refresh_cached_multipart_audio_profiles
- kind: code
  role: implementation
  target: app/conversion_discovery.py#summarize_audio_probes
---

# Refresh stream-copy advice

## Trigger

Cached candidates need current audio properties.

## Outcome

The Product refreshes audiobook audio properties and presents whether stream-copy is recommended.

## Edge cases

- Unknown or incomplete stream properties do not receive a positive no-conversion recommendation.
