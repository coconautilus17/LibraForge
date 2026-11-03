---
kind: primary
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner confirms Apply for the reviewed source, destination and naming scheme.
  entities: []
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
- kind: product
  text: The Product changes the audiobook and ebook locations for eligible moves, marks each planned move Moved
    and completes the run.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Path
    - Companions
  - entity: ebook
    effect: changes
    facts:
    - Path
  - entity: planned-move
    effect: changes
    facts:
    - Result
    from: Planned
    to: Moved
  - entity: run
    effect: creates
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
    to: Completed
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#execute_planned_move
- kind: code
  role: implementation
  target: app/static/organizer.js#showOrgApplyConfirm
---

# Relocate a book and companions

## Trigger

The owner elects to apply an organizer run.

## Outcome

The Product changes the audiobook and ebook locations for eligible moves, marks each planned move Moved and completes the run.

## Edge cases

- Known loose-file companions follow their book and metadata companion names are normalized when appropriate.
- When a folder holds only that one book, every cover, notes, cue and playlist file in it moves with the book and keeps its own name; a folder holding several books keeps such unnamed extras.
- A shared companion that a sibling book from the same folder already took is skipped, and the book still counts as moved.
- The option to include already organized-looking book folders preserves their current folder names.
- Optional source empty-directory removal follows successful moves.
