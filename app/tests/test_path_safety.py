import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app.main as main_module
from app.main import assert_under_audiobooks, safe_child, validate_audiobook_browse_path


class SafeChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_child_returned(self):
        result = safe_child(self.base, "file.py")
        self.assertEqual(result, self.base / "file.py")

    def test_traversal_raises(self):
        with self.assertRaises(HTTPException) as ctx:
            safe_child(self.base, "../etc/passwd")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_absolute_escape_raises(self):
        with self.assertRaises(HTTPException):
            safe_child(self.base, "/etc/passwd")


class AssertUnderAudiobooksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig
        self.tmp.cleanup()

    def test_path_under_root_passes(self):
        p = self.root / "Author" / "Book"
        result = assert_under_audiobooks(p)
        self.assertEqual(result, p)

    def test_root_itself_passes(self):
        result = assert_under_audiobooks(self.root)
        self.assertEqual(result, self.root)

    def test_traversal_raises(self):
        escaped = (self.root / ".." / "etc" / "passwd").resolve()
        with self.assertRaises(HTTPException) as ctx:
            assert_under_audiobooks(escaped)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_sibling_directory_raises(self):
        sibling = self.root.parent / "other"
        with self.assertRaises(HTTPException):
            assert_under_audiobooks(sibling)

    def test_symlink_resolved_path_outside_root_raises(self):
        inside = self.root / "link"
        target = Path(self.tmp.name).parent / "outside"
        target.mkdir(exist_ok=True)
        try:
            inside.symlink_to(target)
            resolved = inside.resolve()
            with self.assertRaises(HTTPException):
                assert_under_audiobooks(resolved)
        finally:
            if inside.exists() or inside.is_symlink():
                inside.unlink()
            if target.exists():
                target.rmdir()


class ValidateAudiobookBrowsePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig
        self.tmp.cleanup()

    def test_valid_subdirectory_passes(self):
        sub = self.root / "Author"
        sub.mkdir()
        result = validate_audiobook_browse_path(str(sub))
        self.assertEqual(result, sub)

    def test_traversal_in_path_raises(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_audiobook_browse_path(str(self.root / ".." / "etc"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_absolute_outside_root_raises(self):
        with self.assertRaises(HTTPException):
            validate_audiobook_browse_path("/etc/passwd")

    def test_nonexistent_path_raises(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_audiobook_browse_path(str(self.root / "nonexistent"))
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
