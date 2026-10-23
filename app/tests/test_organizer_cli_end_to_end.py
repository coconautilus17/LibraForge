"""Folder Forge run end to end through its command line (dry run and apply) on a
temporary library: what it reports, what it moves and what it refuses to touch."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

ORG = load_script("organizer_cli_e2e", "organize-audiobooks-by-metadata-v3_13.py")


class CliFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.lib = self.base / "lib"
        self.un = self.lib / "_unorganized"
        self.un.mkdir(parents=True)

    def sidecar_book(self, name="Will Wight - Unsouled.m4b", title="Unsouled", author="Will Wight", series="Cradle", sequence="1"):
        audio = self.un / name
        audio.write_bytes(b"audio")
        audio.with_name(audio.name + ".libraforge.json").write_text(json.dumps(
            {"sidecar": {"book": {"title": title, "author": author, "series": series, "sequence": sequence}}}))
        return audio

    def run_cli(self, *args, root=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["organizer", str(root or self.un), "--destination-root", str(self.lib), "--structure-cache", str(self.base / "cache.json"),
                "--progress-every", "0", *args]
        old = sys.argv
        sys.argv = argv
        code = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    ORG.main()
                except SystemExit as exit_:
                    code = exit_.code
        finally:
            sys.argv = old
        return out.getvalue(), err.getvalue(), code


if __name__ == "__main__":
    unittest.main()
