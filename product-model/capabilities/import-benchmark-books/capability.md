---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/overlap.py#find_overlap
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#import_dump
- kind: code
  role: implementation
  target: dev/benchmark/dedupe.py#dedupe
domain: benchmark
---

# Import benchmark books

Add another library's books from an ffprobe tag dump: leave out the ones this library already has, add the rest with their file name as the right answer, and keep one book of each search.
