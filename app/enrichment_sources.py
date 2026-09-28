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


# ---------------------------------------------------------------------------
# Series-level sources
# ---------------------------------------------------------------------------

PROGRESSIONFANTASY_POSTS_URL = "https://progressionfantasy.co.uk/wp-json/wp/v2/posts"
_PF_CATEGORIES = {8: "LitRPG", 6: "Progression"}  # 8 = "LitRPG & GameLit", 6 = "Non-LitRPG" progression
HAREMLIT_API_URL = "https://haremlit-fiction.fandom.com/api.php"


def _norm_series(name: Any) -> str:
    text = str(name or "").strip().lower()
    text = re.sub(r"\s*\(series\)\s*$|\s+series\s*$|\s+\d+(\.\d+)?\s*$", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _series_names_match(a: str, b: str) -> bool:
    na, nb = _norm_series(a), _norm_series(b)
    if not na or not nb:
        return False
    return na == nb or (min(len(na), len(nb)) >= 5 and (na.startswith(nb) or nb.startswith(na)))


def _author_matches(candidate: str, authors: list[str]) -> bool:
    cand = str(candidate or "").lower()
    for author in authors:
        surname = str(author or "").strip().lower().split()[-1:] or [""]
        if surname[0] and surname[0] in cand:
            return True
    return False


class ProgressionFantasyIndex:
    """progressionfantasy.co.uk's catalogue ("Author – Series" posts, ~860),
    downloaded once per TTL and matched locally by series name + author.
    Category "Non-LitRPG" is broad (lists The Dresden Files), so voting only
    trusts "Progression" when corroborated (app/genre_voting.py)."""

    def __init__(self, http_get: HttpGet = http_get_json, ttl_s: float = 86400,
                 failure_retry_s: float = 600, clock: Callable[[], float] = time.monotonic):
        self._http_get = http_get
        self._ttl_s = ttl_s
        self._failure_retry_s = failure_retry_s
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: list[tuple[str, str, str]] | None = None  # (author, series, category)
        self._loaded_at = 0.0
        self._failed_at: float | None = None

    def _load(self) -> bool:
        now = self._clock()
        if self._entries is not None and now - self._loaded_at < self._ttl_s:
            return True
        if self._failed_at is not None and now - self._failed_at < self._failure_retry_s:
            return self._entries is not None
        entries: list[tuple[str, str, str]] = []
        try:
            page = 1
            while True:
                posts = self._http_get(f"{PROGRESSIONFANTASY_POSTS_URL}?per_page=100&page={page}&_fields=title,categories", 30)
                if not isinstance(posts, list) or not posts:
                    break
                for post in posts:
                    title = html.unescape(str((post.get("title") or {}).get("rendered") or ""))
                    author, sep, series = title.partition(" – ")
                    category = next((_PF_CATEGORIES[c] for c in post.get("categories") or [] if c in _PF_CATEGORIES), None)
                    if sep and category:
                        entries.append((author.strip(), series.strip(), category))
                page += 1
        except urllib.error.HTTPError as exc:
            # WordPress answers past-the-last-page with 400; anything else failed.
            if not (exc.code == 400 and entries):
                self._failed_at = now
                return self._entries is not None
        except Exception:
            self._failed_at = now
            return self._entries is not None
        self._entries, self._loaded_at, self._failed_at = entries, now, None
        return True

    def lookup(self, series_name: str, authors: list[str]) -> dict[str, Any]:
        with self._lock:
            if not self._load():
                return {"status": "failed", "category": None, "title": None}
            entries = list(self._entries or [])
        for author, series, category in entries:
            if not _series_names_match(series, series_name):
                continue
            # Web serials are often listed under a pen name ("Shirtaloon" for
            # Travis Deverell), so a distinctive exact name stands on its own;
            # short names ("Cradle") still need the author.
            exact = _norm_series(series) == _norm_series(series_name) and len(_norm_series(series_name)) >= 12
            if exact or _author_matches(author, authors):
                return {"status": "found", "category": category, "title": f"{author} – {series}"}
        return {"status": "not_found", "category": None, "title": None}


PF_INDEX = ProgressionFantasyIndex()

_TEMPLATE_RE = re.compile(r"\{\{(Book_Series_Template|Book_Template)\|(.*?)\}\}", re.S)
_WIKILINK_RE = re.compile(r"\[\[(?::?Category:)?([^|\]]+)(?:\|[^\]]*)?\]\]")


def _wiki(params: dict[str, str], http_get: HttpGet) -> dict[str, Any]:
    data = http_get(HAREMLIT_API_URL + "?" + urllib.parse.urlencode({**params, "format": "json"}), 20)
    return data if isinstance(data, dict) else {}


def _wikitext(page: str, http_get: HttpGet) -> str:
    return str(((_wiki({"action": "parse", "page": page, "prop": "wikitext"}, http_get).get("parse") or {})
                .get("wikitext") or {}).get("*") or "")


def _template_fields(text: str) -> dict[str, str] | None:
    match = _TEMPLATE_RE.search(text)
    if not match:
        return None
    fields = {"_type": match.group(1)}
    for part in re.split(r"\|(?![^\[]*\]\])", match.group(2)):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = _WIKILINK_RE.sub(r"\1", value).strip()
    return fields


def haremlit_lookup(series_name: str, authors: list[str], *, http_get: HttpGet = http_get_json) -> dict[str, Any]:
    """HaremLit Fiction wiki: the series' own page (author-checked), else the
    author's page listing the series. The wiki only documents harem fiction,
    so either is harem evidence; the series page also carries `explicit_sex`."""
    empty = {"status": "not_found", "match": None, "explicit": None, "genres": [], "via": None}
    try:
        hits = ((_wiki({"action": "query", "list": "search", "srsearch": series_name, "srlimit": "8"}, http_get)
                 .get("query") or {}).get("search") or [])
        hits = sorted(hits, key=lambda h: not str(h.get("title", "")).endswith("(Series)"))
        for hit in hits:
            title = str(hit.get("title") or "")
            if not _series_names_match(title, series_name):
                continue
            fields = _template_fields(_wikitext(title, http_get))
            if not fields or not _author_matches(fields.get("author", ""), authors):
                continue
            genres = [normalize_label(g) for g in re.split(r"[,;]", fields.get("genre(s)", "")) if g.strip()]
            return {"status": "found", "match": title, "explicit": fields.get("explicit_sex") or fields.get("explicit"),
                    "genres": [g for g in genres if g in LABEL_MAP], "via": "series"}
        for author in authors:
            if not str(author or "").strip():
                continue
            for link in _WIKILINK_RE.findall(_wikitext(author, http_get)):
                if _series_names_match(link, series_name):
                    return {"status": "found", "match": f"{author}: {link.strip()}", "explicit": None, "genres": [], "via": "author"}
    except Exception:
        return {**empty, "status": "failed"}
    return empty


def series_level_labels(pf: dict[str, Any], hl: dict[str, Any]) -> tuple[list[str], list[str], bool]:
    """(labels counted as full series support, evidence lines, pf_progression)."""
    labels: list[str] = []
    evidence: list[str] = []
    pf_progression = False
    if (pf or {}).get("status") == "found":
        if pf.get("category") == "LitRPG":
            labels.append("litrpg")
            evidence.append(f"progressionfantasy.co.uk: LitRPG & GameLit ({pf.get('title')})")
        elif pf.get("category") == "Progression":
            pf_progression = True
            evidence.append(f"progressionfantasy.co.uk: progression, needs corroboration ({pf.get('title')})")
    if (hl or {}).get("status") == "found":
        labels.append("haremlit")
        labels.extend(g for g in hl.get("genres") or [] if g not in labels)
        evidence.append(f"HaremLit wiki: {hl.get('match')}")
    return labels, evidence, pf_progression
