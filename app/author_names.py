"""Universal author-name scheme, its exception patterns, and the on/off switch.

The scheme (only used when enabled in Settings): initials are always "X." per
letter with no spaces between them, then one space before the rest of the name.
"V A Lewis", "V.A Lewis", "J.K.Rowling" and "JK Rowling" become "V.A. Lewis" /
"J.K. Rowling"; a lone initial gets its dot ("Kevin J Anderson" becomes
"Kevin J. Anderson").

Exceptions follow the same patterns-in-use/custom pattern as publishers and title noise:
config/author-names.default.json (patterns in use, ships with LibraForge) and
config/author-names.local.json (custom patterns, disabled_defaults and
custom_names). Stdlib only: shared by the organizer script, the fixer and the app.
"""
import json
import os
import re
from pathlib import Path
from typing import Any

from app.publisher_policy import match_canonical_publisher
from app.settings_paths import user_settings_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_FILE = Path(os.environ.get(
    "AUTHOR_NAMES_DEFAULT_FILE", PROJECT_ROOT / "config" / "author-names.default.json"))
LOCAL_POLICY_FILE = Path(os.environ.get(
    "AUTHOR_NAMES_LOCAL_FILE", user_settings_file("author-names.local.json")))
STATE_FILE = Path(os.environ.get(
    "LIBRAFORGE_STATE_FILE",
    Path(os.environ.get("REPORTS_DIR", PROJECT_ROOT / "reports")) / ".install-state.json"))

# Used only if the shipped default file cannot be read.
_BUILTIN_KNOWN = [
    {"id": "mashton-xx", "label": "Mashton XX", "description": "The letters XX are part of the name, not initials.",
     "name": "Mashton XX", "spelling": "Mashton XX"},
    {"id": "mashton-xy", "label": "Mashton XY", "description": "The letters XY are part of the name, not initials.",
     "name": "Mashton XY", "spelling": "Mashton XY"},
    {"id": "comedian0-l", "label": "Comedian0 L", "description": "A handle with a digit and a single trailing letter, not initials.",
     "name": "Comedian0 L", "spelling": "Comedian0 L"},
]

_ROMAN = re.compile(r"^(?:II|III|IV|VI|VII|VIII|IX|XI|XII)$")
_GLUED = re.compile(r"^((?:[A-Za-z]\.)+)([A-Za-z][a-z].*)$")
_LONE = re.compile(r"^[A-Za-z]\.?$")
_DOTTED = re.compile(r"^(?:[A-Za-z]\.)+[A-Za-z]?\.?$")
_CAPS_CLUSTER = re.compile(r"^[A-Z]{2,3}$")
_ROLE_SUFFIX = re.compile(r"(\s+-\s+[A-Za-z][A-Za-z ]*)$")
_CREDIT_SEPARATOR = re.compile(r"(\s*(?:,|;|&|\band\b)\s*)", re.IGNORECASE)


def name_key(text: str) -> str:
    """Case, dots and spaces ignored, so one pattern matches every variant."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


# ---------------------------------------------------------------- policy files

def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entry(item: Any, source: str, enabled: bool) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()
    spelling = str(item.get("spelling") or "").strip()
    if not name or not spelling:
        return None
    label = str(item.get("label") or spelling).strip()
    identifier = str(item.get("id") or "").strip() or f"{source}-{name_key(name)}"
    return {"id": identifier, "label": label, "description": str(item.get("description") or "").strip(),
            "name": name, "spelling": spelling, "source": source, "enabled": enabled}


def load_author_policy() -> dict[str, Any]:
    """Known (default) and private (custom) name patterns, merged for the UI."""
    default_items = _read_json(DEFAULT_POLICY_FILE).get("names")
    if not isinstance(default_items, list):
        default_items = _BUILTIN_KNOWN
    local = _read_json(LOCAL_POLICY_FILE)
    disabled = {str(x) for x in (local.get("disabled_defaults") or [])}
    names: list[dict[str, Any]] = []
    for item in default_items:
        entry = _entry(item, "default", True)
        if entry:
            entry["enabled"] = entry["id"] not in disabled
            names.append(entry)
    for item in local.get("custom_names") or []:
        entry = _entry(item, "custom", bool(item.get("enabled", True)) if isinstance(item, dict) else True)
        if entry:
            names.append(entry)
    return {"schema_version": 1, "names": names}


def save_author_policy(disabled_defaults: list[str], custom_names: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in custom_names:
        name = str(item.get("name") or "").strip()
        spelling = str(item.get("spelling") or "").strip()
        if not name or not spelling:
            raise ValueError("Each custom pattern needs a name and the exact spelling to keep.")
        if name_key(name) != name_key(spelling):
            raise ValueError(f"{spelling!r} must have the same letters as {name!r}; a pattern can only choose the spelling.")
        if name_key(name) in seen:
            raise ValueError(f"{name!r} is listed twice.")
        seen.add(name_key(name))
        cleaned.append({"id": str(item.get("id") or f"custom-{name_key(name)}"),
                        "label": str(item.get("label") or spelling).strip(), "description": str(item.get("description") or "").strip(),
                        "name": name, "spelling": spelling, "enabled": bool(item.get("enabled", True))})
    payload = {"schema_version": 1, "disabled_defaults": sorted({str(x) for x in disabled_defaults}), "custom_names": cleaned}
    LOCAL_POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = LOCAL_POLICY_FILE.with_name(LOCAL_POLICY_FILE.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, LOCAL_POLICY_FILE)
    return load_author_policy()


_CACHE: dict[str, Any] = {"key": None, "map": {}}


def _files_key() -> tuple:
    key = []
    for path in (DEFAULT_POLICY_FILE, LOCAL_POLICY_FILE):
        try:
            stat = path.stat()
            key.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            key.append((str(path), 0, 0))
    return tuple(key)


def _active_exceptions() -> dict[str, str]:
    key = _files_key()
    if _CACHE["key"] != key:
        _CACHE["map"] = {name_key(e["name"]): e["spelling"] for e in load_author_policy()["names"] if e["enabled"]}
        _CACHE["key"] = key
    return _CACHE["map"]


# --------------------------------------------------------------------- the rule

def _initial_letters(token: str, index: int, last_index: int) -> list[str] | None:
    if _LONE.fullmatch(token):
        return [token[0].upper()]
    if "." in token and _DOTTED.fullmatch(token):
        return [char.upper() for char in token if char.isalpha()]
    # Unspaced capitals such as "JK" or "TJ" are initials only when they are
    # not the final word, so "Mashton XX" and "John Smith III" stay intact.
    if index < last_index and _CAPS_CLUSTER.fullmatch(token) and not _ROMAN.fullmatch(token):
        # A production/broadcaster credit ("BBC - Andrew Marshall & John
        # Lloyd") is not a person, even though "BBC" alone is the same shape
        # as real initials ("JD", "TJ"). Reuse the publisher catalog rather
        # than a second hardcoded list.
        if match_canonical_publisher(token):
            return None
        return list(token)
    return None


def format_person_name(name: str) -> str:
    """Apply the initials scheme to one person's name, keeping any trailing
    role suffix such as " - translator" untouched."""
    if not name or not name.strip():
        return name
    role = ""
    match = _ROLE_SUFFIX.search(name)
    if match:
        role = match.group(1)
        name = name[: match.start()]
    exception = _active_exceptions().get(name_key(name))
    if exception:
        return exception + role
    if any(char.isdigit() for char in name):
        return name + role  # handles such as "Comedian0 L" are never initials
    tokens: list[str] = []
    for token in name.split():
        glued = _GLUED.fullmatch(token)
        tokens.extend(glued.groups() if glued else [token])
    last_index = len(tokens) - 1
    out: list[str] = []
    run: list[str] = []
    for index, token in enumerate(tokens):
        letters = _initial_letters(token, index, last_index)
        if letters:
            run.extend(letters)
            continue
        if run:
            out.append("".join(f"{letter}." for letter in run))
            run = []
        out.append(token)
    if run:
        out.append("".join(f"{letter}." for letter in run))
    return " ".join(out) + role


def format_author_credit(value: str) -> str:
    """Apply the scheme to every person in a credit such as
    "A. F. Kay, Mikhail Yagupov - translator", keeping the original separators."""
    if not value:
        return value
    parts = _CREDIT_SEPARATOR.split(value)
    return "".join(part if index % 2 else format_person_name(part) for index, part in enumerate(parts))


def initials_only_change(before: str, after: str) -> bool:
    """True when two author credits differ only in how initials are written
    ("V A Lewis" and "V.A. Lewis"): same letters, different text."""
    if not before or not after or before == after:
        return False
    strip = lambda text: re.sub(r"[^a-z0-9]+", "", text.lower())
    return strip(before) == strip(after)


# ------------------------------------------------------------------- on/off

_STATE_CACHE: dict[str, Any] = {"key": None, "value": False}


def scheme_enabled() -> bool:
    """True when the universal scheme is switched on (Settings, Author names).
    LIBRAFORGE_AUTHOR_SCHEME=universal|legacy overrides, for scripts and tests."""
    forced = os.environ.get("LIBRAFORGE_AUTHOR_SCHEME", "").strip().lower()
    if forced in ("universal", "legacy"):
        return forced == "universal"
    try:
        stat = STATE_FILE.stat()
        key = (str(STATE_FILE), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return False
    if _STATE_CACHE["key"] != key:
        _STATE_CACHE["value"] = _read_json(STATE_FILE).get("author_scheme_enabled") is True
        _STATE_CACHE["key"] = key
    return _STATE_CACHE["value"]


def output_author_credit(value: str) -> str:
    """Author text the fixer writes to tags and sidecars: unchanged unless the scheme is enabled."""
    return format_author_credit(value) if scheme_enabled() else value
