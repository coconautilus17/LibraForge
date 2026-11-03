---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#run_chaptering_worker
- kind: code
  role: implementation
  target: app/main.py#run_audible_chapters_backend
- kind: code
  role: implementation
  target: app/chaptering.py
domain: chapter-forge
---

# Detect chapters

Produce chapter candidates using Audible’s verified chapter list, Hybrid detection, or Full transcription. Hybrid scans silences with the local speech-recognition runtime and transcribes focused windows on a configured ASR server; Full transcription runs locally. Both need the optional runtime; Audible chapters does not.
