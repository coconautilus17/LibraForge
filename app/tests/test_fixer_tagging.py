"""Behaviour tests for app.fixer.tagging.

Each test states what a caller observes (the m4b-tool argument list, the tag
frames left on a file) so that a changed condition or a dropped field fails
here, not just in a broader end-to-end test that happens to touch the line.
"""

import unittest
from unittest import mock

from app.fixer import tagging


class MutagenAvailabilityTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
