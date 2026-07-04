import unittest

from app.main import RunState, initial_organizer_stats, parse_organizer_line


class OrganizerSkipPatternStatParsingTests(unittest.TestCase):
    def test_initial_stats_include_skipped_pattern_match(self):
        stats = initial_organizer_stats()
        self.assertEqual(stats["skipped_pattern_match"], 0)

    def test_summary_line_updates_skipped_pattern_match(self):
        state = RunState("test")
        state.stats = initial_organizer_stats()

        parse_organizer_line(state, "Skipped by pattern: 3")

        self.assertEqual(state.stats["skipped_pattern_match"], 3)


if __name__ == "__main__":
    unittest.main()
