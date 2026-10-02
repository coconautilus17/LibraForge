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

    def test_grouped_book_category(self):
        lines = [
            "[1/2] Processing: /lib/Grouped Book/book.m4b",
            "AUDIBLE MATCH:",
            "  Mode:     full",
            "  Grouped: 12 files",
            "[2/2] Processing: /lib/Single Book/book.m4b",
            "AUDIBLE MATCH:",
            "  Mode:     full",
        ]
        state = run_lines(lines)
        self.assertEqual(
            self._paths(state, "group:multi-file"),
            ["/lib/Grouped Book/book.m4b"],
        )

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

    def test_write_action_updates_report_item_and_category(self):
        lines = [
            'REPORT_ITEM_JSON: {"path": "/lib/Book/book.m4b", "status": "matched"}',
            '[1/1] Writing: /lib/Book/book.m4b',
            'WRITE_ACTION_JSON: {"path": "/lib/Book/book.m4b", "write_action": "smart_skipped", "write_note": "Smart-skip (tags already match)"}',
        ]
        state = run_lines(lines)
        self.assertEqual(state.report_items[0]["write_action"], "smart_skipped")
        self.assertEqual(
            self._paths(state, "write:smart_skipped"), ["/lib/Book/book.m4b"]
        )

    def test_write_action_before_report_item_is_merged(self):
        lines = [
            'WRITE_ACTION_JSON: {"path": "/lib/Book/book.m4b", "write_action": "written"}',
            'REPORT_ITEM_JSON: {"path": "/lib/Book/book.m4b", "status": "matched"}',
        ]
        state = run_lines(lines)
        self.assertEqual(state.report_items[0]["write_action"], "written")

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

    def test_dry_run_plan_and_skip_complete_write_progress_once(self):
        state = run_lines([
            "Found 2 supported files.",
            "PASS 1 PROGRESS: completed 2/2",
            "[1/2] Writing: /lib/First.m4b",
            "  PLAN: would write tags",
            'WRITE_ACTION_JSON: {"path": "/lib/First.m4b", "write_action": "would_write"}',
            "[2/2] Writing: /lib/Second.m4b",
            "  Write-skip: already processed",
            'WRITE_ACTION_JSON: {"path": "/lib/Second.m4b", "write_action": "write_skipped"}',
            'WRITE_ACTION_JSON: {"path": "/lib/Second.m4b", "write_action": "write_skipped"}',
            "Summary:",
        ])
        self.assertTrue(state.stats["scan_complete"])
        self.assertEqual((state.current, state.write_current, state.total), (2, 2, 2))
        self.assertEqual(state.percent, 96.0)
        self.assertEqual(state.phase_label, "Compiling review reports")
        self.assertEqual(self._paths(state, "write:would_write"), ["/lib/First.m4b"])

    def test_direct_write_during_matching_is_not_counted_twice(self):
        state = run_lines([
            "Found 1 supported files.",
            "PASS 1 PROGRESS: completed 1/1",
            "[1/1] Processing: /lib/Book.m4b",
            "  APPLIED (normal, metadata_json=book)",
            'WRITE_ACTION_JSON: {"path": "/lib/Book.m4b", "write_action": "written"}',
            "[1/1] Writing: /lib/Book.m4b",
            "  APPLIED (normal, metadata_json=book)",
        ])
        self.assertEqual(state.write_current, 1)
        self.assertEqual(state.percent, 95.0)

    def test_empty_scan_is_marked_complete(self):
        state = run_lines(["Found 0 supported files."])
        self.assertTrue(state.stats["scan_complete"])
        self.assertEqual(state.total, 0)


if __name__ == "__main__":
    unittest.main()
