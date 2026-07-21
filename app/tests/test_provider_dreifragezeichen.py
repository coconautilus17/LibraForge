"""Die drei ??? provider verification (abs-agg provider-verification workstream).

Catalog: the German children's mystery-audio-drama franchise "Die drei ???"
(main series, specials, kids spin-off), sourced from dreimetadaten.de.
Live-fetched successfully, 2026-07-20 (docker exec abs-agg wget -qO-
'http://localhost:3000/dreifragezeichen/search?title=Der+Super-Papagei&limit=5')
-- real, working data.

**Real bug found live**: every other abs-agg provider with duration
(LibriVox, Storytel, Audioteka, Big Finish) returns it in *seconds*, and
search_abs_agg_candidates() unconditionally divides by 60. Die drei ???'s
real duration values are already in *minutes* -- confirmed by the actual
numbers: episode "001" = 52.4, the "Spezial" edition = 90, episode "036" =
48.27, episode "002" = 45.65, episode "003" = 45.8. These are textbook real
runtimes for ~45-90 minute audio-drama episodes; as raw seconds they'd mean
a 52-second and a 90-second "episode," which is absurd for this franchise.
Dividing these by 60 again (the existing blanket behavior) would show a
52-minute episode as ~1 minute in the UI. No franchise name is used as
publisher either (it isn't one -- has no publisher field at all in its real
schema, and "Die drei ???" is a media franchise, not an imprint).
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


# Real fixture, captured live 2026-07-20 ("und der Super-Papagei", episode 1).
DDF_SUPER_PAPAGEI = {
    "title": "und der Super-Papagei",
    "subtitle": "Die drei ??? 001",
    "author": "Robert Arthur",
    "narrator": "Peter Pasetti, Oliver Rohrbeck, Jens Wawrczeck",
    "publishedYear": "1979",
    "description": "Der Auftrag an die drei Detektive hört sich recht harmlos an...",
    "cover": "http://a1.mzstatic.com/us/r30/Music41/v4/c9/3f/e4/source",
    "series": [{"series": "Die drei ???", "sequence": "1"}],
    "language": "de",
    "duration": 52.4,
}


class DreiFragezeichenStandardizationTests(unittest.TestCase):
    def test_full_meta_shape_no_fabricated_publisher(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [DDF_SUPER_PAPAGEI]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Super-Papagei", base_url="http://abs-agg:3000", provider="dreifragezeichen",
            )
        meta = result["results"][0]["chosen_metadata"]
        self.assertEqual(meta["title"], "und der Super-Papagei")
        self.assertEqual(meta["series"], "Die drei ???")
        self.assertEqual(meta["sequence"], "1")
        self.assertEqual(meta["language"], "de")
        # No publisher field exists for this source and it is not a
        # SPECIAL_PROVIDER (a franchise name, not an imprint) -- must stay blank.
        self.assertEqual(meta["publisher"], "")

    def test_real_duration_is_already_in_minutes_not_seconds(self):
        # The actual bug: 52.4 is a real ~52-minute episode runtime, not 52.4
        # seconds. Dividing by 60 (the blanket behavior every other provider
        # needs) would wrongly report ~0.87 minutes for a 52-minute episode.
        from app.main import search_abs_agg_candidates

        payload = {"matches": [DDF_SUPER_PAPAGEI]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Super-Papagei", base_url="http://abs-agg:3000", provider="dreifragezeichen",
            )
        self.assertEqual(result["results"][0]["duration_minutes"], 52.4)


if __name__ == "__main__":
    unittest.main()
