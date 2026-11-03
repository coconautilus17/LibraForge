---
domain: folder-forge
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#execute_planned_move
---

# Planned move

A proposed relocation of one book and its companions.

## Information kept

- **Source** — Current book location and media type.
- **Destination** — Proposed destination folder and optional filename.
- **Metadata** — Identity and metadata source used for naming.
- **Review reasons** — Reasons to review or skip the move.
- **Companions** — Associated files included in relocation.
- **Result** — Success or failure detail.

## States

### Planned

A relocation is proposed.

### Skipped

No relocation is selected for this item.

### Moved

The planned relocation completed.

### Failed

Relocation encountered a filesystem error.
