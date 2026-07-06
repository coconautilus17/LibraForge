"""write_marker's field_policy awareness -- the marker-recording counterpart
to app/fixer/tagging.py's should_write_field(). marker.audible must always
describe what the writer actually left embedded for the same field_policy:

- "fill": every field, if blank in the decided match, falls back to the
  current (pre-write) tag value -- the writer left it untouched, so the
  marker must say so, not claim it's blank.
- "overwrite": no field falls back -- a blank really is cleared, so the
  marker must say blank too.
- "legacy" (CLI, unchanged): only genre/subtitle/isbn/asin/publisher fall
  back, exactly as before this feature existed.

See docs/design/manual-review-apply-rewrite-rules.md.
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


FIXER = load_module("fixer_v5_field_policy_marker", "scripts/audible-metadata-fixer-v5.py")


class WriteMarkerFieldPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.media = Path(self.tmp.name) / "Book.m4b"
        self.media.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _marker(self) -> dict:
        raw = json.loads((self.media.parent / "Book.m4b.libraforge.json").read_text())
        return raw["marker"]["audible"]

    # Decided match: only narrator supplied, everything else blank --
    # mirrors the reported Dragon Conjurer 8 bug scenario (kept narrator,
    # cleared everything else) -- plus a "current" snapshot standing in for
    # what's really on disk right now.
    METADATA = {
        "asin": "", "title": "", "subtitle": "", "author": "",
        "narrator": "Kept Narrator", "series": "", "sequence": "",
        "year": "", "genre": "", "isbn": "", "publisher": "",
        "summary": "", "edit_mode": "full",
    }
    CURRENT = {
        "asin": "B0OLDASIN01", "title": "Old Title", "subtitle": "Old Subtitle",
        "author": "Old Author", "narrator": "Old Narrator", "series": "Old Series",
        "sequence": "1", "year": "2019", "genre": "Old Genre",
        "isbn": "9781111111111", "publisher": "Old Publisher",
    }

    def test_fill_falls_back_to_current_for_every_blank_field(self):
        FIXER.write_marker(
            self.media, self.METADATA, {"current": self.CURRENT},
            1.0, "manual_full", False, field_policy="fill",
        )
        audible = self._marker()
        self.assertEqual(audible["title"], "Old Title")
        self.assertEqual(audible["author"], "Old Author")
        self.assertEqual(audible["series"], "Old Series")
        self.assertEqual(audible["sequence"], "1")
        self.assertEqual(audible["year"], "2019")
        self.assertEqual(audible["asin"], "B0OLDASIN01")
        self.assertEqual(audible["genre"], "Old Genre")
        self.assertEqual(audible["subtitle"], "Old Subtitle")
        self.assertEqual(audible["isbn"], "9781111111111")
        self.assertEqual(audible["publisher"], "Old Publisher")
        self.assertEqual(audible["narrator"], "Kept Narrator")

    def test_overwrite_never_falls_back_even_for_previously_conditional_fields(self):
        FIXER.write_marker(
            self.media, self.METADATA, {"current": self.CURRENT},
            1.0, "manual_full", False, field_policy="overwrite",
        )
        audible = self._marker()
        self.assertEqual(audible["title"], "")
        self.assertEqual(audible["author"], "")
        self.assertEqual(audible["series"], "")
        self.assertEqual(audible["sequence"], "")
        self.assertEqual(audible["year"], "")
        self.assertEqual(audible["asin"], "")
        self.assertEqual(audible["genre"], "")
        self.assertEqual(audible["subtitle"], "")
        self.assertEqual(audible["isbn"], "")
        self.assertEqual(audible["publisher"], "")
        self.assertEqual(audible["narrator"], "Kept Narrator")

    def test_legacy_keeps_the_original_six_plain_five_fallback_split(self):
        FIXER.write_marker(
            self.media, self.METADATA, {"current": self.CURRENT},
            1.0, "normal", False, field_policy="legacy",
        )
        audible = self._marker()
        # Unconditional fields: no fallback, blank stays blank (matches CLI's
        # always-clear write behavior for these).
        self.assertEqual(audible["title"], "")
        self.assertEqual(audible["author"], "")
        self.assertEqual(audible["series"], "")
        self.assertEqual(audible["sequence"], "")
        self.assertEqual(audible["year"], "")
        # legacy-conditional fields: fallback to current, matching the
        # writer's pre-existing skip-if-blank behavior for these.
        self.assertEqual(audible["genre"], "Old Genre")
        self.assertEqual(audible["subtitle"], "Old Subtitle")
        self.assertEqual(audible["isbn"], "9781111111111")
        self.assertEqual(audible["asin"], "B0OLDASIN01")
        self.assertEqual(audible["publisher"], "Old Publisher")

    def test_default_field_policy_is_legacy(self):
        # Every existing CLI call site never passes field_policy -- confirm
        # the default alone reproduces legacy behavior.
        FIXER.write_marker(
            self.media, self.METADATA, {"current": self.CURRENT},
            1.0, "normal", False,
        )
        audible = self._marker()
        self.assertEqual(audible["title"], "")
        self.assertEqual(audible["genre"], "Old Genre")

    def test_summary_is_never_policy_gated(self):
        # summary always mirrors the decided match's description, matching
        # metadata.json's unconditional "description" field -- not a survivor
        # fallback under any policy.
        metadata = {**self.METADATA, "summary": ""}
        FIXER.write_marker(
            self.media, metadata, {"current": {**self.CURRENT, "summary": "Old summary."}},
            1.0, "manual_full", False, field_policy="fill",
        )
        self.assertEqual(self._marker()["summary"], "")


if __name__ == "__main__":
    unittest.main()
