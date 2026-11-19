"""Audiobookshelf's author-name parser, ported to Python.

Folder Forge uses this to stay aligned with how Audiobookshelf reads an author
folder name: which text it treats as separate authors, and how it splits one
name into first and last parts. It runs on its own; nothing here calls
Audiobookshelf.

Ported from the Audiobookshelf repository (GPL-3.0), release v2.37.2, which is
identical to 2.35.1 for these two files:
  server/utils/parsers/parseNameString.js  -> parse_name_string()
  server/utils/parsers/parseFullName.js    -> parse_full_name()
parseFullName.js is Audiobookshelf's copy of the npm package parse-full-name
(MIT, https://github.com/RateGravity/parse-full-name). See THIRD_PARTY_NOTICES.md.

The code follows the JavaScript line for line, quirks included, so the two can
be compared by eye. app/tests/fixtures/abs_name_parse.json holds what the real
parser returns (regenerate with tools/abs_name_fixture.js after an
Audiobookshelf update) and app/tests/test_abs_names.py checks the port against
it. No other module should re-implement name splitting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FullName:
    title: str = ""
    first: str = ""
    middle: str = ""
    last: str = ""
    nick: str = ""
    suffix: str = ""


# parseFullName.js, short lists (useLongLists is off as Audiobookshelf calls it).
_CONJUNCTION_LIST = ["&", "and", "et", "e", "of", "the", "und", "y"]
_SUFFIX_LIST = ["esq", "esquire", "jr", "jnr", "sr", "snr", "2", "ii", "iii", "iv",
                "md", "phd", "j.d.", "ll.m.", "m.d.", "d.o.", "d.c.", "p.c.", "ph.d."]
_PREFIX_LIST = ["ab", "bar", "bin", "da", "dal", "de", "de la", "del", "della", "der",
                "di", "du", "ibn", "l'", "la", "le", "san", "st", "st.", "ste", "ter", "van",
                "van de", "van der", "van den", "vel", "ver", "vere", "von"]
_TITLE_LIST = ["dr", "miss", "mr", "mrs", "ms", "prof", "sir", "frau", "herr", "hr",
               "monsieur", "captain", "doctor", "judge", "officer", "professor", "ind", "misc",
               "mx"]
_FORCE_CASE_LIST = ["e", "y", "av", "af", "da", "dal", "de", "del", "der", "di",
                    "la", "le", "van", "der", "den", "vel", "von", "II", "III", "IV", "J.D.", "LL.M.",
                    "M.D.", "D.O.", "D.C.", "Ph.D."]
_FORCE_CASE_LOWER = [v.lower() for v in _FORCE_CASE_LIST]
_PART_LABELS = ["title", "first", "middle", "last", "nick", "suffix"]
_NICKNAME_RE = re.compile(r"""\s(?:[‘’']([^‘’']+)[‘’']|[“”"]([^“”"]+)[“”"]|\[([^\]]+)\]|\(([^\)]+)\)),?\s""")
_CJK_RE = re.compile("[一-鿿぀-ヿㇰ-ㇿ]")


def _index_of(items: list, value) -> int:
    """JavaScript Array.prototype.indexOf."""
    try:
        return items.index(value)
    except ValueError:
        return -1


def _splice(items: list, start: int, count: int) -> list:
    """JavaScript Array.prototype.splice(start, count) for start >= 0: removes
    and returns the items; out-of-range positions remove nothing."""
    removed = items[start:start + count]
    del items[start:start + count]
    return removed


def _fix_parsed_name_case(parsed: dict[str, str], fix_case_now: int) -> dict[str, str]:
    if fix_case_now:
        for label in _PART_LABELS:
            if parsed[label]:
                words = str(parsed[label]).split(" ")
                for j, word in enumerate(words):
                    force_index = _index_of(_FORCE_CASE_LOWER, word.lower())
                    if force_index > -1:  # Set case of words in forceCaseList
                        words[j] = _FORCE_CASE_LIST[force_index]
                    elif len(word) == 1:  # Uppercase initials
                        words[j] = word.upper()
                    elif (
                        len(word) > 2
                        and word[0:1] == word[0:1].upper()
                        and word[1:2] == word[1:2].lower()
                        and word[2:] == word[2:].upper()
                    ):  # Detect McCASE and convert to McCase
                        words[j] = word[0:3] + word[3:].lower()
                    elif (
                        # Upstream compares namePartLabels[j] (the word index, not
                        # the label index) and !indexOf (true only for "esq"); kept as is.
                        j < len(_PART_LABELS) and _PART_LABELS[j] == "suffix"
                        and word[-1:] != "."
                        and not _index_of(_SUFFIX_LIST, word.lower())
                    ):  # Convert suffix abbreviations to UPPER CASE
                        if word == word.lower():
                            words[j] = word.upper()
                    else:  # Convert to Title Case
                        words[j] = word[0:1].upper() + word[1:].lower()
                parsed[label] = " ".join(words)
    return parsed


def _finish(parsed: dict[str, str], fix_case: int) -> FullName:
    parsed = _fix_parsed_name_case(parsed, fix_case)
    return FullName(**parsed)


def parse_full_name(name: str) -> FullName:
    """parseFullName(name) with Audiobookshelf's default arguments
    (fixCase=-1: fix case only when the input is all upper or all lower case)."""
    parsed = {"title": "", "first": "", "middle": "", "last": "", "nick": "", "suffix": ""}
    fix_case = -1
    if not name or not isinstance(name, str):
        return _finish(parsed, fix_case)
    name_to_parse = name.strip()

    if fix_case == -1:
        fix_case = 1 if (name_to_parse == name_to_parse.upper() or name_to_parse == name_to_parse.lower()) else 0

    # Nickname: remove and store parts with surrounding punctuation as nicknames
    parts_found = [m.group(0) for m in _NICKNAME_RE.finditer(" " + name_to_parse + " ")]
    if len(parts_found) == 1:
        nick = parts_found[0][2:][:-2]
        if nick[-1:] == ",":
            nick = nick[:-1]
        parsed["nick"] = nick
        name_to_parse = (" " + name_to_parse + " ").replace(parts_found[0], " ", 1).strip()
        parts_found = []
    elif len(parts_found) > 1:
        for i in range(len(parts_found)):
            name_to_parse = (" " + name_to_parse + " ").replace(parts_found[i], " ", 1).strip()
            parts_found[i] = parts_found[i][2:][:-2]
            if parts_found[i][-1:] == ",":
                parts_found[i] = parts_found[i][:-1]
        parsed["nick"] = ", ".join(parts_found)
        parts_found = []
    if not name_to_parse.strip():
        return _finish(parsed, fix_case)

    # Split remaining name into parts, remove and store preceding commas
    name_parts: list[str] = []
    name_commas: list[str | None] = [None]
    for part in name_to_parse.split(" "):
        comma = None
        if part[-1:] == ",":
            comma = ","
            part = part[:-1]
        name_parts.append(part)
        name_commas.append(comma)

    # Suffix: remove and store matching parts as suffixes
    for i in range(len(name_parts) - 1, 0, -1):
        part_to_check = name_parts[i][:-1].lower() if name_parts[i][-1:] == "." else name_parts[i].lower()
        if part_to_check in _SUFFIX_LIST or (part_to_check + ".") in _SUFFIX_LIST:
            parts_found = _splice(name_parts, i, 1) + parts_found
            if i < len(name_commas) and name_commas[i] == ",":  # Keep comma, either before or after
                _splice(name_commas, i + 1, 1)
            else:
                _splice(name_commas, i, 1)
    if len(parts_found) == 1:
        parsed["suffix"] = parts_found[0]
        parts_found = []
    elif len(parts_found) > 1:
        parsed["suffix"] = ", ".join(parts_found)
        parts_found = []
    if not name_parts:
        return _finish(parsed, fix_case)

    # Title: remove and store matching parts as titles
    for i in range(len(name_parts) - 1, -1, -1):
        part_to_check = name_parts[i][:-1].lower() if name_parts[i][-1:] == "." else name_parts[i].lower()
        if part_to_check in _TITLE_LIST or (part_to_check + ".") in _TITLE_LIST:
            parts_found = _splice(name_parts, i, 1) + parts_found
            if i < len(name_commas) and name_commas[i] == ",":  # Keep comma, either before or after
                _splice(name_commas, i + 1, 1)
            else:
                _splice(name_commas, i, 1)
    if len(parts_found) == 1:
        parsed["title"] = parts_found[0]
        parts_found = []
    elif len(parts_found) > 1:
        parsed["title"] = ", ".join(parts_found)
        parts_found = []
    if not name_parts:
        return _finish(parsed, fix_case)

    # Join name prefixes to following names
    if len(name_parts) > 1:
        for i in range(len(name_parts) - 2, -1, -1):
            if name_parts[i].lower() in _PREFIX_LIST:
                name_parts[i] = name_parts[i] + " " + name_parts[i + 1]
                _splice(name_parts, i + 1, 1)
                _splice(name_commas, i + 1, 1)

    # Join conjunctions to surrounding names
    if len(name_parts) > 2:
        i = len(name_parts) - 3
        while i >= 0:
            if name_parts[i + 1].lower() in _CONJUNCTION_LIST:
                name_parts[i] = name_parts[i] + " " + name_parts[i + 1] + " " + name_parts[i + 2]
                _splice(name_parts, i + 1, 2)
                _splice(name_commas, i + 1, 2)
                i -= 1
            i -= 1

    # Suffix: remove and store items after extra commas as suffixes
    if name_commas:
        name_commas.pop()
    first_comma = _index_of(name_commas, ",")
    remaining_commas = len([v for v in name_commas if v is not None])
    if first_comma > 1 or remaining_commas > 1:
        for i in range(len(name_parts) - 1, 1, -1):
            if i < len(name_commas) and name_commas[i] == ",":
                parts_found = _splice(name_parts, i, 1) + parts_found
                _splice(name_commas, i, 1)
                remaining_commas -= 1
            else:
                break
    if parts_found:
        if parsed["suffix"]:
            parts_found = [parsed["suffix"]] + parts_found
        parsed["suffix"] = ", ".join(parts_found)
        parts_found = []

    # Last name: remove and store last name
    if remaining_commas > 0:
        # Remove and store all parts before first comma as last name
        comma_index = _index_of(name_commas, ",")
        if comma_index:  # JS truthiness: -1 and positive values pass, 0 does not
            if comma_index > 0:
                parsed["last"] = " ".join(_splice(name_parts, 0, comma_index))
                _splice(name_commas, 0, comma_index)
            else:
                # splice(0, -1) removes nothing in JavaScript
                parsed["last"] = ""
    else:
        # Remove and store last part as last name
        parsed["last"] = name_parts.pop()
    if not name_parts:
        return _finish(parsed, fix_case)

    # First name: remove and store first part as first name
    parsed["first"] = name_parts.pop(0)
    if not name_parts:
        return _finish(parsed, fix_case)

    # Middle name: store all remaining parts as middle name
    parsed["middle"] = " ".join(name_parts)
    return _finish(parsed, fix_case)


# ------------------------------------------------------------ parseNameString.js

def _parse_name(name: str) -> dict[str, str]:
    parts = parse_full_name(name)
    first_name = parts.first
    if first_name and parts.middle:
        first_name += " " + parts.middle
    return {"first_name": first_name, "last_name": parts.last}


def _check_is_a_last_name(name: str) -> bool:
    """True when this chunk is the "Last" of a "Last, First" pair."""
    if " " not in name:
        return True  # No spaces must be a Last name
    if not parse_full_name(name).first:
        return True  # had spaces but not a first name i.e. "von Mises", must be last name only
    return False


def _split_and_commas(value: str, separator: str) -> list[str]:
    out: list[str] = []
    for chunk in value.split(separator):
        out.extend(chunk.split(","))
    return out


def parse_name_string(value: str) -> list[str]:
    """parseNameString.parse(value).names: the authors Audiobookshelf reads from
    one author string, each as "First Last". Empty input gives []."""
    if not value:
        return []

    is_comma_separated = "," in value
    if "&" in value:
        split_names = _split_and_commas(value, "&")
    elif " and " in value:
        split_names = _split_and_commas(value, " and ")
    elif ";" in value:
        split_names = _split_and_commas(value, ";")
    else:
        split_names = value.split(",")
    split_names = [a.strip() for a in split_names]

    # If names are in Chinese, Japanese and Korean languages, return as is.
    if _CJK_RE.search(split_names[0]):
        return split_names

    names: list[dict[str, str]] = []
    if len(split_names) == 1:
        names.append(_parse_name(value))
    else:
        first_chunk_is_a_last_name = _check_is_a_last_name(split_names[0]) if is_comma_separated else False
        is_even_num = len(split_names) % 2 == 0
        if not is_even_num and first_chunk_is_a_last_name:
            split_names = split_names[:-1]
        if first_chunk_is_a_last_name:
            for _ in range(len(split_names) // 2):
                last = split_names.pop(0)
                first = split_names.pop(0)
                names.append({"first_name": first, "last_name": last})
        else:
            for segment in split_names:
                names.append(_parse_name(segment))

    names = [n for n in names if n["first_name"] or n["last_name"]]
    out: list[str] = []
    for n in names:
        text = f"{n['first_name']} {n['last_name']}" if n["first_name"] else n["last_name"]
        if text not in out:
            out.append(text)
    return out
