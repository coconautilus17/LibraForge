"""Marker helpers of the Metadata Fixer: rebuilding a match from the stored
marker, the fast-skip rule for already-applied books, and what a marker claims
was written under each field policy."""
import importlib.util
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

SPEC = importlib.util.spec_from_file_location("fixer_marker_helpers", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


class RealAsinTests(unittest.TestCase):
    def test_a_stored_asin_is_upper_cased_and_trimmed(self):
        self.assertEqual(FIXER.marker_real_asin({"audible": {"asin": " b0abc12345 "}}), "B0ABC12345")

    def test_missing_blank_and_placeholder_asins_are_empty(self):
        for marker in ({}, {"audible": {}}, {"audible": {"asin": ""}}, {"audible": {"asin": "NOREALASIN"}},
                       {"audible": {"asin": "norealasin"}}, {"audible": None}):
            with self.subTest(marker=marker):
                self.assertEqual(FIXER.marker_real_asin(marker), "")


class MetadataFromMarkerTests(unittest.TestCase):
    MARKER = {"edit_mode": "series_only", "duration": {"status": "perfect"},
              "audible": {"asin": "b0x", "title": "Audible Title", "chosen_title": "Chosen", "subtitle": "Sub", "author": "A",
                          "narrator": "N", "series": "S", "sequence": "3", "year": "2020", "genre": "Fantasy", "summary": "sum",
                          "isbn": "978", "publisher": "Pub", "cover_url": "http://c", "duration_minutes": 600,
                          "number_candidates": ["3"]}}

    def test_every_stored_field_is_restored(self):
        got = FIXER.metadata_from_marker(self.MARKER)
        self.assertEqual((got["asin"], got["title"], got["audible_title"], got["subtitle"]), ("B0X", "Chosen", "Audible Title", "Sub"))
        self.assertEqual((got["author"], got["narrator"], got["series"], got["sequence"], got["audible_sequence"]),
                         ("A", "N", "S", "3", "3"))
        self.assertEqual((got["year"], got["genre"], got["summary"], got["isbn"], got["publisher"], got["cover_url"]),
                         ("2020", "Fantasy", "sum", "978", "Pub", "http://c"))
        self.assertEqual((got["audible_duration_minutes"], got["audible_number_candidates"]), (600, ["3"]))
        self.assertEqual((got["edit_mode"], got["duration"]), ("series_only", {"status": "perfect"}))

    def test_the_chosen_title_beats_the_audible_title_and_either_is_enough(self):
        marker = {"audible": {"title": "Audible Title"}}
        self.assertEqual(FIXER.metadata_from_marker(marker)["title"], "Audible Title")

    def test_an_empty_marker_gives_empty_strings_lists_and_the_defaults(self):
        got = FIXER.metadata_from_marker({})
        for key in ("asin", "title", "audible_title", "subtitle", "author", "narrator", "series", "sequence", "year", "genre",
                    "summary", "isbn", "publisher", "cover_url"):
            self.assertEqual(got[key], "", key)
        self.assertEqual((got["audible_number_candidates"], got["duration"], got["edit_mode"]), ([], {}, "full"))
        self.assertIsNone(got["audible_duration_minutes"])

    def test_the_legacy_mode_key_is_used_when_there_is_no_edit_mode(self):
        self.assertEqual(FIXER.metadata_from_marker({"mode": "series_only"})["edit_mode"], "series_only")
        self.assertEqual(FIXER.metadata_from_marker({"mode": "x", "edit_mode": "full"})["edit_mode"], "full")

    def test_a_placeholder_asin_is_not_restored(self):
        self.assertEqual(FIXER.metadata_from_marker({"audible": {"asin": "NOREALASIN"}})["asin"], "")


class MarkerSkipCleanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "book.m4b"
        self.source.write_bytes(b"x")
        self.meta = self.root / "metadata.json"
        self.meta.write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def clean(self, marker, alone=False, meta=None):
        return FIXER.marker_skip_is_clean(self.source, marker, alone, meta or self.meta)

    def test_a_recorded_asin_with_metadata_json_present_is_clean(self):
        marker = {"audible": {"asin": "B0X"}, "written_fields": ["asin", "title"]}
        self.assertIs(self.clean(marker), True)

    def test_a_real_asin_that_was_never_recorded_as_written_needs_repair(self):
        self.assertIs(self.clean({"audible": {"asin": "B0X"}, "written_fields": ["title"]}), False)
        self.assertIs(self.clean({"audible": {"asin": "B0X"}}), False)

    def test_no_real_asin_means_nothing_to_write(self):
        self.assertIs(self.clean({"audible": {"asin": "NOREALASIN"}}), True)
        self.assertIs(self.clean({}), True)

    def test_missing_metadata_json_needs_repair(self):
        self.assertIs(self.clean({}, meta=self.root / "missing.json"), False)

    def test_a_lone_files_sidecar_must_already_be_consolidated(self):
        sidecar = self.source.with_name(f"{self.source.name}{FIXER.LIBRAFORGE_SUFFIX}")
        sidecar.write_text("{}")
        self.assertIs(self.clean({}, alone=True), False)
        self.assertIs(self.clean({}, alone=False), True)
        sidecar.unlink()
        self.assertIs(self.clean({}, alone=True), True)


class MarkerSurvivorValueTests(unittest.TestCase):
    def value(self, policy, metadata, current, conditional):
        return FIXER._marker_survivor_value(policy, metadata, current, conditional)

    def test_a_written_value_is_always_what_survives(self):
        for policy in ("fill", "overwrite", "legacy"):
            for conditional in (True, False):
                self.assertEqual(self.value(policy, "new", "old", conditional), "new")

    def test_a_blank_new_value_under_fill_leaves_the_current_one(self):
        self.assertEqual(self.value("fill", "", "old", True), "old")
        self.assertEqual(self.value("fill", "", "old", False), "old")
        self.assertEqual(self.value("fill", "", None, False), "")

    def test_a_blank_new_value_under_overwrite_clears_the_field(self):
        self.assertEqual(self.value("overwrite", "", "old", True), "")

    def test_legacy_keeps_the_current_value_only_for_the_conditionally_written_fields(self):
        self.assertEqual(self.value("legacy", "", "old", True), "old")
        self.assertEqual(self.value("legacy", "", "old", False), "")
        self.assertEqual(self.value("legacy", "", None, True), "")


class ProbeAudioStreamPropertiesTests(unittest.TestCase):
    def probe(self, payload):
        import json
        from unittest import mock
        result = types.SimpleNamespace(stdout=json.dumps(payload))
        with mock.patch.object(FIXER.subprocess, "run", return_value=result):
            return FIXER.probe_audio_stream_properties(Path("/lib/a.m4b"))

    def test_stream_and_format_fields_are_mapped(self):
        got = self.probe({"streams": [{"codec_name": "AAC", "codec_long_name": "AAC (Advanced Audio Coding)", "bit_rate": "64000",
                                       "channels": 2, "sample_rate": "44100"}],
                          "format": {"format_long_name": "QuickTime / MOV", "bit_rate": "70000"}})
        self.assertEqual(got, {"probed": True, "codec": "aac", "codec_label": "AAC (Advanced Audio Coding)",
                               "container": "QuickTime / MOV", "bitrate_kbps": 64, "channels": 2, "sample_rate_hz": 44100})

    def test_the_stream_bitrate_wins_over_the_format_bitrate_and_the_format_is_the_fallback(self):
        self.assertEqual(self.probe({"streams": [{"codec_name": "aac", "bit_rate": "128000"}], "format": {"bit_rate": "999000"}})["bitrate_kbps"], 128)
        self.assertEqual(self.probe({"streams": [{"codec_name": "aac"}], "format": {"bit_rate": "96000"}})["bitrate_kbps"], 96)
        self.assertIsNone(self.probe({"streams": [{"codec_name": "aac"}], "format": {}})["bitrate_kbps"])

    def test_the_label_falls_back_to_the_upper_cased_codec_and_gets_a_profile_suffix(self):
        self.assertEqual(self.probe({"streams": [{"codec_name": "mp3"}]})["codec_label"], "MP3")
        got = self.probe({"streams": [{"codec_name": "aac", "codec_long_name": "AAC", "profile": "LC"}]})
        self.assertEqual(got["codec_label"], "AAC (LC)")

    def test_a_profile_already_in_the_label_is_not_repeated(self):
        got = self.probe({"streams": [{"codec_name": "aac", "codec_long_name": "AAC (LC)", "profile": "LC"}]})
        self.assertEqual(got["codec_label"], "AAC (LC)")

    def test_the_container_prefers_the_long_name_then_the_short_one(self):
        self.assertEqual(self.probe({"streams": [{}], "format": {"format_name": "mov,mp4", "format_long_name": "QuickTime"}})["container"], "QuickTime")
        self.assertEqual(self.probe({"streams": [{}], "format": {"format_name": "mov,mp4"}})["container"], "mov,mp4")

    def test_a_missing_stream_is_not_probed(self):
        self.assertIs(self.probe({"streams": []})["probed"], False)
        self.assertIs(self.probe({})["probed"], False)

    def test_zero_channels_or_rate_become_none(self):
        got = self.probe({"streams": [{"codec_name": "aac", "channels": 0, "sample_rate": 0}]})
        self.assertEqual((got["channels"], got["sample_rate_hz"]), (None, None))

    def test_a_timeout_or_garbage_output_is_an_unprobed_result(self):
        from unittest import mock
        with mock.patch.object(FIXER.subprocess, "run", side_effect=FIXER.subprocess.TimeoutExpired("ffprobe", 30)):
            self.assertEqual(FIXER.probe_audio_stream_properties(Path("a.m4b")), {"probed": False})
        with mock.patch.object(FIXER.subprocess, "run", return_value=types.SimpleNamespace(stdout="not json")):
            self.assertEqual(FIXER.probe_audio_stream_properties(Path("a.m4b")), {"probed": False})


if __name__ == "__main__":
    unittest.main()
