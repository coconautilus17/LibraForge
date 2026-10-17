"""Guards the Metadata Fixer applies before treating several files as one book:
volume-chapter albums, two copies of one book in one folder, and distinct
complete works that merely share a folder. Tag and size readers are injected so
no audio files are needed."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_grouping_guards", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)

MB = 1_000_000


def paths(folder, *names):
    return [Path(folder) / n for n in names]


def album_reader(album="Great Album", start=1):
    """A tag reader giving every file the same album and consecutive track numbers by natural order."""
    def reader(path):
        number = int("".join(ch for ch in path.stem.split("-")[-1] if ch.isdigit()) or 0)
        return {"album": album, "track": str(number)}
    return reader


class NestedChapterSequenceTests(unittest.TestCase):
    FILES = paths("/lib/Album", *[f"1-{n:02d} Title.mp3" for n in (1, 2, 3)], *[f"2-{n:02d} Title.mp3" for n in (4, 5, 6)])

    def tracks(self, mapping):
        return lambda path: mapping.get(path, {})

    def good_tags(self):
        files = sorted(self.FILES, key=FIXER.natural_audio_sort_key)
        return {p: {"album": "Great Album", "track": f"{i}/6"} for i, p in enumerate(files, 1)}

    def test_volume_chapter_names_with_one_album_and_continuous_tracks_are_one_book(self):
        got = FIXER.nested_chapter_sequence_files(self.FILES, self.tracks(self.good_tags()))
        self.assertEqual(got, set(self.FILES))

    def test_fewer_than_six_files_never_qualify(self):
        tags = self.good_tags()
        self.assertEqual(FIXER.nested_chapter_sequence_files(self.FILES[:5], self.tracks(tags)), set())

    def test_exactly_six_files_are_enough(self):
        self.assertEqual(len(FIXER.nested_chapter_sequence_files(self.FILES, self.tracks(self.good_tags()))), 6)

    def test_a_file_that_does_not_follow_the_volume_chapter_pattern_disqualifies_the_group(self):
        files = self.FILES[:5] + [Path("/lib/Album/bonus.mp3")]
        self.assertEqual(FIXER.nested_chapter_sequence_files(files, self.tracks(self.good_tags())), set())

    def test_one_volume_only_is_not_a_nested_sequence(self):
        files = paths("/lib/A", *[f"1-{n:02d} T.mp3" for n in range(1, 7)])
        tags = {p: {"album": "A", "track": str(i)} for i, p in enumerate(sorted(files, key=FIXER.natural_audio_sort_key), 1)}
        self.assertEqual(FIXER.nested_chapter_sequence_files(files, self.tracks(tags)), set())

    def test_volumes_must_be_consecutive_and_chapters_gap_free_and_unique(self):
        gap_volume = paths("/lib/A", *[f"1-{n:02d} T.mp3" for n in (1, 2, 3)], *[f"3-{n:02d} T.mp3" for n in (4, 5, 6)])
        self.assertEqual(FIXER.nested_chapter_sequence_files(gap_volume, lambda p: {"album": "A", "track": "1"}), set())
        gap_chapter = paths("/lib/A", *[f"1-{n:02d} T.mp3" for n in (1, 2, 4)], *[f"2-{n:02d} T.mp3" for n in (5, 6, 7)])
        self.assertEqual(FIXER.nested_chapter_sequence_files(gap_chapter, lambda p: {"album": "A", "track": "1"}), set())
        dup = paths("/lib/A", "1-01 a.mp3", "1-01 b.mp3", "1-02 c.mp3", "2-03 d.mp3", "2-04 e.mp3", "2-05 f.mp3")
        self.assertEqual(FIXER.nested_chapter_sequence_files(dup, lambda p: {"album": "A", "track": "1"}), set())

    def test_two_albums_or_missing_or_non_numeric_tracks_or_discontinuous_tracks_disqualify(self):
        tags = self.good_tags()
        two_albums = dict(tags)
        first = sorted(self.FILES, key=FIXER.natural_audio_sort_key)[0]
        two_albums[first] = {"album": "Other", "track": "1/6"}
        self.assertEqual(FIXER.nested_chapter_sequence_files(self.FILES, self.tracks(two_albums)), set())
        no_album = {p: {"track": t["track"]} for p, t in tags.items()}
        self.assertEqual(FIXER.nested_chapter_sequence_files(self.FILES, self.tracks(no_album)), set())
        bad_track = {p: {"album": "Great Album", "track": "x"} for p in tags}
        self.assertEqual(FIXER.nested_chapter_sequence_files(self.FILES, self.tracks(bad_track)), set())
        skipping = dict(tags)
        skipping[first] = {"album": "Great Album", "track": "2/6"}
        self.assertEqual(FIXER.nested_chapter_sequence_files(self.FILES, self.tracks(skipping)), set())

    def test_groups_are_found_per_folder_among_all_files(self):
        other = [Path("/lib/Other/single.mp3")]
        found = FIXER.find_nested_chapter_groups(self.FILES + other, self.tracks(self.good_tags()))
        self.assertEqual(list(found), [Path("/lib/Album")])
        self.assertEqual(found[Path("/lib/Album")], set(self.FILES))

    def test_non_audio_files_are_ignored_when_grouping_by_folder(self):
        grouped = FIXER.multi_part_files_by_parent([Path("/lib/A/a.mp3"), Path("/lib/A/cover.jpg"), Path("/lib/B/b.m4b")])
        self.assertEqual(grouped, {Path("/lib/A"): [Path("/lib/A/a.mp3")], Path("/lib/B"): [Path("/lib/B/b.m4b")]})


class DuplicateSetFolderTests(unittest.TestCase):
    def test_a_folder_with_two_numbered_sets_is_flagged_with_both_sizes(self):
        files = paths("/lib/Dup", "Book - 01.mp3", "Book - 02.mp3", "Book - 03.mp3",
                      "Part 1.mp3", "Part 2.mp3", "Part 3.mp3", "Part 4.mp3")
        found = FIXER.find_duplicate_set_folders(files, tag_reader=lambda p: {})
        self.assertEqual(list(found), [Path("/lib/Dup")])
        self.assertEqual(found[Path("/lib/Dup")],
                         "skipped: folder holds two numbered sets of audio files (4 and 3 files), "
                         "likely two copies of the same audiobook; keep one set and run again")

    def test_one_set_only_or_sets_smaller_than_three_are_not_duplicates(self):
        one = paths("/lib/A", "Book - 01.mp3", "Book - 02.mp3", "Book - 03.mp3")
        self.assertEqual(FIXER.find_duplicate_set_folders(one, tag_reader=lambda p: {}), {})
        small_second = paths("/lib/A", "Book - 01.mp3", "Book - 02.mp3", "Book - 03.mp3", "Part 1.mp3", "Part 2.mp3")
        self.assertEqual(FIXER.find_duplicate_set_folders(small_second, tag_reader=lambda p: {}), {})
        small_first = paths("/lib/A", "Book - 01.mp3", "Book - 02.mp3", "Part 1.mp3", "Part 2.mp3", "Part 3.mp3")
        self.assertEqual(FIXER.find_duplicate_set_folders(small_first, tag_reader=lambda p: {}), {})

    def test_a_nested_chapter_folder_is_never_a_duplicate_set(self):
        files = paths("/lib/Dup", "Book - 01.mp3", "Book - 02.mp3", "Book - 03.mp3", "Part 1.mp3", "Part 2.mp3", "Part 3.mp3")
        self.assertEqual(FIXER.find_duplicate_set_folders(files, nested_groups={Path("/lib/Dup"): set(files)}), {})
        self.assertEqual(len(FIXER.find_duplicate_set_folders(files, nested_groups={})), 1)

    def test_the_minimum_set_size_is_three(self):
        self.assertEqual(FIXER.DUPLICATE_SET_MIN_FILES, 3)


class DistinctBooksTests(unittest.TestCase):
    def sizes(self, mapping, default=0):
        return lambda path: mapping.get(path, default)

    def test_fewer_than_two_files_cannot_be_distinct_books(self):
        self.assertFalse(FIXER.looks_like_distinct_books([Path("/a.m4b")], tag_reader=lambda p: {}, size_reader=lambda p: 900 * MB))
        self.assertFalse(FIXER.looks_like_distinct_books([], tag_reader=lambda p: {}, size_reader=lambda p: 0))

    def test_an_unreadable_file_size_means_not_distinct(self):
        def boom(path):
            raise OSError("gone")
        self.assertFalse(FIXER.looks_like_distinct_books(paths("/a", "1.m4b", "2.m4b"), tag_reader=lambda p: {}, size_reader=boom))

    def test_large_files_with_different_albums_are_distinct_books(self):
        files = paths("/a", "1.m4b", "2.m4b")
        albums = {files[0]: {"album": "Book One"}, files[1]: {"album": "Book Two"}}
        self.assertTrue(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: albums[p], size_reader=lambda p: 300 * MB))

    def test_large_files_sharing_an_album_or_part_marker_album_are_one_book(self):
        files = paths("/a", "1.m4b", "2.m4b")
        same = {files[0]: {"album": "Book"}, files[1]: {"album": "Book"}}
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: same[p], size_reader=lambda p: 300 * MB))
        parts = {files[0]: {"album": "Book Part 1"}, files[1]: {"album": "Book Part 2"}}
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: parts[p], size_reader=lambda p: 300 * MB))

    def test_a_large_file_without_an_album_makes_the_judgement_impossible(self):
        files = paths("/a", "1.m4b", "2.m4b")
        tags = {files[0]: {"album": "Book One"}, files[1]: {}}
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: tags[p], size_reader=lambda p: 300 * MB))

    def test_the_large_file_threshold_is_two_hundred_fifty_megabytes_for_the_smallest_file(self):
        files = paths("/a", "1.m4b", "2.m4b")
        albums = {files[0]: {"album": "Book One"}, files[1]: {"album": "Book Two"}}
        size_of = lambda smallest: (lambda p: smallest if p == files[0] else 400 * MB)
        self.assertTrue(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: albums[p], size_reader=size_of(250 * MB)))
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: albums[p], size_reader=size_of(249 * MB)))

    def test_five_big_unnumbered_mp3s_with_their_own_titles_and_no_album_are_separate_works(self):
        files = paths("/a", "Apology.mp3", "Crito.mp3", "Phaedo.mp3", "Republic.mp3", "Symposium.mp3")
        tags = {p: {"title": p.stem} for p in files}
        self.assertTrue(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: tags[p], size_reader=lambda p: 100 * MB))

    def test_each_condition_of_the_mp3_collection_rule_matters(self):
        files = paths("/a", "Apology.mp3", "Crito.mp3", "Phaedo.mp3", "Republic.mp3", "Symposium.mp3")
        tags = {p: {"title": p.stem} for p in files}
        read = lambda p: tags[p]
        big = lambda p: 100 * MB
        self.assertFalse(FIXER.looks_like_distinct_books(files[:4], tag_reader=read, size_reader=big))          # fewer than five
        self.assertFalse(FIXER.looks_like_distinct_books(files[:4] + [Path("/a/x.m4b")], tag_reader=read, size_reader=big))  # not all mp3
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=read, size_reader=lambda p: 29 * MB))  # smallest too small
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=read, size_reader=lambda p: 79 * MB))  # median too small
        with_album = {p: {"title": p.stem, "album": "Dialogues"} for p in files}
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: with_album[p], size_reader=big))
        no_titles = {p: {} for p in files}
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: no_titles[p], size_reader=big))
        mismatched = {p: {"title": f"Different {p.stem}"} for p in files}
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: mismatched[p], size_reader=big))   # titles are not the file names
        same_title = {p: {"title": "Same"} for p in files}
        self.assertFalse(FIXER.looks_like_distinct_books(files, tag_reader=lambda p: same_title[p], size_reader=big))   # titles repeat
        numbered = paths("/a", "Book - 01.mp3", "Book - 02.mp3", "Book - 03.mp3", "Book - 04.mp3", "Book - 05.mp3")
        self.assertFalse(FIXER.looks_like_distinct_books(numbered, tag_reader=lambda p: {"title": p.stem}, size_reader=big))
        chapters = paths("/a", "Chapter 1.mp3", "Chapter 2.mp3", "Chapter 3.mp3", "Chapter 4.mp3", "Chapter 5.mp3")
        self.assertFalse(FIXER.looks_like_distinct_books(chapters, tag_reader=lambda p: {"title": p.stem}, size_reader=big))

    def test_the_album_identity_ignores_a_part_marker(self):
        self.assertEqual(FIXER._album_identity("Book Part 2"), "book")
        self.assertEqual(FIXER._album_identity("Plain Album"), "plain album")


if __name__ == "__main__":
    unittest.main()
