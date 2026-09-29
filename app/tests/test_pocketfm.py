"""Pocket FM show metadata from the public show page (schema.org PodcastSeries).

Pocket FM's own API (api.pocketfm.com) needs an app session, so LibraForge
reads only the public show page, the same one a browser gets. Fixtures are
the real JSON-LD blocks of Supreme Magus, Shadow Slave and its Hindi edition.
"""
import json
import unittest
from unittest.mock import patch

from app import pocketfm

SUPREME_MAGUS = {
    "@context": "https://schema.org", "@type": "PodcastSeries",
    "@id": "https://www.pocketfm.com/show/6d490170d41444017ad8573036509e92d867abb6#series",
    "name": "Supreme Magus",
    "image": "https://d2wxtuh5s9v3ty.cloudfront.net/images/media_1960ec.webp",
    "description": "A man is reborn into a magical world as Lith, an infant with his memories intact.",
    "datePublished": "2023-03-14T11:01:50Z", "genre": ["Fantasy"], "inLanguage": "en",
    "numberOfEpisodes": 2286,
    "creator": [{"@type": "Person", "name": "Legion20"}, {"@type": "Person", "name": "Anonymous"}],
}
SHADOW_SLAVE_HINDI = {
    "@type": "PodcastSeries", "name": "छाया दास सनी", "genre": ["Suspense & Thriller"], "inLanguage": "hi",
    "datePublished": "2025-02-01T00:00:00Z", "numberOfEpisodes": 75,
    "creator": [{"@type": "Person", "name": "new"}, {"@type": "Person", "name": "Virtual Voice"}],
}


def page(*blocks):
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)
    return f"<html><head>{scripts}</head><body></body></html>"


class ShowIdTests(unittest.TestCase):
    def test_link_and_bare_id(self):
        sid = "6d490170d41444017ad8573036509e92d867abb6"
        for value in [f"https://pocketfm.com/show/{sid}", f"https://www.pocketfm.com/show/{sid}?utm=x",
                      f"pocketfm.com/show/{sid}/", sid]:
            with self.subTest(value=value):
                self.assertEqual(pocketfm.parse_show_id(value), sid)

    def test_anything_else_is_rejected(self):
        for value in ["https://evil.example/show/6d490170d41444017ad8573036509e92d867abb6",
                      "https://pocketfm.com/episode/9f19003aad294b25938f436c014e4431", "Supreme Magus", ""]:
            with self.subTest(value=value):
                self.assertEqual(pocketfm.parse_show_id(value), "")


class ParseShowPageTests(unittest.TestCase):
    def test_series_metadata_from_the_podcast_series_block(self):
        faq = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": []}
        show = pocketfm.parse_show_page(page(faq, SUPREME_MAGUS))
        self.assertEqual(show["title"], "Supreme Magus")
        self.assertEqual(show["author"], "Legion20")
        self.assertEqual(show["genre"], "Fantasy")
        self.assertEqual(show["language"], "English")
        self.assertEqual(show["year"], "2023")
        self.assertEqual(show["episodes"], 2286)
        self.assertTrue(show["cover_url"].startswith("https://"))
        self.assertIn("Lith", show["summary"])

    def test_placeholder_creators_are_not_the_author(self):
        show = pocketfm.parse_show_page(page(SHADOW_SLAVE_HINDI))
        self.assertEqual(show["author"], "")
        self.assertEqual(show["language"], "Hindi")

    def test_page_without_a_show_block(self):
        self.assertEqual(pocketfm.parse_show_page(page({"@type": "FAQPage"})), {})
        self.assertEqual(pocketfm.parse_show_page("<html>not json</html>"), {})


class ManualRowTests(unittest.TestCase):
    def test_show_becomes_a_manual_review_row_for_the_series(self):
        show = pocketfm.parse_show_page(page(SUPREME_MAGUS))
        row = pocketfm.show_to_manual_row(show, "https://pocketfm.com/show/6d490170d41444017ad8573036509e92d867abb6")
        self.assertEqual(row["provider"], "pocketfm")
        self.assertEqual(row["series"], "Supreme Magus")
        self.assertEqual(row["authors"], ["Legion20"])
        self.assertEqual(set(row["allowed_edit_modes"]), {"full", "series_only"})
        full = row["chosen_metadata_by_mode"]["full"]
        self.assertEqual((full["title"], full["series"], full["author"], full["genre"]),
                         ("Supreme Magus", "Supreme Magus", "Legion20", "Fantasy"))
        self.assertEqual(full["asin"], "")
        self.assertEqual(row["chosen_metadata_by_mode"]["series_only"]["title"], "")


class FetchShowTests(unittest.TestCase):
    def test_fetch_reads_the_public_show_page(self):
        seen = {}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return page(SUPREME_MAGUS).encode()

        def fake_urlopen(req, timeout):
            seen["url"] = req.full_url
            return Resp()

        with patch.object(pocketfm.urllib.request, "urlopen", side_effect=fake_urlopen):
            show = pocketfm.fetch_show("6d490170d41444017ad8573036509e92d867abb6")
        self.assertEqual(seen["url"], "https://pocketfm.com/show/6d490170d41444017ad8573036509e92d867abb6")
        self.assertEqual(show["title"], "Supreme Magus")


class ShowEndpointTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from app import main
        self.client = TestClient(main.app)
        self.main = main

    def test_link_returns_the_show_as_a_manual_review_row(self):
        show = pocketfm.parse_show_page(page(SUPREME_MAGUS))
        with patch.object(self.main, "fetch_pocketfm_show", return_value=show) as fetch:
            response = self.client.post("/api/pocketfm/show", json={
                "link": "https://pocketfm.com/show/6d490170d41444017ad8573036509e92d867abb6"})
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with("6d490170d41444017ad8573036509e92d867abb6")
        data = response.json()
        self.assertEqual(data["show"]["author"], "Legion20")
        self.assertEqual(data["results"][0]["provider"], "pocketfm")

    def test_a_non_pocketfm_link_is_refused_before_any_fetch(self):
        with patch.object(self.main, "fetch_pocketfm_show") as fetch:
            response = self.client.post("/api/pocketfm/show", json={"link": "https://evil.example/show/x"})
        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    def test_page_without_show_data_is_not_found(self):
        with patch.object(self.main, "fetch_pocketfm_show", return_value={}):
            response = self.client.post("/api/pocketfm/show", json={
                "link": "6d490170d41444017ad8573036509e92d867abb6"})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
