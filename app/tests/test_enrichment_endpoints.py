"""Endpoint tests for Enrichment Forge's /api/enrichment/* routes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


class _FakeReviewModule:
    """Stand-in for the dynamically loaded review-libraforge-report.py."""

    @staticmethod
    def normalize_series(value: str) -> str:
        import re
        s = value.strip().lower()
        s = re.sub(r",?\s*book\s+\d+\s*$", "", s).strip()
        return s


def _abs_request(path, params):
    if path == "/api/libraries":
        return {"libraries": [{"id": "lib1", "mediaType": "book"}]}
    if path == "/api/libraries/lib1/items":
        page = int(params["page"])
        if page == 0:
            return {
                "total": 2,
                "results": [
                    {
                        "id": "item-1",
                        "path": "/audiobooks/Logan Jacobs/Scholomance/Scholomance",
                        "isFile": False,
                        "media": {
                            "metadata": {
                                "title": "Scholomance",
                                "asin": "B0AAA",
                                "authorName": "Logan Jacobs",
                                "narratorName": "Andrea Parsneau",
                                "explicit": False,
                                "seriesName": "Scholomance #1",
                            },
                            "tags": ["Fantasy"],
                        },
                    },
                    {
                        "id": "item-2",
                        "path": "/audiobooks/Logan Jacobs/Scholomance/Scholomance 2",
                        "isFile": False,
                        "media": {
                            "metadata": {
                                "title": "Scholomance 2",
                                "asin": "B0BBB",
                                "authorName": "Logan Jacobs",
                                "narratorName": "Andrea Parsneau",
                                "explicit": False,
                                "seriesName": "Scholomance #2",
                            },
                            "tags": [],
                        },
                    },
                ],
            }
        return {"total": 2, "results": []}
    raise AssertionError(f"unexpected path {path}")


class EnrichmentSeriesEndpointTests(unittest.TestCase):
    def test_requires_abs_configured(self):
        with patch("app.main._get_abs_api_key", return_value=""):
            resp = client.get("/api/enrichment/series")
        self.assertEqual(resp.status_code, 400)

    def test_returns_series_summary(self):
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=_abs_request), \
             patch("app.main.load_review_module", return_value=_FakeReviewModule):
            resp = client.get("/api/enrichment/series?q=schol")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"series": [{"name": "Scholomance", "book_count": 2}]})


class EnrichmentCompileEndpointTests(unittest.TestCase):
    def test_requires_abs_configured(self):
        with patch("app.main._get_abs_api_key", return_value=""):
            resp = client.post("/api/enrichment/compile", json={"series_name": "Scholomance"})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_series_404s(self):
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=_abs_request), \
             patch("app.main.load_review_module", return_value=_FakeReviewModule), \
             tempfile.NamedTemporaryFile(suffix=".json") as auth_file:
            resp = client.post(
                "/api/enrichment/compile",
                json={"series_name": "Nonexistent", "auth_file": auth_file.name},
            )
        self.assertEqual(resp.status_code, 404)

    def test_compiles_series(self):
        fake_audible_client = MagicMock()
        fake_products = {
            "B0AAA": {"category_ladders": [{"ladder": [{"name": "Fantasy"}]}], "narrators": [{"name": "Andrea Parsneau"}], "is_adult_product": False},
            "B0BBB": {"category_ladders": [{"ladder": [{"name": "Erotica"}]}], "narrators": [{"name": "Andrea Parsneau"}], "is_adult_product": True},
        }

        def fake_lookup(client_arg, asin, response_groups=None):
            return fake_products.get(asin.upper())

        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=_abs_request), \
             patch("app.main.load_review_module", return_value=_FakeReviewModule), \
             patch("app.main.audible.Authenticator.from_file", return_value=MagicMock()), \
             patch("app.main.audible.Client", return_value=fake_audible_client), \
             patch("app.main.audible_lookup_by_asin", side_effect=fake_lookup), \
             patch("app.main.abs_tract_search", return_value=[]), \
             patch("app.main._load_abs_tract_config", return_value={"url": "", "kindle_region": "us"}), \
             tempfile.NamedTemporaryFile(suffix=".json") as auth_file:
            resp = client.post(
                "/api/enrichment/compile",
                json={"series_name": "Scholomance", "auth_file": auth_file.name},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["explicit_flagged_count"], 1)
        self.assertEqual(body["explicit_total_count"], 2)
        self.assertIn("Fantasy", body["genre"])

    def test_compile_preserves_asin_lookup_fallback(self):
        """audible_lookup_by_asin's real fallback (direct lookup miss -> keyword
        search for the ASIN) must still run through the endpoint: the endpoint
        must call the real fixer.search functions (bound to the enrichment
        response groups), not a duplicate that dropped the fallback.
        """
        fake_audible_client = MagicMock()

        def fake_client_get(path, params=None, **kwargs):
            params = params or {}
            if path == "catalog/products/B0AAA":
                return {
                    "product": {
                        "asin": "B0AAA",
                        "category_ladders": [{"ladder": [{"name": "Fantasy"}]}],
                        "narrators": [{"name": "Andrea Parsneau"}],
                        "is_adult_product": False,
                    }
                }
            if path == "catalog/products/B0BBB":
                # Direct lookup deliberately misses, forcing the fallback.
                return {"product": None}
            if path == "catalog/products":
                # Fallback keyword search inside audible_lookup_by_asin searches
                # for the ASIN itself as the query.
                if params.get("keywords", "").upper() == "B0BBB":
                    return {
                        "products": [
                            {
                                "asin": "B0BBB",
                                "category_ladders": [{"ladder": [{"name": "LitRPG"}]}],
                                "narrators": [{"name": "Andrea Parsneau"}],
                                "is_adult_product": False,
                            }
                        ]
                    }
                return {"products": []}
            raise AssertionError(f"unexpected audible path {path}")

        fake_audible_client.get.side_effect = fake_client_get

        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=_abs_request), \
             patch("app.main.load_review_module", return_value=_FakeReviewModule), \
             patch("app.main.audible.Authenticator.from_file", return_value=MagicMock()), \
             patch("app.main.audible.Client", return_value=fake_audible_client), \
             patch("app.main.abs_tract_search", return_value=[]), \
             patch("app.main._load_abs_tract_config", return_value={"url": "", "kindle_region": "us"}), \
             tempfile.NamedTemporaryFile(suffix=".json") as auth_file:
            resp = client.post(
                "/api/enrichment/compile",
                json={"series_name": "Scholomance", "auth_file": auth_file.name},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # If the fallback had been dropped, item-2's genre (LitRPG, only
        # reachable via the keyword-search fallback) would be missing.
        self.assertIn("Fantasy", body["genre"])
        self.assertIn("LitRPG", body["genre"])


class EnrichmentApplyEndpointTests(unittest.TestCase):
    def test_applies_only_included_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            book_dir = Path(tmp) / "Scholomance"
            book_dir.mkdir()
            payload = {
                "books": [
                    {"id": "1", "path": str(book_dir), "is_file": False, "include": True},
                    {"id": "2", "path": str(Path(tmp) / "Excluded"), "is_file": False, "include": False},
                ],
                "genre": ["Fantasy", "LitRPG"],
                "narrator": "Andrea Parsneau",
                "explicit": False,
            }
            resp = client.post("/api/enrichment/apply", json=payload)
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["applied"], 1)
            self.assertEqual(body["failed"], [])
            written = json.loads((book_dir / "metadata.json").read_text())
            self.assertEqual(written["genres"], ["Fantasy", "LitRPG"])
            self.assertEqual(written["narrators"], ["Andrea Parsneau"])
            self.assertFalse((Path(tmp) / "Excluded" / "metadata.json").exists())

    def test_corrupt_sidecar_reported_as_failure_without_sinking_batch(self):
        """One book with an unreadable existing metadata.json must not crash
        the whole apply request: write_metadata_json_partial raises ValueError
        for a corrupt existing file, and the endpoint must catch that per book,
        skip it, and still apply the rest of the batch (200, not 500)."""
        with tempfile.TemporaryDirectory() as tmp:
            good_dir = Path(tmp) / "Good"
            good_dir.mkdir()
            corrupt_dir = Path(tmp) / "Corrupt"
            corrupt_dir.mkdir()
            (corrupt_dir / "metadata.json").write_text("{not valid json", encoding="utf-8")

            payload = {
                "books": [
                    {"id": "1", "path": str(good_dir), "is_file": False, "include": True},
                    {"id": "2", "path": str(corrupt_dir), "is_file": False, "include": True},
                ],
                "genre": ["Fantasy"],
                "narrator": "Andrea Parsneau",
                "explicit": False,
            }
            resp = client.post("/api/enrichment/apply", json=payload)
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["applied"], 1)
            self.assertEqual(len(body["failed"]), 1)
            self.assertEqual(body["failed"][0]["id"], "2")
            self.assertEqual(body["failed"][0]["path"], str(corrupt_dir))
            self.assertIn("error", body["failed"][0])

            written = json.loads((good_dir / "metadata.json").read_text())
            self.assertEqual(written["genres"], ["Fantasy"])


if __name__ == "__main__":
    unittest.main()
