import importlib.util
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


if __name__ == "__main__":
    unittest.main()
