"""build_disk_asin_map resolves ASINs from cheap sources before probing media."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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


FIXER = load_module("fixer_v5_dupasin", "scripts/audible-metadata-fixer-v5.py")


class BuildDiskAsinMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._p = patch.object(FIXER, "DISK_ASIN_CACHE_PATH", self.root / "cache.json")
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_filename_token_resolves_without_probe(self):
        f = self.root / "Some Book [B0FILE1234].m4b"
        f.write_bytes(b"")
        with patch.object(FIXER, "probe_file", side_effect=AssertionError("should not probe")):
            result = FIXER.build_disk_asin_map([f], 1)
        self.assertEqual(result, {"B0FILE1234": {str(f)}})

    def test_sidecar_resolves_without_probe(self):
        f = self.root / "book.m4b"
        f.write_bytes(b"")
        sidecar = f.with_name(f.name + FIXER.LIBRAFORGE_SUFFIX)
        sidecar.write_text(json.dumps({"marker": {"audible": {"asin": "B0SIDE1234"}}}), encoding="utf-8")
        with patch.object(FIXER, "probe_file", side_effect=AssertionError("should not probe")):
            result = FIXER.build_disk_asin_map([f], 1)
        self.assertEqual(result, {"B0SIDE1234": {str(f)}})

    def test_falls_back_to_media_probe(self):
        f = self.root / "plain.m4b"
        f.write_bytes(b"")
        with patch.object(FIXER, "probe_file", return_value=({"asin": "B0EMBED123"}, None)) as probe:
            result = FIXER.build_disk_asin_map([f], 1)
        self.assertEqual(result, {"B0EMBED123": {str(f)}})
        probe.assert_called_once()

    def test_norealasin_sidecar_falls_through_to_probe(self):
        f = self.root / "noreal.m4b"
        f.write_bytes(b"")
        sidecar = f.with_name(f.name + FIXER.LIBRAFORGE_SUFFIX)
        sidecar.write_text(json.dumps({"marker": {"audible": {"asin": "NOREALASIN"}}}), encoding="utf-8")
        with patch.object(FIXER, "probe_file", return_value=({"asin": "B0REAL1234"}, None)) as probe:
            result = FIXER.build_disk_asin_map([f], 1)
        self.assertEqual(result, {"B0REAL1234": {str(f)}})
        probe.assert_called_once()


if __name__ == "__main__":
    unittest.main()
