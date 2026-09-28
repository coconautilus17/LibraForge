"""Direct Goodreads shelves for Enrichment Forge.

Why not abs-tract: its goodreads/genre.go filters Goodreads' popular shelves
through a ~48-entry allow-list (no litrpg, progression-fantasy, harem,
cultivation, urban-fantasy...) and keeps only the first 3, dropping the vote
counts -- so it can never supply the genres Audible lacks. The same public XML
endpoint abs-tract uses returns the top 100 reader shelves WITH vote counts,
so Enrichment Forge reads it directly. Only Enrichment Forge uses this bypass;
Meta Forge keeps using abs-tract.

Pacing is Meta Forge's (app/fixer/search.py): one shared 0.5 s minimum gap
between any two requests, and a breaker that opens after 2 consecutive
failures for 180 s (measured Goodreads block recovery is ~90-105 s of quiet;
see the abs-tract blocking notes). One direct call is one Goodreads request,
where one abs-tract search is several, so this is gentler than Meta Forge.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable

# Public read-only key embedded in abs-tract (goodreads/goodreads.go,
# DefaultAPIKey: "Read only API key kindly provided by LazyLibrarian").
GOODREADS_PUBLIC_API_KEY = "ckvsiSDsuqh7omh74ZZ6Q"
GOODREADS_BOOK_TITLE_URL = "https://www.goodreads.com/book/title.xml"
_USER_AGENT = "Mozilla/5.0"  # some upstreams reject descriptive UA strings

GAP_S = 0.5
FAIL_THRESHOLD = 2
COOLDOWN_S = 180.0


class GoodreadsPacer:
    """Global pacing + circuit breaker shared by every Goodreads call."""

    def __init__(
        self,
        gap_s: float = GAP_S,
        fail_threshold: int = FAIL_THRESHOLD,
        cooldown_s: float = COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.gap_s = gap_s
        self.fail_threshold = fail_threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last = None  # type: float | None
        self._fails = 0
        self._open_until = 0.0
        self.trips = 0

    @property
    def is_open(self) -> bool:
        return self._clock() < self._open_until

    def wait_turn(self) -> bool:
        """Block until this caller may send one request. False (no wait) while
        the breaker is open -- the caller skips Goodreads for that book."""
        with self._lock:
            now = self._clock()
            if now < self._open_until:
                return False
            if self._last is not None:
                gap = self._last + self.gap_s - now
                if gap > 0:
                    self._sleep(gap)
            self._last = self._clock()
            return True

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._fails = 0
                return
            self._fails += 1
            if self._fails >= self.fail_threshold and self._clock() >= self._open_until:
                self._open_until = self._clock() + self.cooldown_s
                self.trips += 1
                self._fails = 0


_STOPWORDS = {"the", "a", "an", "of", "and", "book"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower())) - _STOPWORDS


def clean_query_title(title: str) -> str:
    """Strip library-naming noise before searching: 'Series - Book 001 - X',
    trailing (...)/[...] groups, ', Book Six', a trailing bare number."""
    t = (title or "").strip()
    t = re.sub(r"^.*? - Book \d+(\.\d+)? - ", "", t)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", t).strip()
    t = re.sub(r",?\s+Book\s+\w+$", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s+\d+(\.\d+)?$", "", t).strip()
    if len(t) > 60 and ": " in t:
        t = t.split(": ", 1)[0].strip()
    return t or (title or "").strip()


def _default_http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_book_shelves(
    title: str,
    author: str,
    *,
    pacer: GoodreadsPacer,
    http_get: Callable[[str, float], bytes] | None = None,
    timeout: float = 20,
    book: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Look one book up on Goodreads. Returns {"status": "found" | "not_found" |
    "failed" | "skipped", "title": str | None, "shelves": [(name, count), ...]}.

    not_found (404, no <book>, or a different book) is a normal answer and never
    counts against the breaker; failed (timeouts, 5xx, garbage) does; skipped
    means the breaker is open and no request was sent.
    """
    http_get = http_get or _default_http_get
    wanted = clean_query_title(title)
    if not pacer.wait_turn():
        return {"status": "skipped", "title": None, "shelves": []}
    url = GOODREADS_BOOK_TITLE_URL + "?" + urllib.parse.urlencode(
        {"title": wanted, "author": author or "", "key": GOODREADS_PUBLIC_API_KEY})
    try:
        body = http_get(url, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            pacer.record(True)
            return {"status": "not_found", "title": None, "shelves": []}
        pacer.record(False)
        return {"status": "failed", "title": None, "shelves": []}
    except Exception:
        pacer.record(False)
        return {"status": "failed", "title": None, "shelves": []}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        pacer.record(False)
        return {"status": "failed", "title": None, "shelves": []}
    pacer.record(True)
    book_el = root.find("book")
    if book_el is None:
        return {"status": "not_found", "title": None, "shelves": []}
    found_title = (book_el.findtext("title") or "").strip()
    found_authors = [a.strip() for a in (n.text or "" for n in book_el.findall("authors/author/name")) if a.strip()]
    # Same book? Metadata Forge's own decision for sparse Goodreads results.
    from app.source_matching import best_candidate, provider_product  # lazy: it imports this module

    library_book = book or {"title": title, "author": author}
    product = provider_product({"title": found_title, "author": ", ".join(found_authors)}, "goodreads")
    if best_candidate(library_book, [(product, True)]) is None:
        return {"status": "not_found", "title": found_title, "shelves": []}
    shelves = []
    for shelf in book_el.findall("popular_shelves/shelf"):
        name = (shelf.get("name") or "").strip().lower()
        try:
            count = int(shelf.get("count") or 0)
        except ValueError:
            count = 0
        if name:
            shelves.append((name, count))
    return {"status": "found", "title": found_title, "shelves": shelves}


# Shelf -> genre, with thresholds relative to the book's top broad-genre shelf.
# Values from the 2026-09-28 full-library prototype (86% benchmark recall).
_NICHE = {
    "litrpg": "LitRPG", "lit-rpg": "LitRPG", "gamelit": "GameLit",
    "progression-fantasy": "Progression Fantasy", "progression": "Progression Fantasy",
    "cultivation": "Cultivation", "xianxia": "Cultivation", "wuxia": "Cultivation",
    "harem": "Harem", "haremlit": "Harem", "harem-lit": "Harem",
    "isekai": "Portal Fantasy", "portal-fantasy": "Portal Fantasy", "dungeon-core": "Dungeon Core",
    "urban-fantasy": "Urban Fantasy", "epic-fantasy": "Epic Fantasy", "high-fantasy": "Epic Fantasy",
    "space-opera": "Space Opera", "military-science-fiction": "Military Science Fiction",
    "military-sci-fi": "Military Science Fiction", "cyberpunk": "Cyberpunk", "post-apocalyptic": "Post-Apocalyptic",
    "dystopian": "Dystopian", "dystopia": "Dystopian", "cozy-mystery": "Cozy Mystery",
    "police-procedural": "Police Procedural", "legal-thriller": "Legal Thriller", "espionage": "Espionage",
    "spy": "Espionage", "time-travel": "Time Travel", "superhero": "Superhero", "superheroes": "Superhero",
    # Measured: real dragon books 12-120% of the top genre shelf, noise <= 1.3%.
    "dragons": "Dragons", "dragon": "Dragons", "dragon-riders": "Dragons", "dragon-rider": "Dragons",
}
_AUDIENCE = {
    "young-adult": "Young Adult", "ya": "Young Adult", "ya-fantasy": "Young Adult", "teen": "Young Adult",
    "middle-grade": "Children's", "childrens": "Children's", "children": "Children's", "kids": "Children's",
}
_BROAD = {
    "fantasy": "Fantasy", "sci-fi": "Science Fiction", "science-fiction": "Science Fiction", "scifi": "Science Fiction",
    "horror": "Horror", "thriller": "Thriller", "thrillers": "Thriller", "mystery": "Mystery", "mysteries": "Mystery",
    "crime": "Crime", "romance": "Romance", "humor": "Humor", "humour": "Humor", "comedy": "Humor",
    "historical-fiction": "Historical Fiction", "classics": "Classics", "classic": "Classics",
    "literary-fiction": "Literary Fiction", "non-fiction": "Non-Fiction", "nonfiction": "Non-Fiction",
    "history": "History", "biography": "Biography", "memoir": "Biography",
}
# "adult"/"adult-fiction" mean an adult (not YA) audience, not sexual content:
# Dune carries adult-fiction x261, and 220 books in one real library had it.
_EXPLICIT = {"erotica", "smut", "nsfw", "explicit", "erotic", "spicy", "steamy", "porn", "explicit-content"}
EXPLICIT_SHARE, EXPLICIT_MIN_VOTES = 0.05, 3
NICHE_SHARE, AUDIENCE_SHARE, BROAD_SHARE, NICHE_MIN_VOTES = 0.05, 0.10, 0.15, 3


def _top_broad(shelves: list[tuple[str, int]]) -> int:
    return max([c for n, c in shelves if n in _BROAD] + [1])


def shelves_to_genres(shelves: list[tuple[str, int]]) -> list[str]:
    """Genres readers actually agree on, in shelf order, deduped."""
    top = _top_broad(shelves)
    out: list[str] = []
    for name, count in shelves:
        genre = None
        if name in _NICHE and count >= NICHE_MIN_VOTES and count >= NICHE_SHARE * top:
            genre = _NICHE[name]
        elif name in _AUDIENCE and count >= NICHE_MIN_VOTES and count >= AUDIENCE_SHARE * top:
            genre = _AUDIENCE[name]
        elif name in _BROAD and count >= BROAD_SHARE * top:
            genre = _BROAD[name]
        if genre and genre not in out:
            out.append(genre)
    return out


def shelves_explicit_evidence(shelves: list[tuple[str, int]]) -> dict[str, Any]:
    """Reader shelving as erotica/smut/nsfw etc.: total votes and their share of
    the top genre shelf. Evidence for the user to judge, never a verdict."""
    votes = sum(c for n, c in shelves if n in _EXPLICIT)
    share = round(votes / _top_broad(shelves), 3) if shelves else 0.0
    # "significant": enough readers relative to the book's top genre shelf that
    # it isn't a handful of stray shelvings on a very popular book.
    return {"votes": votes, "share": share, "significant": votes >= EXPLICIT_MIN_VOTES and share >= EXPLICIT_SHARE}
