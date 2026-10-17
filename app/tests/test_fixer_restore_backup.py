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


@needs_ffmpeg
class Mp4RestoreTests(RestoreFixture):
    def prepared(self):
        from mutagen.mp4 import MP4, MP4Cover
        source = self.silent("book.m4b", "aac")
        audio = MP4(str(source))
        audio["\xa9nam"] = ["Applied Title"]
        audio["\xa9ART"] = ["Applied Author"]
        audio["----:com.apple.iTunes:ASIN"] = [b"B0APPLIED1"]
        audio["covr"] = [MP4Cover(b"\xff\xd8\xff" + b"0" * 20, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
        self.write_backup(source)
        return source

    def test_the_original_tags_replace_the_applied_ones(self):
        from mutagen.mp4 import MP4
        source = self.prepared()
        FIXER.mutagen_restore_metadata_from_backup(source)
        tags = MP4(str(source)).tags
        self.assertEqual(tags["\xa9nam"], ["Original Title"])
        self.assertEqual(tags["\xa9ART"], ["Original Author"])
        self.assertEqual(tags["aART"], ["Original Author"])
        self.assertEqual(tags["\xa9alb"], ["Original Album"])
        self.assertEqual(tags["\xa9grp"], ["Original Series"])
        self.assertEqual(tags["\xa9wrt"], ["Original Narrator"])
        self.assertEqual(tags["\xa9day"], ["2001"])
        self.assertEqual(tags["\xa9gen"], ["Fantasy"])
        self.assertEqual(tags["\xa9cmt"], ["original comment"])
        self.assertEqual(tags["trkn"], [(4, 0)])

    def test_tags_the_fixer_added_are_removed_but_the_cover_is_kept(self):
        from mutagen.mp4 import MP4
        source = self.prepared()
        FIXER.mutagen_restore_metadata_from_backup(source)
        tags = MP4(str(source)).tags
        self.assertNotIn("----:com.apple.iTunes:ASIN", tags)
        self.assertEqual(len(tags["covr"]), 1)

    def test_the_album_falls_back_to_the_title_and_blank_fields_are_not_written(self):
        from mutagen.mp4 import MP4
        source = self.silent("b.m4b", "aac")
        self.write_backup(source, {"title": "Only Title"})
        FIXER.mutagen_restore_metadata_from_backup(source)
        tags = MP4(str(source)).tags
        self.assertEqual((tags["\xa9nam"], tags["\xa9alb"]), (["Only Title"], ["Only Title"]))
        for key in ("\xa9ART", "aART", "\xa9grp", "\xa9wrt", "\xa9day", "\xa9gen", "\xa9cmt", "trkn"):
            self.assertNotIn(key, tags)

    def test_the_record_is_marked_restored_and_not_manually_applied(self):
        source = self.prepared()
        lf = FIXER.mutagen_restore_metadata_from_backup(source)
        marker = json.loads(lf.read_text())["marker"]
        self.assertEqual((marker["applied"], marker["manually_applied"]), (False, False))
        self.assertIn("restored_at", marker)

    def test_the_returned_path_is_the_sidecar_that_held_the_backup(self):
        source = self.prepared()
        self.assertEqual(FIXER.mutagen_restore_metadata_from_backup(source), source.with_name("book.m4b.libraforge.json"))

    def test_no_backup_data_is_an_error_and_the_file_is_untouched(self):
        from mutagen.mp4 import MP4
        source = self.silent("nb.m4b", "aac")
        audio = MP4(str(source))
        audio["\xa9nam"] = ["Keep Me"]
        audio.save()
        with self.assertRaises(FileNotFoundError):
            FIXER.mutagen_restore_metadata_from_backup(source)
        self.assertEqual(MP4(str(source)).tags["\xa9nam"], ["Keep Me"])


@needs_ffmpeg
class Mp3RestoreTests(RestoreFixture):
    def test_original_id3_text_frames_replace_applied_ones_and_covers_stay(self):
        from mutagen.id3 import APIC, ID3, TCON, TIT2, TPE1, TXXX
        source = self.silent("book.mp3", "libmp3lame")
        tags = ID3()
        tags.add(TIT2(encoding=3, text=["Applied Title"]))
        tags.add(TPE1(encoding=3, text=["Applied Author"]))
        tags.add(TXXX(encoding=3, desc="ASIN", text=["B0APPLIED1"]))
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="c", data=b"\xff\xd8\xff" + b"0" * 10))
        tags.save(str(source))
        self.write_backup(source)
        FIXER.mutagen_restore_metadata_from_backup(source)
        restored = ID3(str(source))
        self.assertEqual(str(restored["TIT2"]), "Original Title")
        self.assertEqual(str(restored["TPE1"]), "Original Author")
        self.assertEqual(str(restored["TPE2"]), "Original Author")
        self.assertEqual(str(restored["TALB"]), "Original Album")
        self.assertEqual(str(restored["TCOM"]), "Original Narrator")
        self.assertEqual(str(restored["TCON"]), "Fantasy")
        self.assertEqual(str(restored["TRCK"]), "4")
        self.assertEqual(len(restored.getall("TXXX")), 0)
        self.assertEqual(len(restored.getall("APIC")), 1)

    def test_a_file_with_no_id3_header_is_tagged_from_the_backup(self):
        from mutagen.id3 import ID3
        source = self.silent("plain.mp3", "libmp3lame")
        self.write_backup(source, {"title": "Fresh"})
        FIXER.mutagen_restore_metadata_from_backup(source)
        self.assertEqual(str(ID3(str(source))["TIT2"]), "Fresh")


class UnsupportedAndOrchestrationTests(RestoreFixture):
    def test_an_extension_mutagen_cannot_write_is_an_error(self):
        source = self.folder / "book.flac"
        source.write_bytes(b"x")
        self.write_backup(source)
        with self.assertRaisesRegex(RuntimeError, "does not support this extension: .flac"):
            FIXER.mutagen_restore_metadata_from_backup(source)

    def test_the_restore_loop_counts_restored_and_skipped_books(self):
        from unittest import mock
        ok, no_backup = self.folder / "ok.m4b", self.folder / "nb.m4b"
        for path in (ok, no_backup):
            path.write_bytes(b"x")
        self.write_backup(ok)
        with mock.patch.object(FIXER, "restore_metadata_from_backup", side_effect=lambda source, writer="auto": source), \
             mock.patch("builtins.print"):
            result = FIXER.restore_metadata_backups([ok, no_backup])
        self.assertEqual(result, (1, 1, 0))

    @unittest.expectedFailure
    def test_a_failing_restore_should_be_counted_and_the_loop_should_continue(self):
        # KNOWN BUG, issue #379: the except branch uses an undefined name `manual_review`,
        # so the first failure raises NameError and ends the whole restore run.
        from unittest import mock
        ok, broken = self.folder / "ok.m4b", self.folder / "bad.m4b"
        for path in (ok, broken):
            path.write_bytes(b"x")
            self.write_backup(path)

        def fake_restore(source, writer="auto"):
            if source == broken:
                raise RuntimeError("boom")
            return source

        with mock.patch.object(FIXER, "restore_metadata_from_backup", side_effect=fake_restore), mock.patch("builtins.print"):
            self.assertEqual(FIXER.restore_metadata_backups([broken, ok]), (1, 0, 1))

    def test_a_backup_with_empty_format_tags_counts_as_no_backup(self):
        from unittest import mock
        path = self.folder / "e.m4b"
        path.write_bytes(b"x")
        self.write_backup(path, tags={})
        with mock.patch.object(FIXER, "restore_metadata_from_backup") as restore, mock.patch("builtins.print"):
            self.assertEqual(FIXER.restore_metadata_backups([path]), (0, 1, 0))
        restore.assert_not_called()

    def test_auto_mode_falls_back_to_ffmpeg_when_mutagen_fails_but_mutagen_mode_raises(self):
        from unittest import mock
        path = self.folder / "a.m4b"
        path.write_bytes(b"x")
        with mock.patch.object(FIXER, "mutagen_restore_metadata_from_backup", side_effect=RuntimeError("no")), \
             mock.patch.object(FIXER, "ffmpeg_restore_metadata_from_backup", return_value="ff") as ffmpeg, mock.patch("builtins.print"):
            self.assertEqual(FIXER.restore_metadata_from_backup(path, writer="auto"), "ff")
            with self.assertRaises(RuntimeError):
                FIXER.restore_metadata_from_backup(path, writer="mutagen")
        ffmpeg.assert_called_once()

    def test_the_ffmpeg_writer_is_used_directly_when_asked_or_when_the_format_is_not_mutagen_writable(self):
        from unittest import mock
        path = self.folder / "a.m4b"
        path.write_bytes(b"x")
        with mock.patch.object(FIXER, "mutagen_restore_metadata_from_backup") as mutagen, \
             mock.patch.object(FIXER, "ffmpeg_restore_metadata_from_backup", return_value="ff"):
            self.assertEqual(FIXER.restore_metadata_from_backup(path, writer="ffmpeg"), "ff")
            self.assertEqual(FIXER.restore_metadata_from_backup(self.folder / "x.flac", writer="auto"), "ff")
        mutagen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
