import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, get_latest_run_log


class LatestRunLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reports_dir = Path(self.temp.name)
        patcher = patch("app.main.REPORTS_DIR", self.reports_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_run(self, run_id, script, status, stats, log, apply=False):
        command = ["python", "-u", f"/app/scripts/{script}"]
        if apply:
            command.append("--apply")
        (self.reports_dir / f"{run_id}.report.json").write_text(json.dumps({
            "id": run_id, "status": status, "command": command, "stats": stats,
            "started_at": 100, "finished_at": 200,
        }), encoding="utf-8")
        (self.reports_dir / f"{run_id}.log.txt").write_text(log, encoding="utf-8")

    def test_failed_fixer_uses_recorded_actions_not_missing_final_counters(self):
        self.write_run("001", "audible-metadata-fixer-v5.py", "failed", {"found": 5, "matched": 0},
                       'WRITE_ACTION_JSON: {"write_action":"written"}\n'
                       'WRITE_ACTION_JSON: {"write_action":"written"}\n'
                       'WRITE_ACTION_JSON: {"write_action":"write_skipped"}\n'
                       '  WARNING: mutagen writer failed, falling back to ffmpeg: [Errno 5] Input/output error\n'
                       'Traceback (most recent call last):\n'
                       '  File "/app/scripts/audible-metadata-fixer-v5.py", line 1\n'
                       'OSError: [Errno 5] Input/output error: book.m4b\n', apply=True)
        result = get_latest_run_log("fixer")
        self.assertEqual(result["status"], "failed")
        self.assertEqual([(m["label"], m["value"]) for m in result["metrics"]], [
            ("Books found", 5), ("Writes recorded", 2), ("Skipped / no-op", 1), ("No write result", 2),
            ("Run errors", 1),
        ])
        self.assertEqual(result["issue_count"], 2)
        self.assertEqual(result["error_count"], 1)
        self.assertIn("OSError", result["issues"][-1]["text"])
        self.assertIn("Traceback", result["log"])

    def test_tool_filter_and_organizer_failures(self):
        self.write_run("001", "organize-audiobooks-by-metadata-v3_13.py", "completed", {
            "mode": "APPLY", "found_items": 4, "planned_moves": 3,
            "moves_succeeded": 2, "moves_failed": 1,
            "failed_move_items": [{"title": "Book C", "error": "Permission denied"}],
        }, "Moves succeeded: 2\nMoves failed: 1\nFAILED BOOK:\n  Error: Permission denied\n", apply=True)
        self.write_run("002", "audible-metadata-fixer-v5.py", "completed", {"found": 1},
                       'WRITE_ACTION_JSON: {"write_action":"written"}\n', apply=True)
        result = get_latest_run_log("organizer")
        self.assertEqual(result["id"], "001")
        self.assertEqual(result["mode"], "Apply")
        self.assertEqual(result["metrics"][-1], {"label": "Moves failed", "value": 1})
        self.assertIn("Permission denied", result["issues"][0]["text"])

    def test_completed_preview_and_missing_log(self):
        self.write_run("001", "organize-audiobooks-by-metadata-v3_13.py", "completed", {
            "mode": "DRY RUN", "found_items": 3, "planned_moves": 2,
        }, "Mode: DRY RUN\nPlanned moves: 2\n")
        result = get_latest_run_log("organizer")
        self.assertEqual(result["mode"], "Preview")
        self.assertEqual(result["issue_count"], 0)
        (self.reports_dir / "001.log.txt").unlink()
        with self.assertRaises(HTTPException) as ctx:
            get_latest_run_log("organizer")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_organizer_failure_before_move_totals_is_not_reported_as_zero_success(self):
        self.write_run("001", "organize-audiobooks-by-metadata-v3_13.py", "failed", {
            "mode": "APPLY", "found_items": 3, "planned_moves": 3,
            "moves_succeeded": 0, "moves_failed": 0,
        }, "BOOK:\n  Title: First\nFAILED: second -> target | Permission denied\n", apply=True)
        result = get_latest_run_log("organizer")
        self.assertEqual(result["metrics"][-2]["value"], "Not finalized")
        self.assertEqual(result["metrics"][-1], {"label": "Failures logged", "value": 1})
        self.assertIn("Permission denied", result["issues"][0]["text"])

    def test_invalid_tool_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            get_latest_run_log("../../")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_http_route_returns_viewer_payload(self):
        self.write_run("001", "audible-metadata-fixer-v5.py", "completed", {"found": 1},
                       'WRITE_ACTION_JSON: {"write_action":"written"}\n', apply=True)
        response = TestClient(app).get("/api/run-logs/latest?tool=fixer")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metrics"][1]["value"], 1)
        self.assertEqual(response.json()["download"], "/api/runs/001/download/log")


if __name__ == "__main__":
    unittest.main()
