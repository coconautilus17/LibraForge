"""Tests for search_abs_agg_candidates (app/main.py): abs-agg (GraphicAudio,
SoundBooth Theater, and other non-Audible catalog) search results.

Regression coverage for issue #230: a match with no real ASIN must not get a
synthetic placeholder written into a field that gets persisted verbatim by
the interactive "Use this match" -> save flow, and every abs-agg result
should carry its source provider's display name as publisher.
"""
import unittest
from unittest.mock import patch


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        import json
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen_for(payload):
    def _open(req, timeout=15):
        return _FakeResp(payload)
    return _open


class AbsAggCandidatesAsinTests(unittest.TestCase):
    def test_match_with_no_real_asin_stays_blank_not_synthetic(self):
        from app.main import search_abs_agg_candidates

        payload = {
            "matches": [
                {"title": "Storm Front", "author": "Jim Butcher"},
            ]
        }
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Storm Front",
                base_url="http://abs-agg:3000",
                provider="soundbooththeater",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["asin"], "")
        self.assertEqual(candidate["chosen_metadata"]["asin"], "")
        self.assertEqual(candidate["chosen_metadata_by_mode"]["full"]["asin"], "")

    def test_match_with_a_real_asin_keeps_it(self):
        from app.main import search_abs_agg_candidates

        payload = {
            "matches": [
                {"title": "Storm Front", "author": "Jim Butcher", "asin": "B0REAL0001"},
            ]
        }
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Storm Front",
                base_url="http://abs-agg:3000",
                provider="soundbooththeater",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["asin"], "B0REAL0001")


class AbsAggCandidatesPublisherTests(unittest.TestCase):
    def test_soundbooth_theater_match_gets_publisher_populated(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [{"title": "Storm Front", "author": "Jim Butcher"}]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Storm Front",
                base_url="http://abs-agg:3000",
                provider="soundbooththeater",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["chosen_metadata"]["publisher"], "Soundbooth Theater")
        self.assertEqual(
            candidate["chosen_metadata_by_mode"]["full"]["publisher"], "Soundbooth Theater",
        )

    def test_graphicaudio_match_gets_publisher_populated(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [{"title": "Storm Front", "author": "Jim Butcher"}]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Storm Front",
                base_url="http://abs-agg:3000",
                provider="graphicaudio",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["chosen_metadata"]["publisher"], "Graphic Audio")

    def test_non_special_provider_with_no_real_publisher_stays_blank(self):
        # Only GraphicAudio/SoundBooth Theater are confirmed to genuinely be
        # their own publisher (PR #234). Every other abs-agg provider
        # (LibriVox, Storytel, Audioteka, BookBeat, Big Finish, ARD Audiothek,
        # Die drei ???) must never get its own display name fabricated as
        # "publisher" -- most of them aren't publishers at all (LibriVox is
        # volunteer public-domain readings; BookBeat is a distribution
        # platform; Die drei ??? is a franchise name, not an imprint).
        from app.main import search_abs_agg_candidates

        payload = {"matches": [{"title": "Storm Front", "author": "Jim Butcher"}]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Storm Front",
                base_url="http://abs-agg:3000",
                provider="librivox",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["chosen_metadata"]["publisher"], "")
        self.assertEqual(candidate["chosen_metadata_by_mode"]["full"]["publisher"], "")

    def test_non_special_provider_with_a_real_publisher_field_uses_it(self):
        # ARD Audiothek, Audioteka, Big Finish, and Storytel genuinely return
        # a publisher field (confirmed live against abs-agg's own /providers
        # schema) -- that real data must be used, not discarded.
        from app.main import search_abs_agg_candidates

        payload = {"matches": [{
            "title": "Some Book", "author": "Some Author", "publisher": "Real Publisher House",
        }]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Some Book",
                base_url="http://abs-agg:3000",
                provider="bigfinish",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["chosen_metadata"]["publisher"], "Real Publisher House")


class AbsAggCandidatesLanguageTests(unittest.TestCase):
    def test_real_language_field_is_carried_through(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [{
            "title": "Ein Buch", "author": "Autor", "language": "german",
        }]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Ein Buch",
                base_url="http://abs-agg:3000",
                provider="ardaudiothek",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["chosen_metadata"]["language"], "german")
        self.assertEqual(candidate["chosen_metadata_by_mode"]["full"]["language"], "german")

    def test_missing_language_field_is_blank_not_absent(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [{"title": "Some Book", "author": "Some Author"}]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Some Book",
                base_url="http://abs-agg:3000",
                provider="bookbeat",
            )
        candidate = result["results"][0]
        self.assertEqual(candidate["chosen_metadata"]["language"], "")


if __name__ == "__main__":
    unittest.main()
