"""Bonus check: when an Opening Credits row exists, cross-check the book's
known author/narrator tags against what the Opening Credits transcript
actually says, via the LLM review step (deterministic string matching isn't
reliable here since STT frequently mangles names).
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.chaptering import (
    _build_credits_check_prompt,
    _build_hybrid_llm_prompt,
    _call_ollama_json,
    _extract_json_object,
    detect_chapters_hybrid,
    resolve_book_credits,
)


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


class BuildHybridLlmPromptHasNoCreditsRequestTests(unittest.TestCase):
    # The credits cross-check used to be folded into the main review prompt,
    # but a real "clean" 35-chapter book (nothing needing correction, so the
    # full chapter list gets sent verbatim) pushed that combined prompt to
    # ~21K chars and the model's response degraded into echoing input field
    # names instead of following the output schema -- a context-pressure
    # failure independent of and in addition to num_predict truncation on a
    # long corrections list. The credits check now runs as its own tiny,
    # separate call (see BuildCreditsCheckPromptTests) so its prompt size
    # never grows with the book's chapter or correction count.
    def test_main_review_prompt_never_mentions_credits_check(self):
        chapters = [
            {"id": 1, "start": 0.0, "title": "Opening Credits", "marker_kind": "Opening Credits", "source_text": "This is Audible."},
            {"id": 2, "start": 16.4, "title": "Chapter 1", "marker_kind": "Chapter", "number": 1, "source_text": ""},
        ]
        prompt = _build_hybrid_llm_prompt(_result_with_chapters(chapters))
        self.assertNotIn("credits_check", prompt)
        payload = json.loads(prompt.split("Book data: ", 1)[1])
        self.assertNotIn("credits_check_request", payload)


class BuildCreditsCheckPromptTests(unittest.TestCase):
    def test_includes_known_credits_and_evidence_in_input_payload(self):
        prompt = _build_credits_check_prompt("A. F. Kay", "Travis Baldree", "Written by AFK. Narrated by Travis Boultrie.")
        payload = json.loads(prompt.split("Input data: ", 1)[1])
        self.assertEqual(payload["known_author"], "A. F. Kay")
        self.assertEqual(payload["known_narrator"], "Travis Baldree")
        self.assertIn("Boultrie", payload["opening_credits_evidence"])

    def test_prompt_stays_small_regardless_of_evidence_length(self):
        # This is the whole point of splitting it out: unlike the main review
        # prompt, nothing here scales with chapter count or correction count.
        prompt = _build_credits_check_prompt("Author", "Narrator", "x" * 400)
        self.assertLess(len(prompt), 2000)


class ExtractJsonObjectTests(unittest.TestCase):
    def test_recovers_object_from_otherwise_truncated_json(self):
        raw = (
            '{"assessment":"high","confidence":"high",'
            '"credits_check":{"author_match":"match","author_tag":"Dante King"},'
            '"accepted_corrections":[{"action":"clean_title","number":1,"timestamp":"00:00:2'
        )
        recovered = _extract_json_object(raw, "credits_check")
        self.assertEqual(recovered, {"author_match": "match", "author_tag": "Dante King"})

    def test_handles_nested_braces_and_escaped_quotes_in_strings(self):
        raw = (
            '{"credits_check":{"author_evidence":"he said \\"Dante King\\" clearly", '
            '"nested":{"a":1}},"accepted_corrections":[TRUNCATED'
        )
        recovered = _extract_json_object(raw, "credits_check")
        self.assertEqual(recovered["nested"], {"a": 1})
        self.assertIn("Dante King", recovered["author_evidence"])

    def test_returns_none_when_key_absent(self):
        self.assertIsNone(_extract_json_object('{"assessment":"clean"}', "credits_check"))

    def test_returns_none_when_object_itself_is_truncated(self):
        raw = '{"credits_check":{"author_match":"match","author_tag":"Dante K'
        self.assertIsNone(_extract_json_object(raw, "credits_check"))


class _FakeOllamaResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class CallOllamaJsonSalvageTests(unittest.TestCase):
    def test_salvages_credits_check_from_a_truncated_response(self):
        truncated_response_text = (
            '{"assessment":"high","confidence":"high",'
            '"credits_check":{"author_match":"match","author_tag":"Dante King",'
            '"narrator_match":"match","narrator_tag":"Alex Perone, Marissa Parness"},'
            '"accepted_corrections":[{"action":"clean_title","number":1,"timestamp":"00:00:2'
        )

        def fake_urlopen(request, timeout=None):
            return _FakeOllamaResponse({"response": truncated_response_text})

        with patch("urllib.request.urlopen", fake_urlopen):
            review = _call_ollama_json("http://fake-ollama:11434", "gemma4:latest", "prompt")

        self.assertIn("parse_error", review)
        self.assertEqual(
            review["credits_check"],
            {
                "author_match": "match",
                "author_tag": "Dante King",
                "narrator_match": "match",
                "narrator_tag": "Alex Perone, Marissa Parness",
            },
        )

    def test_no_credits_check_key_added_when_nothing_to_recover(self):
        def fake_urlopen(request, timeout=None):
            return _FakeOllamaResponse({"response": '{"assessment":"clean","confidence":"high"'})

        with patch("urllib.request.urlopen", fake_urlopen):
            review = _call_ollama_json("http://fake-ollama:11434", "gemma4:latest", "prompt")

        self.assertIn("parse_error", review)
        self.assertNotIn("credits_check", review)


class DetectChaptersHybridCreditsCheckDecouplingTests(unittest.TestCase):
    # The credits check is a separate Ollama call from the main chapter
    # review, specifically so a failure or degraded response in one never
    # takes down the other (live-verified: a real book's main review call
    # returned malformed JSON under context pressure while a clean, separate
    # credits-check call for the same book succeeded).
    def _fixed_chapters(self):
        return [
            {
                "id": 1, "start": 0.0, "end": 16.0, "title": "Opening Credits",
                "marker_kind": "Opening Credits", "number": None, "confidence": None,
                "reasons": [], "source_text": "Written by A. F. Kay. Narrated by Travis Baldree.",
                "source_file": "", "original_start": 0.0,
            },
            {
                "id": 2, "start": 16.0, "end": 100.0, "title": "Chapter 1",
                "marker_kind": "Chapter", "number": 1, "confidence": 0.9,
                "reasons": [], "source_text": "", "source_file": "", "original_start": 16.0,
            },
        ]

    def test_credits_check_survives_when_main_review_call_raises(self):
        credits_response = {
            "credits_check": {
                "author_match": "match", "author_tag": "A. F. Kay", "author_evidence": "Written by A. F. Kay",
                "narrator_match": "match", "narrator_tag": "Travis Baldree", "narrator_evidence": "Narrated by Travis Baldree",
            },
            "_model": "gemma4:latest",
        }
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            with patch("app.chaptering.audio_files", return_value=[source]), \
                 patch("app.chaptering._run_sound_of_silence", return_value=([], 100.0, 0, [])), \
                 patch("app.chaptering.annotate_unresolved_gaps", return_value=[]), \
                 patch("app.chaptering.finalize_chapters", side_effect=lambda *a, **k: [dict(c) for c in self._fixed_chapters()]), \
                 patch("app.chaptering._remote_asr_for_chapter_evidence", return_value=([], [])), \
                 patch("app.chaptering.resolve_book_credits", return_value={"author": "A. F. Kay", "narrator": "Travis Baldree"}), \
                 patch("app.chaptering._call_ollama_json", side_effect=[RuntimeError("ollama down"), credits_response]) as mock_ollama:
                result = detect_chapters_hybrid(source, llm_review=True)

        self.assertEqual(mock_ollama.call_count, 2)
        review = result["hybrid"]["llm_review"]
        self.assertEqual(review["assessment"], "llm_unavailable")
        self.assertEqual(review["credits_check"]["author_tag"], "A. F. Kay")
        self.assertEqual(review["credits_check"]["narrator_tag"], "Travis Baldree")

    def test_no_second_call_when_no_opening_credits_chapter(self):
        chapters_without_credits = [
            {
                "id": 1, "start": 0.0, "end": 100.0, "title": "Chapter 1",
                "marker_kind": "Chapter", "number": 1, "confidence": 0.9,
                "reasons": [], "source_text": "", "source_file": "", "original_start": 0.0,
            },
        ]
        main_review_response = {"assessment": "clean", "confidence": "high", "accepted_corrections": [], "unresolved_issues": [], "validator_rules_to_apply": [], "notes": []}
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            with patch("app.chaptering.audio_files", return_value=[source]), \
                 patch("app.chaptering._run_sound_of_silence", return_value=([], 100.0, 0, [])), \
                 patch("app.chaptering.annotate_unresolved_gaps", return_value=[]), \
                 patch("app.chaptering.finalize_chapters", side_effect=lambda *a, **k: [dict(c) for c in chapters_without_credits]), \
                 patch("app.chaptering._remote_asr_for_chapter_evidence", return_value=([], [])), \
                 patch("app.chaptering.resolve_book_credits", return_value={"author": "A. F. Kay", "narrator": "Travis Baldree"}), \
                 patch("app.chaptering._call_ollama_json", return_value=main_review_response) as mock_ollama:
                result = detect_chapters_hybrid(source, llm_review=True)

        mock_ollama.assert_called_once()
        self.assertNotIn("credits_check", result["hybrid"]["llm_review"])


if __name__ == "__main__":
    unittest.main()
