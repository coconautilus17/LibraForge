import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_bracketed_clue", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class BracketedMiddleSegmentStandaloneParseTests(unittest.TestCase):
    """Legacy release filenames like

        Eric Vall - [Okay, But Try Not to Murder Anyone-2] - Okay, But Try Not to Murder Anyone 2.m4b

    split into exactly three " - " segments, but the shape is
    Author - [series/sequence tag] - Title, not the assumed
    Title - Author - Narrator. The bracketed middle segment is never a real
    author credit and must not be trusted as one.
    """

    def test_bracketed_middle_segment_is_not_treated_as_author(self):
        name = (
            "Eric Vall - [Okay, But Try Not to Murder Anyone-2] - "
            "Okay, But Try Not to Murder Anyone 2"
        )
        self.assertEqual(ORGANIZER.parse_standalone_book_folder_name(name), {})


class NarratorClueTitleCorruptionTests(unittest.TestCase):
    """End-to-end reproduction of the organizer report bug where books 2-5 of
    a numbered series collapsed to a bare "Okay" title while books 1, 6, 7, 8
    (same series) correctly collapsed to the series name.
    """

    def _make_loose_file_item(self, root: Path, audio_name: str, audible: dict) -> "ORGANIZER.BookItem":
        book_dir = root / "ericvall2"
        book_dir.mkdir(parents=True, exist_ok=True)
        audio = book_dir / audio_name
        audio.touch()
        marker = audio.with_name(audio.name + ".audible-metadata-fixer.json")
        marker.write_text(json.dumps({"audible": audible}), encoding="utf-8")
        return ORGANIZER.BookItem("loose_file", audio, [audio], audio)

    def test_series_title_survives_when_marker_narrator_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = self._make_loose_file_item(
                root,
                "Eric Vall - [Okay, But Try Not to Murder Anyone-2] - "
                "Okay, But Try Not to Murder Anyone 2.m4b",
                {
                    "title": "Okay, But Try Not to Murder Anyone 2",
                    "chosen_title": "Okay, But Try Not to Murder Anyone 2",
                    "author": "Eric Vall",
                    "narrator": "",
                    "series": "Okay, But Try Not to Murder Anyone",
                    "sequence": "2",
                },
            )
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(metadata["title"], "Okay, But Try Not to Murder Anyone")

    def test_series_title_survives_when_marker_narrator_is_present(self):
        # Book 1 in the same series had a confirmed Audible match with a real
        # narrator, which happened to mask this bug. Keep it working too.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = self._make_loose_file_item(
                root,
                "Eric Vall - [Okay, But Try Not to Murder Anyone-1] - "
                "Okay, But Try Not to Murder Anyone 1.m4b",
                {
                    "title": "Okay, But Try Not to Murder Anyone 1",
                    "chosen_title": "Okay, But Try Not to Murder Anyone 1",
                    "author": "Eric Vall",
                    "narrator": "C.C. Thompson, JD Tanner",
                    "series": "Okay, But Try Not to Murder Anyone",
                    "sequence": "1",
                },
            )
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(metadata["title"], "Okay, But Try Not to Murder Anyone")


if __name__ == "__main__":
    unittest.main()
