"""A book Audible could not answer for is never matched as if Audible had no
listing: no later source is tried, nothing is written, and the next run looks it
up again (business rule audible-unavailable)."""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import audible
import httpx

from app.fixer import plan as match_plan
from app.fixer import search as search_module
from app.tests.fixer_run import library_listing, make_book, run_fixer
from app.tests.script_loader import load_module
from app.tests.test_fixer_v5_audiosilo_fallback import AUDIBLE_PRODUCT, AUDIOSILO_MATCH, CLUES, _Resp, _reset

FIXER = load_module("fixer_v5_audible_unavailable", "scripts/audible-metadata-fixer-v5.py")


def http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.audible.com/1.0/catalog/products")
    return httpx.HTTPStatusError("error", request=request, response=httpx.Response(status, request=request))


class Catalog:
    """Stands in for an Audible client: each get() raises `error`, or answers `answer`."""

    def __init__(self, error: BaseException | None = None, answer: dict | None = None):
        self.error, self.answer, self.calls = error, answer or {"products": []}, 0

    def get(self, path, params=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.answer


class SearchItemTests(unittest.TestCase):
    def setUp(self):
        _reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / "Hellstrom's Hive.m4b"
        self.book.write_bytes(b"")

    def call(self, client, clues=None, special=None):
        args = SimpleNamespace(
            aggressive=False, force=False, min_score=0.7, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=10, api_delay_ms=0,
            abs_agg_url="http://agg" if special else "", abs_tract_url="", trust_abs_metadata=False,
            weight_abs_metadata=False, provider="audible", abs_provider="audible", abs_url="", abs_api_key="",
            audiosilo_url="http://silo", enable_goodreads_fallback=True, duration_review_threshold=15,
        )
        key = FIXER.get_search_context_cache_key(self.book, {})
        silo = []

        def audiosilo(req, timeout=10):
            silo.append(req.full_url)
            return _Resp({"matches": [AUDIOSILO_MATCH]})

        with patch.object(FIXER, "get_thread_client", return_value=client), \
                patch("urllib.request.urlopen", audiosilo), \
                patch.object(FIXER, "detect_special_provider", return_value=special), \
                patch.object(FIXER, "abs_agg_search", return_value=[dict(AUDIBLE_PRODUCT)] if special else []), \
                patch.object(FIXER, "find_goodreads_match", return_value=(None, 0.0, None, "")) as goodreads:
            result = FIXER.search_item(
                index=1, file_path=self.book, total=1, multi_part_group_map={},
                args=args, auth_file="", auth_password=None,
                search_context_cache={key: (["Hellstrom's Hive Frank Herbert"], dict(clues or CLUES))},
                search_context_lock=threading.Lock(),
                match_cache={}, match_cache_lock=threading.Lock(),
                search_cache={}, search_cache_lock=threading.Lock(),
                search_in_flight={}, folder_audio_counts=None, abs_index=None,
            )
        return result, silo, goodreads

    def assertUnavailable(self, result, silo, goodreads):
        self.assertTrue(result.audible_unavailable)
        self.assertEqual((result.status, result.skip_reason), ("skipped", FIXER.AUDIBLE_UNAVAILABLE_REASON))
        self.assertFalse(result.add_to_manual_review)  # no skip marker: the next run looks again
        self.assertIsNone(result.metadata)
        self.assertEqual(silo, [])
        goodreads.assert_not_called()

    def test_audible_still_throttling_after_the_waits_tries_no_other_source(self):
        self.assertUnavailable(*self.call(Catalog(error=http_error(503))))

    def test_audible_not_reachable_tries_no_other_source(self):
        self.assertUnavailable(*self.call(Catalog(error=httpx.ConnectError("refused"))))

    def test_the_logged_in_client_rate_limited(self):
        self.assertUnavailable(*self.call(Catalog(error=audible.exceptions.RatelimitError(httpx.Response(429), {}))))

    def test_the_public_catalog_throttling_through_every_wait(self):
        throttle = search_module.AudibleThrottle(sleep=lambda seconds: None)
        client = search_module.PublicAudibleClient(
            region="us", throttled_retries=2, transport=httpx.MockTransport(lambda request: httpx.Response(503)))
        with patch.object(search_module, "_AUDIBLE_THROTTLE", throttle):
            self.assertUnavailable(*self.call(client))

    def test_audible_answering_nothing_found_still_falls_back(self):
        result, silo, goodreads = self.call(Catalog())
        self.assertFalse(result.audible_unavailable)
        self.assertTrue(silo)

    def test_an_asin_audible_does_not_know_is_an_answer(self):
        result, silo, _ = self.call(Catalog(error=http_error(404)), clues={**CLUES, "existing_asin": "B000000000"})
        self.assertFalse(result.audible_unavailable)
        self.assertTrue(silo)

    def test_a_confident_match_before_audible_still_counts(self):
        # GraphicAudio matched; Audible could not be asked about the embedded ASIN.
        result, _, _ = self.call(Catalog(error=http_error(503)), clues={**CLUES, "existing_asin": "B000000000"},
                                 special="graphicaudio")
        self.assertFalse(result.audible_unavailable)
        self.assertEqual((result.source_provider, result.metadata["title"]), ("graphicaudio", "Hellstrom's Hive"))


class UnansweredLookupTests(unittest.TestCase):
    def setUp(self):
        search_module.start_book_lookups()

    def test_a_failed_batch_is_not_counted_when_the_book_s_own_lookup_answers(self):
        product = {"asin": "B002V59S5K", "title": "Hellstrom's Hive"}

        class BatchDown:
            def get(self, path, params=None):
                if "asins" in (params or {}):
                    raise http_error(503)
                return {"product": product}

        lookahead = search_module.AsinLookahead(lambda index: [])
        self.assertEqual(lookahead.lookup(BatchDown(), "B002V59S5K", 0), product)
        self.assertEqual(search_module.unanswered_audible_lookups(), 0)

    def test_each_book_starts_with_none(self):
        search_module.audible_lookup_by_asin(Catalog(error=http_error(503)), "B000000000")
        self.assertEqual(search_module.unanswered_audible_lookups(), 1)
        search_module.start_book_lookups()
        self.assertEqual(search_module.unanswered_audible_lookups(), 0)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        make_book(self.root / "Author" / "Lone Book" / "Lone Book.m4b", "Lone Book")

    def test_apply_writes_nothing_for_it(self):
        def unavailable(fixer, index, file_path, total):
            return fixer.ItemResult(
                index=index, file_path=file_path, display_path=file_path, log_lines=[],
                status="skipped", skip_reason=fixer.AUDIBLE_UNAVAILABLE_REASON, audible_unavailable=True, clues={},
            )

        book = self.root / "Author" / "Lone Book" / "Lone Book.m4b"
        before = library_listing(self.root)[str(book.relative_to(self.root))]
        out = run_fixer(FIXER, self.root, "--apply", search=unavailable)
        self.assertEqual(library_listing(self.root)[str(book.relative_to(self.root))], before)
        # No skip marker: the original-tags backup Apply takes while reading is all there is.
        for sidecar in self.root.rglob("*libraforge.json"):
            self.assertNotIn("marker", json.loads(sidecar.read_text()))
        self.assertIn('"audible_unavailable": true', out)

    def test_apply_searches_it_again_instead_of_reusing_the_dry_run(self):
        record = {"files": [["a", 1, 2]], "result": {"status": "skipped", "audible_unavailable": True}}
        self.assertIsNone(match_plan.usable_record(record, [["a", 1, 2]]))
        record["result"]["audible_unavailable"] = False
        self.assertIsNotNone(match_plan.usable_record(record, [["a", 1, 2]]))


if __name__ == "__main__":
    unittest.main()
