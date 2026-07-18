from __future__ import annotations

import json
import sys
from pathlib import Path

from app.chaptering import detect_chapters, detect_chapters_hybrid


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python -m app.chaptering_runner CONFIG_JSON RESULT_JSON", file=sys.stderr)
        return 2

    config_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    config = json.loads(config_path.read_text(encoding="utf-8"))

    def progress(message: str) -> None:
        print(json.dumps({"type": "progress", "message": message}), flush=True)

    if config.get("backend") == "hybrid-sos-focused":
        result = detect_chapters_hybrid(
            Path(config["source_path"]),
            remote_endpoint=str(config.get("remote_endpoint") or ""),
            focused_model_name=str(config.get("focused_model") or "medium"),
            focused_compute_type=str(config.get("focused_compute_type") or "float16"),
            max_gap_rescans=int(config.get("max_gap_rescans") or 8),
            silence_snap=bool(config["silence_snap"]),
            silence_window=float(config["silence_window"]),
            silence_marker_lead_seconds=float(config.get("silence_marker_lead_seconds", 1.0)),
            llm_review=bool(config.get("llm_review")),
            llm_endpoint=str(config.get("llm_endpoint") or ""),
            llm_model=str(config.get("llm_model") or "gemma4:latest"),
            llm_extra_instructions=str(config.get("llm_extra_instructions") or ""),
            sos_numbers_only=bool(config.get("sos_numbers_only")),
            progress=progress,
        )
    else:
        result = detect_chapters(
            Path(config["source_path"]),
            model_name=config["model"],
            device=config["device"],
            compute_type=config["compute_type"],
            cpu_threads=int(config["cpu_threads"]),
            vad_filter=bool(config["vad_filter"]),
            language=str(config.get("language") or "en"),
            condition_on_previous_text=bool(config.get("condition_on_previous_text")),
            beam_size=int(config.get("beam_size") or 1),
            silence_snap=bool(config["silence_snap"]),
            silence_window=float(config["silence_window"]),
            silence_marker_lead_seconds=float(config.get("silence_marker_lead_seconds", 1.0)),
            stable_ts=bool(config["stable_ts"]),
            max_audio_seconds=float(config.get("max_audio_seconds") or 0.0),
            chunk_seconds=float(config.get("chunk_seconds") or 0.0),
            focused_rescan=bool(config.get("focused_rescan", True)),
            focused_model_name=str(config.get("focused_model") or ""),
            focused_compute_type=str(config.get("focused_compute_type") or ""),
            focused_beam_size=int(config.get("focused_beam_size") or 5),
            max_gap_rescans=int(config.get("max_gap_rescans") or 8),
            progress=progress,
        )
    result_path.write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps({"type": "complete", "chapters": len(result.get("chapters", []))}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
