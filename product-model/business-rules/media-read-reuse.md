---
appliesTo:
- type: entity
  id: audiobook
  facts:
  - Audio
  - Original metadata
references:
- kind: code
  role: implementation
  target: app/media_probe.py#inspect
- kind: code
  role: implementation
  target: app/media_facts_store.py#MediaFactsStore
---

# What was read from an audio file is reused only while the file is unchanged

What LibraForge read from an audio file is reused across tools, runs and restarts only while the file's path, size and modification time are unchanged. A value that could not be read is unknown, never zero, and a failed read is never reused.
