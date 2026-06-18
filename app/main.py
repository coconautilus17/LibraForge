import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import audible
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
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

APP_ROOT = Path(__file__).resolve().parent
STATIC_DIR = APP_ROOT / "static"
ICON_FILE = APP_ROOT / "libraforge.png"
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/app/scripts")).resolve()
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/app/reports")).resolve()
AUDIOBOOKS_ROOT = Path(os.environ.get("AUDIOBOOKS_ROOT", "/audiobooks")).resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

M4B_TOOL_SIDECAR_SUFFIX = ".m4b-tool-metadata.json"
M4B_DISCOVERY_CACHE = REPORTS_DIR / "m4b-discovery-cache.json"
M4B_DISCOVERY_CACHE_LOCK = threading.Lock()

DEFAULT_AUTH_FILE = Path("/auth/audible-metadata.json")
ABS_AGG_CONFIG_FILE = APP_ROOT.parent / "config" / "abs-agg.json"

# abs-agg provider catalog (key = URL slug, value = display label)
_ABS_AGG_PROVIDERS: dict[str, str] = {
    "librivox":         "LibriVox",
    "goodreads":        "Goodreads",
    "storytel":         "Storytel",
    "audioteka":        "Audioteka",
    "bookbeat":         "BookBeat",
    "bigfinish":        "Big Finish",
    "graphicaudio":     "Graphic Audio",
    "hardcover":        "Hardcover",
    "soundbooththeatre": "Soundbooth Theatre",
    "ard":              "ARD Audiothek",
    "diedrei":          "Die drei ???",
}


def _load_abs_agg_config() -> dict[str, Any]:
    try:
        if ABS_AGG_CONFIG_FILE.exists():
            return json.loads(ABS_AGG_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"url": "http://localhost:3000"}


def _save_abs_agg_config(config: dict[str, Any]) -> None:
    ABS_AGG_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ABS_AGG_CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def search_abs_agg_candidates(
    *,
    query: str,
    base_url: str,
    provider: str,
    provider_params: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    import urllib.error as _urlerror
    import urllib.parse as _urlparse

    if provider not in _ABS_AGG_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown abs-agg provider: {provider}")

    params_segment = f"/{provider_params.strip('/')}" if provider_params.strip("/") else ""
    qs = _urlparse.urlencode({"title": query, "limit": limit})
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
    for i, match in enumerate(data.get("matches", [])[:limit]):
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
        asin = match.get("asin", "") or f"abs-agg-{provider}-{i}"
        duration_seconds = match.get("duration") or 0
        duration_minutes = round(duration_seconds / 60, 2) if duration_seconds else None

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
            "summary": summary,
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
            "summary": "",
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
FOUND_RE = re.compile(r"^Found\s+(\d+)\s+supported files\.")
MODE_RE = re.compile(r"^\s+Mode:\s+([A-Za-z_]+)\s*$")
DURATION_STATUS_RE = re.compile(r"^\s+Status:\s+([A-Za-z_]+)\s*$")
DIFF_RE = re.compile(r"^\s+Diff:\s+([0-9.]+)%")
SUMMARY_RE = re.compile(r"^\s*(Matched|Skipped|Failed):\s+(\d+)\s*$")
SKIP_RE = re.compile(r"^\s+SKIP:\s+(.+)$")
ERROR_RE = re.compile(r"^\s+ERROR:\s+(.+)$")
ORGANIZER_SUMMARY_RE = re.compile(r"^(Found book items|Ignored MP3 files|Skipped likely existing book folders|Skipped unknown author|Skipped already in target folder|Skipped conflicts|Structure cache entries|Matched existing structure|Ambiguous structure matches|Skipped ambiguous structure|Planned moves):\s+(\d+)\s*$")
ORGANIZER_MODE_RE = re.compile(r"^Mode:\s+(APPLY|DRY RUN|INDEX ONLY)\s*$")
ORGANIZER_FIELD_RE = re.compile(r"^\s+(Kind|Title|Author|Files|Metadata Source|Review Reasons|Series|Number|Structure):\s+(.+)$")
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


def discover_scripts() -> tuple[list[str], list[str]]:
    scripts = sorted(
        path.name
        for path in SCRIPTS_DIR.iterdir()
        if path.is_file() and path.suffix == ".py"
    )
    organizer_scripts = [name for name in scripts if is_organizer_script(name)]
    fixer_scripts = [name for name in scripts if not is_organizer_script(name)]
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


def datetime_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value or "output"


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in {
        ".m4b",
        ".m4a",
        ".mp4",
        ".mp3",
        ".flac",
        ".ogg",
        ".opus",
        ".aac",
    }


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
    chapter_files = (payload.get("source", {}) or {}).get("chapter_files", []) or []
    files = [
        Path(file_path)
        for file_path in chapter_files
        if Path(file_path).is_file() and is_audio_file(Path(file_path))
    ]
    return files or source_audio_files(fallback)


def discover_sidecars(path: Path) -> list[Path]:
    folder = path if path.is_dir() else path.parent
    sidecars = sorted(folder.glob(f"*{M4B_TOOL_SIDECAR_SUFFIX}"))
    return [sidecar for sidecar in sidecars if sidecar.is_file()]


def pick_sidecar(path: Path, sidecars: list[Path]) -> Path | None:
    if path.is_file() and path.name.endswith(M4B_TOOL_SIDECAR_SUFFIX):
        return path

    folder = path if path.is_dir() else path.parent
    preferred = folder / f"{folder.name}{M4B_TOOL_SIDECAR_SUFFIX}"
    if preferred in sidecars:
        return preferred

    if path.is_file():
        per_file = path.with_name(f"{path.name}{M4B_TOOL_SIDECAR_SUFFIX}")
        if per_file in sidecars:
            return per_file

    return sidecars[0] if sidecars else None


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {path}: {exc}") from exc


def load_fixer_module(script_name: str = ""):
    script_path = live_script_path(script_name, "fixer")

    module_name = f"audible_fixer_{re.sub(r'[^a-zA-Z0-9_]', '_', script_name)}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail=f"Could not load fixer script: {script_name}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        queries.append(direct_query)
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
    aggressive: bool = False
    force: bool = False
    force_original: bool = False
    reprobe: bool = False
    show_asin_report: bool = False
    cover_if_missing: bool = False
    replace_cover: bool = False
    metadata_json: bool = False

    min_score: float | None = 0.70
    limit: int | None = 50
    max_files: int | None = 0
    duration_review_threshold: float | None = 10.0
    skip_patterns: list[str] = Field(default_factory=list)

    workers: int | None = None
    api_delay_ms: int = 0


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
    progress_every: int = 25


class TitleNoiseCustomPattern(BaseModel):
    id: str = ""
    label: str
    description: str = ""
    pattern: str
    enabled: bool = True


class TitleNoisePolicyUpdate(BaseModel):
    disabled_defaults: list[str] = Field(default_factory=list)
    custom_patterns: list[TitleNoiseCustomPattern] = Field(default_factory=list)


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
    current: int = 0
    total: int = 0
    percent: float = 0.0
    lines_tail: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    files_by_category: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    parser_state: dict[str, Any] = field(default_factory=dict)


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
        # working as designed — they don't belong in manual review.
        if reason.startswith("matched skip pattern:") or reason == "already processed":
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


def parse_line(state: RunState, line: str, threshold: float) -> None:
    detected_phase = fixer_phase_for_line(line, state.current_file)
    if detected_phase:
        set_run_phase(state, *detected_phase)

    m = FOUND_RE.match(line)
    if m:
        state.total = int(m.group(1))
        state.stats["found"] = int(m.group(1))
        set_run_phase(
            state,
            "preparing",
            "Preparing run",
            f"Found {state.total} processing items",
        )
        return

    m = PROCESSING_RE.match(line)
    if m:
        state.current = int(m.group(1))
        state.total = int(m.group(2))
        state.current_file = m.group(3).strip()
        state.percent = round((state.current / state.total) * 100, 2) if state.total else 0.0
        set_run_phase(
            state,
            "inspecting",
            "Inspecting metadata",
            f"Item {state.current} of {state.total}",
        )
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
        state.stats[m.group(1).lower()] = int(m.group(2))
        return

    m = MODE_RE.match(line)
    if m and state.current_file:
        mode = m.group(1)
        if mode in {"full", "series_only", "none"}:
            state.stats["mode_breakdown"].setdefault(mode, 0)
            state.stats["mode_breakdown"][mode] += 1
            add_category(state, "mode", mode, state.current_file)
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
        return

    m = ERROR_RE.match(line)
    if m and state.current_file:
        state.stats["error_count"] += 1
        add_category(state, "status", "error", state.current_file, m.group(1).strip())
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
                if not category.startswith("status:") and not item["title"]:
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
        "log_file": state.log_path.name if state.log_path else None,
    }
    state.report_path = REPORTS_DIR / f"{state.id}.report.json"
    state.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


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
    if req.aggressive:
        cmd.append("--aggressive")
    if req.force:
        cmd.append("--force")
    if req.force_original:
        cmd.append("--force-original")
    if req.reprobe:
        cmd.append("--reprobe")
    if req.show_asin_report:
        cmd.append("--show-asin-report")
    if req.cover_if_missing:
        cmd.append("--cover-if-missing")
    if req.replace_cover:
        cmd.append("--replace-cover")
    if req.metadata_json:
        cmd.append("--metadata-json")
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

    if _fixer_major_version(req.script_name) >= 5:
        if req.workers is not None and req.workers > 0:
            cmd += ["--workers", str(req.workers)]
        if req.api_delay_ms > 0:
            cmd += ["--api-delay-ms", str(req.api_delay_ms)]

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
        sidecar_path = validate_output_path(requested_sidecar_path)
    else:
        if source_path.is_dir():
            sidecar_path = source_path / f"{source_path.name}{M4B_TOOL_SIDECAR_SUFFIX}"
        else:
            sidecar_path = source_path.with_name(f"{source_path.name}{M4B_TOOL_SIDECAR_SUFFIX}")

    excluded = {path.resolve() for path in (excluded_paths or set())}
    existing: dict[str, Any] = {}
    if sidecar_path.is_file():
        try:
            existing = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    chapter_file_paths = [
        Path(value).resolve()
        for value in ((existing.get("source", {}) or {}).get("chapter_files", []) or [])
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
        payload["updated_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        payload["matching"] = existing.get("matching", payload["matching"])
        payload["local_before"] = existing.get(
            "local_before", payload["local_before"]
        )
        payload["audible"] = {
            **(existing.get("audible", {}) or {}),
            **payload["audible"],
        }
        existing_source = existing.get("source", {}) or {}
        payload["source"]["group_search"] = {
            **(existing_source.get("group_search", {}) or {}),
            **payload["source"]["group_search"],
            "files": payload["source"]["chapter_files"],
        }
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
    book = sidecar.get("book", {}) or {}
    audible_meta = sidecar.get("audible", {}) or {}
    local_before = sidecar.get("local_before", {}) or {}

    metadata = M4BMetadataForm(
        title=book.get("title", "")
        or audible_meta.get("title", "")
        or local_before.get("title", ""),
        subtitle=book.get("subtitle", ""),
        author=book.get("author", "") or local_before.get("author", ""),
        narrator=book.get("narrator", "") or local_before.get("narrator", ""),
        series=book.get("series", "") or local_before.get("series", ""),
        sequence=str(
            book.get("sequence", "") or audible_meta.get("sequence", "")
        ),
        year=str(book.get("year", "") or audible_meta.get("year", "")),
        summary=book.get("summary", ""),
        cover_url=book.get("cover_url", ""),
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


def fixer_processing_context(
    *,
    target_path: Path,
    fixer_module,
    chapter_count_reader=None,
) -> tuple[list[Path], dict[Path, list[Path]], list[Path]]:
    """Return source files, accepted multipart groups, and processing items."""
    if target_path.is_file():
        if not fixer_module.collect_audio_files(target_path):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported audiobook file: {target_path}",
            )
        sibling_files = [
            item
            for item in fixer_module.collect_audio_files(target_path.parent)
            if item.parent == target_path.parent
        ]
        sibling_group_map = fixer_module.build_multi_part_group_map(
            sibling_files,
            chapter_count_reader=chapter_count_reader,
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
        chapter_count_reader=chapter_count_reader,
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
    target_path = validate_existing_path(path)
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
    search_entry = {
        "path": str(target_path),
        "script_name": script_name,
        "script_mtime_ns": script_mtime_ns,
        "refreshed_at": refreshed_at,
        "audio_file_count": len(files),
        "chapter_probes": chapter_reader.pruned_entries(),
        "audio_probes": audio_reader.pruned_entries(),
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
        sidecar_path = folder / f"{folder.name}{fixer_module.M4B_TOOL_METADATA_SUFFIX}"

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


def inspect_manual_review_target(
    *,
    path: str,
    script_name: str = "",
) -> dict[str, Any]:
    script_name = script_name or default_fixer_script()
    target_path = validate_existing_path(path)
    fixer_module = load_fixer_module(script_name)
    sidecar_context = manual_review_sidecar_context(
        target_path=target_path,
        fixer_module=fixer_module,
    )
    files, group_map, processing_items = sidecar_context or fixer_processing_context(
        target_path=target_path,
        fixer_module=fixer_module,
    )
    if len(processing_items) != 1:
        raise HTTPException(
            status_code=400,
            detail="Path must point to a single book file or grouped book folder",
        )
    source_path = processing_items[0]
    # Use original pre-apply tags (format_tags from backup) so the manual
    # review form reflects what the file looked like before the fixer wrote to
    # it. Falls back to probing the live file when no backup exists.
    queries, clues, _ = fixer_module.build_search_context(
        source_path, group_map, use_backup_tags=True
    )
    display_path = fixer_module.get_processing_display_path(source_path, group_map)

    metadata = {
        "title": clues.get("title", "") or clues.get("raw_title", ""),
        "subtitle": "",
        "author": clues.get("author", ""),
        "narrator": clues.get("narrator", ""),
        "series": clues.get("series", ""),
        "sequence": clues.get("book_number", ""),
        "year": "",
        "summary": "",
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


def apply_manual_review_result(req: ManualReviewApplyRequest) -> dict[str, Any]:
    context = inspect_manual_review_target(path=req.path, script_name=req.script_name)
    fixer_module = load_fixer_module(req.script_name)
    source_path = Path(context["source_path"])
    file_type = source_path.suffix.lower().lstrip(".")
    metadata = build_manual_metadata_from_result(
        req.selected_result,
        file_type,
        req.edit_mode,
    )

    if not metadata.get("title") or not metadata.get("author"):
        raise HTTPException(status_code=400, detail="Selected result does not include enough metadata to apply")

    clues = build_context_clues(fixer_module, context["metadata"])
    if context.get("is_grouped"):
        clues["group_search"] = context.get("group_search", {})

    score = float(req.selected_result.get("score", 1.0) or 1.0)
    output_kind = "tags"
    output_path = str(source_path)

    if fixer_module.should_write_json_sidecar(source_path, clues):
        output_kind = "json_sidecar"
        sidecar_path = fixer_module.write_m4b_tool_metadata_sidecar(source_path, metadata, clues, score)
        output_path = str(sidecar_path)
    else:
        fixer_module.write_tags(
            source_path,
            metadata,
            backup=req.backup,
            writer=req.writer,
            cover_if_missing=req.cover_if_missing,
            replace_cover=req.replace_cover,
        )

    fixer_module.write_marker(
        source=source_path,
        metadata=metadata,
        clues=clues,
        score=score,
        mode=f"manual_{req.edit_mode}",
        aggressive=False,
        output_kind=output_kind,
    )

    return {
        "status": "applied",
        "target_path": context["display_path"],
        "source_path": context["source_path"],
        "output_kind": output_kind,
        "output_path": output_path,
        "edit_mode": req.edit_mode,
        "metadata_preview": metadata,
    }


def default_output_path(source_path: Path, metadata: dict[str, Any]) -> str:
    folder = source_path if source_path.is_dir() else source_path.parent
    title = sanitize_filename(metadata.get("title", "") or folder.name)
    return str((folder / f"{title}.m4b").resolve())


def build_m4b_command(
    req: M4BRunRequest,
    temp_dir: Path | None = None,
) -> tuple[list[str], list[Path]]:
    input_path = validate_existing_path(req.input_path)
    output_path = validate_output_path(req.output_path)
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
        with urllib.request.urlopen(metadata.cover_url, timeout=30) as response:
            cover_file.write_bytes(response.read())
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
        "skipped_already_target": 0,
        "skipped_conflicts": 0,
        "planned_moves": 0,
        "mode": "",
        "move_items": [],
    }


def finalize_organizer_move(state: RunState) -> None:
    current_move = state.parser_state.pop("organizer_current_move", None)
    if current_move:
        state.stats.setdefault("move_items", []).append(current_move)


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
            "Skipped already in target folder": "skipped_already_target",
            "Skipped conflicts": "skipped_conflicts",
            "Structure cache entries": "structure_cache_entries",
            "Matched existing structure": "matched_existing_structure",
            "Ambiguous structure matches": "ambiguous_structure_matches",
            "Skipped ambiguous structure": "skipped_ambiguous_structure",
            "Planned moves": "planned_moves",
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

    if line == "BOOK:":
        finalize_organizer_move(state)
        state.parser_state["organizer_current_move"] = {"companions": []}
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

    return cmd


def run_script_worker(run_id: str, req: RunRequest) -> None:
    with runs_lock:
        state = runs[run_id]

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
        input_path = validate_existing_path(req.input_path)
        output_path = validate_output_path(req.output_path)
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


app = FastAPI(title="LibraForge")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/app-icon.png")
def app_icon() -> FileResponse:
    return FileResponse(ICON_FILE, media_type="image/png")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "LibraForge"}


# ---------------------------------------------------------------------------
# abs-agg metadata provider
# ---------------------------------------------------------------------------

class AbsAggSettingsRequest(BaseModel):
    url: str


class AbsAggSearchRequest(BaseModel):
    query: str
    provider: str = "librivox"
    provider_params: str = ""
    limit: int = 10
    base_url: str = ""


@app.get("/api/abs-agg/providers")
def abs_agg_providers() -> dict[str, Any]:
    return {"providers": _ABS_AGG_PROVIDERS}


@app.get("/api/abs-agg/settings")
def get_abs_agg_settings() -> dict[str, Any]:
    return _load_abs_agg_config()


@app.put("/api/abs-agg/settings")
def save_abs_agg_settings(req: AbsAggSettingsRequest) -> dict[str, Any]:
    config = {"url": req.url}
    _save_abs_agg_config(config)
    return config


@app.post("/api/abs-agg/search")
def abs_agg_search(req: AbsAggSearchRequest) -> dict[str, Any]:
    base_url = req.base_url.strip() or _load_abs_agg_config().get("url", "")
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="abs-agg URL not configured. Enter it in the search panel.",
        )
    return search_abs_agg_candidates(
        query=req.query,
        base_url=base_url,
        provider=req.provider,
        provider_params=req.provider_params,
        limit=req.limit,
    )


# ---------------------------------------------------------------------------
# Auth setup
# ---------------------------------------------------------------------------

@app.get("/auth-setup", response_class=HTMLResponse)
def auth_setup_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "auth-setup.html").read_text(encoding="utf-8"))


@app.get("/api/auth/status")
def auth_status() -> dict[str, Any]:
    exists = DEFAULT_AUTH_FILE.exists() and DEFAULT_AUTH_FILE.stat().st_size > 10
    return {"auth_ok": exists, "auth_file": str(DEFAULT_AUTH_FILE)}


@app.get("/api/auth/locales")
def auth_locales() -> dict[str, Any]:
    return {"locales": _LOCALE_NAMES}


class AuthLoginStartRequest(BaseModel):
    locale: str = "us"
    auth_file: str = str(DEFAULT_AUTH_FILE)


@app.post("/api/auth/login/start")
def auth_login_start(req: AuthLoginStartRequest) -> dict[str, Any]:
    global _pending_login
    from audible.localization import Locale as _Locale  # noqa: PLC0415
    from audible.login import build_oauth_url, create_code_verifier  # noqa: PLC0415

    if req.locale not in _LOCALE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown locale: {req.locale}")

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
            "auth_file": req.auth_file,
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

    # Persist as an unencrypted JSON auth file.
    try:
        auth = audible.Authenticator()
        auth.locale = _Locale(pending["locale"])
        auth._update_attrs(**reg_result)
        auth_file = Path(pending["auth_file"])
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth.to_file(str(auth_file), encryption=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save auth file: {exc}") from exc

    with _pending_login_lock:
        _pending_login = None

    return {"ok": True, "auth_file": str(pending["auth_file"])}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/m4b-tool", response_class=HTMLResponse)
def m4b_tool_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "m4b-tool.html").read_text(encoding="utf-8"))


@app.get("/organizer", response_class=HTMLResponse)
def organizer_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "organizer.html").read_text(encoding="utf-8"))


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


@app.post("/api/runs")
def start_run(req: RunRequest) -> dict[str, Any]:
    run_id = datetime_id()
    state = RunState(id=run_id)
    with runs_lock:
        runs[run_id] = state
    thread = threading.Thread(target=run_script_worker, args=(run_id, req), daemon=True)
    thread.start()
    return {"id": run_id}


@app.post("/api/m4b/metadata/load")
def load_m4b_metadata(req: M4BLoadRequest) -> dict[str, Any]:
    path = validate_existing_path(req.path)
    sidecars = discover_sidecars(path)
    selected = pick_sidecar(path, sidecars)

    payload: dict[str, Any] = {}
    form = M4BMetadataForm().model_dump()
    source_path = path
    if selected:
        payload = load_json(selected)
        form = sidecar_to_form(payload)
        root_file = str((payload.get("source", {}) or {}).get("root_file", "") or "")
        if root_file:
            source_path = Path(root_file)

    source_for_default = source_path if selected else path
    audio_summary = cached_audio_summary(path)
    if not audio_summary and selected and isinstance(payload.get("audio_summary"), dict):
        audio_summary = payload["audio_summary"]
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
    source_path = validate_existing_path(req.source_path or req.path)
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


@app.post("/api/manual-review/discover")
def discover_manual_review(req: ManualReviewDiscoverRequest) -> dict[str, Any]:
    return discover_manual_review_targets(path=req.path, script_name=req.script_name)


@app.post("/api/manual-review/load")
def load_manual_review_target(req: ManualReviewLoadRequest) -> dict[str, Any]:
    return inspect_manual_review_target(path=req.path, script_name=req.script_name)


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


@app.post("/api/manual-review/apply")
def apply_manual_review(req: ManualReviewApplyRequest) -> dict[str, Any]:
    return apply_manual_review_result(req)


@app.post("/api/m4b/runs")
def start_m4b_run(req: M4BRunRequest) -> dict[str, Any]:
    run_id = datetime_id()
    state = RunState(id=run_id)
    with runs_lock:
        runs[run_id] = state
    thread = threading.Thread(target=run_m4b_worker, args=(run_id, req), daemon=True)
    thread.start()
    return {"id": run_id}


@app.post("/api/organizer/runs")
def start_organizer_run(req: OrganizerRunRequest) -> dict[str, Any]:
    run_id = datetime_id()
    state = RunState(id=run_id)
    with runs_lock:
        runs[run_id] = state
    thread = threading.Thread(target=run_organizer_worker, args=(run_id, req), daemon=True)
    thread.start()
    return {"id": run_id}


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
        "current_file": state.current_file,
        "current": state.current,
        "total": state.total,
        "percent": state.percent,
        "tail": state.lines_tail,
        "stats": state.stats,
        "files_by_category": state.files_by_category,
        "manual_review_items": derive_manual_review_items(state.stats, state.files_by_category),
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
        state.finished_at = time.time()
        set_terminal_phase(state)
        write_final_report(state)
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
