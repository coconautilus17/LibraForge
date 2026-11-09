"""Text cleanup that the matcher repeats on the same strings is remembered, but
never across a change to the title-noise or publisher lists; the policy files
are looked at no more than once a second; the genre name tables are built once."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import genre_taxonomy, publisher_policy, title_noise_policy
from app.fixer import parsing


class PolicyFileChecksTests(unittest.TestCase):
    def setUp(self):
        title_noise_policy.clear_title_noise_cache()
        publisher_policy.clear_publisher_cache()
        self.addCleanup(title_noise_policy.clear_title_noise_cache)
        self.addCleanup(publisher_policy.clear_publisher_cache)

    def count_stats(self, call, *, times: int, clock: list[float]) -> int:
        real_stat = Path.stat
        seen = []

        def stat(path, *a, **k):
            seen.append(path)
            return real_stat(path, *a, **k)

        with patch.object(Path, "stat", stat), patch("time.monotonic", lambda: clock[0]):
            for _ in range(times):
                call()
        return len(seen)

    def test_title_noise_files_are_checked_at_most_once_a_second(self):
        clock = [1000.0]
        self.count_stats(title_noise_policy.active_title_noise_patterns, times=1, clock=clock)
        self.assertEqual(self.count_stats(title_noise_policy.active_title_noise_patterns, times=50, clock=clock), 0)
        clock[0] += 1.5
        self.assertGreater(self.count_stats(title_noise_policy.active_title_noise_patterns, times=1, clock=clock), 0)

    def test_publisher_files_are_checked_at_most_once_a_second(self):
        clock = [1000.0]
        self.count_stats(lambda: publisher_policy.strip_publisher_noise("Tantor Audio"), times=1, clock=clock)
        self.assertEqual(self.count_stats(lambda: publisher_policy.strip_publisher_noise("x Tantor Audio"),
                                          times=50, clock=clock), 0)

    def test_another_policy_file_is_read_at_once(self):
        title_noise_policy.active_title_noise_patterns()
        with tempfile.TemporaryDirectory() as temporary:
            local_file = Path(temporary) / "title-noise.local.json"
            local_file.write_text(json.dumps({"schema_version": 1, "disabled_defaults": [], "custom_patterns": [
                {"id": "x", "label": "x", "pattern": r"zorblax\s+edition", "enabled": True}]}), encoding="utf-8")
            with patch.object(title_noise_policy, "LOCAL_POLICY_FILE", local_file):
                self.assertTrue(title_noise_policy.is_title_noise("Zorblax Edition"))


class CleanupMemoTests(unittest.TestCase):
    def setUp(self):
        title_noise_policy.clear_title_noise_cache()
        publisher_policy.clear_publisher_cache()
        self.addCleanup(title_noise_policy.clear_title_noise_cache)
        self.addCleanup(publisher_policy.clear_publisher_cache)

    def test_repeated_cleanup_is_remembered(self):
        title = "Arrival - A Humorous Isekai LitRPG (Unabridged) [Tantor Audio]"
        first = parsing.normalize_for_match(title)
        with patch.object(parsing, "sanitize_technical_labels", side_effect=AssertionError("cleaned again")):
            self.assertEqual(parsing.normalize_for_match(title), first)
            self.assertEqual(parsing.sanitize_book_title(title), parsing.sanitize_book_title(title))

    def test_a_saved_title_noise_pattern_applies_to_remembered_titles(self):
        title = "Dungeon Days: A Zorblax Saga"
        self.assertEqual(parsing.normalize_for_match(title), "dungeon days a zorblax saga")
        with tempfile.TemporaryDirectory() as temporary:
            local_file = Path(temporary) / "title-noise.local.json"
            with patch.object(title_noise_policy, "LOCAL_POLICY_FILE", local_file):
                title_noise_policy.save_title_noise_policy(disabled_defaults=[], custom_patterns=[
                    {"id": "zorblax", "label": "Zorblax", "pattern": r"(?:a|an)\s+zorblax\s+saga", "enabled": True}])
                self.assertEqual(parsing.normalize_for_match(title), "dungeon days")

    def test_a_saved_publisher_applies_to_remembered_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            local_file = Path(temporary) / "publishers.local.json"
            with patch.object(publisher_policy, "LOCAL_POLICY_FILE", local_file):
                publisher_policy.clear_publisher_cache()
                self.assertEqual(publisher_policy.strip_publisher_noise("Jo Bloggs - Zorblax Audio"), "Jo Bloggs - Zorblax Audio")
                publisher_policy.save_publisher_policy(disabled_defaults=[], custom_publishers=[
                    {"id": "zorblax-audio", "name": "Zorblax Audio"}])
                self.assertEqual(publisher_policy.strip_publisher_noise("Jo Bloggs - Zorblax Audio"), "Jo Bloggs")

    def test_an_author_credit_is_split_once(self):
        credit = "Brandon Sanderson & Dan Wells"
        first = parsing._split_author_names(credit)
        parsing._authors_compatible(credit, "Dan Wells")
        with patch.object(parsing, "split_credit_names", side_effect=AssertionError("split again")):
            self.assertEqual(parsing._split_author_names(credit), first)
            self.assertTrue(parsing._authors_compatible(credit, "Dan Wells"))
        returned = parsing._split_author_names(credit)
        returned.append("someone else")  # a caller's copy, never the remembered names
        self.assertEqual(parsing._split_author_names(credit), first)

    def test_unhashable_input_is_still_cleaned(self):
        self.assertEqual(parsing.normalize_for_match(None), "")


class GenreTablesTests(unittest.TestCase):
    def test_tables_are_built_once_and_match_a_fresh_build(self):
        names = {n for m, sub in genre_taxonomy.LABEL_MAP.values() for n in m + sub}
        fresh = {n.lower(): n for n in set(genre_taxonomy.MAIN_ORDER) | names if not n.endswith("?")}
        self.assertEqual(genre_taxonomy._output_names(), fresh)
        self.assertIs(genre_taxonomy._output_names(), genre_taxonomy._output_names())
        known = set(genre_taxonomy.LABEL_MAP) | {n.lower() for n in names}
        for label in list(known)[:200] + ["fantasys", "not a genre", "LitRPG", "Science Fiction"]:
            label_n = genre_taxonomy.normalize_label(label)
            expected = label_n in known or (label_n.endswith("s") and label_n[:-1] in known)
            self.assertEqual(genre_taxonomy._is_known_genre(label), expected, label)


if __name__ == "__main__":
    unittest.main()
