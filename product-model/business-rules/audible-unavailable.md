---
appliesTo:
- type: entity
  id: metadata-match
  facts:
  - Edit mode
  - Review reasons
  - Write outcome
---

# A book Audible could not answer is never matched as if Audible had no listing

When Audible keeps refusing or failing a book's lookups after LibraForge has waited for it, the book gets no match and nothing is written for it in that run. The later steps (the book's series on Audible, AudioSilo and Goodreads) are not tried for that book. The book is marked Audible unavailable, separate from a genuine no-match, and the next run looks it up again. A confident match from a step before Audible (Audiobook Guild, GraphicAudio or SoundBooth) still counts.
