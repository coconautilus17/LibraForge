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

    def test_ga_source_category_and_provider_breakdown(self):
        lines = [
            "[1/1] Processing: /lib/Dramatized/book.m4b",
            "AUDIBLE MATCH:",
            "  Mode:     full",
            "  SOURCE: graphicaudio",
        ]
        state = run_lines(lines)
        self.assertEqual(
            [i["path"] for i in state.files_by_category.get("provider:graphicaudio", [])],
            ["/lib/Dramatized/book.m4b"],
        )
        self.assertEqual(state.stats["provider_breakdown"].get("graphicaudio"), 1)
        self.assertNotIn("review:special-publisher", state.files_by_category)

    def test_goodreads_header_counts_as_matched_with_provider(self):
        lines = [
            "[1/1] Processing: /lib/Unmatched/book.m4b",
            "GOODREADS MATCH:",
            "  Mode:     full",
            "  SOURCE: goodreads",
        ]
        state = run_lines(lines)
        self.assertEqual(
            self._paths(state, "status:matched"), ["/lib/Unmatched/book.m4b"]
        )
        self.assertEqual(
            [i["path"] for i in state.files_by_category.get("provider:goodreads", [])],
            ["/lib/Unmatched/book.m4b"],
        )
        self.assertEqual(state.stats["provider_breakdown"].get("goodreads"), 1)

    def test_pass1_progress_counts_completed_out_of_order_results(self):
        lines = [
            "Found 3 supported files.",
            "PASS 1 PROGRESS: completed 1/3",
            "[3/3] Processing: /lib/Slow-order/book3.m4b",
            "AUDIBLE MATCH:",
            "PASS 1 PROGRESS: completed 2/3",
            "[1/3] Processing: /lib/Slow-order/book1.m4b",
            "AUDIBLE MATCH:",
        ]
        state = run_lines(lines)
        self.assertEqual(state.current, 2)
        self.assertEqual(state.total, 3)
        self.assertEqual(state.phase_detail, "Completed 2 of 3 · result item 1")
        self.assertGreater(state.percent, 5.0)
        self.assertEqual(
            self._paths(state, "status:matched"),
            ["/lib/Slow-order/book3.m4b", "/lib/Slow-order/book1.m4b"],
        )

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
        # After "Summary:" current_file is cleared, so a SOURCE: line in the
        # report section must NOT add a provider category to the last processed book.
        lines = [
            "[1/1] Processing: /lib/Only/book.m4b",
            "AUDIBLE MATCH:",
            "Summary:",
            "MANUAL REVIEW REPORT:",
            "  SOURCE: graphicaudio",
        ]
        state = run_lines(lines)
        self.assertNotIn("provider:graphicaudio", state.files_by_category)


if __name__ == "__main__":
    unittest.main()
