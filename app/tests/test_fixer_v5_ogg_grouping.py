"""OGG multi-file grouping in the v5 fixer (and organizer ext-set sync).

Per-chapter .ogg dumps (e.g. "1301.ogg".."1900.ogg" for one book) were
discovered and tagged but never grouped, so each chapter counted as its own
book. .ogg now mirrors .opus: groupable and written via an m4b-tool sidecar.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path


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
    sys.modules[spec.name] = module  # register so dataclasses resolve __module__
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_ogg", "scripts/audible-metadata-fixer-v5.py")
ORGANIZER = load_module("organizer_v3_13_ogg", "scripts/organize-audiobooks-by-metadata-v3_13.py")


def bare_number_ogg(folder: str, start: int, count: int) -> list[Path]:
    return [Path(f"{folder}/{n}.ogg") for n in range(start, start + count)]


class OggGroupingTests(unittest.TestCase):
    def test_ogg_is_a_full_peer_of_opus(self):
        self.assertIn(".ogg", FIXER.MULTI_PART_AUDIO_EXTENSIONS)
        self.assertIn(".ogg", FIXER.SIDECAR_OUTPUT_AUDIO_EXTENSIONS)
        # .ogg has no MP4-style chapters and is not tagged in-place by mutagen.
        self.assertNotIn(".ogg", FIXER.CHAPTER_METADATA_EXTENSIONS)

    def test_per_chapter_ogg_dump_groups_as_one_book(self):
        files = bare_number_ogg("/book/Shadow Slave Vol 9 (1301-1900)", 1301, 8)

        def reader(_path):
            raise AssertionError("ogg should skip chapter-metadata probing")

        groups = FIXER.build_multi_part_group_map(files, chapter_count_reader=reader)
        self.assertEqual(groups[files[0].parent], files)
        # The whole folder collapses to a single processing item.
        self.assertEqual(FIXER.build_processing_items(files, groups), [files[0]])

    def test_grouped_ogg_routes_to_m4b_tool_sidecar(self):
        rep = Path("/book/Shadow Slave Vol 9 (1301-1900)/1301.ogg")
        self.assertTrue(
            FIXER.should_write_json_sidecar(rep, {"group_search": {"applied": True}})
        )

    def test_single_ogg_writes_a_sidecar_like_opus(self):
        # .ogg now in SIDECAR_OUTPUT, so even a lone file is sidecar-routed.
        self.assertTrue(FIXER.should_write_json_sidecar(Path("/b/only.ogg")))

    def test_organizer_recognizes_grouped_ogg_book(self):
        files = bare_number_ogg("/book/Shadow Slave Vol 9 (1301-1900)", 1301, 5)
        self.assertIn(".ogg", ORGANIZER.MULTI_PART_AUDIO_EXTENSIONS)
        self.assertTrue(ORGANIZER.looks_like_multi_file_book(files))

    def test_fixer_and_organizer_multipart_sets_stay_in_sync(self):
        self.assertEqual(
            FIXER.MULTI_PART_AUDIO_EXTENSIONS,
            ORGANIZER.MULTI_PART_AUDIO_EXTENSIONS,
        )


if __name__ == "__main__":
    unittest.main()
