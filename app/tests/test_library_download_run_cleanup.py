"""Regression test for issue #73: the download worker's `finally` never wrote a
final report or popped its RunState from `runs`, unlike the other three workers
(run_script_worker, run_m4b_worker, run_organizer_worker). That left every
completed download run permanently resident in the in-memory `runs` dict (a
slow memory leak) and meant `get_run` had no on-disk fallback once a run left
memory (e.g. after a restart).
"""

import tempfile
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.main import LibraryDownloadItem, LibraryDownloadRequest, RunState, run_download_worker, runs


class _FakeResponse:
    def iter_bytes(self, chunk_size: int = 1024 * 1024):
        yield b"fake-encrypted-bytes"


class DownloadWorkerRunCleanupTests(unittest.TestCase):
    def _make_request(self, tmp_dir: str) -> LibraryDownloadRequest:
        items = [LibraryDownloadItem(asin="B000000001", title="Book", author="Author")]
        return LibraryDownloadRequest(
            auth_file="/auth/fake.json", target_path=tmp_dir, items=items, organize=False
        )

    def test_completed_run_is_popped_and_report_written(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        run_id = str(uuid.uuid4())
        runs[run_id] = RunState(id=run_id)

        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch("app.main.audible.Authenticator.from_file", return_value=auth_mock), \
             patch("app.main.audible.Client") as client_cls, \
             patch("app.main._ffmpeg_decrypt"), \
             patch("app.main.write_final_report") as write_report_mock:
            client = client_cls.return_value
            client.post.return_value = {
                "content_license": {
                    "drm_type": "Adrm",
                    "content_metadata": {"content_url": {"offline_url": "https://example.invalid/x"}},
                }
            }

            @contextmanager
            def fake_raw_request(*_a, **_kw):
                yield _FakeResponse()

            client.raw_request.side_effect = fake_raw_request
            run_download_worker(run_id, self._make_request(tmp_dir))

        self.assertNotIn(run_id, runs)
        write_report_mock.assert_called_once()

    def test_errored_run_is_still_popped_and_report_written(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.side_effect = ValueError("data wrong")

        run_id = str(uuid.uuid4())
        runs[run_id] = RunState(id=run_id)

        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch("app.main.audible.Authenticator.from_file", return_value=auth_mock), \
             patch("app.main.audible.Client") as client_cls, \
             patch("app.main._ffmpeg_decrypt"), \
             patch("app.main.write_final_report") as write_report_mock:
            client = client_cls.return_value
            client.post.return_value = {
                "content_license": {
                    "drm_type": "Adrm",
                    "content_metadata": {"content_url": {"offline_url": "https://example.invalid/x"}},
                }
            }

            @contextmanager
            def fake_raw_request(*_a, **_kw):
                yield _FakeResponse()

            client.raw_request.side_effect = fake_raw_request
            run_download_worker(run_id, self._make_request(tmp_dir))

        self.assertNotIn(run_id, runs)
        write_report_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
