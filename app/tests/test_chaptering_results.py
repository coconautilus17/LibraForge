"""Where Chapter Forge writes its output files and what save_result keeps."""
import tempfile
import unittest
from pathlib import Path

from app.chaptering import save_result


class SaveResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "book.m4b"
        self.source.write_bytes(b"")
        self.payload = {"chapters": [{"id": 1, "start": 0.0, "end": 60.0, "title": "One"}], "settings": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_preview_run_is_saved_under_a_preview_variant_name(self):
        written = save_result(self.source, {"chapters": [], "settings": {"max_audio_seconds": 600}})
        self.assertTrue(Path(written["cue"]).name.startswith("book.m4b.preview-10min."))

    def test_an_ai_review_report_is_listed_only_when_the_run_had_one(self):
        self.assertNotIn("ai_review", save_result(self.source, self.payload))
        payload = {**self.payload, "hybrid": {"llm_review": {"assessment": "ok", "confidence": "high", "notes": ["n1"]}}}
        written = save_result(self.source, payload)
        self.assertIn("ai_review", written)
        text = Path(written["ai_review"]).read_text(encoding="utf-8")
        self.assertIn("Assessment: `ok`", text)
        self.assertIn("- n1", text)

if __name__ == "__main__":
    unittest.main()
