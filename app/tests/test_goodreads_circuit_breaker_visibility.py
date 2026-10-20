import unittest

from app.main import RunState, initial_stats, parse_line


class GoodreadsCircuitBreakerStatsTests(unittest.TestCase):
    def test_initial_stats_defaults(self):
        self.assertEqual(initial_stats(10.0), {
            "found": 0, "matched": 0, "skipped": 0, "failed": 0, "smart_skipped": 0,
            "mode_breakdown": {"full": 0, "series_only": 0, "none": 0, "unknown": 0},
            "duration_breakdown": {"perfect": 0, "strong": 0, "acceptable": 0, "mismatch": 0, "unknown": 0},
            "large_duration_threshold": 10.0, "large_duration_items": [], "skip_reasons": {},
            "error_count": 0, "provider_breakdown": {}, "search_workers": None, "goodreads_circuit_tripped": False,
        })

    def test_search_workers_line_sets_stat(self):
        state = RunState("test")
        state.stats = initial_stats(10.0)

        parse_line(state, "Search workers: 8", 10.0)

        self.assertEqual(state.stats["search_workers"], 8)

    def test_circuit_tripped_sentinel_sets_stat(self):
        state = RunState("test")
        state.stats = initial_stats(10.0)

        parse_line(state, "GOODREADS_CIRCUIT_TRIPPED", 10.0)

        self.assertTrue(state.stats["goodreads_circuit_tripped"])

    def test_circuit_tripped_stat_defaults_false_without_sentinel(self):
        state = RunState("test")
        state.stats = initial_stats(10.0)

        parse_line(state, "Search workers: 3", 10.0)

        self.assertFalse(state.stats["goodreads_circuit_tripped"])


if __name__ == "__main__":
    unittest.main()
