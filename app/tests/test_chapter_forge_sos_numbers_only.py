"""SoS's built-in TARGET_NUMBERS_ONLY mode, wired through as an explicit
per-run checkbox (not an automatic fallback). Covers all four layers the
flag has to cross: ChapteringRunRequest -> config.json -> chaptering_runner
-> detect_chapters_hybrid -> _run_sound_of_silence.

Real-world motivation: William D. Arand's "Cultivating Chaos 4" narrates
bare numbers ("One.", "Two.", ...) with no "Chapter" keyword anywhere, so
the default MARKER_WORDS gate misses every chapter but one (the Epilogue).
Live-verified against the real file: TARGET_NUMBERS_ONLY=True recovered
all 36/36 numbered chapters, matching Audible's own chapter list exactly.
"""
import glob
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app.chaptering_runner as chaptering_runner_module
import app.main as main_module
from app.chaptering import _run_sound_of_silence
from app.main import ChapteringRunRequest, RunState, run_chaptering_worker

client = TestClient(main_module.app)


class FakeSosModule:
    def __init__(self, captured_configs):
        self._captured_configs = captured_configs

    def Config(self):
        return types.SimpleNamespace()

    def validate_ffmpeg_path(self, config):
        pass

    def AudioProcessor(self, config):
        self._captured_configs.append(config)
        processor = MagicMock()
        processor.initialize_whisper.return_value = False
        return processor


class RunSoundOfSilenceNumbersOnlyTests(unittest.TestCase):
    def test_numbers_only_false_by_default(self):
        captured_configs = []
        fake_sos = FakeSosModule(captured_configs)
        with patch("app.chaptering._load_sos_module", return_value=fake_sos):
            with self.assertRaises(RuntimeError):
                _run_sound_of_silence(Path("/tmp/does-not-matter.mp3"))
        self.assertFalse(captured_configs[0].TARGET_NUMBERS_ONLY)

    def test_numbers_only_true_is_forwarded_to_sos_config(self):
        captured_configs = []
        fake_sos = FakeSosModule(captured_configs)
        with patch("app.chaptering._load_sos_module", return_value=fake_sos):
            with self.assertRaises(RuntimeError):
                _run_sound_of_silence(Path("/tmp/does-not-matter.mp3"), numbers_only=True)
        self.assertTrue(captured_configs[0].TARGET_NUMBERS_ONLY)


class DetectChaptersHybridNumbersOnlyTests(unittest.TestCase):
    def test_sos_numbers_only_kwarg_reaches_run_sound_of_silence(self):
        from app.chaptering import detect_chapters_hybrid

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            with patch("app.chaptering.audio_files", return_value=[source]), \
                 patch("app.chaptering._run_sound_of_silence", return_value=([], 0.0, 0, [])) as mock_sos, \
                 patch("app.chaptering.annotate_unresolved_gaps", return_value=[]):
                detect_chapters_hybrid(source, sos_numbers_only=True)
            self.assertTrue(mock_sos.call_args.kwargs["numbers_only"])


class ChapteringRunnerNumbersOnlyTests(unittest.TestCase):
    def test_config_flag_reaches_detect_chapters_hybrid(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = Path(root) / "config.json"
            result_path = Path(root) / "result.json"
            config_path.write_text(
                json.dumps({
                    "backend": "hybrid-sos-focused",
                    "source_path": str(Path(root) / "book.mp3"),
                    "silence_snap": True,
                    "silence_window": 4.0,
                    "sos_numbers_only": True,
                }),
                encoding="utf-8",
            )
            with patch.object(
                chaptering_runner_module, "detect_chapters_hybrid", return_value={"chapters": []}
            ) as mock_hybrid:
                import sys
                old_argv = sys.argv
                sys.argv = ["chaptering_runner.py", str(config_path), str(result_path)]
                try:
                    exit_code = chaptering_runner_module.main()
                finally:
                    sys.argv = old_argv
            self.assertEqual(exit_code, 0)
            mock_hybrid.assert_called_once()
            self.assertTrue(mock_hybrid.call_args.kwargs["sos_numbers_only"])


class RunChapteringWorkerConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig_root = main_module.AUDIOBOOKS_ROOT
        self._orig_reports = main_module.REPORTS_DIR
        main_module.AUDIOBOOKS_ROOT = self.root
        main_module.REPORTS_DIR = self.root
        self.run_id = "test-numbers-only-run"
        self.state = RunState(id=self.run_id)
        main_module.runs[self.run_id] = self.state

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        main_module.REPORTS_DIR = self._orig_reports
        main_module.runs.pop(self.run_id, None)
        self.tmp.cleanup()

    def test_sos_numbers_only_written_into_runner_config_json(self):
        source = self.root / "book.mp3"
        source.write_bytes(b"")
        req = ChapteringRunRequest(
            source_path=str(source),
            backend="hybrid-sos-focused",
            remote_endpoint="http://192.168.1.50:8000",
            sos_numbers_only=True,
        )
        with patch.object(main_module.subprocess, "Popen", side_effect=RuntimeError("stop before spawning")):
            run_chaptering_worker(self.run_id, req)
        self.assertEqual(self.state.status, "failed")

        matches = glob.glob(str(self.root / f"{self.run_id}-chaptering-*" / "config.json"))
        self.assertEqual(len(matches), 1)
        written = json.loads(Path(matches[0]).read_text(encoding="utf-8"))
        self.assertTrue(written["sos_numbers_only"])


if __name__ == "__main__":
    unittest.main()
