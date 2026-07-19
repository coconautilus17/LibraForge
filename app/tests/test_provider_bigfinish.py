"""Big Finish provider verification (abs-agg provider-verification workstream).

Catalog: Doctor Who/Torchwood/other audio dramas (bigfinish.com). No
required parameters -- unlike Storytel/Audioteka/BookBeat, this one should
be directly queryable.

**Confirmed broken on the live abs-agg instance, 2026-07-20** -- but with a
different symptom than the Storytel/Audioteka/BookBeat parameter bug: every
query returns HTTP 200 with an empty `{"matches": []}`, including well-known
real Big Finish titles ("Spare Parts", "Jubilee", "Torchwood") and even
maximally generic single-word queries ("the", "a", "time") that must match
something if the scraper is functioning at all. Confirmed this is NOT a
systemic connectivity problem with the abs-agg container -- ARD Audiothek
and Die drei ??? (tested back to back, same container, same session) both
return rich real results for their own real queries. This looks like Big
Finish's specific scraper being broken against the real bigfinish.com site
in this abs-agg version, not a LibraForge issue -- flagged upstream, not
fixed here.

Standardization tests use a schema-derived fixture (abs-agg's own published
returnedFields: title, author, narrator, description, cover, isbn, series,
language, publishedYear, publisher, duration) -- Big Finish is one of the
few non-special providers confirmed to genuinely return real publisher data.
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


BIGFINISH_SCHEMA_FIXTURE = {
    "title": "Spare Parts",
    "author": "Marc Platt",
    "narrator": "Peter Davison, Sarah Sutton, Nicholas Briggs",
    "description": "The Fifth Doctor and Nyssa arrive on Mondas, where the Cybermen began.",
    "cover": "https://example.com/cover.jpg",
    "isbn": "9781844351287",
    "series": [{"series": "Doctor Who Main Range", "sequence": "34"}],
    "language": "English",
    "publishedYear": "2002",
    "publisher": "Big Finish Productions",
    "duration": 6300,
}


class BigFinishStandardizationTests(unittest.TestCase):
    def test_full_meta_shape_and_real_publisher_is_used(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [BIGFINISH_SCHEMA_FIXTURE]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Spare Parts", base_url="http://abs-agg:3000", provider="bigfinish",
            )
        meta = result["results"][0]["chosen_metadata"]
        self.assertEqual(meta["title"], "Spare Parts")
        self.assertEqual(meta["author"], "Marc Platt")
        self.assertEqual(meta["series"], "Doctor Who Main Range")
        self.assertEqual(meta["sequence"], "34")
        # Big Finish genuinely returns a real publisher -- must be used
        # verbatim, never overwritten with "Big Finish" (not a
        # SPECIAL_PROVIDER, even though it plausibly could be one -- not
        # independently confirmed the way GraphicAudio/SoundBooth Theater
        # were, so it isn't granted that exception here).
        self.assertEqual(meta["publisher"], "Big Finish Productions")
        self.assertEqual(result["results"][0]["duration_minutes"], 105.0)


if __name__ == "__main__":
    unittest.main()
