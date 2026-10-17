"""probe_file (one ffprobe call -> tags + minutes) and read_tags_and_duration
(which source the fixer reads a file's tags from: live probe, folder file cache,
or the per-file backup)."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_probe_and_cache", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


def completed(payload, returncode=0):
    return types.SimpleNamespace(stdout=json.dumps(payload) if not isinstance(payload, str) else payload, returncode=returncode)


class ProbeFileTests(unittest.TestCase):
    PATH = Path("/lib/a.m4b")

    def probe(self, result=None, side_effect=None):
        with mock.patch.object(FIXER.subprocess, "run", return_value=result, side_effect=side_effect) as run, \
             mock.patch("builtins.print"):
            return FIXER.probe_file(self.PATH), run

    def test_container_tags_are_lower_cased_and_the_duration_is_in_minutes(self):
        (tags, minutes), run = self.probe(completed({"format": {"tags": {"Title": " T ", "ARTIST": "A"}, "duration": "600"}}))
        self.assertEqual((tags, minutes), ({"title": "T", "artist": "A"}, 10.0))
        self.assertEqual(run.call_args.args[0][0], "ffprobe")
        self.assertEqual(run.call_args.args[0][-1], str(self.PATH))

    def test_stream_tags_fill_in_for_formats_that_keep_tags_there(self):
        data = {"format": {"tags": {"title": "From Container"}, "duration": "60"},
                "streams": [{"tags": {"Title": "From Stream", "Comment": "only on stream"}}]}
        (tags, _), _ = self.probe(completed(data))
        self.assertEqual(tags, {"title": "From Container", "comment": "only on stream"})

    def test_blank_tag_values_are_dropped(self):
        (tags, _), _ = self.probe(completed({"format": {"tags": {"title": "  ", "artist": "A", "empty": ""}, "duration": "1"}}))
        self.assertEqual(tags, {"artist": "A"})

    def test_a_missing_zero_or_garbage_duration_is_none(self):
        for fmt in ({}, {"duration": "0"}, {"duration": "-5"}, {"duration": "abc"}, {"duration": None}):
            with self.subTest(fmt=fmt):
                (_, minutes), _ = self.probe(completed({"format": fmt}))
                self.assertIsNone(minutes)

    def test_a_failing_or_unparseable_ffprobe_gives_nothing(self):
        for result in (completed({"format": {}}, returncode=1), completed("not json")):
            (tags, minutes), _ = self.probe(result)
            self.assertEqual((tags, minutes), ({}, None))

    def test_a_timeout_is_retried_with_the_next_timeout_and_gives_up_after_the_last(self):
        timeouts = FIXER.PROBE_TIMEOUTS_SECONDS
        ok = completed({"format": {"tags": {"title": "T"}, "duration": "60"}})
        effects = [subprocess.TimeoutExpired("ffprobe", timeouts[0]), ok]
        (tags, minutes), run = self.probe(side_effect=effects)
        self.assertEqual((tags, minutes), ({"title": "T"}, 1.0))
        self.assertEqual([c.kwargs["timeout"] for c in run.call_args_list], list(timeouts[:2]))
        always = [subprocess.TimeoutExpired("ffprobe", t) for t in timeouts]
        (tags, minutes), run = self.probe(side_effect=always)
        self.assertEqual((tags, minutes), ({}, None))
        self.assertEqual(run.call_count, len(timeouts))

    def test_the_two_convenience_readers_return_one_half_each(self):
        with mock.patch.object(FIXER, "probe_file", return_value=({"title": "T"}, 3.0)):
            self.assertEqual(FIXER.read_file_tags(self.PATH), {"title": "T"})
            self.assertEqual(FIXER.read_file_duration_minutes(self.PATH), 3.0)


class SynthesizeAppliedTagsTests(unittest.TestCase):
    def test_applied_metadata_becomes_probe_style_tags(self):
        got = FIXER._synthesize_applied_tags({"title": "T", "author": "A", "series": "S", "narrator": "N", "year": "2020",
                                              "asin": "B0X", "sequence": "3"})
        self.assertEqual(got, {"title": "T", "album": "T", "artist": "A", "album_artist": "A", "grouping": "S",
                               "composer": "N", "date": "2020", "asin": "B0X", "track": "3"})

    def test_blank_fields_are_left_out(self):
        self.assertEqual(FIXER._synthesize_applied_tags({"title": " ", "author": "", "sequence": None}), {})


class ReadTagsAndDurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.file = self.folder / "book.m4b"
        self.file.write_bytes(b"x")
        patcher = mock.patch.object(FIXER, "probe_file", return_value=({"title": "live"}, 99.0))
        self.probe = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write_folder(self, payload):
        (self.folder / "libraforge.json").write_text(json.dumps(payload))

    def write_file_lf(self, payload):
        (self.folder / "book.m4b.libraforge.json").write_text(json.dumps(payload))

    def test_with_nothing_cached_the_file_is_probed_live(self):
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "live"}, 99.0, True))

    def test_reprobe_ignores_every_cache(self):
        self.write_file_lf({"backup": {"duration_minutes": 5, "format_tags": {"title": "cached"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file, reprobe=True), ({"title": "live"}, 99.0, True))

    def test_a_backup_supplies_applied_tags_first_then_the_original_format_tags(self):
        self.write_file_lf({"backup": {"duration_minutes": 5, "applied_tags": {"title": "applied"}, "format_tags": {"title": "original"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "applied"}, 5.0, False))
        self.write_file_lf({"backup": {"duration_minutes": 5, "format_tags": {"title": "original"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "original"}, 5.0, False))
        self.probe.assert_not_called()

    def test_use_backup_tags_returns_the_original_pre_apply_tags(self):
        self.write_file_lf({"backup": {"duration_minutes": 5, "applied_tags": {"title": "applied"}, "format_tags": {"title": "original"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file, use_backup_tags=True), ({"title": "original"}, 5.0, False))

    def test_an_empty_or_durationless_backup_is_not_trusted(self):
        self.write_file_lf({"backup": {"duration_minutes": 5, "format_tags": {}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "live"}, 99.0, True))
        self.write_file_lf({"backup": {"format_tags": {"title": "original"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "live"}, 99.0, True))

    def test_a_zero_duration_backup_is_still_a_valid_cache_entry(self):
        self.write_file_lf({"backup": {"duration_minutes": 0, "format_tags": {"title": "original"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "original"}, 0.0, False))

    def test_a_grouped_books_file_cache_wins_and_uses_the_applied_book_tags(self):
        self.write_folder({"file_cache": {str(self.file): {"duration_minutes": 7, "format_tags": {"title": "original"}}},
                           "sidecar": {"book": {"title": "Applied", "author": "A"}}})
        tags, minutes, live = FIXER.read_tags_and_duration(self.file)
        self.assertEqual((tags["title"], tags["artist"], minutes, live), ("Applied", "A", 7.0, False))
        self.assertEqual(FIXER.read_tags_and_duration(self.file, use_backup_tags=True), ({"title": "original"}, 7.0, False))

    def test_the_file_cache_falls_back_to_its_format_tags_without_a_sidecar_book(self):
        self.write_folder({"file_cache": {str(self.file): {"duration_minutes": 7, "format_tags": {"title": "original"}}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "original"}, 7.0, False))

    def test_a_file_cache_entry_for_another_file_is_ignored(self):
        self.write_folder({"file_cache": {"/elsewhere/x.m4b": {"duration_minutes": 7, "format_tags": {"title": "other"}}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "live"}, 99.0, True))

    def test_a_corrupt_folder_sidecar_falls_through_to_the_probe(self):
        (self.folder / "libraforge.json").write_text("{bad")
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "live"}, 99.0, True))


if __name__ == "__main__":
    unittest.main()
