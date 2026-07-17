"""Smoke tests for Chapter Forge's /chapter-forge page and /api/chaptering/* routes.

The chapter-detection algorithm itself (app/chaptering.py) has zero app.*
imports and no faster-whisper dependency at import time, but real detection
runs require faster-whisper to be installed -- these tests only exercise the
FastAPI wiring (page renders, path validation, request shape), not ASR.
"""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from unittest.mock import patch

from app import main

client = TestClient(main.app)


class ChapterForgePageTests(unittest.TestCase):
    def test_page_renders(self):
        response = client.get("/chapter-forge")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Chapter Forge", response.text)
        self.assertIn("chapter-forge.js", response.text)

    def test_nav_link_present_on_other_pages(self):
        for path in ("/", "/m4b-tool", "/organizer", "/enrichment-forge"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('href="/chapter-forge"', response.text, path)


class ChapteringLoadEndpointTests(unittest.TestCase):
    def test_load_rejects_path_outside_audiobooks_root(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(main, "AUDIOBOOKS_ROOT", Path(root)):
                response = client.post(
                    "/api/chaptering/load",
                    json={"source_path": "/etc/passwd"},
                )
                self.assertEqual(response.status_code, 400)

    def test_load_no_existing_result(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "book.mp3").write_bytes(b"")
            with patch.object(main, "AUDIOBOOKS_ROOT", root_path):
                response = client.post(
                    "/api/chaptering/load",
                    json={"source_path": str(root_path / "book.mp3")},
                )
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertIsNone(data["result"])
                self.assertEqual(data["audio_files"], [str(root_path / "book.mp3")])


class ChapteringRunsEndpointTests(unittest.TestCase):
    def test_rejects_unsupported_backend(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "book.mp3").write_bytes(b"")
            with patch.object(main, "AUDIOBOOKS_ROOT", root_path):
                response = client.post(
                    "/api/chaptering/runs",
                    json={
                        "source_path": str(root_path / "book.mp3"),
                        "backend": "remote-faster-whisper",
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("Unsupported chaptering backend", response.json()["detail"])


class ChapteringResourcesEndpointTests(unittest.TestCase):
    def test_returns_resource_snapshot_shape(self):
        response = client.get("/api/chaptering/resources")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in ("cpu_cores", "cpu_percent", "memory_percent", "asr_models"):
            self.assertIn(key, data)
        self.assertIsInstance(data["asr_models"], list)


class ChapteringSaveEndpointTests(unittest.TestCase):
    def test_save_writes_artifacts_and_sorts_by_start(self):
        # The save endpoint sorts by start and re-numbers ids, but trusts the
        # client's own start/end pairs -- it does not recompute end-from-
        # next-start server-side (that normalization is chapter-forge.js's
        # job before it ever POSTs here).
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "book.mp3").write_bytes(b"")
            with patch.object(main, "AUDIOBOOKS_ROOT", root_path):
                response = client.post(
                    "/api/chaptering/save",
                    json={
                        "source_path": str(root_path / "book.mp3"),
                        "duration": 120.0,
                        "chapters": [
                            {"start": 60.0, "end": 120.0, "title": "Chapter 2"},
                            {"start": 0.0, "end": 60.0, "title": "Chapter 1"},
                        ],
                    },
                )
                self.assertEqual(response.status_code, 200)
                data = response.json()
                chapters = data["result"]["chapters"]
                self.assertEqual([c["title"] for c in chapters], ["Chapter 1", "Chapter 2"])
                self.assertEqual([c["id"] for c in chapters], [1, 2])
                self.assertEqual(chapters[0]["end"], 60.0)
                self.assertTrue(all(c["manual"] for c in chapters))
                # Chapter Forge writes into the same libraforge.json sidecar
                # Fixer/Manual Review use, under a "chapter_forge" key --
                # not a separate file.
                self.assertIn("sidecar", data["artifacts"])
                self.assertIn("cue", data["artifacts"])
                sidecar = json.loads(Path(data["artifacts"]["sidecar"]).read_text())
                self.assertIn("chapter_forge", sidecar)


if __name__ == "__main__":
    unittest.main()
