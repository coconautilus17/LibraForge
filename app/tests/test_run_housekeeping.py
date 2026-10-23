"""Report retention (which finished runs are deleted), the category expansion the
report API serves, and the m4b-tool progress parser."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import main


class PruneReportsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patcher = mock.patch.object(main, "REPORTS_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def report(self, run_id, age_days=0, extras=(".log.txt", ".report.suspect-review.json")):
        path = self.dir / f"{run_id}.report.json"
        path.write_text("{}")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        for suffix in extras:
            (self.dir / f"{run_id}{suffix}").write_text("x")
        return path

    def prune(self, **cfg):
        base = {"max_age_days_enabled": False, "max_age_days": 30, "max_count_enabled": False, "max_count": 20}
        with mock.patch.object(main, "_load_retention_config", return_value={**base, **cfg}):
            return sorted(main._prune_reports())

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_both_rules_together_delete_the_union(self):
        self.report("20260101-old", age_days=60)
        self.report("20260102-b")
        self.report("20260103-c")
        self.assertEqual(self.prune(max_age_days_enabled=True, max_age_days=30, max_count_enabled=True, max_count=1),
                         ["20260101-old", "20260102-b"])

class ExpandCategoriesTests(unittest.TestCase):
    def test_a_legacy_report_keeps_its_files_by_category(self):
        report = {"files_by_category": {"mode:full": [{"path": "/a", "title": "A"}]}, "categories": {"x": [1]}, "items": [{"id": 1}]}
        self.assertEqual(main.expand_report_categories(report), {"mode:full": [{"path": "/a", "title": "A"}]})
        self.assertEqual(main.expand_report_categories({"files_by_category": None}), {})

    def test_unknown_ids_are_dropped_and_items_without_an_id_are_ignored(self):
        report = {"items": [{"id": 1, "path": "/a"}, {"path": "/no-id"}, {"id": 0, "path": "/zero"}], "categories": {"c": [1, 99, 0]}}
        self.assertEqual(main.expand_report_categories(report), {"c": [{"path": "/a", "title": ""}, {"path": "/zero", "title": ""}]})

class ParseM4bLineTests(unittest.TestCase):
    def state(self, **kw):
        return main.RunState(id="r", **kw)

    def parse(self, state, line):
        return main.parse_m4b_line(state, line)

    def test_a_found_files_line_starts_the_progress_at_one_percent_and_is_consumed(self):
        state = self.state()
        self.assertIs(self.parse(state, "found 12 files to convert"), True)
        self.assertEqual(state.percent, 1.0)
        state.percent = 50.0
        self.parse(state, "found 12 files to convert")
        self.assertEqual(state.percent, 50.0)                      # never moves backwards

    def test_an_encoding_phase_is_not_replaced_by_the_spinner_and_a_larger_percent_is_kept(self):
        state = self.state(phase="encoding", percent=95.0)
        self.parse(state, "4 remaining / 10 total")
        self.assertEqual(state.phase, "encoding")
        self.parse(state, "0 remaining / 10 total")
        self.assertEqual(state.percent, 95.0)

    def test_a_remaining_count_larger_than_the_total_never_goes_negative(self):
        state = self.state()
        self.parse(state, "12 remaining / 10 total")
        self.assertEqual(state.current, 0)

    def test_the_silence_detection_and_tagging_milestones(self):
        state = self.state()
        self.parse(state, "running silence detection")
        self.assertEqual(state.percent, 92.0)
        self.parse(state, "silence detection finished")
        self.assertEqual(state.percent, 95.0)
        self.parse(state, "tagged file /x/book.m4b, chapters: 14)")
        self.assertEqual((state.percent, state.stats["chapters_created"]), (98.0, 14))
        self.parse(state, "successfully merged 3 files")
        self.assertEqual(state.percent, 100.0)

if __name__ == "__main__":
    unittest.main()
