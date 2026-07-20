"""audible_lookup_chapters: a general-purpose full-chapter-list lookup against
Audible's content/{asin}/metadata?response_groups=chapter_info endpoint
(distinct from catalog/products, used nowhere else in this codebase). Never
guesses -- returns None on inaccurate/missing/failed data rather than
fabricating chapters. Reusable across features (Chapter Forge's Audible
detection backend is the first caller; the audiosilo-books export design
also plans a chapter-count helper that should build on this rather than
duplicate the API call).
"""
import unittest
from unittest.mock import MagicMock

from app.fixer.search import audible_lookup_chapters


def _client(response=None, exc=None):
    client = MagicMock()
    if exc is not None:
        client.get.side_effect = exc
    else:
        client.get.return_value = response
    return client


class AudibleLookupChaptersTests(unittest.TestCase):
    def test_accurate_chapter_info_returns_full_list(self):
        client = _client(response={
            "content_metadata": {
                "chapter_info": {
                    "is_accurate": True,
                    "chapters": [
                        {"title": "Chapter 1", "start_offset_ms": 0, "length_ms": 120000},
                        {"title": "Chapter 2", "start_offset_ms": 120000, "length_ms": 95000},
                    ],
                }
            }
        })
        result = audible_lookup_chapters(client, "B017V4IM1G")
        self.assertEqual(result, [
            {"title": "Chapter 1", "start_ms": 0, "length_ms": 120000},
            {"title": "Chapter 2", "start_ms": 120000, "length_ms": 95000},
        ])

    def test_calls_the_dedicated_chapter_endpoint_not_catalog_products(self):
        client = _client(response={
            "content_metadata": {"chapter_info": {"is_accurate": True, "chapters": []}}
        })
        audible_lookup_chapters(client, "B017V4IM1G")
        client.get.assert_called_once_with(
            "content/B017V4IM1G/metadata",
            params={"response_groups": "chapter_info"},
        )

    def test_inaccurate_returns_none(self):
        client = _client(response={
            "content_metadata": {
                "chapter_info": {"is_accurate": False, "chapters": [{"title": "x"}]}
            }
        })
        self.assertIsNone(audible_lookup_chapters(client, "B017V4IM1G"))

    def test_missing_chapter_info_returns_none(self):
        client = _client(response={"content_metadata": {}})
        self.assertIsNone(audible_lookup_chapters(client, "B017V4IM1G"))

    def test_request_error_returns_none(self):
        client = _client(exc=RuntimeError("404 Not Found"))
        self.assertIsNone(audible_lookup_chapters(client, "B000000000"))

    def test_empty_asin_returns_none_without_calling_client(self):
        client = _client()
        self.assertIsNone(audible_lookup_chapters(client, ""))
        client.get.assert_not_called()

    def test_asin_uppercased_in_request_path(self):
        client = _client(response={
            "content_metadata": {"chapter_info": {"is_accurate": True, "chapters": []}}
        })
        audible_lookup_chapters(client, "b017v4im1g")
        client.get.assert_called_once_with(
            "content/B017V4IM1G/metadata",
            params={"response_groups": "chapter_info"},
        )

    def test_missing_optional_chapter_fields_default_safely(self):
        client = _client(response={
            "content_metadata": {
                "chapter_info": {
                    "is_accurate": True,
                    "chapters": [{}],
                }
            }
        })
        result = audible_lookup_chapters(client, "B017V4IM1G")
        self.assertEqual(result, [{"title": "", "start_ms": 0, "length_ms": 0}])


if __name__ == "__main__":
    unittest.main()
