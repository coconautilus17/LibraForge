"""Spare room in a file's tag block, so tag edits stay in place.

In most audiobooks the tags sit in front of the audio (an MP4 moov box before
its media, an ID3 tag at the start of an MP3). When new tags no longer fit,
mutagen moves every byte of audio after them: a full rewrite of a file of
hundreds of megabytes. Every tag save in LibraForge passes ``save_padding`` so
that happens at most once per book.
"""

from __future__ import annotations

# Left free whenever a save has to rewrite the file anyway. The largest covers
# seen from any source are about 900 KB, so a later cover or a longer
# description still fits.
REWRITE_PADDING = 1 << 20


def save_padding(info) -> int:
    """mutagen padding callback: keep whatever room the file already has (never
    shrink it, which would itself move the audio); when the tags no longer fit,
    leave REWRITE_PADDING spare so this rewrite is the book's last."""
    if info.padding >= 0:
        return info.padding
    return max(info.get_default_padding(), REWRITE_PADDING)
