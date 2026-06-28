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


class AbsTractClientTests(unittest.TestCase):
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
