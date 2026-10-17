"""Folder Forge file-move rules, on a real temporary folder tree: where a loose
file may land, which companions travel with it, what is never overwritten, and
how companion names are normalised after the move."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_move_safety", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def touch(self, rel, content=b"x"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path


class UniqueTargetPathTests(Tree):
    def test_a_free_name_is_used_as_is(self):
        self.assertEqual(ORG.unique_target_path(self.root, "a.m4b"), self.root / "a.m4b")

    def test_an_existing_or_reserved_name_gets_the_next_free_counter_starting_at_two(self):
        self.touch("a.m4b")
        self.assertEqual(ORG.unique_target_path(self.root, "a.m4b"), self.root / "a-2.m4b")
        self.touch("a-2.m4b")
        self.assertEqual(ORG.unique_target_path(self.root, "a.m4b", {self.root / "a-3.m4b"}), self.root / "a-4.m4b")
        self.assertEqual(ORG.unique_target_path(self.root, "fresh.m4b", {self.root / "fresh.m4b"}), self.root / "fresh-2.m4b")


class ExistingBookFilesTests(Tree):
    def test_only_audio_files_count_for_an_audiobook_in_name_order(self):
        self.touch("T/b.m4b")
        self.touch("T/A.mp3")
        self.touch("T/cover.jpg")
        self.touch("T/notes.txt")
        (self.root / "T" / "sub").mkdir()
        self.assertEqual([p.name for p in ORG.existing_book_files(self.root / "T")], ["A.mp3", "b.m4b"])

    def test_only_ebooks_count_for_an_ebook_item(self):
        self.touch("T/book.epub")
        self.touch("T/book.m4b")
        self.assertEqual([p.name for p in ORG.existing_book_files(self.root / "T", "ebook")], ["book.epub"])

    def test_a_missing_folder_has_no_book_files(self):
        self.assertEqual(ORG.existing_book_files(self.root / "nope"), [])


class CompanionDiscoveryTests(Tree):
    def test_suffix_companions_and_same_stem_side_files_are_found(self):
        audio = self.touch("In/Book.m4b")
        for name in ("Book.m4b.libraforge.json", "Book.m4b.metadata.json", "Book.jpg", "Book.txt", "Book.png"):
            self.touch(f"In/{name}")
        self.touch("In/Other.jpg")
        got = sorted(p.name for p in ORG.companion_files_for(audio))
        self.assertEqual(got, ["Book.jpg", "Book.m4b.libraforge.json", "Book.m4b.metadata.json", "Book.png", "Book.txt"])

    def test_an_ebook_is_never_its_own_companion(self):
        book = self.touch("In/Book.epub")
        self.assertNotIn(book, ORG.companion_files_for(book))

    def test_generic_sidecars_and_covers_of_the_folder_are_found_but_not_the_audio_itself(self):
        audio = self.touch("In/Book.m4b")
        for name in ("libraforge.json", "metadata.json", "cover.jpg", "Cover.PNG", "book_cover.webp", "folder.jpg", "other.m4b", "cover.m4b"):
            self.touch(f"In/{name}")
        got = [p.name for p in ORG.generic_sidecars_for_loose_file(audio)]
        self.assertEqual(got, ["Cover.PNG", "book_cover.webp", "cover.jpg", "libraforge.json", "metadata.json"])


class PlanLooseFileMoveTests(Tree):
    def item(self, rel="src/Forge Master.m4b", media="audiobook"):
        path = self.touch(rel)
        return ORG.BookItem("loose_file", path, [path], path, media_type=media)

    def plan(self, item, target_dir, **kw):
        return ORG.plan_loose_file_move(item, target_dir, **kw)

    def test_a_free_target_folder_accepts_the_file_under_its_own_name(self):
        item = self.item()
        ok, path, reason = self.plan(item, self.root / "lib" / "Forge Master")
        self.assertEqual((ok, reason), (True, ""))
        self.assertEqual(path.parent, self.root / "lib" / "Forge Master")
        self.assertEqual(path.suffix, ".m4b")

    def test_a_file_already_in_its_target_folder_is_not_moved(self):
        item = self.item("lib/Forge Master/Forge Master.m4b")
        ok, path, reason = self.plan(item, self.root / "lib" / "Forge Master")
        self.assertEqual((ok, path, reason), (False, None, "already in target folder"))

    def test_a_folder_claimed_by_another_book_this_run_is_refused(self):
        item = self.item()
        target = self.root / "lib" / "Forge Master"
        ok, path, reason = self.plan(item, target, reserved_target_dirs={target})
        self.assertEqual((ok, path, reason), (False, None, "target folder already used by another book this run"))

    def test_a_folder_that_already_holds_a_book_is_refused_unless_merging_is_allowed(self):
        item = self.item()
        target = self.root / "lib" / "Forge Master"
        self.touch("lib/Forge Master/existing.m4b")
        ok, path, reason = self.plan(item, target)
        self.assertEqual((ok, path, reason), (False, None, "target folder already exists"))
        ok, path, reason = self.plan(item, target, merge_existing=True)
        self.assertEqual((ok, reason), (True, ""))
        self.assertNotEqual(path.name, "existing.m4b")

    def test_a_folder_holding_only_a_cover_is_still_free(self):
        item = self.item()
        target = self.root / "lib" / "Forge Master"
        self.touch("lib/Forge Master/cover.jpg")
        self.assertTrue(self.plan(item, target)[0])

    def test_an_ebook_is_not_blocked_by_the_audiobook_in_the_folder(self):
        item = self.item("src/Forge Master.epub", media="ebook")
        target = self.root / "lib" / "Forge Master"
        self.touch("lib/Forge Master/Forge Master.m4b")
        ok, path, _ = self.plan(item, target)
        self.assertTrue(ok)
        self.assertEqual(path, target / "Forge Master.epub")

    def test_an_ebook_is_blocked_by_another_ebook(self):
        item = self.item("src/Forge Master.epub", media="ebook")
        target = self.root / "lib" / "Forge Master"
        self.touch("lib/Forge Master/Other.epub")
        self.assertEqual(self.plan(item, target)[2], "target folder already exists")

    def test_a_reserved_target_file_name_is_uniquified(self):
        item = self.item()
        target = self.root / "lib" / "Forge Master"
        ok, path, _ = self.plan(item, target, reserved_targets={target / "Forge Master.m4b"})
        self.assertTrue(ok)
        self.assertEqual(path, target / "Forge Master-2.m4b")


class ConflictDetailsTests(unittest.TestCase):
    def test_the_target_folder_is_always_listed_last(self):
        self.assertEqual(ORG.conflict_review_details(Path("/lib/T"), None), [{"label": "Would land in", "value": "/lib/T"}])

    def test_existing_files_and_the_claimant_are_listed_before_it_in_that_order(self):
        got = ORG.conflict_review_details(Path("/lib/T"), Path("/src/other"), [Path("/lib/T/a.m4b"), Path("/lib/T/b.m4b")])
        self.assertEqual([d["label"] for d in got], ["Already claimed by", "Already in that folder", "Would land in"])
        self.assertEqual(got[0]["value"], "/src/other")
        self.assertEqual(got[1]["value"], "a.m4b; b.m4b")

    def test_only_the_first_five_existing_files_are_named_with_a_count_of_the_rest(self):
        files = [Path(f"/lib/T/{n}.m4b") for n in range(1, 8)]
        shown = ORG.conflict_review_details(Path("/lib/T"), None, files)[0]["value"]
        self.assertEqual(shown, "1.m4b; 2.m4b; 3.m4b; 4.m4b; 5.m4b; and 2 more")
        five = ORG.conflict_review_details(Path("/lib/T"), None, files[:5])[0]["value"]
        self.assertEqual(five, "1.m4b; 2.m4b; 3.m4b; 4.m4b; 5.m4b")


class ExecuteLooseMoveTests(Tree):
    def execute(self, source, target, companions, **kw):
        ORG.execute_planned_move({"kind": "loose_file", "source": source, "target": target, "companions": companions},
                                 merge_existing_targets=False, remove_empty_dirs=kw.get("remove_empty_dirs", False), root=self.root)

    def test_side_files_keep_their_stem_and_follow_the_renamed_audio(self):
        audio = self.touch("in/Old Name.m4b")
        jpg = self.touch("in/Old Name.jpg")
        self.execute(audio, self.root / "lib" / "New Name.m4b", [jpg])
        self.assertTrue((self.root / "lib" / "New Name.m4b").exists())
        self.assertTrue((self.root / "lib" / "New Name.jpg").exists())
        self.assertFalse(jpg.exists())

    def test_suffix_companions_are_renamed_after_the_audio_and_then_to_their_generic_names(self):
        audio = self.touch("in/Old.m4b")
        side = self.touch("in/Old.m4b.libraforge.json", b"lf")
        meta = self.touch("in/Old.m4b.metadata.json", b"md")
        self.execute(audio, self.root / "lib" / "New.m4b", [side, meta])
        self.assertEqual((self.root / "lib" / "libraforge.json").read_bytes(), b"lf")
        self.assertEqual((self.root / "lib" / "metadata.json").read_bytes(), b"md")
        self.assertEqual(sorted(p.name for p in (self.root / "lib").iterdir()), ["New.m4b", "libraforge.json", "metadata.json"])

    def test_an_existing_generic_name_is_not_overwritten_by_the_companion(self):
        audio = self.touch("in/Old.m4b")
        side = self.touch("in/Old.m4b.libraforge.json", b"new")
        self.touch("lib/libraforge.json", b"existing")
        self.execute(audio, self.root / "lib" / "New.m4b", [side])
        self.assertEqual((self.root / "lib" / "libraforge.json").read_bytes(), b"existing")
        self.assertEqual((self.root / "lib" / "New.m4b.libraforge.json").read_bytes(), b"new")

    def test_generic_sidecars_and_covers_keep_their_own_names(self):
        audio = self.touch("in/Old.m4b")
        cover = self.touch("in/cover.jpg", b"c")
        generic = self.touch("in/metadata.json", b"m")
        self.execute(audio, self.root / "lib" / "New.m4b", [cover, generic])
        self.assertEqual(sorted(p.name for p in (self.root / "lib").iterdir()), ["New.m4b", "cover.jpg", "metadata.json"])

    def test_emptied_source_folders_are_removed_only_when_asked_and_never_the_root(self):
        audio = self.touch("a/b/Old.m4b")
        self.execute(audio, self.root / "lib" / "New.m4b", [], remove_empty_dirs=False)
        self.assertTrue((self.root / "a" / "b").exists())
        audio2 = self.touch("c/d/Old.m4b")
        self.execute(audio2, self.root / "lib" / "New2.m4b", [], remove_empty_dirs=True)
        self.assertFalse((self.root / "c").exists())
        self.assertTrue(self.root.exists())

    def test_a_non_empty_parent_is_kept(self):
        audio = self.touch("c/d/Old.m4b")
        self.touch("c/keep.txt")
        self.execute(audio, self.root / "lib" / "New.m4b", [], remove_empty_dirs=True)
        self.assertFalse((self.root / "c" / "d").exists())
        self.assertTrue((self.root / "c" / "keep.txt").exists())


class MoveFolderContentsTests(Tree):
    def test_every_child_is_moved_and_the_empty_source_removed(self):
        self.touch("src/a.m4b")
        self.touch("src/sub/b.txt")
        ORG.move_folder_contents(self.root / "src", self.root / "dst")
        self.assertEqual(sorted(p.name for p in (self.root / "dst").iterdir()), ["a.m4b", "sub"])
        self.assertFalse((self.root / "src").exists())

    def test_a_name_clash_aborts_without_overwriting(self):
        self.touch("src/a.m4b", b"new")
        self.touch("dst/a.m4b", b"old")
        with self.assertRaises(FileExistsError):
            ORG.move_folder_contents(self.root / "src", self.root / "dst")
        self.assertEqual((self.root / "dst" / "a.m4b").read_bytes(), b"old")
        self.assertTrue((self.root / "src" / "a.m4b").exists())

    def test_remove_empty_parents_stops_at_a_non_empty_folder(self):
        self.touch("a/b/c/keep.txt")
        (self.root / "a" / "b" / "c" / "keep.txt").unlink()
        self.touch("a/other.txt")
        ORG.remove_empty_parents(self.root / "a" / "b" / "c", self.root)
        self.assertFalse((self.root / "a" / "b").exists())
        self.assertTrue((self.root / "a").exists())


if __name__ == "__main__":
    unittest.main()
