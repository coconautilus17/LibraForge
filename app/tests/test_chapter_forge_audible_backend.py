"""Chapter Forge's third detection backend: a live Audible chapters lookup
instead of local ASR. Covers ASIN resolution (resolve_asin_for_chaptering)
and the fast worker path (run_audible_chapters_backend) with the network
boundary (audible_lookup_chapters) mocked -- no real Audible calls.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import ChapteringRunRequest, RunState, resolve_asin_for_chaptering, run_audible_chapters_backend

client = TestClient(main_module.app)


class ResolveAsinForChapteringTests(unittest.TestCase):
    def test_override_wins_and_is_uppercased(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            self.assertEqual(resolve_asin_for_chaptering(source, "b017v4im1g"), "B017V4IM1G")

    def test_reads_book_asin_from_sidecar(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            (Path(root) / "libraforge.json").write_text(
                json.dumps({"book": {"asin": "B0TESTBOOK"}}), encoding="utf-8"
            )
            self.assertEqual(resolve_asin_for_chaptering(source, ""), "B0TESTBOOK")

    def test_falls_back_to_marker_audible_asin(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            (Path(root) / "libraforge.json").write_text(
                json.dumps({"book": {}, "marker": {"audible": {"asin": "B0MARKERASIN"}}}),
                encoding="utf-8",
            )
            self.assertEqual(resolve_asin_for_chaptering(source, ""), "B0MARKERASIN")

    def test_no_sidecar_and_no_override_returns_empty(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            self.assertEqual(resolve_asin_for_chaptering(source, ""), "")

    def test_sidecar_present_but_no_asin_anywhere_returns_empty(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "book.mp3"
            source.write_bytes(b"")
            (Path(root) / "libraforge.json").write_text(
                json.dumps({"book": {"title": "Some Book"}}), encoding="utf-8"
            )
            self.assertEqual(resolve_asin_for_chaptering(source, ""), "")


class RunAudibleChaptersBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig_root = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root
        self.run_id = "test-run-1"
        main_module.runs[self.run_id] = RunState(id=self.run_id)

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        main_module.runs.pop(self.run_id, None)
        self.tmp.cleanup()

    def _req(self, source: Path, asin: str = "") -> ChapteringRunRequest:
        return ChapteringRunRequest(source_path=str(source), backend="audible-chapters", asin=asin)

    def test_success_saves_chapters_with_audible_source_tag(self):
        source = self.root / "book.mp3"
        source.write_bytes(b"")
        raw_chapters = [
            {"title": "Chapter One", "start_ms": 0, "length_ms": 60000},
            {"title": "Chapter Two", "start_ms": 60000, "length_ms": 45000},
        ]
        with patch.object(main_module.audible.Authenticator, "from_file", return_value=MagicMock()), \
             patch.object(main_module.audible, "Client", return_value=MagicMock()), \
             patch.object(main_module, "audible_lookup_chapters", return_value=raw_chapters):
            run_audible_chapters_backend(self.run_id, self._req(source, "B0TESTASIN"))

        sidecar = json.loads((self.root / "libraforge.json").read_text(encoding="utf-8"))
        saved = sidecar["chapter_forge"]["chapters"]
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["title"], "Chapter One")
        self.assertEqual(saved[0]["start"], 0.0)
        self.assertEqual(saved[0]["end"], 60.0)
        self.assertEqual(saved[0]["source"], "audible")
        self.assertIsNone(saved[0]["confidence"])
        self.assertEqual(saved[1]["start"], 60.0)
        self.assertEqual(saved[1]["end"], 105.0)
        self.assertEqual(sidecar["chapter_forge"]["backend"], "audible-chapters")
        self.assertEqual(sidecar["chapter_forge"]["asin"], "B0TESTASIN")

    def test_no_asin_available_fails_the_run(self):
        source = self.root / "book.mp3"
        source.write_bytes(b"")
        run_audible_chapters_backend(self.run_id, self._req(source, ""))
        self.assertFalse((self.root / "libraforge.json").exists())

    def test_inaccurate_or_missing_audible_data_fails_the_run(self):
        source = self.root / "book.mp3"
        source.write_bytes(b"")
        with patch.object(main_module.audible.Authenticator, "from_file", return_value=MagicMock()), \
             patch.object(main_module.audible, "Client", return_value=MagicMock()), \
             patch.object(main_module, "audible_lookup_chapters", return_value=None):
            run_audible_chapters_backend(self.run_id, self._req(source, "B0TESTASIN"))
        self.assertFalse((self.root / "libraforge.json").exists())

    def test_asin_auto_resolved_from_sidecar_when_not_overridden(self):
        source = self.root / "book.mp3"
        source.write_bytes(b"")
        (self.root / "libraforge.json").write_text(
            json.dumps({"book": {"asin": "B0FROMSIDECAR"}}), encoding="utf-8"
        )
        lookup = MagicMock(return_value=[{"title": "Ch 1", "start_ms": 0, "length_ms": 1000}])
        with patch.object(main_module.audible.Authenticator, "from_file", return_value=MagicMock()), \
             patch.object(main_module.audible, "Client", return_value=MagicMock()), \
             patch.object(main_module, "audible_lookup_chapters", lookup):
            run_audible_chapters_backend(self.run_id, self._req(source, ""))
        lookup.assert_called_once()
        self.assertEqual(lookup.call_args[0][1], "B0FROMSIDECAR")


class ChapteringLoadReturnsAsinTests(unittest.TestCase):
    def test_load_response_includes_asin_from_sidecar(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "book.mp3").write_bytes(b"")
            (root_path / "libraforge.json").write_text(
                json.dumps({"book": {"asin": "B0LOADTEST"}}), encoding="utf-8"
            )
            with patch.object(main_module, "AUDIOBOOKS_ROOT", root_path):
                response = client.post(
                    "/api/chaptering/load",
                    json={"source_path": str(root_path / "book.mp3")},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["asin"], "B0LOADTEST")


class ChapteringRunsAcceptsAudibleBackendTests(unittest.TestCase):
    def test_audible_chapters_no_longer_rejected_as_unsupported(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "book.mp3").write_bytes(b"")
            with patch.object(main_module, "AUDIOBOOKS_ROOT", root_path), \
                 patch.object(main_module.threading, "Thread") as mock_thread:
                response = client.post(
                    "/api/chaptering/runs",
                    json={
                        "source_path": str(root_path / "book.mp3"),
                        "backend": "audible-chapters",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("id", response.json())
                mock_thread.assert_called_once()


class AudibleCompareEndpointTests(unittest.TestCase):
    """The read-only /api/chaptering/audible-compare endpoint used by the
    "Compare to Audible" panel -- must never save/mutate the sidecar, unlike
    the audible-chapters detection backend."""

    def test_returns_chapters_without_writing_sidecar(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "book.mp3"
            source.write_bytes(b"")
            raw_chapters = [
                {"title": "Ch 1", "start_ms": 0, "length_ms": 60000},
                {"title": "Ch 2", "start_ms": 60000, "length_ms": 30000},
            ]
            with patch.object(main_module, "AUDIOBOOKS_ROOT", root_path), \
                 patch.object(main_module.audible.Authenticator, "from_file", return_value=MagicMock()), \
                 patch.object(main_module.audible, "Client", return_value=MagicMock()), \
                 patch.object(main_module, "audible_lookup_chapters", return_value=raw_chapters):
                response = client.post(
                    "/api/chaptering/audible-compare",
                    json={"source_path": str(source), "asin": "B0COMPARETEST"},
                )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["asin"], "B0COMPARETEST")
            self.assertEqual(len(data["chapters"]), 2)
            self.assertEqual(data["chapters"][0], {"id": 1, "title": "Ch 1", "start": 0.0, "end": 60.0})
            self.assertFalse((root_path / "libraforge.json").exists())

    def test_no_asin_returns_400(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "book.mp3"
            source.write_bytes(b"")
            with patch.object(main_module, "AUDIOBOOKS_ROOT", root_path):
                response = client.post(
                    "/api/chaptering/audible-compare",
                    json={"source_path": str(source)},
                )
            self.assertEqual(response.status_code, 400)

    def test_no_verified_chapter_data_returns_404(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "book.mp3"
            source.write_bytes(b"")
            with patch.object(main_module, "AUDIOBOOKS_ROOT", root_path), \
                 patch.object(main_module.audible.Authenticator, "from_file", return_value=MagicMock()), \
                 patch.object(main_module.audible, "Client", return_value=MagicMock()), \
                 patch.object(main_module, "audible_lookup_chapters", return_value=None):
                response = client.post(
                    "/api/chaptering/audible-compare",
                    json={"source_path": str(source), "asin": "B0NOTFOUND"},
                )
            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
