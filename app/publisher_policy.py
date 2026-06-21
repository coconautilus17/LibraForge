"""Shared canonical-publisher policy.

A publisher/imprint catalog used to (a) strip publisher/source noise from search
queries and from author/narrator tags, and (b) recognize "special" editions —
GraphicAudio, Soundbooth Theater — that are not on Audible proper and are better
matched via their dedicated abs-agg endpoints.

The catalog is split across two files, mirroring ``title_noise_policy``:

* a committed default catalog (``config/publishers.default.json``), and
* a writable local file (``config/publishers.local.json``) holding disabled
  defaults plus custom/learned entries.

Both the FastAPI backend and the standalone fixer scripts import this module so
the catalog stays in sync across the UI and the runs.
"""

import json
import os
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_FILE = Path(
    os.environ.get(
        "PUBLISHERS_DEFAULT_FILE",
        PROJECT_ROOT / "config" / "publishers.default.json",
    )
)
LOCAL_POLICY_FILE = Path(
    os.environ.get(
        "PUBLISHERS_LOCAL_FILE",
        PROJECT_ROOT / "config" / "publishers.local.json",
    )
)

# Recognized special-edition providers. IDs must match the abs-agg URL slugs.
SPECIAL_PROVIDERS = {
    "graphicaudio": "Graphic Audio",
    "soundbooththeater": "Soundbooth Theater",
}

_CACHE_KEY: tuple[int, int] | None = None
_CACHE_ENTRIES: tuple[dict[str, Any], ...] = ()
_CACHE_PATTERNS: tuple[tuple[re.Pattern[str], dict[str, Any]], ...] = ()


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return payload if isinstance(payload, dict) else fallback


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _normalize_entry(item: dict[str, Any], source: str, enabled: bool) -> dict[str, Any] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    identifier = str(item.get("id") or _slug(name)).strip()
    if not identifier:
        return None
    aliases = [
        str(alias).strip()
        for alias in (item.get("aliases") or [])
        if str(alias).strip()
    ]
    special = str(item.get("special_provider") or "").strip().lower() or None
    if special not in SPECIAL_PROVIDERS:
        special = None
    return {
        "id": identifier,
        "name": name,
        "aliases": aliases,
        "special_provider": special,
        "source": source,
        "enabled": bool(enabled),
    }


def load_publisher_policy() -> dict[str, Any]:
    defaults = _read_json(DEFAULT_POLICY_FILE, {"schema_version": 1, "publishers": []})
    local = _read_json(
        LOCAL_POLICY_FILE,
        {"schema_version": 1, "disabled_defaults": [], "custom_publishers": []},
    )
    disabled = {
        str(item) for item in local.get("disabled_defaults", []) if str(item).strip()
    }

    default_entries = []
    for item in defaults.get("publishers", []):
        if not isinstance(item, dict):
            continue
        entry = _normalize_entry(item, "default", item.get("id") not in disabled)
        if entry:
            default_entries.append(entry)

    custom_entries = []
    for item in local.get("custom_publishers", []):
        if not isinstance(item, dict):
            continue
        entry = _normalize_entry(
            item,
            str(item.get("source") or "custom"),
            item.get("enabled", True),
        )
        if entry:
            # Preserve the "learned" provenance for entries auto-discovered by runs.
            if entry["source"] not in {"custom", "learned"}:
                entry["source"] = "custom"
            custom_entries.append(entry)

    return {
        "schema_version": 1,
        "default_file": str(DEFAULT_POLICY_FILE),
        "local_file": str(LOCAL_POLICY_FILE),
        "publishers": default_entries + custom_entries,
        "disabled_defaults": sorted(disabled),
        "custom_publishers": custom_entries,
        "special_providers": dict(SPECIAL_PROVIDERS),
    }


def save_publisher_policy(
    *,
    disabled_defaults: list[str],
    custom_publishers: list[dict[str, Any]],
) -> dict[str, Any]:
    current = load_publisher_policy()
    default_ids = {
        entry["id"] for entry in current["publishers"] if entry["source"] == "default"
    }
    disabled = sorted(
        {
            str(item).strip()
            for item in disabled_defaults
            if str(item).strip() in default_ids
        }
    )

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in custom_publishers:
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError("Every publisher needs a name")
        identifier = str(item.get("id") or "").strip() or _slug(name)
        if not identifier:
            raise ValueError(f"Could not derive an id for publisher: {name}")
        if identifier in seen_ids:
            raise ValueError(f"Duplicate publisher id: {identifier}")
        seen_ids.add(identifier)
        special = str(item.get("special_provider") or "").strip().lower() or None
        if special is not None and special not in SPECIAL_PROVIDERS:
            raise ValueError(f"Unknown special provider: {special}")
        source = str(item.get("source") or "custom").strip().lower()
        if source not in {"custom", "learned"}:
            source = "custom"
        normalized.append(
            {
                "id": identifier,
                "name": name,
                "aliases": [
                    str(alias).strip()
                    for alias in (item.get("aliases") or [])
                    if str(alias).strip()
                ],
                "special_provider": special,
                "source": source,
                "enabled": bool(item.get("enabled", True)),
            }
        )

    payload = {
        "schema_version": 1,
        "disabled_defaults": disabled,
        "custom_publishers": normalized,
    }
    LOCAL_POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = LOCAL_POLICY_FILE.with_name(f".{LOCAL_POLICY_FILE.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(LOCAL_POLICY_FILE)
    clear_publisher_cache()
    return load_publisher_policy()


def clear_publisher_cache() -> None:
    global _CACHE_KEY, _CACHE_ENTRIES, _CACHE_PATTERNS
    _CACHE_KEY = None
    _CACHE_ENTRIES = ()
    _CACHE_PATTERNS = ()


def _active() -> tuple[
    tuple[dict[str, Any], ...],
    tuple[tuple[re.Pattern[str], dict[str, Any]], ...],
]:
    """Return enabled entries plus their compiled name/alias matchers (mtime-cached)."""
    global _CACHE_KEY, _CACHE_ENTRIES, _CACHE_PATTERNS
    default_mtime = (
        DEFAULT_POLICY_FILE.stat().st_mtime_ns if DEFAULT_POLICY_FILE.exists() else 0
    )
    local_mtime = LOCAL_POLICY_FILE.stat().st_mtime_ns if LOCAL_POLICY_FILE.exists() else 0
    cache_key = (default_mtime, local_mtime)
    if cache_key == _CACHE_KEY:
        return _CACHE_ENTRIES, _CACHE_PATTERNS

    entries: list[dict[str, Any]] = []
    patterns: list[tuple[re.Pattern[str], dict[str, Any]]] = []
    for entry in load_publisher_policy()["publishers"]:
        if not entry.get("enabled"):
            continue
        entries.append(entry)
        for token in [entry["name"], *entry.get("aliases", [])]:
            token = str(token).strip()
            if not token:
                continue
            # Word-boundary, case-insensitive; tolerate runs of separators.
            tokens = [re.escape(part) for part in re.split(r"\s+", token) if part]
            if not tokens:
                continue
            regex = r"\b" + r"[\s\-_]+".join(tokens) + r"\b"
            try:
                patterns.append((re.compile(regex, re.IGNORECASE), entry))
            except re.error:
                continue
    # Longest names first so multi-word imprints match before their substrings.
    patterns.sort(key=lambda pair: len(pair[0].pattern), reverse=True)

    _CACHE_KEY = cache_key
    _CACHE_ENTRIES = tuple(entries)
    _CACHE_PATTERNS = tuple(patterns)
    return _CACHE_ENTRIES, _CACHE_PATTERNS


def strip_publisher_noise(text: str) -> str:
    """Remove known publisher/imprint/source tokens from a string.

    Word-boundary, case-insensitive. Used for search queries and for cleaning
    author/narrator clues — never alters the dedicated publisher field.
    """
    if not text:
        return text
    _entries, patterns = _active()
    result = str(text)
    for pattern, _entry in patterns:
        result = pattern.sub(" ", result)
    result = re.sub(r"\s{2,}", " ", result).strip(" -–—,;:/")
    return result


def match_canonical_publisher(text: str) -> dict[str, Any] | None:
    """Return the catalog entry whose name/alias appears in ``text`` (or None)."""
    if not text:
        return None
    _entries, patterns = _active()
    for pattern, entry in patterns:
        if pattern.search(text):
            return entry
    return None


def special_provider_for(text: str) -> str | None:
    """Return the abs-agg provider id for a recognized special publisher, else None."""
    entry = match_canonical_publisher(text)
    if entry and entry.get("special_provider"):
        return entry["special_provider"]
    return None


def learn_publishers(names: list[str]) -> dict[str, Any] | None:
    """Append unseen publisher names to the local catalog as ``learned`` entries.

    Deduplicated against existing names/aliases. Returns the refreshed policy when
    anything was added, else None. Call this serially (not from worker threads).
    """
    candidates = []
    seen_local: set[str] = set()
    for name in names:
        name = str(name or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_local:
            continue
        seen_local.add(key)
        candidates.append(name)
    if not candidates:
        return None

    current = load_publisher_policy()
    known = set()
    for entry in current["publishers"]:
        known.add(entry["name"].lower())
        for alias in entry.get("aliases", []):
            known.add(alias.lower())

    custom = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "aliases": entry.get("aliases", []),
            "special_provider": entry.get("special_provider"),
            "source": entry["source"],
            "enabled": entry["enabled"],
        }
        for entry in current["custom_publishers"]
    ]
    existing_ids = {entry["id"] for entry in custom}

    added = False
    for name in candidates:
        if name.lower() in known:
            continue
        identifier = _slug(name) or f"learned-{len(custom)}"
        while identifier in existing_ids:
            identifier = f"{identifier}-x"
        existing_ids.add(identifier)
        custom.append(
            {
                "id": identifier,
                "name": name,
                "aliases": [],
                "special_provider": None,
                "source": "learned",
                "enabled": True,
            }
        )
        known.add(name.lower())
        added = True

    if not added:
        return None
    return save_publisher_policy(
        disabled_defaults=current["disabled_defaults"],
        custom_publishers=custom,
    )
