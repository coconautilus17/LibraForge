"""Marker helpers of the Metadata Fixer: rebuilding a match from the stored
marker, the fast-skip rule for already-applied books, and what a marker claims
was written under each field policy."""
import types
import unittest
from pathlib import Path
from app import media_probe
from app.tests.script_loader import load_script

FIXER = load_script("fixer_marker_helpers", "audible-metadata-fixer-v5.py")


class ProbeAudioStreamPropertiesTests(unittest.TestCase):
    def probe(self, payload):
        import json
        from unittest import mock
        result = types.SimpleNamespace(stdout=json.dumps(payload), returncode=0)
        with mock.patch.object(media_probe.subprocess, "run", return_value=result):
            return FIXER.probe_audio_stream_properties(Path("/lib/a.m4b"))

    def test_the_label_falls_back_to_the_upper_cased_codec_and_gets_a_profile_suffix(self):
        self.assertEqual(self.probe({"streams": [{"codec_name": "mp3"}]})["codec_label"], "MP3")
        got = self.probe({"streams": [{"codec_name": "aac", "codec_long_name": "AAC", "profile": "LC"}]})
        self.assertEqual(got["codec_label"], "AAC (LC)")

    def test_a_timeout_or_garbage_output_is_an_unprobed_result(self):
        from unittest import mock
        with mock.patch.object(media_probe.subprocess, "run", side_effect=media_probe.subprocess.TimeoutExpired("ffprobe", 30)):
            self.assertEqual(FIXER.probe_audio_stream_properties(Path("a.m4b")), {"probed": False})
        with mock.patch.object(media_probe.subprocess, "run", return_value=types.SimpleNamespace(stdout="not json", returncode=0)):
            self.assertEqual(FIXER.probe_audio_stream_properties(Path("a.m4b")), {"probed": False})


if __name__ == "__main__":
    unittest.main()
