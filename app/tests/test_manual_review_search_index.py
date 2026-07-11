"""Tests for the Manual Review filesystem search index: the pure disk-walk
that builds the searchable path list, and the ignore-list signature used to
detect when a rebuild is needed."""
import tempfile
import unittest
from pathlib import Path

from app.main import _build_manual_review_search_index, _ignored_signature


class IgnoredSignatureTests(unittest.TestCase):
    def test_empty_list_is_empty_signature(self):
        self.assertEqual(_ignored_signature([]), "")

    def test_order_independent(self):
        self.assertEqual(_ignored_signature(["b", "a"]), _ignored_signature(["a", "b"]))

    def test_case_and_whitespace_independent(self):
        self.assertEqual(_ignored_signature([" Recycle "]), _ignored_signature(["recycle"]))

    def test_blank_entries_dropped(self):
        self.assertEqual(_ignored_signature(["a", "", "  "]), _ignored_signature(["a"]))

    def test_different_tokens_differ(self):
        self.assertNotEqual(_ignored_signature(["a"]), _ignored_signature(["b"]))


class BuildManualReviewSearchIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_finds_a_single_book_folder(self):
        self._touch("Author/Book/Book.m4b")
        entries = _build_manual_review_search_index(self.root, [])
        self.assertEqual(entries, [(str(self.root / "Author" / "Book"), False)])

    def test_loose_root_file_is_its_own_entry(self):
        self._touch("Loose.m4b")
        entries = _build_manual_review_search_index(self.root, [])
        self.assertEqual(entries, [(str(self.root / "Loose.m4b"), True)])

    def test_collapses_disc_subfolders_into_parent(self):
        self._touch("Author/Book/Disc 1/part1.m4b")
        self._touch("Author/Book/Disc 2/part2.m4b")
        entries = _build_manual_review_search_index(self.root, [])
        self.assertEqual(entries, [(str(self.root / "Author" / "Book"), False)])

    def test_skips_hardcoded_hidden_and_system_prefixes(self):
        self._touch("Author/Book/Book.m4b")
        self._touch(".hidden/Ghost.m4b")
        self._touch("#recycle/Ghost.m4b")
        self._touch("@eaDir/Ghost.m4b")
        entries = _build_manual_review_search_index(self.root, [])
        self.assertEqual(entries, [(str(self.root / "Author" / "Book"), False)])

    def test_skips_user_configured_ignore_tokens(self):
        self._touch("Author/Book/Book.m4b")
        self._touch("temp-imports/Ghost.m4b")
        entries = _build_manual_review_search_index(self.root, ["temp"])
        self.assertEqual(entries, [(str(self.root / "Author" / "Book"), False)])

    def test_ignore_token_match_is_case_insensitive(self):
        self._touch("Author/Book/Book.m4b")
        self._touch("TEMP-Imports/Ghost.m4b")
        entries = _build_manual_review_search_index(self.root, ["temp"])
        self.assertEqual(entries, [(str(self.root / "Author" / "Book"), False)])

    def test_progress_callback_receives_incrementing_counts(self):
        self._touch("Author/Book1/Book1.m4b")
        self._touch("Author/Book2/Book2.m4b")
        seen = []
        _build_manual_review_search_index(self.root, [], on_progress=seen.append)
        self.assertEqual(seen, [1, 2])

    def test_non_audio_files_are_ignored(self):
        self._touch("Author/Book/cover.jpg")
        entries = _build_manual_review_search_index(self.root, [])
        self.assertEqual(entries, [])
