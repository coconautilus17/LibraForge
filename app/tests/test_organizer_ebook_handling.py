import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_ebook_handling", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def write_ebook_sidecar(path: Path, *, title: str, author: str, series: str = "", sequence: str = "") -> None:
    path.write_text(json.dumps({
        "schema_version": 2,
        "media_type": "ebook",
        "sidecar": {"book": {"title": title, "author": author, "series": series, "sequence": sequence}},
    }), encoding="utf-8")


class BuildEbookBookItemsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_standalone_epub_is_its_own_item(self):
        epub = self.root / "Some Author - A Book.epub"
        epub.write_bytes(b"fake epub")
        items = ORGANIZER.build_ebook_book_items(self.root)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.kind, "loose_file")
        self.assertEqual(item.media_type, "ebook")
        self.assertEqual(item.source_path, epub)
        self.assertIsNone(item.paired_format_path)

    def test_epub_and_pdf_sharing_a_bucket_folder_stem_pair_into_one_item(self):
        (self.root / "epub").mkdir()
        (self.root / "pdf").mkdir()
        epub = self.root / "epub" / "A Book.epub"
        pdf = self.root / "pdf" / "A Book.pdf"
        epub.write_bytes(b"fake epub")
        pdf.write_bytes(b"fake pdf")
        items = ORGANIZER.build_ebook_book_items(self.root)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source_path, epub)  # epub preferred as canonical
        self.assertEqual(item.paired_format_path, pdf)

    def test_ignores_audio_files(self):
        (self.root / "book.m4b").write_bytes(b"fake audio")
        self.assertEqual(ORGANIZER.build_ebook_book_items(self.root), [])

    def test_still_discovers_an_epub_with_a_same_stem_audiobook_present(self):
        # The whole feature is pointless if a same-stem audiobook makes the
        # ebook invisible -- confirms discovery isn't blocked by one; see
        # CompanionFilesForNeverClaimsAnEbookTests for the other half (the
        # audiobook must not claim it as a companion either).
        (self.root / "Some Novel.m4b").write_bytes(b"fake audio")
        epub = self.root / "Some Novel.epub"
        epub.write_bytes(b"fake epub")
        items = ORGANIZER.build_ebook_book_items(self.root)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_path, epub)


class MetadataFromSidecarEbookTests(unittest.TestCase):
    """Regression test: write_ebook_sidecar() writes payload["sidecar"]["book"],
    but metadata_from_sidecar() only ever checked the (unwritten) top-level
    payload["book"] -- 100% dead code before this fix."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_the_nested_sidecar_book_shape(self):
        epub = self.root / "Book.epub"
        epub.write_bytes(b"fake epub")
        write_ebook_sidecar(
            self.root / "Book.epub.libraforge.json",
            title="A Book", author="Some Author", series="A Series", sequence="2",
        )
        item = ORGANIZER.BookItem("loose_file", epub, [epub], epub, media_type="ebook")
        metadata = ORGANIZER.metadata_from_sidecar(item)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["title"], "A Book")
        self.assertEqual(metadata["author"], "Some Author")
        self.assertEqual(metadata["series"], "A Series")
        self.assertEqual(metadata["book_number"], "002")

    def test_still_reads_the_existing_marker_audible_shape_unchanged(self):
        # Regression guard: the fix must not disturb the audiobook branch.
        audio = self.root / "Book.m4b"
        audio.write_bytes(b"fake audio")
        (self.root / "libraforge.json").write_text(json.dumps({
            "marker": {"audible": {"title": "Real Title", "author": "Real Author", "series": "", "sequence": ""}},
        }), encoding="utf-8")
        item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
        metadata = ORGANIZER.metadata_from_sidecar(item)
        self.assertEqual(metadata["title"], "Real Title")


class SeriesDirLabelAndTargetDirEbookTests(unittest.TestCase):
    def test_series_dir_label_appends_ebook_suffix(self):
        metadata = {"series": "Land of the Elementals", "media_type": "ebook"}
        self.assertEqual(ORGANIZER.series_dir_label(metadata), "Land of the Elementals - EBOOK")

    def test_series_dir_label_without_ebook_is_unaffected(self):
        metadata = {"series": "Land of the Elementals", "media_type": "audiobook"}
        self.assertEqual(ORGANIZER.series_dir_label(metadata), "Land of the Elementals")

    def test_series_dir_label_combines_edition_tag_and_ebook_suffix(self):
        metadata = {"series": "His Dark Materials", "edition_tag": "Dramatized", "media_type": "ebook"}
        self.assertEqual(ORGANIZER.series_dir_label(metadata), "His Dark Materials [Dramatized] - EBOOK")

    def test_build_default_target_dir_with_series(self):
        metadata = {
            "author": "Aaron Oster", "series": "Land of the Elementals", "media_type": "ebook",
            "book_number": "001", "sequence_label": "Book", "title": "Box Set",
        }
        target = ORGANIZER.build_default_target_dir(Path("/library"), metadata)
        self.assertEqual(target, Path("/library/Aaron Oster/Land of the Elementals - EBOOK/Book 1 - Box Set"))

    def test_build_default_target_dir_without_series(self):
        metadata = {
            "author": "Some Author", "series": "", "media_type": "ebook",
            "book_number": "", "sequence_label": "", "title": "A Standalone Book",
        }
        target = ORGANIZER.build_default_target_dir(Path("/library"), metadata)
        self.assertEqual(target, Path("/library/Some Author/A Standalone Book - EBOOK"))

    def test_audiobook_metadata_is_completely_unaffected(self):
        metadata = {
            "author": "Some Author", "series": "", "media_type": "audiobook",
            "book_number": "", "sequence_label": "", "title": "A Standalone Book",
        }
        target = ORGANIZER.build_default_target_dir(Path("/library"), metadata)
        self.assertEqual(target, Path("/library/Some Author/A Standalone Book"))


class CompanionFilesForEbookSelfReferenceTests(unittest.TestCase):
    """Regression test for a real bug: COMPANION_SIDE_EXTENSIONS includes
    .epub/.pdf (for an ebook riding alongside an *audiobook* of the same
    stem) -- when the source file's own extension is already one of those
    (a standalone ebook item), with_suffix(ext) trivially resolved back to
    itself for that extension, so companion_files_for() returned the source
    file as its own companion. The primary move then succeeded, and the
    second, bogus "move" of the (already-gone) source file failed."""

    def test_an_epub_is_never_returned_as_its_own_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "Some Novel.epub"
            epub.write_bytes(b"fake epub")
            self.assertEqual(ORGANIZER.companion_files_for(epub), [])

    def test_a_real_sidecar_companion_is_still_found_alongside_an_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "Some Novel.epub"
            epub.write_bytes(b"fake epub")
            sidecar = root / "Some Novel.epub.libraforge.json"
            sidecar.write_text("{}", encoding="utf-8")
            self.assertEqual(ORGANIZER.companion_files_for(epub), [sidecar])


class CompanionFilesForNeverClaimsAnEbookTests(unittest.TestCase):
    """Regression test for a real bug: COMPANION_SIDE_EXTENSIONS used to
    include .epub/.pdf so an ebook could ride alongside an audiobook of the
    same stem -- but build_ebook_book_items() now *always* discovers and
    organizes every standalone ebook into its own "- EBOOK" folder,
    unconditionally, per an explicit design decision (an ebook is never
    left bundled with an audiobook, even when one exists). With .epub/.pdf
    still in COMPANION_SIDE_EXTENSIONS, an audiobook's own move claimed a
    same-stem epub as ITS companion first -- dropping it into the
    audiobook's folder with no "- EBOOK" suffix at all -- and the ebook's
    own independent move then failed since the file was already gone."""

    def test_a_same_stem_epub_is_not_claimed_as_the_audiobooks_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Some Novel.m4b"
            audio.write_bytes(b"fake audio")
            epub = root / "Some Novel.epub"
            epub.write_bytes(b"fake epub")
            self.assertEqual(ORGANIZER.companion_files_for(audio), [])

    def test_a_same_stem_pdf_is_not_claimed_as_the_audiobooks_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Some Novel.m4b"
            audio.write_bytes(b"fake audio")
            pdf = root / "Some Novel.pdf"
            pdf.write_bytes(b"fake pdf")
            self.assertEqual(ORGANIZER.companion_files_for(audio), [])

    def test_mobi_and_azw3_still_ride_along_as_companions(self):
        # Unaffected: is_ebook_file()/build_ebook_book_items() only ever
        # recognize .epub/.pdf, so .mobi/.azw3 have no independent
        # organizing path of their own to collide with.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Some Novel.m4b"
            audio.write_bytes(b"fake audio")
            mobi = root / "Some Novel.mobi"
            mobi.write_bytes(b"fake mobi")
            self.assertEqual(ORGANIZER.companion_files_for(audio), [mobi])

    def test_a_cover_image_still_rides_along_as_the_audiobooks_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Some Novel.m4b"
            audio.write_bytes(b"fake audio")
            cover = root / "Some Novel.jpg"
            cover.write_bytes(b"fake jpg")
            self.assertEqual(ORGANIZER.companion_files_for(audio), [cover])


class ResolveNamingTokensEbookTests(unittest.TestCase):
    """The real (non-use_default_scheme) path renders {series}/{title} via
    resolve_naming_tokens()/render_naming_template(), not series_dir_label()/
    build_default_target_dir() -- those only apply under the explicit
    use_default_scheme=True toggle. This is the actual default flow."""

    def test_series_token_gets_the_ebook_suffix(self):
        metadata = {"series": "Dragon Chronicles", "title": "Some Novel", "media_type": "ebook"}
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["series"], "Dragon Chronicles - EBOOK")
        self.assertEqual(tokens["title"], "Some Novel")

    def test_title_token_gets_the_suffix_when_there_is_no_series(self):
        metadata = {"series": "", "title": "Some Novel", "media_type": "ebook"}
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["title"], "Some Novel - EBOOK")

    def test_audiobook_tokens_are_unaffected(self):
        metadata = {"series": "Dragon Chronicles", "title": "Some Novel", "media_type": "audiobook"}
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["series"], "Dragon Chronicles")
        self.assertEqual(tokens["title"], "Some Novel")


class ExecutePlannedMoveEbookPairTests(unittest.TestCase):
    def test_paired_format_moves_alongside_the_primary_ebook_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "_unorganized"
            source_dir.mkdir()
            epub = source_dir / "A Book.epub"
            pdf = source_dir / "A Book.pdf"
            epub.write_bytes(b"fake epub")
            pdf.write_bytes(b"fake pdf")

            target_dir = root / "Some Author" / "A Book - EBOOK"
            target_path = target_dir / "A Book.epub"
            move = {
                "kind": "loose_file",
                "source": epub,
                "target": target_path,
                "companions": [pdf],
            }
            ORGANIZER.execute_planned_move(
                move, merge_existing_targets=False, remove_empty_dirs=False, root=root
            )
            self.assertTrue(target_path.is_file())
            self.assertTrue((target_dir / "A Book.pdf").is_file())
            self.assertFalse(pdf.exists())


if __name__ == "__main__":
    unittest.main()
