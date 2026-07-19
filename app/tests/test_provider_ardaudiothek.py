"""ARD Audiothek provider verification (abs-agg provider-verification workstream).

Catalog: German public-broadcaster audio content (NDR, BR, Deutschlandradio,
ARD, etc.) -- German-language only per its own description. Live-fetched
successfully, 2026-07-20 (docker exec abs-agg wget -qO-
'http://localhost:3000/ardaudiothek/search?title=Tatort&limit=5') -- real,
working data, unlike Big Finish (broken) and Storytel/Audioteka/BookBeat
(blocked by an upstream required-parameter bug).

Real, distinctive catalog trait confirmed live: this is a public-broadcaster
podcast/radio-show catalog, not a traditional single-author-book catalog.
"author" is frequently a show/segment concept rather than a person's name
(e.g. real result: author "True Crime meets Kultur" for a true-crime podcast
"Kunstverbrechen"), and some real results have no "author" key at all (e.g.
"Tatort Kunst"). This is a genuine source characteristic to be aware of, not
a bug to fix -- there's no cleaner alternative author-like field available.

Real publisher data confirmed present and genuinely varies per entry (NDR,
BR, Deutschlandradio, ARD were all seen live for different real results) --
this is exactly the case the shared publisher fix (issue #254) was written
for: each entry's own real broadcaster must be used, never a single
fabricated "ARD Audiothek" string for every match.

No duration or series field appears in real live results, matching the
declared schema (no duration field declared at all for this provider).
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


# Real fixture, captured live 2026-07-20.
ARD_KUNSTVERBRECHEN = {
    "title": "Kunstverbrechen",
    "author": "True Crime meets Kultur",
    "publisher": "NDR",
    "description": "Lenore Lötsch und Torben Steenbuck rollen spektakuläre Kunstdiebstähle auf.",
    "cover": "https://api.ardmediathek.de/image-service/images/urn:ard:image:4be3fc0f3b3f7b08",
    "genres": ["Kultur"],
    "tags": ["Doku & Reportage", "True Crime", "Geschichte", "Kultur"],
    "language": "de",
}

# Real fixture: a different broadcaster, and no "author" key at all.
ARD_TATORT_KUNST_NO_AUTHOR = {
    "title": "Tatort Kunst",
    "publisher": "Deutschlandradio",
    "description": "Das Kunstgeschäft ist ein verschlossener Milliardenmarkt.",
    "cover": "https://api.ardmediathek.de/image-service/images/urn:ard:image:6042f324cd5466a8",
    "genres": ["Info"],
    "tags": ["Doku & Reportage", "True Crime", "Kultur"],
    "language": "de",
}


class ArdAudiothekStandardizationTests(unittest.TestCase):
    def test_full_meta_shape_and_real_publisher_varies_per_entry(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [ARD_KUNSTVERBRECHEN, ARD_TATORT_KUNST_NO_AUTHOR]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Tatort", base_url="http://abs-agg:3000", provider="ardaudiothek",
            )
        first, second = (r["chosen_metadata"] for r in result["results"])
        # Each real entry's own broadcaster must come through as-is, never a
        # single fabricated "ARD Audiothek" for every result.
        self.assertEqual(first["publisher"], "NDR")
        self.assertEqual(second["publisher"], "Deutschlandradio")
        self.assertEqual(first["language"], "de")
        self.assertEqual(first["genre"], "Kultur")

    def test_missing_author_field_does_not_raise(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [ARD_TATORT_KUNST_NO_AUTHOR]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Tatort Kunst", base_url="http://abs-agg:3000", provider="ardaudiothek",
            )
        self.assertEqual(result["results"][0]["chosen_metadata"]["author"], "")


if __name__ == "__main__":
    unittest.main()
