"""The end-of-run report must let a user see, per item, what happened: which
title succeeded and by which decrypt method (voucher vs activation_bytes),
and which failed and why -- not just aggregate downloaded/failed counts.

state.stats["results"] carries this, ordered by original selection order
(not completion order, which is nondeterministic under the 3-way
concurrency added alongside this). See
docs/design/download-voucher-first-decryption.md.
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


class FinalReportResultsTests(unittest.TestCase):
    def _make_request(self, tmp_dir: str) -> LibraryDownloadRequest:
        items = [
            LibraryDownloadItem(asin="B000000000", title="Voucher Book", author="Author"),
            LibraryDownloadItem(asin="B000000001", title="No License Book", author="Author"),
            LibraryDownloadItem(asin="B000000002", title="Activation Bytes Book", author="Author"),
            LibraryDownloadItem(asin="B000000003", title="Corrupt Stream Book", author="Author"),
        ]
        return LibraryDownloadRequest(
            auth_file="/auth/fake.json", target_path=tmp_dir, items=items, organize=False
        )

    def test_results_capture_method_and_outcome_per_item_in_selection_order(self):
        auth_mock = MagicMock()
        auth_mock.get_activation_bytes.return_value = "1a2b3c4d"

        def post_side_effect(path, body=None):
            asin = path.split("/")[1]
            if asin == "B000000001":
                raise Exception(f"License not granted to customer [X] for asin [{asin}]")
            return {
                "content_license": {
                    "drm_type": "Adrm",
                    "content_metadata": {"content_url": {"offline_url": "https://example.invalid/x"}},
                    "license_response": "blob",
                    "asin": asin,
                }
            }

        def voucher_side_effect(auth, lr):
            asin = lr["content_license"]["asin"]
            if asin == "B000000002":
                raise KeyError("license_response")
            return {"key": "k", "iv": "i"}

        def ffmpeg_side_effect(enc_path, out_m4b, log, **kwargs):
            if "Corrupt Stream Book" in str(out_m4b):
                raise RuntimeError("ffmpeg decrypt failed: corrupt stream")

        run_id = str(uuid.uuid4())
        state = RunState(id=run_id)
        runs[run_id] = state
        try:
            with tempfile.TemporaryDirectory() as tmp_dir, \
                 patch("app.main.audible.Authenticator.from_file", return_value=auth_mock), \
                 patch("app.main.audible.Client") as client_cls, \
                 patch("app.main._ffmpeg_decrypt", side_effect=ffmpeg_side_effect), \
                 patch("app.main.write_final_report"), \
                 patch(
                     "audible.aescipher.decrypt_voucher_from_licenserequest",
                     side_effect=voucher_side_effect,
                 ):
                client = client_cls.return_value
                client.post.side_effect = post_side_effect

                @contextmanager
                def fake_raw_request(*_a, **_kw):
                    yield _FakeResponse()

                client.raw_request.side_effect = fake_raw_request
                run_download_worker(run_id, self._make_request(tmp_dir))
        finally:
            if state.log_path is not None:
                Path(state.log_path).unlink(missing_ok=True)
            runs.pop(run_id, None)

        results = state.stats["results"]
        self.assertEqual(len(results), 4)
        # Ordered by original selection order, not completion order.
        self.assertEqual([r["asin"] for r in results], [
            "B000000000", "B000000001", "B000000002", "B000000003",
        ])

        voucher_ok, no_license, ab_ok, corrupt = results

        self.assertEqual(voucher_ok["status"], "success")
        self.assertEqual(voucher_ok["method"], "voucher")
        self.assertIn("path", voucher_ok)

        self.assertEqual(no_license["status"], "failed")
        self.assertIsNone(no_license["method"])  # failed before any method was chosen
        self.assertIn("License not granted", no_license["error"])

        self.assertEqual(ab_ok["status"], "success")
        self.assertEqual(ab_ok["method"], "activation_bytes")

        self.assertEqual(corrupt["status"], "failed")
        self.assertEqual(corrupt["method"], "voucher")  # method was chosen before ffmpeg failed
        self.assertIn("corrupt stream", corrupt["error"])

        self.assertEqual(state.stats["downloaded"], 2)
        self.assertEqual(state.stats["failed"], 2)


if __name__ == "__main__":
    unittest.main()
