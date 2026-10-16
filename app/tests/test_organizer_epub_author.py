"""Folder Forge reads an epub's own author when ffprobe and the sidecar give none (#368).

Seen on a real dry run: "The Saga of Tanya the Evil - Volume 09.epub" sat alone in its
folder with no sidecar and was skipped as unknown author, although its OPF names Carlo Zen.
"""
import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_epub_author", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>The Saga of Tanya the Evil, Vol. 9</dc:title>
    <dc:creator>Carlo Zen</dc:creator>
    <dc:creator>Emily Balistrieri</dc:creator>
  </metadata>
</package>"""


def make_epub(path: Path, opf: str = OPF) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)


def ebook_item(path: Path):
    return ORGANIZER.BookItem("loose_file", path, [path], path, media_type="ebook")


class EpubAuthorFallbackTests(unittest.TestCase):
    def tags_for(self, path: Path, ffprobe_tags=None):
        with patch.object(ORGANIZER, "run_ffprobe", return_value=ffprobe_tags or {}):
            return ORGANIZER.metadata_from_tags(ebook_item(path))

    def test_epub_without_tags_takes_its_opf_author_and_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub = Path(temp_dir) / "The Saga of Tanya the Evil - Volume 09 [Yen Press].epub"
            make_epub(epub)
            got = self.tags_for(epub)
            self.assertEqual(got["author"], "Carlo Zen")
            self.assertEqual(got["title"], "The Saga of Tanya the Evil, Vol. 9")

    def test_tags_that_already_name_an_author_win(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub = Path(temp_dir) / "Book.epub"
            make_epub(epub)
            got = self.tags_for(epub, {"artist": "Tagged Author", "title": "Tagged Title"})
            self.assertEqual(got["author"], "Tagged Author")
            self.assertEqual(got["title"], "Tagged Title")

    def test_a_broken_epub_falls_back_to_the_filename_and_unknown_author(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub = Path(temp_dir) / "Broken Book.epub"
            epub.write_bytes(b"not a zip")
            got = self.tags_for(epub)
            self.assertEqual(got["author"], "Unknown Author")
            self.assertEqual(got["title"], "Broken Book")

    def test_a_pdf_is_not_opened_as_an_epub(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = Path(temp_dir) / "Some Book.pdf"
            make_epub(pdf)
            self.assertEqual(self.tags_for(pdf)["author"], "Unknown Author")


if __name__ == "__main__":
    unittest.main()
