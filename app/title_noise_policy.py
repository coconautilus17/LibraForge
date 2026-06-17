import json
import os
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_FILE = Path(
    os.environ.get(
        "TITLE_NOISE_DEFAULT_FILE",
        PROJECT_ROOT / "config" / "title-noise.default.json",
    )
)
LOCAL_POLICY_FILE = Path(
    os.environ.get(
        "TITLE_NOISE_LOCAL_FILE",
        PROJECT_ROOT / "config" / "title-noise.local.json",
    )
)

_CACHE_KEY: tuple[int, int] | None = None
_CACHE_PATTERNS: tuple[re.Pattern[str], ...] = ()


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return payload if isinstance(payload, dict) else fallback


def load_title_noise_policy() -> dict[str, Any]:
    defaults = _read_json(DEFAULT_POLICY_FILE, {"schema_version": 1, "patterns": []})
    local = _read_json(
        LOCAL_POLICY_FILE,
        {"schema_version": 1, "disabled_defaults": [], "custom_patterns": []},
    )
    disabled = {
        str(item)
        for item in local.get("disabled_defaults", [])
        if str(item).strip()
    }

    default_patterns = []
    for item in defaults.get("patterns", []):
        if not isinstance(item, dict) or not item.get("id") or not item.get("pattern"):
            continue
        entry = {**item, "source": "default", "enabled": item["id"] not in disabled}
        default_patterns.append(entry)

    custom_patterns = []
    for item in local.get("custom_patterns", []):
        if not isinstance(item, dict) or not item.get("id") or not item.get("pattern"):
            continue
        custom_patterns.append(
            {
                **item,
                "source": "custom",
                "enabled": bool(item.get("enabled", True)),
            }
        )

    return {
        "schema_version": 1,
        "default_file": str(DEFAULT_POLICY_FILE),
        "local_file": str(LOCAL_POLICY_FILE),
        "patterns": default_patterns + custom_patterns,
        "disabled_defaults": sorted(disabled),
        "custom_patterns": custom_patterns,
    }


def validate_pattern(pattern: str) -> str:
    pattern = str(pattern or "").strip()
    if not pattern:
        raise ValueError("Pattern cannot be empty")
    if len(pattern) > 500:
        raise ValueError("Pattern cannot exceed 500 characters")
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise ValueError(f"Invalid regular expression: {error}") from error
    return pattern




def phrase_to_title_noise_pattern(value: str) -> str:
    """Convert a plain user-entered noise phrase into a safe regex.

    This lets the UI ask for normal text such as:
        A Slice-of-Life LitRPG

    and store a regex that tolerates common separators:
        A Slice of Life LitRPG
        A Slice-of-Life LitRPG
        A Slice_of_Life LitRPG

    Raw regex is still supported separately with mode="regex".
    """
    value = str(value or "").strip()
    if not value:
        raise ValueError("Pattern cannot be empty")
    if len(value) > 500:
        raise ValueError("Pattern cannot exceed 500 characters")

    value = (
        value.replace("：", ":")
        .replace("꞉", ":")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
    )

    tokens = [
        token
        for token in re.split(r"""[\s\-_:;,.!?'"()\[\]{}]+""", value)
        if token
    ]

    if not tokens:
        raise ValueError("Pattern cannot be empty")

    # Keep this deliberately conservative: escape every user token, then allow
    # common word separators between tokens. The regex is compiled with
    # re.IGNORECASE by validate_pattern()/active_title_noise_patterns().
    return r"[-_\s]+".join(re.escape(token) for token in tokens)


def _looks_like_regex_pattern(value: str) -> bool:
    """Best-effort legacy detection for custom patterns saved before phrase mode."""
    value = str(value or "")
    return bool(
        re.search(
            r"(?:\\[AbBdDsSwWZ]|\(\?|\[[^\]]+\]|\.\*|\.\+|\{\d|[|^$])",
            value,
        )
    )


def normalize_custom_title_noise_pattern(item: dict[str, Any]) -> tuple[str, str, str]:
    """Return (mode, phrase, regex_pattern) for a custom policy entry.

    Backward compatibility:
      - Existing custom entries without a mode are treated as regex when they
        look like regex.
      - New UI entries should send mode="phrase" and phrase="<user text>".
    """
    raw_mode = str(item.get("mode") or "").strip().lower()
    phrase = str(item.get("phrase") or "").strip()
    raw_pattern = str(item.get("pattern") or "").strip()

    if raw_mode not in {"phrase", "regex"}:
        if phrase:
            raw_mode = "phrase"
        elif _looks_like_regex_pattern(raw_pattern):
            raw_mode = "regex"
        else:
            # New simplified default: plain text in the old "pattern" field is
            # treated as a phrase, not as raw regex.
            raw_mode = "phrase"

    if raw_mode == "regex":
        pattern = validate_pattern(raw_pattern)
        return "regex", phrase, pattern

    phrase = phrase or raw_pattern
    pattern = validate_pattern(phrase_to_title_noise_pattern(phrase))
    return "phrase", phrase, pattern


def save_title_noise_policy(
    *,
    disabled_defaults: list[str],
    custom_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    defaults = load_title_noise_policy()
    default_ids = {
        item["id"] for item in defaults["patterns"] if item["source"] == "default"
    }
    disabled = sorted(
        {
            str(item).strip()
            for item in disabled_defaults
            if str(item).strip() in default_ids
        }
    )

    normalized_custom = []
    seen_ids: set[str] = set()
    for item in custom_patterns:
        identifier = re.sub(
            r"[^a-z0-9-]+",
            "-",
            str(item.get("id") or item.get("label") or "").strip().lower(),
        ).strip("-")
        if not identifier:
            raise ValueError("Every custom pattern needs a label or id")
        identifier = f"custom-{identifier.removeprefix('custom-')}"
        if identifier in seen_ids:
            raise ValueError(f"Duplicate custom pattern id: {identifier}")
        seen_ids.add(identifier)
        mode, phrase, pattern = normalize_custom_title_noise_pattern(item)
        normalized_custom.append(
            {
                "id": identifier,
                "label": str(item.get("label") or identifier).strip(),
                "description": str(item.get("description") or "").strip(),
                "mode": mode,
                "phrase": phrase,
                "pattern": pattern,
                "enabled": bool(item.get("enabled", True)),
            }
        )

    payload = {
        "schema_version": 1,
        "disabled_defaults": disabled,
        "custom_patterns": normalized_custom,
    }
    LOCAL_POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = LOCAL_POLICY_FILE.with_name(f".{LOCAL_POLICY_FILE.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(LOCAL_POLICY_FILE)
    clear_title_noise_cache()
    return load_title_noise_policy()


def clear_title_noise_cache() -> None:
    global _CACHE_KEY, _CACHE_PATTERNS
    _CACHE_KEY = None
    _CACHE_PATTERNS = ()


def active_title_noise_patterns() -> tuple[re.Pattern[str], ...]:
    global _CACHE_KEY, _CACHE_PATTERNS
    default_mtime = DEFAULT_POLICY_FILE.stat().st_mtime_ns if DEFAULT_POLICY_FILE.exists() else 0
    local_mtime = LOCAL_POLICY_FILE.stat().st_mtime_ns if LOCAL_POLICY_FILE.exists() else 0
    cache_key = (default_mtime, local_mtime)
    if cache_key == _CACHE_KEY:
        return _CACHE_PATTERNS

    compiled = []
    for item in load_title_noise_policy()["patterns"]:
        if not item.get("enabled"):
            continue
        try:
            compiled.append(re.compile(validate_pattern(item["pattern"]), re.IGNORECASE))
        except ValueError:
            continue
    _CACHE_KEY = cache_key
    _CACHE_PATTERNS = tuple(compiled)
    return _CACHE_PATTERNS


def is_title_noise(value: str) -> bool:
    value = str(value or "").strip(" -_.:,/")
    return bool(value) and any(
        pattern.fullmatch(value) for pattern in active_title_noise_patterns()
    )


def contains_title_noise(value: str) -> bool:
    value = str(value or "")
    return bool(value) and any(
        pattern.search(value) for pattern in active_title_noise_patterns()
    )


def remove_trailing_title_noise(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not value:
        return ""

    def without_sequence(text: str) -> str:
        return re.sub(r"\s*\(\s*\d{1,4}\s*\)\s*$", "", text).strip(" -_.:,/")

    parts = [
        part.strip()
        for part in re.split(r"\s+[-–—:;]\s+", value)
        if part.strip()
    ]
    if len(parts) > 1 and is_title_noise(without_sequence(parts[-1])):
        return " - ".join(parts[:-1]).strip(" -_.:,")

    match = re.search(
        r"\s+(?P<descriptor>(?:a|an)\s+[^-–—:;]{0,90}(?:\(\s*\d{1,4}\s*\))?)$",
        value,
        flags=re.IGNORECASE,
    )
    if match and is_title_noise(without_sequence(match.group("descriptor"))):
        return value[: match.start()].strip(" -_.:,")
    return value
