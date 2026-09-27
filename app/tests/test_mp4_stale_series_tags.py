"""LibraForge #289: MP4 tag writer left stale series/subtitle/etc. behind in
©mvn, uppercase freeform atoms (SERIES/SERIES-PART/SUBTITLE/ASIN/ISBN/
PUBLISHER), and soal.

Root cause: mutagen's MP4/ID3 tag dicts key freeform/TXXX entries by their
exact-case name string. This app writes lowercase names ("mvnm"/"mvin"/
"subtitle"/"asin"/"isbn"/"publisher"/"series"/"series-part") while Audible's
own tagger writes uppercase ones for the same semantic fields -- so both
coexisted as separate dict entries, one fresh and one stale, after any edit.
"""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from app.fixer.tagging import (
    mp4_clear_freeform_aliases,
    mp4_set_freeform,
    mp4_set_movement_index,
    id3_clear_txxx_aliases,
    id3_set_txxx,
)

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_mp4_stale_series_tags", "scripts/audible-metadata-fixer-v5.py")


class Mp4ClearFreeformAliasesTests(unittest.TestCase):
    def test_removes_case_variant_regardless_of_dict_key_case(self):
        tags = {"----:com.apple.iTunes:SERIES": [b"stale"], "----:com.apple.iTunes:mvnm": [b"fresh"]}
        mp4_clear_freeform_aliases(tags, ("SERIES",))
        self.assertNotIn("----:com.apple.iTunes:SERIES", tags)
        self.assertIn("----:com.apple.iTunes:mvnm", tags)

    def test_leaves_unrelated_freeform_atoms_alone(self):
        tags = {"----:com.apple.iTunes:isbn": [b"9781111111111"]}
        mp4_clear_freeform_aliases(tags, ("SERIES",))
        self.assertIn("----:com.apple.iTunes:isbn", tags)

    def test_no_op_when_nothing_matches(self):
        tags = {"\xa9nam": ["Title"]}
        mp4_clear_freeform_aliases(tags, ("SERIES",))
        self.assertEqual(tags, {"\xa9nam": ["Title"]})


class Mp4SetFreeformAliasesTests(unittest.TestCase):
    def test_aliases_cleared_even_when_new_value_is_blank(self):
        tags = {"----:com.apple.iTunes:SUBTITLE": [b"stale"]}
        mp4_set_freeform(tags, "subtitle", "", aliases=("SUBTITLE",))
        self.assertNotIn("----:com.apple.iTunes:SUBTITLE", tags)
        self.assertNotIn("----:com.apple.iTunes:subtitle", tags)

    def test_writes_canonical_key_and_clears_alias(self):
        tags = {"----:com.apple.iTunes:SERIES": [b"Old Series"]}
        mp4_set_freeform(tags, "mvnm", "New Series", aliases=("SERIES",))
        self.assertNotIn("----:com.apple.iTunes:SERIES", tags)
        value = tags["----:com.apple.iTunes:mvnm"][0]
        self.assertEqual(bytes(value).decode("utf-8"), "New Series")


class Mp4SetMovementIndexTests(unittest.TestCase):
    def test_sets_integer_list_for_a_clean_sequence(self):
        tags: dict = {}
        mp4_set_movement_index(tags, "3")
        self.assertEqual(tags["\xa9mvi"], [3])

    def test_accepts_whole_number_with_trailing_zero_decimal(self):
        tags: dict = {}
        mp4_set_movement_index(tags, "3.0")
        self.assertEqual(tags["\xa9mvi"], [3])

    def test_blank_clears_existing(self):
        tags = {"\xa9mvi": [3]}
        mp4_set_movement_index(tags, "")
        self.assertNotIn("\xa9mvi", tags)


class Id3ClearTxxxAliasesTests(unittest.TestCase):
    def test_removes_case_variant_desc(self):
        tags = {"TXXX:SERIES": "stale", "TXXX:mvnm": "fresh"}
        id3_clear_txxx_aliases(tags, ("SERIES",))
        self.assertNotIn("TXXX:SERIES", tags)
        self.assertIn("TXXX:mvnm", tags)


def _make_silent_m4a(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "1", "-c:a", "aac", str(path), "-y"],
        check=True,
    )


def _make_silent_mp3(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "1", "-c:a", "libmp3lame", str(path), "-y"],
        check=True,
    )


EDIT_METADATA = {
    "title": "Dune: The Butlerian Jihad",
    "author": "Brian Herbert",
    "narrator": "Scott Brick",
    "series": "Dune",
    "sequence": "1",
    "year": "2002",
    "subtitle": "Legends of Dune, Book 1",
    "genre": "Science Fiction",
    "isbn": "9780765340338",
    "asin": "B0NEWASIN01",
    "publisher": "Tor Books",
}


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class Mp4RealFileStaleTagRepoTests(unittest.TestCase):
    """Reproduces the exact issue #289 scenario against a real m4b: a file
    already carrying Audible's own uppercase freeform atoms + ©mvn + soal
    (simulating how these arrive pre-tagged), then a Manual Review "overwrite"
    edit that changes series/subtitle -- the reported bug is that the stale
    values survived the edit."""

    def _make_pretagged(self) -> Path:
        from mutagen.mp4 import MP4, MP4FreeForm

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "book.m4b"
        _make_silent_m4a(path)

        audio = MP4(str(path))
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        tags["\xa9nam"] = ["Dune: The Butlerian Jihad"]
        tags["\xa9mvn"] = ["DUNE: Legends of Dune"]
        tags["soal"] = ["DUNE: Legends of Dune 1 - Dune: The Butlerian Jihad"]
        tags["----:com.apple.iTunes:SERIES"] = [MP4FreeForm(b"DUNE: Legends of Dune")]
        tags["----:com.apple.iTunes:SERIES-PART"] = [MP4FreeForm(b"1")]
        tags["----:com.apple.iTunes:SUBTITLE"] = [MP4FreeForm(b"Dune: Legends of Dune, Book 1")]
        tags["----:com.apple.iTunes:ASIN"] = [MP4FreeForm(b"B0OLDASIN01")]
        tags["----:com.apple.iTunes:ISBN"] = [MP4FreeForm(b"9781111111111")]
        tags["----:com.apple.iTunes:PUBLISHER"] = [MP4FreeForm(b"Old Publisher")]
        audio.save()
        return path

    def test_overwrite_edit_leaves_no_stale_uppercase_duplicates(self):
        path = self._make_pretagged()
        FIXER.mutagen_write_mp4_tags(path, EDIT_METADATA, backup=False, field_policy="overwrite")

        from mutagen.mp4 import MP4
        tags = MP4(str(path)).tags

        for stale_key in (
            "----:com.apple.iTunes:SERIES",
            "----:com.apple.iTunes:SERIES-PART",
            "----:com.apple.iTunes:SUBTITLE",
            "----:com.apple.iTunes:ASIN",
            "----:com.apple.iTunes:ISBN",
            "----:com.apple.iTunes:PUBLISHER",
        ):
            self.assertNotIn(stale_key, tags, f"stale freeform atom {stale_key} survived the edit")

        self.assertNotIn("soal", tags, "stale album sort-order survived the edit")

        self.assertEqual(bytes(tags["----:com.apple.iTunes:mvnm"][0]).decode("utf-8"), "Dune")
        self.assertEqual(bytes(tags["----:com.apple.iTunes:mvin"][0]).decode("utf-8"), "1")
        self.assertEqual(
            bytes(tags["----:com.apple.iTunes:subtitle"][0]).decode("utf-8"), "Legends of Dune, Book 1"
        )
        self.assertEqual(bytes(tags["----:com.apple.iTunes:asin"][0]).decode("utf-8"), "B0NEWASIN01")
        self.assertEqual(bytes(tags["----:com.apple.iTunes:isbn"][0]).decode("utf-8"), "9780765340338")
        self.assertEqual(bytes(tags["----:com.apple.iTunes:publisher"][0]).decode("utf-8"), "Tor Books")
        self.assertEqual(tags["\xa9mvn"][0], "Dune")
        self.assertEqual(tags["\xa9mvi"], [1])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class Mp3RealFileStaleTagRepoTests(unittest.TestCase):
    def _make_pretagged(self) -> Path:
        from mutagen.id3 import ID3, TXXX

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "book.mp3"
        _make_silent_mp3(path)

        tags = ID3(str(path))
        tags.add(TXXX(encoding=3, desc="SERIES", text=["DUNE: Legends of Dune"]))
        tags.add(TXXX(encoding=3, desc="SERIES-PART", text=["1"]))
        tags.add(TXXX(encoding=3, desc="ASIN", text=["B0OLDASIN01"]))
        tags.add(TXXX(encoding=3, desc="ISBN", text=["9781111111111"]))
        tags.save(str(path))
        return path

    def test_overwrite_edit_leaves_no_stale_uppercase_duplicates(self):
        path = self._make_pretagged()
        FIXER.mutagen_write_mp3_tags(path, EDIT_METADATA, backup=False, field_policy="overwrite")

        from mutagen.id3 import ID3
        tags = ID3(str(path))

        for stale_key in ("TXXX:SERIES", "TXXX:SERIES-PART", "TXXX:ASIN", "TXXX:ISBN"):
            self.assertNotIn(stale_key, tags, f"stale TXXX frame {stale_key} survived the edit")

        self.assertEqual(str(tags["TXXX:series"].text[0]), "Dune")
        self.assertEqual(str(tags["TXXX:series-part"].text[0]), "1")
        self.assertEqual(str(tags["TXXX:asin"].text[0]), "B0NEWASIN01")
        self.assertEqual(str(tags["TXXX:isbn"].text[0]), "9780765340338")


if __name__ == "__main__":
    unittest.main()
