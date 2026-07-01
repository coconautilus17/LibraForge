import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    sys.modules["audible"] = audible_stub


def load_fixer():
    path = ROOT / "scripts/audible-metadata-fixer-v5.py"
    spec = importlib.util.spec_from_file_location("fixer_audio_sidecar", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_fixer()


class FixerAudioSidecarTests(unittest.TestCase):
    def test_refresh_preserves_metadata_and_updates_all_chapter_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Book"
            folder.mkdir()
            chapter_files = [folder / "Part 2.m4a", folder / "Part 1.m4a"]
            for chapter_file in chapter_files:
                chapter_file.touch()

            # v5 writes everything to libraforge.json with existing metadata
            # nested under "sidecar", not as a standalone flat sidecar file.
            lf_path = folder / "libraforge.json"
            existing_sidecar = {
                "book": {"title": "Existing Title", "author": "Existing Author"},
                "audible": {"asin": "B012345678"},
                "source": {"group_search": {"applied": True}},
            }
            lf_path.write_text(
                json.dumps({"schema_version": 2, "sidecar": existing_sidecar}),
                encoding="utf-8",
            )
            summary = {
                "file_count": 2,
                "probed_file_count": 2,
                "codecs": ["aac"],
                "no_conversion": {"status": "copy", "recommended": True},
            }

            written = FIXER.refresh_multipart_sidecar_audio_profile(
                folder=folder,
                chapter_files=chapter_files,
                audio_summary=summary,
            )

            payload = json.loads(written.read_text(encoding="utf-8"))
            sc = payload["sidecar"]
            self.assertEqual(sc["book"], existing_sidecar["book"])
            self.assertEqual(sc["audible"], existing_sidecar["audible"])
            self.assertEqual(sc["audio_summary"], summary)
            self.assertEqual(
                sc["source"]["chapter_files"],
                [str(folder / "Part 1.m4a"), str(folder / "Part 2.m4a")],
            )
            self.assertEqual(sc["source"]["group_search"]["file_count"], 2)
            self.assertIn("audio_profile_updated_at", sc)


if __name__ == "__main__":
    unittest.main()
