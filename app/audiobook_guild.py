"""Audiobook Guild (audiobookguild.com) for Metadata Forge.

A Shopify store selling a short list of self-published authors' audiobooks
(Eric Vall, Logan Jacobs, Michael-Scott Earle, ...), many of them missing from
Audible or listed there without a series. Its public storefront JSON gives each
book's author (the product vendor), series (the product type) and tags
("Narrator_...", "Genre_..."); the product page adds the runtime ("Duration:
9 Hours, 43 Minutes"). There is no ASIN, ISBN or release year: the product
dates are when the store listed the book.

Pacing: one shared 2 s minimum gap and the Goodreads breaker settings,
through the same pacer class. Measured on 2026-10-30: the store refuses the
odd request with 429 whatever the pace (3 of 100 at 2 s, 4 of 100 at 3 s), so
a refused request is tried again once after a wait before it counts.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

import httpx

from app.goodreads_shelves import GoodreadsPacer

STORE_URL = "https://audiobookguild.com"
_USER_AGENT = "Mozilla/5.0"
PAGE_SIZE = 250  # Shopify's products.json maximum
GAP_S = 2.0
RETRY_WAIT_S = 5.0

PACER = GoodreadsPacer(gap_s=GAP_S)

# The store's own vendor for gift cards and bundles, not an author.
_NOT_AUTHORS = {"audiobook guild"}

# The author list changes when the store adds an author, rarely: it is read
# from the store at most weekly and kept with the app's other caches.
AUTHORS_CACHE = Path(os.environ.get("REPORTS_DIR", "/app/reports")) / "audiobook-guild-authors.json"
AUTHORS_MAX_AGE_S = 7 * 24 * 3600

_AUTHORS_LOCK = threading.Lock()
_AUTHORS: list[str] | None = None


def _default_http_get(url: str, timeout: float) -> bytes:
    # httpx (the audible package's client), not urllib: the store answers
    # every urllib request with 429 "local_rate_limited", however paced.
    resp = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _fetch(url: str, pacer: GoodreadsPacer, http_get: Callable[[str, float], bytes],
           timeout: float, retries: int = 2) -> bytes | None:
    """One paced request, tried again after RETRY_WAIT_S when it fails (even
    paced, the store answers the odd request with 429), or None when every try
    failed (one failure for the breaker) or the breaker is open."""
    for attempt in range(max(1, retries)):
        if attempt:
            time.sleep(RETRY_WAIT_S)
        if not pacer.wait_turn():
            return None
        try:
            body = http_get(url, timeout)
        except (httpx.HTTPError, OSError, ValueError):
            continue
        pacer.record(True)
        return body
    pacer.record(False)
    return None


def _read_store_authors(pacer: GoodreadsPacer, http_get: Callable[[str, float], bytes],
                        timeout: float) -> list[str] | None:
    """Every product vendor in the store (four requests for its ~800 books),
    or None when the store can't be read."""
    authors: set[str] = set()
    page = 1
    while True:
        body = _fetch(f"{STORE_URL}/products.json?limit={PAGE_SIZE}&page={page}", pacer, http_get, timeout)
        if body is None:
            return None
        try:
            products = json.loads(body).get("products") or []
        except ValueError:
            return None
        authors |= {p["vendor"].strip() for p in products
                    if (p.get("vendor") or "").strip() and p["vendor"].strip().lower() not in _NOT_AUTHORS}
        if len(products) < PAGE_SIZE:
            return sorted(authors)
        page += 1


def store_authors(*, pacer: GoodreadsPacer | None = None, http_get: Callable[[str, float], bytes] | None = None,
                  timeout: float = 20, cache_path: Path | None = None,
                  clock: Callable[[], float] = time.time) -> list[str]:
    """The authors the store sells: the cached list while it is under a week
    old, else read from the store (the old list when that fails). Empty when
    neither is available."""
    global _AUTHORS
    pacer, cache_path = pacer or PACER, cache_path or AUTHORS_CACHE
    with _AUTHORS_LOCK:
        if _AUTHORS is not None:
            return _AUTHORS
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        authors = cached.get("authors") if isinstance(cached, dict) else None
        if not isinstance(authors, list) or clock() - float(cached.get("read_at") or 0) > AUTHORS_MAX_AGE_S:
            fresh = _read_store_authors(pacer, http_get or _default_http_get, timeout)
            if fresh:
                authors = fresh
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps({"read_at": clock(), "authors": fresh}), encoding="utf-8")
                except OSError:
                    pass
        if not isinstance(authors, list):
            return []  # not kept: the next book tries the store again
        _AUTHORS = authors
        return _AUTHORS


def is_store_author(author: str, **kwargs: Any) -> bool:
    """Is any of the book's authors one the store sells?"""
    from app.fixer.parsing import _authors_compatible  # lazy: keep this module light

    if not (author or "").strip():
        return False
    return any(_authors_compatible(author, name) is True for name in store_authors(**kwargs))


def _runtime_minutes(page: str) -> int | None:
    match = re.search(r"Duration:\s*</strong>\s*([^<]+)", page)
    if not match:
        return None
    text = match.group(1)
    hours = re.search(r"(\d+)\s*Hours?", text, re.IGNORECASE)
    minutes = re.search(r"(\d+)\s*Min", text, re.IGNORECASE)
    if not (hours or minutes):
        return None
    return int(hours.group(1) if hours else 0) * 60 + int(minutes.group(1) if minutes else 0)


def _description(body_html: str) -> str:
    """The product description without its "OVERVIEW:" heading or the
    "Looking for the ebook?" link to the author's own store."""
    text = re.sub(r"<h\d[^>]*>.*?</h\d>", " ", body_html or "", flags=re.IGNORECASE | re.DOTALL)
    paragraphs = re.split(r"</p>|<br\s*/?>", text, flags=re.IGNORECASE)
    kept = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p))).strip() for p in paragraphs]
    return "\n\n".join(p for p in kept if p and not p.lower().startswith("looking for the ebook"))


def _sequence(title: str, series: str) -> str:
    """The book number in the title ("Metal Mage 13", "King of Superheroes -
    Book 6"), read as the matcher reads titles; 1 for the title that is the
    series name alone, as the store titles a first book."""
    from app.fixer.parsing import extract_title_identity_number, normalize_for_match  # lazy: keep this module light

    number = extract_title_identity_number(title)
    if number:
        return number
    return "1" if series and normalize_for_match(title) == normalize_for_match(series) else ""


def _series(product: dict[str, Any]) -> str:
    tags = product.get("tags") or []
    tagged = [t[len("Series_"):].strip() for t in tags if isinstance(t, str) and t.startswith("Series_")]
    return (product.get("type") or product.get("product_type") or "").strip() or next(iter(tagged), "")


def series_names(products: list[dict[str, Any]]) -> dict[str, str]:
    """The store names some series with their books' shared subtitle:
    "Scholomance: The Devil's Academy" holds "Scholomance 6: The Devil's
    Academy", "Werepanther: Paranormal Hunter" holds "Werepanther 2". A series
    one of whose books is titled by the name before the colon, without the
    whole series name, is that name ("Tamer: King of Dinosaurs 11" keeps it)."""
    from app.fixer.parsing import normalize_for_match  # lazy: keep this module light

    names: dict[str, str] = {}
    for product in products:
        series = _series(product)
        name, _, subtitle = series.partition(": ")
        title = normalize_for_match(product.get("title") or "")
        if subtitle and normalize_for_match(series) not in title and title.startswith(normalize_for_match(name) + " "):
            names[series] = name.strip()
    return names


def book_match(product: dict[str, Any], runtime: int | None, series: str | None = None) -> dict[str, Any]:
    """A store product in the Audiobookshelf custom-provider match format
    app/fixer/search._abs_match_to_product reads, plus its runtime. `series`
    is its series name as series_names() reads it."""
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    def tagged(prefix: str) -> list[str]:
        return [t[len(prefix):].strip() for t in tags if t.startswith(prefix) and t[len(prefix):].strip()]

    title = (product.get("title") or "").strip()
    series = _series(product) if series is None else series
    image = product.get("image") or (product.get("featured_image") or {}).get("url") or ""
    return {
        "title": title,
        "author": (product.get("vendor") or "").strip(),
        "narrator": ", ".join(tagged("Narrator_")),
        # A first book is titled by the store's own series name, before or after cleanup.
        "series": [{"series": series, "sequence": _sequence(title, series) or _sequence(title, _series(product))}]
        if series else [],
        "description": _description(product.get("body") or product.get("body_html") or ""),
        "cover": image.split("?", 1)[0],
        "genres": tagged("Genre_"),
        "runtime_minutes": runtime,
    }


def search_books(
    title: str,
    author: str,
    *,
    series: str = "",
    number: str = "",
    pacer: GoodreadsPacer | None = None,
    limit: int = 3,
    http_get: Callable[[str, float], bytes] | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    """The store's search, then the product page (for its runtime) of each of
    the first `limit` results by `author`, only those numbered `number` when
    there are any: every book of a series can share the title searched for.
    "Series N" is searched first (the store returns 10 results, so "Dragon
    Emperor" alone can miss book 8), then `title`. A request that fails, a
    book page included, fails the whole search. Returns
    {"status": "found" | "not_found" | "failed", "matches": [book_match()]}."""
    from app.fixer.parsing import _authors_compatible, sequence_values_equal  # lazy: keep this module light

    pacer, http_get = pacer or PACER, http_get or _default_http_get
    queries = [f"{series} {number}"] if series.strip() and number else []
    queries = list(dict.fromkeys(q.strip() for q in queries + [title] if q.strip()))
    products: list[dict[str, Any]] = []
    numbered: list[dict[str, Any]] = []
    for query in queries:
        params = urllib.parse.urlencode({"q": query, "resources[type]": "product", "resources[limit]": 10})
        body = _fetch(f"{STORE_URL}/search/suggest.json?{params}", pacer, http_get, timeout)
        if body is None:
            return {"status": "failed", "matches": []}
        try:
            found = json.loads(body)["resources"]["results"]["products"]
        except (ValueError, KeyError, TypeError):
            return {"status": "failed", "matches": []}
        products = [p for p in found if not author or _authors_compatible(author, p.get("vendor") or "") is not False]
        numbered = [p for p in products if number and sequence_values_equal(_sequence(p.get("title") or "", _series(p)), number)]
        if numbered:
            break
    names = series_names(products)
    products = numbered or products  # its own number's books alone, when the store has them
    matches = []
    for product in products[:limit]:
        page = _fetch(STORE_URL + "/products/" + urllib.parse.quote(product.get("handle") or ""), pacer, http_get, timeout)
        if page is None:
            # Without its runtime the right book can lose to one the runtime rules out.
            return {"status": "failed", "matches": []}
        matches.append(book_match(product, _runtime_minutes(page.decode("utf-8", "replace")),
                                  names.get(_series(product), _series(product))))
    return {"status": "found" if matches else "not_found", "matches": matches}
