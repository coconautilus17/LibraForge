"""Read an MP4/M4B/M4A file's tags, duration, audio properties and chapter count in-process,
exactly as ffprobe 9.0 reports them, so the shared media inspection can skip launching it.

This is a port of the parts of FFmpeg 9.0's MP4 demuxer (libavformat/mov.c) and stream
timing (libavformat/demux.c, update_stream_timings) that decide those values, limited to
the shapes audiobooks use: one AAC-LC or Opus audio track, optional chapter text tracks, at
most one edit with optional leading empty edits, iTunes metadata and Nero chapters. Any
other shape raises Unsupported and the caller runs ffprobe instead. FFMPEG_RELEASE names
the release whose rules this follows; media_probe uses the reader only with that ffprobe.

Only the ftyp and moov atoms are read, with the kernel's readahead turned off: on a network
share a header read is a few round trips, not megabytes.
"""
from __future__ import annotations

import os
import re
import struct
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FFMPEG_RELEASE = "9.0"
MAX_MOOV_BYTES = 64 * 1024 * 1024
MP4_EPOCH_OFFSET = 2082844800  # seconds from 1904-01-01 to 1970-01-01
UINT32_MAX = 0xFFFFFFFF


class Unsupported(Exception):
    """This file needs ffprobe."""


# mov_read_udta_string's keys (mov.c), and the items it parses its own way.
ITEM_KEYS = {
    b"aART": "album_artist", b"apID": "account_id", b"catg": "category", b"cprt": "copyright",
    b"desc": "description", b"keyw": "keywords", b"ldes": "synopsis", b"manu": "make", b"modl": "model",
    b"purd": "purchase_date", b"soaa": "sort_album_artist", b"soal": "sort_album", b"soar": "sort_artist",
    b"soco": "sort_composer", b"sonm": "sort_name", b"sosn": "sort_show", b"tven": "episode_id",
    b"tvnn": "network", b"tvsh": "show",
    b"\xa9ART": "artist", b"\xa9PRD": "producer", b"\xa9alb": "album", b"\xa9aut": "artist",
    b"\xa9chp": "chapter", b"\xa9cmt": "comment", b"\xa9com": "composer", b"\xa9cpy": "copyright",
    b"\xa9day": "date", b"\xa9dir": "director", b"\xa9dis": "disclaimer", b"\xa9ed1": "edit_date",
    b"\xa9enc": "encoder", b"\xa9fmt": "original_format", b"\xa9gen": "genre", b"\xa9grp": "grouping",
    b"\xa9hst": "host_computer", b"\xa9inf": "comment", b"\xa9lyr": "lyrics", b"\xa9mak": "make",
    b"\xa9mod": "model", b"\xa9nam": "title", b"\xa9ope": "original_artist", b"\xa9prd": "producer",
    b"\xa9prf": "performers", b"\xa9req": "playback_requirements", b"\xa9src": "original_source",
    b"\xa9st3": "subtitle", b"\xa9swr": "encoder", b"\xa9too": "encoder", b"\xa9trk": "track",
    b"\xa9url": "URL", b"\xa9wrn": "warning", b"\xa9wrt": "composer", b"\xa9xyz": "location",
    b"name": "name",
}
INT8_NO_PADDING = {b"akID": "account_type", b"cpil": "compilation", b"egid": "episode_uid",
                   b"hdvd": "hd_video", b"pcst": "podcast", b"pgap": "gapless_playback",
                   b"rtng": "rating", b"stik": "media_type"}
INT8_BYPASS_PADDING = {b"tves": "episode_sort", b"tvsn": "season_number"}
TRACK_OR_DISC = {b"trkn": "track", b"disk": "disc"}
RAW_KEYS = {b"@PRM": "premiere_version", b"@PRQ": "quicktime_version", b"FIRM": "firmware"}
# Atoms FFmpeg's parse table claims, so inside udta/ilst they are not tag strings.
PARSE_TABLE = {
    b"ACLR", b"APRG", b"AALP", b"ARES", b"avss", b"av1C", b"chpl", b"co64", b"colr", b"ctts", b"dinf",
    b"DpxE", b"dref", b"edts", b"elst", b"enda", b"fiel", b"adrm", b"ftyp", b"glbl", b"hdlr", b"ilst",
    b"jp2h", b"mdat", b"mdhd", b"mdia", b"meta", b"minf", b"moof", b"moov", b"mvex", b"mvhd", b"SMI ",
    b"alac", b"avcC", b"pasp", b"sidx", b"stbl", b"stco", b"stps", b"strf", b"stsc", b"stsd", b"stss",
    b"stsz", b"stts", b"stz2", b"sdtp", b"tkhd", b"tfdt", b"tfhd", b"trak", b"traf", b"tref", b"tmcd",
    b"chap", b"trex", b"trun", b"udta", b"wave", b"esds", b"dac3", b"dec3", b"ddts", b"wide", b"wfex",
    b"cmov", b"chan", b"chnl", b"dvc1", b"sgpd", b"sbgp", b"hvcC", b"uuid", b"Cin\x8e", b"free", b"----",
    b"sinf", b"frma", b"senc", b"saiz", b"saio", b"pssh", b"schm", b"schi", b"tenc", b"dfLa", b"st3d",
    b"sv3d", b"dOps", b"dmlp", b"SmDm", b"CoLL", b"vpcC", b"mdcv", b"clli", b"dvcC", b"dvvC", b"dvwC",
    b"kind", b"SA3D", b"SAND", b"iloc", b"pcmC", b"pitm", b"evcC", b"amve", b"apvC", b"clap", b"hfov",
    b"hvcE", b"iacb", b"idat", b"iinf", b"imir", b"iprp", b"iref", b"irot", b"ispe", b"lhvC", b"lvcC",
    b"sbas", b"srat", b"vdep", b"vexu", b"vvcC",
}
# Parse-table atoms whose parser changes nothing this reader reports.
HARMLESS = {b"free", b"wide", b"dinf", b"dref", b"stss", b"stps", b"sdtp", b"sgpd", b"sbgp", b"kind",
            b"chan", b"chnl", b"glbl", b"pasp", b"colr", b"fiel", b"enda"}
# libavformat/id3v1.c ff_id3v1_genre_str, for the iTunes gnre atom.
ID3V1_GENRES = (
    "Blues,Classic Rock,Country,Dance,Disco,Funk,Grunge,Hip-Hop,Jazz,Metal,New Age,Oldies,Other,Pop,R&B,"
    "Rap,Reggae,Rock,Techno,Industrial,Alternative,Ska,Death Metal,Pranks,Soundtrack,Euro-Techno,Ambient,"
    "Trip-Hop,Vocal,Jazz+Funk,Fusion,Trance,Classical,Instrumental,Acid,House,Game,Sound Clip,Gospel,"
    "Noise,AlternRock,Bass,Soul,Punk,Space,Meditative,Instrumental Pop,Instrumental Rock,Ethnic,Gothic,"
    "Darkwave,Techno-Industrial,Electronic,Pop-Folk,Eurodance,Dream,Southern Rock,Comedy,Cult,Gangsta,"
    "Top 40,Christian Rap,Pop/Funk,Jungle,Native American,Cabaret,New Wave,Psychedelic,Rave,Showtunes,"
    "Trailer,Lo-Fi,Tribal,Acid Punk,Acid Jazz,Polka,Retro,Musical,Rock & Roll,Hard Rock,Folk,Folk-Rock,"
    "National Folk,Swing,Fast Fusion,Bebob,Latin,Revival,Celtic,Bluegrass,Avantgarde,Gothic Rock,"
    "Progressive Rock,Psychedelic Rock,Symphonic Rock,Slow Rock,Big Band,Chorus,Easy Listening,Acoustic,"
    "Humour,Speech,Chanson,Opera,Chamber Music,Sonata,Symphony,Booty Bass,Primus,Porn Groove,Satire,"
    "Slow Jam,Club,Tango,Samba,Folklore,Ballad,Power Ballad,Rhythmic Soul,Freestyle,Duet,Punk Rock,"
    "Drum Solo,A capella,Euro-House,Dance Hall,Goa,Drum & Bass,Club-House,Hardcore Techno,Terror,Indie,"
    "BritPop,Negerpunk,Polsk Punk,Beat,Christian Gangsta Rap,Heavy Metal,Black Metal,Crossover,"
    "Contemporary Christian,Christian Rock,Merengue,Salsa,Thrash Metal,Anime,JPop,Synthpop,Abstract,"
    "Art Rock,Baroque,Bhangra,Big Beat,Breakbeat,Chillout,Downtempo,Dub,EBM,Eclectic,Electro,"
    "Electroclash,Emo,Experimental,Garage,Global,IDM,Illbient,Industro-Goth,Jam Band,Krautrock,Leftfield,"
    "Lounge,Math Rock,New Romantic,Nu-Breakz,Post-Punk,Post-Rock,Psytrance,Shoegaze,Space Rock,Trop Rock,"
    "World Music,Neoclassical,Audiobook,Audio Theatre,Neue Deutsche Welle,Podcast,Indie Rock,G-Funk,"
    "Dubstep,Garage Rock,Psybient"
).split(",")
AUDIO_CODECS = {
    "aac": ("AAC (Advanced Audio Coding)", "LC"),
    "opus": ("Opus (Opus Interactive Audio Codec)", ""),
}


class _Stream:
    def __init__(self, index: int) -> None:
        self.index = index
        self.id = -1
        self.kind = "data"  # hdlr: audio, video, subtitle; data otherwise
        self.metadata: dict[str, str] = {}
        self.time_scale = 0
        self.duration = 0
        self.stts: list[tuple[int, int]] = []
        self.stsz: tuple[int, int, int] | None = None  # (fixed size, count, table start)
        self.stsc: list[tuple[int, int]] = []
        self.chunk_count = 0
        self.elst: list[tuple[int, int, float]] = []
        self.codec = ""
        self.channels = 0
        self.sample_rate = 0
        self.esds_bit_rate = 0
        self.start_pad = 0


class _Movie:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.tags: dict[str, str] = {}
        self.streams: list[_Stream] = []
        self.isom = False
        self.time_scale = 0
        self.itunes = False
        self.trak_index = -1
        self.found_hdlr_mdta = False
        self.chapter_tracks: list[int] = []
        self.chpl_count = 0

    def set(self, key: str, value: str, target: dict[str, str] | None = None) -> None:
        """av_dict_set: keys match case-insensitively and the last value wins."""
        tags = self.tags if target is None else target
        for existing in [k for k in tags if k.lower() == key.lower()]:
            del tags[existing]
        tags[key] = value

    def append(self, key: str, value: str, target: dict[str, str]) -> None:
        """av_dict_set with AV_DICT_APPEND, preceded by a ";" when the key is there already
        (mov_read_udta_string inside ilst): repeated items join instead of replacing."""
        old = next((v for k, v in target.items() if k.lower() == key.lower()), None)
        self.set(key, value if old is None else f"{old};{value}", target)


def _c_string(raw: bytes) -> str:
    raw = raw.split(b"\x00", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Unsupported("text that is not UTF-8") from exc


def _mac_string(raw: bytes) -> str:
    """mov_read_mac_string for ASCII text; FFmpeg's Mac Roman table is not reproduced."""
    raw = raw.split(b"\x00", 1)[0]
    if any(b >= 0x80 for b in raw):
        raise Unsupported("Mac Roman text")
    return raw.decode("ascii")


def _timestamp(seconds: int) -> str:
    """avpriv_dict_set_timestamp's "%Y-%m-%dT%H:%M:%S.%06dZ"."""
    try:
        when = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    except OverflowError as exc:
        raise Unsupported("creation time out of range") from exc
    return when.strftime("%Y-%m-%dT%H:%M:%S") + ".000000Z"


def _creation_time(movie: "_Movie", pos: int, version: int, target: dict[str, str]) -> int:
    """mov_metadata_creation_time; returns the position after creation and modification times."""
    data = movie.data
    if version == 1:
        created = struct.unpack(">q", data[pos:pos + 8])[0]
        pos += 16
        if created < 0:
            return pos
    else:
        created = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 8
        if 0 < created < MP4_EPOCH_OFFSET:
            created += MP4_EPOCH_OFFSET
    if created:
        movie.set("creation_time", _timestamp(created - MP4_EPOCH_OFFSET), target)
    return pos


def _language(code: int) -> str | None:
    """ff_mov_lang_to_iso639; only the old Macintosh code 0 (English) of its table."""
    if code >= 0x400 and code != 0x7FFF:
        return "".join(chr(0x60 + ((code >> shift) & 0x1F)) for shift in (10, 5, 0))
    if code == 0:
        return "eng"
    if code < 0x400:
        raise Unsupported("Macintosh language code")
    return None


def _rescale(a: int, b: int, c: int) -> int:
    """av_rescale with AV_ROUND_NEAR_INF, for a >= 0."""
    if c <= 0:
        raise Unsupported("bad timescale")
    if a < 0:
        raise Unsupported("negative time")
    return (a * b + c // 2) // c


def _atoms(data: bytes, start: int, end: int):
    """mov_read_default's walk: (type, payload start, payload end)."""
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1 and pos + 16 <= end:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield kind, pos + header, min(pos + size, end)
        pos += size


def _walk(movie: _Movie, start: int, end: int, parent: bytes, depth: int = 0) -> None:
    if depth > 10:
        raise Unsupported("atoms nested too deeply")
    for kind, s, e in _atoms(movie.data, start, end):
        if parent not in (b"root", b"moov") and kind in (b"trak", b"mdat"):
            raise Unsupported("trak or mdat below the top level")
        if kind in PARSE_TABLE:
            _parse(movie, kind, s, e, depth)
        elif parent in (b"udta", b"ilst"):
            _udta_string(movie, kind, s, e)
        elif parent == b"meta" and kind == b"keys" and movie.found_hdlr_mdta:
            raise Unsupported("QuickTime metadata keys")
        # any other leaf is skipped, as mov_read_default does


def _parse(movie: _Movie, kind: bytes, s: int, e: int, depth: int) -> None:
    data = movie.data
    st = movie.streams[-1] if movie.streams else None
    if kind in (b"mdia", b"minf", b"stbl", b"edts", b"udta", b"tref", b"dinf"):
        _walk(movie, s, e, kind, depth + 1)
    elif kind == b"trak":
        movie.streams.append(_Stream(len(movie.streams)))
        movie.trak_index = len(movie.streams) - 1
        _walk(movie, s, e, kind, depth + 1)
        movie.trak_index = -1
    elif kind == b"ilst":
        movie.itunes = True
        _walk(movie, s, e, kind, depth + 1)
        movie.itunes = False
    elif kind == b"meta":
        # mov_read_meta looks for its hdlr four bytes at a time, then reads on from there.
        pos = s
        while e - pos > 8:
            if data[pos:pos + 4] == b"hdlr":
                _walk(movie, pos - 4, e, kind, depth + 1)
                return
            pos += 4
    elif kind == b"mvhd":
        pos = _creation_time(movie, s + 4, data[s], movie.tags)
        movie.time_scale = struct.unpack(">i", data[pos:pos + 4])[0]
        if movie.time_scale <= 0:
            movie.time_scale = 1
    elif st is None:
        if kind in (b"hdlr",) and movie.trak_index < 0:
            _hdlr(movie, None, s, e)
        elif kind == b"chpl":
            _chpl(movie, s, e)
        elif kind == b"----":
            return  # mov_read_custom needs a stream
        elif kind not in HARMLESS and kind not in (b"esds", b"dOps", b"chap"):
            raise Unsupported(f"atom {kind!r} before any track")
    elif kind == b"tkhd":
        version = data[s]
        st.id = struct.unpack(">I", data[s + (20 if version == 1 else 12):][:4])[0]
    elif kind == b"mdhd":
        version = data[s]
        if version > 1:
            raise Unsupported("mdhd version")
        pos = _creation_time(movie, s + 4, version, st.metadata)
        st.time_scale = struct.unpack(">i", data[pos:pos + 4])[0]
        if version == 1:
            st.duration = struct.unpack(">Q", data[pos + 4:pos + 12])[0]
            pos += 12
            if st.duration == 0xFFFFFFFFFFFFFFFF:
                st.duration = 0
        else:
            st.duration = struct.unpack(">I", data[pos + 4:pos + 8])[0]
            pos += 8
            if st.duration == UINT32_MAX:
                st.duration = 0
        language = _language(struct.unpack(">H", data[pos:pos + 2])[0])
        if language:
            movie.set("language", language, st.metadata)
    elif kind == b"hdlr":
        _hdlr(movie, st if movie.trak_index >= 0 else None, s, e)
    elif kind == b"stsd":
        _stsd(movie, st, s, e)
    elif kind in (b"stts", b"stsz", b"stsc", b"stco", b"co64") and movie.trak_index < 0:
        return  # "outside TRAK": ignored
    elif kind == b"stts":
        count = struct.unpack(">I", data[s + 4:s + 8])[0]
        if s + 8 + 8 * count > e:
            raise Unsupported("short stts")
        entries = struct.unpack(f">{2 * count}I", data[s + 8:s + 8 + 8 * count])
        st.stts = list(zip(entries[0::2], entries[1::2]))
    elif kind == b"stsz":
        fixed, count = struct.unpack(">II", data[s + 4:s + 12])
        if not fixed and s + 12 + 4 * count > e:
            raise Unsupported("short stsz")
        st.stsz = (fixed, count, s + 12)
    elif kind == b"stsc":
        count = struct.unpack(">I", data[s + 4:s + 8])[0]
        if s + 8 + 12 * count > e:
            raise Unsupported("short stsc")
        rows = struct.unpack(f">{3 * count}I", data[s + 8:s + 8 + 12 * count])
        st.stsc = list(zip(rows[0::3], rows[1::3]))
    elif kind in (b"stco", b"co64"):
        st.chunk_count = struct.unpack(">I", data[s + 4:s + 8])[0]
    elif kind == b"elst":
        _elst(movie, st, s, e)
    elif kind == b"chap":
        movie.chapter_tracks = [struct.unpack(">I", data[p:p + 4])[0] for p in range(s, e - 3, 4)]
    elif kind == b"chpl":
        _chpl(movie, s, e)
    elif kind == b"----":
        _custom(movie, s, e)
    elif kind in HARMLESS or kind in (b"esds", b"dOps"):
        return  # nothing reported, or read with its sample description
    else:
        raise Unsupported(f"atom {kind!r}")


def _hdlr(movie: _Movie, st: _Stream | None, s: int, e: int) -> None:
    data = movie.data
    subtype = data[s + 8:s + 12]
    if st is None:
        if subtype == b"mdta":
            movie.found_hdlr_mdta = True
        return
    if subtype == b"vide":
        st.kind = "video"
    elif subtype == b"soun":
        st.kind = "audio"
    elif subtype in (b"subp", b"clcp"):
        st.kind = "subtitle"
    elif subtype == b"m1a ":
        raise Unsupported("MPEG audio track")
    title = data[s + 24:e]
    if title and title[0]:
        off = 1 if (not movie.isom and title[0] == len(title) - 1) else 0
        name = _c_string(title[off:])
        if "handler_name" not in st.metadata:  # AV_DICT_DONT_OVERWRITE
            st.metadata["handler_name"] = name


def _elst(movie: _Movie, st: _Stream, s: int, e: int) -> None:
    data = movie.data
    version = data[s]
    count = struct.unpack(">I", data[s + 4:s + 8])[0]
    size = 20 if version == 1 else 12
    if (e - s - 8) != count * size:
        raise Unsupported("elst size")
    entries = []
    for i in range(count):
        p = s + 8 + i * size
        if version == 1:
            duration, time = struct.unpack(">Qq", data[p:p + 16])
            rate = struct.unpack(">I", data[p + 16:p + 20])[0] / 65536.0
        else:
            duration, time, rate_raw = struct.unpack(">IiI", data[p:p + 12])
            rate = rate_raw / 65536.0
        if duration >= 1 << 63:
            raise Unsupported("negative edit duration")  # mov_read_elst refuses the file
        entries.append((duration, time, rate))
    if entries:
        st.elst = entries


def _chpl(movie: _Movie, s: int, e: int) -> None:
    """mov_read_chpl: the count of Nero chapters it adds (ids 0..n-1)."""
    data = movie.data
    size = e - s - 5
    if size < 0:
        return
    version = data[s]
    pos = s + 4 + (4 if version else 0)
    count = data[pos]
    pos += 1
    added = 0
    for _ in range(count):
        if size < 9:
            break
        str_len = data[pos + 8]
        size -= 9 + str_len
        if size < 0:
            break
        pos += 9 + str_len
        added += 1
    movie.chpl_count = max(movie.chpl_count, added)


def _stsd(movie: _Movie, st: _Stream, s: int, e: int) -> None:
    data = movie.data
    count = struct.unpack(">I", data[s + 4:s + 8])[0]
    entries = list(_atoms(data, s + 8, e))
    if st.kind != "audio":
        if st.kind == "video":
            raise Unsupported("video track")
        return  # a chapter text track: nothing it describes is reported
    if count != 1 or len(entries) != 1:
        raise Unsupported("not exactly one sample description")
    kind, es, ee = entries[0]
    if kind not in (b"mp4a", b"Opus"):
        raise Unsupported(f"sample description {kind!r}")
    version = struct.unpack(">H", data[es + 8:es + 10])[0]
    if version != 0 or not movie.isom or "qt  " in movie.tags.get("compatible_brands", ""):
        raise Unsupported("QuickTime sound description")
    # vendor_id is reported only for QuickTime files, which go to ffprobe above.
    st.channels = struct.unpack(">H", data[es + 16:es + 18])[0]
    st.sample_rate = struct.unpack(">I", data[es + 24:es + 28])[0] >> 16
    children = list(_atoms(data, es + 28, ee))
    for child, _, _ in children:
        if child not in (b"esds", b"dOps", b"btrt"):
            raise Unsupported(f"sample entry child {child!r}")
    if kind == b"mp4a":
        esds = next(((cs, ce) for c, cs, ce in children if c == b"esds"), None)
        if not esds:
            raise Unsupported("mp4a without esds")
        st.codec = "aac"
        st.esds_bit_rate, st.sample_rate, st.channels = _esds_aac(data, *esds)
    else:
        dops = next(((cs, ce) for c, cs, ce in children if c == b"dOps"), None)
        if not dops or dops[1] - dops[0] < 11 or data[dops[0]] != 0:
            raise Unsupported("Opus without a usable dOps")
        channels = data[dops[0] + 1]
        family = data[dops[0] + 10]
        if family != 0 or not 1 <= channels <= 2:
            raise Unsupported("Opus channel mapping")
        st.codec = "opus"
        st.channels = channels
        st.sample_rate = 48000  # the Opus decoder always reports 48 kHz


def _esds_aac(data: bytes, start: int, end: int) -> tuple[int, int, int]:
    """(average bitrate, sample rate, channels) from an AAC-LC elementary stream descriptor."""
    def descriptor(p: int) -> tuple[int, int, int]:
        tag = data[p]
        p += 1
        length = 0
        for _ in range(4):
            b = data[p]
            p += 1
            length = (length << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        return tag, p, p + length

    tag, p, _ = descriptor(start + 4)
    if tag != 0x03:
        raise Unsupported("esds without ES descriptor")
    flags = data[p + 2]
    p += 3
    if flags & 0x80:
        p += 2
    if flags & 0x40:
        p += 1 + data[p]
    if flags & 0x20:
        p += 2
    tag, p, _ = descriptor(p)
    if tag != 0x04 or data[p] != 0x40:
        raise Unsupported("not MPEG-4 audio")
    avg_bit_rate = struct.unpack(">I", data[p + 9:p + 13])[0]
    tag, p, q = descriptor(p + 13)
    if tag != 0x05 or q - p < 2 or q > end:
        raise Unsupported("no AudioSpecificConfig")
    bits = int.from_bytes(data[p:q], "big")
    total = (q - p) * 8
    used = 0

    def take(n: int) -> int:
        nonlocal used
        if used + n > total:
            raise Unsupported("short AudioSpecificConfig")
        used += n
        return (bits >> (total - used)) & ((1 << n) - 1)

    object_type = take(5)
    freq_index = take(4)
    if object_type != 2 or freq_index == 0xF:
        raise Unsupported(f"AAC object type {object_type}")
    channel_config = take(4)
    rates = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350]
    if freq_index >= len(rates) or not 1 <= channel_config <= 2:
        raise Unsupported("unusual AAC configuration")
    _frame_length, core_coder, extension = take(1), take(1), take(1)
    if core_coder or extension:
        raise Unsupported("unusual GASpecificConfig")
    # Backward-compatible signalling: an SBR extension that is switched on means HE-AAC,
    # whose decoded rate and layout ffprobe reports instead of these.
    if total - used >= 16 and take(11) == 0x2B7:
        if take(5) == 5 and take(1):
            raise Unsupported("HE-AAC signalled")
    return (avg_bit_rate if avg_bit_rate < 0x80000000 else 0), rates[freq_index], channel_config


def _udta_string(movie: _Movie, kind: bytes, s: int, e: int) -> None:
    """mov_read_udta_string. Text goes to the track it sits in, or to the file; inside ilst
    every data atom of an item is read, and repeated keys join with ";". The integer and
    genre items always go to the file, last one winning."""
    data = movie.data
    key = (ITEM_KEYS.get(kind) or INT8_NO_PADDING.get(kind) or INT8_BYPASS_PADDING.get(kind)
           or TRACK_OR_DISC.get(kind) or ("genre" if kind == b"gnre" else None))
    raw = kind in RAW_KEYS
    if raw:
        key = RAW_KEYS[kind]
    if kind in (b"HMMT", b"loci"):
        raise Unsupported(f"user data {kind!r}")
    target = movie.streams[movie.trak_index].metadata if movie.trak_index >= 0 else movie.tags
    pos, size = s, e - s
    while True:
        data_type = 0
        langcode = 0
        language = ""
        if movie.itunes and size > 8:
            data_size, tag = struct.unpack(">I4s", data[pos:pos + 8])
            if not (tag == b"data" and 16 <= data_size <= size):
                return
            data_type = struct.unpack(">I", data[pos + 8:pos + 12])[0]
            pos += 16
            size -= 16
            str_size = data_size - 16
            if kind == b"covr":
                return
        elif size > 4 and key and not movie.itunes and not raw:
            str_size, langcode = struct.unpack(">HH", data[pos:pos + 4])
            if str_size > size:
                raise Unsupported("QuickTime user-data string retried raw")
            language = _language(langcode) or ""
            pos += 4
            size -= 4
        else:
            str_size = size
        if not key:
            return
        payload = data[pos:pos + str_size]
        if kind in TRACK_OR_DISC:
            if len(payload) < 4:
                raise Unsupported("short track number")
            current = struct.unpack(">h", payload[2:4])[0]
            total = struct.unpack(">h", payload[4:6])[0] if str_size >= 6 else 0
            movie.set(key, f"{current}/{total}" if total else f"{current}")
            return
        if kind in INT8_NO_PADDING:
            if not payload:
                raise Unsupported("empty integer item")
            movie.set(key, str(payload[0]))
            return
        if kind in INT8_BYPASS_PADDING:
            if len(payload) < 4:
                raise Unsupported("short integer item")
            movie.set(key, str(payload[3]))
            return
        if kind == b"gnre":
            if len(payload) < 2:
                raise Unsupported("short gnre")
            genre = payload[1]
            if 1 <= genre <= len(ID3V1_GENRES):
                movie.set(key, ID3V1_GENRES[genre - 1])
            return
        if not raw and (data_type == 3 or (data_type == 0 and (langcode < 0x400 or langcode == 0x7FFF))):
            value = _mac_string(payload)
        elif data_type == 21:
            value = str(int.from_bytes(payload, "big", signed=True)) if len(payload) in (1, 2, 3, 4) else "0"
        elif data_type == 22:
            value = str(int.from_bytes(payload, "big")) if len(payload) in (1, 2, 3, 4) else "0"
        elif data_type == 23 and str_size >= 4:
            value = "%f" % struct.unpack(">f", payload[:4])[0]
        elif data_type > 1 and data_type != 4:
            return
        else:
            value = _c_string(payload)
        if movie.itunes:
            movie.append(key, value, target)
        else:
            movie.set(key, value, target)
        if language and language != "und":
            movie.set(f"{key}-{language}", value, target)
        pos += str_size
        size -= str_size
        if not (movie.itunes and size > 8):
            return


def _custom(movie: _Movie, s: int, e: int) -> None:
    """mov_read_custom: a '----' item named by its mean and name children."""
    data = movie.data
    parts: dict[bytes, bytes] = {}
    pos = s
    for _ in range(3):
        if e - pos <= 12:
            break
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        pos += 12
        if length < 12 or length - 12 > e - pos:
            break
        length -= 12
        if tag == b"data" and length > 4:
            pos += 4
            length -= 4
        elif tag not in (b"mean", b"name"):
            break
        if tag in parts:
            break
        parts[tag] = data[pos:pos + length]
        pos += length
    if not {b"mean", b"name", b"data"} <= set(parts):
        return
    key = _c_string(parts[b"name"])
    value = _c_string(parts[b"data"])
    st = movie.streams[-1]
    if key == "iTunSMPB":
        m = re.match(r"\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)", value)
        if m:
            priming = int(m.group(1), 16)
            if 0 < priming < 16384 and st.kind == "audio":
                # initial_padding: the priming in samples of the decoded rate
                if not st.time_scale or not st.sample_rate:
                    raise Unsupported("iTunSMPB before the track's timing")
                st.start_pad = _rescale(priming, st.sample_rate, st.time_scale)
    if _c_string(parts[b"mean"]) == "com.apple.iTunes" and key == "DISCSUBTITLE":
        movie.set("disc_subtitle", value)
        movie.tags = {k: v for k, v in movie.tags.items() if k.lower() != key.lower()}
        return  # the value moved to disc_subtitle, so the key itself is removed
    if key != "cdec":
        movie.set(key, value)


def _sample_bytes(movie: _Movie, st: _Stream) -> int:
    fixed, count, table = st.stsz
    if fixed:
        return fixed * count
    sizes = array("I")
    if sizes.itemsize != 4:
        raise Unsupported("platform")
    sizes.frombytes(movie.data[table:table + 4 * count])
    sizes.byteswap()
    return sum(sizes)


def _settle(movie: _Movie, st: _Stream, light: bool = False) -> tuple[int | None, int, int]:
    """mov_read_trak's end (stts, mov_build_index, mov_fix_index): (start time, duration,
    bit rate) in the stream's own time base; start time None when FFmpeg leaves it unset.
    A light read has no sample sizes, so its bit rate is 0."""
    if st.time_scale <= 0:
        st.time_scale = movie.time_scale if movie.time_scale > 0 else 1
    if not st.stts:
        raise Unsupported("no stts (fragmented)")
    if st.stsz is None or not st.chunk_count or not st.stsc:
        raise Unsupported("incomplete sample tables")
    duration = st.duration
    stts_total = 0
    for count, delta in st.stts:
        if delta >= 0x80000000:
            raise Unsupported("stts correction")
        stts_total += count * delta
    if stts_total:
        duration = min(duration, stts_total)
    if st.kind == "audio" and len(st.stts) == 1 and st.stts[0][1] == 1:
        raise Unsupported("uncompressed audio chunking")
    # Every sample the chunks hold must be one stsz describes.
    covered = 0
    for i, (first, per_chunk) in enumerate(st.stsc):
        last = st.stsc[i + 1][0] if i + 1 < len(st.stsc) else st.chunk_count + 1
        if first < 1 or last < first:
            raise Unsupported("stsc order")
        covered += (last - first) * per_chunk
    if covered != st.stsz[1] or sum(c for c, _ in st.stts) != st.stsz[1]:
        raise Unsupported("sample tables disagree")
    bit_rate = 0
    if duration > 0 and st.kind == "audio" and not light:
        bit_rate = _sample_bytes(movie, st) * 8 * st.time_scale // duration
    start_time = None
    if st.elst and st.stsz[1]:
        empty = 0
        end = 0
        seen_media = False
        for edit_duration, media_time, rate in st.elst:
            scaled = _rescale(edit_duration, st.time_scale, movie.time_scale)
            end += scaled
            if media_time == -1 and not seen_media:
                empty += scaled
                continue
            if seen_media or media_time < 0 or rate != 1.0 or edit_duration == 0:
                raise Unsupported("edit list shape")
            seen_media = True
        if not seen_media:
            raise Unsupported("only empty edits")
        start_time = empty
        duration = min(duration, end)
    return start_time, duration, bit_rate


def _chapter_entries(movie: _Movie, track: _Stream) -> int:
    """How many index entries a chapter track's samples make (mov_build_index, then
    mov_fix_index for an edit list), each one a chapter mov_read_chapters adds."""
    sample_dts, dts = [], 0
    for count, delta in track.stts:
        for _ in range(count):
            sample_dts.append(dts)
            dts += delta
    if not track.elst:
        return len(set(sample_dts))
    empty = 0
    edits = []
    for edit_duration, media_time, rate in track.elst:
        scaled = _rescale(edit_duration, track.time_scale, movie.time_scale)
        if media_time == -1 and not edits:
            empty += scaled
        else:
            edits.append((scaled, media_time, rate))
    if len(edits) != 1 or edits[0][1] != 0 or edits[0][2] != 1.0:
        raise Unsupported("chapter track edit list shape")
    edit_duration = edits[0][0]
    added, counter = set(), empty
    for i, cts in enumerate(sample_dts):
        frame_duration = sample_dts[i + 1] - cts if i + 1 < len(sample_dts) else edit_duration
        added.add(counter)  # an entry at a time already indexed replaces it
        counter += frame_duration
        if cts + frame_duration >= edit_duration:
            break  # the first (key) sample reaching the edit's end is the last one kept
    return len(added)


def _format_duration(streams: list[tuple[_Stream, int | None, int]]) -> int | None:
    """update_stream_timings: the format duration in microseconds."""
    int64_min, int64_max = -(2**63), 2**63 - 1
    start = start_text = int64_max
    end = end_text = int64_min
    duration = duration_text = int64_min
    for st, start_time, st_duration in streams:
        is_text = st.kind in ("data", "subtitle")
        if start_time is not None:
            start1 = _rescale(start_time, 1_000_000, st.time_scale)
            end1 = _rescale(st_duration, 1_000_000, st.time_scale) + start1
            if is_text:
                start_text = min(start_text, start1)
                end_text = max(end_text, end1)
            else:
                start = min(start, start1)
                end = max(end, end1)
        duration1 = _rescale(st_duration, 1_000_000, st.time_scale)
        if is_text:
            duration_text = max(duration_text, duration1)
        else:
            duration = max(duration, duration1)
    if start == int64_max or (start > start_text and start - start_text < 1_000_000):
        start = start_text
    if end == int64_min or (end < end_text and end_text - end < 1_000_000):
        end = end_text
    if duration == int64_min or (duration < duration_text and duration_text - duration < 1_000_000):
        duration = duration_text
    if start != int64_max and end != int64_min and end >= start:
        duration = max(duration, end - start)
    return duration if duration != int64_min and duration > 0 else None


def parse(ftyp: bytes, moov: bytes, file_size: int, light: bool = False) -> dict[str, Any]:
    """The facts ffprobe would report for a file with these ftyp and moov atoms (light:
    moov without its sample-table bodies, and no stream bit rate)."""
    movie = _Movie(moov)
    if len(ftyp) < 8:
        raise Unsupported("no ftyp")
    major = ftyp[:4]
    if major != b"qt  ":
        movie.isom = True
    if major == b"aaxc":
        raise Unsupported("Audible aaxc")
    movie.set("major_brand", _c_string(major))
    movie.set("minor_version", str(struct.unpack(">I", ftyp[4:8])[0]))
    movie.set("compatible_brands", _c_string(ftyp[8:]))
    _walk(movie, 0, len(moov), b"moov")

    audio = [st for st in movie.streams if st.kind == "audio"]
    if not audio or not audio[0].codec:
        raise Unsupported("no supported audio track")
    if len(audio) > 1:
        raise Unsupported("more than one audio track")
    if any(st.kind == "video" for st in movie.streams):
        raise Unsupported("video track")
    first = audio[0]
    settled = []
    stream_bit_rate = 0
    for st in movie.streams:
        start_time, duration, bit_rate = _settle(movie, st, light)
        if st is first:
            stream_bit_rate = bit_rate or first.esds_bit_rate
            if start_time is None:
                # update_initial_timestamps: the first packet's time plus the samples it skips.
                start_time = _rescale(st.start_pad, st.time_scale, st.sample_rate) if st.start_pad else 0
        settled.append((st, start_time, duration))
    us = _format_duration(settled)
    seconds = float("%f" % (us * (1 / 1000000))) if us else None

    # Nero chapters and a chapter track's samples share chapter ids, so the larger count
    # stands. A track's samples become index entries one per timestamp (ff_add_index_entry
    # replaces an entry at the same time), so a zero-length sample merges with the next.
    chapter_count = movie.chpl_count
    for track_id in movie.chapter_tracks:
        track = next((st for st in movie.streams if st.id == track_id), None)
        if track is None or not track.stsz:
            continue
        chapter_count = max(chapter_count, _chapter_entries(movie, track))

    long_name, profile = AUDIO_CODECS[first.codec]
    stream = {"codec_name": first.codec, "codec_long_name": long_name, "channels": first.channels,
              "sample_rate": str(first.sample_rate), "bit_rate": str(stream_bit_rate) if stream_bit_rate else None}
    if profile:
        stream["profile"] = profile
    return {
        "format_tags": movie.tags,
        "stream_tags": first.metadata,
        "duration_seconds": seconds,
        "stream": stream,
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "format_long_name": "QuickTime / MOV",
                   "bit_rate": str(int(file_size * 8.0 * 1_000_000 / us)) if us else None},
        "chapter_count": chapter_count,
    }


# A light read (no audio bit rate) leaves out the bodies of these sample tables, by
# far the largest part of a long book's moov (median 3 MB, up to 18 MB): parse()
# reads only how many entries stsz and stco/co64 hold, and the rest are skipped, as
# are free space (often 100 KB or more, left for tag edits) and unused tables.
# The value is how many payload bytes of each are still read.
LIGHT_TABLE_HEADS = {b"stsz": 12, b"stco": 8, b"co64": 8, b"stss": 8, b"stps": 8, b"sdtp": 4,
                     b"sgpd": 8, b"sbgp": 8, b"free": 0, b"skip": 0, b"wide": 0}
LIGHT_CONTAINERS = {b"trak", b"mdia", b"minf", b"stbl", b"udta", b"ilst"}
# An embedded cover's image (up to about 900 KB) is never read: only its data header.
LIGHT_ITEM_HEADS = {b"covr": 16}
LIGHT_BLOCK = 64 * 1024


class _Blocks:
    """A light read's view of the file: whole 64 KB blocks, each read once, so the
    top-level headers and neighbouring small atoms share reads (on a network share
    every read is a round trip)."""

    def __init__(self, fd: int, size: int):
        self.fd, self.size = fd, size
        self.blocks: dict[int, bytes] = {}

    def get(self, offset: int, count: int) -> bytes:
        end = min(offset + count, self.size)
        if end <= offset:
            return b""
        first, last = offset // LIGHT_BLOCK, (end - 1) // LIGHT_BLOCK
        block = first
        while block <= last:
            if block in self.blocks:
                block += 1
                continue
            stop = block
            while stop + 1 <= last and stop + 1 not in self.blocks:
                stop += 1
            lo, hi = block * LIGHT_BLOCK, min((stop + 1) * LIGHT_BLOCK, self.size)
            chunk = os.pread(self.fd, hi - lo, lo)
            if len(chunk) != hi - lo:
                raise Unsupported("file shorter than its size")
            for i in range(block, stop + 1):
                self.blocks[i] = chunk[(i - block) * LIGHT_BLOCK:(i - block + 1) * LIGHT_BLOCK]
            block = stop + 1
        if first == last:
            o = offset - first * LIGHT_BLOCK
            return self.blocks[first][o:o + (end - offset)]
        joined = b"".join(self.blocks[i] for i in range(first, last + 1))
        o = offset - first * LIGHT_BLOCK
        return joined[o:o + (end - offset)]


def _read_moov_light(blocks: _Blocks, start: int, length: int) -> bytearray:
    """The moov payload with the bodies LIGHT_TABLE_HEADS and LIGHT_ITEM_HEADS name
    left as zeros."""
    data = bytearray(length)

    def ensure(offset: int, count: int) -> None:
        end = min(offset + count, length)
        if end > offset:
            data[offset:end] = blocks.get(start + offset, end - offset)

    def visit(pos: int, end: int, depth: int) -> None:
        if depth > 10:
            raise Unsupported("atoms nested too deeply")
        while pos + 8 <= end:
            ensure(pos, 16)
            size, kind = struct.unpack(">I4s", data[pos:pos + 8])
            header = 8
            if size == 1 and pos + 16 <= end:
                size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
                header = 16
            elif size == 0:
                size = end - pos
            if size < header:
                return
            box_end = min(pos + size, end)
            if kind in LIGHT_CONTAINERS:
                visit(pos + header, box_end, depth + 1)
            elif kind == b"meta":
                # parse() finds meta's children from its hdlr (mov_read_meta); so does this.
                ensure(pos, min(box_end - pos, header + 64))
                hdlr = data.find(b"hdlr", pos + header, min(box_end, pos + header + 64))
                if hdlr < 0:
                    ensure(pos, box_end - pos)
                else:
                    visit(hdlr - 4, box_end, depth + 1)
            elif kind in LIGHT_TABLE_HEADS:
                ensure(pos, header + LIGHT_TABLE_HEADS[kind])
            elif kind in LIGHT_ITEM_HEADS:
                ensure(pos, header + LIGHT_ITEM_HEADS[kind])
            else:
                ensure(pos, box_end - pos)
            pos += size

    visit(0, length, 0)
    return data


def read_atoms(path: Path, light: bool = False) -> tuple[bytes, bytes, int]:
    """The file's ftyp and moov payloads and its size, with readahead off; light
    leaves out the sample-table bodies (see LIGHT_TABLE_HEADS)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_RANDOM)
        except (AttributeError, OSError):
            pass
        file_size = os.fstat(fd).st_size
        blocks = _Blocks(fd, file_size) if light else None
        pread = blocks.get if blocks else (lambda offset, count: os.pread(fd, count, offset))
        ftyp = moov = None
        pos = 0
        while pos + 8 <= file_size:
            head = pread(pos, 16)
            if len(head) < 8:
                break
            size, kind = struct.unpack(">I4s", head[:8])
            header = 8
            if size == 1:
                size = struct.unpack(">Q", head[8:16])[0]
                header = 16
            elif size == 0:
                size = file_size - pos
            if size < header:
                raise Unsupported("bad top-level atom")
            if kind == b"ftyp":
                if ftyp is not None or moov is not None:
                    raise Unsupported("ftyp after moov")
                ftyp = pread(pos + header, min(size - header, 4096))
            elif kind == b"moov":
                if moov is not None:
                    raise Unsupported("two moov atoms")
                if size - header > MAX_MOOV_BYTES:
                    raise Unsupported("moov too large")
                if blocks:
                    moov = _read_moov_light(blocks, pos + header, size - header)
                else:
                    moov = os.pread(fd, size - header, pos + header)
                if len(moov) != size - header:
                    raise Unsupported("truncated moov")
            elif kind == b"moof":
                raise Unsupported("fragmented file")
            elif kind not in (b"mdat", b"free", b"skip", b"wide"):
                raise Unsupported(f"top-level atom {kind!r}")
            pos += size
        if moov is None or ftyp is None:
            raise Unsupported("no moov or ftyp")
        return ftyp, moov, file_size
    finally:
        os.close(fd)


def read(path: Path, light: bool = False) -> dict[str, Any]:
    """{format_tags, stream_tags, duration_seconds, stream, format, chapter_count}, as ffprobe reports them.

    light reads a fraction of a long book's moov; its stream bit rate is then not
    the file's (it needs every sample's size), so a light read reports no audio."""
    return parse(*read_atoms(path, light), light=light)
