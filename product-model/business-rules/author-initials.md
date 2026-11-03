---
appliesTo:
- type: entity
  id: author-name-settings
references:
- kind: code
  role: implementation
  target: app/author_names.py#format_person_name
- kind: code
  role: implementation
  target: app/install_state.py#init_install_state
---

# The universal scheme changes author spelling without renaming existing paths

When enabled, later metadata writes place a dot after each recognized initial, join consecutive initials without spaces, and separate the rest of the name with one space. Enabled exceptions and digit-containing handles retain their recognized spelling. Changing the preference does not itself rename existing files or folders.
