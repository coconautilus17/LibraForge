---
appliesTo:
- type: entity
  id: audiobook
  facts:
  - Audio
references:
- kind: code
  role: implementation
  target: app/conversion_discovery.py#summarize_audio_probes
- kind: code
  role: implementation
  target: app/tests/test_conversion_discovery.py
---

# Stream-copy advice requires complete compatible AAC properties

No conversion is recommended only when every source has readable AAC codec, sample rate and channel information, and sample rate and channel layout agree. Different bitrates alone are acceptable.
