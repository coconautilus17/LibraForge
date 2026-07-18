"""_run_sound_of_silence() must pass chaptering.py's own full structural-
marker vocabulary (MARKER_WORDS) into SoundOfSilence.py's TARGET_WORDS, not
a narrower hardcoded subset.

Real-world bug found live against Divine Apostasy Book 2: SoundOfSilence's
own TARGET_WORDS gate decides which silence-break snippets even get
returned as candidate rows at all (TARGET_FIRST_WORD_ONLY=True) -- it ran
BEFORE chaptering.py's own richer MARKER_RE classification ever saw the
text. With TARGET_WORDS hardcoded to just ["chapter", "part", "section"],
a spoken "Prologue" or "Epilogue" cue was filtered out at the SoS stage
and never reached the classifier at all, even though MARKER_RE has always
recognized those words. Confirmed via Book 2's real transcript: a ~12
minute unaccounted gap before the first detected "Chapter 1" candidate,
and no chapter detected in the final ~12 minutes after the last one.
"""
import types
import unittest
from unittest.mock import MagicMock, patch

from app.chaptering import MARKER_WORDS, _run_sound_of_silence


class FakeSosModule:
    def __init__(self, captured_configs):
        self._captured_configs = captured_configs

    def Config(self):
        return types.SimpleNamespace()

    def validate_ffmpeg_path(self, config):
        pass

    def AudioProcessor(self, config):
        self._captured_configs.append(config)
        processor = MagicMock()
        processor.initialize_whisper.return_value = False
        return processor


class RunSoundOfSilenceTargetWordsTests(unittest.TestCase):
    def test_target_words_matches_full_marker_vocabulary(self):
        captured_configs = []
        fake_sos = FakeSosModule(captured_configs)
        with patch("app.chaptering._load_sos_module", return_value=fake_sos):
            with self.assertRaises(RuntimeError):
                _run_sound_of_silence(__import__("pathlib").Path("/tmp/does-not-matter.mp3"))
        self.assertEqual(len(captured_configs), 1)
        self.assertEqual(captured_configs[0].TARGET_WORDS, list(MARKER_WORDS))

    def test_marker_words_includes_prologue_and_epilogue(self):
        # Regression guard for the specific words that were missing before
        # this fix -- these must stay in MARKER_WORDS (and therefore in
        # TARGET_WORDS via the assertion above) for front/back-matter
        # chapters to ever be detected by the SoS/hybrid path.
        for word in ("prologue", "epilogue", "interlude", "afterword", "foreword", "preface"):
            self.assertIn(word, MARKER_WORDS)


if __name__ == "__main__":
    unittest.main()
