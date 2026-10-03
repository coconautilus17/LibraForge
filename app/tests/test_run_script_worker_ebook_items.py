import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

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

    def test_the_runs_source_opt_ins_reach_the_ebook_scan(self):
        run_id = "test-run-ebook-opt-ins"
        state = RunState(id=run_id)
        with runs_lock:
            runs[run_id] = state
        req = RunRequest(script_name="audible-metadata-fixer-v5.py", target_path=str(self.root), apply=False,
                         enable_goodreads_fallback=True, enable_openlibrary_fallback=False)

        def fake_stream_process_output(state, cmd, threshold=None):
            state.returncode = 0

        with patch("app.main.stream_process_output", side_effect=fake_stream_process_output), \
             patch("app.main.scan_ebook_units_for_report", return_value=[]) as scan_mock, \
             patch("app.main.build_command", return_value=(["true"], 10.0)):
            run_script_worker(run_id, req)

        scan_mock.assert_called_once_with(
            self.root, goodreads=True, open_library=False, progress=ANY,
        )

    def test_ebook_scan_and_report_save_have_distinct_live_phases(self):
        run_id = "test-run-ebook-status"
        state = RunState(id=run_id)
        with runs_lock:
            runs[run_id] = state
        req = RunRequest(script_name="audible-metadata-fixer-v5.py", target_path=str(self.root), apply=False)
        observed = []

        def inspect_scan(*_args, **_kwargs):
            observed.append((state.status, state.phase_label, state.current_file))
            return []

        def inspect_report(real_writer):
            def write(s, final_status=None):
                observed.append((s.status, s.phase_label, final_status))
                return real_writer(s, final_status=final_status)
            return write

        def fake_stream(s, *_args, **_kwargs):
            s.returncode = 0
            s.current = s.total = s.write_current = 2
            s.stats["scan_complete"] = True

        from app.main import write_final_report
        with patch("app.main.stream_process_output") as stream, \
             patch("app.main.scan_ebook_units_for_report", side_effect=inspect_scan), \
             patch("app.main.write_final_report", side_effect=inspect_report(write_final_report)), \
             patch("app.main.build_command", return_value=(["true"], 10.0)):
            stream.side_effect = fake_stream
            run_script_worker(run_id, req)

        self.assertEqual(observed[0], ("running", "Checking ebooks for match report", ""))
        self.assertEqual(observed[1], ("running", "Saving match report", "completed"))
        self.assertEqual((state.status, state.phase, state.percent), ("completed", "complete", 100.0))
        report = json.loads(state.report_path.read_text(encoding="utf-8"))
        self.assertEqual((report["status"], report["phase"], report["percent"]),
                         ("completed", "complete", 100.0))
        self.assertEqual(report["run_type"], "fixer")
        self.assertEqual((report["current"], report["write_current"], report["total"]), (2, 2, 2))
        self.assertTrue(report["stats"]["scan_complete"])


if __name__ == "__main__":
    unittest.main()
