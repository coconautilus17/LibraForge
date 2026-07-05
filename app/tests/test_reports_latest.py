import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.main import get_latest_report


def _write_report(reports_dir: Path, name: str, command: list[str]) -> None:
    (reports_dir / f"{name}.report.json").write_text(
        json.dumps({
            "id": name,
            "status": "completed",
            "command": command,
            "stats": {},
            "report_items": [],
        }),
        encoding="utf-8",
    )


class LatestReportTests(unittest.TestCase):
    def test_skips_organizer_reports_for_a_newer_organizer_run(self):
        # command[0] is always the interpreter ("python"/"python3") for both
        # scripts -- the filter must key off the actual script path, not the
        # interpreter, or a newer organizer report always wins.
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            _write_report(
                reports_dir, "20260101-000000-fixer",
                ["python", "-u", "/app/scripts/audible-metadata-fixer-v5.py"],
            )
            _write_report(
                reports_dir, "20260101-000001-organizer",
                ["python3", "-u", "/app/scripts/organize-audiobooks-by-metadata-v3_13.py"],
            )

            with patch("app.main.REPORTS_DIR", reports_dir):
                result = get_latest_report()

        self.assertEqual(result["id"], "20260101-000000-fixer")

    def test_raises_404_when_only_organizer_reports_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            _write_report(
                reports_dir, "20260101-000000-organizer",
                ["python3", "-u", "/app/scripts/organize-audiobooks-by-metadata-v3_13.py"],
            )

            with patch("app.main.REPORTS_DIR", reports_dir):
                with self.assertRaises(HTTPException) as ctx:
                    get_latest_report()

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
