"""The Metadata Fixer's --restore-metadata mode through its command line, on a
real MP4 file: it must put the backed-up tags back, report what it did, and
refuse a missing root."""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

FIXER = load_script("fixer_cli_restore", "audible-metadata-fixer-v5.py")


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

    def test_mixed_folders_restore_only_the_books_that_have_backups(self):
        from mutagen.mp4 import MP4
        a = self.book("a.m4b")
        b = self.book("b.m4b", backup=False)
        out, _ = run_cli(str(self.root), "--restore-metadata")
        self.assertEqual(MP4(str(a)).tags["\xa9nam"], ["Original Title"])
        self.assertEqual(MP4(str(b)).tags["\xa9nam"], ["Applied Title"])
        self.assertIn("Restored: 1", out)
        self.assertIn("Skipped:  1", out)

if __name__ == "__main__":
    unittest.main()
