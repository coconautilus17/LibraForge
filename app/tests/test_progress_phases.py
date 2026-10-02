import unittest

from app.progress_phases import (
    fixer_phase_for_line,
    m4b_phase_for_line,
    organizer_move_phase,
    organizer_progress_phase,
    terminal_phase,
)


class ProgressPhaseTests(unittest.TestCase):
    def test_fixer_reports_search_scoring_cache_and_write_phases(self):
        self.assertEqual(
            fixer_phase_for_line("  Trying query: Spice and Wolf Isuna Hasekura"),
            ("searching", "Searching Audible", "Spice and Wolf Isuna Hasekura"),
        )
        self.assertEqual(
            fixer_phase_for_line("  Results: 50"),
            ("scoring", "Scoring candidates", "Results: 50"),
        )
        self.assertEqual(
            fixer_phase_for_line(
                "  Reusing cached match for shared search context",
                "/library/book",
            ),
            ("cached-match", "Using cached match", "/library/book"),
        )
        self.assertEqual(
            fixer_phase_for_line(
                "  Mutagen MP4 write: saving metadata in place...",
                "/library/book.m4b",
            ),
            ("writing", "Writing metadata", "/library/book.m4b"),
        )
        self.assertEqual(
            fixer_phase_for_line("Summary:"),
            ("summarizing", "Compiling review reports", "Summary"),
        )

    def test_organizer_distinguishes_cache_scan_preview_and_apply(self):
        self.assertEqual(
            organizer_progress_phase(indexing=True),
            ("caching", "Caching library structures", ""),
        )
        self.assertEqual(
            organizer_progress_phase(indexing=True, refreshing=True),
            ("caching", "Refreshing structure cache", ""),
        )
        self.assertEqual(
            organizer_progress_phase(indexing=False),
            ("analyzing", "Analyzing library items", ""),
        )
        self.assertEqual(
            organizer_move_phase(False, 3),
            ("building-preview", "Building move preview", "Move 3"),
        )
        self.assertEqual(
            organizer_move_phase(True, 3),
            ("moving", "Moving books", "Move 3"),
        )

    def test_m4b_reports_conversion_subtasks(self):
        self.assertEqual(
            m4b_phase_for_line("running silence detection"),
            (
                "detecting-chapters",
                "Detecting chapters",
                "Analyzing silence markers",
            ),
        )
        self.assertEqual(
            m4b_phase_for_line("silence detection finished"),
            ("tagging", "Writing chapters and tags", "silence detection finished"),
        )

    def test_terminal_phases_are_human_readable(self):
        self.assertEqual(
            terminal_phase("completed"),
            ("complete", "Complete", "Run finished successfully"),
        )
        self.assertEqual(
            terminal_phase("cancelled"),
            ("cancelled", "Cancelled", "Run was cancelled"),
        )
        self.assertEqual(
            terminal_phase("failed", "bad output"),
            ("failed", "Failed", "bad output"),
        )


if __name__ == "__main__":
    unittest.main()
