#!/usr/bin/env python3
"""
LibraForge suspect-review extractor.

Read-only report reviewer. Scans a LibraForge report JSON and extracts items
that deserve manual review before trusting a match -- including full matches
that might have slipped through with bad metadata.

Supported inputs:
  - Metadata Forge / audible-metadata-fixer v5 reports with report_items[]
  - Older fixer reports with items[] / categories[]
  - Folder Forge / organizer reports with stats.move_items[]

Optional:
  - Send the suspect package to a local Ollama model for advisory review.

Score note: Goodreads/Kindle matches legitimately score ~0.20-0.35 because
those providers do not return audio duration, which is a major scoring signal.
A separate --goodreads-low-score threshold (default 0.10) avoids flooding the
output with low-score flags for expected-low GR/Kindle matches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

TOOL_NAME = "libraforge-suspect-review"
SCHEMA_VERSION = 2

# Skip reasons that mean "this was already handled" -- not suspects.
BENIGN_SKIP_REASONS = frozenset({"already processed", "already manually applied"})

# Providers whose scores are expected to be much lower than Audible.
GR_PROVIDERS = frozenset({"goodreads", "kindle"})


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    value = "" if value is None else str(value)
    value = value.replace("꞉", ":")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize(value: Any) -> str:
    value = clean_text(value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"\[[^\]]*\]", " ", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b(?:unabridged|audiobook|booktrack|edition|booktrack edition)\b", " ", value)
    value = re.sub(r"\b(?:the|a|an)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_person_list(value: Any) -> str:
    value = clean_text(value)
    value = re.sub(r"\b(?:translator|editor|author|narrator)\b", " ", value, flags=re.I)
    value = re.sub(r"\s*-\s*", " ", value)
    return normalize(value)


def similarity(left: Any, right: Any) -> float:
    left_n = normalize(left)
    right_n = normalize(right)
    if not left_n and not right_n:
        return 1.0
    if not left_n or not right_n:
        return 0.0
    if left_n == right_n:
        return 1.0
    if left_n in right_n or right_n in left_n:
        return 0.92
    return SequenceMatcher(None, left_n, right_n).ratio()


def normalize_number(value: Any) -> str:
    value = clean_text(value)
    if not value:
        return ""
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return ""
    value = match.group(0)
    try:
        if "." in value:
            num = float(value)
            if num.is_integer():
                return str(int(num))
            return str(num).rstrip("0").rstrip(".")
        return str(int(value))
    except ValueError:
        return value.lstrip("0") or "0"


def extract_strong_number_from_text(value: Any) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if re.search(r"\bbooks\s+\d+(?:\.\d+)?\s*(?:-|to|through|&|and)\s*\d+", value, flags=re.I):
        return ""
    patterns = [
        r"\bbook\s*#?\s*(\d+(?:\.\d+)?)\b",
        r"\bvol(?:ume)?\.?\s*(\d+(?:\.\d+)?)\b",
        r"\bv\.?\s*(\d+(?:\.\d+)?)\b",
        r"#\s*(\d+(?:\.\d+)?)(?!\s*[-–—])\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, value, flags=re.I)
        if m:
            return normalize_number(m.group(1))
    return ""


def extract_series_suffix_number(value: Any, series: Any) -> str:
    """Detect '<series> 2' only for small 1-2 digit suffixes."""
    value_s = clean_text(value)
    series_s = clean_text(series)
    if not value_s or not series_s:
        return ""
    value_n = normalize(value_s)
    series_n = normalize(series_s)
    if not value_n.startswith(series_n + " "):
        return ""
    tail = value_n[len(series_n):].strip()
    if not re.fullmatch(r"\d{1,2}(?:\.\d+)?", tail):
        return ""
    if re.fullmatch(r"(?:19|20)\d{2}", tail):
        return ""
    return normalize_number(tail)


def extract_any_visible_number(item: dict[str, Any], local: dict[str, Any], match: dict[str, Any]) -> dict[str, str]:
    path = item.get("path") or item.get("source") or ""
    candidates = {
        "path": path,
        "path_parent": Path(path).parent.name if path else "",
        "path_grandparent": Path(path).parent.parent.name if path else "",
        "local_title": local.get("title", ""),
        "match_title": match.get("title", ""),
        "match_subtitle": match.get("subtitle", ""),
    }
    result = {}
    for key, value in candidates.items():
        strong = extract_strong_number_from_text(value)
        if strong:
            result[key] = strong
            continue
        if key in {"local_title", "path", "path_parent", "path_grandparent"}:
            suffix = extract_series_suffix_number(value, local.get("series") or match.get("series"))
            if suffix:
                result[key] = suffix
    return result


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def is_benign_skip(skip_reason: str) -> bool:
    """Return True for skip reasons that indicate normal/expected processing, not suspects."""
    sr = skip_reason.casefold().strip()
    return sr in BENIGN_SKIP_REASONS


_MULTI_BOOK_KW = re.compile(
    r"\b(?:omnibus|complete collection|definitive collection|complete series|"
    r"complete trilogy|complete duology|complete saga|trilogy|duology|box\s?set|"
    r"books?\s+\d+\s*(?:-|to|through|&)\s*\d+)\b",
    re.IGNORECASE,
)
_MULTI_BOOK_SEQ = re.compile(r"^\d+\s*-\s*\d+$")


def is_multi_book(local: dict, match: dict) -> bool:
    """Return True when the item is an omnibus/box-set/multi-book product.

    Mirrors the fixer's is_omnibus_product() logic plus local-side keyword scan.
    """
    for text in (
        local.get("title", ""),
        match.get("title", ""),
        match.get("subtitle", ""),
    ):
        if _MULTI_BOOK_KW.search(text or ""):
            return True
    if _MULTI_BOOK_SEQ.fullmatch(str(match.get("sequence", "") or "").strip()):
        return True
    return False


def is_folder_like_series(series: str) -> bool:
    """Return True when the local series looks like a folder-organization prefix.

    Libraries often store books in "2026 - Book 2" or "Book 3" folders before
    the organizer has run. These aren't real series names and should not trigger
    series-mismatch checks.
    """
    s = clean_text(series).strip()
    if not s:
        return False
    # Year-based prefixes: "2024", "2026 - Book 2", "2025 - Book 1 - Title"
    if re.match(r"^(19|20)\d{2}\b", s):
        return True
    # Pure numbering: "Book 2", "Vol 5", "Volume 3"
    if re.match(r"^(?:book|vol\.?|volume|part)\s*\d+$", s, re.I):
        return True
    return False


# ---------------------------------------------------------------------------
# Reason helpers
# ---------------------------------------------------------------------------

def add_reason(
    reasons: list[dict[str, Any]],
    code: str,
    severity: str,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    reasons.append({"code": code, "severity": severity, "message": message, "evidence": evidence or {}})


def severity_rank(severity: str) -> int:
    return {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 0)


def max_severity(reasons: list[dict[str, Any]]) -> str:
    if not reasons:
        return "none"
    return max((r.get("severity", "info") for r in reasons), key=severity_rank)


def recommendation_for_reasons(reasons: list[dict[str, Any]]) -> str:
    codes = {r.get("code") for r in reasons}
    if {"failed_item", "unsafe_match", "no_match", "score_below_minimum", "non_matched_status"} & codes:
        return "manual_lookup"
    if {"sequence_conflict", "visible_number_conflict", "title_number_conflict", "provider_missing_sequence"} & codes:
        return "verify_sequence_before_apply"
    if {"title_mismatch", "series_mismatch", "author_mismatch"} & codes:
        return "compare_against_runner_up_or_search_manually"
    if {"series_only_mode"} & codes:
        return "verify_metadata_completeness"
    if {"duplicate_asin", "duplicate_local_identity"} & codes:
        return "check_duplicate_or_alternate_edition"
    return "manual_review"


# ---------------------------------------------------------------------------
# Per-item review
# ---------------------------------------------------------------------------

def review_metadata_item(item: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    reasons: list[dict[str, Any]] = []
    local = item.get("local") or {}
    match = item.get("match") or {}

    status = clean_text(item.get("status", ""))
    skip_reason = clean_text(item.get("skip_reason", ""))
    mode = clean_text(item.get("mode", ""))
    duration_status = clean_text(item.get("duration_status", ""))
    score = item.get("score", None)
    provider = clean_text(item.get("provider", ""))
    write_action = clean_text(item.get("write_action", ""))
    was_manually_applied = bool(item.get("was_manually_applied"))

    # Only review items that will actually be written to disk.
    # write_skipped / smart_skipped / skipped items are already handled by the fixer -- not a risk.
    if write_action != "would_write":
        return None

    # --- Mode ---
    if status == "matched":
        if mode in {"none", "unknown"}:
            add_reason(reasons, "unsafe_match", "high", f"Match mode is {mode!r}.", {"mode": mode})
        elif mode == "series_only":
            add_reason(reasons, "series_only_mode", "medium", "Series-only match: metadata may be incomplete.", {"mode": mode})

    # --- Score -- provider-aware ---
    is_gr = provider in GR_PROVIDERS
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None

    effective_threshold = args.goodreads_low_score if is_gr else args.low_score
    already_flagged_for_skip = any(r["code"] in {"no_match", "score_below_minimum"} for r in reasons)
    if score_f is not None and score_f < effective_threshold and not already_flagged_for_skip:
        add_reason(
            reasons, "low_score", "medium" if is_gr else "high",
            f"Match score {score_f:.3f} is below {'Goodreads/Kindle' if is_gr else 'Audible'} review threshold {effective_threshold:.3f}.",
            {"score": score_f, "threshold": effective_threshold, "provider": provider or "audible"},
        )

    # --- Duration -- only flag real mismatches ---
    if duration_status == "mismatch":
        add_reason(
            reasons, "duration_mismatch", "high",
            "Local and provider audio durations differ beyond the mismatch threshold.",
            {
                "duration_status": duration_status,
                "local_minutes": local.get("duration_minutes"),
                "match_minutes": match.get("duration_minutes"),
                "diff_pct": match.get("duration_diff_pct"),
            },
        )
    # "unknown" is expected for GR (no duration data); "acceptable"/"strong"/"perfect" are fine.

    # --- Sequence ---
    local_seq = normalize_number(local.get("sequence"))
    match_seq = normalize_number(match.get("sequence"))

    if local_seq and match_seq and local_seq != match_seq:
        add_reason(
            reasons, "sequence_conflict", "high",
            "Local sequence and provider sequence disagree.",
            {"local_sequence": local_seq, "match_sequence": match_seq},
        )
    elif local_seq and not match_seq and mode == "full" and not is_gr:
        # GR/Kindle routinely omit sequence -- don't flag.
        # Omnibus/box-set/multi-book products on Audible also rarely carry a sequence number.
        if (local.get("series") or match.get("series")) and not is_multi_book(local, match):
            add_reason(
                reasons, "provider_missing_sequence", "medium",
                "Local item has a sequence but the Audible match has none.",
                {"local_sequence": local_seq},
            )

    # --- Visible number conflicts -- deduplicated by number value ---
    visible_numbers = extract_any_visible_number(item, local, match)
    # Group sources that agree on the same number value.
    number_to_sources: dict[str, list[str]] = defaultdict(list)
    for src, num in visible_numbers.items():
        number_to_sources[num].append(src)

    for number, sources in number_to_sources.items():
        sources_str = ", ".join(sources)
        if local_seq and number != local_seq:
            add_reason(
                reasons, "visible_number_conflict", "high",
                f"Visible number {number!r} (from {sources_str}) conflicts with local sequence {local_seq!r}.",
                {"visible_number": number, "sources": sources, "local_sequence": local_seq},
            )
        elif match_seq and number != match_seq and not local_seq:
            # Only flag match-sequence conflict when there's no local_seq (already covered above)
            add_reason(
                reasons, "visible_number_conflict", "medium",
                f"Visible number {number!r} (from {sources_str}) conflicts with provider sequence {match_seq!r}.",
                {"visible_number": number, "sources": sources, "match_sequence": match_seq},
            )

    # --- Title similarity ---
    local_title = clean_text(local.get("title"))
    match_title = clean_text(match.get("title"))
    if local_title and match_title:
        title_score = similarity(local_title, match_title)
        if title_score < args.title_similarity:
            add_reason(
                reasons, "title_mismatch", "medium",
                "Local title and provider title have low similarity.",
                {"local_title": local_title, "match_title": match_title, "similarity": round(title_score, 3)},
            )

    # --- Series similarity -- skip folder-like local series or empty GR series ---
    local_series = clean_text(local.get("series"))
    match_series = clean_text(match.get("series"))
    if local_series and match_series and not is_folder_like_series(local_series):
        series_score = similarity(local_series, match_series)
        if series_score < args.series_similarity:
            add_reason(
                reasons, "series_mismatch", "high",
                "Local series and provider series have low similarity.",
                {"local_series": local_series, "match_series": match_series, "similarity": round(series_score, 3)},
            )

    # --- Author similarity ---
    local_author = normalize_person_list(local.get("author"))
    match_author = normalize_person_list(match.get("author"))
    if local_author and match_author and local_author not in match_author and match_author not in local_author:
        author_score = SequenceMatcher(None, local_author, match_author).ratio()
        if author_score < args.author_similarity:
            add_reason(
                reasons, "author_mismatch", "high",
                "Local author and provider author have low similarity.",
                {"local_author": local.get("author"), "match_author": match.get("author"), "similarity": round(author_score, 3)},
            )

    if not reasons:
        return None

    return {
        "id": item.get("id"),
        "path": item.get("path") or item.get("source") or "",
        "tool": "metadata_fixer",
        "status": status,
        "severity": max_severity(reasons),
        "recommendation": recommendation_for_reasons(reasons),
        "reasons": reasons,
        "score": score,
        "mode": mode,
        "provider": provider,
        "write_action": write_action,
        "duration_status": duration_status,
        "local": local,
        "match": match,
        "used_query": item.get("used_query", ""),
    }


def add_metadata_cross_item_suspects(
    suspects: list[dict[str, Any]], report_items: list[dict[str, Any]], args: argparse.Namespace
) -> None:
    asin_to_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identity_to_items: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for item in report_items:
        match = item.get("match") or {}
        local = item.get("local") or {}
        asin = clean_text(match.get("asin"))
        if asin:
            asin_to_items[asin].append(item)

        series_key = normalize(local.get("series") or match.get("series"))
        seq_key = normalize_number(local.get("sequence") or match.get("sequence"))
        author_key = normalize(local.get("author") or match.get("author"))
        if series_key and seq_key and not is_folder_like_series(local.get("series", "")):
            identity_to_items[(series_key, seq_key, author_key)].append(item)

    for asin, items in sorted(asin_to_items.items()):
        if len(items) <= 1:
            continue
        # Only flag when at least one of the duplicates will actually be written.
        if not any(clean_text(i.get("write_action")) == "would_write" for i in items):
            continue
        paths = [item.get("path") or "" for item in items]
        suspects.append({
            "id": None, "path": "", "tool": "metadata_fixer", "status": "cross_item",
            "severity": "high", "recommendation": "check_duplicate_or_alternate_edition",
            "reasons": [{"code": "duplicate_asin", "severity": "high",
                         "message": "Same provider ASIN assigned to multiple local files.",
                         "evidence": {"asin": asin, "paths": paths}}],
            "related_paths": paths,
        })

    for (series_key, seq_key, author_key), items in sorted(identity_to_items.items()):
        if len(items) <= 1:
            continue
        if not any(clean_text(i.get("write_action")) == "would_write" for i in items):
            continue
        titles = sorted({clean_text((item.get("local") or {}).get("title")) for item in items})
        paths = [item.get("path") or "" for item in items]
        suspects.append({
            "id": None, "path": "", "tool": "metadata_fixer", "status": "cross_item",
            "severity": "low", "recommendation": "check_duplicate_or_alternate_edition",
            "reasons": [{"code": "duplicate_local_identity", "severity": "low",
                         "message": "Multiple local files share the same author/series/sequence (may be alternate editions or duplicates).",
                         "evidence": {"series_key": series_key, "sequence": seq_key, "author_key": author_key,
                                      "titles": titles, "paths": paths}}],
            "related_paths": paths,
        })


def review_organizer_item(item: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    reasons: list[dict[str, Any]] = []

    for reason in item.get("review_reasons") or []:
        add_reason(reasons, "existing_review_reason", "medium", clean_text(reason), {"review_reason": reason})

    target = clean_text(item.get("target"))
    source = clean_text(item.get("source"))
    title = clean_text(item.get("title"))
    author = clean_text(item.get("author"))
    series = clean_text(item.get("series"))
    number = normalize_number(item.get("number"))

    if not author or author.casefold().startswith("unknown"):
        add_reason(reasons, "unknown_author", "high", "Organizer item has unknown/missing author.")
    if not title or title.casefold().startswith("unknown"):
        add_reason(reasons, "unknown_title", "medium", "Organizer item has unknown/missing title.")

    visible_source = extract_strong_number_from_text(source) or extract_series_suffix_number(source, series)
    visible_target = extract_strong_number_from_text(target)
    if number and visible_source and number != visible_source:
        add_reason(reasons, "organizer_source_number_conflict", "high",
                   "Organizer sequence differs from visible source/path number.",
                   {"selected_number": number, "visible_source_number": visible_source})
    if number and visible_target and number != visible_target:
        add_reason(reasons, "organizer_target_number_conflict", "critical",
                   "Organizer sequence differs from target folder number.",
                   {"selected_number": number, "visible_target_number": visible_target})

    if not reasons:
        return None

    return {
        "id": item.get("id"), "path": source, "tool": "organizer",
        "status": item.get("status", "planned_move"),
        "severity": max_severity(reasons),
        "recommendation": recommendation_for_reasons(reasons),
        "reasons": reasons,
        "local": {"title": title, "author": author, "series": series, "sequence": number,
                  "target": target, "metadata_source": item.get("metadata_source", "")},
    }


# ---------------------------------------------------------------------------
# Report routing
# ---------------------------------------------------------------------------

def infer_report_kind(report: dict[str, Any]) -> str:
    if isinstance(report.get("report_items"), list):
        return "metadata_fixer"
    if isinstance((report.get("stats") or {}).get("move_items"), list):
        return "organizer"
    if isinstance(report.get("items"), list) and "mode_breakdown" in (report.get("stats") or {}):
        return "metadata_fixer"
    return "unknown"


def extract_suspects(report: dict[str, Any], args: argparse.Namespace) -> tuple[list[dict[str, Any]], int]:
    """Return (suspects, suppressed_count)."""
    kind = infer_report_kind(report)
    suspects: list[dict[str, Any]] = []
    suppressed = 0

    if kind == "metadata_fixer":
        report_items = report.get("report_items") or []
        if report_items:
            for index, item in enumerate(report_items, start=1):
                item.setdefault("id", item.get("id") or index)
                suspect = review_metadata_item(item, args)
                if suspect:
                    suspects.append(suspect)
                elif (
                    item.get("status") == "skipped"
                    and is_benign_skip(clean_text(item.get("skip_reason", "")))
                ) or item.get("was_manually_applied"):
                    suppressed += 1
            add_metadata_cross_item_suspects(suspects, report_items, args)
        else:
            for item in report.get("items") or []:
                categories = set(item.get("categories") or [])
                if not {"status:matched", "mode:full"}.issubset(categories):
                    reasons: list[dict[str, Any]] = []
                    for category in sorted(categories):
                        if category.startswith("status:") and category != "status:matched":
                            add_reason(reasons, "non_matched_status", "high", f"Item category {category!r}.")
                        if category.startswith("mode:") and category not in {"mode:full"}:
                            add_reason(reasons, "unsafe_match", "high", f"Item category {category!r}.")
                    if reasons:
                        suspects.append({"id": item.get("id"), "path": item.get("path", ""), "tool": "metadata_fixer",
                                         "status": "summary_item", "severity": max_severity(reasons),
                                         "recommendation": recommendation_for_reasons(reasons), "reasons": reasons})

    elif kind == "organizer":
        for index, item in enumerate((report.get("stats") or {}).get("move_items") or [], start=1):
            item.setdefault("id", item.get("id") or index)
            suspect = review_organizer_item(item, args)
            if suspect:
                suspects.append(suspect)

    suspects = sorted(
        suspects,
        key=lambda item: (-severity_rank(item.get("severity", "info")), item.get("tool", ""), clean_text(item.get("path", ""))),
    )
    return suspects, suppressed


# ---------------------------------------------------------------------------
# LLM integration
# ---------------------------------------------------------------------------

def compact_for_llm(suspects: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    compact = []
    for item in suspects[:limit]:
        entry: dict[str, Any] = {
            "path": item.get("path"),
            "severity": item.get("severity"),
            "recommendation": item.get("recommendation"),
            "write_action": item.get("write_action") or None,
            "provider": item.get("provider") or "audible",
            "score": item.get("score"),
            "mode": item.get("mode") or None,
            "reasons": [
                {"code": r.get("code"), "message": r.get("message"), "evidence": r.get("evidence")}
                for r in item.get("reasons", [])
            ],
            "local": item.get("local"),
            "match": item.get("match"),
        }
        # Drop None/empty top-level keys to reduce tokens
        entry = {k: v for k, v in entry.items() if v not in (None, "", [], {})}
        compact.append(entry)
    return compact


_LLM_SYSTEM = """\
You are a read-only audiobook metadata reviewer for LibraForge.

CONTEXT:
- Each item shows local file metadata, a proposed provider match, the reasons
  it was flagged, and write_action (would_write = will be applied to the file).
- Scores are 0-1. Audible matches typically score 0.7-1.0. Goodreads/Kindle
  matches legitimately score 0.15-0.35 because they lack audio duration data --
  a low score alone is NOT evidence of a bad match for those providers.
- Focus on: wrong author, wrong title, sequence/book-number conflicts, and cases
  where the proposed match is clearly a different book.
- Do NOT suggest file writes or commands.

TASK:
For each item classify it as one of:
  safe                  -- the match looks correct despite the flag
  needs_review          -- something is off but not definitely wrong
  likely_bad_match      -- strong evidence the proposed match is incorrect
  duplicate_or_alt_edition -- same book matched to two local files

Return ONLY valid JSON in this exact shape:
{"summary": "one-sentence overall assessment", "items": [{"path": "...", "verdict": "...", "confidence": 0.0-1.0, "reason": "one concise line"}]}
"""


def call_ollama(suspects: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    compact = compact_for_llm(suspects, args.ollama_limit)
    payload = {
        "model": args.ollama_model,
        "stream": False,
        "format": "json",
        "options": {"temperature": args.ollama_temperature, "num_ctx": args.ollama_context},
        "system": _LLM_SYSTEM,
        "prompt": "Suspects:\n" + json.dumps(compact, ensure_ascii=False, indent=2),
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        args.ollama_url.rstrip("/") + "/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=args.ollama_timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    text = body.get("response", "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_response": text, "parse_error": "ollama response was not valid JSON"}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def build_output(
    report: dict[str, Any],
    suspects: list[dict[str, Any]],
    suppressed: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    severity_counts = Counter(item.get("severity", "unknown") for item in suspects)
    reason_counts = Counter(r.get("code", "unknown") for item in suspects for r in item.get("reasons", []))
    kind = infer_report_kind(report)
    input_count = 0
    if kind == "metadata_fixer":
        input_count = len(report.get("report_items") or report.get("items") or [])
    elif kind == "organizer":
        input_count = len((report.get("stats") or {}).get("move_items") or [])

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_report": {
            "id": report.get("id"),
            "kind": kind,
            "status": report.get("status"),
            "command": report.get("command", []),
            "log_file": report.get("log_file"),
        },
        "summary": {
            "input_items": input_count,
            "suspect_items": len(suspects),
            "suppressed_benign": suppressed,
            "severity_counts": dict(sorted(severity_counts.items())),
            "reason_counts": dict(reason_counts.most_common()),
        },
        "suspects": suspects,
    }


def print_text_summary(output: dict[str, Any]) -> None:
    summary = output.get("summary", {})
    suppressed = summary.get("suppressed_benign", 0)
    print(f"{TOOL_NAME}: {summary.get('suspect_items', 0)} suspects out of {summary.get('input_items', 0)} items"
          + (f" ({suppressed} benign skips suppressed)" if suppressed else ""))
    print(f"Severity: {summary.get('severity_counts', {})}")
    print(f"Reasons:  {summary.get('reason_counts', {})}")
    print()
    for index, item in enumerate(output.get("suspects", []), start=1):
        write_tag = f" [{item.get('write_action')}]" if item.get("write_action") else ""
        provider_tag = f" ({item.get('provider')})" if item.get("provider") else ""
        print(f"{index}. [{item.get('severity')}]{write_tag}{provider_tag} {item.get('path') or '(cross-item)'}")
        for reason in item.get("reasons", []):
            print(f"   - {reason.get('code')}: {reason.get('message')}")
        print(f"   recommendation: {item.get('recommendation')}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract suspect manual-review items from a LibraForge report JSON."
    )
    parser.add_argument("report", type=Path, help="Path to LibraForge report JSON")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON path (default: <report>.suspect-review.json)")
    parser.add_argument("--text", action="store_true", help="Print a human-readable summary to stdout")
    parser.add_argument("--low-score", type=float, default=0.85,
                        help="Flag Audible matches below this score (default: 0.85)")
    parser.add_argument("--goodreads-low-score", type=float, default=0.10,
                        help="Flag Goodreads/Kindle matches below this score (default: 0.10; GR scores ~0.2-0.35 by design)")
    parser.add_argument("--title-similarity", type=float, default=0.72,
                        help="Flag title similarity below this ratio (default: 0.72)")
    parser.add_argument("--series-similarity", type=float, default=0.80,
                        help="Flag series similarity below this ratio (default: 0.80)")
    parser.add_argument("--author-similarity", type=float, default=0.55,
                        help="Flag author similarity below this ratio (default: 0.55)")
    parser.add_argument("--ollama-url", default="",
                        help="Optional Ollama base URL, e.g. http://10.0.0.20:11434")
    parser.add_argument("--ollama-model", default="qwen3:4b",
                        help="Ollama model for advisory review (default: qwen3:4b)")
    parser.add_argument("--ollama-limit", type=int, default=25,
                        help="Max suspects to send to Ollama (default: 25)")
    parser.add_argument("--ollama-timeout", type=int, default=180,
                        help="Ollama request timeout in seconds (default: 180)")
    parser.add_argument("--ollama-context", type=int, default=8192,
                        help="Ollama num_ctx token window (default: 8192)")
    parser.add_argument("--ollama-temperature", type=float, default=0.0,
                        help="Ollama temperature (default: 0.0)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    with args.report.open("r", encoding="utf-8") as file:
        report = json.load(file)

    suspects, suppressed = extract_suspects(report, args)
    output = build_output(report, suspects, suppressed, args)

    if args.ollama_url and suspects:
        try:
            output["llm_review"] = call_ollama(suspects, args)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            output["llm_review_error"] = str(error)

    output_path = args.output
    if output_path is None:
        output_path = args.report.with_name(args.report.stem + ".suspect-review.json")

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False)
        file.write("\n")

    if args.text:
        print_text_summary(output)
    else:
        print(f"Wrote suspect review: {output_path}")
        print(f"Suspects: {output['summary']['suspect_items']} / {output['summary']['input_items']}"
              + (f" ({suppressed} benign suppressed)" if suppressed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
