"""app.fixer.search: ASIN lookup fallbacks, ABS provider normalisation, the
abs-tract retry/breaker/throttle behaviour and dramatized-provider detection."""
import io
import json
import tempfile
import unittest
import urllib.error
from unittest import mock

from app.fixer import search


class FakeClient:
    def __init__(self, direct=None, direct_error=None, search_results=None, search_error=None):
        self.direct, self.direct_error = direct, direct_error
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if self.direct_error:
            raise self.direct_error
        return self.direct


class AudibleLookupByAsinTests(unittest.TestCase):
    def test_nothing_found_anywhere_is_none(self):
        with mock.patch.object(search, "audible_search", return_value=[{"asin": "B0OTHER"}]):
            self.assertIsNone(search.audible_lookup_by_asin(FakeClient(direct={}), "B0ABC"))
        with mock.patch.object(search, "audible_search", side_effect=RuntimeError("down")):
            self.assertIsNone(search.audible_lookup_by_asin(FakeClient(direct_error=RuntimeError("x")), "B0ABC"))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AbsTractTests(unittest.TestCase):
    def setUp(self):
        search._ABS_TRACT_BREAKER.update({"consecutive_failures": 0, "open_until": 0.0, "ever_opened": False, "logged_open": False})
        patcher = mock.patch.object(search, "_abs_tract_throttle")
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(search.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def tearDown(self):
        search._ABS_TRACT_BREAKER.update({"consecutive_failures": 0, "open_until": 0.0, "ever_opened": False, "logged_open": False})

    def urlopen(self, outcomes, urls=None):
        outcomes = list(outcomes)

        def fake(req, timeout=None):
            if urls is not None:
                urls.append((req.full_url, timeout))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return _Resp(json.dumps(outcome).encode())
        return mock.patch("urllib.request.urlopen", fake)

    def search(self, **kw):
        args = dict(title="Unsouled", author="Will Wight", provider="goodreads", abs_tract_url="http://tract:5555/", limit=3)
        args.update(kw)
        return search.abs_tract_search(**args)

    def test_malformed_json_is_not_retried(self):
        class Bad(_Resp):
            pass
        calls = []
        def fake(req, timeout=None):
            calls.append(1)
            return Bad(b"not json")
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(self.search(retries=3), [])
        self.assertEqual(len(calls), 1)


class DetectSpecialProviderTests(unittest.TestCase):
    def test_a_series_name_or_the_composer_tag_names_the_production_company(self):
        self.assertEqual(search.detect_special_provider({"series": "Mistborn (GraphicAudio)"}), "graphicaudio")
        self.assertEqual(search.detect_special_provider({"series": "Foo SoundBooth"}), "soundbooththeater")
        self.assertEqual(search.detect_special_provider({"_raw_tags": {"\xa9wrt": ["GraphicAudio Inc"]}}), "graphicaudio")
        self.assertEqual(search.detect_special_provider({"_raw_tags": {"\xa9wrt": [b"Soundbooth Theater"]}}), "soundbooththeater")

class ThreadClientTests(unittest.TestCase):
    def test_the_client_is_built_once_per_thread_and_reused(self):
        search._thread_local.__dict__.pop("client", None)
        fake_audible = mock.Mock()
        with tempfile.NamedTemporaryFile(suffix=".json") as auth, \
                mock.patch.object(search, "audible", fake_audible):
            first = search.get_thread_client(auth.name)
            second = search.get_thread_client(auth.name)
        self.assertIs(first, second)
        fake_audible.Authenticator.from_file.assert_called_once_with(auth.name)
        search._thread_local.__dict__.pop("client", None)

    def test_no_auth_file_falls_back_to_the_public_catalog(self):
        search._thread_local.__dict__.pop("client", None)
        fake_audible = mock.Mock()
        with mock.patch.object(search, "audible", fake_audible):
            client = search.get_thread_client("/nonexistent/audible-metadata.json")
        self.assertIsInstance(client, search.PublicAudibleClient)
        fake_audible.Authenticator.from_file.assert_not_called()
        search._thread_local.__dict__.pop("client", None)

    def test_a_public_region_ignores_an_existing_login(self):
        fake_audible = mock.Mock()
        with tempfile.NamedTemporaryFile(suffix=".json") as auth, \
                mock.patch.object(search, "audible", fake_audible):
            client = search.get_catalog_client(auth.name, public_region="uk")
        self.assertIsInstance(client, search.PublicAudibleClient)
        self.assertEqual(client.base_url, "https://api.audible.co.uk/1.0/")
        fake_audible.Authenticator.from_file.assert_not_called()


class PublicAudibleClientTests(unittest.TestCase):
    def test_get_calls_the_marketplace_catalog_and_parses_json(self):
        urls = []
        def fake(req, timeout=None):
            urls.append(req.full_url)
            return _Resp(json.dumps({"products": [{"asin": "B0X"}]}).encode())
        with mock.patch("urllib.request.urlopen", fake):
            out = search.audible_search(search.PublicAudibleClient("uk"), "Moby Dick", 50)
        self.assertEqual(out, [{"asin": "B0X"}])
        self.assertTrue(urls[0].startswith("https://api.audible.co.uk/1.0/catalog/products?keywords=Moby+Dick&num_results=50"))

    def test_unknown_region_uses_the_us_catalog(self):
        self.assertEqual(search.PublicAudibleClient("zz").base_url, "https://api.audible.com/1.0/")

    def test_throttling_is_retried_then_succeeds(self):
        calls = []
        def fake(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return _Resp(b'{"product": {"asin": "B0X"}}')
        with mock.patch("urllib.request.urlopen", fake), mock.patch.object(search.time, "sleep"):
            self.assertEqual(search.PublicAudibleClient().get("catalog/products/B0X"), {"product": {"asin": "B0X"}})
        self.assertEqual(len(calls), 2)

    def test_not_found_is_not_retried(self):
        calls = []
        def fake(req, timeout=None):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        with mock.patch("urllib.request.urlopen", fake):
            # audible_lookup_by_asin swallows the error and tries keyword search too.
            self.assertIsNone(search.audible_lookup_by_asin(search.PublicAudibleClient(), "B0NOPE0000"))
        self.assertEqual(len(calls), 2)

class AbsSearchTests(unittest.TestCase):
    def search(self, payload, **kw):
        urls = []
        def fake(req, timeout=None):
            urls.append((req.full_url, req.get_header("Authorization"), timeout))
            if isinstance(payload, Exception):
                raise payload
            return _Resp(json.dumps(payload).encode())
        with mock.patch("urllib.request.urlopen", fake), mock.patch("builtins.print"):
            out = search.abs_search(kw.get("title", "Unsouled"), kw.get("author", "Will Wight"), kw.get("provider", "audible"),
                                    "http://abs:80/", "KEY", kw.get("limit", 3))
        return out, urls

    def test_results_become_audible_shaped_products_with_runtime_in_minutes_and_seconds(self):
        out, _ = self.search([{"asin": "B0X", "title": "Unsouled", "subtitle": "S", "author": "Will Wight", "narrator": "Travis",
                               "series": [{"series": "Cradle", "sequence": 1}], "description": "d", "cover": "c", "duration": 600.5,
                               "publishedYear": 2016, "isbn": "978", "genres": ["Fantasy"]}], provider="audible")
        product = out[0]
        self.assertEqual((product["asin"], product["title"], product["subtitle"]), ("B0X", "Unsouled", "S"))
        self.assertEqual((product["authors"], product["narrators"]), ([{"name": "Will Wight"}], [{"name": "Travis"}]))
        self.assertEqual(product["series"], [{"title": "Cradle", "sequence": "1"}])
        self.assertEqual((product["runtime_length_min"], product["runtime_length_sec"]), (600.5, 36030))
        self.assertEqual((product["release_date"], product["_abs_provider"], product["_abs_isbn"]), ("2016", "audible", "978"))
        self.assertEqual(product["product_images"], {"500": "c"})

    def test_a_string_series_has_no_sequence_and_a_missing_one_gives_none(self):
        out, _ = self.search([{"title": "A", "series": "Cradle"}, {"title": "B"}])
        self.assertEqual(out[0]["series"], [{"title": "Cradle", "sequence": ""}])
        self.assertEqual(out[1]["series"], [])

    def test_a_network_error_or_a_non_list_answer_gives_no_results(self):
        self.assertEqual(self.search(urllib.error.URLError("down"))[0], [])
        self.assertEqual(self.search(OSError("x"))[0], [])
        self.assertEqual(self.search({"matches": []})[0], [])


class AbsAggSearchTests(unittest.TestCase):
    def run_search(self, payload, **kw):
        urls = []
        def fake(req, timeout=None):
            urls.append((req.full_url, timeout))
            if isinstance(payload, Exception):
                raise payload
            return _Resp(json.dumps(payload).encode())
        with mock.patch("urllib.request.urlopen", fake):
            out = search.abs_agg_search(kw.get("title", "Dragon Emperor"), kw.get("author", "Eric Vall"), "graphicaudio",
                                        "http://agg:3000/", kw.get("limit", 2), kw.get("existing_asin", ""))
        return out, urls

    def test_the_embedded_asin_is_kept_when_a_match_has_none(self):
        out, _ = self.run_search({"matches": [{"title": "A"}, {"title": "B", "asin": "B0OWN"}]}, existing_asin="B0OLD")
        self.assertEqual([p["asin"] for p in out], ["B0OLD", "B0OWN"])

    def test_errors_and_garbage_give_no_results(self):
        self.assertEqual(self.run_search(urllib.error.URLError("x"))[0], [])
        self.assertEqual(self.run_search(ValueError("x"))[0], [])
        self.assertEqual(self.run_search({"matches": None})[0], [])


class CachedAudibleSearchTests(unittest.TestCase):
    def call(self, cache=None, delay=0, results=None, error=None, query="Unsouled", limit=5):
        import threading
        cache = {} if cache is None else cache
        in_flight = {}
        def fake(client, q, lim):
            if error:
                raise error
            return results
        with mock.patch.object(search, "audible_search", side_effect=fake) as searched, mock.patch.object(search.time, "sleep") as sleeper:
            out = search.cached_audible_search(object(), query, limit, delay, cache, threading.Lock(), in_flight)
        return out, cache, in_flight, searched, sleeper

    def test_a_hit_does_not_search_again(self):
        out, _, _, searched, sleeper = self.call(cache={("unsouled", 5): [{"asin": "CACHED"}]}, delay=500)
        self.assertEqual(out, [{"asin": "CACHED"}])
        searched.assert_not_called()
        sleeper.assert_not_called()

    def test_the_api_delay_is_slept_in_seconds_only_after_a_real_search_and_only_when_positive(self):
        _, _, _, _, sleeper = self.call(results=[], delay=250)
        sleeper.assert_called_once_with(0.25)
        _, _, _, _, sleeper = self.call(results=[], delay=0)
        sleeper.assert_not_called()

if __name__ == "__main__":
    unittest.main()
