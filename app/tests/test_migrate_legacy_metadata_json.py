"""Library-wide legacy metadata.json migration planner (LibraForge #298).

The planner is side-effect free: it reads files and fetches ABS records but
never writes, deletes or PATCHes -- that is what makes the script's default
dry run safe to point at a real library.
"""
import json
import tempfile
import unittest
from pathlib import Path

from app import abs_client


def _never(*a, **k):
    raise AssertionError("the planner must not write")


class PlanLegacyMetadataJsonMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.expanded = {}
        self.mtimes = {}

    def book(self, name, file_data, abs_meta, updated_at=2_000_000, mtime_s=1_000, is_file=False):
        folder = self.root / name; folder.mkdir()
        if file_data is not None:
            f = folder / "metadata.json"
            f.write_text(file_data if isinstance(file_data, str) else json.dumps(file_data), encoding="utf-8")
            self.mtimes[str(f)] = mtime_s
        item_id = f"id-{name}"
        self.expanded[item_id] = {"id": item_id, "path": str(folder), "isFile": is_file, "updatedAt": updated_at,
                                  "media": {"metadata": abs_meta}}
        return {"id": item_id, "path": str(folder), "isFile": is_file}

    def plan(self, items):
        return abs_client.plan_legacy_metadata_json_migration(
            items, get_item=lambda i: self.expanded[i], mtime_fn=lambda p: self.mtimes[p])

    def test_actions_per_case_without_side_effects(self):
        items = [
            self.book("same", {"title": "T", "genres": ["Audiobook"]}, {"title": "T", "genres": []}),
            self.book("absnewer", {"title": "Old"}, {"title": "New"}, mtime_s=1_000),
            self.book("filenewer", {"publisher": "P"}, {"title": "T"}, mtime_s=3_000),
            self.book("broken", "{nope", {"title": "T"}),
            self.book("nofile", None, {"title": "T"}),
        ]
        rows = {r["path"].rsplit("/", 1)[-1]: r for r in self.plan(items)}
        self.assertEqual(rows["same"]["action"], "delete_identical")
        self.assertEqual(rows["absnewer"]["action"], "delete_abs_newer")
        self.assertEqual((rows["filenewer"]["action"], rows["filenewer"]["fields"]), ("consolidate_then_delete", ["publisher"]))
        self.assertEqual(rows["broken"]["action"], "keep_unreadable")
        self.assertNotIn("nofile", rows)
        for name in ("same", "absnewer", "filenewer", "broken"):
            self.assertTrue((self.root / name / "metadata.json").exists())

    def test_single_file_items_are_listed_as_skipped_and_never_fetched(self):
        item = self.book("loose", {"title": "X"}, {"title": "T"}, is_file=True)
        rows = abs_client.plan_legacy_metadata_json_migration(
            [item], get_item=_never, mtime_fn=lambda p: 0)
        self.assertEqual(rows, [])


class ApplyLegacyMetadataJsonMigrationTests(unittest.TestCase):
    """--apply is an irreversible bulk delete: every file is backed up in full
    before it can be deleted, and one bad book never aborts the run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backup = self.root / "backup"

    def row(self, name, content='{"title": "T", "tags": ["keep me"]}', action="delete_identical"):
        folder = self.root / name; folder.mkdir()
        (folder / "metadata.json").write_text(content, encoding="utf-8")
        return {"id": f"id-{name}", "path": str(folder), "action": action, "fields": [], "diff": {}}

    def test_full_file_is_backed_up_before_reconcile_and_errors_are_recorded_per_row(self):
        rows = [self.row("a"), self.row("b"), self.row("c", action="keep_unreadable")]
        seen_backup = []

        def reconcile(path, item):
            seen_backup.append((self.backup / f"{item['id']}.json").read_text(encoding="utf-8"))
            (Path(path) / "metadata.json").unlink()
            return {"action": "deleted_identical", "fields": []}

        def get_item(item_id):
            if item_id == "id-b":
                raise RuntimeError("ABS 502")
            return {"id": item_id}

        outcome = abs_client.apply_legacy_metadata_json_migration(
            rows, get_item=get_item, reconcile=reconcile, backup_dir=self.backup)
        self.assertEqual(seen_backup, ['{"title": "T", "tags": ["keep me"]}'])
        self.assertEqual(outcome, {"deleted_identical": 1, "error": 1, "kept_unreadable": 1})
        self.assertEqual(rows[0]["result"], "deleted_identical")
        self.assertEqual(rows[0]["backup"], str(self.backup / "id-a.json"))
        self.assertEqual((rows[1]["result"], rows[1]["error"]), ("error", "ABS 502"))
        self.assertTrue((self.root / "b" / "metadata.json").exists())
        self.assertEqual(rows[2]["result"], "kept_unreadable")

    def test_backup_failure_skips_the_book_without_deleting(self):
        rows = [self.row("a")]
        self.backup.write_text("not a dir", encoding="utf-8")
        outcome = abs_client.apply_legacy_metadata_json_migration(
            rows, get_item=lambda i: {"id": i}, reconcile=_never, backup_dir=self.backup)
        self.assertEqual(outcome, {"error": 1})
        self.assertTrue((self.root / "a" / "metadata.json").exists())
