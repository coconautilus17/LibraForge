import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIX = load_module("fix_series_book_number_suffix", "scripts/fix-series-book-number-suffix.py")


def write_libraforge_json(path: Path, series: str, sequence: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 2,
        "marker": {"audible": {"asin": "X", "title": "T", "author": "A", "series": series, "sequence": sequence}},
    }), encoding="utf-8")


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


def write_m4b(path: Path, series: str, sequence: str = "") -> None:
    from mutagen.mp4 import MP4

    path.parent.mkdir(parents=True, exist_ok=True)
    _make_silent_m4a(path)
    audio = MP4(str(path))
    FIX.mp4_set_freeform(audio.tags, "mvnm", series)
    if sequence:
        FIX.mp4_set_freeform(audio.tags, "mvin", sequence)
    audio.save()


def write_mp3(path: Path, series: str, sequence: str = "") -> None:
    from mutagen.id3 import ID3

    path.parent.mkdir(parents=True, exist_ok=True)
    _make_silent_mp3(path)
    audio = ID3(str(path))
    FIX.id3_set_txxx(audio, "mvnm", series)
    if sequence:
        FIX.id3_set_txxx(audio, "mvin", sequence)
        FIX.id3_set_txxx(audio, "series-part", sequence)
    audio.save()


class PlanSeriesNumberChangesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self):
        return FIX.plan_series_number_changes(self.root)

    def test_book_word_suffix_with_matching_sequence_is_clean_only(self):
        write_libraforge_json(self.root / "Blight" / "Book 1" / "libraforge.json", "Blight, Book #1", "1")
        changes = self._plan()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["status"], "CLEAN_ONLY")
        self.assertEqual(changes[0]["new_series"], "Blight")

    def test_book_word_suffix_with_empty_sequence_fills_it(self):
        write_libraforge_json(self.root / "Blight" / "Book 1" / "libraforge.json", "Blight, Book #1", "")
        changes = self._plan()
        self.assertEqual(changes[0]["status"], "FILL_SEQUENCE")
        self.assertEqual(changes[0]["new_sequence"], "1")

    def test_book_word_suffix_conflicting_with_a_different_sequence_is_flagged_not_fixed(self):
        write_libraforge_json(self.root / "Author" / "Book 7" / "libraforge.json", "Wax and Wayne, Book #4", "7")
        changes = self._plan()
        self.assertEqual(changes[0]["status"], "CONFLICT")
        self.assertIsNone(changes[0]["new_sequence"])

    def test_bare_number_with_a_plain_sibling_series_is_cleaned(self):
        # "#" right before the number is the separator that makes this
        # worth matching at all -- see the no-separator tests below.
        write_libraforge_json(self.root / "Author" / "Book 1" / "libraforge.json", "Azarinth Healer", "1")
        write_libraforge_json(self.root / "Author" / "Book 4" / "libraforge.json", "Azarinth Healer #4", "4")
        changes = self._plan()
        fixed = next(c for c in changes if c["old_series"] == "Azarinth Healer #4")
        self.assertEqual(fixed["status"], "CLEAN_ONLY")
        self.assertEqual(fixed["new_series"], "Azarinth Healer")

    def test_comma_and_dash_separators_are_also_matched(self):
        write_libraforge_json(self.root / "Author" / "Book 1" / "libraforge.json", "Azarinth Healer", "1")
        write_libraforge_json(self.root / "Author" / "Book 4" / "libraforge.json", "Azarinth Healer, 4", "4")
        write_libraforge_json(self.root / "Author" / "Book 5" / "libraforge.json", "Azarinth Healer-5", "5")
        changes = self._plan()
        self.assertEqual({c["new_series"] for c in changes}, {"Azarinth Healer"})
        self.assertEqual({c["status"] for c in changes}, {"CLEAN_ONLY"})

    def test_a_number_with_only_a_space_before_it_is_never_matched(self):
        # No "#", "," or "-" -- this is deliberately outside Pattern B
        # entirely, not even flagged as UNCERTAIN. A real title/series can
        # end in a digit ("Catch 22", "Beacon 23", "Ultimate Level 1") and
        # nothing at this level can tell that apart from a duplicated book
        # number, so it is simply never touched. A plain sibling being
        # present too doesn't change that -- the separator gate comes first.
        write_libraforge_json(self.root / "Author" / "Book 1" / "libraforge.json", "Catch 22", "")
        write_libraforge_json(self.root / "Author" / "Book 2" / "libraforge.json", "Catch", "2")
        self.assertEqual(self._plan(), [])

    def test_bare_number_with_no_sibling_evidence_is_uncertain_and_not_touched(self):
        write_libraforge_json(self.root / "Author" / "Book 1" / "libraforge.json", "Ard's Oath #3", "1")
        changes = self._plan()
        self.assertEqual(changes[0]["status"], "UNCERTAIN")

    def test_identical_wrong_text_across_different_real_books_keeps_each_books_own_sequence(self):
        # A plain, number-free sibling ("Azarinth Healer") is what actually
        # proves the "1" is a duplicated book-position rather than just part
        # of the series' real name -- see the next test for what happens
        # without one.
        write_libraforge_json(self.root / "Author" / "Book 0" / "libraforge.json", "Azarinth Healer", "0")
        for n in ("6", "7", "10", "11"):
            write_libraforge_json(self.root / "Author" / f"Book {n}" / "libraforge.json", "Azarinth Healer #1", n)
        changes = self._plan()
        fixed = [c for c in changes if c["old_series"] == "Azarinth Healer #1"]
        self.assertEqual(len(fixed), 4)
        for change in fixed:
            self.assertEqual(change["status"], "SAME_TEXT_DIFFERENT_BOOKS")
            self.assertEqual(change["new_series"], "Azarinth Healer")
            self.assertIsNone(change["new_sequence"])

    def test_omnibus_book_range_is_never_split_as_a_bare_number(self):
        # Regression test for a real false-positive: "Beacon 23, Book #1-5"
        # is an omnibus/bundle description (books 1-5 collected), not a
        # duplicated book number -- the "-" inside the range must not be
        # mistaken for Pattern B's separator.
        write_libraforge_json(self.root / "Author" / "Book 1" / "libraforge.json", "Beacon 23, Book #1-5", "23")
        self.assertEqual(self._plan(), [])

    def test_identical_numbered_text_with_no_separator_is_never_matched(self):
        # Regression test for a real bug: 11 real "Ultimate Level 1" books
        # were wrongly cleaned to "Ultimate Level" because the same text
        # recurring with 11 different real sequence numbers (1-11) looked
        # like proof of a copy-pasted duplicate -- but that is exactly what
        # a normal, correctly-numbered series looks like when its own name
        # happens to end in a digit. Audiobookshelf's independently-sourced
        # metadata.json confirmed "Ultimate Level 1" was the real series
        # name all along. Since there is no "#"/","/"-" separator, this
        # pattern is no longer matched at all -- not even as UNCERTAIN.
        for n in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"):
            write_libraforge_json(self.root / "Author" / f"Book {n}" / "libraforge.json", "Ultimate Level 1", n)
        self.assertEqual(self._plan(), [])

    def test_metadata_json_series_field_is_never_touched(self):
        # Audiobookshelf's own "Name #N" format -- must be left completely alone.
        path = self.root / "Author" / "Book 1"
        path.mkdir(parents=True)
        (path / "metadata.json").write_text(json.dumps({"series": ["Azarinth Healer #1"]}), encoding="utf-8")
        changes = self._plan()
        self.assertEqual(changes, [])

    def test_ordinary_series_produces_no_change(self):
        write_libraforge_json(self.root / "Author" / "Book 1" / "libraforge.json", "Ordinary Series", "1")
        self.assertEqual(self._plan(), [])


class ApplyAndRevertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "Author" / "Book 1" / "libraforge.json"
        write_libraforge_json(self.path, "Blight, Book #1", "")

    def tearDown(self):
        self.tmp.cleanup()

    def test_apply_writes_cleaned_series_and_fills_sequence(self):
        change = FIX.plan_series_number_changes(self.root)[0]
        FIX.apply_change(change)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        marker = data["marker"]["audible"]
        self.assertEqual(marker["series"], "Blight")
        self.assertEqual(marker["sequence"], "1")
        # Nothing else in the sidecar was disturbed.
        self.assertEqual(marker["asin"], "X")

    def test_revert_restores_the_original_values(self):
        change = FIX.plan_series_number_changes(self.root)[0]
        FIX.apply_change(change)
        log_path = self.root / "log.jsonl"
        log_path.write_text(json.dumps(change) + "\n", encoding="utf-8")
        FIX.revert(log_path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        marker = data["marker"]["audible"]
        self.assertEqual(marker["series"], "Blight, Book #1")
        self.assertEqual(marker["sequence"], "")


class MetadataJsonSeriesSyncTests(unittest.TestCase):
    """Regression test for a real bug: 14 real books were fixed (marker
    series/sequence and embedded tags both correct) but still showed the
    old dirty series text afterward -- some of it doubled, "Name, Book #N
    #N" -- because metadata.json's "Name #N" field (Audiobookshelf's own
    format, written once at match time by write_audiobookshelf_metadata_json
    using the same "{series} #{sequence}" formula) was never regenerated
    once the marker it was derived from got fixed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.book_dir = self.root / "Author" / "Book 1"
        self.libraforge_json = self.book_dir / "libraforge.json"
        self.metadata_json = self.book_dir / "metadata.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_metadata_json(self, series: str) -> None:
        self.metadata_json.write_text(json.dumps({"title": "T", "series": [series]}), encoding="utf-8")

    def test_apply_regenerates_the_doubled_hash_number_metadata_json_entry(self):
        # The real "Wax and Wayne, Book #4" / existing seq 7 case: metadata.json
        # had baked in "Wax and Wayne, Book #4 #7" (dirty series + its own
        # "#{sequence}" appended) before the marker was ever fixed.
        write_libraforge_json(self.libraforge_json, "Wax and Wayne, Book #4", "7")
        self._write_metadata_json("Wax and Wayne, Book #4 #7")

        change = FIX.plan_series_number_changes(self.root)[0]
        FIX.apply_change(change)

        data = json.loads(self.metadata_json.read_text(encoding="utf-8"))
        self.assertEqual(data["series"], ["Wax and Wayne #7"])
        # Nothing else in metadata.json was disturbed.
        self.assertEqual(data["title"], "T")

    def test_apply_regenerates_metadata_json_when_sequence_gets_filled(self):
        write_libraforge_json(self.libraforge_json, "Blight, Book #1", "")
        self._write_metadata_json("Blight, Book #1")

        change = FIX.plan_series_number_changes(self.root)[0]
        FIX.apply_change(change)

        data = json.loads(self.metadata_json.read_text(encoding="utf-8"))
        self.assertEqual(data["series"], ["Blight #1"])

    def test_revert_also_resyncs_metadata_json_back_to_the_original(self):
        write_libraforge_json(self.libraforge_json, "Blight, Book #1", "")
        self._write_metadata_json("Blight, Book #1")

        change = FIX.plan_series_number_changes(self.root)[0]
        FIX.apply_change(change)
        log_path = self.root / "log.jsonl"
        log_path.write_text(json.dumps(change) + "\n", encoding="utf-8")
        FIX.revert(log_path)

        data = json.loads(self.metadata_json.read_text(encoding="utf-8"))
        self.assertEqual(data["series"], ["Blight, Book #1"])

    def test_no_metadata_json_present_is_a_no_op(self):
        write_libraforge_json(self.libraforge_json, "Blight, Book #1", "")
        change = FIX.plan_series_number_changes(self.root)[0]
        FIX.apply_change(change)  # must not raise just because metadata.json is absent
        self.assertFalse(self.metadata_json.exists())

    def test_already_in_sync_is_left_untouched(self):
        write_libraforge_json(self.libraforge_json, "Blight, Book #1", "")
        self._write_metadata_json("Blight #1")
        before = self.metadata_json.read_text(encoding="utf-8")

        change = FIX.plan_series_number_changes(self.root)[0]
        FIX.apply_change(change)

        self.assertEqual(self.metadata_json.read_text(encoding="utf-8"), before)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class EmbeddedTagScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_only_by_default_ignores_a_dirty_embedded_tag(self):
        write_m4b(self.root / "Author" / "Book 1" / "book.m4b", "Blight, Book #1", "")
        self.assertEqual(FIX.plan_series_number_changes(self.root), [])

    def test_include_tags_finds_an_m4b_book_word_suffix(self):
        write_m4b(self.root / "Author" / "Book 1" / "book.m4b", "Blight, Book #1", "1")
        changes = FIX.plan_series_number_changes(self.root, include_tags=True)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "mp4")
        self.assertEqual(changes[0]["status"], "CLEAN_ONLY")
        self.assertEqual(changes[0]["new_series"], "Blight")

    def test_include_tags_finds_an_mp3_book_word_suffix(self):
        write_mp3(self.root / "Author" / "Book 1" / "book.mp3", "Blight, Book #1", "")
        changes = FIX.plan_series_number_changes(self.root, include_tags=True)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "id3")
        self.assertEqual(changes[0]["status"], "FILL_SEQUENCE")
        self.assertEqual(changes[0]["new_sequence"], "1")

    def test_apply_m4b_writes_the_same_mvnm_mvin_tags_the_fixer_would(self):
        path = self.root / "Author" / "Book 1" / "book.m4b"
        write_m4b(path, "Blight, Book #1", "")
        change = FIX.plan_series_number_changes(self.root, include_tags=True)[0]
        FIX.apply_change(change)

        from mutagen.mp4 import MP4
        audio = MP4(str(path))
        self.assertEqual(FIX._mp4_freeform_str(audio.tags, "mvnm"), "Blight")
        self.assertEqual(FIX._mp4_freeform_str(audio.tags, "mvin"), "1")

    def test_apply_mp3_writes_mvnm_mvin_and_legacy_series_part(self):
        path = self.root / "Author" / "Book 1" / "book.mp3"
        write_mp3(path, "Blight, Book #1", "")
        change = FIX.plan_series_number_changes(self.root, include_tags=True)[0]
        FIX.apply_change(change)

        from mutagen.id3 import ID3
        audio = ID3(str(path))
        self.assertEqual(str(audio["TXXX:mvnm"].text[0]), "Blight")
        self.assertEqual(str(audio["TXXX:mvin"].text[0]), "1")
        self.assertEqual(str(audio["TXXX:series-part"].text[0]), "1")

    def test_revert_restores_the_original_embedded_tag(self):
        path = self.root / "Author" / "Book 1" / "book.m4b"
        write_m4b(path, "Blight, Book #1", "")
        change = FIX.plan_series_number_changes(self.root, include_tags=True)[0]
        FIX.apply_change(change)
        log_path = self.root / "log.jsonl"
        log_path.write_text(json.dumps(change) + "\n", encoding="utf-8")
        FIX.revert(log_path)

        from mutagen.mp4 import MP4
        audio = MP4(str(path))
        self.assertEqual(FIX._mp4_freeform_str(audio.tags, "mvnm"), "Blight, Book #1")
        self.assertEqual(FIX._mp4_freeform_str(audio.tags, "mvin"), "")

    def test_a_bare_trailing_number_title_with_no_sibling_is_left_alone(self):
        # Regression guard for the real "Beacon 23" case -- a genuine title
        # ending in a digit, no "#"/","/"-" separator, must never be touched.
        write_m4b(self.root / "Hugh Howey" / "Beacon 23" / "book.m4b", "Beacon 23", "")
        changes = FIX.plan_series_number_changes(self.root, include_tags=True)
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
