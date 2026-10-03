import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_module


client = TestClient(main_module.app)


def scan_events(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


class ScanStreamProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("First", "Second"):
            folder = self.root / name
            folder.mkdir()
            (folder / f"{name}.mp3").write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def test_stream_reports_discovery_then_book_progress_and_same_result(self):
        with patch.object(main_module, "AUDIOBOOKS_ROOT", self.root), \
             patch.object(main_module, "FOLDER_SCAN_CACHE", self.root / "scan-cache.json"), \
             patch.object(main_module.library_index, "ensure_library_index_fresh"):
            response = client.post("/api/scan/stream", json={"path": str(self.root)})
            sync = client.post("/api/scan", json={"path": str(self.root)})

        self.assertEqual(response.status_code, 200)
        events = scan_events(response)
        phases = [event["phase"] for event in events if event["kind"] == "progress"]
        self.assertIn("discovering", phases)
        self.assertIn("grouping", phases)
        self.assertIn("categorizing", phases)
        self.assertIn("saving", phases)
        discovery = next(event for event in events if event.get("phase") == "discovering")
        self.assertGreaterEqual(discovery["entries"], 1)
        self.assertGreaterEqual(discovery["response_ms"], 0)
        categorized = [event for event in events if event.get("phase") == "categorizing"]
        self.assertEqual((categorized[-1]["completed"], categorized[-1]["total"]), (2, 2))
        self.assertEqual(events[-1]["kind"], "result")
        self.assertEqual(events[-1]["result"]["total"], sync.json()["total"])

    def test_missing_path_reports_error_event(self):
        response = client.post("/api/scan/stream", json={"path": str(self.root / "missing")})
        self.assertEqual(response.status_code, 200)
        events = scan_events(response)
        self.assertEqual(events[-1]["kind"], "error")
        self.assertIn("Directory not found", events[-1]["error"])


if __name__ == "__main__":
    unittest.main()
