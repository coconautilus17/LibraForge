"""'Audiobook' is a format label, never a genre (PR #105; LibraForge #306).

#105 added GENRE_BLOCKLIST, but M4B Tool still stamped ©gen="Audiobook" on
every m4b it built -- and ABS fills an empty genre from file tags on first
scan, so every new M4B Tool book arrived with the junk genre. main.py also kept
its own duplicate blocklist, and neither caught the "Audio Book" spelling.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.mp4 import MP4

from app import main
from app.enrichment import compile_series_enrichment
from app.fixer.scoring import GENRE_BLOCKLIST, clean_provider_genres


class GenreBlocklistTests(unittest.TestCase):
    def test_every_spelling_of_audiobook_is_dropped(self):
        self.assertEqual(clean_provider_genres(["Audio Book", "Audiobook", "audio books", "Fantasy"]), ["Fantasy"])

    def test_main_uses_the_shared_blocklist(self):
        self.assertIs(main.GENRE_BLOCKLIST, GENRE_BLOCKLIST)
        self.assertEqual(main._pick_genre(["Audio Book", "Fantasy"]), "Fantasy")

    def test_compile_never_proposes_audiobook(self):
        books = [{"id": "1", "title": "T", "existing_genres": ["Audiobook"], "existing_tags": ["Audio Book"]}]
        out = compile_series_enrichment(books, {}, {}, clean_provider_genres)
        self.assertEqual(out["genre"], [])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class M4BOutputGenreTests(unittest.TestCase):
    def build(self, genre):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "out.m4b"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1",
                        "-c:a", "aac", "-f", "mp4", str(out)], check=True)
        if genre:
            f = MP4(str(out)); f.add_tags() if f.tags is None else None; f.tags["\xa9gen"] = [genre]; f.save()
        return out

    def enforce(self, path):
        main.enforce_m4b_output_metadata(path, main.M4BMetadataForm(title="T", author="A"))
        return MP4(str(path)).tags

    def test_never_stamps_audiobook_on_an_output_without_a_genre(self):
        self.assertNotIn("\xa9gen", self.enforce(self.build(None)))

    def test_strips_an_inherited_audiobook_genre(self):
        self.assertNotIn("\xa9gen", self.enforce(self.build("Audiobook")))

    def test_keeps_a_real_inherited_genre(self):
        self.assertEqual(self.enforce(self.build("Fantasy")).get("\xa9gen"), ["Fantasy"])
