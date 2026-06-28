"""abs-tract (Goodreads/Kindle) client + Goodreads edit-mode gate in v5."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub


def load_fixer():
    path = ROOT / "scripts" / "audible-metadata-fixer-v5.py"
    spec = importlib.util.spec_from_file_location("audible_fixer_v5_abstract", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fixer = load_fixer()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen_for(payload, captured):
    def _open(req, timeout=15):
        captured["url"] = req.full_url
        return _FakeResp(payload)
    return _open


def _reset_breaker():
    fixer._ABS_TRACT_BREAKER.update(
        {"consecutive_failures": 0, "open_until": 0.0, "logged_open": False}
    )


class AbsTractRetryTests(unittest.TestCase):
    """Transient abs-tract failures retry and are logged distinctly from a real
    empty result (a book that *is* on Goodreads must not look like a miss)."""

    def setUp(self):
        _reset_breaker()

    def test_retries_transient_then_succeeds(self):
        payload = {"matches": [{"title": "T", "author": "A"}]}
        calls = {"n": 0}

        def flaky(req, timeout=20):
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("boom")
            return _FakeResp(payload)

        with patch("time.sleep", lambda *_a: None), \
                patch("urllib.request.urlopen", flaky):
            products = fixer.abs_tract_search(
                "T", "A", "goodreads", "http://abs-tract:5555", 10, retries=3,
            )
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(products), 1)

    def test_exhausted_retries_logs_failure(self):
        def always_fail(req, timeout=20):
            raise TimeoutError("boom")

        log: list[str] = []
        with patch("time.sleep", lambda *_a: None), \
                patch("urllib.request.urlopen", always_fail):
            products = fixer.abs_tract_search(
                "T", "A", "goodreads", "http://abs-tract:5555", 10,
                retries=3, log=log,
            )
        self.assertEqual(products, [])
        self.assertTrue(any("request failed after 3 tries" in line for line in log))

    def test_real_empty_is_not_logged_as_failure(self):
        log: list[str] = []
        with patch("urllib.request.urlopen", fake_urlopen_for({"matches": []}, {})):
            products = fixer.abs_tract_search(
                "T", "A", "goodreads", "http://abs-tract:5555", 10, log=log,
            )
        self.assertEqual(products, [])
        self.assertEqual(log, [])  # genuine no-result, no error line

    def test_non_retryable_http_stops_immediately(self):
        import urllib.error as _e
        calls = {"n": 0}

        def http404(req, timeout=20):
            calls["n"] += 1
            raise _e.HTTPError(req.full_url, 404, "nf", {}, None)

        with patch("time.sleep", lambda *_a: None), \
                patch("urllib.request.urlopen", http404):
            products = fixer.abs_tract_search(
                "T", "A", "goodreads", "http://abs-tract:5555", 10, retries=3,
            )
        self.assertEqual(products, [])
        self.assertEqual(calls["n"], 1)  # 404 is not retried


class AbsTractBreakerTests(unittest.TestCase):
    """Circuit breaker: when upstream blocks (persistent failures), further calls
    short-circuit for a cooldown instead of hanging on every book."""

    def setUp(self):
        _reset_breaker()

    def test_breaker_opens_after_threshold_and_short_circuits(self):
        calls = {"n": 0}

        def always_fail(req, timeout=20):
            calls["n"] += 1
            raise TimeoutError("blocked")

        with patch("time.sleep", lambda *_a: None), \
                patch("urllib.request.urlopen", always_fail):
            # Two persistent failures (threshold=2) trip the breaker.
            for _ in range(fixer._ABS_TRACT_BREAKER_THRESHOLD):
                fixer.abs_tract_search("t", "a", "goodreads", "http://x:5555", 10)
            calls_after_trip = calls["n"]
            # Next call must short-circuit without hitting the network.
            log: list[str] = []
            out = fixer.abs_tract_search(
                "t", "a", "goodreads", "http://x:5555", 10, log=log
            )
        self.assertEqual(out, [])
        self.assertEqual(calls["n"], calls_after_trip)  # no new network call
        self.assertTrue(any("circuit open" in line for line in log))

    def test_success_resets_failure_counter(self):
        payload = {"matches": [{"title": "T", "author": "A"}]}
        seq = [TimeoutError("x"), payload]

        def flaky(req, timeout=20):
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return _FakeResp(item)

        with patch("time.sleep", lambda *_a: None), \
                patch("urllib.request.urlopen", flaky):
            # retries=1 so the first call is a single persistent failure,
            # the second call succeeds and resets the counter.
            fixer.abs_tract_search("t", "a", "goodreads", "http://x:5555", 10, retries=1)
            fixer.abs_tract_search("t", "a", "goodreads", "http://x:5555", 10, retries=1)
        self.assertEqual(fixer._ABS_TRACT_BREAKER["consecutive_failures"], 0)
        self.assertFalse(fixer._abs_tract_breaker_is_open())


class AbsTractClientTests(unittest.TestCase):
    def setUp(self):
        _reset_breaker()

    def test_goodreads_url_and_normalization(self):
        payload = {"matches": [{
            "title": "The Primal Talisman", "author": "Dante King",
            "series": [{"series": "Beast Shifter", "sequence": "3"}],
            "isbn": "9781", "cover": "http://gr/cover.jpg",
            "description": "A book.", "publishedYear": "2024",
        }]}
        cap = {}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload, cap)):
            products = fixer.abs_tract_search(
                title="The Primal Talisman", author="Dante King",
                provider="goodreads", abs_tract_url="http://abs-tract:5555", limit=10,
            )
        self.assertIn("/goodreads/search?", cap["url"])
        self.assertIn("query=The+Primal+Talisman", cap["url"])
        self.assertEqual(len(products), 1)
        p = products[0]
        self.assertEqual(p["title"], "The Primal Talisman")
        self.assertEqual(p["authors"][0]["name"], "Dante King")
        self.assertEqual(p["series"][0]["title"], "Beast Shifter")
        self.assertEqual(p["_abs_provider"], "goodreads")
        self.assertIsNone(p["runtime_length_min"])

    def test_kindle_url_uses_region_and_drops_ebook_asin(self):
        payload = {"matches": [{
            "title": "The Primal Talisman", "author": "Dante King",
            "asin": "B0KINDLE99", "cover": "http://kindle/hq.jpg",
        }]}
        cap = {}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload, cap)):
            products = fixer.abs_tract_search(
                title="The Primal Talisman", author="Dante King",
                provider="kindle", abs_tract_url="http://abs-tract:5555", limit=10,
                existing_asin="", kindle_region="uk",
            )
        self.assertIn("/kindle/uk/search?", cap["url"])
        # Kindle ebook ASIN must NOT be adopted as the book ASIN.
        self.assertNotEqual(products[0]["asin"], "B0KINDLE99")
        self.assertEqual(products[0]["asin"], "")
        self.assertEqual(products[0]["product_images"]["500"], "http://kindle/hq.jpg")

    def test_empty_url_returns_nothing(self):
        self.assertEqual(
            fixer.abs_tract_search("t", "a", "goodreads", "", 10), []
        )


class GoodreadsEditModeGateTests(unittest.TestCase):
    def _product(self, title, author):
        return {"_abs_provider": "goodreads", "title": title,
                "authors": [{"name": author}], "series": []}

    def test_full_on_strong_title_and_author(self):
        mode = fixer.determine_edit_mode(
            self._product("The Primal Talisman", "Dante King"),
            {"title": "The Primal Talisman", "author": "Dante King"},
            0.2,
        )
        self.assertEqual(mode, "full")

    def test_none_on_wrong_author(self):
        mode = fixer.determine_edit_mode(
            self._product("The Primal Talisman", "Someone Else"),
            {"title": "The Primal Talisman", "author": "Dante King"},
            0.2,
        )
        self.assertEqual(mode, "none")

    def test_none_on_wrong_title(self):
        mode = fixer.determine_edit_mode(
            self._product("A Totally Different Book", "Dante King"),
            {"title": "The Primal Talisman", "author": "Dante King"},
            0.2,
        )
        self.assertEqual(mode, "none")


if __name__ == "__main__":
    unittest.main()
