"""probe_file (one ffprobe call -> tags + minutes) and read_tags_and_duration
(which source the fixer reads a file's tags from: live probe, folder file cache,
or the per-file backup)."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_probe_and_cache", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


def completed(payload, returncode=0):
    return types.SimpleNamespace(stdout=json.dumps(payload) if not isinstance(payload, str) else payload, returncode=returncode)


class ProbeFileTests(unittest.TestCase):
    PATH = Path("/lib/a.m4b")

    def probe(self, result=None, side_effect=None):
        with mock.patch.object(FIXER.subprocess, "run", return_value=result, side_effect=side_effect) as run, \
             mock.patch("builtins.print"):
            return FIXER.probe_file(self.PATH), run

    def test_a_failing_or_unparseable_ffprobe_gives_nothing(self):
        for result in (completed({"format": {}}, returncode=1), completed("not json")):
            (tags, minutes), _ = self.probe(result)
            self.assertEqual((tags, minutes), ({}, None))


class ReadTagsAndDurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.file = self.folder / "book.m4b"
        self.file.write_bytes(b"x")
        patcher = mock.patch.object(FIXER, "probe_file", return_value=({"title": "live"}, 99.0))
        self.probe = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write_folder(self, payload):
        (self.folder / "libraforge.json").write_text(json.dumps(payload))

    def write_file_lf(self, payload):
        (self.folder / "book.m4b.libraforge.json").write_text(json.dumps(payload))

    def test_a_backup_supplies_applied_tags_first_then_the_original_format_tags(self):
        self.write_file_lf({"backup": {"duration_minutes": 5, "applied_tags": {"title": "applied"}, "format_tags": {"title": "original"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "applied"}, 5.0, False))
        self.write_file_lf({"backup": {"duration_minutes": 5, "format_tags": {"title": "original"}}})
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "original"}, 5.0, False))
        self.probe.assert_not_called()

    def test_a_grouped_books_file_cache_wins_and_uses_the_applied_book_tags(self):
        self.write_folder({"file_cache": {str(self.file): {"duration_minutes": 7, "format_tags": {"title": "original"}}},
                           "sidecar": {"book": {"title": "Applied", "author": "A"}}})
        tags, minutes, live = FIXER.read_tags_and_duration(self.file)
        self.assertEqual((tags["title"], tags["artist"], minutes, live), ("Applied", "A", 7.0, False))
        self.assertEqual(FIXER.read_tags_and_duration(self.file, use_backup_tags=True), ({"title": "original"}, 7.0, False))

    def test_a_corrupt_folder_sidecar_falls_through_to_the_probe(self):
        (self.folder / "libraforge.json").write_text("{bad")
        self.assertEqual(FIXER.read_tags_and_duration(self.file), ({"title": "live"}, 99.0, True))


if __name__ == "__main__":
    unittest.main()
