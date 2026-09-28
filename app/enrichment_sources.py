"""Evidence sources for Enrichment Forge v2 (besides Audible and Goodreads).

Book level: AudioSilo (meta.audiosilo.app, CC0 community audiobook DB) and
Open Library subjects. Series level: progressionfantasy.co.uk's catalogue and
the HaremLit Fiction wiki. Each lookup returns a status dict shaped like
app/goodreads_shelves.fetch_book_shelves: found / not_found / failed /
skipped. Every match is title-verified first: AudioSilo falls back to fuzzy
matching and confidently returns a different book ("Australia: A History" ->
"Blue Moon Australia"), and Open Library's first doc is often another work.
A mismatch is not_found and never votes.

Each source has its own pacer (gap + breaker, the same class Goodreads uses)
so one slow or blocking source can't stall or trip the others. `http_get` is
injected everywhere so tests never touch the network.
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from app.genre_taxonomy import LABEL_MAP, labels_from_genres, normalize_label
from app.goodreads_shelves import GoodreadsPacer, clean_query_title, title_matches

SourcePacer = GoodreadsPacer
# Measured in the 2026-09-27 full-library run: AudioSilo showed no limiting at
# ~100 req/min; Open Library answers in 1-3 s and asks for about 1 req/s.
AUDIOSILO_PACER = SourcePacer(gap_s=0.35, fail_threshold=3, cooldown_s=60)
OPENLIBRARY_PACER = SourcePacer(gap_s=1.0, fail_threshold=3, cooldown_s=60)

AUDIOSILO_SEARCH_URL = "https://meta.audiosilo.app/abs/search"
OPENLIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
_USER_AGENT = "Mozilla/5.0"  # progressionfantasy.co.uk 403s descriptive UAs
_REAL_ASIN_RE = re.compile(r"B0[0-9A-Z]{8}")
SOURCE_WORKERS = 2

HttpGet = Callable[[str, float], Any]


def http_get_json(url: str, timeout: float = 20) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _result(status: str, title: str | None = None, labels: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "title": title, "labels": labels or []}


def _paced_get(url: str, pacer: GoodreadsPacer, http_get: HttpGet, timeout: float = 20) -> tuple[str, Any]:
    """('ok', data) | ('not_found', None) | ('failed', None) | ('skipped', None)."""
    if not pacer.wait_turn():
        return "skipped", None
    try:
        data = http_get(url, timeout)
    except urllib.error.HTTPError as exc:
        pacer.record(exc.code == 404)
        return ("not_found" if exc.code == 404 else "failed"), None
    except Exception:
        pacer.record(False)
        return "failed", None
    pacer.record(True)
    return "ok", data


def _primary_author(book: dict[str, Any]) -> str:
    return str(book.get("author") or "").split(",")[0].split(" - ")[0].strip()


def audiosilo_lookup(book: dict[str, Any], *, pacer: GoodreadsPacer = AUDIOSILO_PACER,
                     http_get: HttpGet = http_get_json) -> dict[str, Any]:
    """AudioSilo by real ASIN first, then by clean title + author surname."""
    wanted = clean_query_title(str(book.get("title") or ""))
    author = _primary_author(book)
    queries = []
    asin = str(book.get("asin") or "").upper()
    if _REAL_ASIN_RE.fullmatch(asin):
        queries.append({"query": asin})
    queries.append({"query": wanted, "author": author.split()[-1] if author else ""})
    for params in queries:
        status, data = _paced_get(AUDIOSILO_SEARCH_URL + "?" + urllib.parse.urlencode(params), pacer, http_get)
        if status != "ok":
            if status == "not_found":
                continue
            return _result(status)
        matches = (data or {}).get("matches") or [] if isinstance(data, dict) else []
        if not matches:
            continue
        found = matches[0]
        if not title_matches(str(found.get("title") or ""), wanted):
            return _result("not_found", found.get("title"))
        return _result("found", found.get("title"), labels_from_genres(found.get("genres") or []))
    return _result("not_found")


def openlibrary_lookup(book: dict[str, Any], *, pacer: GoodreadsPacer = OPENLIBRARY_PACER,
                       http_get: HttpGet = http_get_json) -> dict[str, Any]:
    """Open Library subjects, kept only when they map into the taxonomy
    (its subjects are noisy: 'Fiction', 'Wizards', place names...)."""
    wanted = clean_query_title(str(book.get("title") or ""))
    params = {"title": wanted, "author": _primary_author(book), "fields": "title,subject", "limit": "1"}
    status, data = _paced_get(OPENLIBRARY_SEARCH_URL + "?" + urllib.parse.urlencode(params), pacer, http_get)
    if status != "ok":
        return _result(status)
    docs = (data or {}).get("docs") or [] if isinstance(data, dict) else []
    if not docs:
        return _result("not_found")
    doc = docs[0]
    if not title_matches(str(doc.get("title") or ""), wanted):
        return _result("not_found", doc.get("title"))
    labels = []
    for subject in doc.get("subject") or []:
        label = normalize_label(subject)
        if label in LABEL_MAP and label not in labels:
            labels.append(label)
    return _result("found", doc.get("title"), labels)


def search_series_sources(
    books: list[dict[str, Any]],
    lookup_fn: Callable[..., dict[str, Any]],
    pacer: GoodreadsPacer,
    workers: int = SOURCE_WORKERS,
    limit: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Run one book-level source over a unit's audio books (the first `limit`
    of them when set). No-audio books are skipped (#301)."""
    results: dict[str, dict[str, Any]] = {}
    audio = [b for b in books if b.get("has_audio", True)]
    for book in books:
        if not book.get("has_audio", True):
            results[book["id"]] = _result("skipped")
    targets = audio[:limit] if limit else audio

    def _one(book: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        try:
            return book["id"], lookup_fn(book, pacer=pacer)
        except Exception:
            return book["id"], _result("failed")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for book_id, result in pool.map(_one, targets):
            results[book_id] = result
    return results


def summarize_status(label: str, results: dict[str, dict[str, Any]], books: list[dict[str, Any]]) -> dict[str, Any]:
    """EnrichmentSourceStatus-shaped counts for one book-level source."""
    statuses = [results[b["id"]]["status"] for b in books if b.get("has_audio", True) and b["id"] in results]
    skipped = statuses.count("skipped")
    return {
        "label": label,
        "state": "searched",
        "searched": len(statuses) - skipped,
        "found": statuses.count("found"),
        "failed": statuses.count("failed"),
        "skipped": skipped,
        "rate_limited": skipped > 0,
        "detail": f"{label} is failing or rate-limiting; paused, the remaining books were skipped." if skipped else "",
    }
