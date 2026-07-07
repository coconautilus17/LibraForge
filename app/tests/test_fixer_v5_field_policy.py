"""field_policy ("legacy"/"fill"/"overwrite") for mutagen_write_mp4_tags and
mutagen_write_mp3_tags.

Bug this covers: Manual Review's apply dialog let a user clear a field
intending "leave this alone," but the writer wrote every field unconditionally
regardless (title/author/narrator/series/sequence/year), while a different 5
fields (genre/subtitle/isbn/asin/publisher) were already "only write if
present." field_policy makes both an explicit, uniform choice across all 11
fields instead of that historical, inconsistent split -- "legacy" (the
default, used by every CLI call site) reproduces the old split byte-for-byte
so the CLI's own tested write-mode system is untouched.
See docs/design/manual-review-apply-rewrite-rules.md.
"""
import importlib.util
import shutil
import subprocess
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


FIXER = load_module("fixer_v5_field_policy", "scripts/audible-metadata-fixer-v5.py")

# The 11 fields Manual Review's edit dialog exposes, mapped to a metadata dict
# key and, for MP4, the primary tag to check back. Genre is handled
# separately (list-valued, see GenreSplitTests).
FULL_METADATA = {
    "title": "New Title",
    "subtitle": "New Subtitle",
    "author": "New Author",
    "narrator": "New Narrator",
    "series": "New Series",
    "sequence": "2",
    "year": "2020",
    "asin": "B0NEWASIN1",
    "isbn": "9789999999999",
    "publisher": "New Publisher",
    "genre": "New Genre",
    "write_summary": True,
    "summary": "New summary.",
}

PRESET_METADATA = {
    "title": "Old Title",
    "subtitle": "Old Subtitle",
    "author": "Old Author",
    "narrator": "Old Narrator",
    "series": "Old Series",
    "sequence": "1",
    "year": "2019",
    "asin": "B0OLDASIN01",
    "isbn": "9781111111111",
    "publisher": "Old Publisher",
    "genre": "Old Genre",
    "write_summary": True,
    "summary": "Old summary.",
}

BLANK_EXCEPT_NARRATOR = {k: "" for k in FULL_METADATA if k not in ("write_summary",)}
BLANK_EXCEPT_NARRATOR["narrator"] = "Kept Narrator"
BLANK_EXCEPT_NARRATOR["write_summary"] = True


def _make_silent_m4a(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "1", "-c:a", "aac", str(path), "-y"],
        check=True,
    )


def _make_silent_mp3(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "1", "-c:a", "libmp3lame", str(path), "-y"],
        check=True,
    )


def _mp4_field_values(path: Path) -> dict:
    from mutagen.mp4 import MP4
    tags = MP4(str(path)).tags or {}
    return {
        "title": (tags.get("\xa9nam") or [""])[0],
        "subtitle": (tags.get("----:com.apple.iTunes:subtitle") or [b""])[0],
        "author": (tags.get("\xa9ART") or [""])[0],
        "narrator": (tags.get("\xa9wrt") or [""])[0],
        "series": (tags.get("\xa9grp") or [""])[0],
        "sequence": str((tags.get("trkn") or [(0, 0)])[0][0]) if tags.get("trkn") else "",
        "year": (tags.get("\xa9day") or [""])[0],
        "asin": (tags.get("----:com.apple.iTunes:asin") or [b""])[0],
        "isbn": (tags.get("----:com.apple.iTunes:isbn") or [b""])[0],
        "publisher": (tags.get("----:com.apple.iTunes:publisher") or [b""])[0],
        "genre": list(tags.get("\xa9gen") or []),
        "summary": (tags.get("\xa9cmt") or [""])[0],
    }


def _mp3_field_values(path: Path) -> dict:
    from mutagen.id3 import ID3

    tags = ID3(str(path))

    def text(frame_id):
        f = tags.get(frame_id)
        return str(f.text[0]) if f and f.text else ""

    def txxx(desc):
        for key, frame in tags.items():
            if key.startswith("TXXX:") and getattr(frame, "desc", "").lower() == desc.lower():
                return str(frame.text[0]) if frame.text else ""
        return ""

    trck = tags.get("TRCK")
    return {
        "title": text("TIT2"),
        "subtitle": text("TIT3"),
        "author": text("TPE1"),
        "narrator": text("TCOM"),
        "series": text("TIT1"),
        "sequence": str(trck.text[0]).split("/")[0] if trck and trck.text else "",
        "year": text("TDRC"),
        "asin": txxx("asin"),
        "isbn": txxx("isbn"),
        "publisher": text("TPUB"),
        "genre": [str(v) for v in (tags.get("TCON").text if tags.get("TCON") else [])],
        "summary": str(tags.get("COMM::eng").text[0]) if tags.get("COMM::eng") else "",
    }


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class Mp4FieldPolicyTests(unittest.TestCase):
    def _write(self, metadata: dict, field_policy: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.m4b"
            _make_silent_m4a(path)
            # Preset every field via the writer itself (legacy, unconditional
            # for all 11 fields since every PRESET_METADATA value is truthy)
            # so all tags, including the freeform ones, start out realistic.
            FIXER.mutagen_write_mp4_tags(path, PRESET_METADATA, backup=False)
            FIXER.mutagen_write_mp4_tags(path, metadata, backup=False, field_policy=field_policy)
            return _mp4_field_values(path)

    def test_legacy_reproduces_historical_split(self):
        # genre/subtitle/isbn/asin/publisher already skip-if-blank; the other
        # 6 always clear if blank -- "legacy" must keep exactly that split.
        values = self._write(BLANK_EXCEPT_NARRATOR, "legacy")
        self.assertEqual(values["title"], "")  # unconditional field: cleared
        self.assertEqual(values["author"], "")
        self.assertEqual(values["series"], "")
        self.assertEqual(values["sequence"], "")
        self.assertEqual(values["year"], "")
        self.assertEqual(values["narrator"], "Kept Narrator")
        # legacy-conditional fields: blank means "leave whatever was there"
        self.assertEqual(values["genre"], ["Old Genre"])
        self.assertEqual(str(values["subtitle"], "utf-8"), "Old Subtitle")
        self.assertEqual(str(values["isbn"], "utf-8"), "9781111111111")
        self.assertEqual(str(values["asin"], "utf-8"), "B0OLDASIN01")
        self.assertEqual(str(values["publisher"], "utf-8"), "Old Publisher")

    def test_fill_leaves_every_blank_field_untouched(self):
        values = self._write(BLANK_EXCEPT_NARRATOR, "fill")
        self.assertEqual(values["title"], "Old Title")
        self.assertEqual(values["author"], "Old Author")
        self.assertEqual(values["series"], "Old Series")
        self.assertEqual(values["sequence"], "1")
        self.assertEqual(values["year"], "2019")
        self.assertEqual(values["narrator"], "Kept Narrator")
        self.assertEqual(values["genre"], ["Old Genre"])
        self.assertEqual(str(values["subtitle"], "utf-8"), "Old Subtitle")

    def test_overwrite_clears_every_blank_field_including_previously_conditional_ones(self):
        values = self._write(BLANK_EXCEPT_NARRATOR, "overwrite")
        self.assertEqual(values["title"], "")
        self.assertEqual(values["author"], "")
        self.assertEqual(values["series"], "")
        self.assertEqual(values["sequence"], "")
        self.assertEqual(values["year"], "")
        self.assertEqual(values["narrator"], "Kept Narrator")
        # Previously these 5 could never be cleared -- now Full Overwrite does.
        self.assertEqual(values["genre"], [])
        self.assertEqual(values["subtitle"], b"")
        self.assertEqual(values["isbn"], b"")
        self.assertEqual(values["asin"], b"")
        self.assertEqual(values["publisher"], b"")

    def test_genre_splits_into_separate_values_not_one_joined_string(self):
        values = self._write({**BLANK_EXCEPT_NARRATOR, "genre": "Fantasy, LitRPG"}, "fill")
        self.assertEqual(values["genre"], ["Fantasy", "LitRPG"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class Mp3FieldPolicyTests(unittest.TestCase):
    def _write(self, metadata: dict, field_policy: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.mp3"
            _make_silent_mp3(path)
            FIXER.mutagen_write_mp3_tags(path, PRESET_METADATA, backup=False)
            FIXER.mutagen_write_mp3_tags(path, metadata, backup=False, field_policy=field_policy)
            return _mp3_field_values(path)

    def test_fill_leaves_every_blank_field_untouched(self):
        values = self._write(BLANK_EXCEPT_NARRATOR, "fill")
        self.assertEqual(values["title"], "Old Title")
        self.assertEqual(values["series"], "Old Series")
        self.assertEqual(values["narrator"], "Kept Narrator")
        self.assertEqual(values["genre"], ["Old Genre"])
        self.assertEqual(values["publisher"], "Old Publisher")

    def test_overwrite_clears_every_blank_field(self):
        values = self._write(BLANK_EXCEPT_NARRATOR, "overwrite")
        self.assertEqual(values["title"], "")
        self.assertEqual(values["series"], "")
        self.assertEqual(values["narrator"], "Kept Narrator")
        self.assertEqual(values["genre"], [])
        self.assertEqual(values["publisher"], "")

    def test_genre_splits_into_separate_values(self):
        values = self._write({**BLANK_EXCEPT_NARRATOR, "genre": "Fantasy, LitRPG"}, "fill")
        self.assertEqual(values["genre"], ["Fantasy", "LitRPG"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg binary not available to build test fixtures")
class M4bToolSidecarAsinFieldPolicyTests(unittest.TestCase):
    """build_m4b_tool_metadata_payload's sidecar.audible.asin is the ONLY place
    a grouped/multi-file book's ASIN is recorded -- Manual Review never writes
    embedded tags for those books (should_write_json_sidecar routes them to
    this JSON sidecar instead). Before field_policy threading, this field had
    an unconditional survivor fallback (`metadata.get("asin") or current`),
    so clearing ASIN via Manual Review's Full Overwrite on a grouped book
    silently did nothing -- the old value always survived. See
    docs/design/manual-review-apply-rewrite-rules.md.
    """

    def _payload(self, asin: str, current_asin: str, field_policy: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.mp3"
            _make_silent_mp3(path)
            metadata = {**FULL_METADATA, "asin": asin}
            clues = {"current": {"asin": current_asin}, "group_search": {}}
            return FIXER.build_m4b_tool_metadata_payload(
                path, metadata, clues, 0.9, field_policy=field_policy
            )

    def test_overwrite_clears_asin_even_when_current_has_one(self):
        payload = self._payload("", "B0OLDASIN01", "overwrite")
        self.assertEqual(payload["audible"]["asin"], "")

    def test_fill_preserves_current_asin_when_blank(self):
        payload = self._payload("", "B0OLDASIN01", "fill")
        self.assertEqual(payload["audible"]["asin"], "B0OLDASIN01")

    def test_legacy_preserves_current_asin_when_blank(self):
        # Default for every CLI call site -- must stay byte-identical to the
        # pre-field_policy unconditional fallback behavior.
        payload = self._payload("", "B0OLDASIN01", "legacy")
        self.assertEqual(payload["audible"]["asin"], "B0OLDASIN01")

    def test_non_blank_asin_always_wins_regardless_of_policy(self):
        for policy in ("legacy", "fill", "overwrite"):
            payload = self._payload("B0NEWASIN1", "B0OLDASIN01", policy)
            self.assertEqual(payload["audible"]["asin"], "B0NEWASIN1")


if __name__ == "__main__":
    unittest.main()
