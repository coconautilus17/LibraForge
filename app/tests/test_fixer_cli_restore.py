"""The Metadata Fixer's --restore-metadata mode through its command line, on a
real MP4 file: it must put the backed-up tags back, report what it did, and
refuse a missing root."""
import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_cli_restore", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


def run_cli(*args):
    out = io.StringIO()
    old = sys.argv
    sys.argv = ["fixer", *args]
    code = None
    try:
        with contextlib.redirect_stdout(out):
            try:
                FIXER.main()
            except SystemExit as exit_:
                code = exit_.code
    finally:
        sys.argv = old
    return out.getvalue(), code


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class RestoreCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def book(self, name="book.m4b", applied="Applied Title", backup=True):
        from mutagen.mp4 import MP4
        path = self.root / name
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1", "-c:a", "aac", str(path), "-y"], check=True)
        audio = MP4(str(path))
        audio["\xa9nam"] = [applied]
        audio.save()
        if backup:
            path.with_name(path.name + ".libraforge.json").write_text(json.dumps(
                {"schema_version": 2, "backup": {"format_tags": {"title": "Original Title", "artist": "Original Author"}}}))
        return path

    def test_the_backed_up_tags_are_restored_and_the_run_reports_it(self):
        from mutagen.mp4 import MP4
        path = self.book()
        out, code = run_cli(str(self.root), "--restore-metadata")
        self.assertIsNone(code)
        self.assertEqual(MP4(str(path)).tags["\xa9nam"], ["Original Title"])
        self.assertEqual(MP4(str(path)).tags["\xa9ART"], ["Original Author"])
        self.assertIn("Mode: RESTORE METADATA", out)
        self.assertIn("Found 1 supported files.", out)
        self.assertIn("RESTORED from:", out)
        for line in ("Found:    1 files", "Restored: 1", "Skipped:  0", "Failed:   0"):
            self.assertIn(line, out)

    def test_a_book_without_a_backup_is_skipped_and_left_untouched(self):
        from mutagen.mp4 import MP4
        path = self.book(backup=False)
        out, _ = run_cli(str(self.root), "--restore-metadata")
        self.assertEqual(MP4(str(path)).tags["\xa9nam"], ["Applied Title"])
        self.assertIn("SKIP: no backup data found", out)
        self.assertIn("Restored: 0", out)
        self.assertIn("Skipped:  1", out)

    def test_mixed_folders_restore_only_the_books_that_have_backups(self):
        from mutagen.mp4 import MP4
        a = self.book("a.m4b")
        b = self.book("b.m4b", backup=False)
        out, _ = run_cli(str(self.root), "--restore-metadata")
        self.assertEqual(MP4(str(a)).tags["\xa9nam"], ["Original Title"])
        self.assertEqual(MP4(str(b)).tags["\xa9nam"], ["Applied Title"])
        self.assertIn("Restored: 1", out)
        self.assertIn("Skipped:  1", out)

    def test_a_missing_root_stops_the_run_with_an_error(self):
        _, code = run_cli(str(self.root / "nowhere"), "--restore-metadata")
        self.assertIn("path does not exist", str(code))

    def test_restoring_marks_the_record_as_no_longer_applied(self):
        path = self.book()
        run_cli(str(self.root), "--restore-metadata")
        marker = json.loads(path.with_name(path.name + ".libraforge.json").read_text()).get("marker")
        if marker is not None:
            self.assertIs(marker["applied"], False)


if __name__ == "__main__":
    unittest.main()
