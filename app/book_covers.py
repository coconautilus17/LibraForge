"""A book file's own cover, and small copies of it for the pages that show covers as
thumbnails.

Reading an embedded cover off a network share takes a few hundred milliseconds and
the image is often half a megabyte or more, for a slot 170 pixels wide. The thumbnail
is made once, kept in the reports folder under the file's path, size and nanosecond
mtime, and served from there until the file changes. The fixer makes them for the
books it searches while the search waits on the network, so the match report opens
with them ready; the web app makes any other the first time it is asked.
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path

THUMB_PIXELS = 320
THUMB_QUALITY = 80
THUMB_MEDIA_TYPE = "image/jpeg"

_dir: Path | None = None


def configure(folder: Path | str | None) -> None:
    """Keep thumbnails in this folder; None turns them off."""
    global _dir
    _dir = Path(folder) if folder else None


def embedded_cover_bytes(audio_file: Path) -> tuple[bytes, str] | None:
    """Return (cover_bytes, media_type) from an audio file's own cover tag (covr/APIC).

    Reads the semantic cover tag via mutagen rather than picking an arbitrary
    embedded picture/video stream by position -- an M4B can carry several
    embedded images (per-chapter thumbnails, stray art), and only the first
    covr/APIC entry is the actual front cover.
    """
    try:
        suffix = audio_file.suffix.lower()
        if suffix in (".m4b", ".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover  # noqa: PLC0415
            tags = MP4(str(audio_file)).tags
            if tags and "covr" in tags and tags["covr"]:
                cover_item = tags["covr"][0]
                fmt = getattr(cover_item, "imageformat", MP4Cover.FORMAT_JPEG)
                media = "image/png" if fmt == MP4Cover.FORMAT_PNG else "image/jpeg"
                return (bytes(cover_item), media)
        elif suffix == ".mp3":
            from mutagen.id3 import ID3  # noqa: PLC0415
            tags = ID3(str(audio_file))
            for key in tags.keys():
                if key.startswith("APIC"):
                    apic = tags[key]
                    mime = getattr(apic, "mime", "image/jpeg")
                    media = "image/png" if "png" in mime else "image/jpeg"
                    return (bytes(apic.data), media)
    except Exception:
        pass
    return None


def make_thumbnail(image: bytes) -> bytes | None:
    """A JPEG at most THUMB_PIXELS on its longer side; None when the image can't be decoded."""
    try:
        from PIL import Image  # noqa: PLC0415
        with Image.open(io.BytesIO(image)) as picture:
            picture.draft("RGB", (THUMB_PIXELS, THUMB_PIXELS))
            small = picture.convert("RGB")
        small.thumbnail((THUMB_PIXELS, THUMB_PIXELS))
        out = io.BytesIO()
        small.save(out, "JPEG", quality=THUMB_QUALITY)
        return out.getvalue()
    except Exception:
        return None


def _path_key(path: Path) -> str:
    return hashlib.sha1(str(path).encode("utf-8", "surrogateescape")).hexdigest()


def signature(path: Path) -> tuple[int, int] | None:
    """(size, nanosecond mtime): taken before a file is read, so what was read is kept
    under the version it came from."""
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _thumb_path(path: Path, sig: tuple[int, int] | None) -> Path | None:
    if _dir is None or sig is None:
        return None
    return _dir / f"{_path_key(path)}-{sig[0]:x}-{sig[1]:x}.jpg"


def cached_thumbnail(path: Path) -> bytes | None:
    """The kept thumbnail of an unchanged file, without opening the file itself."""
    target = _thumb_path(path, signature(path))
    if target is None:
        return None
    try:
        return target.read_bytes()
    except OSError:
        return None


def remember_thumbnail(path: Path, image: bytes, sig: tuple[int, int] | None) -> bytes | None:
    """Make the thumbnail of a cover image read from this file while it had signature
    `sig`, and keep it if the file is still that version, replacing one made for an
    earlier version. Returns it, or None if it couldn't be made."""
    thumb = make_thumbnail(image)
    target = _thumb_path(path, sig)
    if target is None or thumb is None or signature(path) != sig:
        return thumb
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as out:
            out.write(thumb)
        os.replace(temp, target)
        for older in target.parent.glob(f"{_path_key(path)}-*.jpg"):
            if older != target:
                older.unlink(missing_ok=True)
    except OSError:
        pass
    return thumb


def embedded_thumbnail(path: Path) -> bytes | None:
    """The thumbnail of an audio file's own embedded cover: the kept one while the
    file is unchanged, else read and kept now. None when the file has no cover."""
    thumb = cached_thumbnail(path)
    if thumb is not None:
        return thumb
    sig = signature(path)
    cover = embedded_cover_bytes(path)
    return remember_thumbnail(path, cover[0], sig) if cover else None
