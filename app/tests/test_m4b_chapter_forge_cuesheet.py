"""build_m4b_command() should write a cuesheet.cue next to the source audio
whenever Chapter Forge has already detected chapters for that exact file, so
m4b-tool's merge picks them up and embeds real chapters into the output M4B.

cuesheet.cue is a build-time bridge file (m4b-tool's own required literal
filename), not a permanent artifact -- it's returned in temp_files so the
caller (run_m4b_worker) deletes it after the run, same as every other temp
file that function already produces.
"""
import json
import tempfile
import unittest
from pathlib import Path

import app.main as main_module
from app.main import M4BMetadataForm, M4BRunRequest, build_m4b_command


class BuildM4bCommandCuesheetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig_root = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        self.tmp.cleanup()

    def _make_request(self, input_path: Path, output_path: Path) -> M4BRunRequest:
        return M4BRunRequest(
            input_path=str(input_path),
            output_path=str(output_path),
            metadata=M4BMetadataForm(),
        )

    def test_writes_cuesheet_when_chapter_forge_data_exists(self):
        book_dir = self.root / "Author" / "Book"
        book_dir.mkdir(parents=True)
        audio = book_dir / "Book.mp3"
        audio.write_bytes(b"")
        # A single audio file alone in its folder uses a folder-level sidecar
        # (chapter_sidecar_path in app/chaptering.py), not a per-file one.
        sidecar = book_dir / "libraforge.json"
        sidecar.write_text(
            json.dumps(
                {
                    "chapter_forge": {
                        "chapters": [
                            {"id": 1, "title": "Chapter One", "start": 0.0, "end": 60.0},
                            {"id": 2, "title": "Chapter Two", "start": 60.0, "end": None},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        output = book_dir / "Book.m4b"

        cmd, temp_files = build_m4b_command(self._make_request(audio, output))

        cuesheet_path = book_dir / "cuesheet.cue"
        self.assertIn(cuesheet_path, temp_files)
        self.assertTrue(cuesheet_path.exists())
        content = cuesheet_path.read_text(encoding="utf-8")
        self.assertIn('TITLE "Chapter One"', content)
        self.assertIn("INDEX 01 00:00:000", content)
        self.assertIn('TITLE "Chapter Two"', content)
        self.assertIn("INDEX 01 01:00:000", content)

    def test_no_cuesheet_written_when_no_chapter_forge_data(self):
        book_dir = self.root / "Author" / "Other Book"
        book_dir.mkdir(parents=True)
        audio = book_dir / "Other Book.mp3"
        audio.write_bytes(b"")
        output = book_dir / "Other Book.m4b"

        cmd, temp_files = build_m4b_command(self._make_request(audio, output))

        self.assertFalse((book_dir / "cuesheet.cue").exists())
        self.assertEqual(temp_files, [])

    def test_preexisting_cuesheet_is_never_overwritten_or_queued_for_deletion(self):
        # "cuesheet.cue" is m4b-tool's own literal, documented filename for a
        # user-supplied cue sheet. run_m4b_worker deletes everything in
        # temp_files unconditionally after the run -- if we overwrote a real
        # user file here, it would get silently destroyed with no backup.
        book_dir = self.root / "Author" / "Book"
        book_dir.mkdir(parents=True)
        audio = book_dir / "Book.mp3"
        audio.write_bytes(b"")
        sidecar = book_dir / "libraforge.json"
        sidecar.write_text(
            json.dumps({"chapter_forge": {"chapters": [{"id": 1, "title": "Chapter One", "start": 0.0, "end": 60.0}]}}),
            encoding="utf-8",
        )
        cuesheet_path = book_dir / "cuesheet.cue"
        original_content = "FILE \"Book.mp3\" MP3\n  TRACK 01 AUDIO\n    TITLE \"user's own cue sheet\"\n"
        cuesheet_path.write_text(original_content, encoding="utf-8")
        output = book_dir / "Book.m4b"

        cmd, temp_files = build_m4b_command(self._make_request(audio, output))

        self.assertNotIn(cuesheet_path, temp_files)
        self.assertEqual(cuesheet_path.read_text(encoding="utf-8"), original_content)


if __name__ == "__main__":
    unittest.main()
