"""_extract_epub_metadata: read (title, author) from an epub's embedded
OPF metadata (Dublin Core dc:title/dc:creator), for use as a search query
when the filename stem has no recoverable word boundaries (e.g.
"efficientlinuxatthecommandline.epub"). Verified live against the real
Linux folder before this was written -- every previously-unresolved book's
epub had correct embedded title/author."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.main import _extract_epub_metadata


CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _opf(title: str = "", creator: str = "") -> str:
    title_tag = f"<dc:title>{title}</dc:title>" if title else ""
    creator_tag = f"<dc:creator>{creator}</dc:creator>" if creator else ""
    return f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    {title_tag}
    {creator_tag}
  </metadata>
</package>
"""


class ExtractEpubMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_epub(self, name: str, opf_xml: str | None, container_xml: str | None = CONTAINER_XML) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as zf:
            if container_xml is not None:
                zf.writestr("META-INF/container.xml", container_xml)
            if opf_xml is not None:
                zf.writestr("OEBPS/content.opf", opf_xml)
        return path

    def test_extracts_title_and_author(self):
        path = self._make_epub("book.epub", _opf(title="Kubernetes: Up and Running", creator="Kelsey Hightower"))
        title, author = _extract_epub_metadata(path)
        self.assertEqual(title, "Kubernetes: Up and Running")
        self.assertEqual(author, "Kelsey Hightower")

    def test_title_only_no_creator(self):
        path = self._make_epub("book.epub", _opf(title="Some Book"))
        title, author = _extract_epub_metadata(path)
        self.assertEqual(title, "Some Book")
        self.assertEqual(author, "")

    def test_not_a_zip_file_returns_blank(self):
        path = self.root / "not-a-zip.epub"
        path.write_bytes(b"this is not a zip file")
        title, author = _extract_epub_metadata(path)
        self.assertEqual((title, author), ("", ""))

    def test_missing_container_xml_returns_blank(self):
        path = self._make_epub("book.epub", _opf(title="Some Book"), container_xml=None)
        title, author = _extract_epub_metadata(path)
        self.assertEqual((title, author), ("", ""))

    def test_missing_opf_file_returns_blank(self):
        path = self._make_epub("book.epub", opf_xml=None)
        title, author = _extract_epub_metadata(path)
        self.assertEqual((title, author), ("", ""))

    def test_opf_with_no_title_returns_blank_title(self):
        path = self._make_epub("book.epub", _opf(creator="Someone"))
        title, author = _extract_epub_metadata(path)
        self.assertEqual(title, "")
        self.assertEqual(author, "Someone")

    def test_nonexistent_path_returns_blank(self):
        title, author = _extract_epub_metadata(self.root / "does-not-exist.epub")
        self.assertEqual((title, author), ("", ""))

    def test_malformed_opf_xml_returns_blank(self):
        path = self._make_epub("book.epub", "<this is not valid xml")
        title, author = _extract_epub_metadata(path)
        self.assertEqual((title, author), ("", ""))


if __name__ == "__main__":
    unittest.main()
