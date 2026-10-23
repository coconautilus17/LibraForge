import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script


ORGANIZER = load_script("organizer_v3_13_chapter_forge_companions", "organize-audiobooks-by-metadata-v3_13.py")


class ChapterForgeCompanionFilesTests(unittest.TestCase):
    def test_chapter_forge_artifacts_travel_with_the_audio_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Book 1.mp3"
            audio.write_bytes(b"")
            srt = root / "Book 1.mp3.libraforge-chapters.srt"
            cue = root / "Book 1.mp3.libraforge-chapters.cue"
            review = root / "Book 1.mp3.libraforge-ai-review.md"
            srt.write_text("")
            cue.write_text("")
            review.write_text("")

            companions = ORGANIZER.companion_files_for(audio)

            self.assertIn(srt, companions)
            self.assertIn(cue, companions)
            self.assertIn(review, companions)

    def test_unrelated_files_are_not_picked_up_as_companions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Book 1.mp3"
            audio.write_bytes(b"")
            unrelated = root / "Book 1.mp3.libraforge-chapters.srt.bak"
            unrelated.write_text("")

            companions = ORGANIZER.companion_files_for(audio)

            self.assertNotIn(unrelated, companions)


if __name__ == "__main__":
    unittest.main()
