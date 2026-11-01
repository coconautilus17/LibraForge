import json
import tempfile
import unittest
from pathlib import Path

from app.json_files import write_json_atomic


class WriteJsonAtomicTests(unittest.TestCase):
    def test_writes_utf8_json_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new" / "cache.json"
            write_json_atomic(path, {"title": "Kōhai"}, indent=2)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"title": "Kōhai"})
            self.assertIn("Kōhai", path.read_text(encoding="utf-8"))
            self.assertEqual([p.name for p in path.parent.iterdir()], ["cache.json"])

    def test_replaces_an_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            write_json_atomic(path, {"v": 1})
            write_json_atomic(path, {"v": 2}, sort_keys=True)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"v": 2})


if __name__ == "__main__":
    unittest.main()
