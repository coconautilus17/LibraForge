"""Read an epub's own title and author from its OPF metadata."""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def extract_epub_metadata(path: Path) -> tuple[str, str]:
    """Read (title, author) from an epub's embedded OPF metadata.

    An epub is a zip archive; META-INF/container.xml points at the actual
    package (.opf) file, which carries the publisher's own Dublin Core
    <dc:title>/<dc:creator> fields -- not a guess derived from the
    filename. Verified live against real books whose filenames have no
    word separators at all (e.g. "efficientlinuxatthecommandline.epub"):
    the embedded title/author were correct in every case checked.

    Returns ("", "") on any failure (corrupt zip, missing container/opf,
    no dc:title) -- never raises, so a malformed epub just falls back to
    the filename-stem heuristic in the caller.
    """
    dc_ns = "{http://purl.org/dc/elements/1.1/}"
    try:
        with zipfile.ZipFile(path) as zf:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container.find(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            opf_path = rootfile.get("full-path") if rootfile is not None else None
            if not opf_path:
                return "", ""
            opf = ET.fromstring(zf.read(opf_path))
            title_el = opf.find(f".//{dc_ns}title")
            creator_el = opf.find(f".//{dc_ns}creator")
            title = (title_el.text or "").strip() if title_el is not None else ""
            author = (creator_el.text or "").strip() if creator_el is not None else ""
            return title, author
    except (KeyError, zipfile.BadZipFile, ET.ParseError, OSError):
        return "", ""
