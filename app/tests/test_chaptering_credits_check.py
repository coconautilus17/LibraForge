"""Bonus check: when an Opening Credits row exists, cross-check the book's
known author/narrator tags against what the Opening Credits transcript
actually says, via the LLM review step (deterministic string matching isn't
reliable here since STT frequently mangles names).
"""
import json
import tempfile
import unittest
from pathlib import Path

from app.chaptering import _build_hybrid_llm_prompt, resolve_book_credits


class ResolveBookCreditsTests(unittest.TestCase):
    def test_reads_author_narrator_from_sidecar_book_section(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            (Path(root) / "libraforge.json").write_text(
                json.dumps({"book": {"author": "A. F. Kay", "narrator": "Travis Baldree"}}),
                encoding="utf-8",
            )
            credits = resolve_book_credits(source)
            self.assertEqual(credits, {"author": "A. F. Kay", "narrator": "Travis Baldree"})

    def test_falls_back_to_metadata_json_authors_narrators_lists(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            (Path(root) / "metadata.json").write_text(
                json.dumps({"authors": ["A. F. Kay"], "narrators": ["Travis Baldree"]}),
                encoding="utf-8",
            )
            credits = resolve_book_credits(source)
            self.assertEqual(credits, {"author": "A. F. Kay", "narrator": "Travis Baldree"})

    def test_joins_multiple_authors_and_narrators(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            (Path(root) / "metadata.json").write_text(
                json.dumps({"authors": ["A", "B"], "narrators": ["C", "D"]}),
                encoding="utf-8",
            )
            credits = resolve_book_credits(source)
            self.assertEqual(credits, {"author": "A, B", "narrator": "C, D"})

    def test_sidecar_wins_over_metadata_json_per_field(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            (Path(root) / "libraforge.json").write_text(
                json.dumps({"book": {"author": "Sidecar Author"}}), encoding="utf-8"
            )
            (Path(root) / "metadata.json").write_text(
                json.dumps({"authors": ["Metadata Author"], "narrators": ["Metadata Narrator"]}),
                encoding="utf-8",
            )
            credits = resolve_book_credits(source)
            # author comes from the sidecar (present there); narrator falls back since sidecar has none.
            self.assertEqual(credits, {"author": "Sidecar Author", "narrator": "Metadata Narrator"})

    def test_no_data_anywhere_returns_empty_strings(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            self.assertEqual(resolve_book_credits(source), {"author": "", "narrator": ""})


def _result_with_chapters(chapters):
    return {"source_path": "/audiobooks/Book/book.mp3", "chapters": chapters, "hybrid": {}}


class CreditsCheckRequestInPromptTests(unittest.TestCase):
    def test_includes_credits_check_request_when_opening_credits_and_credits_present(self):
        chapters = [
            {"id": 1, "start": 0.0, "title": "Opening Credits", "marker_kind": "Opening Credits", "source_text": "This is Audible. Written by A F K. Narrated by Travis Boultrie."},
            {"id": 2, "start": 16.4, "title": "Chapter 1", "marker_kind": "Chapter", "number": 1, "source_text": ""},
        ]
        prompt = _build_hybrid_llm_prompt(
            _result_with_chapters(chapters), book_credits={"author": "A. F. Kay", "narrator": "Travis Baldree"}
        )
        payload = json.loads(prompt.split("Book data: ", 1)[1])
        self.assertIn("credits_check_request", payload)
        self.assertEqual(payload["credits_check_request"]["known_author"], "A. F. Kay")
        self.assertEqual(payload["credits_check_request"]["known_narrator"], "Travis Baldree")
        self.assertIn("Boultrie", payload["credits_check_request"]["opening_credits_evidence"])

    def test_omits_credits_check_request_without_opening_credits_row(self):
        chapters = [{"id": 1, "start": 0.0, "title": "Chapter 1", "marker_kind": "Chapter", "number": 1, "source_text": ""}]
        prompt = _build_hybrid_llm_prompt(
            _result_with_chapters(chapters), book_credits={"author": "A. F. Kay", "narrator": "Travis Baldree"}
        )
        payload = json.loads(prompt.split("Book data: ", 1)[1])
        self.assertNotIn("credits_check_request", payload)

    def test_omits_credits_check_request_without_known_credits(self):
        chapters = [{"id": 1, "start": 0.0, "title": "Opening Credits", "marker_kind": "Opening Credits", "source_text": "This is Audible."}]
        prompt = _build_hybrid_llm_prompt(_result_with_chapters(chapters), book_credits={"author": "", "narrator": ""})
        payload = json.loads(prompt.split("Book data: ", 1)[1])
        self.assertNotIn("credits_check_request", payload)

    def test_omits_credits_check_request_when_book_credits_not_supplied(self):
        chapters = [{"id": 1, "start": 0.0, "title": "Opening Credits", "marker_kind": "Opening Credits", "source_text": "This is Audible."}]
        prompt = _build_hybrid_llm_prompt(_result_with_chapters(chapters))
        payload = json.loads(prompt.split("Book data: ", 1)[1])
        self.assertNotIn("credits_check_request", payload)


if __name__ == "__main__":
    unittest.main()
