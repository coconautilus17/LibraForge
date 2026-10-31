"""Audiobook Guild (audiobookguild.com) for Metadata Forge.

A Shopify store selling a short list of self-published authors' audiobooks
(Eric Vall, Logan Jacobs, Michael-Scott Earle, ...), many of them missing from
Audible or listed there without a series. Its public storefront JSON gives each
book's author (the product vendor), series (the product type) and tags
("Narrator_...", "Genre_..."); the product page adds the runtime ("Duration:
9 Hours, 43 Minutes"). There is no ASIN, ISBN or release year: the product
dates are when the store listed the book.

The whole catalog (about 800 books, 1.3 MB) is kept locally and searched
there: four products.json requests a week, and a book page only for a
candidate's runtime, read once and kept with the catalog.

Pacing: one shared 2 s minimum gap and the Goodreads breaker settings,
through the same pacer class. Measured on 2026-10-30: the store refuses the
odd request with 429 whatever the pace (3 of 100 at 2 s, 4 of 100 at 3 s), so
a refused request is tried again once after a wait before it counts.
"""
from __future__ import annotations

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

# The catalog is read from the store at most weekly and kept with the app's
# other caches, with the runtimes read so far.
CATALOG_CACHE = Path(os.environ.get("REPORTS_DIR", "/app/reports")) / "audiobook-guild-catalog.json"
CATALOG_MAX_AGE_S = 7 * 24 * 3600

# A store book is a search result when the matcher's title evidence for the
# title searched, or for the series against its series, reaches this: a
# title search, not every book by the author (each costs a page read once).
MIN_RELEVANCE = 0.6

_CATALOG_LOCK = threading.Lock()
_CATALOG: dict[str, Any] | None = None


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


def _slim(product: dict[str, Any]) -> dict[str, Any]:
    """The products.json fields the matcher reads."""
    return {
        "title": (product.get("title") or "").strip(),
        "handle": product.get("handle") or "",
        "vendor": (product.get("vendor") or "").strip(),
        "product_type": (product.get("product_type") or "").strip(),
        "tags": product.get("tags") or [],
        "body_html": product.get("body_html") or "",
        "image": next(iter(product.get("images") or []), {}).get("src") or "",
        "updated_at": product.get("updated_at") or "",
    }


def _read_store_catalog(pacer: GoodreadsPacer, http_get: Callable[[str, float], bytes],
                        timeout: float) -> list[dict[str, Any]] | None:
    """Every book in the store (four requests for its ~800), or None when the
    store can't be read."""
    products: list[dict[str, Any]] = []
    page = 1
    while True:
        body = _fetch(f"{STORE_URL}/products.json?limit={PAGE_SIZE}&page={page}", pacer, http_get, timeout)
        if body is None:
            return None
        try:
            chunk = json.loads(body).get("products") or []
        except ValueError:
            return None
        products += [_slim(p) for p in chunk
                     if p.get("handle") and (p.get("vendor") or "").strip().lower() not in _NOT_AUTHORS]
        if len(chunk) < PAGE_SIZE:
            return products
        page += 1


def _save_catalog(catalog: dict[str, Any], cache_path: Path) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_name(cache_path.name + ".tmp")
        temp.write_text(json.dumps(catalog), encoding="utf-8")
        os.replace(temp, cache_path)
    except OSError:
        pass


def store_catalog(*, pacer: GoodreadsPacer | None = None, http_get: Callable[[str, float], bytes] | None = None,
                  timeout: float = 20, cache_path: Path | None = None,
                  clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """{"read_at", "products": [_slim()], "runtimes": {handle: {"updated_at",
    "minutes"}}}: the cached catalog while it is under a week old, else read
    from the store (the old one when that fails), keeping the runtime of each
    book the store hasn't changed since. No products when neither is
    available."""
    global _CATALOG
    pacer, cache_path = pacer or PACER, cache_path or CATALOG_CACHE
    with _CATALOG_LOCK:
        if _CATALOG is not None:
            return _CATALOG
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        if not isinstance(cached, dict) or not isinstance(cached.get("products"), list):
            cached = {}
        if not cached or clock() - float(cached.get("read_at") or 0) > CATALOG_MAX_AGE_S:
            fresh = _read_store_catalog(pacer, http_get or _default_http_get, timeout)
            if fresh:
                updated = {p["handle"]: p["updated_at"] for p in fresh}
                runtimes = {handle: r for handle, r in (cached.get("runtimes") or {}).items()
                            if isinstance(r, dict) and updated.get(handle) == r.get("updated_at")}
                cached = {"read_at": clock(), "products": fresh, "runtimes": runtimes}
                _save_catalog(cached, cache_path)
        if not cached:
            return {"products": [], "runtimes": {}}  # not kept: the next book tries the store again
        cached.setdefault("runtimes", {})
        _CATALOG = cached
        return _CATALOG


def store_authors(**kwargs: Any) -> list[str]:
    """The authors the store sells."""
    return sorted({p["vendor"] for p in store_catalog(**kwargs)["products"] if p.get("vendor")})


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
    from app.fixer.parsing import clean_text  # lazy: keep this module light

    text = re.sub(r"<h\d[^>]*>.*?</h\d>", " ", body_html or "", flags=re.IGNORECASE | re.DOTALL)
    paragraphs = re.split(r"</p>|<br\s*/?>", text, flags=re.IGNORECASE)
    kept = [clean_text(p) for p in paragraphs]
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
    return (product.get("product_type") or "").strip() or next(iter(tagged), "")


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
    image = product.get("image") or ""
    return {
        "title": title,
        "author": (product.get("vendor") or "").strip(),
        "narrator": ", ".join(tagged("Narrator_")),
        # A first book is titled by the store's own series name, before or after cleanup.
        "series": [{"series": series, "sequence": _sequence(title, series) or _sequence(title, _series(product))}]
        if series else [],
        "description": _description(product.get("body_html") or ""),
        "cover": image.split("?", 1)[0],
        "genres": tagged("Genre_"),
        "runtime_minutes": runtime,
    }


_UNREAD = object()


def _runtime(product: dict[str, Any], catalog: dict[str, Any], pacer: GoodreadsPacer,
             http_get: Callable[[str, float], bytes], timeout: float, cache_path: Path) -> Any:
    """The book's runtime from its page, read once while the store leaves the
    book unchanged (None for a page without one), or _UNREAD."""
    handle = product["handle"]
    kept = catalog["runtimes"].get(handle)
    if isinstance(kept, dict) and kept.get("updated_at") == product.get("updated_at"):
        return kept.get("minutes")
    page = _fetch(STORE_URL + "/products/" + urllib.parse.quote(handle), pacer, http_get, timeout)
    if page is None:
        return _UNREAD
    minutes = _runtime_minutes(page.decode("utf-8", "replace"))
    with _CATALOG_LOCK:
        catalog["runtimes"][handle] = {"updated_at": product.get("updated_at"), "minutes": minutes}
        _save_catalog(catalog, cache_path)
    return minutes


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
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """The `author`'s books in the catalog whose title is close to `title` or
    whose series is close to `series`, only those numbered `number` when there
    are any (every book of a series can share the title searched for), the
    closest first, with the runtime of the first `limit`. A request that
    fails, the catalog or a book page, fails the whole search: without its
    runtime the right book can lose to one the runtime rules out. Returns
    {"status": "found" | "not_found" | "failed", "matches": [book_match()]}."""
    from app.fixer.parsing import _authors_compatible, sequence_values_equal  # lazy: keep this module light
    from app.fixer.scoring import title_evidence_score

    pacer, http_get, cache_path = pacer or PACER, http_get or _default_http_get, cache_path or CATALOG_CACHE
    catalog = store_catalog(pacer=pacer, http_get=http_get, timeout=timeout, cache_path=cache_path)
    if not catalog["products"]:
        return {"status": "failed", "matches": []}
    books = [p for p in catalog["products"] if _authors_compatible(author, p["vendor"]) is True]
    names = series_names(books)

    def relevance(product: dict[str, Any]) -> float:
        evidence = title_evidence_score({"title": title, "author": author}, {"title": product["title"]})
        if series.strip():
            name = names.get(_series(product), _series(product))
            evidence = max(evidence, title_evidence_score({"title": series, "author": author}, {"title": name}))
        return evidence

    scored = sorted(((relevance(p), p) for p in books), key=lambda item: -item[0])
    found = [p for score, p in scored if score >= MIN_RELEVANCE]
    numbered = [p for p in found if number and sequence_values_equal(_sequence(p["title"], _series(p)), number)]
    matches = []
    for product in (numbered or found)[:limit]:  # its own number's books alone, when the store has them
        runtime = _runtime(product, catalog, pacer, http_get, timeout, cache_path)
        if runtime is _UNREAD:
            return {"status": "failed", "matches": []}
        matches.append(book_match(product, runtime, names.get(_series(product), _series(product))))
    return {"status": "found" if matches else "not_found", "matches": matches}
