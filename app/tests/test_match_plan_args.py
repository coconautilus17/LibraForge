"""The server saves each dry run's matches and hands Apply the dry runs that
cover its folder, newest first, unless the user asked to search again."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import RunRequest, dry_run_plans_for, match_plan_args

SCRIPT = "audible-metadata-fixer-v5.py"


def write_plan(reports: Path, run_id: str, root: str, created_at: str) -> Path:
    path = reports / f"{run_id}.plan.jsonl"
    path.write_text(json.dumps({"plan_version": 1, "root": root, "created_at": created_at, "settings": {}}) + "\n",
                    encoding="utf-8")
    return path


class MatchPlanArgsTests(unittest.TestCase):
    def setUp(self):
        self.reports = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.reports, ignore_errors=True)
        patcher = patch("app.main.REPORTS_DIR", self.reports)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.library = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.library, ignore_errors=True)
        (self.library / "Sci-Fi" / "Expanse").mkdir(parents=True)
        (self.library / "Fantasy").mkdir()

    def request(self, **over):
        return RunRequest(**{"script_name": SCRIPT, "target_path": str(self.library), **over})

    def test_a_dry_run_saves_its_matches_in_the_reports_folder(self):
        self.assertEqual(match_plan_args(self.request(), "run1"), ["--save-plan", str(self.reports / "run1.plan.jsonl")])

    def test_apply_gets_the_dry_runs_overlapping_its_folder_newest_first(self):
        whole = write_plan(self.reports, "a", str(self.library), "2026-11-01T00:00:00")
        sub = write_plan(self.reports, "b", str(self.library / "Sci-Fi"), "2026-11-02T00:00:00")
        write_plan(self.reports, "c", str(self.library / "Fantasy"), "2026-11-03T00:00:00")
        target = self.library / "Sci-Fi" / "Expanse"
        self.assertEqual(dry_run_plans_for(target, self.reports), [sub, whole])
        self.assertEqual(dry_run_plans_for(self.library / "Sci-Fi", self.reports), [sub, whole])
        args = match_plan_args(self.request(apply=True, target_path=str(target)), "run2")
        self.assertEqual(args, ["--from-plan", str(sub), "--from-plan", str(whole)])

    def test_search_again_and_restore_use_no_plan(self):
        write_plan(self.reports, "a", str(self.library), "2026-11-01T00:00:00")
        self.assertEqual(match_plan_args(self.request(apply=True, search_again=True), "r"), [])
        self.assertEqual(match_plan_args(self.request(restore_metadata=True), "r"), [])
        self.assertEqual(match_plan_args(self.request(apply=True, script_name="fixer-v4.py"), "r"), [])


if __name__ == "__main__":
    unittest.main()
