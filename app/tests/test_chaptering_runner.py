"""app.chaptering_runner is the subprocess entry point Chapter Forge launches:
it turns a config JSON into the keyword arguments of the detector, applying
documented fallbacks. These tests assert exactly what the detector receives."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import chaptering_runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, config, hybrid=None, plain=None):
        cfg = self.dir / "config.json"
        out = self.dir / "result.json"
        cfg.write_text(json.dumps(config))
        hybrid = hybrid or mock.Mock(return_value={"chapters": [1, 2]})
        plain = plain or mock.Mock(return_value={"chapters": [1]})
        with mock.patch.object(chaptering_runner, "detect_chapters_hybrid", hybrid), \
             mock.patch.object(chaptering_runner, "detect_chapters", plain), \
             mock.patch("sys.argv", ["runner", str(cfg), str(out)]), \
             mock.patch("builtins.print") as printed:
            code = chaptering_runner.main()
        return code, hybrid, plain, out, printed

    HYBRID = {"backend": "hybrid-sos-focused", "source_path": "/b.m4b", "silence_snap": True, "silence_window": 2}
    PLAIN = {"source_path": "/b.m4b", "model": "small", "device": "cpu", "compute_type": "int8", "cpu_threads": 2,
             "vad_filter": True, "silence_snap": False, "silence_window": 1.5, "stable_ts": False}

    def test_wrong_argument_count_returns_usage_error(self):
        with mock.patch("sys.argv", ["runner"]), mock.patch("sys.stderr"):
            self.assertEqual(chaptering_runner.main(), 2)

    def test_hybrid_backend_applies_every_documented_default(self):
        code, hybrid, plain, _, _ = self._run(self.HYBRID)
        self.assertEqual(code, 0)
        plain.assert_not_called()
        kw = hybrid.call_args.kwargs
        self.assertEqual(kw["remote_endpoint"], "")
        self.assertEqual(kw["focused_model_name"], "medium")
        self.assertEqual(kw["focused_compute_type"], "float16")
        self.assertEqual(kw["max_gap_rescans"], 8)
        self.assertEqual(kw["silence_marker_lead_seconds"], 1.0)
        self.assertIs(kw["llm_review"], False)
        self.assertEqual(kw["llm_endpoint"], "")
        self.assertEqual(kw["llm_model"], "gemma4:latest")
        self.assertEqual(kw["llm_extra_instructions"], "")
        self.assertIs(kw["sos_numbers_only"], False)
        self.assertIs(kw["silence_snap"], True)
        self.assertEqual(kw["silence_window"], 2.0)

    def test_hybrid_backend_passes_explicit_values_through(self):
        cfg = dict(self.HYBRID, remote_endpoint="http://asr", focused_model="large", focused_compute_type="int8",
                   max_gap_rescans=3, silence_marker_lead_seconds=0.25, llm_review=True,
                   llm_endpoint="http://llm", llm_model="m", llm_extra_instructions="be brief", sos_numbers_only=True)
        _, hybrid, _, _, _ = self._run(cfg)
        kw = hybrid.call_args.kwargs
        self.assertEqual((kw["remote_endpoint"], kw["focused_model_name"], kw["focused_compute_type"]),
                         ("http://asr", "large", "int8"))
        self.assertEqual((kw["max_gap_rescans"], kw["silence_marker_lead_seconds"]), (3, 0.25))
        self.assertEqual((kw["llm_review"], kw["llm_endpoint"], kw["llm_model"], kw["llm_extra_instructions"]),
                         (True, "http://llm", "m", "be brief"))
        self.assertIs(kw["sos_numbers_only"], True)

    def test_hybrid_blank_values_fall_back_like_missing_ones(self):
        cfg = dict(self.HYBRID, focused_model="", focused_compute_type="", max_gap_rescans=0, llm_model="")
        _, hybrid, _, _, _ = self._run(cfg)
        kw = hybrid.call_args.kwargs
        self.assertEqual((kw["focused_model_name"], kw["focused_compute_type"], kw["max_gap_rescans"], kw["llm_model"]),
                         ("medium", "float16", 8, "gemma4:latest"))

    def test_default_backend_applies_its_defaults(self):
        code, hybrid, plain, _, _ = self._run(self.PLAIN)
        hybrid.assert_not_called()
        kw = plain.call_args.kwargs
        self.assertEqual(kw["language"], "en")
        self.assertEqual(kw["beam_size"], 1)
        self.assertEqual(kw["max_audio_seconds"], 0.0)
        self.assertEqual(kw["chunk_seconds"], 0.0)
        self.assertIs(kw["focused_rescan"], True)
        self.assertEqual(kw["focused_model_name"], "")
        self.assertEqual(kw["focused_compute_type"], "")
        self.assertEqual(kw["focused_beam_size"], 5)
        self.assertEqual(kw["max_gap_rescans"], 8)
        self.assertIs(kw["condition_on_previous_text"], False)
        self.assertEqual((kw["model_name"], kw["device"], kw["compute_type"], kw["cpu_threads"]), ("small", "cpu", "int8", 2))

    def test_default_backend_passes_explicit_values_through(self):
        cfg = dict(self.PLAIN, language="de", beam_size=4, max_audio_seconds=60, chunk_seconds=30, focused_rescan=False,
                   focused_model="large", focused_compute_type="float32", focused_beam_size=2, max_gap_rescans=5,
                   condition_on_previous_text=True)
        _, _, plain, _, _ = self._run(cfg)
        kw = plain.call_args.kwargs
        self.assertEqual((kw["language"], kw["beam_size"], kw["max_audio_seconds"], kw["chunk_seconds"]), ("de", 4, 60.0, 30.0))
        self.assertEqual((kw["focused_rescan"], kw["focused_model_name"], kw["focused_compute_type"]), (False, "large", "float32"))
        self.assertEqual((kw["focused_beam_size"], kw["max_gap_rescans"], kw["condition_on_previous_text"]), (2, 5, True))

    def test_result_is_written_and_completion_event_reports_the_chapter_count(self):
        _, _, _, out, printed = self._run(self.HYBRID)
        self.assertEqual(json.loads(out.read_text()), {"chapters": [1, 2]})
        events = [json.loads(c.args[0]) for c in printed.call_args_list]
        self.assertEqual(events[-1], {"type": "complete", "chapters": 2})
        self.assertTrue(all(c.kwargs.get("flush") is True for c in printed.call_args_list))

    def test_progress_messages_are_emitted_as_json_events(self):
        def hybrid(*a, **kw):
            kw["progress"]("halfway")
            return {"chapters": []}
        _, _, _, _, printed = self._run(self.HYBRID, hybrid=mock.Mock(side_effect=hybrid))
        events = [json.loads(c.args[0]) for c in printed.call_args_list]
        self.assertIn({"type": "progress", "message": "halfway"}, events)
        self.assertEqual(events[-1], {"type": "complete", "chapters": 0})


if __name__ == "__main__":
    unittest.main()
