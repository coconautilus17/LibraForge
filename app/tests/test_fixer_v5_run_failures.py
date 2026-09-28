"""Failures from the forced full Metadata Forge run 20260928-231259-50a3d3ef
on /audiobooks/_unorganized, one class per root cause."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub


def _load_fixer():
    spec = importlib.util.spec_from_file_location("fixer_v5_run_failures", ROOT / "scripts/audible-metadata-fixer-v5.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = _load_fixer()


def group_clues(folder, per_file):
    """Run the grouped-book clue builder over files whose own parsed clues are
    `per_file` (one dict per file)."""
    files = [Path(f"{folder}/{i:02d}.mp3") for i in range(1, len(per_file) + 1)]
    base = {"raw_title": "", "title": "", "series": "", "tag_series": "", "book_number": "",
            "book_number_source": "", "author": "", "narrator": "", "album": ""}
    with (
        patch.object(FIXER, "build_search_clues_from_file",
                     side_effect=[{**base, **c} for c in per_file]),
        patch.object(FIXER, "probe_file", return_value=({}, 30.0)),
        patch.object(FIXER, "validate_multi_part_group_files", return_value={}),
    ):
        return FIXER.build_multi_file_search_context(files)[1]


class PartNumbersAreNotABookNumberTests(unittest.TestCase):
    """48 Laws of Power 01..52 and 1177 B.C.'s 1..N.mp3: each part file parsed
    as "series + book N", so the group took an arbitrary part index (10) as
    its book number and the title as its series."""

    def test_distinct_part_numbers_give_no_book_number_or_series(self):
        per_file = [{"title": "48 Laws of Power", "series": "48 Laws of Power",
                     "book_number": str(n), "book_number_source": "path", "author": "Robert Greene"}
                    for n in range(1, 13)]
        clues = group_clues("/u/48 Laws of Power (Unabridged) - Robert Greene", per_file)
        self.assertEqual(clues["book_number"], "")
        self.assertEqual(clues["series"], "")

    def test_a_number_all_parts_agree_on_is_the_book_number(self):
        per_file = [{"title": "Deeper", "series": "Tunnels", "book_number": "2",
                     "book_number_source": "path"} for _ in range(4)]
        clues = group_clues("/u/Deeper", per_file)
        self.assertEqual(clues["book_number"], "2")
        self.assertEqual(clues["series"], "Tunnels")


class LeadingNumberInTitleTests(unittest.TestCase):
    """1177 B.C.: the leading "1177" was stripped as an ordering prefix."""

    def test_title_numbers_are_kept(self):
        for title in ["1177 B.C. The Year Civilization Collapsed", "2001 A Space Odyssey"]:
            with self.subTest(title=title):
                self.assertEqual(FIXER.strip_leading_sequence_from_title(title), title)

    def test_ordering_prefixes_are_still_stripped(self):
        for value, expected in [("01 Deeper", "Deeper"), ("001 Deeper", "Deeper"), ("1 - Deeper", "Deeper"),
                                ("Book 3 - Deeper", "Deeper"), ("2011 - Guns, Germs And Steel", "Guns, Germs And Steel")]:
            with self.subTest(value=value):
                self.assertEqual(FIXER.strip_leading_sequence_from_title(value), expected)


class AuthorInTitleTests(unittest.TestCase):
    """1177 B.C.: "... By Eric H. Cline" named the author, but extraction
    required a trailing book number; a name with an initial is evidence
    enough, while "Death by Black Hole" stays a title."""

    def test_name_with_an_initial_is_extracted(self):
        self.assertEqual(
            FIXER.extract_author_from_title("1177 B.C. The Year Civilization Collapsed By Eric H. Cline"),
            "Eric H. Cline",
        )

    def test_plain_words_after_by_are_not_an_author(self):
        self.assertEqual(FIXER.extract_author_from_title("Death by Black Hole"), "")

    def test_grouped_folder_title_gives_author_and_clean_title(self):
        folder = ("/u/1177 B.C. (Revised and Updated) The Year Civilization Collapsed "
                  "By Eric H. Cline Unabridged Audiobook")
        clues = group_clues(folder, [{"book_number": str(n), "book_number_source": "path"} for n in range(1, 6)])
        self.assertEqual(clues["author"], "Eric H. Cline")
        self.assertEqual(clues["title"], "1177 B.C. (Revised and Updated) The Year Civilization Collapsed")


class AlbumIsNotASeriesTests(unittest.TestCase):
    """Sapiens (album "Sapiens") and Reforged (album "Intra Mundum:
    Reforged"): an album that is the book's own title was taken as the
    series, so Sapiens fell to series_only and Homo Deus scored 0.93 through
    Harari's "Sapiens" umbrella series."""

    def parse(self, **tags):
        return FIXER.parse_title_series_number_from_metadata(tags)

    def test_album_that_is_the_title_is_not_a_series(self):
        self.assertEqual(self.parse(title="Sapiens", album="Sapiens")["series"], "")

    def test_album_that_starts_the_title_is_not_a_series(self):
        parsed = self.parse(title="Intra Mundum: Reforged: A LitRPG Adventure", album="Intra Mundum: Reforged")
        self.assertEqual(parsed["series"], "")

    def test_a_different_album_is_still_a_series_clue(self):
        self.assertEqual(self.parse(title="Soul Harvest", album="Dread Knight")["series"], "Dread Knight")


class ParentheticalSeriesInTitleTests(unittest.TestCase):
    """Reforged's title tag ends "(The Tower Series, Book 2)", its real series."""

    def test_trailing_series_parenthetical_gives_series_number_and_title(self):
        parsed = FIXER.parse_title_series_number_from_metadata({
            "title": "Intra Mundum: Reforged: A LitRPG Adventure (The Tower Series, Book 2)",
            "album": "Intra Mundum: Reforged",
        })
        self.assertEqual(parsed["series"], "The Tower Series")
        self.assertEqual(parsed["book_number"], "2")
        self.assertEqual(parsed["title"], "Intra Mundum: Reforged")

    def test_descriptor_parenthetical_is_not_a_series(self):
        parsed = FIXER.parse_title_series_number_from_metadata(
            {"title": "Family: The Idle System (A LitRPG series, Book 7)"})
        self.assertEqual(parsed["series"], "")
        self.assertEqual(parsed["book_number"], "7")


class TitleIsItsOwnSeriesTests(unittest.TestCase):
    """Sapiens: Audible titles the book "Sapiens" inside series "Sapiens" with
    no number. The title-equals-series special case demanded a numeric
    sequence, so an exact title/author/duration match wrote nothing."""

    SAPIENS = {"asin": "B00VY2KBAM", "title": "Sapiens", "subtitle": "A Brief History of Humankind",
               "authors": [{"name": "Yuval Noah Harari"}], "narrators": [{"name": "Derek Perkins"}],
               "series": [{"title": "Sapiens", "sequence": ""}], "runtime_length_min": 918}

    def test_exact_title_author_and_duration_is_a_full_match(self):
        clues = {"title": "Sapiens", "author": "Yuval Noah Harari", "narrator": "Derek Perkins",
                 "local_duration_minutes": 918.7}
        self.assertEqual(FIXER.metadata_from_product(self.SAPIENS, clues, 1.0)["edit_mode"], "full")

    def test_other_book_in_the_umbrella_series_is_not(self):
        homo_deus = {**self.SAPIENS, "title": "Homo Deus", "runtime_length_min": 894}
        clues = {"title": "Sapiens", "author": "Yuval Noah Harari", "local_duration_minutes": 918.7}
        self.assertNotEqual(FIXER.metadata_from_product(homo_deus, clues, 0.93)["edit_mode"], "full")


class ReadByNarratorTests(unittest.TestCase):
    """The Aeneid: folder "Virgil - The Aeneid (Read by David Collins)", and
    the rip's artist tag is the reader, so every Aeneid was rejected as a
    different author."""

    FOLDER = "/u/Virgil - The Aeneid (Read by David Collins)"

    def test_read_by_folder_names_author_title_and_narrator(self):
        parsed = FIXER.parse_descriptive_book_text("Virgil - The Aeneid (Read by David Collins)")
        self.assertEqual((parsed["author"], parsed["title"], parsed["narrator"]),
                         ("Virgil", "The Aeneid", "David Collins"))

    def test_grouped_book_takes_the_author_from_the_path_not_the_reader(self):
        per_file = [{"title": f"The Aeneid - Part {n:02d}", "author": "David Collins"} for n in range(1, 4)]
        clues = group_clues(self.FOLDER, per_file)
        self.assertEqual(clues["author"], "Virgil")
        self.assertEqual(clues["narrator"], "David Collins")

    def test_single_file_takes_the_author_from_the_path_not_the_reader(self):
        path = Path(f"{self.FOLDER}/Virgil - The Aeneid (Read by David Collins).mp3")
        clues = FIXER.build_search_clues_from_file(path, tags={"title": "The Aeneid", "artist": "David Collins"})
        self.assertEqual(clues["author"], "Virgil")
        self.assertEqual(clues["narrator"], "David Collins")


class OtherCreditTagsTests(unittest.TestCase):
    """Tanya Vol 5/7 ([PZG] rips): album_artist holds the uploader ("Phantom
    Z. Greyfire" / "[PZG]"), artist the narrator, composer the real author
    (Carlo Zen). Any local credit tag may confirm a candidate's author."""

    TANYA_5 = {"asin": "B0B1Q1Z9Z7", "title": "The Saga of Tanya the Evil, Vol. 5",
               "authors": [{"name": "Carlo Zen"}, {"name": "Shinobu Shinotsuki"}],
               "narrators": [{"name": "Shiromi Arserio"}],
               "series": [{"title": "The Saga of Tanya the Evil (light novel)", "sequence": "5"}],
               "runtime_length_min": 643}
    TAGS = {"title": "The Saga of Tanya the Evil, Vol. 05: Abyssus Abyssum Invocat",
            "album_artist": "Phantom Z. Greyfire", "artist": "Shiromi Arserio", "composer": "Carlo Zen"}

    def test_all_credit_tags_are_kept_as_clues(self):
        parsed = FIXER.parse_title_series_number_from_metadata(self.TAGS)
        self.assertEqual(parsed["author"], "Phantom Z. Greyfire")
        self.assertEqual(parsed["credit_names"], ["Phantom Z. Greyfire", "Shiromi Arserio", "Carlo Zen"])

    def test_composer_credit_confirms_the_author(self):
        clues = {"title": "The Saga of Tanya the Evil, Vol. 05: Abyssus Abyssum Invocat",
                 "author": "Phantom Z. Greyfire", "series": "The Saga of Tanya the Evil", "book_number": "5",
                 "book_number_source": "title",
                 "credit_names": ["Phantom Z. Greyfire", "Shiromi Arserio", "Carlo Zen"],
                 "local_duration_minutes": 643.2}
        score = FIXER.score_product_for_metadata(clues, self.TANYA_5, 643.2)
        self.assertGreaterEqual(score, 0.7)
        self.assertEqual(FIXER.metadata_from_product(self.TANYA_5, clues, score)["edit_mode"], "full")

    def test_a_candidate_matching_no_local_credit_still_conflicts(self):
        clues = {"title": "The Saga of Tanya the Evil, Vol. 05", "author": "Phantom Z. Greyfire",
                 "credit_names": ["Phantom Z. Greyfire", "Shiromi Arserio"], "local_duration_minutes": 643.2}
        self.assertEqual(FIXER.score_product_for_metadata(clues, self.TANYA_5, 643.2), 0.0)


class TagProbeTests(unittest.TestCase):
    """Mythos (Unabridged).m4b has artist/album_artist "Stephen Fry", but a
    sidecar snapshot from an earlier run held format_tags {} and was trusted
    on every later run (no title, no author). Opus/OGG keep their tags on
    the audio stream, which the probe never read (Freedman's "Command")."""

    def _ffprobe(self, payload):
        import json
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    def test_stream_tags_fill_what_the_container_lacks(self):
        payload = {"format": {"duration": "60", "tags": {"encoder": "fre:ac"}},
                   "streams": [{"codec_type": "audio", "tags": {"ARTIST": "Sir Lawrence Freedman",
                                                                "TITLE": "Command"}}]}
        with patch.object(FIXER.subprocess, "run", return_value=self._ffprobe(payload)):
            tags, minutes = FIXER.probe_file(Path("/x/Command.opus"))
        self.assertEqual(tags["artist"], "Sir Lawrence Freedman")
        self.assertEqual(tags["encoder"], "fre:ac")
        self.assertEqual(minutes, 1.0)

    def test_container_tags_win_over_stream_tags(self):
        payload = {"format": {"duration": "60", "tags": {"title": "Mythos"}},
                   "streams": [{"codec_type": "audio", "tags": {"title": "Track 1"}}]}
        with patch.object(FIXER.subprocess, "run", return_value=self._ffprobe(payload)):
            tags, _ = FIXER.probe_file(Path("/x/Mythos.m4b"))
        self.assertEqual(tags["title"], "Mythos")

    def _book_with_sidecar(self, tmp, backup):
        import json
        book = Path(tmp) / "Mythos (Unabridged).m4b"
        book.write_bytes(b"")
        (Path(tmp) / "other.m4b").write_bytes(b"")  # not alone: per-file sidecar
        sidecar = book.with_name(book.name + FIXER.LIBRAFORGE_SUFFIX)
        sidecar.write_text(json.dumps({"schema_version": 2, "backup": backup}))
        return book, sidecar

    def test_empty_cached_snapshot_is_not_trusted(self):
        import tempfile
        live = ({"title": "Mythos (Unabridged)", "artist": "Stephen Fry"}, 925.7)
        with tempfile.TemporaryDirectory() as tmp:
            book, _ = self._book_with_sidecar(tmp, {"duration_minutes": 925.7, "format_tags": {}})
            with patch.object(FIXER, "probe_file", return_value=live) as probe:
                tags, minutes, is_live = FIXER.read_tags_and_duration(book)
        probe.assert_called_once()
        self.assertEqual(tags["artist"], "Stephen Fry")
        self.assertTrue(is_live)

    def test_empty_original_backup_is_repaired_when_never_applied(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            book, sidecar = self._book_with_sidecar(tmp, {"duration_minutes": 925.7, "format_tags": {}})
            FIXER.write_original_metadata_backup(book, tags={"artist": "Stephen Fry"}, duration_minutes=925.7)
            backup = json.loads(sidecar.read_text())["backup"]
        self.assertEqual(backup["format_tags"], {"artist": "Stephen Fry"})

    def test_empty_backup_is_repaired_from_a_fresh_probe(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            book, sidecar = self._book_with_sidecar(tmp, {"duration_minutes": 925.7, "format_tags": {}})
            with patch.object(FIXER, "probe_file", return_value=({"artist": "Stephen Fry"}, 925.7)):
                FIXER.write_original_metadata_backup(book)
            backup = json.loads(sidecar.read_text())["backup"]
        self.assertEqual(backup["format_tags"], {"artist": "Stephen Fry"})

    def test_backup_of_an_applied_book_is_never_replaced(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            book, sidecar = self._book_with_sidecar(
                tmp, {"duration_minutes": 925.7, "format_tags": {}, "applied_tags": {"title": "Mythos"}})
            FIXER.write_original_metadata_backup(book, tags={"artist": "Stephen Fry"}, duration_minutes=925.7)
            backup = json.loads(sidecar.read_text())["backup"]
        self.assertEqual(backup["format_tags"], {})


class SeriesThatIsTheBookTests(unittest.TestCase):
    """Postwar via Goodreads: series "Postwar: A History of Europe Since
    1945" #1945 is the book's own title and subtitle."""

    def test_series_equal_to_title_and_subtitle_is_dropped(self):
        product = {"title": "Postwar", "subtitle": "A History of Europe Since 1945",
                   "series": [{"title": "Postwar: A History of Europe Since 1945", "sequence": "1945"}]}
        self.assertEqual(FIXER.get_primary_series(product), ("", ""))

    def test_book_named_after_its_series_keeps_it(self):
        product = {"title": "Dune", "subtitle": "", "series": [{"title": "Dune", "sequence": "1"}]}
        self.assertEqual(FIXER.get_primary_series(product), ("Dune", "1"))


if __name__ == "__main__":
    unittest.main()
