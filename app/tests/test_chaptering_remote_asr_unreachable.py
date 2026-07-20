"""Real gap found live: when the remote ASR server (used by Hybrid's focused
gap recovery and evidence transcription) is genuinely unreachable, every
clip attempt failed individually and got swallowed into a per-clip "status":
"failed" row -- the overall run still "completed", just with silently
missing data throughout. No clear top-level error ever reached the user.
Connectivity failures should fail fast and loud instead of degrading
silently clip-by-clip like a content-specific issue would.
"""
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from app.chaptering import (
    RemoteAsrUnreachableError,
    SequenceGap,
    _focused_remote_asr_for_gaps,
    _post_remote_asr_audio,
    _remote_asr_for_chapter_evidence,
)


class RemoteAsrUnreachableErrorMessageTests(unittest.TestCase):
    def test_message_names_the_endpoint_and_the_cause(self):
        cause = ConnectionRefusedError("Connection refused")
        error = RemoteAsrUnreachableError("http://192.168.1.50:8000", cause)
        self.assertIn("192.168.1.50:8000", str(error))
        self.assertIn("ConnectionRefusedError", str(error))
        self.assertIn("Advanced settings", str(error))


class PostRemoteAsrAudioWrapsConnectivityFailuresTests(unittest.TestCase):
    def test_connection_refused_becomes_remote_asr_unreachable_error(self):
        with tempfile.TemporaryDirectory() as root:
            clip = Path(root) / "clip.mp3"
            clip.write_bytes(b"")
            with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
                with self.assertRaises(RemoteAsrUnreachableError) as ctx:
                    _post_remote_asr_audio(
                        "http://192.168.1.50:8000", clip,
                        model="medium", compute_type="float16",
                    )
        self.assertIn("192.168.1.50:8000", str(ctx.exception))

    def test_url_error_becomes_remote_asr_unreachable_error(self):
        with tempfile.TemporaryDirectory() as root:
            clip = Path(root) / "clip.mp3"
            clip.write_bytes(b"")
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("name resolution failed")):
                with self.assertRaises(RemoteAsrUnreachableError):
                    _post_remote_asr_audio(
                        "http://bad-host:8000", clip,
                        model="medium", compute_type="float16",
                    )


class FailsFastOnUnreachableServerTests(unittest.TestCase):
    def _fake_clips(self, clips, temp_dir, labels, offsets, expected):
        return (clips, temp_dir, labels, offsets, expected)

    def test_focused_remote_asr_for_gaps_reraises_immediately(self):
        clip = Path("/tmp/fake-clip.mp3")
        fake_return = ([clip], None, {str(clip): "book.mp3"}, {str(clip): 0.0}, {str(clip): 1})
        gaps = [SequenceGap(expected_number=1, start=0.0, end=10.0, reason="missing-before-first")]
        with patch("app.chaptering.make_focus_clips", return_value=fake_return), \
             patch("app.chaptering.sequence_gaps", return_value=gaps), \
             patch(
                 "app.chaptering._post_remote_asr_audio",
                 side_effect=RemoteAsrUnreachableError("http://192.168.1.50:8000", ConnectionRefusedError()),
             ):
            with self.assertRaises(RemoteAsrUnreachableError):
                _focused_remote_asr_for_gaps(
                    [Path("/tmp/book.mp3")], [], 100.0,
                    endpoint="http://192.168.1.50:8000", model_name="medium", compute_type="float16",
                    max_gap_rescans=8, progress=None, should_cancel=None,
                )

    def test_remote_asr_for_chapter_evidence_reraises_immediately(self):
        clip = Path("/tmp/fake-clip.mp3")
        fake_return = ([clip], None, {str(clip): "book.mp3"}, {str(clip): 0.0}, {str(clip): 1})
        chapters = [{"id": 1, "start": 0.0, "end": 10.0, "marker_kind": "Chapter", "number": 1}]
        with patch("app.chaptering.make_focus_clips", return_value=fake_return), \
             patch(
                 "app.chaptering._post_remote_asr_audio",
                 side_effect=RemoteAsrUnreachableError("http://192.168.1.50:8000", ConnectionRefusedError()),
             ):
            with self.assertRaises(RemoteAsrUnreachableError):
                _remote_asr_for_chapter_evidence(
                    [Path("/tmp/book.mp3")], chapters, 100.0,
                    endpoint="http://192.168.1.50:8000", model_name="medium", compute_type="float16",
                    progress=None, should_cancel=None,
                )

    def test_other_per_clip_errors_still_degrade_gracefully_not_fail_fast(self):
        # Regression guard: this fail-fast behavior must stay scoped to
        # genuine unreachability, not swallow the pipeline's existing
        # per-clip resilience for other kinds of failures.
        clip = Path("/tmp/fake-clip.mp3")
        fake_return = ([clip], None, {str(clip): "book.mp3"}, {str(clip): 0.0}, {str(clip): 1})
        chapters = [{"id": 1, "start": 0.0, "end": 10.0, "marker_kind": "Chapter", "number": 1}]
        with patch("app.chaptering.make_focus_clips", return_value=fake_return), \
             patch("app.chaptering._post_remote_asr_audio", side_effect=ValueError("unexpected response shape")):
            segments, runs = _remote_asr_for_chapter_evidence(
                [Path("/tmp/book.mp3")], chapters, 100.0,
                endpoint="http://192.168.1.50:8000", model_name="medium", compute_type="float16",
                progress=None, should_cancel=None,
            )
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("ValueError", runs[0]["error"])


if __name__ == "__main__":
    unittest.main()
