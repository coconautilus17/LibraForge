"""Guards the Metadata Fixer applies before treating several files as one book:
volume-chapter albums, two copies of one book in one folder, and distinct
complete works that merely share a folder. Tag and size readers are injected so
no audio files are needed."""
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

FIXER = load_script("fixer_grouping_guards", "audible-metadata-fixer-v5.py")

MB = 1_000_000


def paths(folder, *names):
    return [Path(folder) / n for n in names]


class NestedChapterSequenceTests(unittest.TestCase):
    FILES = paths("/lib/Album", *[f"1-{n:02d} Title.mp3" for n in (1, 2, 3)], *[f"2-{n:02d} Title.mp3" for n in (4, 5, 6)])

    def tracks(self, mapping):
        return lambda path: mapping.get(path, {})

    def good_tags(self):
        files = sorted(self.FILES, key=FIXER.natural_audio_sort_key)
        return {p: {"album": "Great Album", "track": f"{i}/6"} for i, p in enumerate(files, 1)}

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


class DistinctBooksTests(unittest.TestCase):
    def sizes(self, mapping, default=0):
        return lambda path: mapping.get(path, default)

    def test_fewer_than_two_files_cannot_be_distinct_books(self):
        self.assertFalse(FIXER.looks_like_distinct_books([Path("/a.m4b")], tag_reader=lambda p: {}, size_reader=lambda p: 900 * MB))
        self.assertFalse(FIXER.looks_like_distinct_books([], tag_reader=lambda p: {}, size_reader=lambda p: 0))

if __name__ == "__main__":
    unittest.main()
