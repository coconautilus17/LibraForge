"""A manually-applied book must never be silently reprocessed or downgraded
back to an "unapplied" state by an automated batch run.

Bug (observed live): "Unfuk Yourself" had marker.manually_applied=True but
marker.applied=False. should_skip_due_to_marker() only consults
manually_applied inside the `if marker.get("applied") is True:` branch, so
once applied flips to False for any reason, manually_applied is silently
ignored and the book gets reprocessed by every future run -- surfacing as a
"would write" badge for a book the user already manually reviewed and
applied.

That contradictory state is reachable because two write paths
(write_skip_marker, for "could not find a usable match", and
mark_metadata_restored, for "undo back to original tags") set
applied=False without also clearing manually_applied, even though
"manually applied but not applied" is not a real, meaningful state --
manually_applied should always imply applied.

The corruption itself gets triggered because should_skip_due_to_marker()'s
`--force` and `--aggressive` branches bypass the marker check entirely,
including for manually-applied books, letting a batch run re-search a book
a human already finished with. That fresh re-search can come back
ambiguous/no-match, which is what write_skip_marker() records.

Fixed by: (1) checking manually_applied first and unconditionally in
should_skip_due_to_marker(), before force/aggressive are even consulted, and
(2) enforcing the applied/manually_applied invariant at both write sites
that can clear `applied`.
"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_manual_never_downgraded", "scripts/audible-metadata-fixer-v5.py")


class ShouldSkipDueToMarkerManuallyAppliedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.media = self.folder / "Book.m4b"
        self.media.write_bytes(b"")

    def _write_marker(self, **marker_fields):
        payload = {
            "schema_version": 2,
            "tool": "audible-metadata-fixer",
            "marker": {
                "applied": True,
                "manually_applied": True,
                "mode": "manual_full",
                "aggressive": False,
                "score": 1.0,
                "audible": {"asin": "B0REAL1234"},
                **marker_fields,
            },
        }
        lf_path = self.media.with_name(self.media.name + FIXER.LIBRAFORGE_SUFFIX)
        lf_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_manually_applied_skips_even_when_corrupted_to_unapplied(self):
        # Reproduces the actual observed corrupted state.
        self._write_marker(applied=False)
        skip, reason = FIXER.should_skip_due_to_marker(
            self.media, aggressive_run=False, force=False, minimum_score=0.7
        )
        self.assertTrue(skip)
        self.assertEqual(reason, "already manually applied")

    def test_manually_applied_skips_under_aggressive_run(self):
        # A non-aggressive manual marker must not be reprocessed just
        # because a later run happens to pass --aggressive.
        self._write_marker(aggressive=False)
        skip, reason = FIXER.should_skip_due_to_marker(
            self.media, aggressive_run=True, force=False, minimum_score=0.7
        )
        self.assertTrue(skip)
        self.assertEqual(reason, "already manually applied")

    def test_manually_applied_skips_under_force(self):
        self._write_marker()
        skip, reason = FIXER.should_skip_due_to_marker(
            self.media, aggressive_run=False, force=True, minimum_score=0.7
        )
        self.assertTrue(skip)
        self.assertEqual(reason, "already manually applied")


class ApplyingFalseNeverLeavesManuallyAppliedTrueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.media = self.folder / "Book.m4b"
        self.media.write_bytes(b"")
        self.lf_path = self.media.with_name(self.media.name + FIXER.LIBRAFORGE_SUFFIX)

    def _write_marker(self, **marker_fields):
        payload = {
            "schema_version": 2,
            "tool": "audible-metadata-fixer",
            "marker": {
                "applied": True,
                "manually_applied": True,
                "mode": "manual_full",
                "audible": {"asin": "B0REAL1234"},
                **marker_fields,
            },
        }
        self.lf_path.write_text(json.dumps(payload), encoding="utf-8")

    def _read_marker(self):
        return json.loads(self.lf_path.read_text(encoding="utf-8")).get("marker", {})

    def test_write_skip_marker_clears_manually_applied_when_downgrading(self):
        self._write_marker()
        # alone=False keeps the marker at the per-file path this test reads
        # from -- alone=True's folder-level migration is exercised by
        # test_fixer_v5_libraforge_folder_ownership.py already.
        FIXER.write_skip_marker(self.media, clues={}, alone=False)
        marker = self._read_marker()
        self.assertFalse(marker.get("applied"))
        self.assertFalse(marker.get("manually_applied"))

    def test_mark_metadata_restored_clears_manually_applied(self):
        self._write_marker()
        FIXER.mark_metadata_restored(self.media)
        marker = self._read_marker()
        self.assertFalse(marker.get("applied"))
        self.assertFalse(marker.get("manually_applied"))


if __name__ == "__main__":
    unittest.main()
