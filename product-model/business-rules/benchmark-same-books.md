---
appliesTo:
- type: capability
  id: run-benchmark-tool
- type: capability
  id: build-mock-files
references:
- kind: code
  role: implementation
  target: dev/benchmark/bo_mock.py
- kind: code
  role: implementation
  target: dev/benchmark/lf_bench.py
---

# Every tool is given the same books in their original state

Each tool runs over the same benchmark books, with their original tags at their real folder paths (and their real
runtime for a tool that reads it), in a throwaway instance that holds nothing else, set up the way its own
documentation suggests. No tool is given a book's right answer.

## Rationale

The comparison means something only when every tool starts from the same files a new user would hand it.
