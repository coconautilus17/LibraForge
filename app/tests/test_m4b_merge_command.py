"""The exact m4b-tool merge command LibraForge builds for an M4B request: output
and tmp paths, conversion options and their allow-lists, tag arguments and the
cover temp file. Each choice the user makes on the M4B page must reach m4b-tool."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.main as main_module
from fastapi import HTTPException

from app.main import M4BMetadataForm, M4BRunRequest, build_m4b_command


class M4bMergeCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        patcher = mock.patch.object(main_module, "AUDIOBOOKS_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.book = self.root / "Author" / "Book"
        self.book.mkdir(parents=True)
        self.audio = self.book / "Book.mp3"
        self.audio.write_bytes(b"")
        self.output = self.book / "Book.m4b"
        self.temp_files = []

    def build(self, metadata=None, temp_dir=None, **over):
        req = M4BRunRequest(input_path=str(self.audio), output_path=str(self.output),
                            metadata=metadata or M4BMetadataForm(), **over)
        cmd, temp_files = build_m4b_command(req, temp_dir)
        for path in temp_files:
            self.addCleanup(lambda p=path: p.exists() and p.unlink())
        return cmd, temp_files

    def test_unsupported_encoder_options_are_rejected_with_a_400(self):
        for field, value, message in (("audio_codec", "mp3", "codec"), ("audio_bitrate", "999k", "bitrate"),
                                      ("audio_samplerate", 12345, "sample rate"), ("audio_channels", 6, "channel")):
            with self.subTest(field=field), self.assertRaises(HTTPException) as caught:
                self.build(**{field: value})
            self.assertEqual(caught.exception.status_code, 400)
            self.assertIn(message, caught.exception.detail)

    def test_tags_come_from_the_metadata_form(self):
        meta = M4BMetadataForm(title="Unsouled", author="Will Wight", narrator="Travis Baldree", year="2016")
        cmd, _ = self.build(meta)
        for arg in ("--name=Unsouled", "--album=Unsouled", "--artist=Will Wight", "--albumartist=Will Wight",
                    "--writer=Travis Baldree", "--year=2016"):
            self.assertIn(arg, cmd)
        self.assertFalse([a for a in cmd if a.startswith(("--series=", "--series-part="))])

    def test_a_cover_is_downloaded_to_a_temp_file_with_the_right_extension_and_returned_for_cleanup(self):
        jpeg = b"\xff\xd8\xff" + b"0" * 10
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 10
        with mock.patch.object(main_module, "read_cover_url_bytes", return_value=jpeg):
            cmd, temp_files = self.build(M4BMetadataForm(cover_url="https://x.test/cover.JPG?size=large"))
        cover = [a for a in cmd if a.startswith("--cover=")][0]
        self.assertTrue(cover.endswith(".jpg"))
        self.assertIn(Path(cover[len("--cover="):]), temp_files)
        self.assertEqual(Path(cover[len("--cover="):]).read_bytes(), jpeg)
        with mock.patch.object(main_module, "read_cover_url_bytes", return_value=png):
            cmd, _ = self.build(M4BMetadataForm(cover_url="https://x.test/cover.png"))
        self.assertTrue([a for a in cmd if a.startswith("--cover=")][0].endswith(".png"))


if __name__ == "__main__":
    unittest.main()
