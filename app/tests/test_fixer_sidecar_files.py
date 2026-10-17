"""Where the Metadata Fixer keeps its per-book record (libraforge.json), how it
migrates the old file layouts, who owns a shared folder's sidecar and what the
original-tags backup keeps. Every assertion is on files on disk."""
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

SPEC = importlib.util.spec_from_file_location("fixer_sidecar_files", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


class SidecarFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / "Book"
        self.folder.mkdir()
        self.source = self.folder / "book.m4b"
        self.source.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def folder_lf(self):
        return self.folder / "libraforge.json"

    @property
    def file_lf(self):
        return self.folder / "book.m4b.libraforge.json"


class PathRuleTests(SidecarFixture):
    def test_the_sidecar_is_folder_level_for_grouped_or_lone_books_and_per_file_otherwise(self):
        self.assertEqual(FIXER.get_libraforge_path(self.source), self.file_lf)
        self.assertEqual(FIXER.get_libraforge_path(self.source, alone=True), self.folder_lf)
        self.assertEqual(FIXER.get_libraforge_path(self.source, {"group_search": {"applied": True}}), self.folder_lf)
        self.assertEqual(FIXER.get_libraforge_path(self.source, {"group_search": {"applied": False}}), self.file_lf)
        self.assertEqual(FIXER.get_libraforge_path(self.source, {}), self.file_lf)
        self.assertEqual(FIXER.get_libraforge_path(self.source, None), self.file_lf)

    def test_the_m4b_tool_metadata_path_is_per_folder_for_groups_and_per_file_otherwise(self):
        self.assertEqual(FIXER.get_m4b_tool_metadata_path(self.source, {"group_search": {"applied": True}}),
                         self.folder / "Book.m4b-tool-metadata.json")
        self.assertEqual(FIXER.get_m4b_tool_metadata_path(self.source), self.folder / "book.m4b.m4b-tool-metadata.json")
        self.assertEqual(FIXER.get_m4b_tool_metadata_path(self.source, {"group_search": None}), self.folder / "book.m4b.m4b-tool-metadata.json")

    def test_the_audiobookshelf_metadata_json_is_plain_for_groups_and_lone_files_and_a_companion_otherwise(self):
        self.assertEqual(FIXER.get_audiobookshelf_metadata_path(self.source), self.folder / "book.m4b.metadata.json")
        self.assertEqual(FIXER.get_audiobookshelf_metadata_path(self.source, alone_in_folder=True), self.folder / "metadata.json")
        self.assertEqual(FIXER.get_audiobookshelf_metadata_path(self.source, {"group_search": {"applied": True}}), self.folder / "metadata.json")
        self.assertEqual(FIXER.get_audiobookshelf_metadata_path(self.source, {"group_search": {"applied": False}}), self.folder / "book.m4b.metadata.json")

    def test_marker_paths(self):
        self.assertEqual(FIXER.get_marker_path(self.source), self.folder / "book.m4b.audible-metadata-fixer.json")
        self.assertEqual(FIXER.get_legacy_marker_path(self.source), self.folder / ".audible-metadata-fixer.json")
        self.assertEqual(FIXER.get_metadata_backup_path(self.source), self.folder / "book.m4b.metadata-backup.json")


class LoadLibraforgeRawTests(SidecarFixture):
    def test_with_nothing_on_disk_the_payload_is_empty_and_the_path_follows_the_layout_rule(self):
        self.assertEqual(FIXER._load_libraforge_raw(self.source), (self.file_lf, {}))
        self.assertEqual(FIXER._load_libraforge_raw(self.source, alone=True), (self.folder_lf, {}))
        self.assertEqual(FIXER._load_libraforge_raw(self.source, {"group_search": {"applied": True}}), (self.folder_lf, {}))
        self.assertFalse(self.folder_lf.exists() or self.file_lf.exists())

    def test_a_folder_sidecar_that_belongs_to_the_file_is_used(self):
        self.write(self.folder_lf, {"marker": {"source_file": "book.m4b", "applied": True}})
        path, payload = FIXER._load_libraforge_raw(self.source)
        self.assertEqual((path, payload["marker"]["applied"]), (self.folder_lf, True))

    def test_a_folder_sidecar_owned_by_another_file_is_never_used_or_overwritten(self):
        other = {"marker": {"source_file": "other.m4b", "applied": True}}
        self.write(self.folder_lf, other)
        path, payload = FIXER._load_libraforge_raw(self.source, alone=True)
        self.assertEqual((path, payload), (self.file_lf, {}))
        self.assertEqual(self.read(self.folder_lf), other)

    def test_a_per_file_sidecar_is_used_as_is_when_the_book_shares_its_folder(self):
        self.write(self.file_lf, {"marker": {"applied": True}})
        path, payload = FIXER._load_libraforge_raw(self.source)
        self.assertEqual((path, payload), (self.file_lf, {"marker": {"applied": True}}))

    def test_a_per_file_sidecar_moves_to_folder_level_once_the_book_is_alone(self):
        self.write(self.file_lf, {"marker": {"applied": True}})
        path, payload = FIXER._load_libraforge_raw(self.source, alone=True)
        self.assertEqual((path, payload), (self.folder_lf, {"marker": {"applied": True}}))
        self.assertFalse(self.file_lf.exists())
        self.assertEqual(self.read(self.folder_lf), {"marker": {"applied": True}})

    def test_the_move_to_folder_level_is_refused_when_another_file_owns_that_path(self):
        self.write(self.folder_lf, {"marker": {"source_file": "other.m4b"}})
        self.write(self.file_lf, {"marker": {"applied": True}})
        path, payload = FIXER._load_libraforge_raw(self.source, alone=True)
        self.assertEqual(path, self.file_lf)
        self.assertTrue(self.file_lf.exists())
        self.assertEqual(self.read(self.folder_lf), {"marker": {"source_file": "other.m4b"}})

    def test_a_corrupt_per_file_sidecar_reads_as_empty_but_keeps_its_path(self):
        self.file_lf.write_text("{not json")
        self.assertEqual(FIXER._load_libraforge_raw(self.source), (self.file_lf, {}))

    def test_old_format_files_are_removed_once_a_current_sidecar_is_found(self):
        old_backup = self.write(self.folder / "book.m4b.metadata-backup.json", {})
        old_marker = self.write(self.folder / "book.m4b.audible-metadata-fixer.json", {})
        self.write(self.file_lf, {"marker": {"applied": True}})
        FIXER._load_libraforge_raw(self.source)
        self.assertFalse(old_backup.exists() or old_marker.exists())

    def test_old_backup_and_marker_files_are_migrated_into_one_stamped_sidecar(self):
        self.write(self.folder / "book.m4b.metadata-backup.json", {"created_at": "t0", "source_file": "book.m4b", "duration_minutes": 5,
                                                                    "format_tags": {"title": "T"}, "junk": 1})
        self.write(self.folder / "book.m4b.audible-metadata-fixer.json", {"applied": True, "mode": "full", "score": 0.9, "junk": 2})
        path, payload = FIXER._load_libraforge_raw(self.source)
        self.assertEqual(path, self.file_lf)
        self.assertEqual(payload["backup"], {"created_at": "t0", "source_file": "book.m4b", "duration_minutes": 5, "format_tags": {"title": "T"}})
        self.assertEqual(payload["marker"], {"applied": True, "mode": "full", "score": 0.9})
        self.assertEqual((payload["schema_version"], payload["tool"]), (2, "audible-metadata-fixer"))
        self.assertIn("migrated_at", payload)
        self.assertEqual(self.read(self.file_lf)["marker"]["mode"], "full")
        self.assertEqual([p.name for p in self.folder.iterdir() if "backup" in p.name or "fixer.json" in p.name], [])

    def test_the_legacy_directory_marker_is_migrated_when_there_is_no_per_file_marker(self):
        self.write(self.folder / ".audible-metadata-fixer.json", {"applied": True, "mode": "series_only"})
        _, payload = FIXER._load_libraforge_raw(self.source)
        self.assertEqual(payload["marker"], {"applied": True, "mode": "series_only"})
        self.assertFalse((self.folder / ".audible-metadata-fixer.json").exists())

    def test_an_old_group_sidecar_is_migrated_to_the_folder_level_path(self):
        group = self.folder / "Book.m4b-tool-metadata.json"
        self.write(group, {"book": {"title": "T"}, "audible": {"asin": "B0"}, "file_cache": {"a": 1}, "extra": 9})
        path, payload = FIXER._load_libraforge_raw(self.source)
        self.assertEqual(path, self.folder_lf)
        self.assertEqual(payload["sidecar"], {"book": {"title": "T"}, "audible": {"asin": "B0"}})
        self.assertEqual(payload["file_cache"], {"a": 1})
        self.assertFalse(group.exists())

    def test_a_corrupt_old_file_is_skipped_and_left_alone(self):
        bad = self.folder / "book.m4b.metadata-backup.json"
        bad.write_text("{bad")
        path, payload = FIXER._load_libraforge_raw(self.source)
        self.assertEqual((path, payload), (self.file_lf, {}))
        self.assertTrue(bad.exists())


class BookSidecarReadTests(SidecarFixture):
    def test_nothing_on_disk_is_none(self):
        self.assertIsNone(FIXER.read_book_sidecar(self.source))

    def test_a_grouped_books_sidecar_book_wins_and_gets_the_audible_asin(self):
        self.write(self.folder_lf, {"sidecar": {"book": {"title": "T", "author": "A"}, "audible": {"asin": "B0X"}},
                                    "marker": {"audible": {"title": "Marker"}}})
        got = FIXER.read_book_sidecar(self.source)
        self.assertEqual((got["title"], got["author"], got["asin"]), ("T", "A", "B0X"))

    def test_an_asin_already_in_the_book_section_is_not_replaced(self):
        self.write(self.folder_lf, {"sidecar": {"book": {"title": "T", "asin": "B0OWN"}, "audible": {"asin": "B0X"}}})
        self.assertEqual(FIXER.read_book_sidecar(self.source)["asin"], "B0OWN")

    def test_a_single_files_marker_is_the_fallback_with_a_chosen_title_preferred(self):
        self.write(self.folder_lf, {"marker": {"audible": {"title": "Audible", "chosen_title": "Chosen", "author": "A", "subtitle": "S",
                                                            "narrator": "N", "series": "Se", "sequence": "2", "year": 2020,
                                                            "summary": "sum", "genre": "G", "isbn": "978", "asin": "b0x"}}})
        got = FIXER.read_book_sidecar(self.source)
        self.assertEqual((got["title"], got["subtitle"], got["author"], got["narrator"]), ("Chosen", "S", "A", "N"))
        self.assertEqual((got["series"], got["sequence"], got["year"], got["summary"], got["genre"], got["isbn"], got["asin"]),
                         ("Se", "2", "2020", "sum", "G", "978", "b0x"))

    def test_a_placeholder_asin_in_the_marker_is_dropped(self):
        self.write(self.folder_lf, {"marker": {"audible": {"title": "T", "asin": "NOREALASIN"}}})
        self.assertEqual(FIXER.read_book_sidecar(self.source)["asin"], "")

    def test_a_sidecar_without_any_title_is_none(self):
        self.write(self.folder_lf, {"sidecar": {"book": {"author": "A"}}, "marker": {"audible": {"author": "A"}}})
        self.assertIsNone(FIXER.read_book_sidecar(self.source))

    def test_a_missing_sidecar_file_with_other_state_is_none(self):
        self.assertIsNone(FIXER.read_book_sidecar(self.folder / "other.m4b"))


class OriginalBackupTests(SidecarFixture):
    def test_given_tags_and_duration_are_stored_without_probing(self):
        with mock.patch.object(FIXER, "probe_file", side_effect=AssertionError("no probe needed")):
            path = FIXER.write_original_metadata_backup(self.source, {"title": "T"}, 12.345678)
        backup = self.read(path)["backup"]
        self.assertEqual((backup["source_file"], backup["duration_minutes"], backup["format_tags"]), ("book.m4b", 12.3457, {"title": "T"}))
        self.assertIn("created_at", backup)
        self.assertEqual(self.read(path)["schema_version"], 2)

    def test_missing_tags_or_duration_are_probed(self):
        with mock.patch.object(FIXER, "probe_file", return_value=({"title": "P"}, 7.0)) as probe:
            path = FIXER.write_original_metadata_backup(self.source)
        probe.assert_called_once()
        self.assertEqual(self.read(path)["backup"]["format_tags"], {"title": "P"})
        with mock.patch.object(FIXER, "probe_file", return_value=({"title": "Q"}, 9.0)):
            other = self.folder / "two.m4b"
            other.write_bytes(b"x")
            self.assertEqual(self.read(FIXER.write_original_metadata_backup(other, {"title": "kept"}))["backup"]["format_tags"], {"title": "kept"})
            third = self.folder / "three.m4b"
            third.write_bytes(b"x")
            got = self.read(FIXER.write_original_metadata_backup(third, None, 1.0))["backup"]
            self.assertEqual((got["format_tags"], got["duration_minutes"]), ({"title": "Q"}, 1.0))

    def test_an_existing_real_backup_is_never_overwritten(self):
        path = FIXER.write_original_metadata_backup(self.source, {"title": "first"}, 1.0)
        again = FIXER.write_original_metadata_backup(self.source, {"title": "second"}, 2.0)
        self.assertEqual(path, again)
        self.assertEqual(self.read(path)["backup"]["format_tags"], {"title": "first"})

    def test_an_empty_backup_from_a_failed_probe_is_replaced(self):
        self.write(self.file_lf, {"backup": {"format_tags": {}, "created_at": "old"}})
        path = FIXER.write_original_metadata_backup(self.source, {"title": "real"}, 3.0)
        self.assertEqual(self.read(path)["backup"]["format_tags"], {"title": "real"})

    def test_a_failed_probe_is_never_recorded(self):
        with mock.patch.object(FIXER, "probe_file", return_value=({}, None)):
            path = FIXER.write_original_metadata_backup(self.source)
        self.assertFalse(path.exists())

    def test_empty_tags_with_a_duration_are_recorded_only_the_first_time(self):
        path = FIXER.write_original_metadata_backup(self.source, {}, 5.0)
        backup = self.read(path)["backup"]
        self.assertEqual((backup["format_tags"], backup["duration_minutes"]), ({}, 5.0))
        self.write(self.file_lf, {"backup": {"format_tags": {}, "created_at": "old"}})
        FIXER.write_original_metadata_backup(self.source, {}, 6.0)
        self.assertEqual(self.read(self.file_lf)["backup"]["created_at"], "old")

    def test_a_zero_duration_is_stored_as_none(self):
        path = FIXER.write_original_metadata_backup(self.source, {"title": "T"}, 0.0)
        self.assertIsNone(self.read(path)["backup"]["duration_minutes"])

    def test_the_lone_file_flag_puts_the_backup_in_the_folder_sidecar(self):
        path = FIXER.write_original_metadata_backup(self.source, {"title": "T"}, 1.0, alone=True)
        self.assertEqual(path, self.folder_lf)


class RestoreAndArgsTests(SidecarFixture):
    def test_marking_restored_clears_applied_and_manual_flags_and_stamps_the_time(self):
        self.write(self.file_lf, {"marker": {"applied": True, "manually_applied": True}})
        FIXER.mark_metadata_restored(self.source)
        marker = self.read(self.file_lf)["marker"]
        self.assertEqual((marker["applied"], marker["manually_applied"]), (False, False))
        self.assertIn("restored_at", marker)

    def test_a_book_without_a_marker_is_left_untouched(self):
        self.write(self.file_lf, {"backup": {"format_tags": {"t": "x"}}})
        FIXER.mark_metadata_restored(self.source)
        self.assertEqual(self.read(self.file_lf), {"backup": {"format_tags": {"t": "x"}}})

    def test_load_marker_returns_the_marker_section_or_empty(self):
        self.assertEqual(FIXER.load_marker(self.source), {})
        self.write(self.file_lf, {"marker": {"applied": True}})
        self.assertEqual(FIXER.load_marker(self.source), {"applied": True})

    def test_raw_tags_become_sorted_metadata_arguments_without_blanks(self):
        got = FIXER.build_raw_metadata_args({"title": "T", "artist": "A", " ": "x", "empty": "", "album": "  "})
        self.assertEqual(got, ["-metadata", "artist=A", "-metadata", "title=T"])
        self.assertEqual(FIXER.build_raw_metadata_args({}), [])
        self.assertEqual(FIXER.build_raw_metadata_args(None), [])


class DuplicateAsinGuardTests(unittest.TestCase):
    def result(self, status="matched", asin="B0X", conflict=False, metadata=True):
        return types.SimpleNamespace(status=status, asin_conflict=conflict, metadata={"asin": asin} if metadata else None)

    def test_a_matched_book_with_an_asin_needs_the_scan(self):
        self.assertTrue(FIXER.needs_duplicate_asin_check([self.result()]))

    def test_unmatched_conflicting_blank_or_metadata_less_results_do_not(self):
        for res in (self.result(status="skipped"), self.result(conflict=True), self.result(asin=""), self.result(metadata=False)):
            self.assertFalse(FIXER.needs_duplicate_asin_check([res]))
        self.assertFalse(FIXER.needs_duplicate_asin_check([]))

    def test_one_qualifying_result_among_many_is_enough(self):
        self.assertTrue(FIXER.needs_duplicate_asin_check([self.result(status="skipped"), self.result()]))

    def test_a_cancelled_run_never_scans(self):
        with mock.patch.object(FIXER, "_cancel_requested", True):
            self.assertIs(FIXER.needs_duplicate_asin_check([self.result()]), False)


class SkipDueToMarkerTests(SidecarFixture):
    def decide(self, marker=None, force=False, aggressive=False):
        if marker is not None:
            self.write(self.file_lf, {"marker": marker})
        return FIXER.should_skip_due_to_marker(self.source, aggressive, force)

    def test_a_book_without_a_marker_is_processed(self):
        self.assertEqual(self.decide(), (False, ""))

    def test_an_applied_marker_skips_the_book(self):
        self.assertEqual(self.decide({"applied": True}), (True, "already processed"))

    def test_an_unapplied_marker_does_not(self):
        self.assertEqual(self.decide({"applied": False}), (False, ""))
        self.assertEqual(self.decide({"applied": "yes"}), (False, ""))      # only a real True counts

    def test_force_reprocesses_an_applied_book(self):
        self.assertEqual(self.decide({"applied": True}, force=True), (False, ""))

    def test_a_manually_applied_book_is_never_touched_even_with_force_or_aggressive(self):
        for kwargs in ({}, {"force": True}, {"aggressive": True}, {"force": True, "aggressive": True}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.decide({"manually_applied": True, "applied": False}, **kwargs), (True, "already manually applied"))


if __name__ == "__main__":
    unittest.main()
