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

    def test_with_both_rules_off_nothing_is_deleted(self):
        self.report("20260101-000000-a", age_days=900)
        self.assertEqual(self.prune(), [])
        self.assertIn("20260101-000000-a.report.json", self.names())

    def test_reports_older_than_the_age_limit_are_deleted_with_their_log_and_review_files(self):
        self.report("old", age_days=40)
        self.report("new", age_days=5)
        self.assertEqual(self.prune(max_age_days_enabled=True, max_age_days=30), ["old"])
        self.assertEqual(self.names(), ["new.log.txt", "new.report.json", "new.report.suspect-review.json"])

    def test_the_age_limit_is_strict(self):
        self.report("edge", age_days=29)
        self.assertEqual(self.prune(max_age_days_enabled=True, max_age_days=30), [])
        self.assertEqual(self.prune(max_age_days_enabled=True, max_age_days=0), [])      # 0 falls back to the 30 day default

    def test_the_newest_reports_by_name_are_kept_up_to_the_count_limit(self):
        for run_id in ("20260101-a", "20260102-b", "20260103-c", "20260104-d"):
            self.report(run_id)
        self.assertEqual(self.prune(max_count_enabled=True, max_count=2), ["20260101-a", "20260102-b"])
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.report.json")), ["20260103-c.report.json", "20260104-d.report.json"])

    def test_a_count_limit_of_zero_falls_back_to_twenty(self):
        for number in range(22):
            self.report(f"2026{number:04d}-x")
        self.assertEqual(len(self.prune(max_count_enabled=True, max_count=0)), 2)

    def test_both_rules_together_delete_the_union(self):
        self.report("20260101-old", age_days=60)
        self.report("20260102-b")
        self.report("20260103-c")
        self.assertEqual(self.prune(max_age_days_enabled=True, max_age_days=30, max_count_enabled=True, max_count=1),
                         ["20260101-old", "20260102-b"])

    def test_missing_companion_files_do_not_stop_the_deletion(self):
        self.report("old", age_days=40, extras=())
        self.assertEqual(self.prune(max_age_days_enabled=True), ["old"])
        self.assertEqual(self.names(), [])

    def test_a_new_report_with_unrelated_files_in_the_folder_keeps_them(self):
        (self.dir / "notes.txt").write_text("keep")
        self.report("old", age_days=40)
        self.prune(max_age_days_enabled=True)
        self.assertEqual(self.names(), ["notes.txt"])


class ExpandCategoriesTests(unittest.TestCase):
    def test_a_legacy_report_keeps_its_files_by_category(self):
        report = {"files_by_category": {"mode:full": [{"path": "/a", "title": "A"}]}, "categories": {"x": [1]}, "items": [{"id": 1}]}
        self.assertEqual(main.expand_report_categories(report), {"mode:full": [{"path": "/a", "title": "A"}]})
        self.assertEqual(main.expand_report_categories({"files_by_category": None}), {})

    def test_a_normalised_report_is_expanded_from_item_ids(self):
        report = {"items": [{"id": 1, "path": "/a", "title": "A"}, {"id": 2, "path": "/b", "title": "B"}],
                  "categories": {"mode:full": [1, 2], "duration:perfect": [2]}}
        self.assertEqual(main.expand_report_categories(report), {
            "mode:full": [{"path": "/a", "title": "A"}, {"path": "/b", "title": "B"}],
            "duration:perfect": [{"path": "/b", "title": "B"}]})

    def test_a_category_detail_replaces_the_title_for_that_category_only(self):
        report = {"items": [{"id": 1, "path": "/a", "title": "A", "category_details": {"duration:mismatch": "12% off"}}],
                  "categories": {"duration:mismatch": [1], "mode:full": [1]}}
        got = main.expand_report_categories(report)
        self.assertEqual(got["duration:mismatch"][0]["title"], "12% off")
        self.assertEqual(got["mode:full"][0]["title"], "A")

    def test_unknown_ids_are_dropped_and_items_without_an_id_are_ignored(self):
        report = {"items": [{"id": 1, "path": "/a"}, {"path": "/no-id"}, {"id": 0, "path": "/zero"}], "categories": {"c": [1, 99, 0]}}
        self.assertEqual(main.expand_report_categories(report), {"c": [{"path": "/a", "title": ""}, {"path": "/zero", "title": ""}]})

    def test_empty_reports_expand_to_nothing(self):
        self.assertEqual(main.expand_report_categories({}), {})
        self.assertEqual(main.expand_report_categories({"categories": None}), {})


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

    def test_the_spinner_counts_finished_parts_and_is_not_logged(self):
        state = self.state()
        self.assertIs(self.parse(state, "  3 remaining / 10 total"), False)
        self.assertEqual((state.current, state.total), (7, 10))
        self.assertEqual(state.phase, "converting")
        self.assertEqual(state.phase_detail, "7 of 10 parts")

    def test_when_nothing_remains_the_run_is_finalising_at_ninety_percent(self):
        state = self.state()
        self.parse(state, "0 remaining / 10 total")
        self.assertEqual((state.phase, state.percent, state.current), ("finalizing", 90.0, 10))

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

    def test_a_tagged_line_without_a_chapter_count_still_advances_but_records_nothing(self):
        state = self.state()
        self.parse(state, "tagged file x")
        self.assertEqual(state.percent, 98.0)
        self.assertNotIn("chapters_created", state.stats)

    def test_ordinary_lines_are_logged_and_change_nothing(self):
        state = self.state()
        self.assertIs(self.parse(state, "some other output"), True)
        self.assertEqual(state.percent, 0.0)


if __name__ == "__main__":
    unittest.main()
