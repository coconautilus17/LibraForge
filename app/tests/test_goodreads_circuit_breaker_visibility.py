import unittest

from app.main import RunState, initial_stats, parse_line


class GoodreadsCircuitBreakerStatsTests(unittest.TestCase):
    def test_initial_stats_defaults(self):
        stats = initial_stats(10.0)
        self.assertIsNone(stats["search_workers"])
        self.assertFalse(stats["goodreads_circuit_tripped"])

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
