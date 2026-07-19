from __future__ import annotations

import json
import importlib.util
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


AUDIO_EXTENSIONS = {".m4b", ".m4a", ".mp4", ".mp3", ".flac", ".ogg", ".opus", ".aac", ".wav"}

# Borrowed from the two reference projects' useful behavior:
# - chapterize-whisper: broad "starts with marker" headings.
# - Chapterize-Audiobooks: explicit markers plus an exclusion list for false positives.
MARKER_WORDS = (
    "prologue",
    "prolog",
    "chapter",
    "epilogue",
    "epilog",
    "part",
    "book",
    "section",
    "introduction",
    "interlude",
    "intermission",
    "afterword",
    "foreword",
    "preface",
    "appendix",
)

EXCLUDED_PHRASES = (
    "chapter and verse",
    "chapters",
    "this chapter",
    "that chapter",
    "chapter of",
    "in chapter",
    "and chapter",
    "chapter heading",
    "chapter head",
    "chapter house",
    "chapter book",
    "a chapter",
    "chapter out",
    "chapter in",
    "particular chapter",
    "spicy chapter",
    "before chapter",
    "main chapter",
    "final chapter",
    "concluding chapter",
    "glorious chapter",
    "next chapter",
    "chapter asking",
    "matthew chapter",
    "forgotten chapter",
    "last chapter",
    "chapter room",
    "the chapter",
    "skip forward to chapter",
    "skip to chapter",
    "go to chapter",
    "return to chapter",
    "listen to chapter",
    "rather not listen",
    "copyright",
    "all rights reserved",
    "recording copyright",
    "text copyright",
    "published by",
    "produced by",
    "prologue to",
    "from prologue",
    "epilogue to",
    "from epilogue",
    "a book which",
    "a book that",
    "the book which",
    "the book that",
    "book which teaches",
)

NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "first": 1,
    "two": 2,
    "second": 2,
    "three": 3,
    "third": 3,
    "four": 4,
    "fourth": 4,
    "five": 5,
    "fifth": 5,
    "six": 6,
    "sixth": 6,
    "seven": 7,
    "seventh": 7,
    "eight": 8,
    "eighth": 8,
    "nine": 9,
    "ninth": 9,
    "ten": 10,
    "tenth": 10,
    "eleven": 11,
    "eleventh": 11,
    "twelve": 12,
    "twelfth": 12,
    "thirteen": 13,
    "thirteenth": 13,
    "fourteen": 14,
    "fourteenth": 14,
    "fifteen": 15,
    "fifteenth": 15,
    "sixteen": 16,
    "sixteenth": 16,
    "seventeen": 17,
    "seventeenth": 17,
    "eighteen": 18,
    "eighteenth": 18,
    "nineteen": 19,
    "nineteenth": 19,
    "twenty": 20,
    "twentieth": 20,
    "thirty": 30,
    "thirtieth": 30,
    "forty": 40,
    "fortieth": 40,
    "fifty": 50,
    "fiftieth": 50,
    "sixty": 60,
    "sixtieth": 60,
}

ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}

MARKER_RE = re.compile(
    r"\b(?P<kind>prologue|prolog|epilogue|epilog|chapter|part|book|section|"
    r"introduction|interlude|intermission|afterword|foreword|preface|appendix)\b"
    r"(?P<tail>[\s,.:;-]*(?:[a-z0-9ivxlc-]+(?:\s+[a-z0-9ivxlc-]+){0,14})?)",
    re.IGNORECASE,
)
STANDALONE_NUMBERED_HEADING_RE = re.compile(
    r"(?P<prefix>^|[.!?]\s+)"
    r"(?P<number>\d{1,3}|[ivxlc]{1,8})[.)]\s+"
    r"(?P<title>[A-Z][A-Za-z0-9' -]{1,80})"
)
END_OF_RE = re.compile(r"\bend\s+of\s+(chapter|part|book|section)\b", re.IGNORECASE)
PROSE_START_WORDS = {
    "i", "we", "he", "she", "they", "it", "as", "when",
    "while", "during", "after", "before", "then", "my", "our", "his", "her",
}
MAX_TITLE_WORDS_AFTER_NUMBER = 7
RESCAN_CONTEXT_SECONDS = 240.0
RESCAN_MIN_WINDOW_SECONDS = 480.0
RESCAN_BOUNDARY_PAD_BEFORE_SECONDS = 10.0
RESCAN_BOUNDARY_PAD_AFTER_SECONDS = 30.0
DEFAULT_SOS_MODEL_PATH = "/models"
DEFAULT_REMOTE_ASR_ENDPOINT = "http://192.168.1.50:8000"
DEFAULT_OLLAMA_ENDPOINT = "http://192.168.1.50:11434"


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    file: str = ""
    words: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChapterCandidate:
    start: float
    original_start: float
    end: float
    title: str
    marker_kind: str
    number: int | None = None
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    source_text: str = ""
    source_file: str = ""


@dataclass
class SequenceGap:
    expected_number: int
    start: float
    end: float
    reason: str


class ChapterDetectionCancelled(RuntimeError):
    pass


def audio_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in AUDIO_EXTENSIONS else []
    return sorted(
        child for child in path.rglob("*")
        if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS
    )


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return max(0.0, float((result.stdout or "0").strip()))
    except ValueError:
        return 0.0


def hms(seconds: float, comma: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms -= 1000
    hours, rem = divmod(whole, 3600)
    minutes, sec = divmod(rem, 60)
    sep = "," if comma else "."
    return f"{hours:02}:{minutes:02}:{sec:02}{sep}{ms:03}"


def parse_hms(value: str) -> float:
    text = value.strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp: {value}")
    sec = float(parts[2])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + sec


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def roman_to_int(value: str) -> int | None:
    value = value.lower().strip()
    if not value or not re.fullmatch(r"[ivxlc]+", value):
        return None
    total = 0
    previous = 0
    for char in reversed(value):
        current = ROMAN_VALUES.get(char, 0)
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total if 0 < total < 500 else None


def parse_number(words: str) -> int | None:
    cleaned = re.sub(r"[^a-z0-9ivxlc -]+", " ", words.lower())
    tokens = [token for token in cleaned.replace("-", " ").split() if token]
    if not tokens:
        return None
    if tokens[0].isdigit():
        return int(tokens[0])
    roman = roman_to_int(tokens[0])
    if roman is not None:
        return roman
    total = 0
    consumed = False
    for token in tokens[:3]:
        value = NUMBER_WORDS.get(token)
        if value is None:
            break
        total += value
        consumed = True
    return total if consumed and total > 0 else None


def title_case_marker(kind: str) -> str:
    lower = kind.lower()
    if lower == "prolog":
        return "Prologue"
    if lower == "epilog":
        return "Epilogue"
    return lower.title()


def title_from_match(match: re.Match[str], text: str) -> tuple[str, int | None]:
    kind = title_case_marker(match.group("kind"))
    tail = normalize_text(match.group("tail") or "")
    number = parse_number(tail)
    if number is not None and kind in {"Chapter", "Part", "Book", "Section"}:
        # Keep the transcript's human title after the marker number.
        title = normalize_text(text[match.start():])
        return title[:140] or f"{kind} {number}", number
    title = normalize_text(text[match.start():])
    return title[:140] or kind, number


def _title_word_count_after_marker(title: str, kind: str, number: int | None) -> int:
    words = re.findall(r"[A-Za-z0-9']+", title)
    if not words:
        return 0
    marker_index = next((i for i, word in enumerate(words) if word.lower() == kind.lower()), 0)
    skip = marker_index + (2 if number is not None else 1)
    return max(0, len(words[skip:]))


def trim_long_heading_title(title: str, kind: str, number: int | None) -> str:
    text = normalize_text(title).strip()
    if kind != "Chapter" or number is None:
        return text[:140]
    pieces = re.findall(r"[A-Za-z0-9']+|[^\w\s]", text)
    word_seen = 0
    marker_seen = False
    number_seen = False
    title_words = 0
    cut_index = len(text)
    search_pos = 0
    for piece in pieces:
        found_at = text.find(piece, search_pos)
        if found_at >= 0:
            search_pos = found_at + len(piece)
        if not re.fullmatch(r"[A-Za-z0-9']+", piece):
            continue
        word_seen += 1
        lower = piece.lower()
        if not marker_seen:
            marker_seen = lower == kind.lower()
            continue
        if not number_seen:
            if lower.isdigit() or lower in NUMBER_WORDS or roman_to_int(lower) is not None:
                number_seen = True
            continue
        title_words += 1
        if title_words > MAX_TITLE_WORDS_AFTER_NUMBER:
            cut_index = found_at if found_at >= 0 else len(text)
            break
    if cut_index < len(text):
        return text[:cut_index].strip(" .,;:-")[:140] or text[:140]
    return text[:140]


def smart_title_case(value: str) -> str:
    text = normalize_text(value).strip(" .,;:-")
    if not text:
        return text
    words = re.findall(r"[A-Za-z0-9']+|[^\w\s]", text)
    if not words:
        return text
    alpha_words = [word for word in words if re.search(r"[A-Za-z]", word)]
    if alpha_words and not all(word.isupper() for word in alpha_words):
        return text
    small_words = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
    pieces: list[str] = []
    word_index = 0
    for word in words:
        if re.fullmatch(r"[A-Za-z][A-Za-z']*", word):
            lower = word.lower()
            if word_index > 0 and lower in small_words:
                pieces.append(lower)
            else:
                pieces.append(word.capitalize())
            word_index += 1
        else:
            pieces.append(word)
    result = ""
    for piece in pieces:
        if not result:
            result = piece
        elif re.fullmatch(r"[^\w\s]", piece):
            result += piece
        elif result.endswith(("'", "\"", "(", "[", "{", "-")):
            result += piece
        else:
            result += " " + piece
    return result.strip()


def normalize_heading_title(title: str, kind: str, number: int | None) -> str:
    text = normalize_text(title).strip(" .,;:-")
    if not text:
        return text
    if kind == "Chapter" and number is not None:
        match = re.match(
            r"^\s*chapter\s+[A-Za-z0-9IVXLCivxlc-]+\.?\s*(?P<rest>.*)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            rest = normalize_text(match.group("rest"))
            rest_words = [word.lower() for word in re.findall(r"[A-Za-z']+", rest)]
            if len(rest_words) >= 5 and any(word in {"had", "was", "were", "did", "could", "would"} for word in rest_words):
                rest = ""
            rest = smart_title_case(rest)
            return normalize_text(f"Chapter {number} {rest}".strip())[:140]
    if kind in {"Interlude", "Prologue", "Epilogue", "Introduction", "Afterword", "Foreword", "Preface"}:
        marker = kind.lower()
        match = re.match(rf"^\s*{re.escape(marker)}\b\.?\s*(?P<rest>.*)$", text, flags=re.IGNORECASE)
        if match:
            rest = normalize_text(match.group("rest"))
            if not rest:
                return kind
            first = re.match(r"[A-Za-z']+", rest)
            if first and first.group(0).lower() in PROSE_START_WORDS:
                return kind
            sentence_words = re.findall(r"[A-Za-z0-9']+", rest)
            if len(sentence_words) > MAX_TITLE_WORDS_AFTER_NUMBER and not rest[:1].isupper():
                return kind
            return normalize_text(f"{kind} {smart_title_case(rest)}")[:140]
    return smart_title_case(text)[:140]


def trim_title_prose(title: str, kind: str, number: int | None) -> str:
    text = normalize_text(title).strip()
    if not text:
        return text
    marker = kind.lower()
    words = re.findall(r"[A-Za-z0-9']+", text)
    if len(words) < 4:
        return normalize_heading_title(text, kind, number)

    marker_index = next((i for i, word in enumerate(words) if word.lower() == marker), -1)
    if marker_index < 0:
        marker_index = 0 if kind in {"Prologue", "Epilogue", "Introduction", "Interlude"} else -1
    if marker_index < 0:
        return text

    for match in re.finditer(r"\b([A-Z]?[a-z][a-z']+|I)\b", text):
        word = match.group(1).lower()
        if word not in PROSE_START_WORDS:
            continue
        before = text[:match.start()].strip(" .,;:-")
        before_words = re.findall(r"[A-Za-z0-9']+", before)
        title_words = before_words[marker_index + (2 if number is not None else 1):]
        if len(title_words) < 1:
            continue
        if word in PROSE_START_WORDS or "." in before or len(title_words) >= 2:
            before = re.sub(r"\b(as|when|while|during|after|before|then)$", "", before, flags=re.IGNORECASE).strip(" .,;:-")
            return normalize_heading_title(before[:140] or text, kind, number)
    return normalize_heading_title(trim_long_heading_title(text, kind, number), kind, number)


def is_bare_marker_title(title: str, kind: str, number: int | None) -> bool:
    cleaned = normalize_text(title).strip(" .,;:-").lower()
    if not cleaned:
        return True
    marker = kind.lower()
    if number is None:
        return cleaned == marker
    number_tokens = {str(number)}
    for word, value in NUMBER_WORDS.items():
        if value == number:
            number_tokens.add(word)
    roman = int_to_roman(number).lower() if 0 < number < 400 else ""
    if roman:
        number_tokens.add(roman)
    return cleaned in {f"{marker} {token}" for token in number_tokens} | {f"{marker} {token}." for token in number_tokens}


def int_to_roman(value: int) -> str:
    numerals = [
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    result = []
    remaining = value
    for amount, symbol in numerals:
        while remaining >= amount:
            result.append(symbol)
            remaining -= amount
    return "".join(result)


def extend_bare_title(title: str, kind: str, number: int | None, segments: list[TranscriptSegment], index: int) -> tuple[str, str | None]:
    if not is_bare_marker_title(title, kind, number):
        return title, None
    if kind != "Chapter" or number is None:
        return title, None
    if index + 1 >= len(segments):
        return title, None
    current = segments[index]
    following = segments[index + 1]
    if following.start - current.end > 8.0:
        return title, None
    next_text = normalize_text(following.text).strip(" .,;:-")
    if not next_text or any(phrase in next_text.lower() for phrase in EXCLUDED_PHRASES):
        return title, None
    combined = f"{title.rstrip(' .,:;-')}. {next_text}" if number is not None else f"{title.rstrip(' .,:;-')} {next_text}"
    return combined[:140], "title-extended-next-segment"


def find_marker_candidates(segments: list[TranscriptSegment]) -> list[ChapterCandidate]:
    candidates: list[ChapterCandidate] = []
    for index, segment in enumerate(segments):
        text = normalize_text(segment.text)
        lowered = text.lower()
        if not text or any(phrase in lowered for phrase in EXCLUDED_PHRASES):
            continue
        for match in MARKER_RE.finditer(text):
            prefix = text[max(0, match.start() - 16):match.start()]
            if END_OF_RE.search(prefix):
                continue
            kind = title_case_marker(match.group("kind"))
            start = estimate_marker_time(segment, match.start(), len(text))
            title, number = title_from_match(match, text)
            at_segment_start = match.start() <= 3
            if kind in {"Book", "Part", "Section"} and number is None:
                continue
            if kind == "Chapter" and not at_segment_start and number is None:
                continue
            confidence = 0.45
            reasons = [f"marker:{kind.lower()}"]
            if at_segment_start:
                confidence += 0.2
                reasons.append("segment-start")
            if number is not None:
                confidence += 0.15
                reasons.append(f"number:{number}")
            if kind in {"Prologue", "Epilogue", "Introduction", "Afterword", "Foreword", "Preface"}:
                confidence += 0.1
                reasons.append("structural-marker")
            if not at_segment_start:
                confidence -= 0.2
                reasons.append("embedded-marker")
            title, title_reason = extend_bare_title(title, kind, number, segments, index)
            if title_reason:
                confidence += 0.05
                reasons.append(title_reason)
            trimmed = trim_title_prose(title, kind, number)
            if trimmed != title:
                title = trimmed
                reasons.append("title-trimmed-prose")
            candidates.append(
                ChapterCandidate(
                    start=start,
                    original_start=start,
                    end=segment.end,
                    title=title,
                    marker_kind=kind,
                    number=number,
                    confidence=min(confidence, 0.95),
                    reasons=reasons,
                    source_text=text,
                    source_file=segment.file,
                )
            )
        for match in STANDALONE_NUMBERED_HEADING_RE.finditer(text):
            number = parse_number(match.group("number"))
            if number is None or number <= 0:
                continue
            title_tail = normalize_text(match.group("title")).strip(" .,;:-")
            title_words = re.findall(r"[A-Za-z0-9']+", title_tail)
            if not title_tail or len(title_words) > MAX_TITLE_WORDS_AFTER_NUMBER:
                continue
            if title_words and title_words[0].lower() in PROSE_START_WORDS:
                continue
            start_index = match.start("number")
            start = estimate_marker_time(segment, start_index, len(text))
            title = normalize_heading_title(f"Chapter {number} {title_tail}", "Chapter", number)
            candidates.append(
                ChapterCandidate(
                    start=start,
                    original_start=start,
                    end=segment.end,
                    title=title,
                    marker_kind="Chapter",
                    number=number,
                    confidence=0.52,
                    reasons=["standalone-numbered-heading", f"number:{number}"],
                    source_text=text,
                    source_file=segment.file,
                )
            )
    return candidates


def estimate_marker_time(segment: TranscriptSegment, char_index: int, text_length: int) -> float:
    if text_length <= 0:
        return segment.start
    # Without word timestamps, split the segment duration proportionally. This
    # handles "End of chapter 5. Chapter 6..." better than pinning to segment start.
    ratio = min(0.9, max(0.0, char_index / text_length))
    return segment.start + (segment.end - segment.start) * ratio


def dedupe_candidates(candidates: list[ChapterCandidate], window: float = 20.0) -> list[ChapterCandidate]:
    ordered = sorted(candidates, key=lambda item: (item.start, -item.confidence))
    result: list[ChapterCandidate] = []
    for candidate in ordered:
        if result and abs(result[-1].start - candidate.start) <= window:
            if candidate.confidence > result[-1].confidence:
                result[-1] = candidate
            continue
        result.append(candidate)
    return result


def is_numbered_chapter(candidate: ChapterCandidate) -> bool:
    return candidate.marker_kind == "Chapter" and candidate.number is not None


def validate_sequence(
    candidates: list[ChapterCandidate],
    *,
    min_chapter_seconds: float = 60.0,
) -> list[ChapterCandidate]:
    accepted: list[ChapterCandidate] = []
    last_number: int | None = None
    for candidate in candidates:
        if accepted and candidate.start - accepted[-1].start < min_chapter_seconds:
            candidate.confidence -= 0.25
            candidate.reasons.append("too-close")
            if candidate.confidence <= accepted[-1].confidence:
                continue
            accepted[-1] = candidate
            continue
        if is_numbered_chapter(candidate):
            if last_number is not None and candidate.number == last_number + 1:
                candidate.confidence += 0.2
                candidate.reasons.append("sequence-ok")
            elif last_number is not None and candidate.number <= last_number:
                candidate.confidence -= 0.35
                candidate.reasons.append("sequence-backtrack")
            elif last_number is not None and candidate.number > last_number + 2:
                candidate.confidence -= 0.15
                candidate.reasons.append("sequence-gap")
            if candidate.confidence >= 0.45:
                last_number = candidate.number
        if candidate.confidence >= 0.45:
            accepted.append(candidate)
    return accepted


def sequence_gaps(candidates: list[ChapterCandidate], duration: float) -> list[SequenceGap]:
    chapters = sorted((item for item in candidates if is_numbered_chapter(item)), key=lambda item: item.start)
    gaps: list[SequenceGap] = []
    if not chapters:
        return gaps
    first = chapters[0]
    if first.number and first.number > 1:
        for expected in range(1, first.number):
            span = max(RESCAN_MIN_WINDOW_SECONDS, min(600.0, first.start))
            gaps.append(SequenceGap(expected, max(0.0, first.start - span), max(0.0, first.start - 30.0), "missing-before-first"))
    for previous, current in zip(chapters, chapters[1:]):
        if previous.number is None or current.number is None:
            continue
        if current.number <= previous.number:
            continue
        missing = list(range(previous.number + 1, current.number))
        if not missing:
            continue
        for expected in missing:
            gaps.append(
                SequenceGap(
                    expected,
                    max(0.0, previous.start - RESCAN_BOUNDARY_PAD_BEFORE_SECONDS),
                    min(duration, current.start + RESCAN_BOUNDARY_PAD_AFTER_SECONDS),
                    "missing-between-detected",
                )
            )
    return gaps


def correct_obvious_sequence_misreads(candidates: list[ChapterCandidate]) -> None:
    chapters = sorted((item for item in candidates if is_numbered_chapter(item)), key=lambda item: item.start)
    for previous, current, following in zip(chapters, chapters[1:], chapters[2:]):
        if previous.number is None or current.number is None or following.number is None:
            continue
        expected = previous.number + 1
        if following.number == expected + 1 and current.number != expected:
            current.reasons.append(f"sequence-corrected-from:{current.number}")
            current.number = expected
            current.title = re.sub(
                r"\bChapter\s+[A-Za-z0-9IVXLCivxlc-]+\b",
                f"Chapter {expected}",
                current.title,
                count=1,
                flags=re.IGNORECASE,
            )
            current.confidence = max(0.55, current.confidence - 0.05)


def annotate_unresolved_gaps(candidates: list[ChapterCandidate], duration: float) -> list[dict[str, Any]]:
    return [
        {
            "expected_number": gap.expected_number,
            "start": round(gap.start, 3),
            "end": round(gap.end, 3),
            "reason": gap.reason,
        }
        for gap in sequence_gaps(candidates, duration)
    ]


def detect_silences(files: list[Path], offsets: dict[str, float], noise_db: int = -35, min_duration: float = 0.6) -> list[tuple[float, float]]:
    silences: list[tuple[float, float]] = []
    silence_start: float | None = None
    for file_path in files:
        offset = offsets.get(str(file_path), 0.0)
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(file_path),
                "-map",
                "0:a:0",
                "-dn",
                "-sn",
                "-vn",
                "-af",
                f"silencedetect=noise={noise_db}dB:d={min_duration}",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        for line in (result.stderr or "").splitlines():
            if "silence_start:" in line:
                try:
                    silence_start = float(line.rsplit("silence_start:", 1)[1].strip()) + offset
                except ValueError:
                    silence_start = None
            elif "silence_end:" in line and silence_start is not None:
                match = re.search(r"silence_end:\s*([0-9.]+)", line)
                if match:
                    silences.append((silence_start, float(match.group(1)) + offset))
                silence_start = None
    return silences


def snap_to_silence(
    candidates: list[ChapterCandidate],
    silences: list[tuple[float, float]],
    window: float = 4.0,
    marker_lead_seconds: float = 1.0,
) -> None:
    for candidate in candidates:
        marker_start = float(candidate.start)
        lead = max(0.0, float(marker_lead_seconds or 0.0))
        if lead > 0:
            target = max(0.0, marker_start - lead)
            best_time: float | None = None
            best_delta = math.inf
            for start, end in silences:
                if end < marker_start - window or start > marker_start + window:
                    continue
                clamped = min(max(target, start), end)
                delta = abs(target - clamped)
                if delta < best_delta and delta <= window:
                    best_time = clamped
                    best_delta = delta
            if best_time is not None:
                candidate.start = best_time
                candidate.reasons.append("silence-lead-snapped")
                candidate.confidence = min(0.99, candidate.confidence + 0.08)
                continue
        best: tuple[float, float] | None = None
        best_delta = math.inf
        for start, end in silences:
            for boundary in (start, end):
                delta = abs(marker_start - boundary)
                if delta < best_delta and delta <= window:
                    best = (start, end)
                    best_delta = delta
        if best:
            candidate.start = best[1] if best[1] <= marker_start + 0.5 else best[0]
            candidate.reasons.append("silence-snapped")
            candidate.confidence = min(0.99, candidate.confidence + 0.08)


# Audible always brackets a book with "Opening Credits" (0 -> first real
# chapter) and "End Credits" (last real chapter -> file end) entries. Our own
# silence+keyword detection has no spoken cue to key off for either -- no one
# says the word "credits" -- so these are synthesized structurally instead:
# a real leading/trailing gap around the detected content, not a keyword hit.
# Thresholds are deliberately conservative (matches SoS's own
# SILENCE_DURATION=2.5 "this counts as a boundary-caliber silence" cutoff)
# so a normal in-chapter pause near the very start/end of a book isn't
# mistaken for a credits split.
OPENING_CREDITS_MIN_GAP_SECONDS = 3.0
END_CREDITS_MIN_SILENCE_SECONDS = 2.5
END_CREDITS_MIN_TRAILING_SECONDS = 3.0
# The credits reading itself has its own internal pauses between sentences,
# often longer than the pause marking where real content actually ends --
# live-verified on Divine Apostasy Book 2 where the *first* qualifying gap
# after the last chapter's start landed within 2s of Audible's own End
# Credits boundary, but the *latest* one instead caught a pause inside the
# credits reading, 21s past the real boundary. Search only the file's own
# tail (credits readings are always short and always at the very end,
# regardless of book length) and take the earliest qualifying gap in it.
END_CREDITS_SEARCH_WINDOW_SECONDS = 120.0
# Buffer added past the synthesized Opening/End Credits boundary when
# transcribing it for evidence: the "written by ... narrated by ..." phrase
# regularly trails a couple seconds past the silence-derived split point
# (live-verified on Divine Apostasy Book 2, where the real announcement ran
# to 17.0s but the synthesized Opening Credits boundary landed at 16.4s).
CREDITS_EVIDENCE_BUFFER_SECONDS = 5.0


def _synthesize_credits_rows(
    chapters: list[dict[str, Any]],
    duration: float,
    silences: list[tuple[float, float]] | None,
) -> list[dict[str, Any]]:
    if not chapters:
        return chapters

    def credits_row(title: str, start: float, end: float) -> dict[str, Any]:
        return {
            "start": round(start, 3),
            "end": round(end, 3),
            "title": title,
            "marker_kind": title,
            "number": None,
            "confidence": None,
            "reasons": ["synthesized:leading-gap" if title == "Opening Credits" else "synthesized:trailing-gap"],
            "source_text": "",
            "source_file": "",
            "original_start": round(start, 3),
        }

    result = list(chapters)
    if result[0]["start"] > OPENING_CREDITS_MIN_GAP_SECONDS:
        result.insert(0, credits_row("Opening Credits", 0.0, result[0]["start"]))

    if silences:
        last = result[-1]
        window_start = max(last["start"], duration - END_CREDITS_SEARCH_WINDOW_SECONDS)
        candidates = [
            (s_start, s_end)
            for s_start, s_end in silences
            if s_start >= window_start
            and (s_end - s_start) >= END_CREDITS_MIN_SILENCE_SECONDS
            and (duration - s_end) >= END_CREDITS_MIN_TRAILING_SECONDS
        ]
        if candidates:
            split_start, split_end = min(candidates, key=lambda pair: pair[0])
            split_point = (split_start + split_end) / 2.0
            last["end"] = round(split_point, 3)
            result.append(credits_row("End Credits", split_point, duration))

    for index, chapter in enumerate(result):
        chapter["id"] = index + 1
    return result


def finalize_chapters(
    candidates: list[ChapterCandidate],
    duration: float,
    silences: list[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    ordered = sorted(candidates, key=lambda item: item.start)
    for index, candidate in enumerate(ordered):
        end = ordered[index + 1].start if index + 1 < len(ordered) else duration
        if end <= candidate.start:
            end = min(duration, candidate.start + 1.0)
        chapters.append({
            "id": index + 1,
            "start": round(candidate.start, 3),
            "end": round(end, 3),
            "title": candidate.title,
            "marker_kind": candidate.marker_kind,
            "number": candidate.number,
            "confidence": round(max(0.0, min(1.0, candidate.confidence)), 3),
            "reasons": candidate.reasons,
            "source_text": candidate.source_text,
            "source_file": candidate.source_file,
            "original_start": round(candidate.original_start, 3),
        })
    return _synthesize_credits_rows(chapters, duration, silences)


def enrich_chapter_evidence(
    chapters: list[dict[str, Any]],
    segments: list[TranscriptSegment],
    silences: list[tuple[float, float]] | None = None,
    *,
    before_seconds: float = 120.0,
    after_seconds: float = 180.0,
) -> None:
    if not chapters:
        return
    silences = silences or []
    ordered_segments = sorted(segments, key=lambda item: item.start)
    for chapter in chapters:
        start = float(chapter.get("start") or 0.0)
        window_start = max(0.0, start - before_seconds)
        window_end = start + after_seconds
        nearby_segments = [
            segment for segment in ordered_segments
            if segment.end >= window_start and segment.start <= window_end and normalize_text(segment.text)
        ]
        anchors: list[dict[str, Any]] = []
        word_anchors: list[dict[str, Any]] = []
        silence_windows: list[dict[str, Any]] = []
        evidence_lines: list[str] = []
        for segment in nearby_segments:
            text = normalize_text(segment.text)
            if not text:
                continue
            anchors.append({
                "time": round(segment.start, 3),
                "label": f"{hms(segment.start)} transcript",
                "kind": "transcript",
                "text": text[:220],
            })
            evidence_lines.append(f"[{hms(segment.start)} - {hms(segment.end)}] {text}")
            for word in segment.words or []:
                word_text = normalize_text(str(word.get("word") or ""))
                word_start = float(word.get("start") or segment.start)
                word_end = float(word.get("end") or word_start)
                if not word_text or not (window_start <= word_start <= window_end):
                    continue
                word_anchors.append(
                    {
                        "start": round(word_start, 3),
                        "end": round(word_end, 3),
                        "text": word_text,
                        "probability": word.get("probability"),
                    }
                )
        for silence_start, silence_end in silences:
            if silence_end < window_start or silence_start > window_end:
                continue
            clipped_start = max(window_start, float(silence_start))
            clipped_end = min(window_end, float(silence_end))
            if clipped_end > clipped_start:
                silence_windows.append(
                    {
                        "start": round(clipped_start, 3),
                        "end": round(clipped_end, 3),
                        "duration": round(clipped_end - clipped_start, 3),
                    }
                )
            if window_start <= silence_start <= window_end:
                anchors.append({
                    "time": round(silence_start, 3),
                    "label": f"{hms(silence_start)} silence start",
                    "kind": "silence",
                    "text": "silence start",
                })
            if window_start <= silence_end <= window_end:
                anchors.append({
                    "time": round(silence_end, 3),
                    "label": f"{hms(silence_end)} silence end",
                    "kind": "silence",
                    "text": "silence end",
                })
        anchors.sort(key=lambda item: (float(item["time"]), item["kind"]))
        deduped_anchors: list[dict[str, Any]] = []
        for anchor in anchors:
            if deduped_anchors and abs(float(anchor["time"]) - float(deduped_anchors[-1]["time"])) < 0.05 and anchor["kind"] == deduped_anchors[-1]["kind"]:
                continue
            deduped_anchors.append(anchor)
        if evidence_lines:
            chapter["evidence_text"] = "\n".join(evidence_lines[:120])
            chapter["source_text"] = chapter["evidence_text"]
        else:
            chapter["evidence_text"] = str(chapter.get("source_text") or "")
        chapter["evidence_anchors"] = deduped_anchors[:180]
        chapter["evidence_words"] = word_anchors[:500]
        chapter["evidence_silences"] = silence_windows[:80]


def transcribe_faster_whisper(
    files: list[Path],
    *,
    model_name: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
    vad_filter: bool,
    language: str = "en",
    condition_on_previous_text: bool = False,
    beam_size: int = 1,
    progress: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    source_labels: dict[str, str] | None = None,
    file_offsets: dict[str, float] | None = None,
) -> tuple[list[TranscriptSegment], float, dict[str, float]]:
    if should_cancel and should_cancel():
        raise ChapterDetectionCancelled("Chapter detection cancelled")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed in this container") from exc

    if progress:
        progress(f"Loading faster-whisper model {model_name}")
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )
    segments: list[TranscriptSegment] = []
    offsets: dict[str, float] = {}
    durations = {str(file_path): ffprobe_duration(file_path) for file_path in files}
    total_audio_duration = sum(durations.values())
    last_progress_percent = -1.0
    offset = 0.0
    for file_path in files:
        if should_cancel and should_cancel():
            raise ChapterDetectionCancelled("Chapter detection cancelled")
        base_offset = file_offsets.get(str(file_path), offset) if file_offsets else offset
        offsets[str(file_path)] = base_offset
        if progress:
            progress(f"Transcribing {file_path.name}")
        if should_cancel and should_cancel():
            raise ChapterDetectionCancelled("Chapter detection cancelled")
        result, info = model.transcribe(
            str(file_path),
            language=language or None,
            beam_size=beam_size,
            vad_filter=vad_filter,
            vad_parameters={"min_silence_duration_ms": 1000, "speech_pad_ms": 400},
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt="This is an audiobook with spoken chapter headings.",
        )
        duration = float(getattr(info, "duration", 0.0) or 0.0) or durations.get(str(file_path), 0.0)
        if duration > 0:
            durations[str(file_path)] = duration
        for segment in result:
            if should_cancel and should_cancel():
                raise ChapterDetectionCancelled("Chapter detection cancelled")
            segment_start = float(segment.start)
            segment_end = float(segment.end)
            segments.append(
                TranscriptSegment(
                    start=segment_start + base_offset,
                    end=segment_end + base_offset,
                    text=segment.text,
                    file=(source_labels or {}).get(str(file_path), str(file_path)),
                )
            )
            if progress and total_audio_duration > 0:
                done = min(total_audio_duration, offset + segment_end)
                progress_percent = round((done / total_audio_duration) * 100, 1)
                if progress_percent >= last_progress_percent + 1.0 or progress_percent >= 99.9:
                    last_progress_percent = progress_percent
                    progress(
                        f"Transcribing progress={progress_percent} "
                        f"{hms(done)} / {hms(total_audio_duration)} {file_path.name}"
                    )
        offset += duration
    return segments, offset, offsets


def limited_audio_files(
    files: list[Path],
    max_audio_seconds: float,
    chunk_seconds: float = 0.0,
) -> tuple[list[Path], Path | None, dict[str, str]]:
    source_labels: dict[str, str] = {str(file_path): str(file_path) for file_path in files}
    if max_audio_seconds <= 0 and chunk_seconds <= 0:
        return files, None, source_labels
    temp_dir = Path(tempfile.mkdtemp(prefix="libraforge-chapter-limit-"))
    limited: list[Path] = []
    remaining = max_audio_seconds if max_audio_seconds > 0 else math.inf
    for index, file_path in enumerate(files, start=1):
        if remaining <= 0:
            break
        duration = ffprobe_duration(file_path)
        process_duration = min(duration, remaining)
        if chunk_seconds <= 0 and duration <= remaining:
            limited.append(file_path)
            remaining -= duration
            continue
        if chunk_seconds <= 0:
            chunk_plan = [(0.0, process_duration)]
        else:
            chunk_plan = []
            start = 0.0
            while start < process_duration:
                length = min(chunk_seconds, process_duration - start)
                chunk_plan.append((start, length))
                start += length
        for chunk_index, (start, length) in enumerate(chunk_plan, start=1):
            clip_path = temp_dir / f"clip-{index:03d}-{chunk_index:04d}.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    str(start),
                    "-i",
                    str(file_path),
                    "-t",
                    str(max(1.0, length)),
                    "-map",
                    "0:a:0",
                    "-dn",
                    "-sn",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(clip_path),
                ],
                check=True,
                timeout=300,
            )
            limited.append(clip_path)
            source_labels[str(clip_path)] = str(file_path)
        remaining -= process_duration
    return limited, temp_dir, source_labels


def source_file_offsets(files: list[Path]) -> dict[str, float]:
    offsets: dict[str, float] = {}
    current = 0.0
    for file_path in files:
        offsets[str(file_path)] = current
        current += ffprobe_duration(file_path)
    return offsets


def make_focus_clips(
    files: list[Path],
    gaps: list[SequenceGap],
    *,
    accurate_seek: bool = False,
) -> tuple[list[Path], Path | None, dict[str, str], dict[str, float], dict[str, int]]:
    if not gaps:
        return [], None, {}, {}, {}
    source_offsets = source_file_offsets(files)
    source_durations = {str(file_path): ffprobe_duration(file_path) for file_path in files}
    temp_dir = Path(tempfile.mkdtemp(prefix="libraforge-chapter-rescan-"))
    clips: list[Path] = []
    labels: dict[str, str] = {}
    offsets: dict[str, float] = {}
    expected_numbers: dict[str, int] = {}
    for gap_index, gap in enumerate(gaps, start=1):
        for file_index, file_path in enumerate(files, start=1):
            file_offset = source_offsets[str(file_path)]
            file_duration = source_durations[str(file_path)]
            file_start = max(0.0, gap.start - file_offset)
            file_end = min(file_duration, gap.end - file_offset)
            if file_end - file_start < 5.0:
                continue
            clip_path = temp_dir / f"gap-{gap_index:03d}-file-{file_index:03d}.wav"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
            if accurate_seek:
                pre_seek = max(0.0, file_start - 5.0)
                command.extend(["-ss", str(pre_seek), "-i", str(file_path), "-ss", str(file_start - pre_seek)])
            else:
                command.extend(["-ss", str(file_start), "-i", str(file_path)])
            command.extend(
                [
                    "-t",
                    str(max(1.0, file_end - file_start)),
                    "-map",
                    "0:a:0",
                    "-dn",
                    "-sn",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(clip_path),
                ]
            )
            subprocess.run(command, check=True, timeout=300)
            key = str(clip_path)
            clips.append(clip_path)
            labels[key] = str(file_path)
            offsets[key] = file_offset + file_start
            expected_numbers[key] = gap.expected_number
    if not clips:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return [], None, {}, {}, {}
    return clips, temp_dir, labels, offsets, expected_numbers


def merge_rescan_candidates(
    base: list[ChapterCandidate],
    rescanned: list[ChapterCandidate],
    gaps: list[SequenceGap],
) -> list[ChapterCandidate]:
    if not rescanned:
        return base
    accepted = list(base)
    for gap in gaps:
        matches = [
            candidate for candidate in rescanned
            if is_numbered_chapter(candidate)
            and candidate.number == gap.expected_number
            and gap.start <= candidate.start <= gap.end
        ]
        if not matches:
            continue
        best = max(matches, key=lambda item: (item.confidence, -abs(item.start - ((gap.start + gap.end) / 2))))
        if any(abs(existing.start - best.start) <= 20.0 for existing in accepted):
            continue
        best.reasons.append("focused-gap-rescan")
        best.confidence = min(0.97, best.confidence + 0.12)
        accepted.append(best)
    return validate_sequence(dedupe_candidates(accepted))


def rescan_sequence_gaps(
    original_files: list[Path],
    candidates: list[ChapterCandidate],
    duration: float,
    *,
    model_name: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
    vad_filter: bool,
    language: str,
    condition_on_previous_text: bool,
    beam_size: int,
    max_gap_rescans: int,
    progress: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[list[ChapterCandidate], list[dict[str, Any]]]:
    gaps = sequence_gaps(candidates, duration)[:max(0, max_gap_rescans)]
    if not gaps:
        return candidates, []
    if progress:
        progress(f"Focused rescan for {len(gaps)} sequence gap(s)")
    clips, temp_dir, labels, offsets, _expected = make_focus_clips(original_files, gaps)
    if not clips:
        return candidates, annotate_unresolved_gaps(candidates, duration)
    try:
        rescan_segments, _rescan_duration, _rescan_offsets = transcribe_faster_whisper(
            clips,
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            vad_filter=vad_filter,
            language=language,
            condition_on_previous_text=condition_on_previous_text,
            beam_size=beam_size,
            progress=progress,
            should_cancel=should_cancel,
            source_labels=labels,
            file_offsets=offsets,
        )
        rescan_candidates = validate_sequence(dedupe_candidates(find_marker_candidates(rescan_segments)))
        merged = merge_rescan_candidates(candidates, rescan_candidates, gaps)
        correct_obvious_sequence_misreads(merged)
        return merged, annotate_unresolved_gaps(merged, duration)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def write_srt(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        lines.extend([
            str(index),
            f"{hms(segment.start, comma=True)} --> {hms(segment.end, comma=True)}",
            normalize_text(segment.text),
            "",
        ])
    return "\n".join(lines)


def write_transcript_text(segments: list[TranscriptSegment]) -> str:
    lines = []
    for segment in segments:
        text = normalize_text(segment.text)
        if not text:
            continue
        lines.append(f"[{hms(segment.start)} - {hms(segment.end)}] {text}")
    return "\n".join(lines) + ("\n" if lines else "")


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sos_script_path() -> Path:
    root = _workspace_root()
    candidates = [
        root / "tools/ABS-scripts/SoundOfSilence.py",
        Path("/app/tools/ABS-scripts/SoundOfSilence.py"),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise RuntimeError("ABS SoundOfSilence.py was not found under tools/ABS-scripts")


def _load_sos_module() -> Any:
    path = _sos_script_path()
    spec = importlib.util.spec_from_file_location("abs_soundofsilence_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load SoundOfSilence script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _number_from_sos_text(text: str) -> int | None:
    cleaned = re.sub(r"^[^A-Za-z0-9]+", "", text or "").strip()
    match = re.match(r"^(?:chapter|part|section)?\s*([A-Za-z0-9 -]+?)(?:[:.,\s]|$)", cleaned, flags=re.IGNORECASE)
    if match:
        number = parse_number(match.group(1))
        if number is not None:
            return number
    return parse_number(cleaned)


def _sos_rows_to_candidates(rows: list[dict[str, Any]]) -> list[ChapterCandidate]:
    segments = [
        TranscriptSegment(
            start=float(row.get("seconds") or 0.0),
            end=float(row.get("seconds") or 0.0) + 5.0,
            text=str(row.get("text") or ""),
            file="sound-of-silence",
        )
        for row in rows
    ]
    candidates = validate_sequence(dedupe_candidates(find_marker_candidates(segments)))
    for candidate in candidates:
        candidate.reasons.append("sound-of-silence")
        candidate.confidence = min(0.96, candidate.confidence + 0.08)
    correct_obvious_sequence_misreads(candidates)
    return candidates


def _run_sound_of_silence(
    source: Path,
    *,
    numbers_only: bool = False,
    progress: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[dict[str, Any]], float, int, list[ChapterCandidate]]:
    if should_cancel and should_cancel():
        raise ChapterDetectionCancelled("Chapter detection cancelled")
    if progress:
        progress("Running SoundOfSilence candidate scan")
    sos = _load_sos_module()
    config = sos.Config()
    config.WHISPER_MODEL_PATH = DEFAULT_SOS_MODEL_PATH
    config.WHISPER_PROFILE = "flexible"
    config.WHISPER_MODEL = "tiny.en"
    config.WHISPER_DEVICE = "cpu"
    config.WHISPER_COMPUTE_TYPE = "int8"
    config.SILENCE_THRESHOLD = "-30dB"
    config.SILENCE_DURATION = 2.5
    config.SNIPPET_DURATION = 5
    config.TARGET_NUMBERS_ONLY = numbers_only
    config.TARGET_FIRST_WORD_ONLY = True
    config.TARGET_WORDS = list(MARKER_WORDS)
    config.FILE_OUTPUT = False
    config.FILE_OUTPUT_TEXT = False
    config.TEXT_FIXUP = True
    config.TEST_RUN = False
    config.DEBUG = False
    sos.validate_ffmpeg_path(config)
    processor = sos.AudioProcessor(config)
    processor.timer.start_total()
    processor.setup_target_words()
    if not processor.initialize_whisper():
        raise RuntimeError("SoundOfSilence failed to initialize Whisper")
    if should_cancel and should_cancel():
        raise ChapterDetectionCancelled("Chapter detection cancelled")
    audio_list = processor.collect_audio_files(str(source))
    if not audio_list:
        raise RuntimeError(f"No audio files found: {source}")
    silences, chapters = processor.process_files(audio_list)
    duration = sum(processor.get_audio_duration(path) or 0.0 for path in audio_list)
    rows = [
        {
            "number": _number_from_sos_text(text),
            "text": text,
            "timestamp": hms(float(seconds)),
            "seconds": round(float(seconds), 3),
        }
        for text, _formatted, seconds in chapters
    ]
    return rows, duration, len(silences), _sos_rows_to_candidates(rows)


def _post_remote_asr_audio(
    endpoint: str,
    path: Path,
    *,
    model: str,
    compute_type: str,
) -> tuple[dict[str, Any], float]:
    boundary = f"----libraforge{time.time_ns()}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="{path.name}"\r\n'
        "Content-Type: audio/mpeg\r\n\r\n"
    ).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    query = urllib.parse.urlencode({"model": model, "compute_type": compute_type, "word_timestamps": "true"})
    url = f"{endpoint.rstrip('/')}/transcribe?{query}"
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=1800) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload, time.time() - started


def _remote_payload_to_segments(payload: dict[str, Any], offset: float) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    top_level_words = payload.get("words") or []
    for item in payload.get("segments", []):
        words = []
        segment_start = offset + float(item.get("start") or 0.0)
        segment_end = offset + float(item.get("end") or 0.0)
        segment_words = item.get("words") or [
            word for word in top_level_words
            if segment_start <= offset + float(word.get("start") or 0.0) <= segment_end
        ]
        for word in segment_words:
            words.append(
                {
                    "start": round(offset + float(word.get("start") or 0.0), 3),
                    "end": round(offset + float(word.get("end") or 0.0), 3),
                    "word": normalize_text(str(word.get("word") or word.get("text") or "")),
                    "probability": word.get("probability"),
                }
            )
        segments.append(
            TranscriptSegment(
                start=segment_start,
                end=segment_end,
                text=str(item.get("text") or ""),
                file="remote-focused-asr",
                words=words,
            )
        )
    return segments


def _focused_remote_asr_for_gaps(
    source_files: list[Path],
    candidates: list[ChapterCandidate],
    duration: float,
    *,
    endpoint: str,
    model_name: str,
    compute_type: str,
    max_gap_rescans: int,
    progress: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[list[ChapterCandidate], list[TranscriptSegment], list[dict[str, Any]], list[dict[str, Any]]]:
    gaps = sequence_gaps(candidates, duration)[:max(0, max_gap_rescans)]
    gaps = [
        SequenceGap(
            expected_number=gap.expected_number,
            start=0.0 if gap.reason == "missing-before-first" else gap.start,
            end=gap.end,
            reason=gap.reason,
        )
        for gap in gaps
    ]
    if not gaps:
        return candidates, [], [], []
    if progress:
        progress(f"Focused remote ASR for {len(gaps)} hybrid gap(s)")
    clips, temp_dir, labels, offsets, _expected = make_focus_clips(source_files, gaps)
    focused_segments: list[TranscriptSegment] = []
    focused_runs: list[dict[str, Any]] = []
    if not clips:
        return candidates, focused_segments, focused_runs, annotate_unresolved_gaps(candidates, duration)
    try:
        for clip in clips:
            if should_cancel and should_cancel():
                raise ChapterDetectionCancelled("Chapter detection cancelled")
            offset = offsets.get(str(clip), 0.0)
            expected = _expected.get(str(clip))
            if progress:
                progress(f"Transcribing focused hybrid window for Chapter {expected}")
            started = time.time()
            row = {
                "status": "running",
                "expected_number": expected,
                "window_start": round(offset, 3),
                "source_file": labels.get(str(clip), ""),
                "model": model_name,
                "compute_type": compute_type,
            }
            focused_runs.append(row)
            try:
                payload, elapsed = _post_remote_asr_audio(
                    endpoint,
                    clip,
                    model=model_name,
                    compute_type=compute_type,
                )
                segments = _remote_payload_to_segments(payload, offset)
                focused_segments.extend(segments)
                row.update(
                    {
                        "status": "completed",
                        "elapsed_seconds": round(elapsed, 3),
                        "total_elapsed_seconds": round(time.time() - started, 3),
                        "text_preview": normalize_text(str(payload.get("text") or ""))[:1000],
                        "chapter_text_hits": [
                            {
                                "start": round(segment.start, 3),
                                "end": round(segment.end, 3),
                                "text": normalize_text(segment.text)[:320],
                            }
                            for segment in segments
                            if "chapter" in segment.text.lower()
                        ][:20],
                    }
                )
            except Exception as exc:
                row.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        rescan_candidates = validate_sequence(dedupe_candidates(find_marker_candidates(focused_segments)))
        for candidate in rescan_candidates:
            candidate.reasons.append("hybrid-focused-asr")
            candidate.confidence = min(0.98, candidate.confidence + 0.14)
        merged = merge_rescan_candidates(candidates, rescan_candidates, gaps)
        correct_obvious_sequence_misreads(merged)
        for row in focused_runs:
            expected = row.get("expected_number")
            matches = [
                candidate for candidate in merged
                if expected and candidate.number == expected
                and float(row.get("window_start") or 0.0) <= candidate.start <= float(row.get("window_start") or 0.0) + 3600.0
            ]
            row["candidates"] = [
                {
                    "start": round(candidate.start, 3),
                    "timestamp": hms(candidate.start),
                    "number": candidate.number,
                    "title": candidate.title,
                    "source_text": candidate.source_text[:320],
                    "confidence": round(candidate.confidence, 3),
                }
                for candidate in matches
            ]
        return merged, focused_segments, focused_runs, annotate_unresolved_gaps(merged, duration)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _remote_asr_for_chapter_evidence(
    source_files: list[Path],
    chapters: list[dict[str, Any]],
    duration: float,
    *,
    endpoint: str,
    model_name: str,
    compute_type: str,
    before_seconds: float = 30.0,
    after_seconds: float = 30.0,
    progress: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[list[TranscriptSegment], list[dict[str, Any]]]:
    if not chapters:
        return [], []
    if progress:
        progress(f"Transcribing evidence context for {len(chapters)} chapter(s)")

    def _window_for(chapter: dict[str, Any]) -> tuple[float, float]:
        start = float(chapter.get("start") or 0.0)
        # Opening/End Credits are synthesized with a known, often-longer span
        # (the full "written by ... narrated by ..." announcement); the fixed
        # before/after window used for ordinary chapter markers was truncating
        # names mid-word, so give these two rows their full extent instead.
        marker_kind = chapter.get("marker_kind")
        if marker_kind == "Opening Credits":
            return 0.0, min(duration, float(chapter.get("end") or start) + CREDITS_EVIDENCE_BUFFER_SECONDS)
        if marker_kind == "End Credits":
            return max(0.0, start - CREDITS_EVIDENCE_BUFFER_SECONDS), duration
        return max(0.0, start - before_seconds), min(duration, start + after_seconds)

    windows = [
        SequenceGap(
            expected_number=int(chapter.get("number") or chapter.get("id") or index),
            start=_window_for(chapter)[0],
            end=_window_for(chapter)[1],
            reason="chapter-evidence-context",
        )
        for index, chapter in enumerate(chapters, start=1)
    ]
    clips, temp_dir, labels, offsets, expected = make_focus_clips(source_files, windows, accurate_seek=True)
    evidence_segments: list[TranscriptSegment] = []
    evidence_runs: list[dict[str, Any]] = []
    if not clips:
        return evidence_segments, evidence_runs
    try:
        for clip in clips:
            if should_cancel and should_cancel():
                raise ChapterDetectionCancelled("Chapter detection cancelled")
            offset = offsets.get(str(clip), 0.0)
            chapter_number = expected.get(str(clip))
            if progress:
                progress(f"Transcribing evidence context for Chapter {chapter_number}")
            started = time.time()
            row = {
                "status": "running",
                "chapter_number": chapter_number,
                "window_start": round(offset, 3),
                "window_end": round(offset + ffprobe_duration(clip), 3),
                "source_file": labels.get(str(clip), ""),
                "model": model_name,
                "compute_type": compute_type,
            }
            evidence_runs.append(row)
            try:
                payload, elapsed = _post_remote_asr_audio(
                    endpoint,
                    clip,
                    model=model_name,
                    compute_type=compute_type,
                )
                segments = _remote_payload_to_segments(payload, offset)
                evidence_segments.extend(segments)
                row.update(
                    {
                        "status": "completed",
                        "elapsed_seconds": round(elapsed, 3),
                        "total_elapsed_seconds": round(time.time() - started, 3),
                        "segment_count": len(segments),
                        "text_preview": normalize_text(str(payload.get("text") or ""))[:1200],
                    }
                )
            except Exception as exc:
                row.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        return evidence_segments, evidence_runs
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _extract_json_object(raw: str, key: str) -> dict[str, Any] | None:
    """Best-effort recovery of one top-level `"key": {...}` object out of a
    JSON string that failed to parse as a whole. Ollama's num_predict cap
    truncates long responses mid-document (a book needing many
    accepted_corrections runs out of room), but an earlier field like
    credits_check is usually still complete in the raw text even though the
    document as a whole isn't -- this recovers just that field via brace
    matching instead of losing it along with the truncated tail.
    """
    marker = f'"{key}":'
    marker_pos = raw.find(marker)
    if marker_pos == -1:
        return None
    brace_start = raw.find("{", marker_pos)
    if brace_start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(brace_start, len(raw)):
        char = raw[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[brace_start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _call_ollama_json(endpoint: str, model: str, prompt: str) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 4096},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read().decode("utf-8"))
    raw = data.get("response") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        parsed = {"parse_error": str(exc), "raw_response": raw}
        recovered_credits_check = _extract_json_object(raw, "credits_check")
        if recovered_credits_check is not None:
            parsed["credits_check"] = recovered_credits_check
    parsed["_ollama_duration_seconds"] = round(time.time() - started, 3)
    parsed["_model"] = model
    return parsed


HYBRID_LLM_REVIEW_INSTRUCTIONS = (
    "You are the text-only parser/reviewer in a cascade audiobook chapter detection pipeline. "
    "STT means speech-to-text; audio has already been transcribed. "
    "Review only the supplied text evidence. Prefer focused ASR evidence over noisy SoS snippets. "
    "Do not invent timestamps or names. Do not output every chapter. "
    "Do not claim a chapter is missing if it appears in chapters_under_review or focused_asr_evidence. "
    "Only emit corrections that affect chapter identity, number parsing, or obvious repeated ASR garbage. "
    "A title is bled narrative text, not a real chapter name, when it runs on past the marker into "
    'ordinary prose (for example "Chapter 3 the darkness disappeared and ruin stood on a cliff") -- '
    'flag these with action "clean_title" and a title trimmed to just the marker and number '
    '(for example "Chapter 3"), not a rewritten summary. Only do this when the source_text clearly '
    "shows narration continuing past the marker; do not clean_title a genuinely spoken chapter name. "
    "The \"Book data\" JSON further below is INPUT ONLY, for you to analyze -- never copy its key names "
    "(book, chapter_count, focused_asr_evidence, etc.) into your response. "
    "Return JSON only, matching only this OUTPUT shape: "
    '{"assessment":"clean|resolved_by_focused_asr|needs_manual_review|poor","confidence":"low|medium|high",'
    '"accepted_corrections":[{"action":"add_missing_chapter|correct_number|clean_title|keep",'
    '"number":1,"timestamp":"HH:MM:SS","title":"supported title","evidence":"short supplied text","reason":"short"}],'
    '"unresolved_issues":[{"type":"missing_chapter|parse_error|title_noise|sequence_conflict|needs_audio",'
    '"severity":"low|medium|high","details":"short","recommended_action":"short"}],'
    '"validator_rules_to_apply":["short deterministic rule"],"notes":["short note"]}.'
)

# A dedicated, minimal prompt for the author/narrator credits cross-check --
# deliberately NOT folded into HYBRID_LLM_REVIEW_INSTRUCTIONS's shared prompt.
# Live-tested against real books: a large "clean" book (35 chapters, nothing
# needing correction, so the full chapter list is sent verbatim) pushed the
# combined review prompt to ~21K chars, and the model's response degraded
# into echoing input field names instead of following the output schema --
# a context-pressure failure distinct from and in addition to the num_predict
# truncation that can drop a late field from a long corrections list. Keeping
# this check on its own short prompt makes it immune to both: its size never
# grows with the book's chapter count or correction count.
CREDITS_CHECK_LLM_INSTRUCTIONS = (
    "You are cross-checking an audiobook's known author/narrator credits against a rough "
    "speech-to-text transcript of its spoken Opening Credits announcement. STT frequently mangles names "
    '(phonetic misspellings, wrong casing, merged or split words, e.g. "Boultrie" for "Baldree", "AFK" '
    "for \"A. F. Kay\"). Judge whether the evidence plausibly names the same author/narrator despite "
    "that -- don't require an exact string match. "
    "The input data below is INPUT ONLY -- never copy its key names into your response. author_tag and "
    "narrator_tag in your response must be copied verbatim from the known_author/known_narrator values "
    "given in the input, never the placeholder text shown in the shape below. "
    "Return JSON only, matching exactly this shape: "
    '{"credits_check":{"author_match":"match|mismatch|uncertain","author_tag":"<verbatim known_author value>",'
    '"author_evidence":"the phrase in opening_credits_evidence that supports this","narrator_match":"match|mismatch|uncertain",'
    '"narrator_tag":"<verbatim known_narrator value>","narrator_evidence":"the phrase in opening_credits_evidence that supports this"}}.'
)


def _build_credits_check_prompt(known_author: str, known_narrator: str, opening_credits_evidence: str) -> str:
    payload = {
        "known_author": known_author,
        "known_narrator": known_narrator,
        "opening_credits_evidence": opening_credits_evidence,
    }
    return f"{CREDITS_CHECK_LLM_INSTRUCTIONS} Input data: {json.dumps(payload, ensure_ascii=False)}"


def _build_hybrid_llm_prompt(
    result: dict[str, Any],
    extra_instructions: str = "",
) -> str:
    all_chapters = [
        {
            "id": chapter.get("id"),
            "timestamp": hms(float(chapter.get("start") or 0.0)),
            "number": chapter.get("number"),
            "title": chapter.get("title"),
            "source_text": normalize_text(str(chapter.get("source_text") or ""))[:240],
            "reasons": chapter.get("reasons", []),
        }
        for chapter in result.get("chapters", [])
    ]
    focus_numbers = {
        run.get("expected_number")
        for run in result.get("hybrid", {}).get("focused_runs", [])
        if run.get("expected_number")
    }
    review_numbers = {
        item.get("expected_number")
        for item in result.get("sequence_review", [])
        if item.get("expected_number")
    } | focus_numbers
    if len(all_chapters) > 60 and review_numbers:
        chapters = [
            chapter for chapter in all_chapters
            if chapter.get("number") in review_numbers
            or chapter.get("number") in {number - 1 for number in review_numbers}
            or chapter.get("number") in {number + 1 for number in review_numbers}
        ][:40]
    elif len(all_chapters) > 60:
        chapters = all_chapters[:8] + all_chapters[-8:]
    else:
        chapters = all_chapters
    focused = []
    for run in result.get("hybrid", {}).get("focused_runs", []):
        focused.append(
            {
                "expected_number": run.get("expected_number"),
                "status": run.get("status"),
                "candidates": run.get("candidates", []),
                "chapter_text_hits": run.get("chapter_text_hits", [])[:6],
                "text_preview": normalize_text(str(run.get("text_preview") or ""))[:650],
            }
        )
    payload = {
        "book": Path(result.get("source_path", "book")).name,
        "clean_path": not result.get("sequence_review"),
        "sequence_review": result.get("sequence_review", []),
        "chapters_under_review": chapters,
        "chapter_count": len(all_chapters),
        "focused_asr_evidence": focused,
    }
    extra_block = ""
    if extra_instructions and extra_instructions.strip():
        extra_block = f" Additional reviewer instructions from the user: {extra_instructions.strip()}"
    return (
        f"{HYBRID_LLM_REVIEW_INSTRUCTIONS}{extra_block} "
        f"Book data: {json.dumps(payload, ensure_ascii=False)}"
    )


def _apply_llm_chapter_corrections(result: dict[str, Any], review: dict[str, Any]) -> None:
    chapters = result.get("chapters", [])
    applied: list[dict[str, Any]] = []
    for correction in review.get("accepted_corrections", [])[:8]:
        action = correction.get("action")
        number = correction.get("number")
        timestamp = correction.get("timestamp")
        title = normalize_text(str(correction.get("title") or ""))
        if not isinstance(number, int) or not timestamp or not title:
            continue
        ts = _stamp_to_seconds(str(timestamp))
        best = None
        best_delta = math.inf
        for chapter in chapters:
            if chapter.get("number") != number:
                continue
            delta = abs(float(chapter.get("start") or 0.0) - ts)
            if delta < best_delta:
                best = chapter
                best_delta = delta
        if best and best_delta <= 8.0 and action in {"correct_number", "clean_title", "add_missing_chapter", "keep"}:
            old_title = best.get("title")
            best["title"] = title
            reasons = list(best.get("reasons") or [])
            if "llm-reviewed-title" not in reasons:
                reasons.append("llm-reviewed-title")
            best["reasons"] = reasons
            best["llm_evidence"] = correction.get("evidence", "")
            applied.append({"number": number, "timestamp": timestamp, "old_title": old_title, "new_title": title})
    result.setdefault("hybrid", {})["llm_applied_corrections"] = applied


def _stamp_to_seconds(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        return 0.0
    return (int(parts[0]) * 3600) + (int(parts[1]) * 60) + float(parts[2])


def detect_chapters_hybrid(
    source: Path,
    *,
    remote_endpoint: str = DEFAULT_REMOTE_ASR_ENDPOINT,
    focused_model_name: str = "medium",
    focused_compute_type: str = "float16",
    max_gap_rescans: int = 8,
    silence_snap: bool = True,
    silence_window: float = 4.0,
    silence_marker_lead_seconds: float = 1.0,
    llm_review: bool = False,
    llm_endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    llm_model: str = "gemma4:latest",
    llm_extra_instructions: str = "",
    sos_numbers_only: bool = False,
    progress: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    original_files = audio_files(source)
    if not original_files:
        raise RuntimeError("No supported audio files found")
    rows, duration, silence_count, candidates = _run_sound_of_silence(
        source,
        numbers_only=sos_numbers_only,
        progress=progress,
        should_cancel=should_cancel,
    )
    sequence_review = annotate_unresolved_gaps(candidates, duration)
    focused_segments: list[TranscriptSegment] = []
    focused_runs: list[dict[str, Any]] = []
    if sequence_review and max_gap_rescans > 0:
        candidates, focused_segments, focused_runs, sequence_review = _focused_remote_asr_for_gaps(
            original_files,
            candidates,
            duration,
            endpoint=remote_endpoint or DEFAULT_REMOTE_ASR_ENDPOINT,
            model_name=focused_model_name or "medium",
            compute_type=focused_compute_type or "float16",
            max_gap_rescans=max_gap_rescans,
            progress=progress,
            should_cancel=should_cancel,
        )
    silences: list[tuple[float, float]] = []
    if silence_snap and candidates:
        if progress:
            progress("Snapping hybrid markers to silence")
        silences = detect_silences(original_files, source_file_offsets(original_files))
        snap_to_silence(
            candidates,
            silences,
            window=silence_window,
            marker_lead_seconds=silence_marker_lead_seconds,
        )
    chapters = finalize_chapters(candidates, duration, silences)
    evidence_segments_remote, evidence_runs = _remote_asr_for_chapter_evidence(
        original_files,
        chapters,
        duration,
        endpoint=remote_endpoint or DEFAULT_REMOTE_ASR_ENDPOINT,
        model_name=focused_model_name or "medium",
        compute_type=focused_compute_type or "float16",
        before_seconds=10.0,
        after_seconds=10.0,
        progress=progress,
        should_cancel=should_cancel,
    )
    sos_evidence_segments = [
        TranscriptSegment(
            start=float(row.get("seconds") or 0.0),
            end=float(row.get("seconds") or 0.0) + 5.0,
            text=str(row.get("text") or ""),
            file="sound-of-silence",
        )
        for row in rows
    ]
    evidence_segments = (focused_segments + evidence_segments_remote) if evidence_segments_remote else (sos_evidence_segments + focused_segments)
    enrich_chapter_evidence(chapters, evidence_segments, silences, before_seconds=35.0, after_seconds=35.0)
    result = {
        "schema_version": 1,
        "source_path": str(source),
        "audio_files": [str(path) for path in original_files],
        "duration": round(duration, 3),
        "settings": {
            "backend": "hybrid-sos-focused",
            "remote_endpoint": remote_endpoint,
            "focused_model": focused_model_name,
            "focused_compute_type": focused_compute_type,
            "max_gap_rescans": max_gap_rescans,
            "silence_snap": silence_snap,
            "silence_window": silence_window,
            "silence_marker_lead_seconds": silence_marker_lead_seconds,
            "llm_review": llm_review,
            "llm_endpoint": llm_endpoint,
            "llm_model": llm_model,
            "llm_extra_instructions": llm_extra_instructions,
        },
        "chapters": chapters,
        "segments": [asdict(segment) for segment in focused_segments + evidence_segments_remote],
        "silences": [{"start": round(s, 3), "end": round(e, 3)} for s, e in silences],
        "sequence_review": sequence_review,
        "hybrid": {
            "sos_rows": rows,
            "sos_silence_count": silence_count,
            "focused_runs": focused_runs,
            "evidence_runs": evidence_runs,
        },
    }
    if llm_review:
        if progress:
            progress(f"Reviewing hybrid chapters with {llm_model}")
        try:
            review = _call_ollama_json(
                llm_endpoint or DEFAULT_OLLAMA_ENDPOINT,
                llm_model or "gemma4:latest",
                _build_hybrid_llm_prompt(result, llm_extra_instructions),
            )
        except Exception as exc:
            review = {
                "assessment": "llm_unavailable",
                "confidence": "low",
                "accepted_corrections": [],
                "unresolved_issues": [
                    {
                        "type": "llm_review_failed",
                        "severity": "medium",
                        "details": f"{type(exc).__name__}: {exc}",
                        "recommended_action": "Verify the LLM endpoint is reachable, or rerun with LLM review disabled.",
                    }
                ],
                "validator_rules_to_apply": [],
                "notes": ["Chapter detection completed, but optional LLM review did not run."],
                "_model": llm_model or "gemma4:latest",
                "_endpoint": llm_endpoint or DEFAULT_OLLAMA_ENDPOINT,
                "_error": f"{type(exc).__name__}: {exc}",
            }
            if progress:
                progress(f"LLM review unavailable; saving chapters without AI corrections ({type(exc).__name__})")
        opening_credits_chapter = next(
            (chapter for chapter in chapters if chapter.get("marker_kind") == "Opening Credits"),
            None,
        )
        book_credits = resolve_book_credits(source)
        if opening_credits_chapter and (book_credits.get("author") or book_credits.get("narrator")):
            if progress:
                progress(f"Cross-checking author/narrator credits with {llm_model}")
            try:
                credits_review = _call_ollama_json(
                    llm_endpoint or DEFAULT_OLLAMA_ENDPOINT,
                    llm_model or "gemma4:latest",
                    _build_credits_check_prompt(
                        book_credits.get("author", ""),
                        book_credits.get("narrator", ""),
                        normalize_text(str(opening_credits_chapter.get("source_text") or ""))[:400],
                    ),
                )
                if credits_review.get("credits_check"):
                    review["credits_check"] = credits_review["credits_check"]
            except Exception:
                pass
        result["hybrid"]["llm_review"] = review
        if not review.get("parse_error"):
            _apply_llm_chapter_corrections(result, review)
            result["chapters"] = finalize_chapters(
                [
                    ChapterCandidate(
                        start=float(chapter["start"]),
                        original_start=float(chapter.get("original_start", chapter["start"])),
                        end=float(chapter["end"]),
                        title=str(chapter["title"]),
                        marker_kind=str(chapter.get("marker_kind") or "Chapter"),
                        number=chapter.get("number"),
                        confidence=float(chapter.get("confidence") or 0.0),
                        reasons=list(chapter.get("reasons") or []),
                        source_text=str(chapter.get("source_text") or ""),
                        source_file=str(chapter.get("source_file") or ""),
                    )
                    for chapter in result["chapters"]
                ],
                duration,
            )
            enrich_chapter_evidence(result["chapters"], evidence_segments, silences, before_seconds=35.0, after_seconds=35.0)
    return result


def cue_timecode(seconds: float) -> str:
    """mm:ss:mmm as expected by the CUE INDEX field (no hours component)."""
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms -= 1000
    minutes, sec = divmod(whole, 60)
    return f"{minutes:02}:{sec:02}:{ms:03}"


def write_cue(chapters: list[dict[str, Any]], file_name: str = "audiobook") -> str:
    lines = [f'FILE "{file_name}" MP3']
    for chapter in chapters:
        lines.append(f"TRACK {int(chapter['id']):02d} AUDIO")
        lines.append(f'  TITLE "{chapter.get("title", "")}"')
        lines.append(f"  INDEX 01 {cue_timecode(float(chapter.get('start', 0.0)))}")
    return "\n".join(lines) + "\n"


def _companion_path(source: Path, shared_name: str, loose_suffix: str) -> Path:
    """Resolve a companion-file path for `source`: books living alone in
    their own folder share one file named `shared_name`; an audio file
    sharing a folder with siblings gets its own `<file><loose_suffix>` file
    next to it instead.
    """
    if source.is_dir():
        return source / shared_name
    folder = source.parent
    audio_count = len([path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS])
    if audio_count <= 1:
        return folder / shared_name
    return source.with_name(source.name + loose_suffix)


def chapter_sidecar_path(source: Path) -> Path:
    return _companion_path(source, "libraforge.json", ".libraforge.json")


def metadata_json_path(source: Path) -> Path:
    return _companion_path(source, "metadata.json", ".metadata.json")


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_book_credits(source: Path) -> dict[str, str]:
    """Author/narrator to cross-check against an Opening Credits reading --
    same fallback chain as resolve_asin_for_chaptering() in app/main.py:
    the sidecar's curated book.author/book.narrator first, then the sibling
    Audiobookshelf metadata.json's authors/narrators lists.
    """
    sidecar = _read_json_file(chapter_sidecar_path(source))
    if "sidecar" in sidecar and isinstance(sidecar["sidecar"], dict):
        sidecar = sidecar["sidecar"]
    book = sidecar.get("book", {}) or {}
    author = str(book.get("author") or "").strip()
    narrator = str(book.get("narrator") or "").strip()
    if not author or not narrator:
        metadata = _read_json_file(metadata_json_path(source))
        if not author:
            author = ", ".join(str(a).strip() for a in (metadata.get("authors") or []) if str(a).strip())
        if not narrator:
            narrator = ", ".join(str(n).strip() for n in (metadata.get("narrators") or []) if str(n).strip())
    return {"author": author, "narrator": narrator}


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_chapter_review_report(source: Path, result: dict[str, Any]) -> Path | None:
    review = (result.get("hybrid") or {}).get("llm_review")
    if not isinstance(review, dict) or not review:
        return None
    path = result_paths(source)["ai_review"]
    lines = [
        "# Chapter Forge AI Review",
        "",
        f"Source: `{source}`",
        f"Model: `{review.get('_model', '-')}`",
        f"Assessment: `{review.get('assessment', '-')}`",
        f"Confidence: `{review.get('confidence', '-')}`",
        f"Runtime: `{review.get('_ollama_duration_seconds', '-')} sec`",
        "",
        "## Accepted Corrections",
        "",
    ]
    corrections = review.get("accepted_corrections") or []
    if not corrections:
        lines.append("- None.")
    for item in corrections:
        lines.append(
            f"- `{item.get('action')}` chapter {item.get('number')} at `{item.get('timestamp')}`: "
            f"{item.get('title') or ''}. Evidence: {item.get('evidence') or ''}"
        )
    lines.extend(["", "## Unresolved Issues", ""])
    issues = review.get("unresolved_issues") or []
    if not issues:
        lines.append("- None.")
    for item in issues:
        lines.append(
            f"- `{item.get('type')}` / `{item.get('severity')}`: "
            f"{item.get('details') or ''} Action: {item.get('recommended_action') or ''}"
        )
    lines.extend(["", "## Validator Rules", ""])
    rules = review.get("validator_rules_to_apply") or []
    if not rules:
        lines.append("- None.")
    for rule in rules:
        lines.append(f"- {rule}")
    lines.extend(["", "## Notes", ""])
    notes = review.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    if not notes:
        lines.append("- None.")
    for note in notes:
        lines.append(f"- {note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def result_paths(source: Path, variant: str = "") -> dict[str, Path]:
    folder = source if source.is_dir() else source.parent
    stem = source.name if source.is_file() else source.name
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" .") or "chapters"
    if variant:
        safe_variant = re.sub(r"[^A-Za-z0-9._ -]+", "_", variant).strip(" .")
        if safe_variant:
            safe_stem = f"{safe_stem}.{safe_variant}"
    return {
        "sidecar": chapter_sidecar_path(source),
        "srt": folder / f"{safe_stem}.libraforge-chapters.srt",
        "transcript": folder / f"{safe_stem}.libraforge-transcript.txt",
        "cue": folder / f"{safe_stem}.libraforge-chapters.cue",
        "ai_review": folder / f"{safe_stem}.libraforge-ai-review.md",
    }


def save_result(source: Path, payload: dict[str, Any], srt: str = "", transcript: str = "") -> dict[str, str]:
    max_audio_seconds = float((payload.get("settings") or {}).get("max_audio_seconds") or 0.0)
    variant = f"preview-{round(max_audio_seconds / 60)}min" if max_audio_seconds > 0 else ""
    paths = result_paths(source, variant=variant)
    sidecar = _read_json_file(paths["sidecar"])
    sidecar["chapter_forge"] = payload
    sidecar.setdefault("schema_version", 1)
    _write_json_file(paths["sidecar"], sidecar)
    if srt:
        paths["srt"].write_text(srt, encoding="utf-8")
    if transcript:
        paths["transcript"].write_text(transcript, encoding="utf-8")
    paths["cue"].write_text(write_cue(payload.get("chapters", []), source.name), encoding="utf-8")
    review_path = write_chapter_review_report(source, payload)
    if review_path is not None:
        paths["ai_review"] = review_path
    return {key: str(path) for key, path in paths.items() if path.exists()}


def load_existing_result(source: Path) -> dict[str, Any] | None:
    paths = result_paths(source)
    sidecar = _read_json_file(paths["sidecar"])
    chapter_forge = sidecar.get("chapter_forge")
    if isinstance(chapter_forge, dict):
        return chapter_forge
    return None


def detect_chapters(
    source: Path,
    *,
    model_name: str = "large-v3",
    device: str = "auto",
    compute_type: str = "int8",
    cpu_threads: int = 0,
    vad_filter: bool = True,
    language: str = "en",
    condition_on_previous_text: bool = False,
    beam_size: int = 1,
    silence_snap: bool = True,
    silence_window: float = 4.0,
    silence_marker_lead_seconds: float = 1.0,
    stable_ts: bool = False,
    max_audio_seconds: float = 0.0,
    chunk_seconds: float = 1200.0,
    focused_rescan: bool = True,
    focused_model_name: str = "",
    focused_compute_type: str = "",
    focused_beam_size: int = 5,
    max_gap_rescans: int = 8,
    progress: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if should_cancel and should_cancel():
        raise ChapterDetectionCancelled("Chapter detection cancelled")
    if stable_ts:
        # Placeholder hook: stable-ts can replace/augment timestamps later while
        # preserving the detector contract and UI payload.
        try:
            import stable_whisper  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("stable-ts was requested but stable_whisper is not installed") from exc

    original_files = audio_files(source)
    if not original_files:
        raise RuntimeError("No supported audio files found")
    if should_cancel and should_cancel():
        raise ChapterDetectionCancelled("Chapter detection cancelled")
    files, temp_dir, source_labels = limited_audio_files(
        original_files,
        max_audio_seconds,
        chunk_seconds=chunk_seconds,
    )
    try:
        segments, duration, offsets = transcribe_faster_whisper(
            files,
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            vad_filter=vad_filter,
            language=language,
            condition_on_previous_text=condition_on_previous_text,
            beam_size=beam_size,
            progress=progress,
            should_cancel=should_cancel,
            source_labels=source_labels,
        )
        if should_cancel and should_cancel():
            raise ChapterDetectionCancelled("Chapter detection cancelled")
        if progress:
            progress("Detecting chapter markers")
        candidates = validate_sequence(dedupe_candidates(find_marker_candidates(segments)))
        correct_obvious_sequence_misreads(candidates)
        sequence_review = annotate_unresolved_gaps(candidates, duration)
        if focused_rescan and sequence_review and max_audio_seconds <= 0:
            if should_cancel and should_cancel():
                raise ChapterDetectionCancelled("Chapter detection cancelled")
            candidates, sequence_review = rescan_sequence_gaps(
                original_files,
                candidates,
                duration,
                model_name=focused_model_name.strip() or model_name,
                device=device,
                compute_type=focused_compute_type.strip() or compute_type,
                cpu_threads=cpu_threads,
                vad_filter=vad_filter,
                language=language,
                condition_on_previous_text=condition_on_previous_text,
                beam_size=focused_beam_size,
                max_gap_rescans=max_gap_rescans,
                progress=progress,
                should_cancel=should_cancel,
            )
        silences: list[tuple[float, float]] = []
        if silence_snap and candidates:
            if should_cancel and should_cancel():
                raise ChapterDetectionCancelled("Chapter detection cancelled")
            if progress:
                progress("Snapping markers to silence")
            silences = detect_silences(files, offsets)
            if should_cancel and should_cancel():
                raise ChapterDetectionCancelled("Chapter detection cancelled")
            snap_to_silence(
                candidates,
                silences,
                window=silence_window,
                marker_lead_seconds=silence_marker_lead_seconds,
            )
        chapters = finalize_chapters(candidates, duration, silences)
        enrich_chapter_evidence(chapters, segments, silences)
        return {
            "schema_version": 1,
            "source_path": str(source),
            "audio_files": [str(path) for path in original_files],
            "duration": round(duration, 3),
            "settings": {
                "backend": "faster-whisper",
                "model": model_name,
                "device": device,
                "compute_type": compute_type,
                "cpu_threads": cpu_threads,
                "vad_filter": vad_filter,
                "language": language,
                "condition_on_previous_text": condition_on_previous_text,
                "beam_size": beam_size,
                "silence_snap": silence_snap,
                "silence_window": silence_window,
                "silence_marker_lead_seconds": silence_marker_lead_seconds,
                "stable_ts": stable_ts,
                "max_audio_seconds": max_audio_seconds,
                "chunk_seconds": chunk_seconds,
                "focused_rescan": focused_rescan,
                "focused_model": focused_model_name.strip() or model_name,
                "focused_compute_type": focused_compute_type.strip() or compute_type,
                "focused_beam_size": focused_beam_size,
                "max_gap_rescans": max_gap_rescans,
            },
            "chapters": chapters,
            "segments": [asdict(segment) for segment in segments],
            "silences": [{"start": round(s, 3), "end": round(e, 3)} for s, e in silences],
            "sequence_review": sequence_review,
        }
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
