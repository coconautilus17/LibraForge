"""--trust-abs-metadata and --weight-abs-metadata: the two opt-in modes that
let Meta Forge treat an already-manually-corrected Audiobookshelf record as
an input, for an existing/messy library where the user has already fixed
some books directly in the Audiobookshelf UI.

Calls search_item() directly (Meta Forge's real per-book worker function),
with real tempdir files, so this exercises the actual wiring rather than a
paraphrase of it.
"""
import importlib.util
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


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


FIXER = load_module("fixer_v5_abs_metadata_input_modes", "scripts/audible-metadata-fixer-v5.py")


class SearchItemAbsInputModesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.book = self.root / "book.m4b"
        self.book.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **overrides):
        base = dict(
            aggressive=False, force=False, min_score=0.5, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=5,
            abs_agg_url="", abs_tract_url="", trust_abs_metadata=False, weight_abs_metadata=False,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def _call(self, args, abs_index):
        return FIXER.search_item(
            index=1, file_path=self.book, total=1, multi_part_group_map={},
            args=args, auth_file="", auth_password=None,
            search_context_cache={}, search_context_lock=threading.Lock(),
            match_cache={}, match_cache_lock=threading.Lock(),
            search_cache={}, search_cache_lock=threading.Lock(),
            search_in_flight={}, folder_audio_counts=None, abs_index=abs_index,
        )

    def _hit_index(self, abs_media, library_item_id="li1"):
        return {
            "by_asin": {}, "by_path": {str(self.root): {
                "library_item_id": library_item_id, "path": str(self.root),
                "rel_path": "book", "updated_at": 100, "media": abs_media,
            }},
        }

    # --trust-abs-metadata --------------------------------------------------

    def test_trust_mode_lookup_hit_uses_abs_data_directly(self):
        abs_media = {"metadata": {
            "title": "The Real Title", "authorName": "Real Author", "narratorName": "Real Narrator",
            "seriesName": "Real Series, Book 2", "asin": "B0REALASIN",
        }}
        args = self._args(trust_abs_metadata=True)
        result = self._call(args, self._hit_index(abs_media))
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.edit_mode, "full")
        self.assertEqual(result.metadata["title"], "The Real Title")
        self.assertEqual(result.metadata["author"], "Real Author")
        # "Real Series, Book 2" -- Pattern-A wording cleanup still applies.
        self.assertEqual(result.metadata["series"], "Real Series")
        self.assertEqual(result.metadata["sequence"], "2")

    def test_trust_mode_lookup_miss_does_not_short_circuit(self):
        args = self._args(trust_abs_metadata=True)
        result = self._call(args, {"by_asin": {}, "by_path": {}})
        # No ABS record and no useful embedded metadata on a blank file ->
        # falls through to the normal "nothing to search from" skip, proving
        # the trust-mode branch didn't fire (it would have set score=1.0).
        self.assertNotEqual(result.score, 1.0)

    def test_trust_mode_off_never_checks_abs_even_on_a_hit(self):
        abs_media = {"metadata": {"title": "The Real Title", "asin": "B0REALASIN"}}
        args = self._args(trust_abs_metadata=False)
        result = self._call(args, self._hit_index(abs_media))
        self.assertNotEqual(result.score, 1.0)

    # --weight-abs-metadata ---------------------------------------------------

    def test_weight_mode_sets_abs_asin_clue_when_it_differs_from_existing(self):
        abs_media = {"metadata": {"title": "T", "asin": "B0DIFFERENT"}}
        args = self._args(weight_abs_metadata=True)
        result = self._call(args, self._hit_index(abs_media))
        self.assertEqual(result.clues.get("abs_asin"), "B0DIFFERENT")

    def test_weight_mode_does_not_set_abs_asin_clue_when_lookup_misses(self):
        args = self._args(weight_abs_metadata=True)
        result = self._call(args, {"by_asin": {}, "by_path": {}})
        self.assertNotIn("abs_asin", result.clues)

    def test_weight_mode_off_never_sets_abs_asin_clue_even_on_a_hit(self):
        abs_media = {"metadata": {"title": "T", "asin": "B0DIFFERENT"}}
        args = self._args(weight_abs_metadata=False)
        result = self._call(args, self._hit_index(abs_media))
        self.assertNotIn("abs_asin", result.clues)


if __name__ == "__main__":
    unittest.main()
