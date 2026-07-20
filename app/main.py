import difflib
import functools
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import audible
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from mutagen.mp4 import MP4, MP4FreeForm
from pydantic import BaseModel, Field

from app.conversion_cache import (
    CachedAudioProbeReader,
    CachedChapterCountReader,
    load_discovery_cache,
    save_discovery_cache,
    search_cache_key,
    utc_timestamp,
)
from app.conversion_discovery import conversion_candidate, summarize_audio_probes
from app.folder_scan_cache import (
    load_scan_cache_file,
    save_scan_cache_file,
    scan_cache_key as folder_scan_cache_key,
)
import app.library_index as library_index
from app.library_index import FS_SKIP_PREFIXES as _FS_SKIP_PREFIXES
from app.library_index import is_audio_file
from app.enrichment import (
    compile_series_enrichment,
    fetch_all_abs_book_items,
    get_series_books,
    group_items_by_series,
    list_series_summary,
    resolve_metadata_json_path,
    search_series_abs,
    search_series_audible,
    search_series_goodreads,
    write_metadata_json_partial,
)
from app.fixer.scoring import clean_provider_genres
from app.fixer.search import (
    ENRICHMENT_RESPONSE_GROUPS,
    abs_tract_search,
    audible_lookup_by_asin,
)
from app.fixer.search import audible_search as fixer_audible_search
from app.m4b_naming import canonical_m4b_title
from app.manual_review import build_sidecar_multipart_context
from app.progress_phases import (
    fixer_phase_for_line,
    m4b_phase_for_line,
    organizer_move_phase,
    organizer_progress_phase,
    terminal_phase,
)
from app.title_noise_policy import load_title_noise_policy, save_title_noise_policy
from app.publisher_policy import SPECIAL_PROVIDERS, load_publisher_policy, save_publisher_policy

APP_ROOT = Path(__file__).resolve().parent
STATIC_DIR = APP_ROOT / "static"
ICON_FILE = APP_ROOT / "libraforge.png"
EXAMPLE_BOOKS_DIR = APP_ROOT / "example_books"
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/app/scripts")).resolve()
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/app/reports")).resolve()
AUDIOBOOKS_ROOT = Path(os.environ.get("AUDIOBOOKS_ROOT", "/audiobooks")).resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

_GENRE_BLOCKLIST = {"audiobook", "audiobooks"}


def _pick_genre(genres: list[str]) -> str:
    """Return every genre that isn't a generic format label, joined by ", ".

    Providers can return several real genres (e.g. ["Fantasy", "Romance"]) --
    keep all of them, not just the first, so the joined result matches what a
    provider's own listing shows instead of silently dropping the rest.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for g in genres:
        cleaned = g.strip()
        key = cleaned.lower()
        if not cleaned or key in _GENRE_BLOCKLIST or key in seen:
            continue
        seen.add(key)
        kept.append(cleaned)
    return ", ".join(kept)


M4B_TOOL_SIDECAR_SUFFIX = ".m4b-tool-metadata.json"
M4B_DISCOVERY_CACHE = REPORTS_DIR / "m4b-discovery-cache.json"
M4B_DISCOVERY_CACHE_LOCK = threading.Lock()

FOLDER_SCAN_CACHE = REPORTS_DIR / "folder-scan-cache.json"
FOLDER_SCAN_CACHE_LOCK = threading.Lock()

DEFAULT_AUTH_FILE = Path("/auth/audible-metadata.json")
# Saved Audible accounts live here, one <user_id>.json auth file plus a
# <user_id>.meta.json sidecar holding the user-given flavor name. The active
# account is whichever one currently mirrors DEFAULT_AUTH_FILE.
ACCOUNTS_DIR = Path("/auth/accounts")
COVER_UPLOAD_DIR = Path(tempfile.gettempdir()) / "libraforge-cover-uploads"
MAX_COVER_DOWNLOAD_BYTES = 10 * 1024 * 1024
ABS_AGG_CONFIG_FILE = APP_ROOT.parent / "config" / "abs-agg.json"
RETENTION_CONFIG_FILE = APP_ROOT.parent / "config" / "retention.json"


def _load_retention_config() -> dict[str, Any]:
    try:
        if RETENTION_CONFIG_FILE.exists():
            return json.loads(RETENTION_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"max_age_days_enabled": False, "max_age_days": 30, "max_count_enabled": False, "max_count": 20}


def _save_retention_config(config: dict[str, Any]) -> None:
    RETENTION_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    RETENTION_CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _prune_reports() -> list[str]:
    """Apply retention rules and return list of deleted run IDs."""
    cfg = _load_retention_config()
    report_files = sorted(REPORTS_DIR.glob("*.report.json"), reverse=True)

    to_delete: set[Path] = set()

    if cfg.get("max_age_days_enabled"):
        max_age = int(cfg.get("max_age_days") or 30)
        cutoff = datetime.now(timezone.utc).timestamp() - max_age * 86400
        for p in report_files:
            if p.stat().st_mtime < cutoff:
                to_delete.add(p)

    if cfg.get("max_count_enabled"):
        max_count = int(cfg.get("max_count") or 20)
        for p in report_files[max_count:]:
            to_delete.add(p)

    deleted: list[str] = []
    for report_path in to_delete:
        run_id = report_path.name.replace(".report.json", "")
        for suffix in (".report.json", ".log.txt", ".report.suspect-review.json"):
            companion = REPORTS_DIR / f"{run_id}{suffix}"
            try:
                companion.unlink(missing_ok=True)
            except OSError:
                pass
        deleted.append(run_id)
    return deleted

# Fallback provider catalog used when abs-agg is unreachable.
# IDs must match the abs-agg URL slugs exactly (verified against /providers endpoint).
# graphicaudio/soundbooththeater come from publisher_policy.SPECIAL_PROVIDERS
# (also read by app/fixer/scoring.py) rather than being duplicated here, so
# the two abs-agg publisher-backfill paths (this interactive-search catalog
# and the automated fixer's SPECIAL_PROVIDERS lookup) can't silently drift.
_ABS_AGG_PROVIDERS_FALLBACK: dict[str, str] = {
    "librivox":          "LibriVox",
    "storytel":          "Storytel",
    "audioteka":         "Audioteka",
    "bookbeat":          "BookBeat",
    "bigfinish":         "Big Finish",
    **SPECIAL_PROVIDERS,
    "ardaudiothek":      "ARD Audiothek",
    "dreifragezeichen":  "Die drei ???",
}

# Providers that require a path parameter — shown as a hint in the UI.
# Format: provider_id -> (param_name, example_value, description)
ABS_AGG_REQUIRED_PARAMS: dict[str, tuple[str, str, str]] = {
    "storytel":  ("language", "en", "ISO language code, e.g. en, de, fr, sv, es"),
    "audioteka": ("lang",     "pl", "Region code: pl, cz, de, sk, lt"),
    "bookbeat":  ("market",   "germany", "Country name, e.g. germany, sweden, united-kingdom"),
}


def _load_abs_agg_config() -> dict[str, Any]:
    try:
        if ABS_AGG_CONFIG_FILE.exists():
            return json.loads(ABS_AGG_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"url": "http://abs-agg:3000"}


def _save_abs_agg_config(config: dict[str, Any]) -> None:
    ABS_AGG_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ABS_AGG_CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# abs-tract (Goodreads/Kindle) is a separate service from abs-agg. Empty URL by
# default. Batch Goodreads fallback also requires an explicit per-run flag.
ABS_TRACT_CONFIG_FILE = APP_ROOT.parent / "config" / "abs-tract.json"


def _load_abs_tract_config() -> dict[str, Any]:
    try:
        if ABS_TRACT_CONFIG_FILE.exists():
            return json.loads(ABS_TRACT_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"url": "", "kindle_region": "us"}


def _save_abs_tract_config(config: dict[str, Any]) -> None:
    ABS_TRACT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ABS_TRACT_CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def search_abs_agg_candidates(
    *,
    query: str,
    author: str = "",
    base_url: str,
    provider: str,
    provider_params: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    import urllib.error as _urlerror
    import urllib.parse as _urlparse

    # provider_params is the raw path value (e.g. "en" for Storytel, "pl" for Audioteka).
    # It slots directly into the URL path: /{provider}/{params}/search
    params_segment = f"/{provider_params.strip('/')}" if provider_params.strip("/") else ""
    qs_dict: dict[str, Any] = {"title": query, "limit": limit}
    if author:
        qs_dict["author"] = author
    qs = _urlparse.urlencode(qs_dict)
    search_url = f"{base_url.rstrip('/')}/{provider}{params_segment}/search?{qs}"

    try:
        req = urllib.request.Request(
            search_url,
            headers={"Accept": "application/json", "User-Agent": "LibraForge/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except _urlerror.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"abs-agg unreachable at {base_url}: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"abs-agg search failed: {exc}") from exc

    results: list[dict[str, Any]] = []
    for match in data.get("matches", [])[:limit]:
        series_list = match.get("series") or []
        series_name = series_list[0].get("series", "") if series_list else ""
        sequence = str(series_list[0].get("sequence", "") or "") if series_list else ""
        author = match.get("author", "") or ""
        narrator = match.get("narrator", "") or ""
        year = str(match.get("publishedYear", "") or "")
        cover_url = match.get("cover", "") or ""
        summary = match.get("description", "") or ""
        title = match.get("title", "") or ""
        subtitle = match.get("subtitle", "") or ""
        # No synthetic placeholder here: this asin flows straight through
        # "Use this match" -> the ASIN form field -> save, with nothing to
        # distinguish a real, persistable ASIN from a display-only stand-in.
        # These dedicated-catalog sources (GraphicAudio, SoundBooth Theater,
        # etc.) generally have no Audible ASIN at all, so it must stay blank
        # rather than leak a fabricated "abs-agg-{provider}-{i}" string into
        # the saved sidecar.
        asin = match.get("asin", "") or ""
        publisher = _ABS_AGG_PROVIDERS_FALLBACK.get(provider, provider)
        duration_seconds = match.get("duration") or 0
        duration_minutes = round(duration_seconds / 60, 2) if duration_seconds else None
        genre = _pick_genre(match.get("genres") or [])

        full_meta = {
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "narrator": narrator,
            "series": series_name,
            "sequence": sequence,
            "year": year,
            "cover_url": cover_url,
            "asin": asin,
            "publisher": publisher,
            "summary": summary,
            "genre": genre,
        }
        series_only_meta = {
            "title": "",
            "subtitle": "",
            "author": "",
            "narrator": "",
            "series": series_name,
            "sequence": sequence,
            "year": "",
            "cover_url": "",
            "asin": asin,
            "publisher": publisher,
            "summary": "",
            "genre": genre,
        }
        allowed_modes = ["full"] + (["series_only"] if series_name else [])

        results.append({
            "asin": asin,
            "query": query,
            "score": None,
            "edit_mode": "full",
            "recommended_edit_mode": "full",
            "allowed_edit_modes": allowed_modes,
            "title": title,
            "subtitle": subtitle,
            "authors": [author] if author else [],
            "narrators": [narrator] if narrator else [],
            "series": series_name,
            "sequence": sequence,
            "duration_minutes": duration_minutes,
            "year": year,
            "cover_url": cover_url,
            "summary": summary,
            "chosen_metadata": full_meta,
            "chosen_metadata_by_mode": {"full": full_meta, "series_only": series_only_meta},
            "duration": {},
            "provider": "abs-agg",
            "abs_agg_provider": provider,
        })

    return {"queries": [query], "results": results}


def search_abs_tract_candidates(
    *,
    query: str,
    author: str = "",
    base_url: str,
    provider: str,
    kindle_region: str = "us",
    limit: int = 10,
) -> dict[str, Any]:
    """Manual search against an abs-tract provider (Goodreads / Kindle).

    abs-tract returns the same ABS-standard {matches:[...]} shape as abs-agg, so
    the result rows match the abs-agg format the manual-search UI renders. Kindle
    Store ASINs are *ebook* ASINs (not Audible audiobook ASINs), so a Kindle
    candidate never carries an ASIN — it is useful for its cover only.
    """
    import urllib.error as _urlerror
    import urllib.parse as _urlparse

    if provider == "kindle":
        path = f"kindle/{kindle_region.strip('/')}/search"
    else:
        path = f"{provider}/search"
    qs = _urlparse.urlencode({"query": query, **({"author": author} if author else {})})
    search_url = f"{base_url.rstrip('/')}/{path}?{qs}"

    try:
        req = urllib.request.Request(
            search_url,
            headers={"Accept": "application/json", "User-Agent": "LibraForge/1.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except _urlerror.URLError as exc:
        raise HTTPException(
            status_code=502, detail=f"abs-tract unreachable at {base_url}: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"abs-tract search failed: {exc}") from exc

    is_kindle = provider == "kindle"
    results: list[dict[str, Any]] = []
    for i, match in enumerate(data.get("matches", [])[:limit]):
        series_list = match.get("series") or []
        series_name = series_list[0].get("series", "") if series_list else ""
        sequence = str(series_list[0].get("sequence", "") or "") if series_list else ""
        m_author = match.get("author", "") or ""
        narrator = match.get("narrator", "") or ""
        year = str(match.get("publishedYear", "") or "")
        cover_url = match.get("cover", "") or ""
        summary = match.get("description", "") or ""
        title = match.get("title", "") or ""
        subtitle = match.get("subtitle", "") or ""
        # Never surface a Kindle ebook ASIN as the audiobook ASIN.
        asin = "" if is_kindle else (match.get("asin", "") or "")
        display_key = asin or f"abs-tract-{provider}-{i}"

        genre = _pick_genre(match.get("genres") or [])

        full_meta = {
            "title": title, "subtitle": subtitle, "author": m_author,
            "narrator": narrator, "series": series_name, "sequence": sequence,
            "year": year, "cover_url": cover_url, "asin": asin, "summary": summary,
            "genre": genre,
        }
        series_only_meta = {
            "title": "", "subtitle": "", "author": "", "narrator": "",
            "series": series_name, "sequence": sequence, "year": "",
            "cover_url": "", "asin": asin, "summary": "",
            "genre": genre,
        }
        allowed_modes = ["full"] + (["series_only"] if series_name else [])

        results.append({
            "asin": asin,
            "display_key": display_key,
            "query": query,
            "score": None,
            "edit_mode": "full",
            "recommended_edit_mode": "full",
            "allowed_edit_modes": allowed_modes,
            "title": title,
            "subtitle": subtitle,
            "authors": [m_author] if m_author else [],
            "narrators": [narrator] if narrator else [],
            "series": series_name,
            "sequence": sequence,
            "duration_minutes": None,
            "year": year,
            "cover_url": cover_url,
            "summary": summary,
            "chosen_metadata": full_meta,
            "chosen_metadata_by_mode": {"full": full_meta, "series_only": series_only_meta},
            "duration": {},
            "provider": "abs-tract",
            "abs_tract_provider": provider,
        })

    return {"queries": [query], "results": results}


# In-memory state for the in-progress OAuth login (single-user homelab — no sessions needed).
_pending_login_lock = threading.Lock()
_pending_login: dict | None = None

_LOCALE_NAMES: dict[str, str] = {
    "us": "United States",
    "uk": "United Kingdom",
    "de": "Germany",
    "fr": "France",
    "ca": "Canada",
    "au": "Australia",
    "it": "Italy",
    "jp": "Japan",
    "es": "Spain",
    "br": "Brazil",
    "in": "India",
}

PROCESSING_RE = re.compile(r"^\[(\d+)/(\d+)\]\s+Processing:\s+(.+)$")
WRITING_RE = re.compile(r"^\[(\d+)/(\d+)\]\s+Writing:\s+(.+)$")
PASS1_PROGRESS_RE = re.compile(r"^PASS 1 PROGRESS:\s+completed\s+(\d+)/(\d+)\s*$")
FOUND_RE = re.compile(r"^Found\s+(\d+)\s+supported files\.")
SEARCH_WORKERS_RE = re.compile(r"^Search workers:\s+(\d+)\s*$")
GOODREADS_CIRCUIT_TRIPPED_SENTINEL = "GOODREADS_CIRCUIT_TRIPPED"
MODE_RE = re.compile(r"^\s+Mode:\s+([A-Za-z_]+)\s*$")
GROUPED_RE = re.compile(r"^\s+Grouped:\s+(\d+)\s+files?\s*$")
DURATION_STATUS_RE = re.compile(r"^\s+Status:\s+([A-Za-z_]+)\s*$")
DIFF_RE = re.compile(r"^\s+Diff:\s+([0-9.]+)%")
SUMMARY_RE = re.compile(r"^\s*(Matched|Skipped|Failed|Smart-skipped):\s+(\d+)\s*$")
FILL_STATS_RE = re.compile(r"^\s*(Books filled|Already complete|ASIN filled):\s+(\d+)\s*$")
SKIP_RE = re.compile(r"^\s+SKIP:\s+(.+)$")
WRITE_SKIP_RE = re.compile(r"^\s+Write-(?:skip|error):\s+")
ERROR_RE = re.compile(r"^\s+ERROR:\s+(.+)$")
# The plan header names the source ("AUDIBLE MATCH:", "GOODREADS MATCH:",
# "GRAPHICAUDIO MATCH:", ...). Match any provider header so non-Audible matches
# are still categorized as matched.
MATCH_RE = re.compile(r"^[A-Z][A-Z ]*MATCH:")
AMBIG_RESOLVED_RE = re.compile(r"\(chose .* on duration\)\s*$")
FILL_ITEM_RE = re.compile(r"^\s+FILL:\s+(?:complete|filled\s+(.+))\s*$")
SOURCE_RE = re.compile(r"^\s+SOURCE:\s+(\S+)\s*$")
WRITE_ACTION_PREFIX = "WRITE_ACTION_JSON: "
SECTION_END_RE = re.compile(
    r"^(Summary:|Mode breakdown:|MANUAL REVIEW REPORT:|DURATION REVIEW REPORT|"
    r"ASIN VERIFICATION|Checking the library)"
)
ORGANIZER_SUMMARY_RE = re.compile(r"^(Found book items|Ignored MP3 files|Skipped likely existing book folders|Skipped unknown author|Skipped by pattern|Skipped already in target folder|Skipped conflicts|Structure cache entries|Matched existing structure|Ambiguous structure matches|Skipped ambiguous structure|Planned moves|Moves succeeded|Moves failed):\s+(\d+)\s*$")
ORGANIZER_MODE_RE = re.compile(r"^Mode:\s+(APPLY|DRY RUN|INDEX ONLY)\s*$")
ORGANIZER_FIELD_RE = re.compile(r"^\s+(Kind|Title|Author|Files|Metadata Source|Review Reasons|Series|Number|Structure|Error):\s+(.+)$")
ORGANIZER_PROGRESS_RE = re.compile(r"^Scanning\s+(\d+)/(\d+):\s+(.+)$")
ORGANIZER_INDEX_PROGRESS_RE = re.compile(r"^Indexing structure\s+(\d+)/(\d+):\s+(.+)$")
M4B_SPINNER_RE = re.compile(r"^\s*(\d+)\s+remaining\s+/\s+(\d+)\s+total")
M4B_TAGGED_CHAPTERS_RE = re.compile(r"^tagged file .+,\s+chapters:\s+(\d+)\)$")
M4B_AUDIO_CODECS = {"libfdk_aac", "aac"}
M4B_AUDIO_BITRATES = {"64k", "80k", "96k", "128k", "160k", "192k"}
M4B_AUDIO_SAMPLERATES = {22050, 32000, 44100, 48000}
M4B_AUDIO_CHANNELS = {1, 2}


def safe_child(base: Path, name: str) -> Path:
    candidate = (base / name).resolve()
    if base not in candidate.parents and candidate != base:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def is_organizer_script(script_name: str) -> bool:
    return script_name.startswith("organize-audiobooks") and script_name.endswith(".py")


def is_fixer_script(script_name: str) -> bool:
    return script_name.startswith("audible-metadata-fixer") and script_name.endswith(".py")


def discover_scripts() -> tuple[list[str], list[str]]:
    scripts = sorted(
        path.name
        for path in SCRIPTS_DIR.iterdir()
        if path.is_file() and path.suffix == ".py"
    )
    organizer_scripts = [name for name in scripts if is_organizer_script(name)]
    fixer_scripts = [name for name in scripts if is_fixer_script(name)]
    return fixer_scripts, organizer_scripts


def default_fixer_script() -> str:
    fixer_scripts, _ = discover_scripts()
    return fixer_scripts[-1] if fixer_scripts else ""


def default_organizer_script() -> str:
    _, organizer_scripts = discover_scripts()
    return organizer_scripts[-1] if organizer_scripts else ""


def live_script_path(script_name: str, script_kind: str) -> Path:
    script_path = safe_child(SCRIPTS_DIR, script_name)
    if (
        not script_path.exists()
        or not script_path.is_file()
        or script_path.suffix != ".py"
    ):
        raise HTTPException(status_code=404, detail=f"{script_kind.title()} script not found")
    if (script_kind == "organizer") != is_organizer_script(script_name):
        raise HTTPException(status_code=400, detail=f"Invalid {script_kind} script")
    return script_path


def validate_existing_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    return path


def validate_output_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    parent = path.parent
    if not parent.exists():
        raise HTTPException(status_code=404, detail=f"Output directory not found: {parent}")
    return path


def assert_under_audiobooks(path: Path) -> Path:
    if path != AUDIOBOOKS_ROOT and AUDIOBOOKS_ROOT not in path.parents:
        raise HTTPException(
            status_code=400,
            detail=f"Path must be under: {AUDIOBOOKS_ROOT}",
        )
    return path


def validate_audiobook_path(raw_path: str) -> Path:
    return assert_under_audiobooks(validate_existing_path(raw_path))


def validate_audiobook_output_path(raw_path: str) -> Path:
    return assert_under_audiobooks(validate_output_path(raw_path))


def datetime_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value or "output"



def source_audio_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if is_audio_file(path) else []
    return sorted(
        child
        for child in path.rglob("*")
        if child.is_file()
        and is_audio_file(child)
        and not any(part.endswith("-tmpfiles") for part in child.parts)
    )


def probe_audio_file(audio_file: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,codec_long_name,profile,bit_rate,channels,sample_rate:format=format_name,format_long_name,bit_rate",
            "-of",
            "json",
            str(audio_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        probe = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"probed": False}
    stream = (probe.get("streams") or [{}])[0]
    format_info = probe.get("format") or {}
    bitrate = stream.get("bit_rate") or format_info.get("bit_rate")
    codec = str(stream.get("codec_name", "") or "").lower()
    codec_label = str(stream.get("codec_long_name", "") or codec.upper())
    profile = str(stream.get("profile", "") or "")
    if profile and profile.lower() not in codec_label.lower():
        codec_label = f"{codec_label} ({profile})"
    container = str(format_info.get("format_long_name", "") or format_info.get("format_name", "") or "")
    return {
        "probed": bool(stream),
        "codec": codec,
        "codec_label": codec_label,
        "container": container,
        "bitrate_kbps": round(int(bitrate) / 1000) if bitrate else None,
        "channels": int(stream["channels"]) if stream.get("channels") else None,
        "sample_rate_hz": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
    }


def probe_audio_summary(
    path: Path,
    probe_reader: CachedAudioProbeReader | None = None,
) -> dict[str, Any]:
    files = source_audio_files(path)
    reader = probe_reader or probe_audio_file
    return summarize_audio_probes(files, [reader(audio_file) for audio_file in files])


def cached_audio_summary(path: Path) -> dict[str, Any] | None:
    with M4B_DISCOVERY_CACHE_LOCK:
        cache = load_discovery_cache(M4B_DISCOVERY_CACHE)
    target = str(path)
    for search in cache.get("searches", {}).values():
        for candidates in (search.get("results", {}) or {}).values():
            for candidate in candidates:
                if candidate.get("path") == target:
                    summary = candidate.get("audio_summary")
                    if isinstance(summary, dict) and summary:
                        return summary
    return None


def sidecar_audio_files(payload: dict[str, Any], fallback: Path) -> list[Path]:
    root = payload.get("sidecar", payload) if "sidecar" in payload else payload
    chapter_files = (root.get("source", {}) or {}).get("chapter_files", []) or []
    files = [
        Path(file_path)
        for file_path in chapter_files
        if Path(file_path).is_file() and is_audio_file(Path(file_path))
    ]
    return files or source_audio_files(fallback)


def discover_sidecars(path: Path) -> list[Path]:
    folder = path if path.is_dir() else path.parent
    sidecars: list[Path] = []
    lf = folder / "libraforge.json"
    if lf.is_file():
        try:
            payload = json.loads(lf.read_text(encoding="utf-8"))
            if payload.get("sidecar") or payload.get("marker"):
                sidecars.append(lf)
        except (OSError, json.JSONDecodeError):
            pass
    sidecars.extend(sorted(folder.glob(f"*{M4B_TOOL_SIDECAR_SUFFIX}")))
    return [s for s in sidecars if s.is_file()]


def pick_sidecar(path: Path, sidecars: list[Path]) -> Path | None:
    if path.is_file() and path.name.endswith(M4B_TOOL_SIDECAR_SUFFIX):
        return path

    folder = path if path.is_dir() else path.parent

    # Prefer folder-level libraforge.json when it has sidecar data
    lf = folder / "libraforge.json"
    if lf in sidecars:
        return lf

    preferred = folder / f"{folder.name}{M4B_TOOL_SIDECAR_SUFFIX}"
    if preferred in sidecars:
        return preferred

    if path.is_file():
        per_file = path.with_name(f"{path.name}{M4B_TOOL_SIDECAR_SUFFIX}")
        if per_file in sidecars:
            return per_file

        # No name-based match. A folder can hold several independent,
        # single-file books (e.g. a mixed classics dump) where only some
        # have been processed -- guessing by position (e.g. sidecars[0])
        # would silently attach an unrelated sibling's metadata. Every
        # sidecar records the exact file(s) it covers under source.*, so
        # trust only a candidate that explicitly claims this file.
        target_str = str(path)
        for sidecar in sidecars:
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            source = (payload.get("sidecar") or payload).get("source", {}) or {}
            covered = set(source.get("chapter_files") or [])
            root_file = source.get("root_file")
            if root_file:
                covered.add(root_file)
            if target_str in covered:
                return sidecar
        return None

    # `path` is a directory with no folder-level or preferred-name match
    # above. A single remaining sidecar unambiguously belongs to it (e.g.
    # a multi-part group's sidecar named after its anchor file); with 2+
    # candidates we can't tell which one covers this folder.
    return sidecars[0] if len(sidecars) == 1 else None


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {path}: {exc}") from exc


# Loading the fixer re-execs the module, which is too costly to do on every request.
# Cache by (path, mtime) so edits to the bind-mounted script are still picked up.
_fixer_module_cache: dict[tuple[str, int], Any] = {}


def load_fixer_module(script_name: str = ""):
    script_path = live_script_path(script_name, "fixer")
    try:
        mtime = script_path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(script_path), mtime)
    cached = _fixer_module_cache.get(key)
    if cached is not None:
        return cached

    module_name = f"audible_fixer_{re.sub(r'[^a-zA-Z0-9_]', '_', script_name)}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail=f"Could not load fixer script: {script_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _fixer_module_cache.clear()  # only keep the current script version
    _fixer_module_cache[key] = module
    return module


_ORGANIZER_MODULE_CACHE: dict[tuple[str, int], Any] = {}


def load_organizer_module(script_name: str = ""):
    """Load the organizer script in-process, mirroring load_fixer_module()'s
    mtime-cached pattern, so naming-template validate/preview endpoints can
    call its pure functions directly instead of shelling out to a subprocess.
    """
    script_name = script_name or default_organizer_script()
    script_path = live_script_path(script_name, "organizer")
    try:
        mtime = script_path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(script_path), mtime)
    cached = _ORGANIZER_MODULE_CACHE.get(key)
    if cached is not None:
        return cached

    module_name = f"audiobook_organizer_{re.sub(r'[^a-zA-Z0-9_]', '_', script_name)}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail=f"Could not load organizer script: {script_name}")
    module = importlib.util.module_from_spec(spec)
    # The organizer script uses `from __future__ import annotations` with
    # module-level @dataclass classes; dataclass's annotation resolution
    # looks the module up via sys.modules[cls.__module__], so it must be
    # registered there before exec_module runs the class bodies.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _ORGANIZER_MODULE_CACHE.clear()
    _ORGANIZER_MODULE_CACHE[key] = module
    return module


_REVIEW_MODULE_CACHE: dict[tuple[str, int], Any] = {}


def load_review_module():
    """Dynamically load scripts/review-libraforge-report.py, mirroring
    load_fixer_module()'s pattern (cached by mtime) so Enrichment Forge
    reuses its normalize_series() instead of duplicating series-name
    cleanup logic.
    """
    script_path = SCRIPTS_DIR / "review-libraforge-report.py"
    try:
        mtime = script_path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(script_path), mtime)
    cached = _REVIEW_MODULE_CACHE.get(key)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("review_libraforge_report", script_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail="Could not load review-libraforge-report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _REVIEW_MODULE_CACHE.clear()
    _REVIEW_MODULE_CACHE[key] = module
    return module


def scan_fixer_module():
    """Return the active fixer module (cached)."""
    return load_fixer_module(default_fixer_script())


def build_context_clues(
    fixer_module,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = metadata or {}
    title = fixer_module.clean_text(metadata.get("title", ""))
    subtitle = fixer_module.clean_text(metadata.get("subtitle", ""))
    raw_title = fixer_module.clean_text(metadata.get("raw_title", "") or title or subtitle)
    if not raw_title:
        raw_title = title or subtitle

    clues = {
        "raw_title": raw_title,
        "title": title or raw_title,
        "series": fixer_module.clean_text(metadata.get("series", "")),
        "book_number": fixer_module.normalize_book_number(str(metadata.get("sequence", "") or "").strip()),
        "book_number_source": "manual" if metadata.get("sequence") else "",
        "author": fixer_module.clean_author_value(metadata.get("author", "")),
        "narrator": fixer_module.clean_text(metadata.get("narrator", "")),
        "album": title or raw_title,
        "local_duration_minutes": metadata.get("local_duration_minutes"),
    }
    return clues


def search_audible_candidates(
    *,
    query: str,
    auth_file: str,
    metadata: dict[str, Any] | None = None,
    limit: int = 10,
    script_name: str = "",
) -> dict[str, Any]:
    fixer_module = load_fixer_module(script_name or default_fixer_script())
    clues = build_context_clues(fixer_module, metadata)

    direct_query = fixer_module.clean_text(query)
    queries: list[str] = []
    if direct_query:
        # Explicit query overrides auto-derived ones so editing the field has effect
        queries.append(direct_query)
    else:
        queries.extend(fixer_module.build_search_queries_from_clues(clues))

    unique_queries: list[str] = []
    seen_queries = set()
    for item in queries:
        key = item.lower()
        if item and key not in seen_queries:
            unique_queries.append(item)
            seen_queries.add(key)

    auth = audible.Authenticator.from_file(auth_file)
    client = audible.Client(auth=auth)

    by_asin: dict[str, dict[str, Any]] = {}

    # If the user typed a bare ASIN (B0... pattern), try a direct product lookup
    # first -- Audible's text search does not find books by ASIN string.
    _asin_re = re.compile(r"^[Bb]0[A-Za-z0-9]{8}$")
    if direct_query and _asin_re.match(direct_query.strip()):
        asin_upper = direct_query.strip().upper()
        product = fixer_module.audible_lookup_by_asin(client, asin_upper)
        if product:
            asin_key = str(product.get("asin", "") or asin_upper)
            score = fixer_module.score_product_for_metadata(
                clues, product, clues.get("local_duration_minutes")
            )
            metadata_preview = fixer_module.metadata_from_product(product, clues, score)
            metadata_by_mode = {
                mode: fixer_module.metadata_from_product(product, clues, score, requested_edit_mode=mode)
                for mode in ("full", "series_only")
            }
            allowed_edit_modes = ["full"]
            if metadata_by_mode["series_only"].get("series"):
                allowed_edit_modes.append("series_only")
            by_asin[asin_key] = {
                "asin": asin_key,
                "query": f"ASIN:{asin_upper}",
                "score": score,
                "product": product,
                "metadata": metadata_preview,
                "metadata_by_mode": metadata_by_mode,
                "allowed_edit_modes": allowed_edit_modes,
            }
            unique_queries = []  # direct hit is definitive, skip text search

    for current_query in unique_queries[:5]:
        products = fixer_module.audible_search(client, current_query, max(limit, 10))
        for product in products:
            asin = str(product.get("asin", "") or "")
            if not asin:
                continue
            score = fixer_module.score_product_for_metadata(
                clues,
                product,
                clues.get("local_duration_minutes"),
            )
            metadata_preview = fixer_module.metadata_from_product(product, clues, score)
            metadata_by_mode = {
                mode: fixer_module.metadata_from_product(
                    product,
                    clues,
                    score,
                    requested_edit_mode=mode,
                )
                for mode in ("full", "series_only")
            }
            allowed_edit_modes = ["full"]
            if metadata_by_mode["series_only"].get("series"):
                allowed_edit_modes.append("series_only")
            existing = by_asin.get(asin)
            if existing and existing["score"] >= score:
                continue
            by_asin[asin] = {
                "asin": asin,
                "query": current_query,
                "score": score,
                "product": product,
                "metadata": metadata_preview,
                "metadata_by_mode": metadata_by_mode,
                "allowed_edit_modes": allowed_edit_modes,
            }

    results: list[dict[str, Any]] = []
    for item in sorted(by_asin.values(), key=lambda value: value["score"], reverse=True)[:limit]:
        product = item["product"]
        metadata_preview = item["metadata"]
        results.append(
            {
                "asin": item["asin"],
                "query": item["query"],
                "score": item["score"],
                "edit_mode": metadata_preview.get("edit_mode", ""),
                "recommended_edit_mode": metadata_preview.get(
                    "recommended_edit_mode",
                    metadata_preview.get("edit_mode", ""),
                ),
                "allowed_edit_modes": item["allowed_edit_modes"],
                "title": product.get("title", "") or "",
                "subtitle": product.get("subtitle", "") or "",
                "authors": fixer_module.get_people(product, "authors"),
                "narrators": fixer_module.get_people(product, "narrators"),
                "series": metadata_preview.get("series", ""),
                "sequence": metadata_preview.get("audible_sequence", ""),
                "duration_minutes": metadata_preview.get("audible_duration_minutes"),
                "year": metadata_preview.get("audible_year", ""),
                "cover_url": metadata_preview.get("cover_url", ""),
                "summary": metadata_preview.get("summary", ""),
                "chosen_metadata": {
                    "title": metadata_preview.get("title", ""),
                    "subtitle": metadata_preview.get("subtitle", ""),
                    "author": metadata_preview.get("author", ""),
                    "narrator": metadata_preview.get("narrator", ""),
                    "series": metadata_preview.get("series", ""),
                    "sequence": metadata_preview.get("sequence", ""),
                    "year": metadata_preview.get("year", ""),
                    "summary": metadata_preview.get("summary", ""),
                    "cover_url": metadata_preview.get("cover_url", ""),
                    "asin": metadata_preview.get("asin", ""),
                    "genre": metadata_preview.get("genre", ""),
                },
                "chosen_metadata_by_mode": {
                    mode: {
                        "title": preview.get("title", ""),
                        "subtitle": preview.get("subtitle", ""),
                        "author": preview.get("author", ""),
                        "narrator": preview.get("narrator", ""),
                        "series": preview.get("series", ""),
                        "sequence": preview.get("sequence", ""),
                        "year": preview.get("year", ""),
                        "summary": preview.get("summary", ""),
                        "cover_url": preview.get("cover_url", ""),
                        "asin": preview.get("asin", ""),
                        "genre": preview.get("genre", ""),
                    }
                    for mode, preview in item["metadata_by_mode"].items()
                },
                "duration": metadata_preview.get("duration", {}),
            }
        )

    return {"queries": unique_queries, "results": results}


class RunRequest(BaseModel):
    script_name: str
    target_path: str = Field(default="/audiobooks")
    auth_file: str = Field(default="/auth/audible-metadata.json")

    apply: bool = False
    backup: bool = False
    restore_metadata: bool = False
    force: bool = False
    force_original: bool = False
    cover_if_missing: bool = False
    replace_cover: bool = False
    metadata_json_only: bool = False

    min_score: float | None = 0.70
    limit: int | None = 50
    max_files: int | None = 0
    duration_review_threshold: float | None = 10.0
    skip_patterns: list[str] = Field(default_factory=list)
    ignored_folders: list[str] = Field(default_factory=list)

    workers: int | None = None
    write_workers: int | None = None
    api_delay_ms: int = 0
    write_mode: str = "smart"
    provider: str = "audible"
    abs_provider: str = "audible"
    enable_goodreads_fallback: bool = False
    debug_trace: bool = False
    debug_trace_file: str = ""


class M4BMetadataForm(BaseModel):
    title: str = ""
    subtitle: str = ""
    author: str = ""
    narrator: str = ""
    series: str = ""
    sequence: str = ""
    year: str = ""
    summary: str = ""
    cover_url: str = ""
    asin: str = ""
    local_duration_minutes: float | None = None


class M4BLoadRequest(BaseModel):
    path: str


class M4BDiscoverRequest(BaseModel):
    path: str = Field(default="/audiobooks")
    mode: str = Field(default="multipart")
    script_name: str = Field(default_factory=default_fixer_script)
    limit: int = Field(default=200, ge=1, le=500)
    cache_action: str = Field(default="refresh")


class M4BDiscoveryCacheStatusRequest(BaseModel):
    path: str = Field(default="/audiobooks")
    script_name: str = Field(default_factory=default_fixer_script)


class M4BRefreshAudioProfilesRequest(BaseModel):
    path: str = Field(default="/audiobooks")
    script_name: str = Field(default_factory=default_fixer_script)


class M4BSaveRequest(BaseModel):
    path: str
    metadata: M4BMetadataForm
    source_path: str = ""
    sidecar_path: str = ""


class AudibleSearchRequest(BaseModel):
    query: str = ""
    auth_file: str = Field(default="/auth/audible-metadata.json")
    metadata: M4BMetadataForm = Field(default_factory=M4BMetadataForm)
    limit: int = 10
    script_name: str = Field(default_factory=default_fixer_script)


class ManualReviewLoadRequest(BaseModel):
    path: str
    script_name: str = Field(default_factory=default_fixer_script)
    use_backup_tags: bool = False


class ManualReviewEbookLoadRequest(BaseModel):
    path: str


class ManualReviewEbookApplyRequest(BaseModel):
    path: str
    book: dict[str, Any]


class ManualReviewDiscoverRequest(BaseModel):
    path: str = Field(default="/audiobooks")
    script_name: str = Field(default_factory=default_fixer_script)


class ManualReviewApplyRequest(BaseModel):
    path: str
    script_name: str = Field(default_factory=default_fixer_script)
    selected_result: dict[str, Any]
    edit_mode: str
    backup: bool = False
    cover_if_missing: bool = False
    replace_cover: bool = False
    writer: str = "auto"
    metadata_override: dict[str, Any] = Field(default_factory=dict)
    # "fill": only write fields with a value; blank fields are left untouched.
    # "overwrite": write every field exactly as shown, including blanks (a
    # blank clears that tag). See docs/design/manual-review-apply-rewrite-rules.md.
    write_policy: str = "fill"


class ManualReviewEditRequest(BaseModel):
    """Direct field editing, no match/search involved -- see
    docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
    Always writes with field_policy="overwrite" (a blank field here always
    clears that tag) and score=1.0 (no match to carry a confidence score
    from).
    """
    path: str
    script_name: str = Field(default_factory=default_fixer_script)
    title: str
    subtitle: str = ""
    author: str
    narrator: str = ""
    series: str = ""
    sequence: str = ""
    year: str = ""
    asin: str = ""
    isbn: str = ""
    publisher: str = ""
    genre: str = ""
    language: str = ""
    explicit: bool = False
    summary: str = ""
    cover_url: str = ""


class SeriesGroupBookEntry(BaseModel):
    path: str
    sequence: str = ""


class SeriesGroupApplyRequest(BaseModel):
    """Bulk field edit across several books at once (Fix Series). A blank
    shared field is left untouched on every book; a filled one overwrites
    it on every included book, even one that already had a value -- see
    docs/design/2026-07-09-fix-series-cross-book-editor-design.md.
    """
    script_name: str = Field(default_factory=default_fixer_script)
    series: str = ""
    author: str = ""
    genre: str = ""
    narrator: str = ""
    language: str = ""
    explicit: bool = False
    # Whether the Explicit checkbox was touched at all -- a bare `explicit:
    # bool` can't distinguish "leave untouched" from "set to False", since
    # both are the JSON value `false`.
    explicit_set: bool = False
    books: list[SeriesGroupBookEntry]


class M4BRunRequest(BaseModel):
    input_path: str
    output_path: str
    save_sidecar: bool = True
    sidecar_path: str = ""
    metadata: M4BMetadataForm = Field(default_factory=M4BMetadataForm)
    force: bool = True
    jobs: int = Field(default=4, ge=0, le=12)
    no_conversion: bool = False
    use_filenames_as_chapters: bool = False
    audio_codec: str = "libfdk_aac"
    audio_bitrate: str = "128k"
    audio_samplerate: int = 44100
    audio_channels: int | None = None


class OrganizerRunRequest(BaseModel):
    root_path: str = Field(default="/audiobooks/_unorganized")
    destination_root: str = Field(default="/audiobooks")
    script_name: str = Field(default_factory=default_organizer_script)
    apply: bool = False
    m4b_only: bool = False
    include_existing_book_folders: bool = False
    allow_unknown_author: bool = False
    no_companions: bool = False
    rebuild_structure_cache: bool = False
    index_only: bool = False
    consolidate_structures: bool = False
    remove_empty_dirs: bool = False
    max_items: int = 0
    progress_every: int = 1
    skip_patterns: list[str] = Field(default_factory=list)
    acknowledge_no_sidecars: bool = False
    naming_template: str = ""
    use_default_scheme: bool = True


class OrganizerNamingTemplateValidateRequest(BaseModel):
    template: str
    script_name: str = Field(default_factory=default_organizer_script)


class OrganizerNamingTemplatePreviewRequest(BaseModel):
    template: str
    root_path: str = Field(default="/audiobooks/_unorganized")
    destination_root: str = Field(default="/audiobooks")
    script_name: str = Field(default_factory=default_organizer_script)
    limit: int = 3


class OrganizerNamingTemplateExamplePreviewRequest(BaseModel):
    template: str
    script_name: str = Field(default_factory=default_organizer_script)


class TitleNoiseCustomPattern(BaseModel):
    id: str = ""
    label: str
    description: str = ""
    pattern: str
    enabled: bool = True


class TitleNoisePolicyUpdate(BaseModel):
    disabled_defaults: list[str] = Field(default_factory=list)
    custom_patterns: list[TitleNoiseCustomPattern] = Field(default_factory=list)


class PublisherEntry(BaseModel):
    id: str = ""
    name: str
    aliases: list[str] = Field(default_factory=list)
    special_provider: str | None = None
    source: str = "custom"
    enabled: bool = True


class PublisherPolicyUpdate(BaseModel):
    disabled_defaults: list[str] = Field(default_factory=list)
    custom_publishers: list[PublisherEntry] = Field(default_factory=list)


@dataclass
class RunState:
    id: str
    status: str = "queued"
    phase: str = "queued"
    phase_label: str = "Queued"
    phase_detail: str = "Waiting to start"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    command: list[str] = field(default_factory=list)
    log_path: Path | None = None
    report_path: Path | None = None
    process: subprocess.Popen | None = None
    returncode: int | None = None
    error: str = ""
    current_file: str = ""
    run_type: str = ""
    current: int = 0
    total: int = 0
    percent: float = 0.0
    write_current: int = 0
    in_write_phase: bool = False
    lines_tail: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    files_by_category: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    parser_state: dict[str, Any] = field(default_factory=dict)
    report_items: list[dict[str, Any]] = field(default_factory=list)
    report_item_updates: dict[str, dict[str, Any]] = field(default_factory=dict)


runs: dict[str, RunState] = {}
runs_lock = threading.Lock()


def set_run_phase(
    state: RunState,
    phase: str,
    label: str,
    detail: str = "",
) -> None:
    state.phase = phase
    state.phase_label = label
    state.phase_detail = detail
    state.stats["phase"] = phase
    state.stats["phase_label"] = label
    state.stats["phase_detail"] = detail


def set_terminal_phase(state: RunState) -> None:
    set_run_phase(state, *terminal_phase(state.status, state.error))


def initial_stats(threshold: float) -> dict[str, Any]:
    return {
        "found": 0,
        "matched": 0,
        "skipped": 0,
        "failed": 0,
        "smart_skipped": 0,
        "mode_breakdown": {"full": 0, "series_only": 0, "none": 0, "unknown": 0},
        "duration_breakdown": {
            "perfect": 0,
            "strong": 0,
            "acceptable": 0,
            "mismatch": 0,
            "unknown": 0,
        },
        "large_duration_threshold": threshold,
        "large_duration_items": [],
        "skip_reasons": {},
        "error_count": 0,
        "provider_breakdown": {},
        "search_workers": None,
        "goodreads_circuit_tripped": False,
    }


def derive_manual_review_items(
    stats: dict[str, Any],
    files_by_category: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}

    def ensure(path: str) -> dict[str, Any]:
        entry = items.setdefault(path, {"path": path, "reasons": []})
        return entry

    for path in [item.get("path", "") for item in files_by_category.get("mode:none", []) if item.get("path")]:
        ensure(path)["reasons"].append("mode:none")

    for item in files_by_category.get("status:skipped", []):
        path = item.get("path", "")
        if not path:
            continue
        reason = item.get("title", "")
        # Intentional skips (pattern matches and already-processed markers) are
        # working as designed -- they don't belong in manual review.
        # "already manually applied" is handled via the status:manual_applied category below.
        if reason.startswith("matched skip pattern:") or reason in {"already processed", "already manually applied"}:
            continue
        # Map verbose skip reasons to concise UI labels.
        if reason.startswith("duplicate Audible ASIN") or "asin conflict" in reason.lower():
            label = "asin conflict"
        elif "no usable Audible match" in reason:
            label = "no match"
        elif reason.startswith("score below minimum"):
            label = "low score"
        elif "missing title or author" in reason:
            label = "missing metadata"
        elif "match marked unsafe" in reason or "no editable metadata" in reason:
            label = "unsafe match"
        elif "no useful embedded metadata" in reason:
            label = "no metadata"
        else:
            label = "status:skipped"
        ensure(path)["reasons"].append(label)

    for path in [item.get("path", "") for item in files_by_category.get("mode:series_only", []) if item.get("path")]:
        ensure(path)["reasons"].append("mode:series_only")

    for path in [item.get("path", "") for item in files_by_category.get("review:duration-tiebreak", []) if item.get("path")]:
        ensure(path)["reasons"].append("duration tie-break")

    for path in [item.get("path", "") for item in files_by_category.get("status:manual_applied", []) if item.get("path")]:
        ensure(path)["reasons"].append("manually applied")

    threshold = stats.get("large_duration_threshold", 10)
    for item in stats.get("large_duration_items", []):
        path = item.get("path", "")
        if not path:
            continue
        entry = ensure(path)
        entry["reasons"].append(f"duration>{threshold:g}%")
        entry["diff_percent"] = item.get("diff_percent")

    for entry in items.values():
        entry["reasons"] = sorted(set(entry["reasons"]))

    _skip_labels = {"no match", "asin conflict", "low score", "missing metadata", "unsafe match", "no metadata", "status:skipped"}

    return sorted(
        items.values(),
        key=lambda item: (
            not any(r in _skip_labels for r in item["reasons"]),
            "mode:none" not in item["reasons"],
            item["path"],
        ),
    )


def category_key(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def add_category(state: RunState, kind: str, value: str, path: str, title: str = "") -> None:
    key = category_key(kind, value)
    state.files_by_category.setdefault(key, [])
    if not any(item.get("path") == path for item in state.files_by_category[key]):
        state.files_by_category[key].append({"path": path, "title": title})


def _fixer_percent(state: RunState) -> float:
    """Overall percent from 3 phases: scan 5%, match 70%, write 25%."""
    if not state.total:
        return 0.0
    scan = 5.0
    match = state.current / state.total * 70
    write = state.write_current / state.total * 25
    return round(scan + match + write, 2)


def merge_report_item_update(state: RunState, update: dict[str, Any]) -> None:
    path = str(update.get("path", "") or "")
    if not path:
        return
    clean_update = {k: v for k, v in update.items() if k != "path"}
    if not clean_update:
        return
    for item in state.report_items:
        if item.get("path") == path:
            item.update(clean_update)
            return
    state.report_item_updates.setdefault(path, {}).update(clean_update)


def parse_line(state: RunState, line: str, threshold: float) -> None:
    if line.startswith("REPORT_ITEM_JSON: "):
        try:
            item = json.loads(line[18:])
            update = state.report_item_updates.get(item.get("path", ""))
            if update:
                item.update(update)
            state.report_items.append(item)
        except Exception:
            pass
        return
    if line.startswith(WRITE_ACTION_PREFIX):
        try:
            update = json.loads(line[len(WRITE_ACTION_PREFIX):])
            merge_report_item_update(state, update)
            path = str(update.get("path", "") or state.current_file)
            action = str(update.get("write_action", "") or "")
            if path and action:
                add_category(state, "write", action, path, str(update.get("write_note", "") or ""))
        except Exception:
            pass
        return

    detected_phase = fixer_phase_for_line(line, state.current_file)
    if detected_phase:
        set_run_phase(state, *detected_phase)
        phase_id = detected_phase[0]
        if phase_id == "recording" and state.total:
            state.write_current += 1
            state.percent = _fixer_percent(state)
        elif phase_id == "summarizing":
            state.percent = max(state.percent, 98.0)

    # NO-OP and Smart-skip: tags already matched, no write needed. They only
    # appear in Pass 2 output, so always count them toward write_current.
    stripped = line.strip()
    if stripped.startswith("NO-OP") or stripped.startswith("Smart-skip"):
        state.write_current += 1
        state.percent = _fixer_percent(state)

    # Once the end-of-run summary/report region begins, no further lines belong to
    # a processed item. Clear current_file so per-item reason lines re-printed in
    # the reports (e.g. "(chose ... on duration)", "abs-agg endpoint") are not
    # misattributed to the last processed book.
    if SECTION_END_RE.match(line):
        state.current_file = ""
        return

    m = FOUND_RE.match(line)
    if m:
        state.total = int(m.group(1))
        state.stats["found"] = int(m.group(1))
        state.percent = 5.0  # scan phase complete
        set_run_phase(
            state,
            "preparing",
            "Preparing run",
            f"Found {state.total} processing items",
        )
        return

    m = SEARCH_WORKERS_RE.match(line)
    if m:
        state.stats["search_workers"] = int(m.group(1))
        return

    if line == GOODREADS_CIRCUIT_TRIPPED_SENTINEL:
        state.stats["goodreads_circuit_tripped"] = True
        return

    m = PASS1_PROGRESS_RE.match(line)
    if m:
        state.parser_state["pass1_progress_mode"] = True
        state.current = int(m.group(1))
        state.total = int(m.group(2))
        state.percent = _fixer_percent(state)
        set_run_phase(
            state,
            "matching",
            "Matching metadata",
            f"Completed {state.current} of {state.total}",
        )
        return

    m = PROCESSING_RE.match(line)
    if m:
        item_index = int(m.group(1))
        total = int(m.group(2))
        state.total = total
        state.current_file = m.group(3).strip()
        if state.parser_state.get("pass1_progress_mode"):
            detail = f"Completed {state.current} of {state.total} · result item {item_index}"
        else:
            state.current = item_index
            state.percent = _fixer_percent(state)
            detail = f"Item {state.current} of {state.total}"
        set_run_phase(
            state,
            "inspecting",
            "Inspecting metadata",
            detail,
        )
        return

    # Pass 2 write header -- distinct from Processing: so match current is not overwritten.
    m = WRITING_RE.match(line)
    if m:
        state.current = state.total  # match phase is done; lock it at 100%
        state.in_write_phase = True
        state.current_file = m.group(3).strip()
        state.percent = _fixer_percent(state)
        set_run_phase(
            state,
            "writing",
            "Writing metadata",
            f"Writing {state.write_current + 1} of {state.total}",
        )
        return

    # Pass 2 completion for books that were skipped or failed during Pass 1.
    # Their skip/error reasons were already counted in Pass 1; here we only
    # advance write_current so the write bar stays accurate.
    if WRITE_SKIP_RE.match(line) and state.in_write_phase and state.total:
        state.write_current += 1
        state.percent = _fixer_percent(state)
        return

    restore = re.match(r"^\[(\d+)/(\d+)\]\s+Restoring:\s+(.+)$", line)
    if restore:
        state.current = int(restore.group(1))
        state.total = int(restore.group(2))
        state.current_file = restore.group(3).strip()
        state.percent = round((state.current / state.total) * 100, 2) if state.total else 0.0
        set_run_phase(
            state,
            "restoring",
            "Restoring metadata",
            f"Item {state.current} of {state.total}",
        )
        return

    m = SUMMARY_RE.match(line)
    if m:
        state.stats[m.group(1).lower().replace("-", "_")] = int(m.group(2))
        return

    m = FILL_STATS_RE.match(line)
    if m:
        key = {"Books filled": "filled", "Already complete": "complete", "ASIN filled": "asin"}[
            m.group(1)
        ]
        state.stats.setdefault("fill_breakdown", {})[key] = int(m.group(2))
        return

    m = MODE_RE.match(line)
    if m and state.current_file:
        mode = m.group(1)
        if mode in {"full", "series_only", "none"}:
            state.stats["mode_breakdown"].setdefault(mode, 0)
            state.stats["mode_breakdown"][mode] += 1
            add_category(state, "mode", mode, state.current_file)
        return

    m = GROUPED_RE.match(line)
    if m and state.current_file:
        add_category(state, "group", "multi-file", state.current_file)
        return

    m = DURATION_STATUS_RE.match(line)
    if m and state.current_file:
        status = m.group(1)
        state.stats["duration_breakdown"].setdefault(status, 0)
        state.stats["duration_breakdown"][status] += 1
        add_category(state, "duration", status, state.current_file)
        return

    m = DIFF_RE.match(line)
    if m and state.current_file:
        diff = float(m.group(1))
        if diff > threshold:
            if not any(item.get("path") == state.current_file for item in state.stats["large_duration_items"]):
                state.stats["large_duration_items"].append({"path": state.current_file, "diff_percent": diff})
            add_category(state, "duration", f">{threshold:g}%", state.current_file)
        return

    m = SKIP_RE.match(line)
    if m and state.current_file:
        reason = m.group(1).strip()
        state.stats["skip_reasons"].setdefault(reason, 0)
        state.stats["skip_reasons"][reason] += 1
        add_category(state, "status", "skipped", state.current_file, reason)
        if reason == "already manually applied":
            add_category(state, "status", "manual_applied", state.current_file)
        # In write phase, a skip means this item is done (no write needed).
        if state.in_write_phase and state.total:
            state.write_current += 1
            state.percent = _fixer_percent(state)
        return

    m = ERROR_RE.match(line)
    if m and state.current_file:
        state.stats["error_count"] += 1
        add_category(state, "status", "error", state.current_file, m.group(1).strip())
        if state.in_write_phase and state.total:
            state.write_current += 1
            state.percent = _fixer_percent(state)
        return

    if state.current_file and MATCH_RE.match(line):
        add_category(state, "status", "matched", state.current_file)
        return

    if state.current_file and AMBIG_RESOLVED_RE.search(line):
        add_category(state, "review", "duration-tiebreak", state.current_file)
        return

    m = SOURCE_RE.match(line)
    if m and state.current_file:
        provider = m.group(1)
        add_category(state, "provider", provider, state.current_file)
        state.stats.setdefault("provider_breakdown", {}).setdefault(provider, 0)
        state.stats["provider_breakdown"][provider] += 1
        return

    m = FILL_ITEM_RE.match(line)
    if m and state.current_file:
        filled = m.group(1)
        if filled:
            add_category(state, "fill", "filled", state.current_file, filled.strip())
            fields = {f.strip().lower() for f in filled.split(",")}
            if "asin" in fields:
                add_category(state, "fill", "asin", state.current_file)
        else:
            add_category(state, "fill", "complete", state.current_file)
        return


def build_report_items(
    files_by_category: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    """Normalize faceted categories into one canonical record per path."""
    items_by_path: dict[str, dict[str, Any]] = {}
    for category, category_items in files_by_category.items():
        for category_item in category_items:
            path = str(category_item.get("path", "") or "")
            if not path:
                continue
            item = items_by_path.setdefault(
                path,
                {"path": path, "title": "", "categories": [], "category_details": {}},
            )
            if category not in item["categories"]:
                item["categories"].append(category)
            detail = str(category_item.get("title", "") or "")
            if detail:
                item["category_details"][category] = detail
                # status: details are skip reasons; fill: details are field lists —
                # neither is a real book title, so don't let them become the generic
                # title other categories fall back to.
                if (
                    not category.startswith("status:")
                    and not category.startswith("fill:")
                    and not item["title"]
                ):
                    item["title"] = detail

    items = sorted(items_by_path.values(), key=lambda item: item["path"])
    categories: dict[str, list[int]] = {}
    for item_id, item in enumerate(items, start=1):
        item["id"] = item_id
        item["categories"].sort()
        if not item["category_details"]:
            item.pop("category_details")
        for category in item["categories"]:
            categories.setdefault(category, []).append(item_id)
    return items, dict(sorted(categories.items()))


def expand_report_categories(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build the legacy API category shape from a normalized report."""
    if "files_by_category" in report:
        return report.get("files_by_category", {}) or {}
    items_by_id = {
        item.get("id"): item
        for item in report.get("items", [])
        if item.get("id") is not None
    }
    expanded: dict[str, list[dict[str, Any]]] = {}
    for category, item_ids in (report.get("categories", {}) or {}).items():
        rows = []
        for item_id in item_ids:
            item = items_by_id.get(item_id)
            if not item:
                continue
            detail = (item.get("category_details", {}) or {}).get(category, "")
            rows.append({
                "path": item.get("path", ""),
                "title": detail or item.get("title", ""),
            })
        expanded[category] = rows
    return expanded


def report_for_api(report: dict[str, Any]) -> dict[str, Any]:
    result = dict(report)
    result["files_by_category"] = expand_report_categories(report)
    result.setdefault(
        "manual_review_items",
        derive_manual_review_items(result.get("stats", {}), result["files_by_category"]),
    )
    return result

def write_final_report(state: RunState) -> None:
    items, categories = build_report_items(state.files_by_category)
    manual_review_items = derive_manual_review_items(state.stats, state.files_by_category)
    report = {
        "schema_version": 2,
        "id": state.id,
        "status": state.status,
        "phase": state.phase,
        "phase_label": state.phase_label,
        "phase_detail": state.phase_detail,
        "started_at": state.started_at,
        "finished_at": state.finished_at,
        "returncode": state.returncode,
        "command": state.command,
        "stats": state.stats,
        "items": items,
        "categories": categories,
        "manual_review_items": manual_review_items,
        "report_items": state.report_items,
        "log_file": state.log_path.name if state.log_path else None,
    }
    state.report_path = REPORTS_DIR / f"{state.id}.report.json"
    state.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _prune_reports()


def stream_process_output(
    state: RunState,
    cmd: list[str],
    threshold: float | None = None,
    line_parser: Callable[[RunState, str], bool | None] | None = None,
) -> None:
    with state.log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("COMMAND:\n")
        log.write(" ".join(shlex.quote(part) for part in cmd) + "\n\n")
        log.flush()

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            start_new_session=True,
        )
        state.process = proc

        assert proc.stdout is not None
        for line in proc.stdout:
            stripped = line.rstrip("\n")
            keep_line = True
            if line_parser is not None:
                parser_result = line_parser(state, stripped)
                if parser_result is False:
                    keep_line = False
            elif threshold is not None:
                parse_line(state, stripped, threshold)
            if keep_line:
                log.write(line)
                log.flush()
                state.lines_tail.append(stripped)
                state.lines_tail = state.lines_tail[-250:]

        state.returncode = proc.wait()


def _fixer_major_version(script_name: str) -> int:
    m = re.search(r"-v(\d+)", script_name)
    return int(m.group(1)) if m else 0


def build_command(req: RunRequest) -> tuple[list[str], float]:
    script_path = live_script_path(req.script_name, "fixer")

    cmd = ["python", "-u", str(script_path), req.target_path]

    if req.restore_metadata:
        cmd.append("--restore-metadata")
    else:
        if req.auth_file:
            cmd += ["--auth-file", req.auth_file]

    if req.apply:
        cmd.append("--apply")
    if req.backup:
        cmd.append("--backup")
    if req.force:
        cmd.append("--force")
    if req.force_original:
        cmd.append("--force-original")
    if req.cover_if_missing:
        cmd.append("--cover-if-missing")
    if req.replace_cover:
        cmd.append("--replace-cover")
    if req.metadata_json_only:
        cmd.append("--metadata-json-only")
    if req.min_score is not None:
        cmd += ["--min-score", str(req.min_score)]
    if req.limit is not None:
        cmd += ["--limit", str(req.limit)]
    if req.max_files is not None and req.max_files > 0:
        cmd += ["--max-files", str(req.max_files)]
    if req.duration_review_threshold is not None:
        cmd += ["--duration-review-threshold", str(req.duration_review_threshold)]
    for pattern in req.skip_patterns:
        pattern = pattern.strip()
        if pattern:
            cmd += ["--skip-pattern", pattern]
    for folder in req.ignored_folders:
        folder = folder.strip()
        if folder:
            cmd += ["--ignore-folder", folder]

    if _fixer_major_version(req.script_name) >= 5:
        if req.workers is not None and req.workers > 0:
            cmd += ["--workers", str(req.workers)]
        if req.write_workers is not None and req.write_workers > 0:
            cmd += ["--write-workers", str(req.write_workers)]
        if req.api_delay_ms > 0:
            cmd += ["--api-delay-ms", str(req.api_delay_ms)]
        if req.write_mode and req.write_mode != "smart":
            cmd += ["--write-mode", req.write_mode]
        if req.provider == "abs":
            cmd += ["--provider", "abs"]
            cmd += ["--abs-provider", req.abs_provider]
            cmd += ["--abs-url", _get_abs_url()]
            cmd += ["--abs-api-key", _get_abs_api_key()]
        # Always pass abs-agg URL so the fixer can auto-detect and search
        # GraphicAudio / SoundBooth Theater regardless of the selected provider.
        cmd += ["--abs-agg-url", _load_abs_agg_config().get("url", "http://abs-agg:3000")]
        # abs-tract (Goodreads/Kindle): pass the URL when configured so the fixer
        # can use it only when the explicit Goodreads fallback flag is set.
        _abs_tract_cfg = _load_abs_tract_config()
        _abs_tract_url = (_abs_tract_cfg.get("url") or "").strip()
        if req.enable_goodreads_fallback:
            cmd.append("--enable-goodreads-fallback")
        if _abs_tract_url:
            cmd += ["--abs-tract-url", _abs_tract_url]
            _region = (_abs_tract_cfg.get("kindle_region") or "").strip()
            if _region:
                cmd += ["--abs-tract-kindle-region", _region]

    if req.debug_trace:
        cmd.append("--debug-trace")
        if req.debug_trace_file:
            cmd += ["--debug-trace-file", req.debug_trace_file]

    return cmd, float(req.duration_review_threshold or 10.0)


def build_sidecar_payload(
    source_path: Path,
    sidecar_path: Path,
    metadata: M4BMetadataForm,
    chapter_file_paths: list[Path] | None = None,
) -> dict[str, Any]:
    metadata = normalize_m4b_metadata(metadata)
    if chapter_file_paths is None:
        if source_path.is_dir():
            chapter_file_paths = [
                child
                for child in sorted(source_path.iterdir(), key=natural_path_sort_key)
                if child.is_file() and is_audio_file(child)
            ]
        elif source_path.is_file():
            chapter_file_paths = [source_path]
        else:
            chapter_file_paths = []
    chapter_files = [str(path) for path in chapter_file_paths]

    return {
        "schema_version": 1,
        "tool": "audible-metadata-fixer-ui",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_format": source_path.suffix.lower().lstrip(".") if source_path.is_file() else "",
        "output_intent": "m4b-tool-remux",
        "metadata_file": str(sidecar_path),
        "book": metadata.model_dump(),
        "audible": {
            "asin": metadata.asin,
            "title": metadata.title,
            "sequence": metadata.sequence,
            "year": metadata.year,
        },
        "matching": {},
        "local_before": {
            "title": metadata.title,
            "author": metadata.author,
            "series": metadata.series,
            "narrator": metadata.narrator,
            "local_duration_minutes": metadata.local_duration_minutes,
        },
        "audio_summary": summarize_audio_probes(
            chapter_file_paths,
            [probe_audio_file(path) for path in chapter_file_paths],
        ),
        "source": {
            "root_file": str(source_path),
            "group_search": {
                "applied": source_path.is_dir(),
                "folder": str(source_path if source_path.is_dir() else source_path.parent),
                "file_count": len(chapter_files),
            },
            "chapter_files": chapter_files,
        },
    }


def save_sidecar_file(
    *,
    source_path: Path,
    metadata: M4BMetadataForm,
    requested_sidecar_path: str = "",
    excluded_paths: set[Path] | None = None,
) -> Path:
    if requested_sidecar_path:
        sidecar_path = validate_audiobook_output_path(requested_sidecar_path)
    else:
        if source_path.is_dir():
            sidecar_path = source_path / "libraforge.json"
        else:
            sidecar_path = source_path.with_name(f"{source_path.name}{M4B_TOOL_SIDECAR_SUFFIX}")

    is_libraforge = sidecar_path.name == "libraforge.json"
    excluded = {path.resolve() for path in (excluded_paths or set())}
    lf_payload: dict[str, Any] = {}
    existing: dict[str, Any] = {}
    if sidecar_path.is_file():
        try:
            lf_payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
            existing = lf_payload.get("sidecar", lf_payload) if is_libraforge else lf_payload
        except (OSError, json.JSONDecodeError):
            lf_payload = {}
            existing = {}

    existing_source = existing.get("source", {}) or {}
    chapter_file_paths = [
        Path(value).resolve()
        for value in (existing_source.get("chapter_files", []) or [])
        if value
    ]
    chapter_file_paths = [
        path
        for path in chapter_file_paths
        if path.is_file() and is_audio_file(path) and path not in excluded
    ]
    chapter_file_paths.sort(key=natural_path_sort_key)
    if not chapter_file_paths:
        if source_path.is_dir():
            chapter_file_paths = [
                path.resolve()
                for path in sorted(source_path.iterdir(), key=natural_path_sort_key)
                if path.is_file()
                and is_audio_file(path)
                and path.resolve() not in excluded
            ]
        elif source_path.is_file() and source_path.resolve() not in excluded:
            chapter_file_paths = [source_path.resolve()]

    payload = build_sidecar_payload(
        source_path,
        sidecar_path,
        metadata,
        chapter_file_paths=chapter_file_paths,
    )
    if existing:
        payload["tool"] = existing.get("tool", payload["tool"])
        payload["created_at"] = existing.get("created_at", payload["created_at"])
        payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload["matching"] = existing.get("matching", payload["matching"])
        payload["local_before"] = existing.get("local_before", payload["local_before"])
        payload["audible"] = {
            **(existing.get("audible", {}) or {}),
            **payload["audible"],
        }
        payload["source"]["group_search"] = {
            **(existing_source.get("group_search", {}) or {}),
            **payload["source"]["group_search"],
            "files": payload["source"]["chapter_files"],
        }

    if is_libraforge:
        lf_payload.setdefault("schema_version", 2)
        lf_payload.setdefault("tool", "audible-metadata-fixer")
        lf_payload["sidecar"] = payload
        sidecar_path.write_text(json.dumps(lf_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        sidecar_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return sidecar_path


def natural_path_sort_key(path: Path) -> list[tuple[int, int | str]]:
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", path.name)
    ]


def normalize_m4b_metadata(metadata: M4BMetadataForm) -> M4BMetadataForm:
    fixer_module = load_fixer_module(default_fixer_script())
    author = (
        fixer_module.canonicalize_author_credits(metadata.author)
        or fixer_module.clean_author_value(metadata.author)
    )
    sequence = fixer_module.normalize_book_number(metadata.sequence)
    title = canonical_m4b_title(
        title=fixer_module.clean_text(metadata.title),
        subtitle=fixer_module.clean_text(metadata.subtitle),
        sequence=sequence,
    )
    return metadata.model_copy(
        update={
            "title": title,
            "subtitle": fixer_module.clean_text(metadata.subtitle),
            "author": author,
            "narrator": fixer_module.clean_text(metadata.narrator),
            "series": fixer_module.clean_text(metadata.series),
            "sequence": sequence,
            "year": fixer_module.clean_text(metadata.year),
            "summary": fixer_module.clean_text(metadata.summary),
            "asin": fixer_module.clean_text(metadata.asin).upper(),
        }
    )


def sidecar_to_form(sidecar: dict[str, Any]) -> dict[str, Any]:
    # libraforge.json nests sidecar data under a "sidecar" key (m4b-tool format)
    if "sidecar" in sidecar and isinstance(sidecar["sidecar"], dict):
        sidecar = sidecar["sidecar"]
    # Fixer-generated libraforge.json stores metadata under "marker"
    marker = sidecar.get("marker", {}) or {} if isinstance(sidecar.get("marker"), dict) else {}
    book = sidecar.get("book", {}) or {}
    audible_meta = sidecar.get("audible", {}) or marker.get("audible", {}) or {}
    local_before = sidecar.get("local_before", {}) or marker.get("local_before", {}) or {}

    metadata = M4BMetadataForm(
        title=book.get("title", "")
        or audible_meta.get("title", "")
        or local_before.get("title", ""),
        subtitle=book.get("subtitle", ""),
        author=book.get("author", "") or audible_meta.get("author", "") or local_before.get("author", ""),
        narrator=book.get("narrator", "") or audible_meta.get("narrator", "") or local_before.get("narrator", ""),
        series=book.get("series", "") or audible_meta.get("series", "") or local_before.get("series", ""),
        sequence=str(
            book.get("sequence", "") or audible_meta.get("sequence", "")
        ),
        year=str(book.get("year", "") or audible_meta.get("year", "")),
        summary=book.get("summary", ""),
        cover_url=book.get("cover_url", "") or audible_meta.get("cover_url", ""),
        asin=audible_meta.get("asin", ""),
        local_duration_minutes=local_before.get("local_duration_minutes"),
    )
    return normalize_m4b_metadata(metadata).model_dump()


def validate_audiobook_browse_path(raw_path: str) -> Path:
    path = Path(raw_path or str(AUDIOBOOKS_ROOT)).expanduser().resolve()
    if path != AUDIOBOOKS_ROOT and AUDIOBOOKS_ROOT not in path.parents:
        raise HTTPException(
            status_code=400,
            detail=f"Browse path must be under: {AUDIOBOOKS_ROOT}",
        )
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    return path


def browse_manual_review_path(path: str) -> dict[str, Any]:
    current = validate_audiobook_browse_path(path)
    if not current.is_dir():
        raise HTTPException(status_code=400, detail="Browse path must be a folder")

    directories = sorted(
        (child for child in current.iterdir() if child.is_dir()),
        key=lambda child: child.name.casefold(),
    )
    audio_files = sorted(
        (
            child
            for child in current.iterdir()
            if child.is_file() and is_audio_file(child)
        ),
        key=lambda child: child.name.casefold(),
    )
    entry_limit = 200
    return {
        "root_path": str(AUDIOBOOKS_ROOT),
        "current_path": str(current),
        "parent_path": str(current.parent) if current != AUDIOBOOKS_ROOT else "",
        "directories": [
            {"name": item.name, "path": str(item)} for item in directories[:entry_limit]
        ],
        "files": [
            {"name": item.name, "path": str(item)} for item in audio_files[:entry_limit]
        ],
        "truncated": len(directories) > entry_limit or len(audio_files) > entry_limit,
    }


def _make_cached_chapter_count_reader(fixer_module):
    """Return a chapter_count_reader that serves from the on-disk per-folder cache.

    build_multi_part_group_map calls this instead of running ffprobe when the
    persistent cache file (<folder>/<folder>.chapter-count-cache.json) already
    has a valid (mtime-matched) entry for the file.
    """
    loaded: dict[Path, dict] = {}

    def reader(file_path: Path) -> int | None:
        parent = file_path.parent
        if parent not in loaded:
            loaded[parent] = fixer_module._load_chapter_count_persistent(parent)
        entry = loaded[parent].get(str(file_path))
        if entry is not None:
            try:
                if entry.get("mtime") == file_path.stat().st_mtime:
                    return entry.get("chapter_count")
            except OSError:
                pass
        return fixer_module.read_file_chapter_count(file_path)

    return reader


def fixer_processing_context(
    *,
    target_path: Path,
    fixer_module,
    chapter_count_reader=None,
) -> tuple[list[Path], dict[Path, list[Path]], list[Path]]:
    """Return source files, accepted multipart groups, and processing items."""
    reader = chapter_count_reader or _make_cached_chapter_count_reader(fixer_module)
    if target_path.is_file():
        if not fixer_module.collect_audio_files(target_path):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported audiobook file: {target_path}",
            )
        sibling_files = [
            item
            for item in target_path.parent.iterdir()
            if item.is_file() and fixer_module.is_supported_audio_file(item)
        ]
        sibling_group_map = fixer_module.build_multi_part_group_map(
            sibling_files,
            chapter_count_reader=reader,
        )
        grouped_files = sibling_group_map.get(target_path.parent, [])
        files = grouped_files if target_path in grouped_files else [target_path]
    else:
        files = fixer_module.collect_audio_files(target_path)

    if not files:
        raise HTTPException(
            status_code=400,
            detail=f"No supported audio files under: {target_path}",
        )

    group_map = fixer_module.build_multi_part_group_map(
        files,
        chapter_count_reader=reader,
    )
    processing_items = fixer_module.build_processing_items(files, group_map)
    return files, group_map, processing_items


def manual_review_sidecar_context(
    *,
    target_path: Path,
    fixer_module,
) -> tuple[list[Path], dict[Path, list[Path]], list[Path]] | None:
    """Use an existing sidecar's chapter list as the multipart source of truth."""
    selected_sidecar = pick_sidecar(target_path, discover_sidecars(target_path))
    if selected_sidecar is None:
        return None

    payload = load_json(selected_sidecar)
    fallback = target_path if target_path.is_dir() else target_path.parent
    chapter_files = sidecar_audio_files(payload, fallback)
    return build_sidecar_multipart_context(
        chapter_files,
        fixer_module.natural_audio_sort_key,
    )


def discover_manual_review_targets(
    *,
    path: str,
    script_name: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    script_name = script_name or default_fixer_script()
    target_path = validate_audiobook_path(path)
    fixer_module = load_fixer_module(script_name)
    _files, group_map, processing_items = fixer_processing_context(
        target_path=target_path,
        fixer_module=fixer_module,
    )
    items = []
    for source_path in processing_items[:limit]:
        display_path = fixer_module.get_processing_display_path(source_path, group_map)
        items.append(
            {
                "path": str(source_path),
                "display_path": str(display_path),
                "is_grouped": display_path != source_path,
            }
        )

    return {
        "path": str(target_path),
        "items": items,
        "total": len(processing_items),
        "returned": len(items),
        "limit": limit,
        "truncated": len(processing_items) > limit,
    }


def discover_m4b_candidates(
    *,
    path: str,
    mode: str,
    script_name: str = "",
    limit: int = 200,
    cache_action: str = "refresh",
) -> dict[str, Any]:
    script_name = script_name or default_fixer_script()
    supported_modes = ("multipart", "non_m4b")
    if mode not in {*supported_modes, "all"}:
        raise HTTPException(
            status_code=400,
            detail="Discovery mode must be multipart, non_m4b, or all",
        )
    if cache_action not in {"load", "refresh"}:
        raise HTTPException(
            status_code=400,
            detail="Cache action must be load or refresh",
        )

    target_path = validate_audiobook_browse_path(path)
    script_path = live_script_path(script_name, "fixer")
    script_mtime_ns = script_path.stat().st_mtime_ns
    cache_key = search_cache_key(target_path, script_name)
    with M4B_DISCOVERY_CACHE_LOCK:
        cache = load_discovery_cache(M4B_DISCOVERY_CACHE)
        cached_search = cache["searches"].get(cache_key)

    if cache_action == "load":
        if not cached_search:
            raise HTTPException(
                status_code=404,
                detail="No cached M4B discovery search exists for this root and fixer",
            )
        if cached_search.get("script_mtime_ns") != script_mtime_ns:
            raise HTTPException(
                status_code=409,
                detail="The selected fixer changed after this search was cached; refresh the search",
            )
        return format_m4b_discovery_response(
            target_path=target_path,
            mode=mode,
            results=cached_search.get("results", {}),
            limit=limit,
            cache_info={
                "source": "cache",
                "refreshed_at": cached_search.get("refreshed_at", ""),
                "audio_file_count": cached_search.get("audio_file_count", 0),
                "chapter_probes_reused": 0,
                "chapter_probes_run": 0,
                "audio_probes_reused": 0,
                "audio_probes_run": 0,
            },
        )

    # Nothing-changed fast path: if the shared library index has a folder
    # signature for every folder this cached search previously covered,
    # and every one of them is unchanged, and no new folders exist under
    # target_path, skip the walk and reprobe entirely and reuse the cached
    # results verbatim. This is what makes the common case instant; any
    # actual change anywhere under target_path falls through to the
    # existing full-walk logic below, which already reuses per-file
    # ffprobe results for any file that itself did not change.
    library_index.ensure_library_index_fresh(AUDIOBOOKS_ROOT)
    shared = library_index.get_state()
    if (
        cached_search
        and cached_search.get("script_mtime_ns") == script_mtime_ns
        and _m4b_cached_search_is_still_fresh(cached_search, target_path, shared)
    ):
        return format_m4b_discovery_response(
            target_path=target_path,
            mode=mode,
            results=cached_search.get("results", {}),
            limit=limit,
            cache_info={
                "source": "cache",
                "refreshed_at": cached_search.get("refreshed_at", ""),
                "audio_file_count": cached_search.get("audio_file_count", 0),
                "chapter_probes_reused": 0,
                "chapter_probes_run": 0,
                "audio_probes_reused": 0,
                "audio_probes_run": 0,
            },
        )

    # When there is no cache entry for this script version, look for per-file
    # probe data from any cached entry for the same path. Chapter counts and
    # audio stream properties are script-independent, so they can be safely
    # reused across script upgrades.
    probe_seed = cached_search
    if probe_seed is None:
        for entry in cache["searches"].values():
            if entry.get("path") == str(target_path):
                probe_seed = entry
                break

    fixer_module = load_fixer_module(script_name)
    chapter_reader = CachedChapterCountReader(
        probe=fixer_module.read_file_chapter_count,
        entries=(probe_seed or {}).get("chapter_probes", {}),
    )
    audio_reader = CachedAudioProbeReader(
        probe=probe_audio_file,
        entries=(probe_seed or {}).get("audio_probes", {}),
    )
    files, group_map, processing_items = fixer_processing_context(
        target_path=target_path,
        fixer_module=fixer_module,
        chapter_count_reader=chapter_reader,
    )

    candidates_by_mode: dict[str, list[dict[str, Any]]] = {
        requested_mode: [] for requested_mode in supported_modes
    }
    for source_path in processing_items:
        display_path = fixer_module.get_processing_display_path(source_path, group_map)
        grouped_files = group_map.get(source_path.parent, [])
        item_files = grouped_files if display_path != source_path else [source_path]
        included_modes = [
            requested_mode
            for requested_mode in supported_modes
            if conversion_candidate(
                source_path=source_path,
                display_path=display_path,
                item_files=item_files,
                mode=requested_mode,
            )
        ]
        if not included_modes:
            continue
        audio_summary = summarize_audio_probes(
            item_files,
            [audio_reader(item_file) for item_file in item_files],
        )
        for requested_mode in included_modes:
            candidate = conversion_candidate(
                source_path=source_path,
                display_path=display_path,
                item_files=item_files,
                mode=requested_mode,
                audio_summary=audio_summary,
            )
            candidates_by_mode[requested_mode].append(candidate)

    results: dict[str, list[dict[str, Any]]] = {}
    for requested_mode, candidates in candidates_by_mode.items():
        candidates.sort(key=lambda item: item["display_path"].casefold())
        results[requested_mode] = candidates

    refreshed_at = utc_timestamp()
    # Re-fetch the shared state rather than reusing the `shared` snapshot
    # taken before the fast-path check above: ensure_library_index_fresh
    # only kicks a background walk and returns immediately, so that early
    # snapshot can still be the pre-walk (possibly empty) state. By this
    # point the full m4b walk and ffprobe reads above have run, giving the
    # much cheaper background folder walk ample time to finish, so this
    # later read is the freshest available signature data to persist.
    folder_signatures = _m4b_folder_signatures_under(target_path, library_index.get_state())
    search_entry = {
        "path": str(target_path),
        "script_name": script_name,
        "script_mtime_ns": script_mtime_ns,
        "refreshed_at": refreshed_at,
        "audio_file_count": len(files),
        "chapter_probes": chapter_reader.pruned_entries(),
        "audio_probes": audio_reader.pruned_entries(),
        "folder_signatures": folder_signatures,
        "results": results,
    }
    with M4B_DISCOVERY_CACHE_LOCK:
        cache = load_discovery_cache(M4B_DISCOVERY_CACHE)
        cache["searches"][cache_key] = search_entry
        save_discovery_cache(M4B_DISCOVERY_CACHE, cache)

    return format_m4b_discovery_response(
        target_path=target_path,
        mode=mode,
        results=results,
        limit=limit,
        cache_info={
            "source": "refresh",
            "refreshed_at": refreshed_at,
            "audio_file_count": len(files),
            "chapter_probes_reused": chapter_reader.reused,
            "chapter_probes_run": chapter_reader.probed,
            "audio_probes_reused": audio_reader.reused,
            "audio_probes_run": audio_reader.probed,
        },
    )


def _m4b_folder_signature_scope(target_path: Path) -> Path:
    """The folder whose signature (and everything under it) determines
    whether a cached discover_m4b_candidates search is still fresh.

    discover_m4b_candidates accepts a single audio file as target_path
    (fixer_processing_context has a dedicated branch for this: it groups
    target_path with its siblings via target_path.parent.iterdir()), and
    the shared library index only carries signatures for folders, not
    individual files (see library_index.build_library_index). Using
    target_path directly in that case would look for a signature keyed by
    a file path that never has one, silently and permanently returning an
    empty folder_signatures dict on both sides of every comparison --
    trivially "unchanged" even when a sibling file is added, removed, or
    rewritten. Scoping to the parent folder instead is what the file
    target case actually depends on, matching fixer_processing_context's
    own sibling-grouping behavior.
    """
    return target_path.parent if target_path.is_file() else target_path


def _m4b_folder_signatures_under(
    target_path: Path, shared: "library_index.LibraryIndexState"
) -> dict[str, str]:
    scope = _m4b_folder_signature_scope(target_path)
    prefix = str(scope) + os.sep
    return {
        path_str: signature
        for path_str, signature in shared.signatures.items()
        if path_str == str(scope) or path_str.startswith(prefix)
    }


def _m4b_cached_search_is_still_fresh(
    cached_search: dict[str, Any], target_path: Path, shared: "library_index.LibraryIndexState"
) -> bool:
    """True only if every folder the shared index currently has under
    target_path is present in the cached search's folder_signatures with
    an identical signature, AND the cached search has no folder that the
    shared index no longer has (a folder disappearing is a change too).
    A cache entry from before this migration (no folder_signatures key)
    is always a miss, never a crash.

    Forces a miss when the signature scope resolves to AUDIOBOOKS_ROOT
    itself (target_path IS AUDIOBOOKS_ROOT, or target_path is a loose
    file sitting directly in it). library_index.build_library_index never
    assigns a signature to AUDIOBOOKS_ROOT or to loose root files (see its
    own docstring: "Loose root files have no signature entry"), so
    _m4b_folder_signatures_under would return {} on both sides of the
    comparison in that case, always comparing equal regardless of what
    actually changed among the loose root files. Falling back to the
    existing full-walk path here is conservative: it never reports stale
    results as fresh, it just forgoes the fast-path speedup for this one
    narrow case.
    """
    scope = _m4b_folder_signature_scope(target_path)
    if scope == AUDIOBOOKS_ROOT:
        return False
    cached_signatures = cached_search.get("folder_signatures")
    if not isinstance(cached_signatures, dict):
        return False
    return _m4b_folder_signatures_under(target_path, shared) == cached_signatures


def format_m4b_discovery_response(
    *,
    target_path: Path,
    mode: str,
    results: dict[str, list[dict[str, Any]]],
    limit: int,
    cache_info: dict[str, Any],
) -> dict[str, Any]:
    formatted: dict[str, dict[str, Any]] = {}
    requested_modes = ("multipart", "non_m4b") if mode == "all" else (mode,)
    for requested_mode in requested_modes:
        candidates = results.get(requested_mode, [])
        returned = candidates[:limit]
        formatted[requested_mode] = {
            "mode": requested_mode,
            "items": returned,
            "total": len(candidates),
            "returned": len(returned),
            "limit": limit,
            "truncated": len(candidates) > limit,
        }

    if mode == "all":
        return {
            "path": str(target_path),
            "mode": mode,
            "results": formatted,
            "cache": cache_info,
        }

    return {
        "path": str(target_path),
        **formatted[mode],
        "cache": cache_info,
    }


def m4b_discovery_cache_status(*, path: str, script_name: str) -> dict[str, Any]:
    target_path = validate_audiobook_browse_path(path)
    script_path = live_script_path(script_name, "fixer")
    cache_key = search_cache_key(target_path, script_name)
    with M4B_DISCOVERY_CACHE_LOCK:
        cached_search = load_discovery_cache(M4B_DISCOVERY_CACHE)["searches"].get(cache_key)

    available = bool(
        cached_search
        and cached_search.get("script_mtime_ns") == script_path.stat().st_mtime_ns
    )
    return {
        "path": str(target_path),
        "script_name": script_name,
        "available": available,
        "stale": bool(cached_search) and not available,
        "refreshed_at": cached_search.get("refreshed_at", "") if cached_search else "",
        "audio_file_count": cached_search.get("audio_file_count", 0) if cached_search else 0,
    }


def refresh_cached_multipart_audio_profiles(
    *,
    path: str,
    script_name: str,
) -> dict[str, Any]:
    target_path = validate_audiobook_browse_path(path)
    script_path = live_script_path(script_name, "fixer")
    cache_key = search_cache_key(target_path, script_name)
    with M4B_DISCOVERY_CACHE_LOCK:
        cached_search = load_discovery_cache(M4B_DISCOVERY_CACHE)["searches"].get(
            cache_key
        )

    if not cached_search:
        raise HTTPException(
            status_code=404,
            detail="Run multipart discovery first so the audio profiles are available",
        )
    if cached_search.get("script_mtime_ns") != script_path.stat().st_mtime_ns:
        raise HTTPException(
            status_code=409,
            detail="The selected fixer changed; refresh multipart discovery first",
        )

    fixer_module = load_fixer_module(script_name)
    candidates = (cached_search.get("results") or {}).get("multipart", [])
    updated: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []

    for candidate in candidates:
        folder = Path(candidate.get("display_path", ""))
        chapter_files = [Path(item) for item in candidate.get("files", [])]
        sidecar_path = folder / "libraforge.json"

        if not folder.is_dir() or not chapter_files:
            failed.append(
                {
                    "path": str(folder),
                    "error": "Cached multipart source is incomplete; refresh discovery",
                }
            )
            continue
        if not sidecar_path.exists():
            skipped.append(str(sidecar_path))
            continue

        try:
            written = fixer_module.refresh_multipart_sidecar_audio_profile(
                folder=folder,
                chapter_files=chapter_files,
                audio_summary=candidate.get("audio_summary") or None,
            )
            updated.append(str(written))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            failed.append({"path": str(sidecar_path), "error": str(error)})

    return {
        "path": str(target_path),
        "multipart_count": len(candidates),
        "updated": len(updated),
        "skipped": len(skipped),
        "failed": len(failed),
        "updated_sidecars": updated,
        "skipped_sidecars": skipped,
        "failures": failed,
    }


def _read_sidecar_book(source_path: Path, fixer_module) -> dict | None:
    """Return the applied book metadata from libraforge.json, if present.

    Thin delegate to fixer_module.read_book_sidecar -- the fixer script's
    own report-building (_build_report_item) reads through the exact same
    function, so Manual Review and the report can never diverge on what
    counts as this book's current applied metadata. See that function's
    docstring for the sidecar.book / marker.audible precedence.
    """
    return fixer_module.read_book_sidecar(source_path)


def _sum_group_duration(folder: Path, group_files: list[Path]) -> float | None:
    """Sum per-file duration_minutes from the folder-level libraforge.json file_cache.

    Falls back to filename-only matching so durations survive after the organizer
    moves files to a new folder path.
    """
    lf_path = folder / "libraforge.json"
    if not lf_path.is_file():
        return None
    try:
        lf = json.loads(lf_path.read_text(encoding="utf-8"))
        cache = lf.get("file_cache") or {}
        if not cache:
            return None
        total = 0.0
        found = 0
        for f in group_files:
            dur = (cache.get(str(f)) or {}).get("duration_minutes")
            if dur is not None:
                total += float(dur)
                found += 1
        if found > 0:
            return round(total, 2)
        # Paths may have changed (organizer moved files). Try filename-only match.
        by_name = {Path(k).name: v for k, v in cache.items()}
        for f in group_files:
            dur = (by_name.get(f.name) or {}).get("duration_minutes")
            if dur is not None:
                total += float(dur)
                found += 1
        return round(total, 2) if found > 0 else None
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _probe_and_cache_group_duration(
    group_files: list[Path], fixer_module, max_files: int = 200
) -> float | None:
    """Probe all files concurrently for duration and save to libraforge.json file_cache.

    Skips groups larger than max_files to avoid multi-second hangs on extreme
    cases (e.g. 600-file .ogg chapter splits).  Results are cached so the next
    manual-review load is instant.
    """
    if not group_files or len(group_files) > max_files:
        return None
    workers = min(16, len(group_files))
    per_file: list[tuple[dict, float | None]] = [({}, None)] * len(group_files)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fixer_module.probe_file, f): i for i, f in enumerate(group_files)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                per_file[idx] = fut.result()
            except Exception:
                pass
    try:
        fixer_module._save_group_file_cache(group_files, per_file)
    except Exception:
        pass
    total = sum(float(dur or 0) for _, dur in per_file)
    found = sum(1 for _, dur in per_file if dur is not None)
    return round(total, 2) if found > 0 else None


def inspect_manual_review_target(
    *,
    path: str,
    script_name: str = "",
    use_backup_tags: bool = False,
) -> dict[str, Any]:
    script_name = script_name or default_fixer_script()
    target_path = validate_audiobook_path(path)
    fixer_module = load_fixer_module(script_name)
    sidecar_context = manual_review_sidecar_context(
        target_path=target_path,
        fixer_module=fixer_module,
    )
    if sidecar_context is not None:
        files, group_map, processing_items = sidecar_context
    else:
        # fixer_processing_context uses the cached chapter-count reader so sibling
        # scanning stays fast even for large multifile folders.
        if target_path.is_file() and not fixer_module.is_supported_audio_file(target_path):
            raise HTTPException(status_code=400, detail=f"Unsupported audiobook file: {target_path}")
        files, group_map, processing_items = fixer_processing_context(
            target_path=target_path,
            fixer_module=fixer_module,
        )
    if len(processing_items) != 1:
        raise HTTPException(
            status_code=400,
            detail="Path must point to a single book file or grouped book folder",
        )
    source_path = processing_items[0]
    # For large multi-part groups (e.g. 600-chapter .ogg books), build_search_context
    # would ffprobe every chapter file to gather tags. For manual review we only need
    # one representative file's tags -- title/author/series are the same in all parts.
    # Strip the group from group_map when it has more than a few files so
    # build_search_context falls through to the single-file path.
    group_key = source_path.parent
    real_group = group_map.get(group_key) or []
    if len(real_group) > 4:
        effective_group_map: dict = {}
    else:
        effective_group_map = group_map
    queries, clues, _ = fixer_module.build_search_context(
        source_path, effective_group_map, use_backup_tags=use_backup_tags
    )
    # When the group_map was stripped to avoid ffprobing a large group, the clues
    # won't have group_search.applied. Restore it so apply writes a folder-level
    # sidecar instead of tagging an individual chapter file.
    # Also compute the total duration: prefer the cached libraforge.json file_cache,
    # fall back to a concurrent ffprobe pass (one-time cost, results saved to cache).
    if not effective_group_map and real_group:
        gs = clues.setdefault("group_search", {})
        gs["applied"] = True
        gs.setdefault("folder", str(group_key))
        gs.setdefault("file_count", len(real_group))
        total_dur = _sum_group_duration(group_key, real_group)
        if total_dur is None:
            total_dur = _probe_and_cache_group_duration(real_group, fixer_module)
        if total_dur is not None:
            clues["local_duration_minutes"] = total_dur
    display_path = fixer_module.get_processing_display_path(source_path, group_map)

    # For live display (use_backup_tags=False), prefer the libraforge.json sidecar.book
    # over the search-context clues. build_search_clues_from_file applies path-based
    # overrides (folder name -> title, hierarchy -> series) that are useful for finding
    # the right match but corrupt the "Current" column when showing post-apply state.
    sidecar_book = None if use_backup_tags else _read_sidecar_book(source_path, fixer_module)
    if sidecar_book:
        # Take all fields stored in the sidecar (no preset list) so genre and any
        # future fields come through without code changes here.
        metadata = {
            **sidecar_book,
            # Prefer stored title but fall back to raw parsed title if blank.
            "title": sidecar_book.get("title") or clues.get("raw_title", ""),
            # Publisher is not stored in the sidecar; read from clues (embedded tags).
            "publisher": sidecar_book.get("publisher") or clues.get("publisher", ""),
            "cover_url": "",
            "local_duration_minutes": clues.get("local_duration_minutes"),
            "raw_title": clues.get("raw_title", ""),
            "book_number_source": clues.get("book_number_source", ""),
        }
    else:
        metadata = {
            "title": clues.get("title", "") or clues.get("raw_title", ""),
            "subtitle": "",
            "author": clues.get("author", ""),
            "narrator": clues.get("narrator", ""),
            "series": clues.get("series", ""),
            "sequence": clues.get("book_number", ""),
            "year": "",
            "summary": "",
            "publisher": clues.get("publisher", ""),
            "cover_url": "",
            "asin": "",
            "local_duration_minutes": clues.get("local_duration_minutes"),
            "raw_title": clues.get("raw_title", ""),
            "book_number_source": clues.get("book_number_source", ""),
        }

    return {
        "path": str(target_path),
        "source_path": str(source_path),
        "display_path": str(display_path),
        "is_grouped": bool((clues.get("group_search", {}) or {}).get("applied")),
        "queries": queries,
        "metadata": metadata,
        "group_search": clues.get("group_search", {}) or {},
    }


def extract_current_cover(source_path: Path) -> tuple[bytes, str]:
    embedded = _embedded_cover_bytes(source_path)
    if embedded:
        return embedded

    # Fallback for files with no readable covr/APIC tag but a raw embedded
    # picture/video stream ffmpeg can pull out (rare; mutagen normally finds
    # the real cover first).
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if result.returncode == 0 and result.stdout.startswith(b"\xff\xd8\xff"):
        return result.stdout, "image/jpeg"

    for name in ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png"):
        cover_path = source_path.parent / name
        if not cover_path.is_file():
            continue
        data = cover_path.read_bytes()
        if data.startswith(b"\xff\xd8\xff"):
            return data, "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return data, "image/png"

    raise HTTPException(status_code=404, detail="No current cover was found")


def build_manual_metadata_from_result(
    result: dict[str, Any],
    file_type: str,
    edit_mode: str,
) -> dict[str, Any]:
    allowed_modes = result.get("allowed_edit_modes") or []
    if edit_mode not in {"full", "series_only"}:
        raise HTTPException(
            status_code=400,
            detail="Choose full or series_only before applying a manual match",
        )
    if edit_mode not in allowed_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Selected result does not support {edit_mode} mode",
        )

    metadata_by_mode = result.get("chosen_metadata_by_mode") or {}
    chosen = dict(metadata_by_mode.get(edit_mode) or {})
    if not chosen:
        raise HTTPException(
            status_code=400,
            detail=f"Selected result is missing its {edit_mode} metadata preview",
        )
    chosen["edit_mode"] = edit_mode
    chosen["audible_title"] = result.get("title", "")
    chosen["audible_sequence"] = result.get("sequence", "")
    chosen["audible_year"] = str(result.get("year", "") or "")
    chosen["audible_duration_minutes"] = result.get("duration_minutes")
    chosen["audible_number_candidates"] = [str(result.get("sequence"))] if result.get("sequence") else []
    chosen["duration"] = result.get("duration", {}) or {}
    chosen["file_type"] = file_type
    return chosen


def _write_book_metadata(
    *,
    source_path: Path,
    metadata: dict[str, Any],
    clues: dict[str, Any],
    score: float,
    fixer_module,
    write_policy: str,
    marker_mode: str,
    writer: str = "auto",
    cover_if_missing: bool = False,
    replace_cover: bool = False,
    backup: bool = False,
) -> dict[str, Any]:
    """Resolves alone/grouped placement and writes tags-or-JSON-sidecar,
    metadata.json, and the marker. Shared by apply_manual_review_result and
    edit_manual_review_book so the two flows can never diverge -- see
    docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
    """
    # Full Overwrite can't be honestly honored on a file that falls back to
    # the ffmpeg writer (build_metadata_args never clears a tag -- see
    # docs/design/manual-review-apply-rewrite-rules.md). Detect this ahead of
    # time and apply anyway with fill-like behavior, surfacing why instead of
    # silently doing something other than what was asked.
    write_policy_warning = ""
    if write_policy == "overwrite" and writer != "mutagen":
        will_use_mutagen = (
            fixer_module.is_mutagen_mp4_candidate(source_path)
            or fixer_module.is_mutagen_mp3_candidate(source_path)
        )
        if not will_use_mutagen:
            write_policy_warning = (
                "Full Overwrite requested, but this file type only supports the "
                "ffmpeg writer, which cannot force-clear a tag; blank fields were "
                "left untouched instead of cleared."
            )

    output_kind = "tags"
    output_path = str(source_path)

    # Follow the same sidecar placement as the rest of the script: a single file
    # alone in its folder (or a grouped multi-file book) gets a folder-level
    # libraforge.json + metadata.json; a loose file sharing its folder gets per-file
    # companions. Grouped books are already routed folder-level via the group_search
    # clue; for a single file we detect "alone" by counting sibling audio files.
    grouped = bool((clues.get("group_search") or {}).get("applied"))
    if grouped:
        alone = False
    else:
        folder = source_path.parent
        try:
            alone = sum(1 for x in folder.iterdir() if x.is_file() and is_audio_file(x)) <= 1
        except OSError:
            alone = True

    if fixer_module.should_write_json_sidecar(source_path, clues):
        output_kind = "json_sidecar"
        sidecar_path = fixer_module.write_m4b_tool_metadata_sidecar(
            source_path, metadata, clues, score, field_policy=write_policy
        )
        output_path = str(sidecar_path)
    else:
        # Back up explicitly so the backup lands in the same (alone-aware)
        # libraforge.json the marker will use, instead of a split per-file copy.
        if backup:
            fixer_module.write_original_metadata_backup(source_path, alone=alone)
        fixer_module.write_tags(
            source_path,
            metadata,
            backup=False,
            writer=writer,
            cover_if_missing=cover_if_missing,
            replace_cover=replace_cover,
            field_policy=write_policy,
        )

    # Audiobookshelf metadata.json, placed by the same alone/group rules.
    metadata_json_path = fixer_module.write_audiobookshelf_metadata_json(
        source_path, metadata, clues, alone,
        skip_blank_fields=(write_policy == "fill"),
    )

    # Mirror the CLI path's written_fields computation (audible-metadata-fixer-v5.py,
    # around WRITE_ACTION_JSON emission): a field counts as "written" whenever
    # this apply actually persisted it somewhere -- tags for a single file, or
    # the json sidecar for a grouped/multi-file book -- and the resolved value
    # is non-blank. Both output kinds are real writes here (this function only
    # runs on an actual apply, never a preview), so there is no "wrote tags
    # vs. sidecar-only" distinction to make. Gating this on output_kind=="tags"
    # used to leave written_fields empty for every grouped book, which made
    # marker_skip_is_clean() believe the real ASIN was never recorded and
    # routed the book into the recovery path on every future scan -- surfacing
    # a permanent "would write" badge for a book that was already applied.
    written_fields = [
        f for f in fixer_module.FILL_FIELDS if str((metadata or {}).get(f) or "").strip()
    ]
    fixer_module.write_marker(
        source=source_path,
        metadata=metadata,
        clues=clues,
        score=score,
        mode=marker_mode,
        aggressive=False,
        output_kind=output_kind,
        alone=alone,
        written_fields=written_fields,
        field_policy=write_policy,
    )

    return {
        "output_kind": output_kind,
        "output_path": output_path,
        "metadata_json_path": str(metadata_json_path),
        "warning": write_policy_warning,
    }


def apply_manual_review_result(req: ManualReviewApplyRequest) -> dict[str, Any]:
    if req.write_policy not in ("fill", "overwrite"):
        raise HTTPException(status_code=400, detail="write_policy must be 'fill' or 'overwrite'")

    context = inspect_manual_review_target(path=req.path, script_name=req.script_name)
    fixer_module = load_fixer_module(req.script_name)
    source_path = Path(context["source_path"])
    file_type = source_path.suffix.lower().lstrip(".")
    metadata = build_manual_metadata_from_result(
        req.selected_result,
        file_type,
        req.edit_mode,
    )

    for key in ("title", "subtitle", "author", "narrator", "series", "sequence", "year", "asin", "publisher", "genre", "summary"):
        if key in req.metadata_override and req.metadata_override[key] is not None:
            metadata[key] = req.metadata_override[key]

    metadata["write_summary"] = True

    if not metadata.get("title") or not metadata.get("author"):
        raise HTTPException(status_code=400, detail="Selected result does not include enough metadata to apply")

    clues = build_context_clues(fixer_module, context["metadata"])
    if context.get("is_grouped"):
        clues["group_search"] = context.get("group_search", {})
    # Required for write_marker's per-field survivor-fallback to work on this
    # path at all -- context["metadata"] is already exactly the right "current
    # tag state" shape (inspect_manual_review_target prefers sidecar/marker
    # over a live probe, same rule as the CLI path). Without this,
    # clues.get("current") is always {} here, so marker.audible silently
    # misreports any field the match didn't supply as blank even when the
    # real tag survives on disk. See docs/design/manual-review-apply-rewrite-rules.md.
    clues["current"] = dict(context["metadata"])

    score = float(req.selected_result.get("score", 1.0) or 1.0)

    write_result = _write_book_metadata(
        source_path=source_path,
        metadata=metadata,
        clues=clues,
        score=score,
        fixer_module=fixer_module,
        write_policy=req.write_policy,
        marker_mode=f"manual_{req.edit_mode}",
        writer=req.writer,
        cover_if_missing=req.cover_if_missing,
        replace_cover=req.replace_cover,
        backup=req.backup,
    )

    result = {
        "status": "applied",
        "target_path": context["display_path"],
        "source_path": context["source_path"],
        "output_kind": write_result["output_kind"],
        "output_path": write_result["output_path"],
        "metadata_json_path": write_result["metadata_json_path"],
        "edit_mode": req.edit_mode,
        "write_policy": req.write_policy,
        "metadata_preview": metadata,
    }
    if write_result["warning"]:
        result["warning"] = write_result["warning"]
    return result


def edit_manual_review_book(req: ManualReviewEditRequest) -> dict[str, Any]:
    if not req.title or not req.author:
        raise HTTPException(status_code=400, detail="Title and author are required")

    context = inspect_manual_review_target(path=req.path, script_name=req.script_name)
    fixer_module = load_fixer_module(req.script_name)
    source_path = Path(context["source_path"])

    metadata = {
        "title": req.title,
        "subtitle": req.subtitle,
        "author": req.author,
        "narrator": req.narrator,
        "series": req.series,
        "sequence": req.sequence,
        "year": req.year,
        "asin": req.asin,
        "isbn": req.isbn,
        "publisher": req.publisher,
        "genre": req.genre,
        "language": req.language,
        "explicit": req.explicit,
        "summary": req.summary,
        "write_summary": True,
        "edit_mode": "full",
        "cover_url": req.cover_url,
    }

    clues = build_context_clues(fixer_module, context["metadata"])
    if context.get("is_grouped"):
        clues["group_search"] = context.get("group_search", {})
    clues["current"] = dict(context["metadata"])

    write_result = _write_book_metadata(
        source_path=source_path,
        metadata=metadata,
        clues=clues,
        score=1.0,
        fixer_module=fixer_module,
        write_policy="overwrite",
        marker_mode="manual_edit",
        writer="auto",
        cover_if_missing=False,
        replace_cover=bool(req.cover_url),
        backup=False,
    )

    result = {
        "status": "applied",
        "target_path": context["display_path"],
        "source_path": context["source_path"],
        "output_kind": write_result["output_kind"],
        "output_path": write_result["output_path"],
        "metadata_json_path": write_result["metadata_json_path"],
        "metadata_preview": metadata,
    }
    if write_result["warning"]:
        result["warning"] = write_result["warning"]
    return result


def apply_series_group(req: SeriesGroupApplyRequest) -> dict[str, Any]:
    fixer_module = load_fixer_module(req.script_name)
    results: list[dict[str, Any]] = []

    for book in req.books:
        try:
            context = inspect_manual_review_target(path=book.path, script_name=req.script_name)
            source_path = Path(context["source_path"])

            metadata: dict[str, Any] = {"edit_mode": "full", "write_summary": False}
            if req.series:
                metadata["series"] = req.series
            if req.author:
                metadata["author"] = req.author
            if req.genre:
                metadata["genre"] = req.genre
            if req.narrator:
                metadata["narrator"] = req.narrator
            if req.language:
                metadata["language"] = req.language
            if req.explicit_set:
                metadata["explicit"] = req.explicit
            if book.sequence:
                metadata["sequence"] = book.sequence

            clues = build_context_clues(fixer_module, context["metadata"])
            if context.get("is_grouped"):
                clues["group_search"] = context.get("group_search", {})
            clues["current"] = dict(context["metadata"])

            write_result = _write_book_metadata(
                source_path=source_path,
                metadata=metadata,
                clues=clues,
                score=1.0,
                fixer_module=fixer_module,
                write_policy="fill",
                marker_mode="manual_edit",
                writer="auto",
                cover_if_missing=False,
                replace_cover=False,
                backup=False,
            )
            results.append({
                "path": book.path,
                "status": "applied",
                "output_kind": write_result["output_kind"],
            })
        except Exception as exc:
            results.append({"path": book.path, "status": "failed", "error": str(exc)})

    return {"results": results}


def default_output_path(source_path: Path, metadata: dict[str, Any]) -> str:
    folder = source_path if source_path.is_dir() else source_path.parent
    title = sanitize_filename(metadata.get("title", "") or folder.name)
    return str((folder / f"{title}.m4b").resolve())


def read_cover_url_bytes(url: str) -> bytes:
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        upload_root = COVER_UPLOAD_DIR.resolve()
        path = Path(urllib.parse.unquote(parsed.path)).resolve()
        if path != upload_root and upload_root not in path.parents:
            raise HTTPException(status_code=400, detail="Local cover file must come from a LibraForge upload")
        data = path.read_bytes()
    elif scheme in {"http", "https"}:
        req = urllib.request.Request(url, headers={"User-Agent": "LibraForge/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(MAX_COVER_DOWNLOAD_BYTES + 1)
    else:
        raise HTTPException(status_code=400, detail="Cover URL must use http, https, or a LibraForge upload")

    if len(data) > MAX_COVER_DOWNLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Cover image is too large")
    if not (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")):
        raise HTTPException(status_code=400, detail="Cover URL did not return a JPEG or PNG image")
    return data


def build_m4b_command(
    req: M4BRunRequest,
    temp_dir: Path | None = None,
) -> tuple[list[str], list[Path]]:
    input_path = validate_audiobook_path(req.input_path)
    output_path = validate_audiobook_output_path(req.output_path)
    metadata = normalize_m4b_metadata(req.metadata)
    input_files = resolve_m4b_input_files(
        input_path=input_path,
        output_path=output_path,
        sidecar_path=req.sidecar_path,
    )

    temp_files: list[Path] = []
    cmd = [
        "m4b-tool",
        "merge",
        *(str(path) for path in input_files),
        f"--output-file={output_path}",
        "-v",
    ]
    if temp_dir is not None:
        cmd.append(f"--tmp-dir={temp_dir}")

    if req.force:
        cmd.append("--force")
    if req.jobs > 0:
        cmd.append(f"--jobs={req.jobs}")
    if req.no_conversion:
        cmd.append("--no-conversion")
    else:
        if req.audio_codec not in M4B_AUDIO_CODECS:
            raise HTTPException(status_code=400, detail="Unsupported audio codec")
        if req.audio_bitrate not in M4B_AUDIO_BITRATES:
            raise HTTPException(status_code=400, detail="Unsupported audio bitrate")
        if req.audio_samplerate not in M4B_AUDIO_SAMPLERATES:
            raise HTTPException(status_code=400, detail="Unsupported audio sample rate")
        if req.audio_channels is not None and req.audio_channels not in M4B_AUDIO_CHANNELS:
            raise HTTPException(status_code=400, detail="Unsupported audio channel count")
        cmd.append(f"--audio-codec={req.audio_codec}")
        cmd.append(f"--audio-bitrate={req.audio_bitrate}")
        cmd.append(f"--audio-samplerate={req.audio_samplerate}")
        if req.audio_channels is not None:
            cmd.append(f"--audio-channels={req.audio_channels}")
    if req.use_filenames_as_chapters:
        cmd.append("--use-filenames-as-chapters")

    if metadata.title:
        cmd.append(f"--name={metadata.title}")
        cmd.append(f"--album={metadata.title}")
    if metadata.author:
        cmd.append(f"--artist={metadata.author}")
        cmd.append(f"--albumartist={metadata.author}")
    if metadata.narrator:
        cmd.append(f"--writer={metadata.narrator}")
    if metadata.series:
        cmd.append(f"--series={metadata.series}")
    if metadata.sequence:
        cmd.append(f"--series-part={metadata.sequence}")
    if metadata.year:
        cmd.append(f"--year={metadata.year}")
    if metadata.summary:
        cmd.append(f"--description={metadata.summary[:240]}")
        cmd.append(f"--longdesc={metadata.summary}")
    cmd.append("--genre=Audiobook")
    cmd.append("--encoded-by=LibraForge")
    if metadata.cover_url:
        suffix = ".jpg"
        lower = metadata.cover_url.lower()
        if ".png" in lower:
            suffix = ".png"
        cover_file = Path(tempfile.mkstemp(prefix="m4b-cover-", suffix=suffix)[1])
        cover_file.write_bytes(read_cover_url_bytes(metadata.cover_url))
        temp_files.append(cover_file)
        cmd.append(f"--cover={cover_file}")

    return cmd, temp_files


def resolve_m4b_input_files(
    *,
    input_path: Path,
    output_path: Path,
    sidecar_path: str = "",
) -> list[Path]:
    if input_path.is_file():
        if input_path.resolve() == output_path.resolve():
            raise HTTPException(
                status_code=400,
                detail="M4B input and output paths cannot be the same file",
            )
        return [input_path]

    selected_sidecar: Path | None = None
    if sidecar_path:
        candidate = Path(sidecar_path).expanduser().resolve()
        if candidate.is_file():
            selected_sidecar = candidate
    if selected_sidecar is None:
        selected_sidecar = pick_sidecar(input_path, discover_sidecars(input_path))

    input_files: list[Path] = []
    if selected_sidecar:
        try:
            payload = json.loads(selected_sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        for value in ((payload.get("source", {}) or {}).get("chapter_files", []) or []):
            path = Path(value).expanduser().resolve()
            if (
                path.is_file()
                and is_audio_file(path)
                and path.resolve() != output_path.resolve()
            ):
                input_files.append(path)

    if not input_files:
        input_files = [
            path.resolve()
            for path in sorted(input_path.iterdir(), key=natural_path_sort_key)
            if path.is_file()
            and is_audio_file(path)
            and path.resolve() != output_path.resolve()
        ]

    if not input_files:
        raise HTTPException(
            status_code=400,
            detail="No source audio files remain after excluding the output file",
        )
    input_files.sort(key=natural_path_sort_key)
    return input_files


def set_mp4_text(tags: dict, key: str, value: str) -> None:
    value = str(value or "").strip()
    if value:
        tags[key] = [value]
    else:
        tags.pop(key, None)


def set_mp4_freeform(tags: dict, name: str, value: str) -> None:
    key = f"----:com.apple.iTunes:{name}"
    value = str(value or "").strip()
    if value:
        tags[key] = [MP4FreeForm(value.encode("utf-8"))]
    else:
        tags.pop(key, None)


def enforce_m4b_output_metadata(
    output_path: Path,
    metadata: M4BMetadataForm,
) -> None:
    metadata = normalize_m4b_metadata(metadata)
    audio = MP4(str(output_path))
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags

    set_mp4_text(tags, "\xa9nam", metadata.title)
    set_mp4_text(tags, "\xa9alb", metadata.title)
    set_mp4_text(tags, "\xa9ART", metadata.author)
    set_mp4_text(tags, "aART", metadata.author)
    set_mp4_text(tags, "\xa9wrt", metadata.narrator)
    set_mp4_text(tags, "\xa9grp", metadata.series)
    set_mp4_text(tags, "\xa9day", metadata.year)
    set_mp4_text(tags, "\xa9gen", "Audiobook")
    set_mp4_text(tags, "desc", metadata.summary[:240])
    set_mp4_text(tags, "ldes", metadata.summary)
    set_mp4_text(tags, "\xa9cmt", metadata.summary)
    tags["stik"] = [2]

    fixer_module = load_fixer_module(default_fixer_script())
    track_sequence = fixer_module.clean_sequence(metadata.sequence)
    if track_sequence:
        tags["trkn"] = [(int(track_sequence), 0)]
    else:
        tags.pop("trkn", None)

    for name in ("series", "mvnm"):
        set_mp4_freeform(tags, name, metadata.series)
    for name in ("series-part", "mvin"):
        set_mp4_freeform(tags, name, metadata.sequence)
    set_mp4_freeform(tags, "SUBTITLE", metadata.subtitle)
    set_mp4_freeform(tags, "NARRATOR", metadata.narrator)
    set_mp4_freeform(tags, "ASIN", metadata.asin)
    set_mp4_freeform(tags, "AUDIBLE_ASIN", metadata.asin)
    audio.save()


def probe_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
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
        return max(0.0, float(result.stdout.strip()))
    except ValueError:
        return 0.0


def m4b_input_duration_seconds(input_path: Path, output_path: Path) -> float:
    if input_path.is_file():
        return probe_duration_seconds(input_path)

    total = 0.0
    output_path = output_path.resolve()
    for path in input_path.rglob("*"):
        if not path.is_file() or not is_audio_file(path):
            continue
        if path.resolve() == output_path or any(part.endswith("-tmpfiles") for part in path.parts):
            continue
        total += probe_duration_seconds(path)
    return total


def monitor_m4b_progress(
    state: RunState,
    temp_dir: Path,
    expected_bytes: float,
    stop_event: threading.Event,
) -> None:
    if expected_bytes <= 0:
        return

    while not stop_event.wait(1):
        if not temp_dir.exists():
            continue
        sizes = (
            path.stat().st_size
            for path in temp_dir.rglob("*")
            if path.is_file() and is_audio_file(path)
        )
        encoded_bytes = sum(sizes)
        if encoded_bytes <= 0:
            continue
        estimated = min(90.0, (encoded_bytes / expected_bytes) * 90.0)
        if estimated > state.percent:
            state.percent = round(estimated, 1)
            set_run_phase(
                state,
                "encoding",
                "Encoding audio",
                f"{state.percent:.1f}% estimated from output size",
            )


def parse_m4b_line(state: RunState, line: str) -> bool:
    detected_phase = m4b_phase_for_line(line)
    if detected_phase:
        set_run_phase(state, *detected_phase)

    if line.startswith("found ") and " files to convert" in line:
        state.percent = max(state.percent, 1.0)
        return True

    spinner = M4B_SPINNER_RE.match(line)
    if spinner:
        remaining = int(spinner.group(1))
        total = int(spinner.group(2))
        state.current = max(0, total - remaining)
        state.total = total
        if remaining == 0:
            state.percent = max(state.percent, 90.0)
            set_run_phase(
                state,
                "finalizing",
                "Finalizing conversion",
                "All audio parts encoded",
            )
        elif state.phase != "encoding":
            set_run_phase(
                state,
                "converting",
                "Converting audio parts",
                f"{state.current} of {state.total} parts",
            )
        return False

    if line.startswith("running silence detection"):
        state.percent = max(state.percent, 92.0)
    elif line == "silence detection finished":
        state.percent = max(state.percent, 95.0)
    elif line.startswith("tagged file "):
        state.percent = max(state.percent, 98.0)
        tagged = M4B_TAGGED_CHAPTERS_RE.match(line)
        if tagged:
            state.stats["chapters_created"] = int(tagged.group(1))
    elif line.startswith("successfully merged "):
        state.percent = 100.0
    return True


def initial_organizer_stats() -> dict[str, Any]:
    return {
        "kind": "organizer",
        "found_items": 0,
        "ignored_mp3_files": 0,
        "skipped_existing_book_folders": 0,
        "structure_cache_entries": 0,
        "matched_existing_structure": 0,
        "ambiguous_structure_matches": 0,
        "skipped_ambiguous_structure": 0,
        "skipped_unknown_author": 0,
        "skipped_pattern_match": 0,
        "skipped_already_target": 0,
        "skipped_conflicts": 0,
        "planned_moves": 0,
        "moves_succeeded": 0,
        "moves_failed": 0,
        "mode": "",
        "move_items": [],
        "failed_move_items": [],
        "no_sidecars_warning": False,
    }


def finalize_organizer_move(state: RunState) -> None:
    current_move = state.parser_state.pop("organizer_current_move", None)
    is_failure = state.parser_state.pop("organizer_current_move_is_failure", False)
    if current_move:
        key = "failed_move_items" if is_failure else "move_items"
        state.stats.setdefault(key, []).append(current_move)


def parse_organizer_line(state: RunState, line: str) -> None:
    m = ORGANIZER_INDEX_PROGRESS_RE.match(line)
    if m:
        state.current = int(m.group(1))
        state.total = int(m.group(2))
        state.current_file = m.group(3).strip()
        state.percent = round((state.current / state.total) * 100, 2) if state.total else 0.0
        phase, label, _detail = organizer_progress_phase(
            indexing=True,
            refreshing=bool(state.parser_state.get("organizer_moves_started")),
        )
        set_run_phase(
            state,
            phase,
            label,
            f"Item {state.current} of {state.total}",
        )
        return

    m = ORGANIZER_PROGRESS_RE.match(line)
    if m:
        state.current = int(m.group(1))
        state.total = int(m.group(2))
        state.current_file = m.group(3).strip()
        state.percent = round((state.current / state.total) * 100, 2) if state.total else 0.0
        phase, label, _detail = organizer_progress_phase(indexing=False)
        set_run_phase(state, phase, label, f"Item {state.current} of {state.total}")
        return

    m = ORGANIZER_SUMMARY_RE.match(line)
    if m:
        key = {
            "Found book items": "found_items",
            "Ignored MP3 files": "ignored_mp3_files",
            "Skipped likely existing book folders": "skipped_existing_book_folders",
            "Skipped unknown author": "skipped_unknown_author",
            "Skipped by pattern": "skipped_pattern_match",
            "Skipped already in target folder": "skipped_already_target",
            "Skipped conflicts": "skipped_conflicts",
            "Structure cache entries": "structure_cache_entries",
            "Matched existing structure": "matched_existing_structure",
            "Ambiguous structure matches": "ambiguous_structure_matches",
            "Skipped ambiguous structure": "skipped_ambiguous_structure",
            "Planned moves": "planned_moves",
            "Moves succeeded": "moves_succeeded",
            "Moves failed": "moves_failed",
        }[m.group(1)]
        state.stats[key] = int(m.group(2))
        set_run_phase(state, "summarizing", "Calculating move summary", line)
        return

    m = ORGANIZER_MODE_RE.match(line)
    if m:
        state.stats["mode"] = m.group(1)
        label = "Preparing move operation" if m.group(1) == "APPLY" else "Preparing move preview"
        set_run_phase(state, "planning", label, f"Mode: {m.group(1)}")
        return

    if line == "Rebuilding structure cache...":
        set_run_phase(state, "caching", "Rebuilding structure cache", "Scanning library for cache update...")
        return

    if line == "Structure cache rebuild complete.":
        set_run_phase(state, "caching", "Structure cache updated", "Cache is ready for next run.")
        return

    if line == "NO_SIDECARS_FOUND":
        state.stats["no_sidecars_warning"] = True
        set_run_phase(state, "summarizing", "No fixer sidecars found", line)
        return

    if line in ("BOOK:", "FAILED BOOK:"):
        finalize_organizer_move(state)
        state.parser_state["organizer_current_move"] = {"companions": []}
        state.parser_state["organizer_current_move_is_failure"] = line == "FAILED BOOK:"
        state.parser_state["organizer_section"] = ""
        apply_mode = state.stats.get("mode") == "APPLY"
        state.parser_state["organizer_moves_started"] = apply_mode
        set_run_phase(
            state,
            *organizer_move_phase(
                apply_mode,
                len(state.stats.get("move_items", [])) + 1,
            ),
        )
        return

    current_move = state.parser_state.get("organizer_current_move")
    if not current_move:
        return

    m = ORGANIZER_FIELD_RE.match(line)
    if m:
        key = {
            "Kind": "kind",
            "Title": "title",
            "Author": "author",
            "Files": "files",
            "Metadata Source": "metadata_source",
            "Review Reasons": "review_reasons",
            "Series": "series",
            "Number": "number",
            "Structure": "structure",
            "Error": "error",
        }[m.group(1)]
        value = m.group(2).strip()
        if key == "files" and value.isdigit():
            current_move[key] = int(value)
        elif key == "review_reasons":
            current_move[key] = [reason.strip() for reason in value.split("|") if reason.strip()]
        else:
            current_move[key] = value
        return

    if line.strip() == "MOVE:":
        state.parser_state["organizer_section"] = "source"
        return
    if line.strip() == "TO:":
        state.parser_state["organizer_section"] = "target"
        return
    if line.strip() == "COMPANION FILES:":
        state.parser_state["organizer_section"] = "companions"
        return

    if not line.startswith("    "):
        return

    value = line.strip()
    section = state.parser_state.get("organizer_section", "")
    if section == "source":
        current_move["source"] = value
    elif section == "target":
        current_move["target"] = value
    elif section == "companions":
        current_move["companions"].append(value)


def build_organizer_command(req: OrganizerRunRequest) -> list[str]:
    script_path = live_script_path(req.script_name, "organizer")
    cmd = ["python3", "-u", str(script_path), req.root_path]
    if req.destination_root:
        cmd += ["--destination-root", req.destination_root]
    if req.rebuild_structure_cache:
        cmd.append("--rebuild-structure-cache")
    if req.consolidate_structures:
        cmd.append("--consolidate-structures")
    if req.index_only:
        cmd.append("--index-only")
    if req.apply:
        cmd.append("--apply")
    if req.m4b_only:
        cmd.append("--m4b-only")
    if req.allow_unknown_author:
        cmd.append("--allow-unknown-author")
    if req.include_existing_book_folders:
        cmd.append("--include-existing-book-folders")
    if req.no_companions:
        cmd.append("--no-companions")
    if req.remove_empty_dirs:
        cmd.append("--remove-empty-dirs")
    if req.max_items > 0:
        cmd += ["--max-items", str(req.max_items)]
    if req.progress_every >= 0:
        cmd += ["--progress-every", str(req.progress_every)]
    for pattern in req.skip_patterns:
        pattern = pattern.strip()
        if pattern:
            cmd += ["--skip-pattern", pattern]
    if req.acknowledge_no_sidecars:
        cmd.append("--acknowledge-no-sidecars")
    if req.use_default_scheme:
        cmd.append("--use-default-scheme")
    elif req.naming_template.strip():
        cmd += ["--naming-template", req.naming_template]

    return cmd


def run_script_worker(run_id: str, req: RunRequest) -> None:
    with runs_lock:
        state = runs[run_id]

    state.run_type = "fixer"
    threshold = float(req.duration_review_threshold or 10.0)
    state.stats = initial_stats(threshold)
    state.log_path = REPORTS_DIR / f"{run_id}.log.txt"
    set_run_phase(
        state,
        "discovering",
        "Discovering audiobooks",
        req.target_path,
    )

    try:
        cmd, threshold = build_command(req)
        state.command = cmd
        state.status = "running"
        stream_process_output(state, cmd, threshold=threshold)
        if state.status != "cancelled":
            try:
                state.report_items.extend(scan_ebook_units_for_report(Path(req.target_path)))
            except Exception as exc:
                print(f"scan_ebook_units_for_report failed, continuing without ebook items: {exc}", file=sys.stderr)
        state.finished_at = time.time()
        if state.status != "cancelled":
            state.status = "completed" if state.returncode == 0 else "failed"
        set_terminal_phase(state)
        write_final_report(state)
    except Exception as exc:
        state.error = str(exc)
        state.finished_at = time.time()
        state.status = "failed"
        set_terminal_phase(state)
        try:
            write_final_report(state)
        except Exception:
            pass
    finally:
        with runs_lock:
            runs.pop(run_id, None)


def _aggregate_m4b_libraforge(input_path: Path, output_path: Path) -> None:
    """After a successful m4b-tool merge, fold the source folder's libraforge.json
    data into the output file's libraforge.json and clean up the old folder file."""
    try:
        source_folder = input_path if input_path.is_dir() else input_path.parent
        folder_lf = source_folder / "libraforge.json"
        out_lf = output_path.with_name(f"{output_path.name}.libraforge.json")
        out_payload: dict = {}

        if out_lf.is_file():
            try:
                out_payload = json.loads(out_lf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                out_payload = {}

        if folder_lf.is_file():
            try:
                src = json.loads(folder_lf.read_text(encoding="utf-8"))
                for key in ("sidecar", "file_cache", "marker"):
                    if key in src and key not in out_payload:
                        out_payload[key] = src[key]
            except (OSError, json.JSONDecodeError):
                pass

        if out_payload:
            out_payload.setdefault("schema_version", 2)
            out_payload.setdefault("tool", "audible-metadata-fixer")
            out_payload["merged_from"] = str(source_folder)
            out_payload["merged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            out_lf.write_text(
                json.dumps(out_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        # Clean up folder-level libraforge and any per-chapter libraforge files
        if folder_lf.is_file():
            folder_lf.unlink(missing_ok=True)
        if source_folder.is_dir():
            for ch_lf in source_folder.glob("*.libraforge.json"):
                ch_lf.unlink(missing_ok=True)
    except Exception:
        pass  # aggregation is best-effort; never fail a successful merge


def run_m4b_worker(run_id: str, req: M4BRunRequest) -> None:
    with runs_lock:
        state = runs[run_id]

    state.stats = {"kind": "m4b-tool"}
    state.log_path = REPORTS_DIR / f"{run_id}.log.txt"
    set_run_phase(state, "calculating", "Calculating conversion", req.input_path)
    temp_files: list[Path] = []
    run_temp_dir = Path(tempfile.gettempdir()) / f"m4b-tool-{run_id}"
    progress_stop = threading.Event()
    progress_thread: threading.Thread | None = None

    try:
        input_path = validate_audiobook_path(req.input_path)
        output_path = validate_audiobook_output_path(req.output_path)
        duration = m4b_input_duration_seconds(input_path, output_path)
        bitrate = int(req.audio_bitrate.removesuffix("k")) * 1000
        expected_bytes = 0.0 if req.no_conversion else duration * bitrate / 8
        state.stats.update(
            {
                "input_duration_seconds": round(duration, 3),
                "audio_codec": req.audio_codec,
                "audio_bitrate": req.audio_bitrate,
                "audio_samplerate": req.audio_samplerate,
                "audio_channels": req.audio_channels,
            }
        )
        set_run_phase(
            state,
            "preparing",
            "Preparing conversion",
            f"Input duration: {round(duration, 1)} seconds",
        )
        if req.save_sidecar:
            set_run_phase(
                state,
                "saving-sidecar",
                "Saving metadata sidecar",
                req.sidecar_path or req.input_path,
            )
            save_sidecar_file(
                source_path=input_path,
                metadata=req.metadata,
                requested_sidecar_path=req.sidecar_path,
                excluded_paths={output_path},
            )

        cmd, temp_files = build_m4b_command(req, run_temp_dir)
        state.command = cmd
        state.status = "running"
        state.current_file = req.input_path
        progress_thread = threading.Thread(
            target=monitor_m4b_progress,
            args=(state, run_temp_dir, expected_bytes, progress_stop),
            daemon=True,
        )
        progress_thread.start()
        stream_process_output(state, cmd, threshold=None, line_parser=parse_m4b_line)
        if state.returncode == 0 and state.status != "cancelled":
            set_run_phase(
                state,
                "tagging",
                "Enforcing fixed metadata",
                str(output_path),
            )
            enforce_m4b_output_metadata(output_path, req.metadata)
            state.stats["metadata_enforced"] = True
            _aggregate_m4b_libraforge(input_path, output_path)
        state.finished_at = time.time()
        if state.status != "cancelled":
            state.status = "completed" if state.returncode == 0 else "failed"
            if state.status == "completed":
                state.percent = 100.0
        set_terminal_phase(state)
        write_final_report(state)
    except Exception as exc:
        state.error = str(exc)
        state.finished_at = time.time()
        state.status = "failed"
        set_terminal_phase(state)
        try:
            write_final_report(state)
        except Exception:
            pass
    finally:
        progress_stop.set()
        if progress_thread is not None:
            progress_thread.join(timeout=2)
        shutil.rmtree(run_temp_dir, ignore_errors=True)
        for temp_file in temp_files:
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass
        with runs_lock:
            runs.pop(run_id, None)


def run_organizer_worker(run_id: str, req: OrganizerRunRequest) -> None:
    with runs_lock:
        state = runs[run_id]

    state.stats = initial_organizer_stats()
    state.log_path = REPORTS_DIR / f"{run_id}.log.txt"
    initial_label = (
        "Preparing structure cache"
        if req.rebuild_structure_cache or req.index_only
        else "Loading structure cache"
    )
    set_run_phase(state, "preparing-cache", initial_label, req.destination_root)

    try:
        cmd = build_organizer_command(req)
        state.command = cmd
        state.status = "running"
        state.current_file = req.root_path
        stream_process_output(state, cmd, threshold=None, line_parser=parse_organizer_line)
        finalize_organizer_move(state)
        state.finished_at = time.time()
        if state.status != "cancelled":
            state.status = "completed" if state.returncode == 0 else "failed"
        set_terminal_phase(state)
        write_final_report(state)
    except Exception as exc:
        state.error = str(exc)
        state.finished_at = time.time()
        state.status = "failed"
        set_terminal_phase(state)
        try:
            write_final_report(state)
        except Exception:
            pass
    finally:
        with runs_lock:
            runs.pop(run_id, None)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Kick off the Manual Review filesystem search index build immediately
    # on startup, in the background, so it's already underway (or done, for
    # a modest library) before anyone opens Manual Review. Referencing
    # _ensure_manual_review_search_index_fresh here works even though it's
    # defined later in this module -- name lookup inside a function body
    # happens at call time, well after the whole module has loaded.
    _ensure_manual_review_search_index_fresh([])
    yield


app = FastAPI(title="LibraForge", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/app-icon.png")
def app_icon() -> FileResponse:
    return FileResponse(ICON_FILE, media_type="image/png")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "LibraForge"}


VERSION_FILE = APP_ROOT / "VERSION"


@app.get("/api/version")
def get_version() -> dict[str, str]:
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        version = "dev"
    return {"version": version or "dev"}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {"audiobooks_root": str(AUDIOBOOKS_ROOT)}




@app.get("/api/fs/ls")
def fs_ls(path: str = "/") -> dict[str, Any]:
    p = Path(path)
    if not p.is_dir():
        p = p.parent
    if not p.is_dir():
        return {"dirs": [], "path": path}
    try:
        dirs = sorted(
            str(child)
            for child in p.iterdir()
            if child.is_dir() and not any(child.name.startswith(s) for s in _FS_SKIP_PREFIXES)
        )
    except PermissionError:
        dirs = []
    return {"dirs": dirs, "path": str(p)}


class ScanRequest(BaseModel):
    path: str
    ignored_folders: list[str] = Field(default_factory=list)


_ASIN_TAG_KEYS = (
    "----:com.apple.iTunes:asin",
    "----:com.pilabor.tone:AUDIBLE_ASIN",
    "----:com.apple.iTunes:ASIN",
)
_FIXER_SIDECAR_SUFFIX = ".audible-metadata-fixer.json"
_FIXER_LEGACY_MARKER = ".audible-metadata-fixer.json"


_NOREALASIN = "NOREALASIN"


def _asin_from_libraforge_json(path: Path) -> bool | None:
    """Read ASIN from a libraforge.json sidecar.

    Returns True (real ASIN present), False (NOREALASIN sentinel cached),
    or None (field absent/empty -- fall through to mutagen).
    Checks scan_cache.asin first (isolated from organizer fields), then
    marker.audible.asin and audible.asin set by the fixer/M4B tool.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Dedicated scan cache key -- written only by _write_scan_asin_cache,
        # never by the fixer or organizer, so safe to read for scan purposes.
        scan_asin = str((data.get("scan_cache") or {}).get("asin") or "").strip()
        if scan_asin:
            return scan_asin != _NOREALASIN
        # Fixer / M4B tool fields
        asin = str(
            ((data.get("marker") or {}).get("audible") or {}).get("asin")
            or (data.get("audible") or {}).get("asin")
            or ""
        ).strip()
        if not asin:
            return None
        return asin != _NOREALASIN
    except Exception:
        return None


def _write_scan_asin_cache(folder: Path, audio_file: Path, asin: str) -> None:
    """Cache scan ASIN result in an existing libraforge.json under scan_cache.asin.

    Only updates existing sidecars -- never creates new ones -- to avoid
    producing thin sidecars that break manual_review_sidecar_context.
    Writes to a dedicated scan_cache key so organizer fields are untouched.
    """
    candidates = [
        audio_file.parent / (audio_file.name + ".libraforge.json"),
        folder / "libraforge.json",
    ]
    sidecar = next((p for p in candidates if p.is_file()), None)
    if sidecar is None:
        return  # no existing sidecar -- don't create thin ones
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return
    data.setdefault("scan_cache", {})["asin"] = asin
    try:
        sidecar.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass


# Core metadata fields the scan requires for a book to count as "complete".
# A book is complete only when it has a real ASIN AND each of these. Series and
# sequence are intentionally excluded (standalone books legitimately lack them);
# year is treated as optional for the same reason.
_CORE_FIELDS = ("title", "author", "narrator")
_CORE_MP4_KEYS = {
    "title": ("\xa9nam",),
    "author": ("\xa9ART", "aART"),
    "narrator": ("\xa9wrt",),  # the fixer writes narrator to the composer atom
}
_CORE_ID3_KEYS = {
    "title": ("TIT2",),
    "author": ("TPE1",),
    "narrator": ("TCOM",),
}
_SCAN_AUDIO_EXTS = (".m4b", ".m4a", ".mp3", ".mp4")


def _probe_book_metadata(audio_file: Path) -> dict:
    """Read the ASIN and core fields from an audio file in a single tag load.

    Returns ``{"asin": <str>, "fields": {"title": bool, "author": bool,
    "narrator": bool}}`` -- ``asin`` is "" when absent.
    """
    fields = {f: False for f in _CORE_FIELDS}
    asin = ""
    try:
        suffix = audio_file.suffix.lower()
        if suffix in (".m4b", ".m4a", ".mp4"):
            tags = MP4(str(audio_file)).tags or {}
            for key in _ASIN_TAG_KEYS:
                raw = tags.get(key, [])
                if raw:
                    val = raw[0]
                    text = (
                        bytes(val).decode("utf-8", errors="ignore")
                        if isinstance(val, (bytes, bytearray, MP4FreeForm))
                        else str(val)
                    ).strip()
                    if text:
                        asin = text
                        break
            for field, keys in _CORE_MP4_KEYS.items():
                for k in keys:
                    raw = tags.get(k)
                    if raw and str(raw[0]).strip():
                        fields[field] = True
                        break
        elif suffix == ".mp3":
            from mutagen.id3 import ID3  # noqa: PLC0415
            t = ID3(str(audio_file))
            if any("asin" in k.lower() for k in t.keys()):
                asin = "HAS_ASIN"
            for field, keys in _CORE_ID3_KEYS.items():
                for k in keys:
                    frame = t.get(k)
                    if frame and str(frame).strip():
                        fields[field] = True
                        break
    except Exception:
        pass
    return {"asin": asin, "fields": fields}


def _scan_sidecar_target(
    audio_files: list[Path], book_dir: Path, audio_file: Path, fixer=None
) -> Path:
    """Canonical libraforge.json path for the scan, decided by the fixer itself.

    Delegates to the fixer's ``get_libraforge_path`` so the scan and a real run
    always agree on placement: multi-file (grouped) books and single files alone
    in their folder use a folder-level ``libraforge.json``; a single file sharing
    its folder with other books uses a per-file ``<name>.libraforge.json``.
    """
    fixer = fixer or scan_fixer_module()
    grouped = len(audio_files) > 1
    if grouped:
        alone = False
    else:
        try:
            alone = sum(
                1 for x in audio_file.parent.iterdir()
                if x.is_file() and x.suffix.lower() in _SCAN_AUDIO_EXTS
            ) <= 1
        except OSError:
            alone = True
    clues = {"group_search": {"applied": grouped}}
    return fixer.get_libraforge_path(audio_file, clues, alone)


def _ensure_scan_sidecar(
    audio_files: list[Path], book_dir: Path, audio_file: Path, asin: str, fields: dict,
    fixer=None,
) -> None:
    """Persist the probe result to the canonical libraforge.json, in the fixer's format.

    Writes only to the path the fixer would use (``get_libraforge_path``) and only
    the ``scan_cache`` key, using the fixer's own writer for byte-for-byte format
    parity. It never adopts a folder-level file for a per-file book, so distinct
    single-file books sharing a folder can no longer clobber one shared sidecar.
    The audio file's mtime is stored so a later tag change invalidates the cache.
    """
    fixer = fixer or scan_fixer_module()
    target = _scan_sidecar_target(audio_files, book_dir, audio_file, fixer)
    # If the canonical file is missing but this book's own per-file sidecar exists
    # (e.g. a pending fixer file->folder migration for a now-alone book), update it
    # in place rather than create a duplicate. Never reach for a folder-level file.
    if not target.is_file():
        own_file_lf = audio_file.with_name(audio_file.name + ".libraforge.json")
        if target == book_dir / "libraforge.json" and own_file_lf.is_file():
            target = own_file_lf
    payload: dict = {}
    if target.is_file():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 2)
    payload.setdefault("tool", "audible-metadata-fixer")
    try:
        mtime = audio_file.stat().st_mtime_ns
    except OSError:
        mtime = None
    payload["scan_cache"] = {
        **(payload.get("scan_cache") or {}),
        "asin": asin or _NOREALASIN,
        "fields": fields,
        "mtime": mtime,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fixer._write_libraforge(target, payload)
    except Exception:
        pass


def _marker_says_no_asin(data: dict) -> bool:
    """True iff the fixer's marker records NOREALASIN -- a confirmed determination
    that no Audible match exists. A marker that names a *real* ASIN is ignored
    here (the embedded tag is the source of truth for a real ASIN), so a book
    whose marker claims an ASIN it never wrote stays Incomplete."""
    asin = str(((data.get("marker") or {}).get("audible") or {}).get("asin") or "").strip().upper()
    return asin == _NOREALASIN


def _sidecar_marker_no_asin(audio_file: Path, book_dir: Path) -> bool:
    """Read the fixer's NOREALASIN determination from a libraforge.json sidecar."""
    for sidecar in (
        audio_file.parent / (audio_file.name + ".libraforge.json"),
        book_dir / "libraforge.json",
    ):
        if sidecar.is_file():
            try:
                if _marker_says_no_asin(json.loads(sidecar.read_text(encoding="utf-8"))):
                    return True
            except Exception:
                continue
    return False


def _scan_cache_from_sidecar(audio_file: Path, book_dir: Path) -> tuple[bool, dict] | None:
    """Return cached ``(asin_satisfied, fields)`` from a fresh scan_cache, or None.

    ``asin_satisfied`` is True when a real ASIN is embedded OR the fixer confirmed
    NOREALASIN (no Audible match exists). The NOREALASIN determination is re-read
    from the marker on every call -- it is cheap and can change without the audio
    file changing -- while the (expensive) field/ASIN probe stays mtime-cached.
    None means no usable cache (absent, old asin-only cache, or stale) -- re-probe.
    """
    for sidecar in (
        audio_file.parent / (audio_file.name + ".libraforge.json"),
        book_dir / "libraforge.json",
    ):
        if not sidecar.is_file():
            continue
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            continue
        sc = data.get("scan_cache") or {}
        fields = sc.get("fields")
        if not isinstance(fields, dict) or "asin" not in sc:
            return None  # old asin-only cache -- need a full probe
        try:
            cur_mtime = audio_file.stat().st_mtime_ns
        except OSError:
            cur_mtime = None
        if sc.get("mtime") != cur_mtime:
            return None  # file changed since cached -- re-probe
        asin_embedded = str(sc.get("asin") or "").strip() not in ("", _NOREALASIN)
        asin_satisfied = asin_embedded or _marker_says_no_asin(data)
        return asin_satisfied, {f: bool(fields.get(f)) for f in _CORE_FIELDS}
    return None


def _book_metadata_state(book_dir: Path, audio_files: list[Path]) -> tuple[bool, dict]:
    """Return ``(asin_satisfied, {field: present})`` for a book.

    Reads the embedded tags (cached in a libraforge.json scan_cache). ASIN is
    "satisfied" when a real ASIN is embedded OR the fixer marked NOREALASIN, so a
    book that genuinely has no Audible match stops being flagged Incomplete once
    its core fields are present. A marker's *claimed* real ASIN is not trusted --
    only the actual embedded tag counts for a real ASIN."""
    audio_file = audio_files[0]
    cached = _scan_cache_from_sidecar(audio_file, book_dir)
    if cached is not None:
        return cached
    probe = _probe_book_metadata(audio_file)
    asin_embedded = bool(probe["asin"]) and probe["asin"] != _NOREALASIN
    asin_satisfied = asin_embedded or _sidecar_marker_no_asin(audio_file, book_dir)
    _ensure_scan_sidecar(audio_files, book_dir, audio_file, probe["asin"], probe["fields"])
    return asin_satisfied, probe["fields"]


def _book_audio_files(folder: Path) -> list[Path]:
    """Direct audio files in a book folder, or files one level down (disc subfolders).

    A loose audio file (book unit that is itself a file) returns just itself.
    """
    if folder.is_file():
        return [folder] if is_audio_file(folder) else []
    direct = sorted(c for c in folder.iterdir() if c.is_file() and is_audio_file(c))
    if direct:
        return direct
    nested: list[Path] = []
    for sub in folder.iterdir():
        if sub.is_dir():
            nested.extend(c for c in sub.iterdir() if c.is_file() and is_audio_file(c))
    return sorted(nested)


def _find_book_folders(root: Path) -> list[Path]:
    """
    Recursively find all book-level folders under root at any depth.
    Handles Author/Series/Book/file and disc-subfolder patterns.
    A folder that matches the disc naming pattern (Disc 1, CD2, Part 3…) is
    collapsed into its parent so multi-disc books count as one.

    Delegates to library_index.build_library_index -- the same walk shared
    by Manual Review search, M4B discovery, and Folder Forge scan -- instead
    of maintaining a second, independent copy of the walk/disc-collapse
    logic that a future fix to that shared walk wouldn't reach.
    """
    entries, _signatures = library_index.build_library_index(root)
    return [path for path, _is_file in entries]


def _filter_entries_by_ignored_folders(
    entries: list[tuple[str, bool]], root: Path, ignored_folders: list[str]
) -> list[tuple[str, bool]]:
    """Post-filter the shared index's entries by ignored_folders: an entry
    is dropped if any path component between root and the entry (the
    entry's own folder name included, a loose file's own filename
    excluded) starts with an ignore token, case-insensitively. Mirrors
    matches_ignored_folders' semantics (fixer script) as an in-memory
    filter over an already-built list, since the shared walker itself has
    no concept of any single consumer's ignore list.
    """
    tokens = tuple(f.strip().lower() for f in (ignored_folders or []) if f and f.strip())
    if not tokens:
        return list(entries)
    kept: list[tuple[str, bool]] = []
    for path_str, is_file in entries:
        path = Path(path_str)
        check_path = path.parent if is_file else path
        try:
            rel_parts = check_path.relative_to(root).parts
        except ValueError:
            rel_parts = check_path.parts
        if not any(part.lower().startswith(token) for part in rel_parts for token in tokens):
            kept.append((path_str, is_file))
    return kept


@dataclass
class _ManualReviewSearchIndex:
    """In-memory state for the Manual Review filesystem search index.

    Derived from the shared library_index state rather than running its own
    walk. source_generation tracks which shared-index generation this was
    last derived from, replacing the old root+first-level fingerprint as
    the staleness signal. ebook_source_generation is the equivalent signal
    for the fully-independent ebook index (see app/library_index.py).
    """
    status: str = "idle"  # idle | building | updating | ready | error
    entries: list[tuple[str, bool]] = field(default_factory=list)
    book_count: int = 0
    source_generation: int = -1
    ebook_source_generation: int = -1
    ignored_signature: str | None = None
    error: str | None = None
    ebook_formats: dict[str, list[str]] = field(default_factory=dict)


_manual_review_search_index = _ManualReviewSearchIndex()
_manual_review_search_lock = threading.Lock()


def _manual_review_search_index_is_stale(
    state: _ManualReviewSearchIndex, generation: int, ebook_generation: int, ignored_signature: str
) -> bool:
    """Whether Manual Review's own derived entries need rebuilding from the
    current shared index state. A build already in flight is never
    re-triggered; an error state always retries.

    source_generation == -1 with status == "ready" only happens when a
    caller (e.g. a test fixture) marks the state ready directly, bypassing
    _run_manual_review_search_index_build, which always records a real
    (non-negative) generation. Real production code never produces this
    combination, so it is safe to treat it as "trust the caller's snapshot"
    rather than force an immediate rebuild the caller has no way to predict
    or avoid -- the ignore-list signature is still honored either way.
    """
    if state.status in ("building", "updating"):
        return False
    if state.status == "ready" and state.source_generation == -1:
        return state.ignored_signature != ignored_signature
    return (
        state.status != "ready"
        or state.source_generation != generation
        or state.ebook_source_generation != ebook_generation
        or state.ignored_signature != ignored_signature
    )


def _run_manual_review_search_index_build(
    state: _ManualReviewSearchIndex, root: Path, ignored_folders: list[str]
) -> None:
    """Synchronously derive state's entries from the current shared index
    state. Directly testable; callers wanting this off the request thread
    wrap it in a background thread."""
    state.status = "updating" if state.entries else "building"
    state.error = None
    try:
        shared = library_index.get_state()
        if shared.status == "idle":
            # The shared walker has never completed a single walk yet (cold
            # start), not just "stale" -- deriving now would mark this
            # index "ready" with an empty/incomplete result, which is worse
            # than staying in the already-set building/updating status a
            # bit longer. ensure_library_index_fresh already triggered a
            # walk before this worker was scheduled; wait for it here
            # (off the request thread, so blocking is harmless) instead of
            # reporting a false-ready empty index. The first cold walk of a
            # large library over a network mount can genuinely take tens of
            # seconds with no per-folder progress signal to poll on, so the
            # bound here is a safety valve against a truly hung walk, not a
            # normal-case timeout -- it should never fire in practice.
            deadline = time.monotonic() + 600
            while shared.status == "idle" and time.monotonic() < deadline:
                time.sleep(0.05)
                shared = library_index.get_state()
        ebook_shared = library_index.get_ebook_state()
        audio_entries = _filter_entries_by_ignored_folders(shared.entries, root, ignored_folders)
        raw_ebook_entries = [(str(unit.path), True) for unit in ebook_shared.units]
        ebook_entries = _filter_entries_by_ignored_folders(raw_ebook_entries, root, ignored_folders)
        state.entries = audio_entries + ebook_entries
        ebook_entry_paths = {path for path, _ in ebook_entries}
        state.ebook_formats = {
            str(unit.path): sorted(unit.formats.keys())
            for unit in ebook_shared.units
            if str(unit.path) in ebook_entry_paths
        }
        state.book_count = len(state.entries)
        state.source_generation = shared.generation
        state.ebook_source_generation = ebook_shared.generation
        state.ignored_signature = _ignored_signature(ignored_folders)
        state.status = "ready"
    except Exception as exc:
        state.status = "error"
        state.error = str(exc)


def _ensure_manual_review_search_index_fresh(ignored_folders: list[str]) -> None:
    """Kick a non-blocking background rebuild of the shared index if
    needed, then a non-blocking rebuild of this state's own filtered
    entries if the shared index has moved on or the ignore list changed.
    Returns immediately whether or not a build was started."""
    library_index.ensure_library_index_fresh(AUDIOBOOKS_ROOT)
    library_index.ensure_ebook_index_fresh(AUDIOBOOKS_ROOT)

    state = _manual_review_search_index
    shared = library_index.get_state()
    ebook_shared = library_index.get_ebook_state()
    signature = _ignored_signature(ignored_folders)
    if not _manual_review_search_index_is_stale(state, shared.generation, ebook_shared.generation, signature):
        return
    if not _manual_review_search_lock.acquire(blocking=False):
        return

    def worker() -> None:
        try:
            _run_manual_review_search_index_build(state, AUDIOBOOKS_ROOT, ignored_folders)
        finally:
            _manual_review_search_lock.release()

    threading.Thread(target=worker, daemon=True).start()


def _scan_book_units(p: Path) -> list[tuple[Path, list[Path], Path]]:
    """Book units under ``p``, counted exactly like a real fixer run.

    Returns ``(ref, audio_files, book_dir)`` where ``ref`` is the containing folder for
    a grouped multi-part book or the file itself for a standalone book. A folder holding
    several complete books (each its own file) yields one unit per book, while a folder
    of chapter files yields a single unit — reusing the fixer's chapter-count-based
    multi-part grouping so the scan and a run agree. Falls back to folder-based discovery
    if the fixer module cannot be loaded.
    """
    try:
        fixer = load_fixer_module(default_fixer_script())
        files = fixer.collect_audio_files(p)
        group_map = fixer.build_multi_part_group_map(files)
        units = fixer.build_processing_items(files, group_map)
    except Exception:
        out: list[tuple[Path, list[Path], Path]] = []
        for folder in _find_book_folders(p):
            out.append((folder, _book_audio_files(folder), folder if folder.is_dir() else folder.parent))
        return out

    out = []
    for unit in units:
        group_files = group_map.get(unit.parent)
        if group_files and unit in group_files:
            out.append((unit.parent, list(group_files), unit.parent))
        else:
            out.append((unit, [unit], unit.parent))
    return out


def _filter_ignored_units(
    units: list[tuple[Path, list[Path], Path]],
    scan_root: Path,
    ignored_folders: list[str],
    fixer=None,
) -> list[tuple[Path, list[Path], Path]]:
    """Drop units under an ignored folder, reusing the fixer's matcher.

    Matching is relative to ``scan_root`` so the same configured folder (e.g.
    ``_unorganized``) is skipped during a library-root scan but still scanned when
    the user targets it directly. This keeps the scanner from touching, and
    creating sidecars in, folders the fixer is told to ignore.
    """
    folders = [f.strip() for f in (ignored_folders or []) if f and f.strip()]
    if not folders:
        return units
    fixer = fixer or scan_fixer_module()
    kept: list[tuple[Path, list[Path], Path]] = []
    for unit in units:
        ref, audio, book_dir = unit
        probe = audio[0] if audio else (book_dir or ref)
        try:
            rel = Path(probe).relative_to(scan_root)
        except ValueError:
            rel = Path(probe)
        skip, _ = fixer.matches_ignored_folders(rel, folders)
        if not skip:
            kept.append(unit)
    return kept


def _categorise_book_unit(audio: list[Path], book_dir: Path, scan_root: Path) -> str:
    if not audio:
        return "skip"
    # A book is "complete" only with a real ASIN AND every core field present.
    asin_present, fields = _book_metadata_state(book_dir, audio)
    complete = asin_present and all(fields.get(f) for f in _CORE_FIELDS)
    single_m4b = len(audio) == 1 and audio[0].suffix.lower() == ".m4b"
    if not complete:
        return "needs_metadata"
    if not single_m4b:
        return "needs_conversion"
    # "organized" only when scanning the library root itself and the book sits in a
    # proper Author/... subdirectory (depth > 1 under AUDIOBOOKS_ROOT). Anything
    # scanned from a subfolder (e.g. _unorganized) is always "ready_to_organize".
    if scan_root == AUDIOBOOKS_ROOT:
        try:
            depth = len(book_dir.relative_to(AUDIOBOOKS_ROOT).parts)
        except ValueError:
            depth = 1
        return "organized" if depth > 1 else "ready_to_organize"
    return "ready_to_organize"


_COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "cover.jpeg")

_AUDIO_EXTS_COVER = ("*.m4b", "*.m4a", "*.mp3", "*.mp4")


def _library_fingerprint(root: Path) -> str:
    """Fast change-detection fingerprint: root mtime + first-level subdir names/mtimes.
    Catches new/removed author folders and changes inside existing author folders.
    ~100 stat() calls on a typical audiobook library = <500ms even over NFS."""
    parts: list[str] = []
    try:
        parts.append(str(root.stat().st_mtime_ns))
        for child in sorted(root.iterdir()):
            if child.is_dir() and not any(child.name.startswith(s) for s in _FS_SKIP_PREFIXES):
                parts.append(f"{child.name}:{child.stat().st_mtime_ns}")
    except PermissionError:
        pass
    return "|".join(parts)


def _ignored_signature(ignored_folders: list[str] | None) -> str:
    """Order/case/whitespace-independent signature of an ignore-folder list,
    so a config change can be detected by simple string comparison."""
    return ",".join(sorted(f.strip().lower() for f in (ignored_folders or []) if f and f.strip()))


def _has_cover_fast(folder: Path) -> bool:
    """Fast cover heuristic: file covers or any audio file presence."""
    if folder.is_file():
        return True  # loose audio book unit — treat as present
    if any((folder / n).is_file() for n in _COVER_NAMES):
        return True
    for ext in _AUDIO_EXTS_COVER:
        if next(folder.glob(ext), None):
            return True
    for sub in folder.iterdir():
        if sub.is_dir():
            for ext in _AUDIO_EXTS_COVER:
                if next(sub.glob(ext), None):
                    return True
    return False


def _categorized_book_units(
    p: Path, ignored_folders: list[str], shared: "library_index.LibraryIndexState"
) -> tuple[list[tuple[Path, Path, str]], bool]:
    """Return (book_results, all_from_cache) for scan root p.

    Each book_results entry is (ref, book_dir, category): ref is the unit's
    display path (a file for a standalone book, a folder for a grouped one),
    while book_dir is always the real containing folder -- callers that need
    an actual directory (e.g. a cover-presence check) must use book_dir, not
    ref, since ref can be a plain file for a standalone unit.

    Per folder under p, compares the shared index's current listing
    signature against what is stored in FOLDER_SCAN_CACHE for that folder.
    A folder's cache entry is {"signature": str, "units": {ref_str: category}}
    -- one signature per folder (the folder's listing as a whole), but a map
    of per-unit categories, because _scan_book_units can yield more than one
    unit for a single folder (e.g. two complete standalone books sitting
    side by side in an _unorganized dump folder both resolve to that same
    folder as their book_dir). Collapsing those into one shared category
    field previously meant whichever unit's write ran last in the loop below
    silently overwrote every sibling unit's cached category. When the
    folder's signature is unchanged AND a given unit's own ref is present in
    the folder's "units" map, that unit is a cache hit and reuses its own
    stored category; any other unit is recategorized (via
    _categorise_book_unit, which is cheap -- metadata/tag reads, no ffprobe
    subprocess for the common case) and written back into that folder's
    "units" map without disturbing its still-valid siblings. A folder whose
    signature changed has its entire "units" map treated as stale and
    replaced outright, since a signature change means something in that
    folder changed and none of its previously cached unit categories can
    still be trusted. all_from_cache is True only if every unit under p was
    a cache hit, used by the route to report from_cache.

    A folder key with no signature entry in the shared index (empty
    string) is never trusted as a cache hit, even if a stored category
    happens to match "" -- this is the deliberate conservative gate for
    loose top-level audio files and AUDIOBOOKS_ROOT itself as a scan
    target, neither of which library_index.build_library_index ever
    assigns a real signature to (see its docstring). Treating an absent
    signature as "unchanged" would silently freeze those categories
    forever; treating it as "always recompute" costs nothing beyond an
    extra _categorise_book_unit call, which is cheap.
    """
    cache_key = folder_scan_cache_key(p, ignored_folders)
    with FOLDER_SCAN_CACHE_LOCK:
        cache = load_scan_cache_file(FOLDER_SCAN_CACHE)
        cached_scan = cache["scans"].get(cache_key, {})
    cached_folders = cached_scan.get("folders", {})  # {path_str: {"signature": str, "units": {ref_str: category}}}

    units = _filter_ignored_units(_scan_book_units(p), p, ignored_folders)

    def resolve(unit: tuple[Path, list[Path], Path]) -> tuple[str, str, str, bool]:
        ref, audio, book_dir = unit
        folder_key = str(book_dir if book_dir.is_dir() else book_dir.parent)
        unit_key = str(ref)
        current_signature = shared.signatures.get(folder_key, "")
        cached_folder = cached_folders.get(folder_key)
        if (
            cached_folder is not None
            and current_signature != ""
            and cached_folder.get("signature") == current_signature
        ):
            cached_units = cached_folder.get("units", {})
            if unit_key in cached_units:
                return folder_key, unit_key, cached_units[unit_key], True
        try:
            category = _categorise_book_unit(audio, book_dir, p)
        except PermissionError:
            category = "skip"
        return folder_key, unit_key, category, False

    resolved: list[tuple[str, str, str, bool]] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        for outcome in pool.map(resolve, units):
            resolved.append(outcome)

    # Re-fetch the shared state rather than reusing the `shared` snapshot the
    # caller passed in: ensure_library_index_fresh only kicks a background
    # walk and returns immediately, so that snapshot (taken before the units
    # above were even scanned) can still be the pre-walk state, with no
    # signature for a freshly-discovered folder. Writing that stale
    # snapshot back to the cache would permanently store signature "" for
    # every newly-seen folder, which the read-side conservative check above
    # then always treats as a miss -- so the fast path would never engage
    # even when nothing actually changes on the next call. By this point the
    # full folder walk and per-unit categorization above have run, giving
    # the much cheaper background folder-signature walk ample time to
    # finish, so this later read is the freshest available signature data
    # to persist. Mirrors the identical fix in discover_m4b_candidates.
    #
    # Deliberately NOT replaced with a direct, synchronous
    # folder_listing_signature() call at persist time (see #238): that reads
    # real disk state at a different moment than the async shared index's
    # own next walk will, and _categorise_book_unit's own scan-cache sidecar
    # write (_ensure_scan_sidecar) mutates the very folder being signed
    # during this same request -- a synchronous read here can capture that
    # sidecar while the shared index's background walk (started earlier in
    # this request, racing the sidecar write) captured the folder without
    # it. Persisting that "with sidecar" value while shared.signatures keeps
    # reporting "without sidecar" (until some future unrelated background
    # walk happens to run after the sidecar write) permanently desyncs the
    # persisted signature from what the read-side check compares against,
    # so from_cache never goes true again for that folder. Keeping both the
    # read side (shared.signatures, above) and the write side (fresh_shared,
    # here) sourced from the same get_state() avoids that: they can lag
    # real disk state by one background-walk cycle, but they lag it
    # together, so a cache hit is still reachable once that walk catches up.
    fresh_shared = library_index.get_state()

    # Start from the previous cache contents, but for every folder touched by
    # this scan, first decide whether its old "units" map is still trustworthy:
    # if the folder's signature has not changed since it was last written,
    # carry its old units forward as the base (siblings that were cache hits
    # this round are never even recomputed, so their only record lives here);
    # if the signature changed (or the folder is new), the old units map is
    # entirely stale and is replaced with an empty one. Only after this
    # per-folder reset do the per-unit results below get layered on top.
    updated_folders = {
        folder_key: {"signature": data.get("signature", ""), "units": dict(data.get("units", {}))}
        for folder_key, data in cached_folders.items()
    }
    touched_folder_keys = {folder_key for folder_key, _, _, _ in resolved}
    for folder_key in touched_folder_keys:
        fresh_signature = fresh_shared.signatures.get(folder_key, "")
        existing = updated_folders.get(folder_key)
        stale = existing is None or fresh_signature == "" or existing.get("signature") != fresh_signature
        if stale:
            updated_folders[folder_key] = {"signature": fresh_signature, "units": {}}
        else:
            existing["signature"] = fresh_signature

    for folder_key, unit_key, category, was_cached in resolved:
        if not was_cached:
            updated_folders[folder_key]["units"][unit_key] = category

    with FOLDER_SCAN_CACHE_LOCK:
        cache = load_scan_cache_file(FOLDER_SCAN_CACHE)
        cache["scans"][cache_key] = {"folders": updated_folders}
        save_scan_cache_file(FOLDER_SCAN_CACHE, cache)

    book_results = [
        (unit[0], unit[2], category) for unit, (_, _, category, _) in zip(units, resolved)
    ]
    all_from_cache = bool(resolved) and all(was_cached for _, _, _, was_cached in resolved)
    return book_results, all_from_cache


@app.post("/api/scan")
def scan_folder_route(req: ScanRequest) -> dict[str, Any]:
    p = Path(req.path)
    if not p.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {req.path}")
    t0 = time.monotonic()

    library_index.ensure_library_index_fresh(AUDIOBOOKS_ROOT)
    shared = library_index.get_state()
    book_results, from_cache = _categorized_book_units(p, req.ignored_folders, shared)

    needs_metadata = sum(1 for _, _, c in book_results if c == "needs_metadata")
    needs_conversion = sum(1 for _, _, c in book_results if c == "needs_conversion")
    ready_to_organize = sum(1 for _, _, c in book_results if c == "ready_to_organize")
    organized = sum(1 for _, _, c in book_results if c == "organized")
    total = needs_metadata + needs_conversion + ready_to_organize + organized

    return {
        "path": str(p),
        "total": total,
        "needs_metadata": needs_metadata,
        "needs_conversion": needs_conversion,
        "ready_to_organize": ready_to_organize,
        "organized": organized,
        "scan_ms": round((time.monotonic() - t0) * 1000),
        "from_cache": from_cache,
    }


def _book_author(folder: Path, scan_root: Path) -> str:
    try:
        rel = folder.relative_to(AUDIOBOOKS_ROOT)
        return rel.parts[0] if len(rel.parts) > 1 else ""
    except ValueError:
        try:
            rel = folder.relative_to(scan_root)
            return rel.parts[0] if len(rel.parts) > 1 else ""
        except ValueError:
            return ""


def _embedded_cover_bytes(audio_file: Path) -> tuple[bytes, str] | None:
    """Return (cover_bytes, media_type) from an audio file's own cover tag (covr/APIC).

    Reads the semantic cover tag via mutagen rather than picking an arbitrary
    embedded picture/video stream by position -- an M4B can carry several
    embedded images (per-chapter thumbnails, stray art), and only the first
    covr/APIC entry is the actual front cover.
    """
    try:
        suffix = audio_file.suffix.lower()
        if suffix in (".m4b", ".m4a", ".mp4"):
            tags = MP4(str(audio_file)).tags
            if tags and "covr" in tags and tags["covr"]:
                cover_item = tags["covr"][0]
                from mutagen.mp4 import MP4Cover  # noqa: PLC0415
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


def _book_cover_data(folder: Path) -> tuple[bytes, str] | None:
    """Return (cover_bytes, media_type) from a file cover or embedded audio tag."""
    for name in _COVER_NAMES:
        cover = folder / name
        if cover.is_file():
            media = "image/png" if cover.suffix.lower() == ".png" else "image/jpeg"
            return (cover.read_bytes(), media)
    # Find first audio file (prefer m4b > m4a > mp3 > mp4), one level deep
    candidates: list[Path] = []
    for ext in ("*.m4b", "*.m4a", "*.mp3", "*.mp4"):
        found = sorted(folder.glob(ext))
        if found:
            candidates = found
            break
    if not candidates:
        for sub in sorted(folder.iterdir()):
            if sub.is_dir():
                for ext in ("*.m4b", "*.m4a", "*.mp3", "*.mp4"):
                    found = sorted(sub.glob(ext))
                    if found:
                        candidates = found
                        break
                if candidates:
                    break
    for audio_file in candidates[:1]:
        result = _embedded_cover_bytes(audio_file)
        if result:
            return result
    return None


@app.post("/api/scan/books")
def scan_books_route(req: ScanRequest) -> dict[str, Any]:
    p = Path(req.path)
    if not p.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {req.path}")

    library_index.ensure_library_index_fresh(AUDIOBOOKS_ROOT)
    shared = library_index.get_state()
    book_results, _from_cache = _categorized_book_units(p, req.ignored_folders, shared)
    attention = [
        (folder, book_dir, category)
        for folder, book_dir, category in book_results
        if category in ("needs_metadata", "needs_conversion")
    ]

    def fast_entry(fc: tuple[Path, Path, str]) -> dict[str, Any]:
        folder, book_dir, category = fc
        return {
            "path": str(folder),
            "title": folder.stem if folder.is_file() else folder.name,
            "author": _book_author(folder, p),
            "has_cover": _has_cover_fast(book_dir),
            "category": category,
        }

    with ThreadPoolExecutor(max_workers=10) as pool:
        books = list(pool.map(fast_entry, attention))
    books.sort(key=lambda b: (b["category"], b["title"].lower()))
    return {"books": books, "total": len(books)}


@app.get("/api/book/cover")
def book_cover(path: str) -> Response:
    p = validate_audiobook_path(path)
    if p.is_file():
        # Loose audio file: extract embedded cover from the specific file
        try:
            data, media = extract_current_cover(p)
            return Response(content=data, media_type=media)
        except Exception:
            raise HTTPException(status_code=404, detail="No cover found")
    if not p.is_dir():
        raise HTTPException(status_code=404, detail="Not a directory")
    result = _book_cover_data(p)
    if result:
        data, media = result
        return Response(content=data, media_type=media)
    raise HTTPException(status_code=404, detail="No cover found")


# ---------------------------------------------------------------------------
# Sidecar cleanup: remove the JSON files the fixer/library writes alongside
# audio. "libraforge" mode removes all internal libraforge state; the optional
# metadata.json removal also clears the Audiobookshelf-facing metadata.json
# (folder-level and per-file companions), regardless of whether we wrote it or
# it shipped with the download. Audio files are never touched.
# ---------------------------------------------------------------------------

def _libraforge_state_suffixes(fixer_module: Any) -> tuple[set[str], set[str]]:
    """Return (exact_names, name_suffixes) identifying internal libraforge files.

    Sourced from the fixer's own constants so the cleanup never drifts from the
    names the fixer actually writes.
    """
    suffixes = {
        getattr(fixer_module, "LIBRAFORGE_SUFFIX", ".libraforge.json"),
        getattr(fixer_module, "M4B_TOOL_METADATA_SUFFIX", ".m4b-tool-metadata.json"),
        getattr(fixer_module, "CHAPTER_COUNT_CACHE_SUFFIX", ".chapter-count-cache.json"),
        getattr(fixer_module, "METADATA_BACKUP_SUFFIX", ".metadata-backup.json"),
        getattr(fixer_module, "MARKER_SUFFIX", ".audible-metadata-fixer.json"),
    }
    return {"libraforge.json"}, suffixes


def _classify_sidecar(path: Path, state_names: set[str], state_suffixes: set[str]) -> str | None:
    """Return "libraforge", "metadata_json", or None for a given file."""
    name = path.name
    if name in state_names or any(name.endswith(suffix) for suffix in state_suffixes):
        return "libraforge"
    # metadata.json must be checked after the libraforge suffixes so that e.g.
    # ".metadata-backup.json" is classified as libraforge, not metadata.json.
    if name == "metadata.json" or name.endswith(".metadata.json"):
        return "metadata_json"
    return None


def collect_cleanup_targets(
    root: Path, include_metadata_json: bool, fixer_module: Any
) -> dict[str, list[Path]]:
    """Find sidecar files under `root` grouped by category."""
    state_names, state_suffixes = _libraforge_state_suffixes(fixer_module)
    found: dict[str, list[Path]] = {"libraforge": [], "metadata_json": []}
    walk_root = root if root.is_dir() else root.parent
    for path in walk_root.rglob("*.json"):
        if not path.is_file():
            continue
        category = _classify_sidecar(path, state_names, state_suffixes)
        if category == "libraforge":
            found["libraforge"].append(path)
        elif category == "metadata_json" and include_metadata_json:
            found["metadata_json"].append(path)
    return found


class SidecarCleanupRequest(BaseModel):
    path: str
    include_metadata_json: bool = False
    dry_run: bool = True


@app.post("/api/cleanup/sidecars")
def cleanup_sidecars(req: SidecarCleanupRequest) -> dict[str, Any]:
    target = assert_under_audiobooks(validate_existing_path(req.path))
    fixer_module = load_fixer_module(default_fixer_script())
    found = collect_cleanup_targets(target, req.include_metadata_json, fixer_module)

    libraforge_files = found["libraforge"]
    metadata_files = found["metadata_json"]
    all_files = libraforge_files + metadata_files
    total_bytes = sum(f.stat().st_size for f in all_files if f.exists())

    deleted = 0
    errors: list[str] = []
    if not req.dry_run:
        for path in all_files:
            try:
                path.unlink()
                deleted += 1
            except OSError as exc:
                errors.append(f"{path}: {exc}")

    return {
        "path": str(target),
        "dry_run": req.dry_run,
        "include_metadata_json": req.include_metadata_json,
        "counts": {
            "libraforge": len(libraforge_files),
            "metadata_json": len(metadata_files),
            "total": len(all_files),
        },
        "total_bytes": total_bytes,
        "deleted": deleted,
        "errors": errors,
        "sample": [str(p) for p in all_files[:10]],
    }


# ---------------------------------------------------------------------------
# abs-agg metadata provider
# ---------------------------------------------------------------------------

def require_http_base_url(url: str, *, field_name: str = "URL", allow_blank: bool = False) -> str:
    import urllib.parse

    value = (url or "").strip().rstrip("/")
    if not value:
        if allow_blank:
            return ""
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be an http or https URL")
    return value


class AbsAggSettingsRequest(BaseModel):
    url: str


class AbsAggSearchRequest(BaseModel):
    query: str
    author: str = ""
    provider: str = "librivox"
    provider_params: str = ""
    limit: int = 10
    base_url: str = ""


@app.get("/api/abs-agg/providers")
def abs_agg_providers() -> dict[str, Any]:
    base_url = require_http_base_url(
        _load_abs_agg_config().get("url", "http://abs-agg:3000"),
        field_name="abs-agg URL",
    )
    providers: dict[str, str] = {}
    reachable = False
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/providers",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        providers = {
            p["id"]: p["name"]
            for p in data.get("providers", [])
            if p.get("available", True)
        }
        reachable = True
    except Exception:
        providers = _ABS_AGG_PROVIDERS_FALLBACK

    return {
        "providers": providers,
        "required_params": ABS_AGG_REQUIRED_PARAMS,
        "reachable": reachable,
        "url": base_url,
    }


@app.get("/api/abs-agg/settings")
def get_abs_agg_settings() -> dict[str, Any]:
    return _load_abs_agg_config()


@app.put("/api/abs-agg/settings")
def save_abs_agg_settings(req: AbsAggSettingsRequest) -> dict[str, Any]:
    config = {"url": require_http_base_url(req.url, field_name="abs-agg URL")}
    _save_abs_agg_config(config)
    return config


class AbsTractSettingsRequest(BaseModel):
    url: str = ""
    kindle_region: str = "us"


@app.get("/api/abs-tract/settings")
def get_abs_tract_settings() -> dict[str, Any]:
    return _load_abs_tract_config()


@app.put("/api/abs-tract/settings")
def save_abs_tract_settings(req: AbsTractSettingsRequest) -> dict[str, Any]:
    config = {
        "url": require_http_base_url(req.url, field_name="abs-tract URL", allow_blank=True),
        "kindle_region": (req.kindle_region or "us").strip(),
    }
    _save_abs_tract_config(config)
    return config


@app.post("/api/abs-agg/search")
def abs_agg_search(req: AbsAggSearchRequest) -> dict[str, Any]:
    base_url = req.base_url.strip() or _load_abs_agg_config().get("url", "")
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="abs-agg URL not configured. Enter it in the search panel.",
        )
    base_url = require_http_base_url(base_url, field_name="abs-agg URL")
    return search_abs_agg_candidates(
        query=req.query,
        author=req.author,
        base_url=base_url,
        provider=req.provider,
        provider_params=req.provider_params,
        limit=req.limit,
    )


class AbsTractSearchRequest(BaseModel):
    query: str
    author: str = ""
    provider: str = "goodreads"  # "goodreads" | "kindle"
    limit: int = 10


@app.post("/api/abs-tract/search")
def abs_tract_search_endpoint(req: AbsTractSearchRequest) -> dict[str, Any]:
    cfg = _load_abs_tract_config()
    base_url = (cfg.get("url") or "").strip()
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="abs-tract URL not configured. Set it in Settings → Goodreads/Kindle fallback.",
        )
    base_url = require_http_base_url(base_url, field_name="abs-tract URL")
    provider = req.provider if req.provider in {"goodreads", "kindle"} else "goodreads"
    return search_abs_tract_candidates(
        query=req.query,
        author=req.author,
        base_url=base_url,
        provider=provider,
        kindle_region=(cfg.get("kindle_region") or "us").strip() or "us",
        limit=req.limit,
    )


# ---------------------------------------------------------------------------
# Enrichment Forge
# ---------------------------------------------------------------------------


class EnrichmentSeriesRow(BaseModel):
    name: str
    book_count: int


class EnrichmentSeriesResponse(BaseModel):
    series: list[EnrichmentSeriesRow]


# Cached full-catalog item list: (monotonic_ts, items). The series-search box
# debounces at 250ms and calls /api/enrichment/series on every keystroke, and
# selecting a result immediately calls /api/enrichment/compile for the same
# catalog -- without this, each of those re-runs fetch_all_abs_book_items's
# full paginated ABS walk from scratch. TTL is short enough that a real
# library change shows up within one search session, long enough to cover a
# multi-keystroke search plus the compile call that follows it.
_ENRICHMENT_ITEMS_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_ENRICHMENT_ITEMS_CACHE_TTL = 30
_ENRICHMENT_ITEMS_LOCK = threading.Lock()


def _fetch_all_abs_book_items_cached() -> list[dict[str, Any]]:
    global _ENRICHMENT_ITEMS_CACHE
    now = time.monotonic()
    with _ENRICHMENT_ITEMS_LOCK:
        if _ENRICHMENT_ITEMS_CACHE is not None:
            ts, items = _ENRICHMENT_ITEMS_CACHE
            if now - ts < _ENRICHMENT_ITEMS_CACHE_TTL:
                return items
    items = fetch_all_abs_book_items(_abs_request)
    with _ENRICHMENT_ITEMS_LOCK:
        _ENRICHMENT_ITEMS_CACHE = (now, items)
    return items


def _reset_enrichment_items_cache_for_tests() -> None:
    """Test-only helper: clear the cached full-catalog item list so each test
    exercises its own _abs_request mock instead of reusing a prior test's
    cached result. Not used by production code paths."""
    global _ENRICHMENT_ITEMS_CACHE
    with _ENRICHMENT_ITEMS_LOCK:
        _ENRICHMENT_ITEMS_CACHE = None


@app.get("/api/enrichment/series")
def enrichment_series(q: str = "") -> EnrichmentSeriesResponse:
    if not _get_abs_api_key():
        raise HTTPException(status_code=400, detail="Audiobookshelf is not configured. Set it up in Settings first.")
    review_module = load_review_module()
    items = _fetch_all_abs_book_items_cached()
    groups = group_items_by_series(items, review_module.normalize_series)
    summary = list_series_summary(groups, q)
    return EnrichmentSeriesResponse(series=[EnrichmentSeriesRow(**row) for row in summary])


class EnrichmentCompileRequest(BaseModel):
    series_name: str
    auth_file: str = "/auth/audible-metadata.json"


class EnrichmentBookRow(BaseModel):
    id: str
    path: str
    is_file: bool
    title: str
    audible_genres: list[str]
    goodreads_genres: list[str]
    flagged_explicit: bool
    existing_genres: list[str]
    existing_narrator: str
    existing_explicit: bool


class EnrichmentSourceStatus(BaseModel):
    label: str
    state: str
    detail: str = ""
    searched: int = 0


class EnrichmentCompileResponse(BaseModel):
    books: list[EnrichmentBookRow]
    genre: list[str]
    narrator: str
    sequence_range: str
    explicit_flagged_count: int
    explicit_total_count: int
    explicit_evidence_note: str
    source_status: dict[str, EnrichmentSourceStatus] = Field(default_factory=dict)


@app.post("/api/enrichment/compile")
def enrichment_compile(req: EnrichmentCompileRequest) -> EnrichmentCompileResponse:
    if not _get_abs_api_key():
        raise HTTPException(status_code=400, detail="Audiobookshelf is not configured. Set it up in Settings first.")

    review_module = load_review_module()
    items = _fetch_all_abs_book_items_cached()
    groups = group_items_by_series(items, review_module.normalize_series)
    books = get_series_books(groups, req.series_name, review_module.normalize_series)
    if not books:
        raise HTTPException(status_code=404, detail=f"Series not found: {req.series_name}")

    source_status: dict[str, dict[str, Any]] = {}
    audible_results: dict[str, dict | None] = {}
    abs_results: dict[str, dict | None] = {}

    # Phase 1: Direct Audible when an auth file exists; otherwise fall back to
    # Audiobookshelf's provider search so Enrichment Forge can still compile.
    auth_path = Path(req.auth_file)
    if auth_path.exists():
        try:
            auth = audible.Authenticator.from_file(req.auth_file)
            client = audible.Client(auth=auth)
            # Reuse the real fixer search/lookup functions (including the ASIN
            # keyword-search fallback in audible_lookup_by_asin), just bound to
            # the enrichment-only expanded response groups instead of duplicating them.
            audible_search_fn = functools.partial(fixer_audible_search, response_groups=ENRICHMENT_RESPONSE_GROUPS)
            audible_lookup_by_asin_fn = functools.partial(audible_lookup_by_asin, response_groups=ENRICHMENT_RESPONSE_GROUPS)
            audible_results = search_series_audible(books, audible_search_fn, audible_lookup_by_asin_fn, client)
            source_status["audible"] = {
                "label": "Audible",
                "state": "searched",
                "searched": len(books),
            }
        except Exception as exc:
            abs_results = search_series_abs(books, search_abs_candidates, provider="audible")
            source_status["audible"] = {
                "label": "Audible",
                "state": "searched",
                "detail": f"Used ABS's Audible provider because direct auth failed: {exc}",
                "searched": len(books),
            }
    else:
        abs_results = search_series_abs(books, search_abs_candidates, provider="audible")
        source_status["audible"] = {
            "label": "Audible",
            "state": "searched",
            "detail": "Used ABS's Audible provider because no direct Audible auth file is configured.",
            "searched": len(books),
        }

    # Phase 2: Goodreads, 5 workers, starts only after phase 1 is fully done
    # (never interleaved with Audible calls, see app/enrichment.py's
    # search_series_goodreads docstring).
    abs_tract_config = _load_abs_tract_config()
    abs_tract_url = (abs_tract_config.get("url") or "").strip()
    if abs_tract_url:
        goodreads_results = search_series_goodreads(books, abs_tract_search, abs_tract_url)
        source_status["goodreads"] = {
            "label": "Goodreads",
            "state": "searched",
            "searched": len(books),
        }
    else:
        goodreads_results = {}
        source_status["goodreads"] = {
            "label": "Goodreads",
            "state": "skipped",
            "detail": "abs-tract is not connected, so Goodreads was not used.",
            "searched": 0,
        }

    compiled = compile_series_enrichment(books, audible_results, goodreads_results, clean_provider_genres, abs_results)
    compiled["source_status"] = source_status
    return EnrichmentCompileResponse(**compiled)


class EnrichmentApplyBook(BaseModel):
    id: str
    path: str
    is_file: bool
    include: bool


class EnrichmentApplyRequest(BaseModel):
    books: list[EnrichmentApplyBook]
    genre: list[str] = []
    narrator: str = ""
    explicit: bool = False


class EnrichmentApplyResponse(BaseModel):
    applied: int
    failed: list[dict] = []


@app.post("/api/enrichment/apply")
def enrichment_apply(req: EnrichmentApplyRequest) -> EnrichmentApplyResponse:
    applied = 0
    failed: list[dict] = []
    for book in req.books:
        if not book.include:
            continue
        try:
            validated_path = validate_audiobook_path(book.path)
        except HTTPException as exc:
            failed.append({"id": book.id, "path": book.path, "error": str(exc.detail)})
            continue
        target = resolve_metadata_json_path(str(validated_path), book.is_file)
        try:
            assert_under_audiobooks(target)
            write_metadata_json_partial(target, req.genre, req.narrator, req.explicit)
            applied += 1
        except HTTPException as exc:
            failed.append({"id": book.id, "path": book.path, "error": str(exc.detail)})
        except Exception as exc:
            failed.append({"id": book.id, "path": book.path, "error": str(exc)})
    return EnrichmentApplyResponse(applied=applied, failed=failed)


# ---------------------------------------------------------------------------
# ABS (Audiobookshelf) metadata provider
# ---------------------------------------------------------------------------

ABS_CONFIG_FILE = APP_ROOT.parent / "config" / "abs.json"

# Env vars are the startup defaults; config file values override at request time.
_ABS_URL_DEFAULT = os.environ.get("ABS_URL", "http://audiobookshelf").rstrip("/")
_ABS_API_KEY_DEFAULT = os.environ.get("ABS_API_KEY", "")


def _load_abs_config() -> dict[str, Any]:
    try:
        if ABS_CONFIG_FILE.exists():
            return json.loads(ABS_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_abs_config(config: dict[str, Any]) -> None:
    ABS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ABS_CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _get_abs_url() -> str:
    return require_http_base_url(
        _load_abs_config().get("url") or _ABS_URL_DEFAULT,
        field_name="Audiobookshelf URL",
    )


def _get_abs_api_key() -> str:
    return _load_abs_config().get("api_key") or _ABS_API_KEY_DEFAULT


def _abs_request(path: str, params: dict[str, str]) -> Any:
    import urllib.error as _urlerror
    import urllib.parse as _urlparse

    abs_url = _get_abs_url()
    abs_api_key = _get_abs_api_key()

    if not abs_api_key:
        raise HTTPException(status_code=503, detail="ABS API key not configured. Visit /auth-setup to add it.")
    qs = _urlparse.urlencode(params)
    url = f"{abs_url}{path}?{qs}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {abs_api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except _urlerror.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ABS error {exc.code}: {exc.reason}") from exc
    except _urlerror.URLError as exc:
        raise HTTPException(status_code=502, detail=f"ABS unreachable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ABS search failed: {exc}") from exc


def search_abs_candidates(*, title: str, author: str = "", provider: str = "audible", limit: int = 10) -> dict[str, Any]:
    params: dict[str, str] = {"title": title, "provider": provider}
    if author:
        params["author"] = author
    raw = _abs_request("/api/search/books", params)
    matches = raw if isinstance(raw, list) else []

    results: list[dict[str, Any]] = []
    for i, match in enumerate(matches[:limit]):
        series_raw = match.get("series") or []
        if isinstance(series_raw, list):
            series_name = series_raw[0].get("series", "") if series_raw else ""
            sequence = str(series_raw[0].get("sequence", "") or "") if series_raw else ""
        elif isinstance(series_raw, str):
            series_name = series_raw
            sequence = ""
        else:
            series_name = ""
            sequence = ""

        title_val = match.get("title", "") or ""
        subtitle = match.get("subtitle", "") or ""
        author_val = match.get("author", "") or ""
        narrator = match.get("narrator", "") or ""
        year = str(match.get("publishedYear", "") or "")
        cover_url = match.get("cover", "") or ""
        summary = match.get("description", "") or ""
        asin = match.get("asin", "") or f"abs-{provider}-{i}"
        isbn = match.get("isbn", "") or ""
        duration_minutes_raw = match.get("duration")
        duration_minutes = round(float(duration_minutes_raw), 2) if duration_minutes_raw else None
        region = match.get("region", "") or ""

        genre = _pick_genre(match.get("genres") or [])

        full_meta = {
            "title": title_val, "subtitle": subtitle, "author": author_val,
            "narrator": narrator, "series": series_name, "sequence": sequence,
            "year": year, "cover_url": cover_url, "asin": asin, "summary": summary,
            "genre": genre,
        }
        series_only_meta = {
            "title": "", "subtitle": "", "author": "", "narrator": "",
            "series": series_name, "sequence": sequence,
            "year": "", "cover_url": "", "asin": asin, "summary": "",
            "genre": genre,
        }
        allowed_modes = ["full"] + (["series_only"] if series_name else [])

        results.append({
            "asin": asin,
            "isbn": isbn,
            "query": title,
            "score": None,
            "edit_mode": "full",
            "recommended_edit_mode": "full",
            "allowed_edit_modes": allowed_modes,
            "title": title_val,
            "subtitle": subtitle,
            "authors": [author_val] if author_val else [],
            "narrators": [narrator] if narrator else [],
            "series": series_name,
            "sequence": sequence,
            "duration_minutes": duration_minutes,
            "year": year,
            "cover_url": cover_url,
            "summary": summary,
            "chosen_metadata": full_meta,
            "chosen_metadata_by_mode": {"full": full_meta, "series_only": series_only_meta},
            "duration": {},
            "provider": "abs",
            "abs_provider": provider,
            "abs_region": region,
        })

    return {"queries": [title], "results": results}


def search_ebook_candidates(*, title: str, author: str = "", limit: int = 5) -> dict[str, Any] | None:
    """Open-Library-primary, Goodreads-backfill metadata lookup for an ebook.

    Open Library is used first. A missing result, or a top result with a
    blank cover_url/summary, is backfilled from Goodreads via abs-tract --
    live-testing (see docs/superpowers/specs/2026-07-18-ebook-support-design.md)
    showed Goodreads fills exactly those two fields far more consistently
    than Open Library does. Only descriptive fields are backfilled: title/
    author identity always stays whatever Open Library reported when it
    reported anything at all. Returns None if both sources come back empty.
    """
    try:
        primary = search_abs_candidates(title=title, author=author, provider="openlibrary", limit=limit)
    except HTTPException:
        primary = {"results": []}
    top = primary["results"][0] if primary["results"] else None

    needs_backfill = top is None or not top.get("cover_url") or not top.get("summary")
    if needs_backfill:
        abs_tract_config = _load_abs_tract_config()
        if abs_tract_config.get("url"):
            try:
                fallback = search_abs_tract_candidates(
                    query=title,
                    author=author,
                    base_url=abs_tract_config["url"],
                    provider="goodreads",
                    kindle_region=abs_tract_config.get("kindle_region", "us"),
                    limit=limit,
                )
                fallback_results = fallback["results"]
            except HTTPException:
                fallback_results = []
            fb_top = fallback_results[0] if fallback_results else None
            if fb_top:
                if top is None:
                    top = fb_top
                else:
                    for field_name in ("cover_url", "summary"):
                        if not top.get(field_name) and fb_top.get(field_name):
                            top[field_name] = fb_top[field_name]
    return top


def score_ebook_candidate(
    query_title: str, query_author: str, candidate_title: str, candidate_author: str,
) -> float:
    """Similarity score (0.0-1.0) between a search query and one candidate.

    Purpose-built for ebooks, not a reuse of app/fixer/scoring.py -- that
    module is tuned around duration/narrator/ASIN signals ebooks don't
    have. Title carries most of the weight; author only contributes when
    the query actually supplied one (an epub's embedded dc:creator can be
    blank even when dc:title is present).
    """
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    q_title, c_title = _norm(query_title), _norm(candidate_title)
    if not q_title or not c_title:
        return 0.0
    title_sim = difflib.SequenceMatcher(None, q_title, c_title).ratio()

    q_author, c_author = _norm(query_author), _norm(candidate_author)
    if not q_author:
        return round(title_sim, 4)

    author_sim = difflib.SequenceMatcher(None, q_author, c_author).ratio()
    return round(title_sim * 0.7 + author_sim * 0.3, 4)


EBOOK_MATCH_SCORE_FLOOR = 0.35


def scan_ebook_units_for_report(root: Path) -> list[dict[str, Any]]:
    """Score every discovered ebook unit against a fresh provider search.

    Companion to the audio Fixer's per-item report entries -- same shape
    (path/local/match/score/status/provider/used_query) plus media_type/
    formats, so it slots straight into state.report_items and renders
    through the existing Match Report card unmodified. Never writes
    anything; write_action is deliberately left unset since nothing here
    is auto-applied (see docs/superpowers/specs/
    2026-07-21-ebook-audiobook-parity-design.md).
    """
    fixer_module = load_fixer_module(default_fixer_script())
    items: list[dict[str, Any]] = []
    for unit in library_index.build_ebook_index(root):
        local = fixer_module.read_book_sidecar(unit.path) or {}
        epub_path = unit.formats.get("epub")
        embedded_title, embedded_author = (
            _extract_epub_metadata(epub_path) if epub_path else ("", "")
        )
        query = embedded_title or _ebook_query_from_stem(unit.path.stem)

        candidate = search_ebook_candidates(title=query, author=embedded_author) if query else None
        score = None
        match: dict[str, Any] | None = None
        provider = ""
        if candidate:
            authors = candidate.get("authors") or []
            candidate_author = authors[0] if authors else ""
            score = score_ebook_candidate(query, embedded_author, candidate.get("title", ""), candidate_author)
            if score >= EBOOK_MATCH_SCORE_FLOOR:
                match = {
                    "title": candidate.get("title", ""),
                    "subtitle": candidate.get("subtitle", ""),
                    "author": candidate_author,
                    "series": candidate.get("series", ""),
                    "sequence": candidate.get("sequence", ""),
                    "year": candidate.get("year", ""),
                    "genre": "",
                    "isbn": candidate.get("isbn", ""),
                    "cover_url": candidate.get("cover_url", ""),
                    "summary": candidate.get("summary", ""),
                }
                provider = "goodreads" if (candidate.get("cover_url") or candidate.get("summary")) else "openlibrary"

        items.append({
            "path": str(unit.path),
            "local": {
                "title": local.get("title", ""),
                "subtitle": local.get("subtitle", ""),
                "author": local.get("author", ""),
                "series": local.get("series", ""),
                "sequence": str(local.get("sequence", "") or ""),
                "year": local.get("year", ""),
                "genre": local.get("genre", ""),
                "isbn": local.get("isbn", ""),
                "summary": local.get("summary", ""),
            },
            "match": match,
            "score": score if match else None,
            "status": "matched" if match else "unmatched",
            "provider": provider,
            "used_query": query,
            "media_type": "ebook",
            "formats": sorted(unit.formats.keys()),
        })
    return items


def _extract_epub_metadata(path: Path) -> tuple[str, str]:
    """Read (title, author) from an epub's embedded OPF metadata.

    An epub is a zip archive; META-INF/container.xml points at the actual
    package (.opf) file, which carries the publisher's own Dublin Core
    <dc:title>/<dc:creator> fields -- not a guess derived from the
    filename. Verified live against real books whose filenames have no
    word separators at all (e.g. "efficientlinuxatthecommandline.epub"):
    the embedded title/author were correct in every case checked.

    Returns ("", "") on any failure (corrupt zip, missing container/opf,
    no dc:title) -- never raises, so a malformed epub just falls back to
    the filename-stem heuristic in the caller.
    """
    dc_ns = "{http://purl.org/dc/elements/1.1/}"
    try:
        with zipfile.ZipFile(path) as zf:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container.find(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            opf_path = rootfile.get("full-path") if rootfile is not None else None
            if not opf_path:
                return "", ""
            opf = ET.fromstring(zf.read(opf_path))
            title_el = opf.find(f".//{dc_ns}title")
            creator_el = opf.find(f".//{dc_ns}creator")
            title = (title_el.text or "").strip() if title_el is not None else ""
            author = (creator_el.text or "").strip() if creator_el is not None else ""
            return title, author
    except (KeyError, zipfile.BadZipFile, ET.ParseError, OSError):
        return "", ""


def _ebook_query_from_stem(stem: str) -> str:
    """Best-effort recovery of a searchable title from a filename stem.

    Filenames in ebook "format bucket" dumps are frequently
    underscore/hyphen-joined with no further word-splitting (e.g.
    "kubernetes_upandrunning"). Replacing separators with spaces is a
    cheap, always-safe improvement; fully space-free stems (e.g.
    "efficientlinuxatthecommandline") are a known, accepted gap -- both
    Open Library and Goodreads reliably return zero results for those
    (verified live), so search_ebook_candidates correctly returns None
    for them rather than guessing at a wrong match.
    """
    return re.sub(r"[_\-\.]+", " ", stem).strip()


class AbsSearchRequest(BaseModel):
    query: str
    author: str = ""
    provider: str = "audible"
    limit: int = 10


@app.get("/api/abs/providers")
def abs_providers() -> dict[str, Any]:
    try:
        data = _abs_request("/api/search/providers", {})
        return {"providers": {p["value"]: p["text"] for p in data.get("providers", {}).get("books", [])}}
    except HTTPException:
        # Return a minimal fallback so the UI stays functional if ABS is unreachable.
        return {"providers": {"audible": "Audible.com", "google": "Google Books", "itunes": "iTunes", "openlibrary": "Open Library"}}


@app.get("/api/abs/status")
def abs_status() -> dict[str, Any]:
    abs_url = _get_abs_url()
    abs_api_key = _get_abs_api_key()
    configured = bool(abs_api_key)
    reachable = False
    if configured:
        try:
            req = urllib.request.Request(
                f"{abs_url}/api/search/providers",
                headers={"Authorization": f"Bearer {abs_api_key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            reachable = True
        except Exception:
            pass
    return {"configured": configured, "reachable": reachable, "url": abs_url}


class AbsSaveConfigRequest(BaseModel):
    url: str = "http://audiobookshelf"
    api_key: str


@app.post("/api/abs/save-config")
def abs_save_config(req: AbsSaveConfigRequest) -> dict[str, Any]:
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="API key cannot be empty.")
    config = {
        "url": require_http_base_url(req.url, field_name="Audiobookshelf URL"),
        "api_key": req.api_key.strip(),
    }
    _save_abs_config(config)
    # Verify the key works before confirming success.
    try:
        probe = urllib.request.Request(
            f"{config['url']}/api/search/providers",
            headers={"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(probe, timeout=5) as resp:
            resp.read()
        reachable = True
    except Exception:
        reachable = False
    return {"ok": True, "reachable": reachable, "url": config["url"]}


@app.post("/api/abs/disconnect")
def abs_disconnect() -> dict[str, Any]:
    """Delete the stored ABS API key (keeps the URL for convenience)."""
    config = _load_abs_config()
    config.pop("api_key", None)
    _save_abs_config(config)
    # If ABS_API_KEY was set via environment, the UI cannot clear it.
    return {"ok": True, "env_key_present": bool(_ABS_API_KEY_DEFAULT)}


@app.post("/api/abs/search")
def abs_search(req: AbsSearchRequest) -> dict[str, Any]:
    return search_abs_candidates(
        title=req.query,
        author=req.author,
        provider=req.provider,
        limit=req.limit,
    )


# ---------------------------------------------------------------------------
# Auth setup
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
def settings_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "settings.html").read_text(encoding="utf-8"))


@app.get("/auth-setup")
def auth_setup_page() -> RedirectResponse:
    # Accounts moved into the consolidated Settings page.
    return RedirectResponse(url="/settings#accounts", status_code=302)


# ---------------------------------------------------------------------------
# Audible account management (multi-account switcher)
# ---------------------------------------------------------------------------

_ACCOUNTS_LOCK = threading.Lock()


def _read_auth_identity(path: Path) -> dict[str, Any] | None:
    """Identity fields from an Audible auth JSON, read offline (no network)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    cust = data.get("customer_info") or {}
    user_id = cust.get("user_id")
    if not user_id:
        return None
    return {
        "user_id": str(user_id),
        "name": cust.get("name") or cust.get("given_name") or "",
        "given_name": cust.get("given_name") or "",
        "locale_code": data.get("locale_code") or "us",
    }


def _account_auth_path(user_id: str) -> Path:
    return ACCOUNTS_DIR / f"{user_id}.json"


def _account_meta_path(user_id: str) -> Path:
    return ACCOUNTS_DIR / f"{user_id}.meta.json"


def _read_account_meta(user_id: str) -> dict[str, Any]:
    try:
        return json.loads(_account_meta_path(user_id).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_account_meta(user_id: str, flavor_name: str) -> None:
    meta = _read_account_meta(user_id)
    meta["flavor_name"] = flavor_name
    meta.setdefault("added_at", time.time())
    _account_meta_path(user_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _active_user_id() -> str | None:
    ident = _read_auth_identity(DEFAULT_AUTH_FILE) if DEFAULT_AUTH_FILE.exists() else None
    return ident["user_id"] if ident else None


def _sync_accounts() -> None:
    """Ensure the accounts folder exists and the active auth file is managed."""
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    ident = _read_auth_identity(DEFAULT_AUTH_FILE) if DEFAULT_AUTH_FILE.exists() else None
    if not ident:
        return
    uid = ident["user_id"]
    if not _account_auth_path(uid).exists():
        shutil.copy2(DEFAULT_AUTH_FILE, _account_auth_path(uid))
    if not _account_meta_path(uid).exists():
        _write_account_meta(uid, ident["name"] or "My account")


def _account_summary(user_id: str, active_id: str | None) -> dict[str, Any] | None:
    ident = _read_auth_identity(_account_auth_path(user_id))
    if not ident:
        return None
    loc = ident["locale_code"]
    return {
        "user_id": user_id,
        "flavor_name": _read_account_meta(user_id).get("flavor_name") or ident["name"] or user_id,
        "name": ident["name"],
        "marketplace": _LOCALE_NAMES.get(loc, loc.upper()),
        "locale_code": loc,
        "active": user_id == active_id,
    }


def _list_accounts() -> list[dict[str, Any]]:
    active = _active_user_id()
    out: list[dict[str, Any]] = []
    for p in sorted(ACCOUNTS_DIR.glob("*.json")):
        if p.name.endswith(".meta.json"):
            continue
        summ = _account_summary(p.stem, active)
        if summ:
            out.append(summ)
    out.sort(key=lambda a: (not a["active"], a["flavor_name"].lower()))
    return out


def _remove_account_files(user_id: str) -> None:
    _account_auth_path(user_id).unlink(missing_ok=True)
    _account_meta_path(user_id).unlink(missing_ok=True)


@app.get("/api/auth/status")
def auth_status() -> dict[str, Any]:
    exists = DEFAULT_AUTH_FILE.exists() and DEFAULT_AUTH_FILE.stat().st_size > 10
    name = ""
    activation_bytes_set = False
    if exists:
        with _ACCOUNTS_LOCK:
            _sync_accounts()
            uid = _active_user_id()
            if uid:
                name = _read_account_meta(uid).get("flavor_name") or ""
        try:
            activation_bytes_set = bool(json.loads(DEFAULT_AUTH_FILE.read_text()).get("activation_bytes"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "auth_ok": exists,
        "auth_file": str(DEFAULT_AUTH_FILE),
        "active_name": name,
        "activation_bytes_set": activation_bytes_set,
    }


@app.get("/api/auth/accounts")
def auth_accounts() -> dict[str, Any]:
    with _ACCOUNTS_LOCK:
        _sync_accounts()
        return {"accounts": _list_accounts()}


class AccountRenameRequest(BaseModel):
    flavor_name: str


@app.patch("/api/auth/accounts/{user_id}")
def auth_account_rename(user_id: str, req: AccountRenameRequest) -> dict[str, Any]:
    name = (req.flavor_name or "").strip()[:80]
    if not name:
        raise HTTPException(status_code=400, detail="Account name cannot be empty.")
    with _ACCOUNTS_LOCK:
        if not _account_auth_path(user_id).exists():
            raise HTTPException(status_code=404, detail="Account not found.")
        _write_account_meta(user_id, name)
        return _account_summary(user_id, _active_user_id()) or {}


@app.post("/api/auth/accounts/{user_id}/activate")
def auth_account_activate(user_id: str) -> dict[str, Any]:
    with _ACCOUNTS_LOCK:
        src = _account_auth_path(user_id)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Account not found.")
        DEFAULT_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, DEFAULT_AUTH_FILE)
        return {"ok": True, "active": _account_summary(user_id, user_id)}


def _deregister_or_502(path: Path) -> None:
    """Deregister the device with Audible; raise HTTP 502 with a flag on failure."""
    try:
        audible.Authenticator.from_file(str(path)).deregister_device()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"deregister_failed": True, "message": f"Could not deregister with Audible: {exc}"},
        ) from exc


class DisconnectRequest(BaseModel):
    force: bool = False


@app.post("/api/auth/disconnect")
def auth_disconnect(req: DisconnectRequest) -> dict[str, Any]:
    with _ACCOUNTS_LOCK:
        uid = _active_user_id()
        if not uid:
            raise HTTPException(status_code=400, detail="No active account to disconnect.")
        if not req.force:
            _deregister_or_502(DEFAULT_AUTH_FILE)
        _remove_account_files(uid)
        DEFAULT_AUTH_FILE.unlink(missing_ok=True)
        return {"ok": True}


@app.delete("/api/auth/accounts/{user_id}")
def auth_account_remove(user_id: str, force: bool = False) -> dict[str, Any]:
    with _ACCOUNTS_LOCK:
        path = _account_auth_path(user_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Account not found.")
        if user_id == _active_user_id():
            raise HTTPException(
                status_code=400, detail="That is the active account — use Disconnect instead."
            )
        if not force:
            _deregister_or_502(path)
        _remove_account_files(user_id)
        return {"ok": True}


@app.get("/api/auth/locales")
def auth_locales() -> dict[str, Any]:
    return {"locales": _LOCALE_NAMES}


class AuthLoginStartRequest(BaseModel):
    locale: str = "us"
    flavor_name: str = ""


@app.post("/api/auth/login/start")
def auth_login_start(req: AuthLoginStartRequest) -> dict[str, Any]:
    global _pending_login
    from audible.localization import Locale as _Locale  # noqa: PLC0415
    from audible.login import build_oauth_url, create_code_verifier  # noqa: PLC0415

    if req.locale not in _LOCALE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown locale: {req.locale}")

    flavor_name = (req.flavor_name or "").strip()[:80]
    if not flavor_name:
        raise HTTPException(status_code=400, detail="Enter a name for this account first.")

    try:
        locale_obj = _Locale(req.locale)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    code_verifier = create_code_verifier()
    oauth_url, serial = build_oauth_url(
        country_code=locale_obj.country_code,
        domain=locale_obj.domain,
        market_place_id=locale_obj.market_place_id,
        code_verifier=code_verifier,
    )

    with _pending_login_lock:
        _pending_login = {
            "code_verifier": code_verifier,
            "serial": serial,
            "domain": locale_obj.domain,
            "locale": req.locale,
            "flavor_name": flavor_name,
        }

    return {"oauth_url": oauth_url}


class AuthLoginCompleteRequest(BaseModel):
    redirect_url: str


@app.post("/api/auth/login/complete")
def auth_login_complete(req: AuthLoginCompleteRequest) -> dict[str, Any]:
    global _pending_login
    import urllib.parse as _urlparse  # noqa: PLC0415
    from audible.localization import Locale as _Locale  # noqa: PLC0415
    from audible.register import register as _register  # noqa: PLC0415

    with _pending_login_lock:
        pending = dict(_pending_login) if _pending_login else None

    if not pending:
        raise HTTPException(
            status_code=400,
            detail="No pending login session. Click 'Generate login URL' first.",
        )

    # Parse the authorization code out of the redirect URL.
    try:
        parsed = _urlparse.urlparse(req.redirect_url)
        params = _urlparse.parse_qs(parsed.query)
        code_list = params.get("openid.oa2.authorization_code")
        if not code_list:
            raise ValueError("openid.oa2.authorization_code not found in URL")
        authorization_code = code_list[0]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse redirect URL: {exc}") from exc

    # Exchange code + verifier for device credentials.
    try:
        reg_result = _register(
            authorization_code=authorization_code,
            code_verifier=pending["code_verifier"],
            domain=pending["domain"],
            serial=pending["serial"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Audible registration failed: {exc}") from exc

    # Persist as a managed account (unencrypted JSON), keyed by Audible user_id, then
    # make it the active account. Saving to the side folder never clobbers the active
    # auth file mid-login.
    try:
        auth = audible.Authenticator()
        auth.locale = _Locale(pending["locale"])
        auth._update_attrs(**reg_result)
        with _ACCOUNTS_LOCK:
            ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
            # Write to a temp file first so we can read the user_id back, then rename.
            tmp = ACCOUNTS_DIR / f".pending-{int(time.time() * 1000)}.json"
            auth.to_file(str(tmp), encryption=False)
            ident = _read_auth_identity(tmp)
            if not ident:
                tmp.unlink(missing_ok=True)
                raise RuntimeError("Audible did not return a usable account profile.")
            uid = ident["user_id"]
            tmp.replace(_account_auth_path(uid))
            _write_account_meta(uid, pending["flavor_name"] or ident["name"] or "My account")
            DEFAULT_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_account_auth_path(uid), DEFAULT_AUTH_FILE)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to save auth file: {exc}") from exc

    with _pending_login_lock:
        _pending_login = None

    return {"ok": True, "user_id": uid, "flavor_name": pending["flavor_name"], "name": ident["name"]}


# ---------------------------------------------------------------------------
# Audible Library Downloader
# ---------------------------------------------------------------------------

_LIBRARY_RESPONSE_GROUPS = ",".join(
    [
        "product_desc",
        "product_attrs",
        "contributors",
        "media",
        "series",
        "relationships",
    ]
)

# Cached owned-ASIN scans keyed by resolved root path: (monotonic_ts, fingerprint, set[str]).
_OWNED_ASIN_CACHE: dict[str, tuple[float, str, set[str]]] = {}
_OWNED_ASIN_CACHE_TTL = 1800  # 30 minutes
_OWNED_ASIN_LOCK = threading.Lock()
_FILENAME_ASIN_RE = re.compile(r"\[(?:ASIN\.)?([Bb]0[A-Z0-9]{8})\]", re.IGNORECASE)
# Audible's CloudFront CDN 403s the default python-httpx User-Agent; a client-like
# UA is required to fetch the content stream.
_AUDIBLE_DOWNLOAD_UA = "Audible/671 CFNetwork/1240.0.4 Darwin/20.6.0"


class LibraryListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class LibraryDownloadItem(BaseModel):
    asin: str
    title: str = ""
    author: str = ""
    # "new" (not owned), "replace" (overwrite existing target folder), "keep_both" (suffix folder)
    dup_action: str = "new"


class LibraryDownloadRequest(BaseModel):
    auth_file: str = Field(default="/auth/audible-metadata.json")
    target_path: str
    items: list[LibraryDownloadItem]
    quality: str = "High"
    organize: bool = False
    destination_root: str = Field(default="/audiobooks")


def _read_asin_from_audio(audio_file: Path) -> str:
    """Return the embedded ASIN for an audio file, or '' if none."""
    try:
        suffix = audio_file.suffix.lower()
        if suffix in (".m4b", ".m4a", ".mp4"):
            tags = MP4(str(audio_file)).tags
            if tags:
                for key in _ASIN_TAG_KEYS:
                    raw = tags.get(key, [])
                    if raw:
                        val = raw[0]
                        text = (
                            bytes(val).decode("utf-8", errors="ignore")
                            if isinstance(val, (bytes, bytearray, MP4FreeForm))
                            else str(val)
                        )
                        if text.strip():
                            return text.strip().upper()
        elif suffix == ".mp3":
            from mutagen.id3 import ID3  # noqa: PLC0415

            t = ID3(str(audio_file))
            for k in t.keys():
                if "asin" in k.lower():
                    frame = t.get(k)
                    text = "".join(getattr(frame, "text", []) or []) if frame else ""
                    if text.strip():
                        return text.strip().upper()
    except Exception:
        pass
    return ""


def _asin_string_from_libraforge_json(path: Path) -> str:
    """Return the real ASIN recorded in a libraforge.json sidecar, or ''.

    Reads the same fields as _asin_from_libraforge_json but returns the value so
    the owned-ASIN scan can avoid opening (and mutagen-parsing) the media file.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    for candidate in (
        (data.get("scan_cache") or {}).get("asin"),
        ((data.get("marker") or {}).get("audible") or {}).get("asin"),
        (data.get("audible") or {}).get("asin"),
    ):
        asin = str(candidate or "").strip()
        if asin and asin != _NOREALASIN:
            return asin.upper()
    return ""


def _owned_asins_for_folder(folder: Path) -> set[str]:
    """Resolve a book folder's ASIN(s) using the cheapest source available.

    Order: [B0XXXXXXXX] filename token, then a libraforge.json sidecar, and only
    as a last resort the embedded media tag (which opens the file -- slow over a
    network mount). Most organized books resolve without ever opening media.
    """
    try:
        audio = _book_audio_files(folder)
    except OSError:
        # Folder vanished or is unreadable mid-scan (libraries change while a
        # scan runs). Skip it rather than failing the whole scan.
        return set()
    if not audio:
        return set()

    # 1) Filename token -- no file open.
    owned = {m.group(1).upper() for f in audio if (m := _FILENAME_ASIN_RE.search(f.name))}
    if owned:
        return owned

    # 2) libraforge.json sidecar -- small JSON read, no media parse.
    first = audio[0]
    for sidecar in (first.parent / (first.name + ".libraforge.json"), folder / "libraforge.json"):
        if sidecar.is_file():
            asin = _asin_string_from_libraforge_json(sidecar)
            if asin:
                return {asin}

    # 3) Embedded tag -- opens the media file.
    asin = _read_asin_from_audio(first)
    return {asin} if asin else set()


def _owned_asins_under_subtree(start: Path) -> tuple[set[str], list[tuple[Path, str]], list[Path]]:
    """Single-pass walk of one subtree.

    Collects [B0XXXXXXXX] filename ASINs directly (no second directory listing)
    and records the dirs that still need a fallback read: those with a
    libraforge.json sidecar, or those with audio but no cheap ASIN (media open).
    """
    owned: set[str] = set()
    sidecar_dirs: list[tuple[Path, str]] = []
    media_files: list[Path] = []
    try:
        for dirpath, dirnames, filenames in os.walk(str(start)):
            dirnames[:] = [d for d in dirnames if not any(d.startswith(s) for s in _FS_SKIP_PREFIXES)]
            dir_found = False
            sidecar_name: str | None = None
            first_audio: Path | None = None
            for f in filenames:
                hit = _FILENAME_ASIN_RE.search(f)
                if hit:
                    owned.add(hit.group(1).upper())
                    dir_found = True
                elif sidecar_name is None and (f == "libraforge.json" or f.endswith(".libraforge.json")):
                    sidecar_name = f
                if first_audio is None and is_audio_file(Path(dirpath) / f):
                    first_audio = Path(dirpath) / f
            if dir_found or first_audio is None:
                continue  # ASIN already found here, or no audio -> nothing to resolve
            if sidecar_name:
                sidecar_dirs.append((Path(dirpath), sidecar_name))
            else:
                media_files.append(first_audio)
    except OSError:
        pass
    return owned, sidecar_dirs, media_files


def _scan_owned_asins(root: Path) -> set[str]:
    """Collect every ASIN already present under root (tags + [B0XXXXXXXX] filenames).

    The cost on a network mount is the directory enumeration, so the walk is
    fanned out across top-level entries (overlapping CIFS round trips) and done
    in a single pass. Cheap sources win: filename token, then libraforge.json
    sidecar; the media file is opened only as a last resort.
    """
    try:
        top = [c for c in root.iterdir() if not any(c.name.startswith(s) for s in _FS_SKIP_PREFIXES)]
    except OSError:
        return set()

    owned: set[str] = set()
    # Loose audio files directly under root carry their ASIN in the filename.
    for c in top:
        if c.is_file() and (hit := _FILENAME_ASIN_RE.search(c.name)):
            owned.add(hit.group(1).upper())

    subtrees = [c for c in top if c.is_dir()]
    sidecar_dirs: list[tuple[Path, str]] = []
    media_files: list[Path] = []
    if subtrees:
        with ThreadPoolExecutor(max_workers=16) as pool:
            for sub_owned, sub_sidecars, sub_media in pool.map(_owned_asins_under_subtree, subtrees):
                owned |= sub_owned
                sidecar_dirs.extend(sub_sidecars)
                media_files.extend(sub_media)

    # Fallback 1: read sidecars (cheap JSON, parallel) for dirs lacking a filename ASIN.
    if sidecar_dirs:
        with ThreadPoolExecutor(max_workers=16) as pool:
            for asin in pool.map(lambda item: _asin_string_from_libraforge_json(item[0] / item[1]), sidecar_dirs):
                if asin:
                    owned.add(asin)

    # Fallback 2: open the media file (slow) only for the residual dirs.
    if media_files:
        with ThreadPoolExecutor(max_workers=16) as pool:
            for asin in pool.map(_read_asin_from_audio, media_files):
                if asin:
                    owned.add(asin)

    return owned


def _abs_owned_asins() -> set[str] | None:
    """Owned ASINs from Audiobookshelf's indexed library.

    Returns the set of ASINs ABS already knows about (a few paginated API
    calls, ~instant and authoritative), or None when ABS is not configured or
    unreachable so the caller can fall back to the local index/scan.
    """
    if not _get_abs_api_key():
        return None
    try:
        items = fetch_all_abs_book_items(_abs_request)
        if not items:
            # fetch_all_abs_book_items can't distinguish "no libraries at
            # all" (fall back to the filesystem scan) from "libraries exist
            # but are genuinely empty" (trust ABS's authoritative answer of
            # zero owned ASINs) -- check libraries directly, only in this
            # empty-items case, to preserve that distinction.
            libs_raw = _abs_request("/api/libraries", {})
            libraries = libs_raw.get("libraries", []) if isinstance(libs_raw, dict) else (libs_raw or [])
            if not libraries:
                return None
        asins: set[str] = set()
        for item in items:
            asin = str(((item.get("media") or {}).get("metadata") or {}).get("asin") or "").strip()
            if asin:
                asins.add(asin.upper())
        return asins
    except Exception:
        return None


# Persistent owned-ASIN index so the (slow) filesystem fallback runs at most
# once per library state and survives container restarts. Keyed by root path.
_OWNED_INDEX_PATH = REPORTS_DIR / "owned-asin-index.json"


def _load_owned_index() -> dict[str, Any]:
    try:
        return json.loads(_OWNED_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _store_owned_asins(root: Path, asins: set[str], fingerprint: str) -> None:
    """Update the in-memory cache and the persistent index for a root."""
    with _OWNED_ASIN_LOCK:
        _OWNED_ASIN_CACHE[str(root)] = (time.monotonic(), fingerprint, asins)
    index = _load_owned_index()
    record = {"fingerprint": fingerprint, "asins": sorted(asins), "built_at": time.time()}
    if index.get(str(root), {}).get("fingerprint") == fingerprint and set(index.get(str(root), {}).get("asins", [])) == asins:
        return  # unchanged -- skip the disk write
    index[str(root)] = record
    try:
        _OWNED_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OWNED_INDEX_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_OWNED_INDEX_PATH)
    except Exception:
        pass


def _owned_asins_cached(root: Path) -> set[str]:
    """Owned ASINs for a root via the filesystem, with memory + disk caching.

    Used only as the fallback when Audiobookshelf is unavailable.
    """
    key = str(root)
    fingerprint = _library_fingerprint(root)
    with _OWNED_ASIN_LOCK:
        entry = _OWNED_ASIN_CACHE.get(key)
        if entry is not None:
            ts, cached_fp, data = entry
            if time.monotonic() - ts < _OWNED_ASIN_CACHE_TTL and cached_fp == fingerprint:
                return data
    # Persistent index survives restarts, so a matching fingerprint avoids the
    # expensive walk entirely (e.g. after a container restart or 30-min idle).
    record = _load_owned_index().get(key)
    if isinstance(record, dict) and record.get("fingerprint") == fingerprint and isinstance(record.get("asins"), list):
        data = {str(a).upper() for a in record["asins"]}
        with _OWNED_ASIN_LOCK:
            _OWNED_ASIN_CACHE[key] = (time.monotonic(), fingerprint, data)
        return data
    data = _scan_owned_asins(root)
    _store_owned_asins(root, data, fingerprint)
    return data


def _library_item_to_dict(item: dict[str, Any]) -> dict[str, Any]:
    authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
    narrators = [n.get("name", "") for n in (item.get("narrators") or []) if n.get("name")]
    series_list = item.get("series") or item.get("relationships") or []
    series_title = ""
    series_seq = ""
    for s in series_list:
        if s.get("relationship_type") in (None, "series") and s.get("title"):
            series_title = s.get("title", "")
            series_seq = str(s.get("sequence", "") or "")
            break
    images = item.get("product_images") or {}
    cover_url = ""
    for size in ("500", "1024", "300", "252", "180"):
        if images.get(size):
            cover_url = images[size]
            break
    runtime = item.get("runtime_length_min")
    return {
        "asin": item.get("asin", ""),
        "title": item.get("title", ""),
        "subtitle": item.get("subtitle", ""),
        "authors": authors,
        "narrators": narrators,
        "series_title": series_title,
        "series_sequence": series_seq,
        "runtime_minutes": runtime,
        "cover_url": cover_url,
        "purchase_date": item.get("purchase_date", ""),
        "release_date": item.get("release_date", ""),
        "is_finished": bool(item.get("is_finished", False)),
    }


@app.get("/api/library/list")
def library_list(
    auth_file: str = "/auth/audible-metadata.json", num_results: int = 1000
) -> LibraryListResponse:
    if not Path(auth_file).exists():
        raise HTTPException(status_code=400, detail="No Audible auth file. Complete auth setup first.")
    try:
        auth = audible.Authenticator.from_file(auth_file)
        client = audible.Client(auth=auth)
        resp = client.get(
            "library",
            params={
                "num_results": max(1, min(num_results, 1000)),
                "response_groups": _LIBRARY_RESPONSE_GROUPS,
                "sort_by": "-PurchaseDate",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Audible library fetch failed: {exc}") from exc
    raw_items = resp.get("items", []) or []
    items = [_library_item_to_dict(i) for i in raw_items if i.get("asin")]
    return LibraryListResponse(items=items, total=len(items))


@app.get("/api/library/owned-asins")
def library_owned_asins(root: str) -> dict[str, Any]:
    p = Path(root)
    if not p.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {root}")
    # Prefer Audiobookshelf's indexed library (authoritative, ~instant). It maps
    # to the same files as `root`, so its ASINs answer "already owned" directly.
    abs_asins = _abs_owned_asins()
    if abs_asins is not None:
        # Persist a snapshot so a later ABS outage falls back instantly instead
        # of re-walking the mount.
        try:
            _store_owned_asins(p, abs_asins, _library_fingerprint(p))
        except Exception:
            pass
        return {"root": str(p), "asins": sorted(abs_asins), "count": len(abs_asins), "source": "abs"}
    asins = sorted(_owned_asins_cached(p))
    return {"root": str(p), "asins": asins, "count": len(asins), "source": "filesystem"}


def _safe_component(text: str) -> str:
    """Filesystem-safe single path component."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text or "").strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:150] or "audiobook"


def _ffmpeg_decrypt(
    src: Path,
    out: Path,
    log,
    *,
    activation_bytes: str | None = None,
    key: str | None = None,
    iv: str | None = None,
) -> None:
    """Decrypt an Audible download to M4B.

    AAX (drm_type Adrm) decrypts with ``-activation_bytes``; AAXC (Mpeg) uses the
    per-file voucher ``-audible_key``/``-audible_iv``. Only the audio and cover
    streams are mapped — copying every stream pulls in a timed-text/data stream
    the mp4 muxer rejects. Chapters survive as container metadata regardless.
    """
    decrypt_args: list[str] = []
    if activation_bytes:
        decrypt_args = ["-activation_bytes", activation_bytes]
    elif key and iv:
        decrypt_args = ["-audible_key", key, "-audible_iv", iv]
    cmd = [
        "ffmpeg",
        "-y",
        *decrypt_args,
        "-i",
        str(src),
        "-map",
        "0:a",
        "-map",
        "0:v?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out),
    ]
    log(f"  ffmpeg decrypt -> {out.name}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-800:]
        raise RuntimeError(f"ffmpeg decryption failed: {tail}")


def _embed_asin_tag(m4b_path: Path, asin: str) -> None:
    try:
        mp4 = MP4(str(m4b_path))
        if mp4.tags is None:
            mp4.add_tags()
        mp4.tags[_ASIN_TAG_KEYS[0]] = [MP4FreeForm(asin.encode("utf-8"))]
        mp4.save()
    except Exception:
        pass


# Matches audible-cli's own default concurrency (`audible download --jobs 3`).
# See docs/design/download-voucher-first-decryption.md for why this is safe
# with respect to the CloudFront activation-bytes block and the license-grant
# threshold: both are still detected and cached exactly once per run, guarded
# by run_download_worker's bookkeeping_lock, regardless of how many workers
# are in flight.
LIBRARY_DOWNLOAD_CONCURRENCY = 3


def run_download_worker(run_id: str, req: LibraryDownloadRequest) -> None:
    state = runs[run_id]
    state.status = "running"
    state.log_path = REPORTS_DIR / f"{run_id}.log.txt"
    log_lines: list[str] = []
    # Reentrant: log() is called from within other bookkeeping_lock-held
    # blocks below, and a plain Lock would deadlock a thread against itself.
    bookkeeping_lock = threading.RLock()

    def log(msg: str) -> None:
        with bookkeeping_lock:
            log_lines.append(msg)
            state.lines_tail = log_lines[-40:]
            try:
                state.log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")  # type: ignore[union-attr]
            except Exception:
                pass

    target = Path(req.target_path)
    completed: list[Path] = []
    failures: list[dict[str, str]] = []
    # Keyed by idx (not appended in completion order) so the final report can
    # list every item in its original selection order even though workers
    # finish out of order under concurrency.
    results_by_idx: dict[int, dict[str, Any]] = {}
    done_count = 0
    active_titles: dict[int, str] = {}

    def _update_progress_locked() -> None:
        detail = ", ".join(active_titles[k] for k in sorted(active_titles))
        state.current = done_count
        state.current_file = detail
        state.percent = round(done_count / total * 100, 1) if total else 0.0
        label = f"{done_count} of {total} done"
        if detail:
            label += f" -- downloading: {detail}"
        set_run_phase(state, "downloading", "Downloading", label)

    try:
        target.mkdir(parents=True, exist_ok=True)
        auth = audible.Authenticator.from_file(req.auth_file)
        client = audible.Client(auth=auth)
        from audible.aescipher import decrypt_voucher_from_licenserequest  # noqa: PLC0415

        activation_bytes_cache: str | None = None
        activation_bytes_error: Exception | None = None
        # Audible enforces a separate, account-wide cap on how many license
        # grants (licenserequest calls) can be issued in a period -- distinct
        # from the CloudFront activation-bytes block and from concurrency: a
        # fully serial run can still hit it on a large batch, and once hit it
        # applies to every remaining item, not just a transient one. Detected
        # by a 403 whose message mentions the account being "above threshold"
        # for the license grant count (a known audible-cli-reported error).
        # Cache it like activation_bytes_error so the rest of a large run
        # fails fast locally instead of making one wasted live call per
        # remaining book. See docs/design/download-voucher-first-decryption.md.
        license_threshold_error: Exception | None = None

        total = len(req.items)
        state.total = total
        set_run_phase(state, "downloading", "Downloading", f"0 of {total}")

        def process_item(idx: int, item: LibraryDownloadItem) -> None:
            nonlocal activation_bytes_cache, activation_bytes_error, license_threshold_error, done_count
            display_title = item.title or item.asin
            # Set as soon as it's known so both the success and failure
            # branches below can report it in the final per-item report,
            # even if the failure happens after the method was chosen (e.g.
            # ffmpeg decrypt itself fails partway through).
            method_used: str | None = None
            with bookkeeping_lock:
                active_titles[idx] = display_title
                _update_progress_locked()
            log(f"[{idx}/{total}] {display_title} ({item.asin})")
            try:
                with bookkeeping_lock:
                    threshold_hit = license_threshold_error
                if threshold_hit is not None:
                    log(f"  [{idx}/{total}] skipping: Audible license-grant threshold was hit earlier this run")
                    raise threshold_hit

                with bookkeeping_lock:
                    # Folder collision resolution touches the shared target
                    # directory, so concurrent workers must serialize it --
                    # otherwise two items racing on the same computed name
                    # (e.g. duplicate titles) could pick the same "(2)" suffix.
                    folder_name = _safe_component(
                        f"{item.author} - {item.title}".strip(" -") or item.title or item.asin
                    )
                    folder_name = f"{folder_name} [{item.asin}]"
                    book_dir = target / folder_name
                    if book_dir.exists():
                        if item.dup_action == "keep_both":
                            n = 2
                            while (target / f"{folder_name} ({n})").exists():
                                n += 1
                            book_dir = target / f"{folder_name} ({n})"
                        elif item.dup_action == "replace":
                            shutil.rmtree(book_dir, ignore_errors=True)
                    book_dir.mkdir(parents=True, exist_ok=True)

                try:
                    lr = client.post(
                        f"content/{item.asin}/licenserequest",
                        body={
                            "supported_drm_types": ["Mpeg", "Adrm"],
                            "quality": req.quality,
                            "consumption_type": "Download",
                            "response_groups": "last_position_heard,pdf_url,content_reference,chapter_info",
                        },
                    )
                except Exception as lr_exc:  # noqa: BLE001
                    if "threshold" in str(lr_exc).lower():
                        with bookkeeping_lock:
                            license_threshold_error = lr_exc
                        log("  Audible license-grant threshold hit -- stopping further license requests this run")
                    raise
                content_license = lr.get("content_license", {})
                content_url = (
                    content_license.get("content_metadata", {})
                    .get("content_url", {})
                    .get("offline_url")
                )
                if not content_url:
                    raise RuntimeError(
                        content_license.get("message")
                        or content_license.get("status_code")
                        or "No download URL returned (title may not be downloadable)."
                    )

                # AAX (Adrm) decrypts with account activation_bytes; AAXC (Mpeg) with a
                # per-file voucher. The declared drm_type is not a reliable signal for
                # which material is actually available, though: live-probed 2026-07-07,
                # titles Audible labels "Adrm" can still carry a usable per-book voucher
                # in the same licenserequest response (confirmed for 3/3 titles that were
                # previously stuck on the activation-bytes path). The voucher is derived
                # entirely locally from already-known device/customer credentials plus
                # this book's own encrypted voucher blob -- it never touches Audible's
                # CloudFront-fronted activation endpoint -- so it's always preferred over
                # activation_bytes when available, regardless of drm_type.
                #
                # Activation bytes are an account/device property, not a per-book one, and
                # live-fetching them hits that legacy activation endpoint. Fetching it once
                # per book (instead of once per run) fires that request repeatedly in quick
                # succession, which trips CloudFront's abuse protection and makes every
                # activation-bytes-dependent item in the batch fail. Fetch it once, reuse
                # for the rest of the run, and persist it to the auth file so future runs
                # skip the live fetch entirely. A failed fetch is cached too (not just a
                # successful one) so a persistent block fails every remaining item needing
                # it immediately instead of retrying the live call once per book, which
                # would keep hammering the endpoint. See
                # docs/design/download-voucher-first-decryption.md.
                drm_type = content_license.get("drm_type", "")
                base = _safe_component(item.title or item.asin)
                voucher_error: Exception | None = None
                try:
                    voucher = decrypt_voucher_from_licenserequest(auth, lr)
                    decrypt_kwargs = {"key": voucher["key"], "iv": voucher["iv"]}
                    enc_path = book_dir / f"{base}.aaxc"
                    method_used = "voucher"
                    log("  using per-book voucher (no account activation bytes needed)")
                except Exception as v_exc:  # noqa: BLE001
                    voucher_error = v_exc
                    log(f"  no per-book voucher available ({v_exc}); falling back to account activation bytes")

                if voucher_error is not None:
                    # Locked for the whole check-fetch-cache sequence (not just
                    # the flag check) so two workers that both discover they
                    # need activation_bytes at the same time don't both fire a
                    # live fetch -- the second one blocks on the lock and then
                    # sees the first one's cached result or error, exactly as
                    # the single-threaded version fetched it once per run.
                    with bookkeeping_lock:
                        if activation_bytes_cache is None and activation_bytes_error is None:
                            log("  fetching account activation bytes (first title needing it this run)...")
                            try:
                                activation_bytes_cache = auth.get_activation_bytes()
                                log("  activation bytes obtained")
                                try:
                                    auth.to_file()
                                except Exception:
                                    pass
                            except Exception as ab_exc:  # noqa: BLE001
                                activation_bytes_error = ab_exc
                        elif activation_bytes_error is not None:
                            log("  activation bytes already failed earlier this run; skipping live retry")
                        else:
                            log("  reusing activation bytes fetched earlier this run")
                        resolved_ab_value = activation_bytes_cache
                        resolved_ab_error = activation_bytes_error
                    if resolved_ab_error is not None:
                        raise resolved_ab_error
                    decrypt_kwargs = {"activation_bytes": resolved_ab_value}
                    enc_path = book_dir / f"{base}.aax"
                    method_used = "activation_bytes"

                log(f"  downloading encrypted stream (declared drm_type={drm_type or 'unknown'}, decrypting via {method_used})...")
                with client.raw_request(  # type: ignore[union-attr]
                    "GET",
                    content_url,
                    stream=True,
                    headers={"User-Agent": _AUDIBLE_DOWNLOAD_UA},
                ) as resp:
                    with open(enc_path, "wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                            fh.write(chunk)

                out_m4b = book_dir / f"{base}.m4b"
                _ffmpeg_decrypt(enc_path, out_m4b, log, **decrypt_kwargs)
                enc_path.unlink(missing_ok=True)
                _embed_asin_tag(out_m4b, item.asin)
                # No sidecar cover.jpg: Audible embeds full-quality cover art in the M4B.

                with bookkeeping_lock:
                    completed.append(book_dir)
                    results_by_idx[idx] = {
                        "asin": item.asin,
                        "title": display_title,
                        "status": "success",
                        "method": method_used,
                        "path": str(out_m4b),
                    }
                log(f"  done -> {out_m4b}")
            except Exception as exc:  # noqa: BLE001
                with bookkeeping_lock:
                    failures.append({"asin": item.asin, "title": item.title, "error": str(exc)})
                    results_by_idx[idx] = {
                        "asin": item.asin,
                        "title": display_title,
                        "status": "failed",
                        "method": method_used,
                        "error": str(exc),
                    }
                log(f"  FAILED: {exc}")
            finally:
                with bookkeeping_lock:
                    done_count += 1
                    active_titles.pop(idx, None)
                    _update_progress_locked()

        workers = min(LIBRARY_DOWNLOAD_CONCURRENCY, total) or 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(process_item, idx, item) for idx, item in enumerate(req.items, 1)]
            for fut in as_completed(futures):
                fut.result()  # process_item catches its own item-level errors; this only re-raises bugs

        state.stats["downloaded"] = len(completed)
        state.stats["failed"] = len(failures)
        state.stats["failures"] = failures
        # Ordered by original selection order (not completion order, which is
        # nondeterministic under concurrency) so the end-of-run report reads
        # the same way the user picked the items. Unbounded, unlike
        # state.lines_tail's 40-line cap, so a 100-item run's full report
        # doesn't get truncated the way the raw log tail would be.
        results = [results_by_idx[i] for i in sorted(results_by_idx)]
        state.stats["results"] = results

        log("")
        log(f"=== Summary: {len(completed)} downloaded, {len(failures)} failed ===")
        for r in results:
            if r["status"] == "success":
                log(f"  OK    {r['title']} ({r['asin']}) -- via {r['method']}")
            else:
                via = f" [attempted via {r['method']}]" if r.get("method") else ""
                log(f"  FAIL  {r['title']} ({r['asin']}) -- {r['error']}{via}")

        if req.organize and completed:
            set_run_phase(state, "organizing", "Organizing", "Dry-run preview")
            log("Organizing downloaded books (dry-run preview)...")
            org_req = OrganizerRunRequest(
                root_path=str(target),
                destination_root=req.destination_root,
                apply=False,
            )
            preview = subprocess.run(
                build_organizer_command(org_req), capture_output=True, text=True
            )
            state.stats["organize_preview"] = (preview.stdout or "")[-4000:]
            log((preview.stdout or "")[-2000:])
            set_run_phase(state, "organizing", "Organizing", "Applying moves")
            log("Applying organize moves...")
            org_req.apply = True
            applied = subprocess.run(
                build_organizer_command(org_req), capture_output=True, text=True
            )
            state.stats["organize_apply"] = (applied.stdout or "")[-4000:]
            log((applied.stdout or "")[-2000:])
            # Owned-ASIN cache is now stale for both target and destination roots.
            with _OWNED_ASIN_LOCK:
                _OWNED_ASIN_CACHE.clear()

        state.status = "completed" if not failures else "completed_with_errors"
        set_run_phase(
            state,
            "done",
            "Done",
            f"{len(completed)} downloaded, {len(failures)} failed",
        )
        state.percent = 100.0
    except Exception as exc:  # noqa: BLE001
        state.status = "error"
        state.error = str(exc)
        set_run_phase(state, "error", "Error", str(exc))
        log(f"FATAL: {exc}")
    finally:
        state.finished_at = time.time()
        # Invalidate target-folder owned cache so a re-open reflects new books.
        with _OWNED_ASIN_LOCK:
            _OWNED_ASIN_CACHE.pop(str(target), None)
        try:
            write_final_report(state)
        except Exception:
            pass
        with runs_lock:
            runs.pop(run_id, None)


@app.post("/api/library/download/runs")
def start_library_download(req: LibraryDownloadRequest) -> dict[str, Any]:
    if not req.items:
        raise HTTPException(status_code=400, detail="No books selected.")
    if not Path(req.auth_file).exists():
        raise HTTPException(status_code=400, detail="No Audible auth file. Complete auth setup first.")
    run_id = datetime_id()
    state = RunState(id=run_id)
    with runs_lock:
        runs[run_id] = state
    thread = threading.Thread(target=run_download_worker, args=(run_id, req), daemon=True)
    thread.start()
    return {"id": run_id}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def start_here_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "start-here.html").read_text(encoding="utf-8"))


@app.get("/forge", response_class=HTMLResponse)
def forge_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/m4b-tool", response_class=HTMLResponse)
def m4b_tool_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "m4b-tool.html").read_text(encoding="utf-8"))


@app.get("/organizer", response_class=HTMLResponse)
def organizer_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "organizer.html").read_text(encoding="utf-8"))


@app.get("/library", response_class=HTMLResponse)
def library_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "downloader.html").read_text(encoding="utf-8"))


@app.get("/enrichment-forge", response_class=HTMLResponse)
def enrichment_forge_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "enrichment-forge.html").read_text(encoding="utf-8"))


@app.get("/api/scripts")
def list_scripts() -> dict[str, Any]:
    fixer_scripts, organizer_scripts = discover_scripts()
    return {
        "scripts": fixer_scripts + organizer_scripts,
        "fixer_scripts": fixer_scripts,
        "organizer_scripts": organizer_scripts,
        "scripts_dir": str(SCRIPTS_DIR),
        "default_script": fixer_scripts[-1] if fixer_scripts else "",
        "default_organizer_script": organizer_scripts[-1] if organizer_scripts else "",
    }


@app.get("/api/settings/retention")
def get_retention_settings() -> dict[str, Any]:
    return _load_retention_config()


@app.put("/api/settings/retention")
def save_retention_settings(req: dict[str, Any]) -> dict[str, Any]:
    cfg = {
        "max_age_days_enabled": bool(req.get("max_age_days_enabled")),
        "max_age_days": max(1, int(req.get("max_age_days") or 30)),
        "max_count_enabled": bool(req.get("max_count_enabled")),
        "max_count": max(1, int(req.get("max_count") or 20)),
    }
    _save_retention_config(cfg)
    return cfg


@app.post("/api/reports/prune")
def prune_reports_now() -> dict[str, Any]:
    deleted = _prune_reports()
    return {"deleted": deleted, "count": len(deleted)}


@app.get("/api/settings/title-noise")
def get_title_noise_policy() -> dict[str, Any]:
    return load_title_noise_policy()


@app.put("/api/settings/title-noise")
def update_title_noise_policy(req: TitleNoisePolicyUpdate) -> dict[str, Any]:
    try:
        return save_title_noise_policy(
            disabled_defaults=req.disabled_defaults,
            custom_patterns=[item.model_dump() for item in req.custom_patterns],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/settings/publishers")
def get_publisher_policy() -> dict[str, Any]:
    return load_publisher_policy()


@app.put("/api/settings/publishers")
def update_publisher_policy(req: PublisherPolicyUpdate) -> dict[str, Any]:
    try:
        return save_publisher_policy(
            disabled_defaults=req.disabled_defaults,
            custom_publishers=[item.model_dump() for item in req.custom_publishers],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/runs")
def start_run(req: RunRequest) -> dict[str, Any]:
    try:
        validate_audiobook_path(req.target_path)
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Bad path: {req.target_path!r} — must be an existing path under {AUDIOBOOKS_ROOT}")
    run_id = datetime_id()
    state = RunState(id=run_id)
    with runs_lock:
        runs[run_id] = state
    thread = threading.Thread(target=run_script_worker, args=(run_id, req), daemon=True)
    thread.start()
    return {"id": run_id}


@app.post("/api/m4b/metadata/load")
def load_m4b_metadata(req: M4BLoadRequest) -> dict[str, Any]:
    path = validate_audiobook_path(req.path)
    sidecars = discover_sidecars(path)
    selected = pick_sidecar(path, sidecars)

    payload: dict[str, Any] = {}
    form = M4BMetadataForm().model_dump()
    source_path = path
    if selected:
        payload = load_json(selected)
        form = sidecar_to_form(payload)
        sidecar_section = payload.get("sidecar") if "sidecar" in payload else payload
        root_file = str((sidecar_section.get("source", {}) or {}).get("root_file", "") or "")
        if root_file:
            source_path = Path(root_file)
    else:
        # No sidecar -- read the current embedded tags from the first audio file
        # so the M4B Tool form is pre-populated instead of blank.
        try:
            audio_files = source_audio_files(path)
            if audio_files:
                fixer_module = load_fixer_module(default_fixer_script())
                _, clues, _ = fixer_module.build_search_context(
                    audio_files[0], {}, use_backup_tags=False
                )
                raw_tags = clues.get("_raw_tags") or {}
                year_val = str(raw_tags.get("date", raw_tags.get("year", "")) or "").strip()
                year_val = year_val[:4] if len(year_val) >= 4 else year_val
                summary_val = (
                    raw_tags.get("comment")
                    or raw_tags.get("description")
                    or raw_tags.get("ldes")
                    or ""
                )
                form = normalize_m4b_metadata(M4BMetadataForm(
                    title=clues.get("title", "") or clues.get("raw_title", ""),
                    author=clues.get("author", ""),
                    narrator=clues.get("narrator", ""),
                    series=clues.get("series", ""),
                    sequence=str(clues.get("book_number", "") or ""),
                    year=year_val,
                    asin=str(raw_tags.get("asin", "") or ""),
                    summary=summary_val,
                    local_duration_minutes=clues.get("local_duration_minutes"),
                )).model_dump()
        except Exception:
            pass

    source_for_default = source_path if selected else path
    audio_summary = cached_audio_summary(path)
    if not audio_summary and selected:
        sidecar_section = payload.get("sidecar") if "sidecar" in payload else payload
        if isinstance(sidecar_section.get("audio_summary"), dict):
            audio_summary = sidecar_section["audio_summary"]
    if not audio_summary:
        audio_files = sidecar_audio_files(payload, source_for_default)
        audio_summary = summarize_audio_probes(
            audio_files,
            [probe_audio_file(audio_file) for audio_file in audio_files],
        )

    return {
        "path": str(path),
        "sidecars": [str(item) for item in sidecars],
        "selected_sidecar": str(selected) if selected else "",
        "source_path": str(source_path),
        "metadata": form,
        "audio_summary": audio_summary,
        "output_path": default_output_path(source_for_default, form),
        "raw": payload,
    }


@app.post("/api/m4b/discover")
def discover_m4b_sources(req: M4BDiscoverRequest) -> dict[str, Any]:
    return discover_m4b_candidates(
        path=req.path,
        mode=req.mode,
        script_name=req.script_name,
        limit=req.limit,
        cache_action=req.cache_action,
    )


@app.post("/api/m4b/discover/cache-status")
def m4b_discovery_cache_status_route(
    req: M4BDiscoveryCacheStatusRequest,
) -> dict[str, Any]:
    return m4b_discovery_cache_status(
        path=req.path,
        script_name=req.script_name,
    )


@app.post("/api/m4b/discover/refresh-audio-profiles")
def refresh_m4b_audio_profiles(
    req: M4BRefreshAudioProfilesRequest,
) -> dict[str, Any]:
    return refresh_cached_multipart_audio_profiles(
        path=req.path,
        script_name=req.script_name,
    )


@app.post("/api/m4b/metadata/save")
def save_m4b_metadata(req: M4BSaveRequest) -> dict[str, Any]:
    source_path = validate_audiobook_path(req.source_path or req.path)
    sidecar_path = save_sidecar_file(
        source_path=source_path,
        metadata=req.metadata,
        requested_sidecar_path=req.sidecar_path,
    )
    return {"sidecar_path": str(sidecar_path)}


@app.post("/api/m4b/search")
def audible_search(req: AudibleSearchRequest) -> dict[str, Any]:
    return search_audible_candidates(
        query=req.query,
        auth_file=req.auth_file,
        metadata=req.metadata.model_dump(),
        limit=req.limit,
        script_name=req.script_name,
    )


@app.get("/api/manual-review/browse")
def browse_manual_review(path: str = "/audiobooks") -> dict[str, Any]:
    return browse_manual_review_path(path)


class ManualReviewSearchIndexStatusResponse(BaseModel):
    status: str
    book_count: int
    error: str | None = None


@app.get("/api/manual-review/search-index/status")
def manual_review_search_index_status(
    ignored_folders: list[str] = Query(default=[]),
) -> ManualReviewSearchIndexStatusResponse:
    _ensure_manual_review_search_index_fresh(ignored_folders)
    state = _manual_review_search_index
    return ManualReviewSearchIndexStatusResponse(
        status=state.status, book_count=state.book_count, error=state.error,
    )


class ManualReviewSearchRequest(BaseModel):
    query: str = ""
    ignored_folders: list[str] = Field(default_factory=list)


class ManualReviewSearchResult(BaseModel):
    name: str
    path: str
    is_file: bool
    media_type: str = ""
    formats: list[str] = Field(default_factory=list)


class ManualReviewSearchResponse(BaseModel):
    results: list[ManualReviewSearchResult]
    index_status: str
    book_count: int


@app.post("/api/manual-review/search")
def manual_review_search(req: ManualReviewSearchRequest) -> ManualReviewSearchResponse:
    _ensure_manual_review_search_index_fresh(req.ignored_folders)
    state = _manual_review_search_index
    query = req.query.strip().lower()
    results = [
        ManualReviewSearchResult(
            name=Path(path).name,
            path=path,
            is_file=is_file,
            media_type="ebook" if path in state.ebook_formats else "",
            formats=state.ebook_formats.get(path, []),
        )
        for path, is_file in state.entries
        if not query or query in path.lower()
    ]
    return ManualReviewSearchResponse(
        results=results, index_status=state.status, book_count=state.book_count,
    )


@app.post("/api/manual-review/discover")
def discover_manual_review(req: ManualReviewDiscoverRequest) -> dict[str, Any]:
    return discover_manual_review_targets(path=req.path, script_name=req.script_name)


@app.post("/api/manual-review/load")
def load_manual_review_target(req: ManualReviewLoadRequest) -> dict[str, Any]:
    return inspect_manual_review_target(path=req.path, script_name=req.script_name, use_backup_tags=req.use_backup_tags)


@app.post("/api/manual-review/ebook/load")
def load_manual_review_ebook_target(req: ManualReviewEbookLoadRequest) -> dict[str, Any]:
    target_path = validate_audiobook_path(req.path)
    fixer_module = load_fixer_module(default_fixer_script())
    local = fixer_module.read_book_sidecar(target_path) or {}
    ebook_state = library_index.get_ebook_state()
    unit = next((u for u in ebook_state.units if u.path == target_path), None)
    formats = sorted(unit.formats.keys()) if unit else [target_path.suffix.lower().lstrip(".")]

    epub_path = (
        unit.formats.get("epub") if unit
        else target_path if target_path.suffix.lower() == ".epub"
        else None
    )
    embedded_title, embedded_author = _extract_epub_metadata(epub_path) if epub_path else ("", "")
    query = embedded_title or _ebook_query_from_stem(target_path.stem)

    candidate = search_ebook_candidates(title=query, author=embedded_author) if query else None
    score = None
    match: dict[str, Any] | None = None
    if candidate:
        authors = candidate.get("authors") or []
        candidate_author = authors[0] if authors else ""
        score = score_ebook_candidate(query, embedded_author, candidate.get("title", ""), candidate_author)
        if score >= EBOOK_MATCH_SCORE_FLOOR:
            match = {
                "title": candidate.get("title", ""),
                "subtitle": candidate.get("subtitle", ""),
                "author": candidate_author,
                "series": candidate.get("series", ""),
                "sequence": candidate.get("sequence", ""),
                "year": candidate.get("year", ""),
                "genre": "",
                "isbn": candidate.get("isbn", ""),
                "cover_url": candidate.get("cover_url", ""),
                "summary": candidate.get("summary", ""),
            }
        else:
            score = None

    return {
        "path": str(target_path),
        "local": {
            "title": local.get("title", ""),
            "subtitle": local.get("subtitle", ""),
            "author": local.get("author", ""),
            "series": local.get("series", ""),
            "sequence": str(local.get("sequence", "") or ""),
            "year": local.get("year", ""),
            "genre": local.get("genre", ""),
            "isbn": local.get("isbn", ""),
            "summary": local.get("summary", ""),
            "cover_url": local.get("cover_url", ""),
        },
        "match": match,
        "score": score,
        "formats": formats,
    }


@app.post("/api/manual-review/ebook/apply")
def apply_manual_review_ebook_target(req: ManualReviewEbookApplyRequest) -> dict[str, Any]:
    target_path = validate_audiobook_path(req.path)
    fixer_module = load_fixer_module(default_fixer_script())
    ebook_state = library_index.get_ebook_state()
    unit = next((u for u in ebook_state.units if u.path == target_path), None)
    if unit:
        source_formats = sorted(unit.formats.keys())
        source_files = {ext: str(p) for ext, p in unit.formats.items()}
    else:
        ext = target_path.suffix.lower().lstrip(".")
        source_formats = [ext]
        source_files = {ext: str(target_path)}

    book = {
        "title": req.book.get("title", ""),
        "subtitle": req.book.get("subtitle", ""),
        "author": req.book.get("author", ""),
        "narrator": "",
        "series": req.book.get("series", ""),
        "sequence": req.book.get("sequence", ""),
        "year": req.book.get("year", ""),
        "summary": req.book.get("summary", ""),
        "genre": req.book.get("genre", ""),
        "isbn": req.book.get("isbn", ""),
        "cover_url": req.book.get("cover_url", ""),
    }
    fixer_module.write_ebook_sidecar(
        target_path, source_formats=source_formats, source_files=source_files, book=book,
    )
    return {"path": str(target_path), "book": book}


@app.get("/api/manual-review/current-cover")
def current_manual_review_cover(
    path: str,
    script_name: str = "",
) -> Response:
    context = inspect_manual_review_target(path=path, script_name=script_name or default_fixer_script())
    cover_bytes, media_type = extract_current_cover(Path(context["source_path"]))
    return Response(
        content=cover_bytes,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )

@app.post("/api/manual-review/cover-upload")
async def upload_manual_review_cover(file: UploadFile = File(...)) -> dict[str, str]:
    data = await file.read(MAX_COVER_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_COVER_DOWNLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Uploaded cover image is too large")
    if data.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    else:
        raise HTTPException(status_code=400, detail="Uploaded file is not a JPEG or PNG image")

    COVER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = COVER_UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    return {"cover_url": dest.as_uri()}


@app.post("/api/manual-review/apply")
def apply_manual_review(req: ManualReviewApplyRequest) -> dict[str, Any]:
    return apply_manual_review_result(req)


@app.post("/api/manual-review/edit")
def edit_manual_review(req: ManualReviewEditRequest) -> dict[str, Any]:
    return edit_manual_review_book(req)


@app.post("/api/manual-review/apply-series-group")
def apply_series_group_endpoint(req: SeriesGroupApplyRequest) -> dict[str, Any]:
    return apply_series_group(req)


@app.post("/api/m4b/runs")
def start_m4b_run(req: M4BRunRequest) -> dict[str, Any]:
    run_id = datetime_id()
    state = RunState(id=run_id)
    with runs_lock:
        runs[run_id] = state
    thread = threading.Thread(target=run_m4b_worker, args=(run_id, req), daemon=True)
    thread.start()
    return {"id": run_id}


class OrganizerCleanupRequest(BaseModel):
    root_path: str


@app.post("/api/organizer/cleanup-source")
def organizer_cleanup_source(req: OrganizerCleanupRequest) -> dict[str, Any]:
    """Delete empty folders, Thumbs.db files, and chapter-count-cache JSON files
    from the organizer scan root after books have been moved out."""
    root = assert_under_audiobooks(validate_existing_path(req.root_path))

    # Chapter-count-cache JSON files left behind by the fixer.
    # Pattern: <folder>/<folder>.chapter-count-cache.json
    CACHE_SUFFIX = ".chapter-count-cache.json"
    json_deleted: list[dict[str, str]] = []
    for cache_file in sorted(root.rglob(f"*{CACHE_SUFFIX}")):
        rel = str(cache_file.parent.relative_to(root)) or "."
        try:
            cache_file.unlink()
            json_deleted.append({"name": cache_file.name, "folder": rel, "status": "deleted"})
        except OSError as exc:
            json_deleted.append({"name": cache_file.name, "folder": rel, "status": f"error: {exc}"})

    # Thumbs.db thumbnail cache files created by Windows Explorer.
    thumbs_results: list[dict[str, str]] = []
    for thumbs in sorted(p for p in root.rglob("*") if p.name.lower() == "thumbs.db"):
        rel = str(thumbs.parent.relative_to(root)) or "."
        try:
            thumbs.unlink()
            thumbs_results.append({"path": rel, "name": thumbs.name, "status": "deleted"})
        except OSError as exc:
            thumbs_results.append({"path": rel, "name": thumbs.name, "status": f"error: {exc}"})

    # Empty directories — walk deepest-first so parents become empty after children.
    empty_dirs_deleted = 0
    for dirpath in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if dirpath == root or not dirpath.is_dir():
            continue
        try:
            dirpath.rmdir()
            empty_dirs_deleted += 1
        except OSError:
            pass

    return {
        "root": str(root),
        "empty_dirs_deleted": empty_dirs_deleted,
        "json_files": json_deleted,
        "thumbs_db": thumbs_results,
    }


@app.post("/api/organizer/runs")
def start_organizer_run(req: OrganizerRunRequest) -> dict[str, Any]:
    run_id = datetime_id()
    state = RunState(id=run_id)
    with runs_lock:
        runs[run_id] = state
    thread = threading.Thread(target=run_organizer_worker, args=(run_id, req), daemon=True)
    thread.start()
    return {"id": run_id}


@app.post("/api/organizer/naming-template/validate")
def validate_organizer_naming_template(req: OrganizerNamingTemplateValidateRequest) -> dict[str, Any]:
    organizer = load_organizer_module(req.script_name)
    problems = organizer.validate_naming_template(req.template)
    return {"valid": not problems, "problems": problems}


@app.post("/api/organizer/naming-template/preview")
def preview_organizer_naming_template(req: OrganizerNamingTemplatePreviewRequest) -> dict[str, Any]:
    organizer = load_organizer_module(req.script_name)
    problems = organizer.validate_naming_template(req.template)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))
    root = validate_audiobook_path(req.root_path)
    destination_root = validate_audiobook_path(req.destination_root)
    previews = organizer.preview_naming_template_for_root(root, destination_root, req.template, limit=req.limit)
    return {"previews": previews}


def _example_books_manifest() -> dict[str, str]:
    manifest_path = EXAMPLE_BOOKS_DIR / "manifest.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@app.post("/api/organizer/naming-template/example-preview")
def preview_organizer_naming_template_examples(req: OrganizerNamingTemplateExamplePreviewRequest) -> dict[str, Any]:
    """Renders the same template against a small set of bundled, lightweight
    example books (metadata-only sidecars + tiny silent placeholder audio,
    not real user data) instead of the caller's own library -- a fixed,
    always-available set of scenarios (title==series, no series, distinct
    title, special edition, multi-file) that don't depend on what a given
    user's library happens to contain.
    """
    organizer = load_organizer_module(req.script_name)
    problems = organizer.validate_naming_template(req.template)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))
    manifest = _example_books_manifest()
    previews = organizer.preview_naming_template_for_root(
        EXAMPLE_BOOKS_DIR, AUDIOBOOKS_ROOT, req.template, limit=len(manifest) or 10
    )
    for preview in previews:
        source_parts = Path(preview["source"]).parts
        preview["scenario"] = next((manifest[key] for key in manifest if key in source_parts), "")
    return {"previews": previews}


@app.get("/api/runs/draining")
def get_draining() -> dict[str, Any]:
    """Return whether any cancelled run still has live worker threads finishing writes."""
    draining = any(
        s.status == "cancelled" and s.in_write_phase and s.process is not None and s.process.poll() is None
        for s in runs.values()
    )
    return {"draining": draining}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    state = runs.get(run_id)
    if not state:
        report_path = safe_child(REPORTS_DIR, f"{run_id}.report.json")
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            result = report_for_api(report)
            log_name = report.get("log_file")
            result["downloads"] = {
                "log": f"/api/runs/{run_id}/download/log" if log_name else None,
                "report": f"/api/runs/{run_id}/download/report",
            }
            return result
        raise HTTPException(status_code=404, detail="Run not found")

    workers_draining = (
        state.status == "cancelled"
        and state.in_write_phase
        and state.process is not None
        and state.process.poll() is None
    )
    return {
        "id": state.id,
        "status": state.status,
        "phase": state.phase,
        "phase_label": state.phase_label,
        "phase_detail": state.phase_detail,
        "started_at": state.started_at,
        "finished_at": state.finished_at,
        "returncode": state.returncode,
        "error": state.error,
        "command": state.command,
        "run_type": state.run_type,
        "current_file": state.current_file,
        "current": state.current,
        "total": state.total,
        "write_current": state.write_current,
        "percent": state.percent,
        "tail": state.lines_tail,
        "stats": state.stats,
        "files_by_category": state.files_by_category,
        "manual_review_items": derive_manual_review_items(state.stats, state.files_by_category),
        "workers_draining": workers_draining,
        "downloads": {
            "log": f"/api/runs/{run_id}/download/log" if state.log_path else None,
            "report": f"/api/runs/{run_id}/download/report" if state.report_path else None,
        },
    }


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    state = runs.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    if state.process and state.status == "running":
        try:
            os.killpg(os.getpgid(state.process.pid), signal.SIGTERM)
        except Exception:
            state.process.terminate()
        state.status = "cancelled"
        # Don't write the final report here — the worker thread does it after
        # the process exits cleanly (respecting any in-flight writes).
    return {"status": state.status}


@app.get("/api/runs/{run_id}/download/{kind}")
def download(run_id: str, kind: str) -> FileResponse:
    if kind not in {"log", "report"}:
        raise HTTPException(status_code=400, detail="Invalid download type")
    filename = f"{run_id}.log.txt" if kind == "log" else f"{run_id}.report.json"
    path = safe_child(REPORTS_DIR, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


@app.get("/api/reports/latest")
def get_latest_report() -> dict[str, Any]:
    report_files = sorted(REPORTS_DIR.glob("*.report.json"), reverse=True)
    for path in report_files:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # command[0] is always the interpreter ("python"/"python3") for every
        # script, fixer or organizer -- checking it here always matched, so
        # this never actually filtered out organizer reports. Check the
        # script path itself instead, using the same naming convention
        # is_fixer_script_name() uses elsewhere (startswith "audible-metadata-fixer").
        command = report.get("command") or []
        if any(Path(part).name.startswith("audible-metadata-fixer") for part in command):
            return report_for_api(report)
    raise HTTPException(status_code=404, detail="No fixer reports found")


def _suspect_review_path(report_id: str) -> Path:
    return safe_child(REPORTS_DIR, f"{report_id}.report.suspect-review.json")


@app.get("/api/reports/{report_id}/suspect-review")
def get_suspect_review(report_id: str) -> dict[str, Any]:
    # Every report load probes this to decide the button state, and "not
    # generated yet" is the common case, not an error -- 200 + exists:false
    # keeps that out of the browser console instead of logging a 404 on
    # every single page load.
    path = _suspect_review_path(report_id)
    if not path.exists():
        return {"exists": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/reports/{report_id}/suspect-review")
def generate_suspect_review(report_id: str) -> dict[str, Any]:
    report_path = safe_child(REPORTS_DIR, f"{report_id}.report.json")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Source report not found")
    review_script = safe_child(SCRIPTS_DIR, "review-libraforge-report.py")
    if not review_script.exists():
        raise HTTPException(status_code=500, detail="review-libraforge-report.py not found in scripts dir")
    out_path = _suspect_review_path(report_id)
    result = subprocess.run(
        [sys.executable, str(review_script), str(report_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr or result.stdout or "Script failed")
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))
