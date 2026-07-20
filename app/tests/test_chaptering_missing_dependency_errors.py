"""Real bug found live: an unopted-in image (no requirements-chaptering.txt)
still ships the Chapter Forge page and lets a user select Hybrid (the
default-recommended backend) and click Detect. The failure used to surface
as a bare "Chapter detection runner exited with code 1" -- no mention of
what's missing or how to fix it, with the real ModuleNotFoundError only
ever reaching a server-side log file the user never sees.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.chaptering import (
    _load_sos_module,
    _missing_chaptering_dependency_error,
    transcribe_faster_whisper,
)


class MissingChapteringDependencyErrorTests(unittest.TestCase):
    def test_message_names_the_missing_module_and_the_fix(self):
        try:
            import this_module_does_not_exist_xyz123  # noqa: F401
        except ImportError as exc:
            error = _missing_chaptering_dependency_error(exc, "Hybrid detection")
        self.assertIn("Hybrid detection", str(error))
        self.assertIn("this_module_does_not_exist_xyz123", str(error))
        self.assertIn("Dockerfile.unified", str(error))
        self.assertIn("requirements-chaptering.txt", str(error))


class LoadSosModuleMissingDependencyTests(unittest.TestCase):
    def test_raises_actionable_error_when_the_script_itself_cant_import(self):
        # Exercises the real importlib exec_module path (not mocked) against
        # a script that fails exactly the way SoundOfSilence.py does in an
        # unopted-in image: a top-level import of a package that isn't
        # installed.
        with tempfile.TemporaryDirectory() as root:
            fake_script = Path(root) / "fake_sos.py"
            fake_script.write_text("import this_module_does_not_exist_xyz123\n", encoding="utf-8")
            with patch("app.chaptering._sos_script_path", return_value=fake_script):
                with self.assertRaises(RuntimeError) as ctx:
                    _load_sos_module()
        self.assertIn("Hybrid detection", str(ctx.exception))
        self.assertIn("this_module_does_not_exist_xyz123", str(ctx.exception))
        self.assertIn("Dockerfile.unified", str(ctx.exception))

    def test_unrelated_errors_in_the_script_are_not_swallowed(self):
        # Only ImportError/ModuleNotFoundError should be reworded -- a real
        # bug in the script itself should still surface as-is.
        with tempfile.TemporaryDirectory() as root:
            fake_script = Path(root) / "fake_sos.py"
            fake_script.write_text("raise ValueError('a real bug, not a missing dependency')\n", encoding="utf-8")
            with patch("app.chaptering._sos_script_path", return_value=fake_script):
                with self.assertRaises(ValueError):
                    _load_sos_module()


class TranscribeFasterWhisperMissingDependencyTests(unittest.TestCase):
    def test_raises_actionable_error_when_faster_whisper_is_not_installed(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "faster_whisper":
                raise ModuleNotFoundError("No module named 'faster_whisper'", name="faster_whisper")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(RuntimeError) as ctx:
                transcribe_faster_whisper(
                    [], model_name="small", device="cpu", compute_type="int8",
                    cpu_threads=1, vad_filter=False,
                )
        self.assertIn("Full transcription", str(ctx.exception))
        self.assertIn("faster_whisper", str(ctx.exception))
        self.assertIn("Dockerfile.unified", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
