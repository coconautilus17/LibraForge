import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


import os
from unittest import mock

MIGRATE = load_module("normalize_author_names_script", "scripts/normalize-author-names.py")


def setUpModule():
    global _env
    _env = mock.patch.dict(os.environ, {"LIBRAFORGE_AUTHOR_SCHEME": "universal"})
    _env.start()


def tearDownModule():
    _env.stop()


def build_library(root: Path):
    for name in ("A. F. Kay", "Kevin J Anderson", "Kevin J. Anderson", "V A Lewis", "George R. R. Martin", "George R.R. Martin", "_unorganized", "Brian McClellan"):
        (root / name).mkdir()
    (root / "Kevin J Anderson" / "Old").mkdir()
    (root / "George R. R. Martin" / "Clash").mkdir()
    (root / "George R.R. Martin" / "Clash").mkdir()
    book = root / "V A Lewis" / "Amber"
    book.mkdir()
    (book / "metadata.json").write_text(json.dumps({"authors": ["V A Lewis", "Mikhail Yagupov - translator"]}))
    (book / "libraforge.json").write_text(json.dumps({"marker": {"audible": {"author": "V A Lewis, TJ Klune"}}}))


class PlanTests(unittest.TestCase):
    def test_folder_plan_marks_renames_and_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_library(root)
            plan = {(c["old"], c["new"], c["action"]) for c in MIGRATE.plan_folder_changes(root)}
            self.assertEqual(plan, {
                ("A. F. Kay", "A.F. Kay", "rename"),
                ("Kevin J Anderson", "Kevin J. Anderson", "merge"),
                ("V A Lewis", "V.A. Lewis", "rename"),
                ("George R. R. Martin", "George R.R. Martin", "merge"),
            })

    def test_sidecar_plan_finds_only_noncanonical_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_library(root)
            edits = MIGRATE.plan_sidecar_changes(root)
            self.assertEqual(sorted((e["field"], e["new"]) for e in edits), [
                ("authors[0]", "V.A. Lewis"),
                ("marker.audible.author", "V.A. Lewis, T.J. Klune"),
            ])


class ApplyAndRevertTests(unittest.TestCase):
    def run_cli(self, *args):
        old = sys.argv
        sys.argv = ["normalize-author-names.py", *map(str, args)]
        try:
            return MIGRATE.main()
        finally:
            sys.argv = old

    def snapshot(self, root: Path):
        return sorted(str(p.relative_to(root)) for p in root.rglob("*"))

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_library(root)
            before = self.snapshot(root)
            self.assertEqual(self.run_cli(root), 0)
            self.assertEqual(self.snapshot(root), before)

    def test_apply_then_revert_restores_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lib"
            root.mkdir()
            build_library(root)
            before = self.snapshot(root)
            before_meta = json.loads((root / "V A Lewis" / "Amber" / "metadata.json").read_text())
            log = Path(tmp) / "changes.jsonl"
            self.run_cli(root, "--apply", "--log", log)
            self.assertTrue((root / "V.A. Lewis" / "Amber").is_dir())
            self.assertTrue((root / "Kevin J. Anderson" / "Old").is_dir())
            # the blocked merge is skipped whole, nothing is overwritten
            self.assertTrue((root / "George R. R. Martin" / "Clash").is_dir())
            meta = json.loads((root / "V.A. Lewis" / "Amber" / "metadata.json").read_text())
            self.assertEqual(meta["authors"], ["V.A. Lewis", "Mikhail Yagupov - translator"])
            self.run_cli(root, "--revert", log)
            self.assertEqual(self.snapshot(root), before)
            # values are restored; file whitespace may be reformatted (2-space JSON)
            self.assertEqual(json.loads((root / "V A Lewis" / "Amber" / "metadata.json").read_text()), before_meta)

    def test_second_run_finds_only_the_blocked_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lib"
            root.mkdir()
            build_library(root)
            self.run_cli(root, "--apply", "--log", Path(tmp) / "a.jsonl")
            remaining = MIGRATE.plan_folder_changes(root)
            self.assertEqual([(c["old"], c["action"]) for c in remaining], [("George R. R. Martin", "merge")])
            self.assertEqual(MIGRATE.plan_sidecar_changes(root), [])


class SchemeOffTests(unittest.TestCase):
    def run_cli(self, *args):
        old = sys.argv
        sys.argv = ["normalize-author-names.py", *map(str, args)]
        try:
            return MIGRATE.main()
        finally:
            sys.argv = old

    def test_refuses_to_run_while_the_scheme_is_off(self):
        with mock.patch.dict(os.environ, {"LIBRAFORGE_AUTHOR_SCHEME": "legacy"}):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build_library(root)
                before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
                self.assertEqual(self.run_cli(root, "--apply"), 2)
                self.assertEqual(sorted(str(p.relative_to(root)) for p in root.rglob("*")), before)

    def test_even_if_disabled_overrides_the_refusal(self):
        with mock.patch.dict(os.environ, {"LIBRAFORGE_AUTHOR_SCHEME": "legacy"}):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build_library(root)
                self.assertEqual(self.run_cli(root, "--even-if-disabled"), 0)


class TagTests(unittest.TestCase):
    def test_mp3_tags_are_rewritten_and_reverted(self):
        from mutagen.id3 import ID3, TPE1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lib"
            book = root / "V A Lewis" / "Amber"
            book.mkdir(parents=True)
            track = book / "a.mp3"
            tags = ID3()
            tags.add(TPE1(encoding=3, text=["V A Lewis"]))
            tags.save(track)
            log = Path(tmp) / "t.jsonl"
            old = sys.argv
            try:
                sys.argv = ["x", str(root), "--apply", "--tags", "--log", str(log)]
                MIGRATE.main()
                self.assertEqual(str(ID3(root / "V.A. Lewis" / "Amber" / "a.mp3")["TPE1"].text[0]), "V.A. Lewis")
                sys.argv = ["x", str(root), "--revert", str(log)]
                MIGRATE.main()
            finally:
                sys.argv = old
            self.assertEqual(str(ID3(track)["TPE1"].text[0]), "V A Lewis")



class AbsAuthorPlanTests(unittest.TestCase):
    """--abs-authors: ABS keeps authors in its DB / central metadata.json, which a
    rescan re-applies over already-corrected files."""

    def plan(self, authors, details, items):
        return MIGRATE.plan_abs_author_changes(authors, lambda i: details.get(i, {}), lambda i: items[i])

    def test_book_with_off_scheme_author_is_patched_to_scheme_spelling(self):
        authors = [{"id": "a1", "name": "DB King"}, {"id": "a2", "name": "D.B. King"}]
        details = {"a1": {"libraryItems": [{"id": "i1"}]}}
        items = {"i1": {"path": "/x", "media": {"metadata": {"authors": [{"name": "DB King"}]}}}}
        changes = self.plan(authors, details, items)
        self.assertEqual([(c["phase"], c["old"], c["new"]) for c in changes], [("abs-item", ["DB King"], ["D.B. King"])])

    def test_multi_author_list_is_fixed_per_name_and_deduplicated(self):
        authors = [{"id": "a1", "name": "T C Liyanage"}]
        details = {"a1": {"libraryItems": [{"id": "i1"}]}}
        items = {"i1": {"path": "/x", "media": {"metadata": {"authors": [{"name": "Extra26"}, {"name": "T C Liyanage"}, {"name": "T.C. Liyanage"}]}}}}
        self.assertEqual(self.plan(authors, details, items)[0]["new"], ["Extra26", "T.C. Liyanage"])

    def test_empty_author_is_deleted_when_scheme_spelling_exists_else_renamed(self):
        authors = [{"id": "a1", "name": "VK Slatter"}, {"id": "a2", "name": "V.K. Slatter"}, {"id": "a3", "name": "JD Kirk"}]
        details = {"a1": {"libraryItems": []}, "a3": {"libraryItems": []}}
        changes = {c["old"]: c for c in self.plan(authors, details, {})}
        self.assertEqual(changes["VK Slatter"]["phase"], "abs-author-delete")
        self.assertEqual((changes["JD Kirk"]["phase"], changes["JD Kirk"]["new"]), ("abs-author-rename", "J.D. Kirk"))

    def test_empty_author_with_data_adopts_a_data_less_twin_instead_of_being_deleted(self):
        authors = [{"id": "a1", "name": "VK Slatter"}, {"id": "a2", "name": "V.K. Slatter"}]
        details = {"a1": {"libraryItems": [], "imagePath": "/metadata/authors/a1.jpg", "asin": "B0"}, "a2": {"libraryItems": [{"id": "i"}]}}
        items = {"i": {"path": "/x", "media": {"metadata": {"authors": [{"name": "V.K. Slatter"}]}}}}
        change = self.plan(authors, details, items)[0]
        self.assertEqual((change["phase"], change["twin_id"], change["keeps"]), ("abs-author-adopt", "a2", ["imagePath", "asin"]))

    def test_empty_author_is_deleted_when_the_twin_already_has_data(self):
        authors = [{"id": "a1", "name": "VK Slatter"}, {"id": "a2", "name": "V.K. Slatter"}]
        details = {"a1": {"libraryItems": [], "asin": "B0"}, "a2": {"libraryItems": [], "asin": "B1"}}
        self.assertEqual(self.plan(authors, details, {})[0]["phase"], "abs-author-delete")

    def test_adopt_parks_the_twin_renames_the_orphan_then_merges_the_twin(self):
        change = {"phase": "abs-author-adopt", "author_id": "aaaaaaaa1", "twin_id": "bbbbbbbb2", "old": "VK Slatter", "new": "V.K. Slatter", "status": "CLEAN"}
        with mock.patch.object(MIGRATE, "abs_get_json", return_value={"libraryItems": []}), \
             mock.patch.object(MIGRATE, "abs_patch_json") as patch:
            self.assertEqual(MIGRATE.apply_abs_changes([change], "u", "k"), [change])
            self.assertEqual([(c.args[0], c.args[1]["name"]) for c in patch.call_args_list], [
                ("/api/authors/bbbbbbbb2", "V.K. Slatter (merging bbbbbbbb)"),
                ("/api/authors/aaaaaaaa1", "V.K. Slatter"),
                ("/api/authors/bbbbbbbb2", "V.K. Slatter"),
            ])

    def test_adopt_restores_the_twin_if_the_rename_fails(self):
        change = {"phase": "abs-author-adopt", "author_id": "aaaaaaaa1", "twin_id": "bbbbbbbb2", "old": "VK", "new": "V.K.", "status": "CLEAN"}
        calls = []
        def fake_patch(path, body, *_):
            calls.append((path, body["name"]))
            if path.endswith("aaaaaaaa1"):
                raise RuntimeError("boom")
        with mock.patch.object(MIGRATE, "abs_get_json", return_value={"libraryItems": []}), \
             mock.patch.object(MIGRATE, "abs_patch_json", side_effect=fake_patch):
            with self.assertRaises(RuntimeError):
                MIGRATE.apply_abs_changes([change], "u", "k")
        self.assertEqual(calls[-1], ("/api/authors/bbbbbbbb2", "V.K."))

    def test_apply_patches_books_first_skips_uncertain_and_rechecks_deletes(self):
        changes = [
            {"phase": "abs-author-delete", "author_id": "a1", "old": "VK Slatter", "new": "V.K. Slatter", "status": "CLEAN"},
            {"phase": "abs-author-delete", "author_id": "a9", "old": "X", "new": "Y", "status": "UNCERTAIN"},
            {"phase": "abs-item", "item_id": "i1", "path": "", "old": ["DB King"], "new": ["D.B. King"], "status": "CLEAN"},
        ]
        with mock.patch.object(MIGRATE, "abs_patch_json") as patch, \
             mock.patch.object(MIGRATE, "abs_get_json", return_value={"libraryItems": []}), \
             mock.patch.object(MIGRATE, "abs_delete_json") as delete:
            applied = MIGRATE.apply_abs_changes(changes, "http://abs", "k")
            patch.assert_called_once_with("/api/items/i1/media", {"metadata": {"authors": [{"name": "D.B. King"}]}}, "http://abs", "k")
            delete.assert_called_once_with("/api/authors/a1", "http://abs", "k")
            self.assertEqual([c["phase"] for c in applied], ["abs-item", "abs-author-delete"])
            patch.reset_mock(); delete.reset_mock()
            MIGRATE.apply_abs_changes(applied, "http://abs", "k", reverse=True)
            self.assertEqual(patch.call_args.args[1]["metadata"]["authors"], [{"name": "DB King"}])
            delete.assert_not_called()

    def test_each_applied_change_is_reported_as_it_happens(self):
        seen = []
        changes = [{"phase": "abs-author-rename", "author_id": "a", "old": "A. L. F", "new": "A.L. F", "status": "CLEAN"}]
        with mock.patch.object(MIGRATE, "abs_patch_json"):
            MIGRATE.apply_abs_changes(changes, "u", "k", on_applied=seen.append)
        self.assertEqual(seen, changes)

    def test_delete_tolerates_abs_plain_text_ok_reply(self):
        import app.abs_client as client
        with mock.patch.object(client, "_abs_send_json", side_effect=json.JSONDecodeError("x", "OK", 0)):
            self.assertEqual(client.abs_delete_json("/api/authors/a", "u", "k"), {})

    def test_delete_is_skipped_if_the_author_regained_a_book(self):
        change = {"phase": "abs-author-delete", "author_id": "a1", "old": "VK", "new": "V.K.", "status": "CLEAN"}
        with mock.patch.object(MIGRATE, "abs_get_json", return_value={"libraryItems": [{"id": "i"}]}), \
             mock.patch.object(MIGRATE, "abs_delete_json") as delete:
            self.assertEqual(MIGRATE.apply_abs_changes([change], "u", "k"), [])
            delete.assert_not_called()


class SidecarAuthorEditPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, payload):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_metadata_json_authors_are_fixed_one_by_one_with_their_index(self):
        path = self.write("A/metadata.json", {"authors": ["V A Lewis", "Brian McClellan", "J R R Tolkien", 7]})
        edits = MIGRATE._json_author_edits(path)
        self.assertEqual([(e["field"], e["old"], e["new"]) for e in edits],
                         [("authors[0]", "V A Lewis", "V.A. Lewis"), ("authors[2]", "J R R Tolkien", "J.R.R. Tolkien")])
        self.assertTrue(all(e["phase"] == "sidecar" and e["path"] == str(path) for e in edits))

    def test_only_files_named_metadata_json_have_their_authors_list_read(self):
        path = self.write("A/libraforge.json", {"authors": ["V A Lewis"]})
        self.assertEqual(MIGRATE._json_author_edits(path), [])

    def test_a_non_list_authors_value_is_ignored(self):
        path = self.write("A/metadata.json", {"authors": "V A Lewis"})
        self.assertEqual(MIGRATE._json_author_edits(path), [])

    def test_the_marker_audible_author_credit_is_fixed_as_a_whole_credit(self):
        path = self.write("A/libraforge.json", {"marker": {"audible": {"author": "V A Lewis, Kevin J Anderson"}}})
        edits = MIGRATE._json_author_edits(path)
        self.assertEqual([(e["field"], e["new"]) for e in edits], [("marker.audible.author", "V.A. Lewis, Kevin J. Anderson")])

    def test_already_correct_blank_or_malformed_sidecars_plan_nothing(self):
        self.assertEqual(MIGRATE._json_author_edits(self.write("A/libraforge.json", {"marker": {"audible": {"author": "V.A. Lewis"}}})), [])
        self.assertEqual(MIGRATE._json_author_edits(self.write("B/libraforge.json", {"marker": "x"})), [])
        bad = self.root / "C" / "metadata.json"
        bad.parent.mkdir()
        bad.write_text("{not json")
        self.assertEqual(MIGRATE._json_author_edits(bad), [])
        self.assertEqual(MIGRATE._json_author_edits(self.root / "missing.json"), [])

    def test_the_planner_walks_the_tree_skipping_service_folders_and_other_file_names(self):
        self.write("A/metadata.json", {"authors": ["V A Lewis"]})
        self.write("#recycle/metadata.json", {"authors": ["V A Lewis"]})
        self.write(".hidden/libraforge.json", {"marker": {"audible": {"author": "V A Lewis"}}})
        self.write("A/notes.json", {"authors": ["V A Lewis"]})
        edits = MIGRATE.plan_sidecar_changes(self.root)
        self.assertEqual([Path(e["path"]).parent.name for e in edits], ["A"])


class AbsAuthorPlanEdgeTests(unittest.TestCase):
    def test_a_book_shared_by_two_off_scheme_authors_is_planned_once(self):
        authors = [{"id": "a1", "name": "V A Lewis"}, {"id": "a2", "name": "K J Anderson"}]
        details = {"a1": {"libraryItems": [{"id": "i1"}]}, "a2": {"libraryItems": [{"id": "i1"}]}}
        items = {"i1": {"path": "/x", "media": {"metadata": {"authors": [{"name": "V A Lewis"}, {"name": "K J Anderson"}]}}}}
        changes = MIGRATE.plan_abs_author_changes(authors, lambda i: details[i], lambda i: items[i])
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0]["item_id"], changes[0]["path"], changes[0]["status"]),
                         ("i1", "/x", "CLEAN"))
        self.assertEqual(changes[0]["new"], ["V.A. Lewis", "K.J. Anderson"])

    def test_a_book_whose_credits_are_already_on_scheme_is_not_changed(self):
        authors = [{"id": "a1", "name": "V A Lewis"}]
        details = {"a1": {"libraryItems": [{"id": "i1"}]}}
        items = {"i1": {"path": "/x", "media": {"metadata": {"authors": [{"name": "V.A. Lewis"}]}}}}
        self.assertEqual(MIGRATE.plan_abs_author_changes(authors, lambda i: details[i], lambda i: items[i]), [])

    def test_authors_already_on_scheme_are_not_even_fetched(self):
        fetched = []
        MIGRATE.plan_abs_author_changes([{"id": "a1", "name": "V.A. Lewis"}], lambda i: fetched.append(i) or {}, lambda i: {})
        self.assertEqual(fetched, [])


class MainExitCodeAndOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "lib"
        self.root.mkdir()
        (self.root / "V A Lewis").mkdir()
        (self.root / "V.A. Lewis").mkdir()
        (self.root / "Brian McClellan").mkdir()
        self.log = Path(self.tmp.name) / "deep" / "log.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["x", str(self.root), *args]), contextlib.redirect_stdout(out):
            code = MIGRATE.main()
        return code, out.getvalue()

    def test_a_dry_run_reports_counts_including_merges_and_changes_nothing(self):
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Author folders to change: 1 (1 merges)", out)
        self.assertIn("Sidecar author fields to change: 0", out)
        self.assertIn("Embedded tag fields to change: 0 (not scanned, pass --tags)", out)
        self.assertIn("Dry run only", out)
        self.assertTrue((self.root / "V A Lewis").exists())

    def test_the_tag_scan_message_changes_when_tags_are_requested(self):
        _, out = self.run_main("--tags")
        self.assertIn("Embedded tag fields to change: 0\n", out)
        self.assertNotIn("not scanned", out)

    def test_apply_returns_zero_creates_the_log_folder_and_records_the_folder_changes(self):
        code, out = self.run_main("--apply", "--log", str(self.log))
        self.assertEqual(code, 0)
        self.assertIn(f"Done. Change log: {self.log}", out)
        entries = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["phase"] for e in entries][-1], "folder")
        self.assertFalse((self.root / "V A Lewis").exists())

    def test_with_the_scheme_off_nothing_runs_and_the_exit_code_is_two(self):
        with mock.patch.dict(os.environ, {"LIBRAFORGE_AUTHOR_SCHEME": "legacy"}):
            code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("switched off", out)

    def test_even_if_disabled_overrides_the_off_switch(self):
        with mock.patch.dict(os.environ, {"LIBRAFORGE_AUTHOR_SCHEME": "legacy"}):
            code, out = self.run_main("--even-if-disabled")
        self.assertEqual(code, 0)
        self.assertIn("Author folders to change", out)

    def test_revert_undoes_a_logged_apply_and_exits_zero(self):
        self.run_main("--apply", "--log", str(self.log))
        code, out = self.run_main("--revert", str(self.log))
        self.assertEqual(code, 0)
        self.assertIn("Reverted changes", out)
        self.assertTrue((self.root / "V A Lewis").exists())


if __name__ == "__main__":
    unittest.main()
