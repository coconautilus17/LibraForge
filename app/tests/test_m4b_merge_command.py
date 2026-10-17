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

    def test_the_base_command_merges_the_input_into_the_output_verbosely(self):
        cmd, _ = self.build()
        self.assertEqual(cmd[:3], ["m4b-tool", "merge", str(self.audio)])
        self.assertIn(f"--output-file={self.output}", cmd)
        self.assertIn("-v", cmd)

    def test_the_defaults_force_four_jobs_and_convert_with_the_requested_encoder_settings(self):
        cmd, _ = self.build()
        for arg in ("--force", "--jobs=4", "--audio-codec=libfdk_aac", "--audio-bitrate=128k", "--audio-samplerate=44100"):
            self.assertIn(arg, cmd)
        self.assertNotIn("--no-conversion", cmd)
        self.assertFalse([a for a in cmd if a.startswith("--audio-channels")])
        self.assertNotIn("--use-filenames-as-chapters", cmd)

    def test_the_genre_and_encoder_tags_are_always_added(self):
        cmd, _ = self.build()
        self.assertIn("--genre=Audiobook", cmd)
        self.assertIn("--encoded-by=LibraForge", cmd)

    def test_force_and_jobs_are_optional(self):
        cmd, _ = self.build(force=False, jobs=0)
        self.assertNotIn("--force", cmd)
        self.assertFalse([a for a in cmd if a.startswith("--jobs")])
        self.assertIn("--jobs=12", self.build(jobs=12)[0])

    def test_a_tmp_dir_is_passed_only_when_given(self):
        self.assertFalse([a for a in self.build()[0] if a.startswith("--tmp-dir")])
        self.assertIn(f"--tmp-dir={self.root}/work", self.build(temp_dir=self.root / "work")[0])

    def test_no_conversion_skips_the_encoder_options_entirely(self):
        cmd, _ = self.build(no_conversion=True, audio_codec="bogus", audio_bitrate="1k", audio_samplerate=1)
        self.assertIn("--no-conversion", cmd)
        self.assertFalse([a for a in cmd if a.startswith("--audio-")])

    def test_channels_are_passed_when_chosen(self):
        self.assertIn("--audio-channels=1", self.build(audio_channels=1)[0])
        self.assertIn("--audio-channels=2", self.build(audio_channels=2)[0])

    def test_unsupported_encoder_options_are_rejected_with_a_400(self):
        for field, value, message in (("audio_codec", "mp3", "codec"), ("audio_bitrate", "999k", "bitrate"),
                                      ("audio_samplerate", 12345, "sample rate"), ("audio_channels", 6, "channel")):
            with self.subTest(field=field), self.assertRaises(HTTPException) as caught:
                self.build(**{field: value})
            self.assertEqual(caught.exception.status_code, 400)
            self.assertIn(message, caught.exception.detail)

    def test_every_supported_option_is_accepted(self):
        for codec in main_module.M4B_AUDIO_CODECS:
            self.assertIn(f"--audio-codec={codec}", self.build(audio_codec=codec)[0])
        for rate in main_module.M4B_AUDIO_BITRATES:
            self.assertIn(f"--audio-bitrate={rate}", self.build(audio_bitrate=rate)[0])
        for rate in main_module.M4B_AUDIO_SAMPLERATES:
            self.assertIn(f"--audio-samplerate={rate}", self.build(audio_samplerate=rate)[0])

    def test_filenames_can_be_used_as_chapters(self):
        self.assertIn("--use-filenames-as-chapters", self.build(use_filenames_as_chapters=True)[0])

    def test_tags_come_from_the_metadata_form(self):
        meta = M4BMetadataForm(title="Unsouled", author="Will Wight", narrator="Travis Baldree", year="2016")
        cmd, _ = self.build(meta)
        for arg in ("--name=Unsouled", "--album=Unsouled", "--artist=Will Wight", "--albumartist=Will Wight",
                    "--writer=Travis Baldree", "--year=2016"):
            self.assertIn(arg, cmd)
        self.assertFalse([a for a in cmd if a.startswith(("--series=", "--series-part="))])

    def test_a_series_adds_its_tags_and_is_folded_into_the_title_by_the_metadata_normaliser(self):
        meta = M4BMetadataForm(title="Unsouled", series="Cradle", sequence="1")
        cmd, _ = self.build(meta)
        self.assertIn("--series=Cradle", cmd)
        self.assertIn("--series-part=1", cmd)
        self.assertIn("--name=Unsouled, Book 1", cmd)

    def test_blank_metadata_fields_add_no_tag_arguments(self):
        cmd, _ = self.build()
        for prefix in ("--name", "--album", "--artist", "--albumartist", "--writer", "--series", "--year", "--description",
                       "--longdesc", "--cover"):
            self.assertFalse([a for a in cmd if a.startswith(prefix + "=")], prefix)

    def test_a_long_summary_is_cut_for_the_short_description_but_kept_in_full_for_the_long_one(self):
        summary = "x" * 300
        cmd, _ = self.build(M4BMetadataForm(summary=summary))
        self.assertIn("--description=" + "x" * 240, cmd)
        self.assertNotIn("--description=" + "x" * 241, cmd)
        self.assertIn("--longdesc=" + summary, cmd)

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
