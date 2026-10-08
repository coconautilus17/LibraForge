"""Folder Forge report: which review reasons raise an alert, and the paths a card shows.

The pure helpers in organizer.js run in QuickJS (skipped when the optional `quickjs`
package is missing); the markup assertions are plain text checks.
"""
import json
import unittest
from pathlib import Path

try:
    import quickjs
except ImportError:  # pragma: no cover
    quickjs = None

ROOT = Path(__file__).parents[2]
JS = (ROOT / "app" / "static" / "organizer.js").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts" / "organize-audiobooks-by-metadata-v3_13.py").read_text(encoding="utf-8")

START = "// Reasons that only say how a value was derived"
END = "function renderRisks("


def helpers():
    block = JS[JS.index(START):JS.index(END)]
    context = quickjs.Context()
    context.eval(block)
    return context


def good_item(**fields):
    base = {"author": "A Author", "title": "A Title", "source": "/in/a.m4b", "target": "/lib/a.m4b",
            "structure": "new", "review_reasons": []}
    base.update(fields)
    return base


@unittest.skipIf(quickjs is None, "quickjs not installed")
class ReviewTierTests(unittest.TestCase):
    def call(self, fn, item):
        return json.loads(helpers().eval(f"JSON.stringify({fn}({json.dumps(item)}))"))

    def test_a_book_with_only_a_derivation_note_is_not_a_review_item(self):
        item = good_item(review_reasons=["title matches series name; using sequence only"])
        self.assertFalse(self.call("isReviewMove", item))
        self.assertEqual(self.call("reviewReasonsOf", item), [])
        self.assertEqual(self.call("noteReasonsOf", item), ["title matches series name; using sequence only"])

    def test_a_real_problem_is_still_an_alert(self):
        item = good_item(review_reasons=["title looks cut off at the end"])
        self.assertTrue(self.call("isReviewMove", item))

    def test_mixed_reasons_split_into_alerts_and_notes(self):
        item = good_item(review_reasons=["title inferred from path", "book number differs between metadata and path"])
        self.assertEqual(self.call("reviewReasonsOf", item), ["book number differs between metadata and path"])
        self.assertEqual(self.call("noteReasonsOf", item), ["title inferred from path"])
        self.assertTrue(self.call("isReviewMove", item))

    def test_unknown_author_is_always_a_review_item(self):
        self.assertTrue(self.call("isReviewMove", good_item(author="Unknown Author")))

    def test_blocked_items_are_recognized_by_their_structure(self):
        self.assertTrue(self.call("isBlockedMove", good_item(structure="skipped_conflict")))
        self.assertTrue(self.call("isBlockedMove", good_item(structure="skipped_unknown_author")))
        self.assertFalse(self.call("isBlockedMove", good_item(structure="existing")))


class NoteTierMatchesTheOrganizerTests(unittest.TestCase):
    def test_every_note_only_reason_is_a_string_the_organizer_really_emits(self):
        block = JS[JS.index("const NOTE_ONLY_REASONS"):JS.index("function reviewReasonsOf")]
        reasons = [line.strip().strip(",").strip('"') for line in block.splitlines()[1:] if line.strip().startswith('"')]
        self.assertGreaterEqual(len(reasons), 3)
        for reason in reasons:
            self.assertIn(f'"{reason}"', SCRIPT, reason)


class MoveCardPathsTests(unittest.TestCase):
    def test_card_shows_the_full_source_and_target_not_just_their_directories(self):
        self.assertNotIn("pathDir", JS)
        details = JS[JS.index("Show source, destination, and companion files"):]
        details = details[: details.index("</details>")]
        self.assertIn("escapeHtml(item.source || \"-\")", details)
        self.assertIn("escapeHtml(item.target || \"-\")", details)

    def test_blocked_cards_say_so_and_the_count_distinguishes_them(self):
        self.assertIn("Blocked: will not move", JS)
        self.assertIn("will move,", JS)


if __name__ == "__main__":
    unittest.main()
