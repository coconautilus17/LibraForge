"""write_ebook_sidecar() must write a libraforge.json that read_book_sidecar()
can read straight back, tagged with media_type so a consumer can tell an
ebook record apart from an audiobook one, without touching audio-only
fields (marker/audio_summary/duration) that don't apply to an epub/pdf."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_ebook_sidecar", "scripts/audible-metadata-fixer-v5.py")


class WriteEbookSidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_writes_sidecar_next_to_the_source_file(self):
        source = self._make("Linux/EPUB/kubernetes.epub")
        FIXER.write_ebook_sidecar(
            source,
            source_formats=["epub", "pdf"],
            source_files={"epub": str(source), "pdf": str(source.parent.parent / "PDF" / "kubernetes.pdf")},
            book={"title": "Kubernetes: Up and Running", "subtitle": "", "author": "Kelsey Hightower",
                  "narrator": "", "series": "", "sequence": "", "year": "2022", "summary": "...",
                  "genre": "", "isbn": "", "cover_url": "https://example.com/cover.jpg"},
        )
        sidecar_path = source.with_name(f"{source.name}.libraforge.json")
        self.assertTrue(sidecar_path.is_file())
        payload = json.loads(sidecar_path.read_text())
        self.assertEqual(payload["media_type"], "ebook")
        self.assertEqual(payload["source_formats"], ["epub", "pdf"])
        self.assertEqual(payload["sidecar"]["book"]["title"], "Kubernetes: Up and Running")

    def test_read_book_sidecar_round_trips(self):
        source = self._make("Linux/EPUB/kubernetes.epub")
        FIXER.write_ebook_sidecar(
            source, source_formats=["epub"], source_files={"epub": str(source)},
            book={"title": "Kubernetes: Up and Running", "subtitle": "", "author": "Kelsey Hightower",
                  "narrator": "", "series": "", "sequence": "", "year": "2022", "summary": "",
                  "genre": "", "isbn": "", "cover_url": ""},
        )
        result = FIXER.read_book_sidecar(source)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Kubernetes: Up and Running")
        self.assertEqual(result["author"], "Kelsey Hightower")

    def test_two_unrelated_ebooks_sharing_a_bucket_folder_get_separate_sidecars(self):
        book_a = self._make("Linux/EPUB/kubernetes.epub")
        book_b = self._make("Linux/EPUB/gitpocketguide.epub")
        FIXER.write_ebook_sidecar(
            book_a, source_formats=["epub"], source_files={"epub": str(book_a)},
            book={"title": "Kubernetes: Up and Running", "subtitle": "", "author": "", "narrator": "",
                  "series": "", "sequence": "", "year": "", "summary": "", "genre": "", "isbn": "", "cover_url": ""},
        )
        FIXER.write_ebook_sidecar(
            book_b, source_formats=["epub"], source_files={"epub": str(book_b)},
            book={"title": "Git Pocket Guide", "subtitle": "", "author": "", "narrator": "",
                  "series": "", "sequence": "", "year": "", "summary": "", "genre": "", "isbn": "", "cover_url": ""},
        )
        self.assertEqual(FIXER.read_book_sidecar(book_a)["title"], "Kubernetes: Up and Running")
        self.assertEqual(FIXER.read_book_sidecar(book_b)["title"], "Git Pocket Guide")

    def test_no_marker_or_audio_summary_section_is_written(self):
        source = self._make("Linux/EPUB/kubernetes.epub")
        FIXER.write_ebook_sidecar(
            source, source_formats=["epub"], source_files={"epub": str(source)},
            book={"title": "T", "subtitle": "", "author": "", "narrator": "", "series": "",
                  "sequence": "", "year": "", "summary": "", "genre": "", "isbn": "", "cover_url": ""},
        )
        payload = json.loads(source.with_name(f"{source.name}.libraforge.json").read_text())
        self.assertNotIn("marker", payload)
        self.assertNotIn("audio_summary", payload)


if __name__ == "__main__":
    unittest.main()
