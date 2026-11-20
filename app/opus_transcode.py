"""Opus transcode (DEV / WIP): request model, dev-feature flag, command builder and output parser.

The work itself is done by scripts/opus-transcode.py (a subprocess, like the fixer and
Folder Forge). This module only decides whether the feature is switched on, turns a
request into that script's command line, and reads the script's JSON lines back into
run stats for the M4B Tool page.

The feature is hidden unless LIBRAFORGE_DEV_FEATURES lists "opus_transcode" (or "all").
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEV_FEATURES_ENV = "LIBRAFORGE_DEV_FEATURES"
FEATURE = "opus_transcode"
SCRIPT_NAME = "opus-transcode.py"
MODES = ("celt", "auto", "voip")


def dev_features() -> list[str]:
    raw = os.environ.get(DEV_FEATURES_ENV, "")
    return sorted({part.strip().lower() for part in raw.split(",") if part.strip()})


def opus_transcode_enabled() -> bool:
    enabled = dev_features()
    return FEATURE in enabled or "all" in enabled


class OpusTranscodeRunRequest(BaseModel):
    root_path: str
    staging_path: str
    apply: bool = False
    only: list[str] = Field(default_factory=list)
    workers: int = Field(default=2, ge=1, le=12)
    mono_kbps: int = Field(default=32, ge=8, le=128)
    stereo_kbps: int = Field(default=48, ge=12, le=192)
    src_cap_ratio: float = Field(default=0.8, ge=0.3, le=1.0)
    leave_alone_kbps: float = Field(default=48, ge=0, le=320)
    max_size_ratio: float = Field(default=0.75, ge=0.1, le=1.0)
    mode: str = "celt"
    frame_ms: int = 60
    side_margin_db: float = Field(default=30.0, ge=6, le=80)
    side_floor_db: float = Field(default=-60.0, ge=-120, le=-20)


def validate_request(req: OpusTranscodeRunRequest, root: Path, staging: Path) -> None:
    """Raise ValueError with a user-facing message when the request cannot run safely."""
    if req.mode not in MODES:
        raise ValueError(f"Unknown encoder mode {req.mode!r} (use one of {', '.join(MODES)})")
    if req.frame_ms not in (20, 40, 60):
        raise ValueError("Frame duration must be 20, 40 or 60 ms")
    if not staging.is_absolute():
        raise ValueError("The staging folder must be an absolute path")
    if staging == root or root in staging.parents:
        raise ValueError("The staging folder must be outside the folder being scanned")
    if not staging.exists() and not staging.parent.is_dir():
        raise ValueError(f"The staging folder's parent does not exist: {staging.parent}")


def build_command(req: OpusTranscodeRunRequest, scripts_dir: Path, python: str = "python3") -> list[str]:
    cmd = [python, "-u", str(scripts_dir / SCRIPT_NAME), req.root_path, "--staging", req.staging_path,
           "--workers", str(req.workers),
           "--mono-kbps", str(req.mono_kbps), "--stereo-kbps", str(req.stereo_kbps),
           "--src-cap-ratio", f"{req.src_cap_ratio:g}", "--leave-alone-kbps", f"{req.leave_alone_kbps:g}",
           "--max-size-ratio", f"{req.max_size_ratio:g}", "--mode", req.mode, "--frame-ms", str(req.frame_ms),
           "--side-margin-db", f"{req.side_margin_db:g}", "--side-floor-db", f"{req.side_floor_db:g}"]
    for needle in req.only:
        if needle.strip():
            cmd += ["--only", needle.strip()]
    if req.apply:
        cmd.append("--apply")
    return cmd


def _plan_view(row: dict[str, Any]) -> dict[str, Any]:
    keep = ("key", "kind", "folder", "files", "action", "reason", "flags", "duration_h", "source_mb", "src_kbps",
            "src_codec", "channels", "target_kbps", "predicted_mb")
    return {k: row.get(k) for k in keep if k in row}


def _result_view(res: dict[str, Any]) -> dict[str, Any]:
    verify = res.get("verify") or {}
    return {
        "key": res.get("key"), "folder": res.get("folder"), "out": res.get("out"), "status": res.get("status"),
        "target": res.get("target"), "stereo_check": res.get("stereo_check"),
        "src_size": res.get("src_size"), "out_size": res.get("out_size"), "wall_s": res.get("wall_s"),
        "failed_checks": sorted(k for k, v in verify.items() if v is False),
        "error": (res.get("error") or "")[-400:],
    }


def parse_line(stats: dict[str, Any], line: str) -> dict[str, Any] | None:
    """Fold one script output line into run stats. Returns the parsed payload plus
    "line" (plan / results / summary) for the JSON lines, None for plain lines."""
    for tag, key in (("OPUS_PLAN_JSON: ", "plan"), ("OPUS_RESULT_JSON: ", "results"), ("OPUS_SUMMARY_JSON: ", "summary")):
        if line.startswith(tag):
            try:
                payload = json.loads(line[len(tag):])
            except json.JSONDecodeError:
                return None
            opus = stats.setdefault("opus", {"plan": [], "results": [], "summary": {}})
            if key == "summary":
                opus["summary"] = payload
            elif key == "plan":
                opus["plan"].append(_plan_view(payload))
            else:
                opus["results"].append(_result_view(payload))
            return {**payload, "line": key}
    return None
