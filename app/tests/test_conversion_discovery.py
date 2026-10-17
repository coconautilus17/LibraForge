import unittest
from pathlib import Path

from app.conversion_discovery import conversion_candidate, summarize_audio_probes


class ConversionDiscoveryTests(unittest.TestCase):
    def test_multipart_returns_one_folder_candidate(self):
        folder = Path("/library/Book")
        files = [folder / "Chapter 1.opus", folder / "Chapter 2.opus"]

        candidate = conversion_candidate(
            source_path=files[0],
            display_path=folder,
            item_files=files,
            mode="multipart",
        )

        self.assertEqual(candidate["path"], str(folder))
        self.assertEqual(candidate["file_count"], 2)
        self.assertEqual(candidate["files"], [str(item) for item in files])
        self.assertEqual(candidate["formats"], ["opus"])
        self.assertTrue(candidate["is_grouped"])

    def test_loose_non_m4b_file_is_a_conversion_candidate(self):
        source = Path("/library/Book.mp3")

        candidate = conversion_candidate(
            source_path=source,
            display_path=source,
            item_files=[source],
            mode="non_m4b",
        )

        self.assertEqual(candidate["formats"], ["mp3"])
        self.assertFalse(candidate["is_grouped"])

    def test_existing_single_m4b_is_not_a_conversion_candidate(self):
        source = Path("/library/Book.m4b")

        candidate = conversion_candidate(
            source_path=source,
            display_path=source,
            item_files=[source],
            mode="non_m4b",
        )

        self.assertIsNone(candidate)

    def test_unsupported_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            conversion_candidate(
                source_path=Path("/library/Book.mp3"),
                display_path=Path("/library/Book.mp3"),
                item_files=[Path("/library/Book.mp3")],
                mode="unknown",
            )

    def test_consistent_aac_recommends_no_conversion(self):
        files = [Path("/library/1.m4a"), Path("/library/2.m4a")]
        probes = [
            {
                "probed": True,
                "codec": "aac",
                "codec_label": "AAC",
                "container": "QuickTime / MOV",
                "bitrate_kbps": bitrate,
                "channels": 2,
                "sample_rate_hz": 44100,
            }
            for bitrate in (96, 128)
        ]

        summary = summarize_audio_probes(files, probes)

        self.assertTrue(summary["no_conversion"]["recommended"])
        self.assertTrue(summary["mixed"]["bitrate"])
        self.assertFalse(summary["mixed"]["sample_rate"])

    def test_non_aac_recommends_conversion(self):
        summary = summarize_audio_probes(
            [Path("/library/book.mp3")],
            [{
                "probed": True,
                "codec": "mp3",
                "codec_label": "MP3",
                "container": "MP3",
                "bitrate_kbps": 128,
                "channels": 2,
                "sample_rate_hz": 44100,
            }],
        )

        self.assertFalse(summary["no_conversion"]["recommended"])
        self.assertEqual(summary["no_conversion"]["status"], "convert")

    def test_mixed_sample_rate_recommends_conversion(self):
        files = [Path("/library/1.m4a"), Path("/library/2.m4a")]
        probes = [
            {
                "probed": True,
                "codec": "aac",
                "codec_label": "AAC",
                "container": "QuickTime / MOV",
                "bitrate_kbps": 128,
                "channels": 2,
                "sample_rate_hz": sample_rate,
            }
            for sample_rate in (44100, 48000)
        ]

        summary = summarize_audio_probes(files, probes)

        self.assertFalse(summary["no_conversion"]["recommended"])
        self.assertTrue(summary["mixed"]["sample_rate"])


def _probe(**over):
    base = {"probed": True, "codec": "aac", "codec_label": "AAC", "container": "QuickTime / MOV",
            "bitrate_kbps": 128, "channels": 2, "sample_rate_hz": 44100}
    base.update(over)
    return base


def _files(n):
    return [Path(f"/library/{i}.m4a") for i in range(n)]


class MixedPropertyFlagTests(unittest.TestCase):
    """Each 'mixed' flag is true exactly when that one property takes more than one value."""

    def _mixed(self, field, values):
        probes = [_probe(**{field: v}) for v in values]
        return summarize_audio_probes(_files(len(probes)), probes)["mixed"]

    def test_one_distinct_value_is_not_mixed_and_two_are(self):
        for flag, field, one, two in (
            ("codec", "codec", ("aac", "aac"), ("aac", "mp3")),
            ("container", "container", ("MOV", "MOV"), ("MOV", "MP3")),
            ("bitrate", "bitrate_kbps", (64, 64), (64, 128)),
            ("channels", "channels", (2, 2), (1, 2)),
            ("sample_rate", "sample_rate_hz", (44100, 44100), (44100, 48000)),
        ):
            with self.subTest(flag=flag):
                self.assertIs(self._mixed(field, one)[flag], False)
                self.assertIs(self._mixed(field, two)[flag], True)

    def test_three_distinct_values_are_still_mixed(self):
        self.assertIs(self._mixed("channels", (1, 2, 6))["channels"], True)

    def test_mixed_properties_lists_only_the_differing_ones(self):
        probes = [_probe(bitrate_kbps=64, container="A"), _probe(bitrate_kbps=128, container="B")]
        summary = summarize_audio_probes(_files(2), probes)
        self.assertEqual(summary["mixed_properties"], ["container", "bitrate"])
        self.assertIs(summary["is_mixed"], True)

    def test_nothing_mixed_means_is_mixed_false(self):
        summary = summarize_audio_probes(_files(2), [_probe(), _probe()])
        self.assertEqual(summary["mixed_properties"], [])
        self.assertIs(summary["is_mixed"], False)

    def test_blank_and_missing_values_do_not_count_as_a_second_value(self):
        probes = [_probe(bitrate_kbps=128), _probe(bitrate_kbps=None), _probe(bitrate_kbps="")]
        summary = summarize_audio_probes(_files(3), probes)
        self.assertEqual(summary["bitrates_kbps"], [128])
        self.assertIs(summary["mixed"]["bitrate"], False)


class NoConversionRecommendationTests(unittest.TestCase):
    def _rec(self, files, probes):
        return summarize_audio_probes(files, probes)["no_conversion"]

    def test_no_files_or_no_readable_probe_is_unknown_and_not_recommended(self):
        for label, files, probes in (
            ("no files", [], []),
            ("none probed", _files(2), [_probe(probed=False), _probe(probed=False)]),
            ("no files but a probe", [], [_probe()]),
        ):
            with self.subTest(label):
                rec = self._rec(files, probes)
                self.assertEqual(rec["status"], "unknown")
                self.assertIs(rec["recommended"], False)

    def test_an_unprobed_file_among_probed_ones_blocks_the_recommendation(self):
        rec = self._rec(_files(2), [_probe(), _probe(probed=False)])
        self.assertEqual(rec["status"], "convert")
        self.assertIs(rec["recommended"], False)
        self.assertIn("missing or unreadable", rec["reason"])

    def test_a_probe_missing_codec_channels_or_sample_rate_blocks_it(self):
        for field in ("codec", "channels", "sample_rate_hz"):
            with self.subTest(field=field):
                rec = self._rec(_files(2), [_probe(), _probe(**{field: None})])
                self.assertEqual(rec["status"], "convert")
                self.assertIn("missing or unreadable", rec["reason"])

    def test_non_aac_names_the_codec_using_the_label(self):
        rec = self._rec(_files(1), [_probe(codec="mp3", codec_label="MP3 (MPEG)")])
        self.assertEqual(rec["status"], "convert")
        self.assertIn("The source codec is MP3 (MPEG);", rec["reason"])

    def test_non_aac_without_labels_falls_back_to_the_upper_cased_codec(self):
        rec = self._rec(_files(1), [_probe(codec="opus", codec_label=None)])
        self.assertIn("The source codec is OPUS;", rec["reason"])

    def test_two_codecs_name_both_and_convert(self):
        rec = self._rec(_files(2), [_probe(codec="aac", codec_label="AAC"), _probe(codec="mp3", codec_label="MP3")])
        self.assertEqual(rec["status"], "convert")
        self.assertIn("AAC, MP3", rec["reason"])

    def test_mixed_sample_rate_only_names_sample_rates(self):
        rec = self._rec(_files(2), [_probe(sample_rate_hz=44100), _probe(sample_rate_hz=48000)])
        self.assertEqual(rec["status"], "convert")
        self.assertIn("mixed sample rates,", rec["reason"])
        self.assertNotIn("channel layouts", rec["reason"])

    def test_mixed_channels_only_names_channel_layouts(self):
        rec = self._rec(_files(2), [_probe(channels=1), _probe(channels=2)])
        self.assertEqual(rec["status"], "convert")
        self.assertIn("mixed channel layouts,", rec["reason"])
        self.assertNotIn("sample rates", rec["reason"])

    def test_mixed_both_names_both(self):
        rec = self._rec(_files(2), [_probe(channels=1, sample_rate_hz=44100), _probe(channels=2, sample_rate_hz=48000)])
        self.assertIn("mixed sample rates and channel layouts", rec["reason"])

    def test_matching_aac_is_copy_and_recommended(self):
        rec = self._rec(_files(2), [_probe(), _probe()])
        self.assertEqual(rec["status"], "copy")
        self.assertIs(rec["recommended"], True)
        self.assertEqual(rec["label"], "No conversion recommended")
        self.assertNotIn("Bitrates vary", rec["reason"])

    def test_varying_bitrates_are_noted_but_still_recommended(self):
        rec = self._rec(_files(2), [_probe(bitrate_kbps=64), _probe(bitrate_kbps=128)])
        self.assertIs(rec["recommended"], True)
        self.assertIn("Bitrates vary", rec["reason"])

    def test_only_the_copy_case_is_ever_recommended(self):
        cases = [
            ([], []),
            (_files(1), [_probe(probed=False)]),
            (_files(2), [_probe(), _probe(codec=None)]),
            (_files(1), [_probe(codec="mp3")]),
            (_files(2), [_probe(channels=1), _probe(channels=2)]),
        ]
        for files, probes in cases:
            self.assertIs(self._rec(files, probes)["recommended"], False)


class ConversionCandidateAudioSummaryTests(unittest.TestCase):
    def _candidate(self, **kw):
        return conversion_candidate(source_path=Path("/lib/b/1.mp3"), display_path=Path("/lib/b/1.mp3"),
                                    item_files=[Path("/lib/b/1.mp3")], mode="non_m4b", **kw)

    def test_the_audio_summary_passed_in_is_carried_through(self):
        self.assertEqual(self._candidate(audio_summary={"file_count": 1})["audio_summary"], {"file_count": 1})

    def test_no_audio_summary_gives_an_empty_dict(self):
        self.assertEqual(self._candidate()["audio_summary"], {})
        self.assertEqual(self._candidate(audio_summary=None)["audio_summary"], {})


class FixerCopyParityTests(unittest.TestCase):
    """The Metadata Fixer script carries its own copy of the probe summary
    (summarize_audio_stream_properties). It must keep answering exactly like the
    shared app.conversion_discovery.summarize_audio_probes."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        import sys
        import types
        try:
            import audible  # noqa: F401
        except ModuleNotFoundError:
            stub = types.ModuleType("audible")
            stub.Client = type("Client", (), {})
            stub.Authenticator = type("Authenticator", (), {})
            sys.modules["audible"] = stub
        path = Path(__file__).parents[2] / "scripts" / "audible-metadata-fixer-v5.py"
        spec = importlib.util.spec_from_file_location("fixer_summary_parity", path)
        cls.fixer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.fixer
        spec.loader.exec_module(cls.fixer)

    SCENARIOS = {
        "no files": ([], []),
        "nothing probed": (2, [{"probed": False}, {"probed": False}]),
        "one unprobed": (2, [_probe(), {"probed": False}]),
        "missing channels": (2, [_probe(), _probe(channels=None)]),
        "mp3": (1, [_probe(codec="mp3", codec_label="MP3")]),
        "mp3 and aac": (2, [_probe(), _probe(codec="mp3", codec_label="MP3")]),
        "mixed rates": (2, [_probe(sample_rate_hz=44100), _probe(sample_rate_hz=48000)]),
        "mixed layouts": (2, [_probe(channels=1), _probe(channels=2)]),
        "mixed both": (2, [_probe(channels=1, sample_rate_hz=44100), _probe(channels=2, sample_rate_hz=48000)]),
        "matching": (2, [_probe(), _probe()]),
        "bitrates vary": (2, [_probe(bitrate_kbps=64), _probe(bitrate_kbps=128)]),
    }

    def test_every_scenario_gets_the_same_summary_from_both_implementations(self):
        from unittest import mock
        for name, (count, probes) in self.SCENARIOS.items():
            with self.subTest(name):
                files = [Path(f"/lib/{i}.m4a") for i in range(count if isinstance(count, int) else len(probes))]
                if not probes:
                    files = []
                expected = summarize_audio_probes(files, probes)
                with mock.patch.object(self.fixer, "probe_audio_stream_properties", side_effect=list(probes)):
                    got = self.fixer.summarize_audio_stream_properties(files)
                self.assertEqual(got, expected)


if __name__ == "__main__":
    unittest.main()
