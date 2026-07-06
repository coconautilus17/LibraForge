"""Regression test: activation bytes must be fetched once per run, not once per book.

Root cause of the 2026-07-03 "data wrong" failures: run_download_worker called
auth.get_activation_bytes() inside the per-item loop, so a batch of AAX (Adrm)
titles fired that many live requests to Audible's activation endpoint back to
back, tripping CloudFront's abuse protection. Fetching once and reusing avoids
the repeated live calls.
"""

import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.main import LibraryDownloadItem, LibraryDownloadRequest, RunState, run_download_worker, runs


class _FakeResponse:
    def iter_bytes(self, chunk_size: int = 1024 * 1024):
        yield b"fake-encrypted-bytes"


class ActivationBytesCachingTests(unittest.TestCase):
    def _make_request(self, tmp_dir: str, n_items: int) -> LibraryDownloadRequest:
        items = [
            LibraryDownloadItem(asin=f"B0{i:08d}", title=f"Book {i}", author="Author")
            for i in range(n_items)
        ]
        return LibraryDownloadRequest(
            auth_file="/auth/fake.json", target_path=tmp_dir, items=items, organize=False
        )

    def _run(self, req: LibraryDownloadRequest, auth_mock: MagicMock) -> None:
        run_id = str(uuid.uuid4())
        state = RunState(id=run_id)
        runs[run_id] = state
        try:
            with patch("app.main.audible.Authenticator.from_file", return_value=auth_mock), \
                 patch("app.main.audible.Client") as client_cls, \
                 patch("app.main._ffmpeg_decrypt"), \
                 patch("app.main.write_final_report"):
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
                run_download_worker(run_id, req)
        finally:
            # run_download_worker's own finally now pops run_id and writes a
            # report (issue #73 fix) -- write_final_report is mocked above so
            # this test doesn't touch real disk; runs.pop is safe either way.
            if state.log_path is not None:
                Path(state.log_path).unlink(missing_ok=True)
            runs.pop(run_id, None)

    def test_activation_bytes_fetched_once_for_multiple_adrm_items(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        with tempfile.TemporaryDirectory() as tmp_dir:
            req = self._make_request(tmp_dir, n_items=3)
            self._run(req, auth_mock)

        self.assertEqual(auth_mock.get_activation_bytes.call_count, 1)

    def test_activation_bytes_persisted_to_auth_file_after_fetch(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        with tempfile.TemporaryDirectory() as tmp_dir:
            req = self._make_request(tmp_dir, n_items=2)
            self._run(req, auth_mock)

        auth_mock.to_file.assert_called_once()

    def test_activation_bytes_failure_is_cached_and_not_retried(self):
        """A persistent failure (e.g. CloudFront blocking the endpoint) must not be
        retried once per remaining Adrm item -- that's the same hammering the cache
        was meant to prevent, just reached via the failure path instead of success."""
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.side_effect = ValueError("data wrong")

        with tempfile.TemporaryDirectory() as tmp_dir:
            req = self._make_request(tmp_dir, n_items=3)
            self._run(req, auth_mock)

        self.assertEqual(auth_mock.get_activation_bytes.call_count, 1)
        auth_mock.to_file.assert_not_called()

    def test_no_activation_fetch_when_no_adrm_items(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        with tempfile.TemporaryDirectory() as tmp_dir:
            req = self._make_request(tmp_dir, n_items=1)
            run_id = str(uuid.uuid4())
            state = RunState(id=run_id)
            runs[run_id] = state
            try:
                with patch("app.main.audible.Authenticator.from_file", return_value=auth_mock), \
                     patch("app.main.audible.Client") as client_cls, \
                     patch("app.main._ffmpeg_decrypt"), \
                     patch("app.main.write_final_report"), \
                     patch(
                         "audible.aescipher.decrypt_voucher_from_licenserequest",
                         return_value={"key": "k", "iv": "i"},
                     ):
                    client = client_cls.return_value
                    client.post.return_value = {
                        "content_license": {
                            "drm_type": "Mpeg",
                            "content_metadata": {"content_url": {"offline_url": "https://example.invalid/x"}},
                            "license_response": "encrypted",
                            "asin": req.items[0].asin,
                        }
                    }

                    @contextmanager
                    def fake_raw_request(*_a, **_kw):
                        yield _FakeResponse()

                    client.raw_request.side_effect = fake_raw_request
                    run_download_worker(run_id, req)
            finally:
                if state.log_path is not None:
                    Path(state.log_path).unlink(missing_ok=True)
                runs.pop(run_id, None)

        auth_mock.get_activation_bytes.assert_not_called()
        auth_mock.to_file.assert_not_called()


class VoucherFirstDecryptionTests(unittest.TestCase):
    """Live-probed 2026-07-07: Audible can label a title drm_type="Adrm" while
    still returning a usable per-book voucher in the same licenserequest
    response (confirmed for 3/3 titles previously stuck on the blocked
    activation-bytes endpoint). The declared drm_type is not a reliable
    signal for which material is actually available, so the voucher must
    always be tried first, regardless of drm_type -- activation_bytes is
    only a fallback for titles where no voucher truly exists.
    See docs/design/download-voucher-first-decryption.md.
    """

    def _make_request(self, tmp_dir: str, n_items: int = 1) -> LibraryDownloadRequest:
        items = [
            LibraryDownloadItem(asin=f"B0{i:08d}", title=f"Book {i}", author="Author")
            for i in range(n_items)
        ]
        return LibraryDownloadRequest(
            auth_file="/auth/fake.json", target_path=tmp_dir, items=items, organize=False
        )

    def _run(self, req: LibraryDownloadRequest, auth_mock: MagicMock, voucher_side_effect):
        run_id = str(uuid.uuid4())
        state = RunState(id=run_id)
        runs[run_id] = state
        decrypt_calls = []
        try:
            with (
                patch("app.main.audible.Authenticator.from_file", return_value=auth_mock),
                patch("app.main.audible.Client") as client_cls,
                patch("app.main._ffmpeg_decrypt", side_effect=lambda *a, **k: decrypt_calls.append(k)),
                patch("app.main.write_final_report"),
                patch("audible.aescipher.decrypt_voucher_from_licenserequest", side_effect=voucher_side_effect),
            ):
                client = client_cls.return_value
                client.post.return_value = {
                    "content_license": {
                        "drm_type": "Adrm",  # declared Adrm -- must not stop a voucher attempt
                        "content_metadata": {"content_url": {"offline_url": "https://example.invalid/x"}},
                        "license_response": "encrypted-blob",
                        "asin": req.items[0].asin,
                    }
                }

                @contextmanager
                def fake_raw_request(*_a, **_kw):
                    yield _FakeResponse()

                client.raw_request.side_effect = fake_raw_request
                run_download_worker(run_id, req)
        finally:
            if state.log_path is not None:
                Path(state.log_path).unlink(missing_ok=True)
            runs.pop(run_id, None)
        return decrypt_calls

    def test_adrm_labeled_title_with_real_voucher_skips_activation_bytes_entirely(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        with tempfile.TemporaryDirectory() as tmp_dir:
            decrypt_calls = self._run(
                self._make_request(tmp_dir), auth_mock,
                voucher_side_effect=lambda auth, lr: {"key": "thekey", "iv": "theiv"},
            )

        auth_mock.get_activation_bytes.assert_not_called()
        self.assertEqual(len(decrypt_calls), 1)
        self.assertEqual(decrypt_calls[0], {"key": "thekey", "iv": "theiv"})

    def test_adrm_labeled_title_falls_back_when_voucher_genuinely_unavailable(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        with tempfile.TemporaryDirectory() as tmp_dir:
            decrypt_calls = self._run(
                self._make_request(tmp_dir), auth_mock,
                voucher_side_effect=KeyError("license_response"),
            )

        auth_mock.get_activation_bytes.assert_called_once()
        self.assertEqual(decrypt_calls, [{"activation_bytes": "1a2b3c4d"}])

    def test_activation_bytes_still_fetched_only_once_when_voucher_fails_for_every_item(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        with tempfile.TemporaryDirectory() as tmp_dir:
            decrypt_calls = self._run(
                self._make_request(tmp_dir, n_items=3), auth_mock,
                voucher_side_effect=KeyError("license_response"),
            )

        self.assertEqual(auth_mock.get_activation_bytes.call_count, 1)
        self.assertEqual(len(decrypt_calls), 3)


if __name__ == "__main__":
    unittest.main()
