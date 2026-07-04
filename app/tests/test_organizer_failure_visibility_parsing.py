import unittest

from app.main import (
    RunState,
    finalize_organizer_move,
    initial_organizer_stats,
    parse_organizer_line,
)


class OrganizerFailureVisibilityParsingTests(unittest.TestCase):
    def test_initial_stats_include_moves_succeeded_and_failed(self):
        stats = initial_organizer_stats()
        self.assertEqual(stats["moves_succeeded"], 0)
        self.assertEqual(stats["moves_failed"], 0)
        self.assertEqual(stats["failed_move_items"], [])

    def test_summary_lines_update_succeeded_and_failed_counts(self):
        state = RunState("test")
        state.stats = initial_organizer_stats()

        parse_organizer_line(state, "Moves succeeded: 7")
        parse_organizer_line(state, "Moves failed: 2")

        self.assertEqual(state.stats["moves_succeeded"], 7)
        self.assertEqual(state.stats["moves_failed"], 2)

    def test_failed_book_block_goes_to_failed_move_items_not_move_items(self):
        state = RunState("test")
        state.stats = initial_organizer_stats()
        lines = [
            "FAILED BOOK:",
            "  Kind:   folder",
            "  Title:  Some Book",
            "  Author: Jane Doe",
            "  Files:  1",
            "  MOVE:",
            "    /incoming/book",
            "  TO:",
            "    /library/Jane Doe/Some Book",
            "  Error: [Errno 13] Permission denied",
        ]

        for line in lines:
            parse_organizer_line(state, line)
        finalize_organizer_move(state)

        self.assertEqual(state.stats["move_items"], [])
        self.assertEqual(len(state.stats["failed_move_items"]), 1)
        failed = state.stats["failed_move_items"][0]
        self.assertEqual(failed["title"], "Some Book")
        self.assertEqual(failed["error"], "[Errno 13] Permission denied")

    def test_regular_book_block_still_goes_to_move_items(self):
        state = RunState("test")
        state.stats = initial_organizer_stats()
        lines = [
            "BOOK:",
            "  Kind:   folder",
            "  Title:  Some Book",
            "  Author: Jane Doe",
            "  Files:  1",
            "  MOVE:",
            "    /incoming/book",
            "  TO:",
            "    /library/Jane Doe/Some Book",
        ]

        for line in lines:
            parse_organizer_line(state, line)
        finalize_organizer_move(state)

        self.assertEqual(state.stats["failed_move_items"], [])
        self.assertEqual(len(state.stats["move_items"]), 1)


if __name__ == "__main__":
    unittest.main()
