import unittest

from app.main import (
    RunState,
    build_report_items,
    derive_manual_review_items,
    initial_stats,
    parse_line,
)


def run_lines(lines):
    state = RunState("test")
    state.stats = initial_stats(10)
    for line in lines:
        parse_line(state, line, 10)
    return state


class ReportParserCategoryTests(unittest.TestCase):
    def _paths(self, state, key):
        return [item["path"] for item in state.files_by_category.get(key, [])]

    def test_matched_and_tiebreak_and_fill_categories(self):
        lines = [
            "[1/2] Processing: /lib/Book One/book.m4b",
            "AUDIBLE MATCH:",
            "  Mode:     full",
            "  ambiguous match: 2 candidates at score 1.0 (chose Book One [B01] on duration)",
            "  FILL: filled series, asin",
            "[2/2] Processing: /lib/Book Two/book.m4b",
            "AUDIBLE MATCH:",
            "  FILL: complete",
            "Summary:",
            "MANUAL REVIEW REPORT:",
            "  - /lib/Book One/book.m4b",
            "    reason: ambiguous match: 2 candidates at score 1.0 (chose Book One [B01] on duration)",
        ]
        state = run_lines(lines)
        self.assertEqual(self._paths(state, "status:matched"),
                         ["/lib/Book One/book.m4b", "/lib/Book Two/book.m4b"])
        self.assertEqual(self._paths(state, "review:duration-tiebreak"),
                         ["/lib/Book One/book.m4b"])
        self.assertEqual(self._paths(state, "fill:filled"), ["/lib/Book One/book.m4b"])
        self.assertEqual(self._paths(state, "fill:asin"), ["/lib/Book One/book.m4b"])
        self.assertEqual(self._paths(state, "fill:complete"), ["/lib/Book Two/book.m4b"])

    def test_special_publisher_category_and_review(self):
        lines = [
            "[1/1] Processing: /lib/Dramatized/book.m4b",
            "AUDIBLE MATCH:",
            "  publisher Graphic Audio — consider the Graphic Audio abs-agg endpoint "
            "(graphicaudio) instead of Audible",
        ]
        state = run_lines(lines)
        self.assertEqual(
            [i["path"] for i in state.files_by_category.get("review:special-publisher", [])],
            ["/lib/Dramatized/book.m4b"],
        )
        _items, categories = build_report_items(state.files_by_category)
        review = derive_manual_review_items(state.stats, state.files_by_category)
        reasons = {r for item in review for r in item["reasons"]}
        self.assertIn("special publisher", reasons)

    def test_tiebreak_surfaced_in_manual_review(self):
        lines = [
            "[1/1] Processing: /lib/Book One/book.m4b",
            "AUDIBLE MATCH:",
            "  ambiguous match: 2 candidates at score 1.0 (chose Book One [B01] on duration)",
        ]
        state = run_lines(lines)
        review = derive_manual_review_items(state.stats, state.files_by_category)
        reasons = {r for item in review for r in item["reasons"]}
        self.assertIn("duration tie-break", reasons)

    def test_report_lines_do_not_misattribute_after_summary(self):
        # After "Summary:" current_file is cleared, so a report reason line must NOT
        # add a category to the last processed book.
        lines = [
            "[1/1] Processing: /lib/Only/book.m4b",
            "AUDIBLE MATCH:",
            "Summary:",
            "DURATION REVIEW REPORT (> 10% difference):",
            "    reason: consider the Graphic Audio abs-agg endpoint (graphicaudio) instead of Audible",
        ]
        state = run_lines(lines)
        self.assertNotIn("review:special-publisher", state.files_by_category)


if __name__ == "__main__":
    unittest.main()
