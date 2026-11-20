"""The Python port of Audiobookshelf's author-name parser must read every
name exactly as Audiobookshelf does. The fixture comes from the parser running
inside an Audiobookshelf container (tools/abs_name_fixture.js)."""
import json
import unittest
from pathlib import Path

from app import abs_names

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "abs_name_parse.json").read_text(encoding="utf-8"))


class ParseFullNameMatchesAbs(unittest.TestCase):
    def test_every_fixture_name(self):
        for name, expected in FIXTURE["full_names"].items():
            with self.subTest(name=name):
                got = abs_names.parse_full_name(name)
                for part in ("title", "first", "middle", "last", "nick", "suffix"):
                    self.assertEqual(getattr(got, part), expected[part], part)


class ParseNameStringMatchesAbs(unittest.TestCase):
    def test_every_fixture_string(self):
        for value, expected in FIXTURE["name_strings"].items():
            with self.subTest(value=value):
                self.assertEqual(abs_names.parse_name_string(value), expected)

    def test_empty_is_empty_list(self):
        self.assertEqual(abs_names.parse_name_string(""), [])


if __name__ == "__main__":
    unittest.main()
