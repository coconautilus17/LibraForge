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

    def test_default_backend_passes_explicit_values_through(self):
        cfg = dict(self.PLAIN, language="de", beam_size=4, max_audio_seconds=60, chunk_seconds=30, focused_rescan=False,
                   focused_model="large", focused_compute_type="float32", focused_beam_size=2, max_gap_rescans=5,
                   condition_on_previous_text=True)
        _, _, plain, _, _ = self._run(cfg)
        kw = plain.call_args.kwargs
        self.assertEqual((kw["language"], kw["beam_size"], kw["max_audio_seconds"], kw["chunk_seconds"]), ("de", 4, 60.0, 30.0))
        self.assertEqual((kw["focused_rescan"], kw["focused_model_name"], kw["focused_compute_type"]), (False, "large", "float32"))
        self.assertEqual((kw["focused_beam_size"], kw["max_gap_rescans"], kw["condition_on_previous_text"]), (2, 5, True))

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
