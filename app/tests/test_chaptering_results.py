"""Where Chapter Forge writes its output files and what save_result keeps."""
import json
import tempfile
import unittest
from pathlib import Path

from app.chaptering import load_existing_result, result_paths, save_result


class ResultPathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_file_source_writes_next_to_it_named_after_the_file(self):
        source = self.root / "My Book.m4b"
        source.write_bytes(b"")
        paths = result_paths(source)
        self.assertEqual(paths["srt"], self.root / "My Book.m4b.libraforge-chapters.srt")
        self.assertEqual(paths["transcript"], self.root / "My Book.m4b.libraforge-transcript.txt")
        self.assertEqual(paths["cue"], self.root / "My Book.m4b.libraforge-chapters.cue")
        self.assertEqual(paths["ai_review"], self.root / "My Book.m4b.libraforge-ai-review.md")

    def test_a_folder_source_writes_inside_the_folder(self):
        book = self.root / "Some Book"
        book.mkdir()
        self.assertEqual(result_paths(book)["cue"], book / "Some Book.libraforge-chapters.cue")

    def test_unsafe_characters_in_the_name_are_replaced(self):
        source = self.root / "A:B*C?.m4b"
        source.write_bytes(b"")
        self.assertEqual(result_paths(source)["srt"].name, "A_B_C_.m4b.libraforge-chapters.srt")

    def test_a_name_that_is_only_dots_and_spaces_falls_back_to_chapters(self):
        folder = self.root / " . "
        folder.mkdir()
        self.assertEqual(result_paths(folder)["srt"].name, "chapters.libraforge-chapters.srt")

    def test_a_variant_is_inserted_before_the_suffix_and_sanitised(self):
        source = self.root / "b.m4b"
        source.write_bytes(b"")
        self.assertEqual(result_paths(source, variant="preview-5min")["srt"].name, "b.m4b.preview-5min.libraforge-chapters.srt")
        self.assertEqual(result_paths(source, variant="a/b")["srt"].name, "b.m4b.a_b.libraforge-chapters.srt")

    def test_a_variant_that_sanitises_to_nothing_is_ignored(self):
        source = self.root / "b.m4b"
        source.write_bytes(b"")
        self.assertEqual(result_paths(source, variant=" . ")["srt"].name, "b.m4b.libraforge-chapters.srt")


class SaveResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "book.m4b"
        self.source.write_bytes(b"")
        self.payload = {"chapters": [{"id": 1, "start": 0.0, "end": 60.0, "title": "One"}], "settings": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_payload_lands_in_the_sidecar_under_chapter_forge_with_a_schema_version(self):
        save_result(self.source, self.payload)
        sidecar = json.loads((self.root / "libraforge.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["chapter_forge"], self.payload)
        self.assertEqual(sidecar["schema_version"], 1)

    def test_an_existing_sidecar_keeps_its_other_sections_and_its_own_schema_version(self):
        (self.root / "libraforge.json").write_text(json.dumps({"book": {"title": "T"}, "schema_version": 3}))
        save_result(self.source, self.payload)
        sidecar = json.loads((self.root / "libraforge.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["book"], {"title": "T"})
        self.assertEqual(sidecar["schema_version"], 3)

    def test_srt_and_transcript_are_written_only_when_given_and_the_cue_always(self):
        written = save_result(self.source, self.payload)
        self.assertEqual(sorted(Path(p).suffix for p in written.values()), [".cue", ".json"])
        written = save_result(self.source, self.payload, srt="1\n", transcript="text")
        self.assertIn("srt", written)
        self.assertIn("transcript", written)
        self.assertEqual(Path(written["srt"]).read_text(encoding="utf-8"), "1\n")
        self.assertEqual(Path(written["transcript"]).read_text(encoding="utf-8"), "text")

    def test_the_cue_names_the_source_file_and_the_chapters(self):
        written = save_result(self.source, self.payload)
        cue = Path(written["cue"]).read_text(encoding="utf-8")
        self.assertIn("book.m4b", cue)
        self.assertIn("One", cue)

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

    def test_load_existing_result_round_trips_and_ignores_missing_or_malformed_data(self):
        self.assertIsNone(load_existing_result(self.source))
        save_result(self.source, self.payload)
        self.assertEqual(load_existing_result(self.source), self.payload)
        (self.root / "libraforge.json").write_text(json.dumps({"chapter_forge": "oops"}))
        self.assertIsNone(load_existing_result(self.source))


if __name__ == "__main__":
    unittest.main()
