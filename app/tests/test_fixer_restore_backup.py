"""Restoring a book's original tags from the backup the fixer took before it
wrote anything. Runs on real MP4 and MP3 files (made with ffmpeg, read back with
mutagen) because the point is what ends up inside the file."""
import importlib.util
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

SPEC = importlib.util.spec_from_file_location("fixer_restore_backup", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)

ORIGINAL = {"title": "Original Title", "artist": "Original Author", "album_artist": "Original Author", "album": "Original Album",
            "grouping": "Original Series", "composer": "Original Narrator", "date": "2001", "genre": "Fantasy",
            "comment": "original comment", "track": "4"}

needs_ffmpeg = unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")


class RestoreFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def silent(self, name, codec):
        path = self.folder / name
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1", "-c:a", codec, str(path), "-y"], check=True)
        return path

    def write_backup(self, source, tags=None, **extra):
        lf = source.with_name(source.name + ".libraforge.json")
        lf.write_text(json.dumps({"schema_version": 2, "backup": {"format_tags": tags if tags is not None else ORIGINAL, "created_at": "t"},
                                  "marker": {"applied": True, "manually_applied": True}, **extra}))
        return lf


if __name__ == "__main__":
    unittest.main()
