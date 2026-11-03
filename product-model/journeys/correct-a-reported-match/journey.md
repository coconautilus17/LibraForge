---
actors:
- library-owner
references:
- kind: code
  role: implementation
  target: app/static/app.js#renderManualReviewList
- kind: code
  role: implementation
  target: app/static/app.js#loadManualTarget
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_result
---

# Correct a reported match

## Goal

Fix a doubtful Match Report result by hand in Manual Review.

## Success criterion

The selected book has the owner’s reviewed metadata.
