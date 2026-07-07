"""POST /api/manual-review/cover-upload -- stores an uploaded cover image
as a temp file and returns a file:// URL. That URL is used directly as
metadata["cover_url"] by the edit/apply write path -- download_cover_bytes
(scripts/audible-metadata-fixer-v5.py) already fetches arbitrary URLs via
urllib, which handles file:// with no extra code. See
docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
"""
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi.testclient import TestClient

from app.main import app

# Smallest possible valid 1x1 JPEG (magic bytes only matter for sniffing).
_JPEG_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    + "01" * 64
    + "ffd9"
)


class CoverUploadTests(unittest.TestCase):
    def test_upload_returns_file_url_and_file_exists_with_correct_bytes(self):
        client = TestClient(app)
        res = client.post(
            "/api/manual-review/cover-upload",
            files={"file": ("cover.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        self.assertEqual(res.status_code, 200)
        cover_url = res.json()["cover_url"]
        self.assertTrue(cover_url.startswith("file://"))

        stored_path = Path(unquote(urlparse(cover_url).path))
        self.assertTrue(stored_path.is_file())
        self.assertEqual(stored_path.read_bytes(), _JPEG_BYTES)
        self.assertEqual(stored_path.suffix, ".jpg")

    def test_rejects_non_image_upload(self):
        client = TestClient(app)
        res = client.post(
            "/api/manual-review/cover-upload",
            files={"file": ("notes.txt", b"not an image", "text/plain")},
        )
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
