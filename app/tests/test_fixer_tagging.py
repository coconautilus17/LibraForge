"""Behaviour tests for app.fixer.tagging.

Each test states what a caller observes (the m4b-tool argument list, the tag
frames left on a file) so that a changed condition or a dropped field fails
here, not just in a broader end-to-end test that happens to touch the line.
"""

import unittest
from pathlib import Path
from unittest import mock

from app.fixer import tagging


def _pairs(args):
    """['-metadata', 'k=v', ...] -> {'k': 'v'}"""
    assert args[::2] == ["-metadata"] * (len(args) // 2)
    return dict(item.split("=", 1) for item in args[1::2])


class BuildMetadataArgsTests(unittest.TestCase):
    FULL = {
        "title": "Gideon the Ninth",
        "author": "Tamsyn Muir",
        "series": "Locked Tomb",
        "sequence": "1",
        "narrator": "Moe Rock",
        "year": "2019",
        "genre": "Fantasy",
        "publisher": "Macmillan Audio",
        "subtitle": "The Locked Tomb Trilogy",
        "asin": "B07FOO1234",
        "isbn": "9781250313195",
        "summary": "Necromancers in space",
        "write_summary": True,
    }

    def test_every_populated_field_reaches_its_m4b_tool_tag(self):
        tags = _pairs(tagging.build_metadata_args(self.FULL))
        self.assertEqual(tags["title"], "Gideon the Ninth")
        self.assertEqual(tags["album"], "Gideon the Ninth")
        self.assertEqual(tags["artist"], "Tamsyn Muir")
        self.assertEqual(tags["album_artist"], "Tamsyn Muir")
        self.assertEqual(tags["grouping"], "Locked Tomb")
        self.assertEqual(tags["mvnm"], "Locked Tomb")
        self.assertEqual(tags["mvin"], "1")
        self.assertEqual(tags["composer"], "Moe Rock")
        self.assertEqual(tags["date"], "2019")
        self.assertEqual(tags["genre"], "Fantasy")
        self.assertEqual(tags["publisher"], "Macmillan Audio")
        self.assertEqual(tags["subtitle"], "The Locked Tomb Trilogy")

    def test_sequence_asin_isbn_and_summary_are_written_when_present(self):
        tags = _pairs(tagging.build_metadata_args(self.FULL))
        self.assertEqual(tags["track"], "1")
        self.assertEqual(tags["asin"], "B07FOO1234")
        self.assertEqual(tags["isbn"], "9781250313195")
        self.assertEqual(tags["comment"], "Necromancers in space")

    def test_each_optional_tag_is_absent_when_its_value_is_absent(self):
        for field, tag in (("sequence", "track"), ("asin", "asin"), ("isbn", "isbn")):
            with self.subTest(field=field):
                meta = dict(self.FULL)
                meta.pop(field)
                tags = _pairs(tagging.build_metadata_args(meta))
                self.assertNotIn(tag, tags)
                # the other optional tags are unaffected
                others = {"track", "asin", "isbn", "comment"} - {tag}
                self.assertTrue(others <= set(tags), others - set(tags))

    def test_summary_is_only_written_when_write_summary_is_set(self):
        meta = dict(self.FULL, write_summary=False)
        self.assertNotIn("comment", _pairs(tagging.build_metadata_args(meta)))

    def test_summary_flag_without_a_summary_writes_no_comment(self):
        meta = dict(self.FULL, summary="", write_summary=True)
        self.assertNotIn("comment", _pairs(tagging.build_metadata_args(meta)))

    def test_summary_without_the_flag_is_not_written(self):
        meta = {k: v for k, v in self.FULL.items() if k != "write_summary"}
        self.assertNotIn("comment", _pairs(tagging.build_metadata_args(meta)))

    def test_blank_and_whitespace_values_never_produce_an_argument(self):
        args = tagging.build_metadata_args({"title": "  ", "author": "", "series": "S"})
        self.assertEqual(_pairs(args), {"grouping": "S", "mvnm": "S"})

    def test_empty_metadata_gives_no_arguments(self):
        self.assertEqual(tagging.build_metadata_args({}), [])


class Id3SetTxxxTests(unittest.TestCase):
    def setUp(self):
        if tagging.ID3 is None:
            self.skipTest("mutagen not installed")
        self.tags = tagging.ID3()

    def test_a_value_is_stored_as_a_txxx_frame(self):
        tagging.id3_set_txxx(self.tags, "ASIN", "B07FOO1234")
        self.assertEqual(self.tags.getall("TXXX:ASIN")[0].text, ["B07FOO1234"])

    def test_a_blank_value_removes_the_existing_frame_and_adds_none(self):
        tagging.id3_set_txxx(self.tags, "ASIN", "B07FOO1234")
        tagging.id3_set_txxx(self.tags, "ASIN", "")
        self.assertEqual(self.tags.getall("TXXX:ASIN"), [])

    def test_replacing_a_value_leaves_exactly_one_frame(self):
        tagging.id3_set_txxx(self.tags, "ASIN", "OLD")
        tagging.id3_set_txxx(self.tags, "ASIN", "NEW")
        frames = self.tags.getall("TXXX:ASIN")
        self.assertEqual([f.text for f in frames], [["NEW"]])


class ShouldWriteFieldTests(unittest.TestCase):
    def _fn(self):
        return tagging.should_write_field

    def test_a_present_value_is_written_under_every_policy(self):
        for policy in ("overwrite", "fill", "legacy", "anything-else"):
            for conditional in (True, False):
                with self.subTest(policy=policy, conditional=conditional):
                    self.assertIs(self._fn()("x", policy, conditional), True)

    def test_blank_value_overwrite_policy_writes_so_the_setter_can_clear(self):
        for conditional in (True, False):
            self.assertIs(self._fn()("", "overwrite", conditional), True)

    def test_blank_value_fill_policy_never_writes(self):
        for conditional in (True, False):
            self.assertIs(self._fn()("", "fill", conditional), False)

    def test_blank_value_legacy_policy_follows_the_historical_split(self):
        self.assertIs(self._fn()("", "legacy", True), False)
        self.assertIs(self._fn()("", "legacy", False), True)


class Id3TrackTests(unittest.TestCase):
    def setUp(self):
        if tagging.ID3 is None:
            self.skipTest("mutagen not installed")
        self.tags = tagging.ID3()

    def test_a_sequence_is_stored_as_trck(self):
        tagging.id3_set_track(self.tags, "4")
        self.assertEqual(self.tags.getall("TRCK")[0].text, ["4"])

    def test_a_blank_sequence_clears_the_track_frame(self):
        tagging.id3_set_track(self.tags, "4")
        tagging.id3_set_track(self.tags, "")
        self.assertEqual(self.tags.getall("TRCK"), [])


class Mp4TrackTests(unittest.TestCase):
    def test_a_sequence_becomes_a_track_number_tuple(self):
        tags = {}
        tagging.mp4_set_track(tags, "3")
        self.assertEqual(tags["trkn"], [(3, 0)])

    def test_a_blank_sequence_clears_an_existing_track(self):
        tags = {"trkn": [(3, 0)]}
        tagging.mp4_set_track(tags, "")
        self.assertNotIn("trkn", tags)

    def test_set_text_stores_a_list_and_blank_removes_the_key(self):
        tags = {}
        tagging.mp4_set_text(tags, "©nam", "Title")
        self.assertEqual(tags["©nam"], ["Title"])
        tagging.mp4_set_text(tags, "©nam", " ")
        self.assertNotIn("©nam", tags)


class MutagenAvailabilityTests(unittest.TestCase):
    def test_mp4_support_needs_all_three_mutagen_mp4_classes(self):
        for missing in ("MP4", "MP4FreeForm", "MP4Cover"):
            with self.subTest(missing=missing):
                with mock.patch.multiple(tagging, MP4=object, MP4FreeForm=object, MP4Cover=object):
                    self.assertTrue(tagging.mutagen_mp4_is_available())
                    with mock.patch.object(tagging, missing, None):
                        self.assertFalse(tagging.mutagen_mp4_is_available())

    def test_mp3_support_needs_all_three_mutagen_id3_classes(self):
        for missing in ("ID3", "APIC", "TXXX"):
            with self.subTest(missing=missing):
                with mock.patch.multiple(tagging, ID3=object, APIC=object, TXXX=object):
                    self.assertTrue(tagging.mutagen_mp3_is_available())
                    with mock.patch.object(tagging, missing, None):
                        self.assertFalse(tagging.mutagen_mp3_is_available())

    def test_overall_availability_is_either_family(self):
        mp4 = dict(MP4=object, MP4FreeForm=object, MP4Cover=object)
        mp3 = dict(ID3=object, APIC=object, TXXX=object)
        none_mp4 = dict(MP4=None, MP4FreeForm=None, MP4Cover=None)
        none_mp3 = dict(ID3=None, APIC=None, TXXX=None)
        for label, patch, expected in (
            ("both", {**mp4, **mp3}, True),
            ("mp4 only", {**mp4, **none_mp3}, True),
            ("mp3 only", {**none_mp4, **mp3}, True),
            ("neither", {**none_mp4, **none_mp3}, False),
        ):
            with self.subTest(label), mock.patch.multiple(tagging, **patch):
                self.assertIs(tagging.mutagen_is_available(), expected)


class CandidateExtensionTests(unittest.TestCase):
    def test_extensions_route_to_the_right_family_case_insensitively(self):
        for name, mp4, mp3 in (
            ("a.m4b", True, False), ("a.M4A", True, False), ("a.mp4", True, False),
            ("a.mp3", False, True), ("a.MP3", False, True),
            ("a.flac", False, False), ("a", False, False),
        ):
            with self.subTest(name):
                p = Path(name)
                self.assertIs(tagging.is_mutagen_mp4_candidate(p), mp4)
                self.assertIs(tagging.is_mutagen_mp3_candidate(p), mp3)
                self.assertIs(tagging.is_mutagen_candidate(p), mp4 or mp3)


if __name__ == "__main__":
    unittest.main()
