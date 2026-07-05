import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import get_suspect_review


class SuspectReviewProbeTests(unittest.TestCase):
    def test_not_yet_generated_returns_200_exists_false(self):
        # A fresh report probes this on every load to decide the button
        # state; that's the common case, not an error, so it must not be a
        # 404 (which used to log a red entry in the browser console on every
        # single report load).
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.main.REPORTS_DIR", Path(temp_dir)):
                result = get_suspect_review("does-not-exist")

        self.assertEqual(result, {"exists": False})

    def test_generated_review_returns_its_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            (reports_dir / "abc123.report.suspect-review.json").write_text(
                '{"suspects": [{"path": "/book.m4b"}]}', encoding="utf-8",
            )

            with patch("app.main.REPORTS_DIR", reports_dir):
                result = get_suspect_review("abc123")

        self.assertEqual(result, {"suspects": [{"path": "/book.m4b"}]})


if __name__ == "__main__":
    unittest.main()
