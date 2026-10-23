"""An applied match is reused unless the run explicitly requests a rematch."""
import json
import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script


FIXER = load_script("fixer_v5_force_reprocess", "audible-metadata-fixer-v5.py")


class ForceReprocessMarkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name) / "Book.m4b"
        self.media.write_bytes(b"")

    def _write_marker(self, applied, score, **extra):
        sidecar = self.media.with_name(self.media.name + FIXER.LIBRAFORGE_SUFFIX)
        sidecar.write_text(json.dumps({"marker": {
            "applied": applied, "aggressive": False, "score": score,
            **extra,
        }}), encoding="utf-8")

    def test_applied_low_score_is_not_researched_without_force(self):
        self._write_marker(applied=True, score=0.29)
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=False, force=False, minimum_score=0.7
            ),
            (True, "already processed"),
        )

    def test_force_researches_applied_low_score(self):
        self._write_marker(applied=True, score=0.29)
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=False, force=True, minimum_score=0.7
            ),
            (False, ""),
        )

    def test_unapplied_book_is_retried_without_force(self):
        self._write_marker(applied=False, score=None)
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=False, force=False, minimum_score=0.7
            ),
            (False, ""),
        )

    def test_previously_searched_unapplied_book_is_retried(self):
        self._write_marker(applied=False, score=0.29, processed_at="2026-10-01T00:00:00Z")
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=False, force=False, minimum_score=0.7
            ),
            (False, ""),
        )

    def test_force_researches_previously_skipped_book(self):
        self._write_marker(applied=False, score=0.29, processed_at="2026-10-01T00:00:00Z")
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=False, force=True, minimum_score=0.7
            ),
            (False, ""),
        )

    def test_restored_book_is_eligible_for_search(self):
        self._write_marker(
            applied=False, score=1.0,
            processed_at="2026-10-01T00:00:00Z", restored_at="2026-10-02T00:00:00Z",
        )
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=False, force=False, minimum_score=0.7
            ),
            (False, ""),
        )

    def test_aggressive_mode_does_not_research_applied_book(self):
        self._write_marker(applied=True, score=0.29, processed_at="2026-10-01T00:00:00Z")
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=True, force=False, minimum_score=0.7
            ),
            (True, "already processed"),
        )

    def test_completed_search_after_restore_is_retried(self):
        self._write_marker(
            applied=False, score=None,
            processed_at="2026-10-01T00:00:00Z", restored_at="2026-10-02T00:00:00Z",
        )
        FIXER.write_skip_marker(self.media)
        self.assertEqual(
            FIXER.should_skip_due_to_marker(
                self.media, aggressive_run=False, force=False, minimum_score=0.7
            ),
            (False, ""),
        )


if __name__ == "__main__":
    unittest.main()
