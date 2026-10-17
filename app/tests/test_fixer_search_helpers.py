"""app.fixer.search: ASIN lookup fallbacks, ABS provider normalisation, the
abs-tract retry/breaker/throttle behaviour and dramatized-provider detection."""
import io
import json
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
    def test_the_direct_endpoint_is_tried_first_with_an_upper_cased_trimmed_asin(self):
        client = FakeClient(direct={"product": {"asin": "B0ABC", "title": "T"}})
        with mock.patch.object(search, "audible_search", side_effect=AssertionError("no fallback needed")):
            got = search.audible_lookup_by_asin(client, "  b0abc ")
        self.assertEqual(got["title"], "T")
        self.assertEqual(client.calls[0][0], "catalog/products/B0ABC")

    def test_an_empty_direct_answer_falls_back_to_a_search_and_needs_an_exact_asin(self):
        client = FakeClient(direct={"product": None})
        results = [{"asin": "B0OTHER"}, {"asin": "b0abc", "title": "Found"}]
        with mock.patch.object(search, "audible_search", return_value=results) as searched:
            got = search.audible_lookup_by_asin(client, "B0ABC")
        self.assertEqual(got["title"], "Found")
        self.assertEqual(searched.call_args.args[1:3], ("B0ABC", 5))

    def test_a_failing_direct_call_still_falls_back(self):
        client = FakeClient(direct_error=RuntimeError("boom"))
        with mock.patch.object(search, "audible_search", return_value=[{"asin": "B0ABC", "title": "F"}]):
            self.assertEqual(search.audible_lookup_by_asin(client, "B0ABC")["title"], "F")

    def test_nothing_found_anywhere_is_none(self):
        with mock.patch.object(search, "audible_search", return_value=[{"asin": "B0OTHER"}]):
            self.assertIsNone(search.audible_lookup_by_asin(FakeClient(direct={}), "B0ABC"))
        with mock.patch.object(search, "audible_search", side_effect=RuntimeError("down")):
            self.assertIsNone(search.audible_lookup_by_asin(FakeClient(direct_error=RuntimeError("x")), "B0ABC"))


class AbsMatchToProductTests(unittest.TestCase):
    MATCH = {"title": "Unsouled", "subtitle": "Cradle 1", "author": "Will Wight", "narrator": "Travis Baldree",
             "series": [{"series": "Cradle", "sequence": 1}], "description": "d", "cover": "http://c", "publishedYear": 2016,
             "language": "english", "isbn": "978", "genres": ["Fantasy"]}

    def test_every_field_is_mapped_into_the_audible_product_shape(self):
        product = search._abs_match_to_product(self.MATCH, "audiosilo", "B0X")
        self.assertEqual((product["asin"], product["title"], product["subtitle"]), ("B0X", "Unsouled", "Cradle 1"))
        self.assertEqual(product["authors"], [{"name": "Will Wight"}])
        self.assertEqual(product["narrators"], [{"name": "Travis Baldree"}])
        self.assertEqual(product["series"], [{"title": "Cradle", "sequence": "1"}])
        self.assertEqual((product["publisher_summary"], product["product_images"], product["release_date"]),
                         ("d", {"500": "http://c"}, "2016"))
        self.assertEqual((product["language"], product["_abs_provider"], product["_abs_isbn"]), ("english", "audiosilo", "978"))
        self.assertIsNone(product["runtime_length_min"])
        self.assertIn("Fantasy", product["_abs_genres"])

    def test_missing_or_none_fields_become_empty_strings_not_none(self):
        product = search._abs_match_to_product({"title": None, "subtitle": None, "author": None, "narrator": None,
                                                "description": None, "cover": None, "publishedYear": None,
                                                "language": None, "isbn": None}, "x", "")
        self.assertEqual((product["title"], product["subtitle"], product["publisher_summary"], product["release_date"]),
                         ("", "", "", ""))
        self.assertEqual((product["authors"], product["narrators"]), ([{"name": ""}], [{"name": ""}]))
        self.assertEqual((product["language"], product["_abs_isbn"], product["product_images"]), ("", "", {"500": ""}))
        self.assertEqual(product["series"], [])

    def test_a_series_entry_without_a_name_or_a_non_list_series_gives_no_series(self):
        self.assertEqual(search._abs_match_to_product({"series": [{"series": "", "sequence": "1"}]}, "x", "")["series"], [])
        self.assertEqual(search._abs_match_to_product({"series": "Cradle"}, "x", "")["series"], [])

    def test_a_series_without_a_sequence_has_a_blank_one(self):
        product = search._abs_match_to_product({"series": [{"series": "Cradle", "sequence": None}]}, "x", "")
        self.assertEqual(product["series"], [{"title": "Cradle", "sequence": ""}])


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

    def test_the_request_url_carries_provider_path_query_and_author(self):
        urls = []
        with self.urlopen([{"matches": []}], urls):
            self.search(timeout=7)
        self.assertEqual(urls[0], ("http://tract:5555/goodreads/search?query=Unsouled&author=Will+Wight", 7))

    def test_kindle_uses_a_region_path_and_a_blank_author_is_left_out(self):
        urls = []
        with self.urlopen([{"matches": []}], urls):
            self.search(provider="kindle", kindle_region="/uk/", author="")
        self.assertEqual(urls[0][0], "http://tract:5555/kindle/uk/search?query=Unsouled")

    def test_no_url_means_no_request(self):
        with self.urlopen([]):
            self.assertEqual(self.search(abs_tract_url=""), [])

    def test_results_are_limited_and_goodreads_asins_are_adopted_with_a_fallback(self):
        matches = [{"title": f"T{i}", "asin": f"A{i}" if i else ""} for i in range(5)]
        with self.urlopen([{"matches": matches}]):
            got = self.search(limit=3, existing_asin="B0OLD")
        self.assertEqual([p["asin"] for p in got], ["B0OLD", "A1", "A2"])

    def test_a_kindle_asin_is_never_adopted(self):
        with self.urlopen([{"matches": [{"title": "T", "asin": "KINDLE"}]}]):
            got = self.search(provider="kindle", existing_asin="B0OLD")
        self.assertEqual(got[0]["asin"], "B0OLD")

    def test_transient_http_errors_are_retried_with_a_doubling_backoff(self):
        err = lambda code: urllib.error.HTTPError("u", code, "x", {}, None)
        with self.urlopen([err(503), err(429), {"matches": [{"title": "ok"}]}]):
            got = self.search(retries=3)
        self.assertEqual(got[0]["title"], "ok")
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [0.75, 1.5])

    def test_each_retryable_status_is_retried(self):
        for code in (429, 500, 502, 503, 504):
            with self.subTest(code=code), self.urlopen([urllib.error.HTTPError("u", code, "x", {}, None), {"matches": [{"title": "ok"}]}]):
                self.assertEqual(self.search(retries=2)[0]["title"], "ok")

    def test_a_non_retryable_status_stops_at_once_and_is_logged(self):
        log = []
        with self.urlopen([urllib.error.HTTPError("u", 404, "x", {}, None), {"matches": [{"title": "late"}]}]):
            got = self.search(retries=3, log=log)
        self.assertEqual(got, [])
        self.sleep.assert_not_called()
        self.assertIn("goodreads request failed after 3 tries (HTTP 404)", log[0])

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

    def test_exhausting_the_retries_sleeps_between_but_not_after_the_last_attempt(self):
        with self.urlopen([urllib.error.URLError("x"), urllib.error.URLError("x")]):
            self.assertEqual(self.search(retries=2), [])
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [0.75])

    def test_a_failed_search_counts_towards_the_breaker_and_a_good_one_resets_it(self):
        with self.urlopen([OSError("x")]):
            self.search(retries=1)
        self.assertEqual(search._ABS_TRACT_BREAKER["consecutive_failures"], 1)
        with self.urlopen([{"matches": []}]):
            self.search(retries=1)
        self.assertEqual(search._ABS_TRACT_BREAKER["consecutive_failures"], 0)

    def test_two_consecutive_failures_open_the_breaker_and_it_skips_further_calls_logging_once(self):
        with self.urlopen([OSError("x")]):
            self.search(retries=1)
        with self.urlopen([OSError("x")]):
            self.search(retries=1)
        self.assertTrue(search._abs_tract_breaker_is_open())
        self.assertTrue(search.abs_tract_breaker_ever_opened())
        log = []
        with self.urlopen([]):
            self.assertEqual(self.search(log=log), [])
            self.assertEqual(self.search(log=log), [])
        self.assertEqual(len(log), 1)
        self.assertIn("circuit open", log[0])

    def test_a_success_clears_the_logged_open_flag_so_the_next_open_period_logs_again(self):
        search._ABS_TRACT_BREAKER["logged_open"] = True
        search._abs_tract_breaker_record(success=True)
        self.assertIs(search._ABS_TRACT_BREAKER["logged_open"], False)


class AbsTractThrottleTests(unittest.TestCase):
    def test_a_request_inside_the_delay_waits_for_the_remainder(self):
        with mock.patch.object(search.time, "time", side_effect=[100.2, 100.7]), \
             mock.patch.object(search.time, "sleep") as sleeper, \
             mock.patch.object(search, "_ABS_TRACT_LAST_REQUEST_TIME", [100.0]):
            search._abs_tract_throttle()
        self.assertAlmostEqual(sleeper.call_args.args[0], 0.3, places=3)

    def test_a_request_after_the_delay_does_not_wait(self):
        with mock.patch.object(search.time, "time", side_effect=[200.0, 200.0]), \
             mock.patch.object(search.time, "sleep") as sleeper, \
             mock.patch.object(search, "_ABS_TRACT_LAST_REQUEST_TIME", [100.0]):
            search._abs_tract_throttle()
        sleeper.assert_not_called()

    def test_the_time_of_the_request_is_recorded(self):
        last = [0.0]
        with mock.patch.object(search.time, "time", side_effect=[500.0, 500.0]), \
             mock.patch.object(search.time, "sleep"), mock.patch.object(search, "_ABS_TRACT_LAST_REQUEST_TIME", last):
            search._abs_tract_throttle()
        self.assertEqual(last[0], 500.0)


class DetectSpecialProviderTests(unittest.TestCase):
    def test_a_series_name_or_the_composer_tag_names_the_production_company(self):
        self.assertEqual(search.detect_special_provider({"series": "Mistborn (GraphicAudio)"}), "graphicaudio")
        self.assertEqual(search.detect_special_provider({"series": "Foo SoundBooth"}), "soundbooththeater")
        self.assertEqual(search.detect_special_provider({"_raw_tags": {"\xa9wrt": ["GraphicAudio Inc"]}}), "graphicaudio")
        self.assertEqual(search.detect_special_provider({"_raw_tags": {"\xa9wrt": [b"Soundbooth Theater"]}}), "soundbooththeater")

    def test_the_ffprobe_composer_key_is_used_only_when_no_mp4_atom_exists(self):
        self.assertEqual(search.detect_special_provider({"_raw_tags": {"composer": "GraphicAudio"}}), "graphicaudio")
        clues = {"_raw_tags": {"\xa9wrt": ["Someone"], "composer": "GraphicAudio"}}
        self.assertIsNone(search.detect_special_provider(clues))

    def test_a_dramatized_adaptation_marker_in_title_subtitle_or_narrator_triggers_graphicaudio(self):
        for field in ("title", "subtitle", "narrator"):
            with self.subTest(field=field):
                self.assertEqual(search.detect_special_provider({field: "Storm Front (Dramatized Adaptation)"}), "graphicaudio")

    def test_both_words_are_needed(self):
        self.assertIsNone(search.detect_special_provider({"title": "A dramatized account"}))
        self.assertIsNone(search.detect_special_provider({"title": "An adaptation"}))

    def test_nothing_suspicious_is_not_special(self):
        self.assertIsNone(search.detect_special_provider({}))
        self.assertIsNone(search.detect_special_provider({"series": None, "title": None, "subtitle": None, "narrator": None}))


class ThreadClientTests(unittest.TestCase):
    def test_the_client_is_built_once_per_thread_and_reused(self):
        search._thread_local.__dict__.pop("client", None)
        fake_audible = mock.Mock()
        with mock.patch.object(search, "audible", fake_audible):
            first = search.get_thread_client("auth.json")
            second = search.get_thread_client("auth.json")
        self.assertIs(first, second)
        fake_audible.Authenticator.from_file.assert_called_once_with("auth.json")
        search._thread_local.__dict__.pop("client", None)

    def test_a_password_is_passed_through_only_when_given(self):
        search._thread_local.__dict__.pop("client", None)
        fake_audible = mock.Mock()
        with mock.patch.object(search, "audible", fake_audible):
            search.get_thread_client("auth.json", "secret")
        fake_audible.Authenticator.from_file.assert_called_once_with("auth.json", password="secret")
        search._thread_local.__dict__.pop("client", None)


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

    def test_the_request_is_an_authenticated_search_with_title_provider_and_author(self):
        _, urls = self.search([])
        self.assertEqual(urls, [("http://abs:80/api/search/books?title=Unsouled&provider=audible&author=Will+Wight", "Bearer KEY", 15)])

    def test_a_blank_author_is_left_out_of_the_query(self):
        _, urls = self.search([], author="")
        self.assertNotIn("author=", urls[0][0])

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

    def test_a_missing_duration_gives_none_for_both_runtimes(self):
        out, _ = self.search([{"title": "A"}])
        self.assertEqual((out[0]["runtime_length_min"], out[0]["runtime_length_sec"]), (None, None))

    def test_only_the_first_limit_results_are_kept(self):
        out, _ = self.search([{"title": str(i)} for i in range(10)], limit=3)
        self.assertEqual([p["title"] for p in out], ["0", "1", "2"])

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

    def test_the_url_carries_title_limit_and_author_for_the_provider(self):
        _, urls = self.run_search({"matches": []})
        self.assertEqual(urls, [("http://agg:3000/graphicaudio/search?title=Dragon+Emperor&limit=2&author=Eric+Vall", 15)])
        _, urls = self.run_search({"matches": []}, author="")
        self.assertNotIn("author=", urls[0][0])

    def test_matches_are_normalised_and_limited(self):
        out, _ = self.run_search({"matches": [{"title": "A", "asin": "B0A"}, {"title": "B"}, {"title": "C"}]})
        self.assertEqual([p["title"] for p in out], ["A", "B"])
        self.assertEqual(out[0]["_abs_provider"], "graphicaudio")

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

    def test_a_miss_searches_once_and_caches_under_the_lower_cased_query_and_limit(self):
        out, cache, in_flight, searched, _ = self.call(results=[{"asin": "A"}])
        self.assertEqual(out, [{"asin": "A"}])
        self.assertEqual(cache, {("unsouled", 5): [{"asin": "A"}]})
        self.assertEqual(in_flight, {})
        searched.assert_called_once()

    def test_a_hit_does_not_search_again(self):
        out, _, _, searched, sleeper = self.call(cache={("unsouled", 5): [{"asin": "CACHED"}]}, delay=500)
        self.assertEqual(out, [{"asin": "CACHED"}])
        searched.assert_not_called()
        sleeper.assert_not_called()

    def test_a_different_limit_is_a_different_entry(self):
        out, _, _, searched, _ = self.call(cache={("unsouled", 10): [{"asin": "OTHER"}]}, results=[{"asin": "NEW"}])
        self.assertEqual(out, [{"asin": "NEW"}])
        searched.assert_called_once()

    def test_the_api_delay_is_slept_in_seconds_only_after_a_real_search_and_only_when_positive(self):
        _, _, _, _, sleeper = self.call(results=[], delay=250)
        sleeper.assert_called_once_with(0.25)
        _, _, _, _, sleeper = self.call(results=[], delay=0)
        sleeper.assert_not_called()

    def test_a_failing_search_caches_an_empty_result_and_releases_waiters(self):
        out, cache, in_flight, _, _ = self.call(error=RuntimeError("boom"))
        self.assertEqual((out, cache, in_flight), ([], {("unsouled", 5): []}, {}))


if __name__ == "__main__":
    unittest.main()
