import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import RunRequest, RunState, run_script_worker, runs, runs_lock


class RunScriptWorkerIncludesEbookItemsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "book.mp3").write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ebook_items_land_in_report_items_alongside_audio_items(self):
        run_id = "test-run-ebook-merge"
        state = RunState(id=run_id)
        with runs_lock:
            runs[run_id] = state
        req = RunRequest(script_name="audible-metadata-fixer-v5.py", target_path=str(self.root), apply=False)

        fake_ebook_items = [{
            "path": str(self.root / "book.epub"), "local": {}, "match": None,
            "score": None, "status": "unmatched", "provider": "", "used_query": "book",
            "media_type": "ebook", "formats": ["epub"],
        }]

        def fake_stream_process_output(state, cmd, threshold=None):
            state.returncode = 0
            state.report_items.append({
                "path": str(self.root / "book.mp3"), "local": {}, "match": None,
                "score": None, "status": "unmatched",
            })

        with patch("app.main.stream_process_output", side_effect=fake_stream_process_output), \
             patch("app.main.scan_ebook_units_for_report", return_value=fake_ebook_items), \
             patch("app.main.build_command", return_value=(["true"], 10.0)):
            run_script_worker(run_id, req)

        report = json.loads(state.report_path.read_text(encoding="utf-8"))
        media_types = {item.get("media_type") for item in report["report_items"]}
        self.assertIn("ebook", media_types)
        self.assertEqual(len(report["report_items"]), 2)


if __name__ == "__main__":
    unittest.main()
