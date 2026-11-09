"""Audible / ABS search helpers and per-provider HTTP clients.

All functions here are either pure transformations or call only external HTTP
services (Audible API, ABS, abs-agg, abs-tract). They do not touch the local
filesystem and have no dependency on the fixer script itself.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable
from itertools import islice

import audible
import httpx

from app import audiobook_guild
from app.debug_trace import trace, CHOOSE
from app.fixer.scoring import clean_provider_genres
from app.goodreads_shelves import GoodreadsPacer, search_books as goodreads_search_books
from app.publisher_policy import special_provider_for

# ---------------------------------------------------------------------------
# Audible API helpers
# ---------------------------------------------------------------------------

RESPONSE_GROUPS = ",".join(
    [
        "contributors",
        "media",
        "product_attrs",
        "product_desc",
        "product_extended_attrs",
        "series",
        # Audible's store categories: the matched book's genres.
        "category_ladders",
    ]
)

# Enrichment Forge also needs rating (is_adult_product). Kept out of
# RESPONSE_GROUPS so the high-volume batch matcher calls stay lighter.
ENRICHMENT_RESPONSE_GROUPS = RESPONSE_GROUPS + ",rating"


def audible_search(
    client: audible.Client, query: str, limit: int, response_groups: str = RESPONSE_GROUPS,
    title: str = "", author: str = "",
) -> list[dict]:
    """Keyword search, or with title (and author) Audible's structured search,
    which finds listings keyword search doesn't return (Postwar, Tony Judt)."""
    terms = {"title": title, "author": author} if title else {"keywords": query}
    response = client.get(
        "catalog/products",
        params={
            **{k: v for k, v in terms.items() if v},
            "num_results": limit,
            "response_groups": response_groups,
        },
    )

    return response.get("products", []) or []


def audible_lookup_by_asin(
    client: audible.Client, asin: str, response_groups: str = RESPONSE_GROUPS
) -> dict | None:
    """Look up a product by ASIN.

    Tries catalog/products/{asin} (direct) first. If that returns nothing,
    falls back to a keyword search for the ASIN and returns the first result
    whose ASIN matches exactly. Some ASINs only respond to one of the two
    endpoints, so both are needed for complete coverage.
    """
    asin_upper = asin.strip().upper()
    try:
        response = client.get(
            f"catalog/products/{asin_upper}",
            params={"response_groups": response_groups},
        )
        product = response.get("product") or None
        if product:
            return product
    except Exception:
        pass
    # Fallback: keyword search -- some ASINs surface here but not via direct lookup
    try:
        results = audible_search(client, asin_upper, 5, response_groups)
        for p in results:
            if str(p.get("asin", "") or "").upper() == asin_upper:
                return p
    except Exception:
        pass
    return None


# A series' members, by series ASIN, for the run: books of one series share it.
_SERIES_MEMBERS: dict[str, list[str]] = {}
_SERIES_MEMBERS_LOCK = threading.Lock()


def audible_series_members(client: audible.Client, series_asin: str) -> list[str]:
    """The ASINs of a series' books, from the series' own listing.

    Audible's search leaves out listings that can't be sold where the request
    comes from, but a lookup by ASIN doesn't, and a series' listing names every
    member (Riyria Revelations B0081WUWRK lists Theft of Swords, which no
    search returns from outside the US)."""
    series_asin = series_asin.strip().upper()
    with _SERIES_MEMBERS_LOCK:
        if series_asin in _SERIES_MEMBERS:
            return _SERIES_MEMBERS[series_asin]
    try:
        response = client.get(f"catalog/products/{series_asin}", params={"response_groups": "relationships"})
    except Exception:
        return []
    members = [
        str(rel["asin"]).upper()
        for rel in ((response or {}).get("product") or {}).get("relationships") or []
        if rel.get("asin") and rel.get("relationship_type") == "series" and rel.get("relationship_to_product") == "child"
    ]
    with _SERIES_MEMBERS_LOCK:
        _SERIES_MEMBERS[series_asin] = members
    return members


def audible_lookup_many(
    client: audible.Client, asins: list[str], response_groups: str = RESPONSE_GROUPS
) -> list[dict]:
    """Full listings for several ASINs, 50 to a request (catalog/products?asins=),
    which like a single lookup isn't limited by the requester's country."""
    products: list[dict] = []
    for start in range(0, len(asins), 50):
        batch = asins[start:start + 50]
        try:
            response = client.get(
                "catalog/products",
                params={"asins": ",".join(batch), "num_results": len(batch), "response_groups": response_groups},
            )
        except Exception:
            continue
        products += (response or {}).get("products") or []
    return products


class AsinLookahead:
    """A run's ASIN lookups, answered up to 50 to a request.

    The first lookup a book needs also asks for the ASINs of the books after it
    in the run (catalog/products?asins=, the same listing a single lookup
    returns), so their lookups are answered when they get there. A run never
    sends more requests than one per looked-up book, as before; an ASIN the
    batch leaves out is looked up on its own (audible_lookup_by_asin)."""

    def __init__(self, upcoming: Callable[[int], Iterable[str]], batch_size: int = 50):
        self._upcoming = upcoming  # index -> the ASINs of the books after it
        self._batch_size = batch_size
        self._found: dict[str, dict] = {}
        self._pending: dict[str, threading.Event] = {}
        self._asked: set[str] = set()
        self._lock = threading.Lock()

    def lookup(self, client: audible.Client, asin: str, index: int) -> dict | None:
        asin = asin.strip().upper()
        with self._lock:
            started = asin in self._asked
        # The next books' ASINs are read outside the lock: a sidecar read is file I/O.
        ahead = [] if started else [a.strip().upper() for a in islice(self._upcoming(index), 4 * self._batch_size) if a]
        batch: list[str] = []
        with self._lock:
            if asin not in self._asked:
                batch = [asin] + [a for a in dict.fromkeys(ahead) if a != asin and a not in self._asked]
                batch = batch[:self._batch_size]
                event = threading.Event()
                for a in batch:
                    self._asked.add(a)
                    self._pending[a] = event
            else:
                event = self._pending.get(asin)
        if batch:
            products: list[dict] = []
            try:
                products = audible_lookup_many(client, batch)
            finally:
                with self._lock:
                    for product in products:
                        key = str(product.get("asin") or "").upper()
                        if key in batch:
                            self._found[key] = product
                    for a in batch:
                        self._pending.pop(a, None)
                event.set()
        elif event is not None:
            event.wait(timeout=60)
        with self._lock:
            product = self._found.get(asin)
        return product or audible_lookup_by_asin(client, asin)


def audible_lookup_chapters(client: audible.Client, asin: str) -> list[dict] | None:
    """Return a book's chapter list from Audible's dedicated chapters endpoint.

    Distinct from catalog/products (RESPONSE_GROUPS) -- this hits
    content/{asin}/metadata?response_groups=chapter_info, a separate Audible
    request the normal match flow never makes. General-purpose lookup, not
    tied to any one caller: suitable for a one-off or small-batch call (a
    single book's chapter fetch, an export, etc). Do not call it from the
    batch matcher's per-book hot loop or any other high-volume path.

    Each returned entry is {"title": str, "start_ms": int, "length_ms": int}.
    Returns None -- never guesses -- when the ASIN is empty, Audible's
    chapter data for it is not marked accurate, or the request fails.
    """
    asin_upper = asin.strip().upper()
    if not asin_upper:
        return None
    try:
        response = client.get(
            f"content/{asin_upper}/metadata",
            params={"response_groups": "chapter_info"},
        )
    except Exception:
        return None
    chapter_info = (response.get("content_metadata") or {}).get("chapter_info") or {}
    if chapter_info.get("is_accurate") is not True:
        return None
    raw_chapters = chapter_info.get("chapters")
    if not isinstance(raw_chapters, list):
        return None
    return [
        {
            "title": chapter.get("title") or "",
            "start_ms": int(chapter.get("start_offset_ms") or 0),
            "length_ms": int(chapter.get("length_ms") or 0),
        }
        for chapter in raw_chapters
    ]


# ---------------------------------------------------------------------------
# ABS / abs-agg / abs-tract search helpers
# ---------------------------------------------------------------------------

def abs_search(title: str, author: str, provider: str, abs_url: str, abs_api_key: str, limit: int) -> list[dict]:
    """Search Audiobookshelf's metadata API and return results normalised to Audible product shape."""
    import urllib.error as _urlerror
    import urllib.parse as _urlparse
    import urllib.request as _urlrequest

    params: dict[str, str] = {"title": title, "provider": provider}
    if author:
        params["author"] = author
    url = f"{abs_url.rstrip('/')}/api/search/books?{_urlparse.urlencode(params)}"
    req = _urlrequest.Request(url, headers={"Authorization": f"Bearer {abs_api_key}", "Accept": "application/json"})
    try:
        with _urlrequest.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (_urlerror.URLError, OSError) as exc:
        print(f"  WARNING: ABS search failed: {exc}")
        return []
    except Exception as exc:
        print(f"  WARNING: ABS search error: {exc}")
        return []

    products = []
    for match in (raw if isinstance(raw, list) else [])[:limit]:
        series_raw = match.get("series") or []
        if isinstance(series_raw, list) and series_raw:
            series_name = series_raw[0].get("series", "")
            sequence = str(series_raw[0].get("sequence", "") or "")
        elif isinstance(series_raw, str):
            series_name, sequence = series_raw, ""
        else:
            series_name, sequence = "", ""

        duration_min = match.get("duration")
        duration_sec = round(float(duration_min) * 60) if duration_min else None

        # Normalise to Audible product shape so existing scoring/metadata functions work unchanged.
        products.append({
            "asin": match.get("asin", ""),
            "title": match.get("title", "") or "",
            "subtitle": match.get("subtitle", "") or "",
            "authors": [{"name": match.get("author", "") or ""}],
            "narrators": [{"name": match.get("narrator", "") or ""}],
            "series": [{"title": series_name, "sequence": sequence}] if series_name else [],
            "publisher_summary": match.get("description", "") or "",
            "product_images": {"500": match.get("cover", "") or ""},
            "runtime_length_min": duration_min,
            "runtime_length_sec": duration_sec,
            "release_date": str(match.get("publishedYear", "") or ""),
            # Read by the language penalty and the publisher tiebreak, which
            # were inactive in ABS mode while these were dropped.
            "language": match.get("language", "") or "",
            "publisher_name": match.get("publisher", "") or "",
            "_abs_provider": provider,
            "_abs_isbn": match.get("isbn", "") or "",
            "_abs_genres": clean_provider_genres(match.get("genres") or []),
        })
    return products


def abs_lookup_by_asin(asin: str, provider: str, abs_url: str, abs_api_key: str) -> dict | None:
    """Look up one product by ASIN through ABS (it treats an ASIN title as a direct lookup).

    Only an exact ASIN match counts, so a provider that ignores ASINs returns None.
    """
    asin_upper = asin.strip().upper()
    for product in abs_search(asin_upper, "", provider, abs_url, abs_api_key, 5):
        if str(product.get("asin", "") or "").upper() == asin_upper:
            return product
    return None


def abs_agg_search(
    title: str,
    author: str,
    provider: str,
    abs_agg_url: str,
    limit: int,
    existing_asin: str = "",
) -> list[dict]:
    """Search an abs-agg provider endpoint and normalize results to Audible product shape.

    Calls /{provider}/search?title=...&author=...&limit=... on the abs-agg service.
    The existing_asin is preserved in the result so tag writes don't clear embedded ASINs.
    """
    import urllib.error as _urlerror
    import urllib.parse as _urlparse
    import urllib.request as _urlrequest

    params: dict[str, str] = {"title": title, "limit": str(limit)}
    if author:
        params["author"] = author
    url = f"{abs_agg_url.rstrip('/')}/{provider}/search?{_urlparse.urlencode(params)}"
    try:
        req = _urlrequest.Request(url, headers={"Accept": "application/json"})
        with _urlrequest.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (_urlerror.URLError, OSError) as exc:
        return []
    except Exception:
        return []

    products = []
    for match in (raw.get("matches", []) or [])[:limit]:
        # Preserve the embedded ASIN so we don't accidentally clear it on write.
        asin = match.get("asin", "") or existing_asin
        products.append(_abs_match_to_product(match, provider, asin))
    return products


def _abs_match_to_product(match: dict, provider: str, asin: str) -> dict:
    """Normalize one ABS-custom-provider ``match`` to the Audible product shape.

    Shared by abs-agg and abs-tract (both speak the Audiobookshelf custom
    metadata provider format). ``asin`` is supplied by the caller so each source
    can decide whether to trust the match's own ASIN.
    """
    series_raw = match.get("series") or []
    if isinstance(series_raw, list) and series_raw:
        series_name = series_raw[0].get("series", "")
        sequence = str(series_raw[0].get("sequence", "") or "")
    else:
        series_name, sequence = "", ""

    return {
        "asin": asin,
        "title": match.get("title", "") or "",
        "subtitle": match.get("subtitle", "") or "",
        "authors": [{"name": match.get("author", "") or ""}],
        "narrators": [{"name": match.get("narrator", "") or ""}],
        "series": [{"title": series_name, "sequence": sequence}] if series_name else [],
        "publisher_summary": match.get("description", "") or "",
        "product_images": {"500": match.get("cover", "") or ""},
        "runtime_length_min": None,  # these sources do not return runtime
        "release_date": str(match.get("publishedYear", "") or ""),
        # Several providers (LibriVox especially -- public-domain works are
        # commonly read in many languages with no language filter available)
        # genuinely return a real language value. score_product_for_metadata's
        # language penalty already reads product.get("language") generically
        # for any source; it was previously always inactive here since this
        # key never existed, not because the check doesn't apply.
        "language": match.get("language", "") or "",
        "_abs_provider": provider,
        "_abs_isbn": match.get("isbn", "") or "",
        "_abs_genres": clean_provider_genres(match.get("genres") or []),
    }


# ---------------------------------------------------------------------------
# AudioSilo community database
# ---------------------------------------------------------------------------

AUDIOSILO_DEFAULT_URL = "https://meta.audiosilo.app"
# Shared by every AudioSilo call (the matcher fallback and Enrichment Forge).
# Measured in the 2026-09-27 full-library run: AudioSilo showed no limiting at
# ~100 req/min.
AUDIOSILO_PACER = GoodreadsPacer(gap_s=0.35, fail_threshold=3, cooldown_s=60)


def audiosilo_product(match: dict) -> dict:
    """An AudioSilo /abs/search match as the Audible-shaped product, with the
    runtime (minutes) and publisher it returns, so the matcher can judge it
    like an Audible listing."""
    product = _abs_match_to_product(match, "audiosilo", str(match.get("asin") or "").upper())
    if match.get("duration"):
        product["runtime_length_min"] = match["duration"]
    product["publisher_name"] = match.get("publisher", "") or ""
    return product


def audiosilo_search(title: str, author: str, base_url: str, limit: int, log: list[str] | None = None) -> list[dict]:
    """Search AudioSilo's community database (meta.audiosilo.app or a self-hosted
    copy) through its Audiobookshelf provider endpoint: one result per
    recording, with its narrator and runtime. While the pacer's breaker is open
    after failures, nothing is sent."""
    import urllib.parse as _urlparse
    import urllib.request as _urlrequest

    if not AUDIOSILO_PACER.wait_turn():
        if log is not None:
            log.append("  AudioSilo paused after failed requests -> skipped")
        return []
    params = {"query": title}
    if author:
        params["author"] = author
    url = f"{base_url.rstrip('/')}/abs/search?{_urlparse.urlencode(params)}"
    try:
        req = _urlrequest.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        with _urlrequest.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        AUDIOSILO_PACER.record(False)
        if log is not None:
            log.append(f"  AudioSilo search failed: {exc}")
        return []
    AUDIOSILO_PACER.record(True)
    return [audiosilo_product(match) for match in (raw.get("matches") or [])[:limit]]


# ---------------------------------------------------------------------------
# abs-tract circuit breaker + throttle
# ---------------------------------------------------------------------------

# abs-tract scrapes Goodreads/Amazon live. Under sustained mixed load the
# upstream sites start blocking, after which every request hangs until timeout.
# A naive per-call retry then makes a long run pathologically slow (every book
# burns retries * timeout). This circuit breaker trips after a few consecutive
# persistent failures and short-circuits further calls for a cooldown, so one
# upstream block doesn't tax the rest of the run.
_ABS_TRACT_BREAKER_LOCK = threading.Lock()
_ABS_TRACT_BREAKER = {
    "consecutive_failures": 0,
    "open_until": 0.0,
    "logged_open": False,
    # Unlike logged_open/consecutive_failures, this never resets on success --
    # it answers "did this run ever hit the breaker", for end-of-run reporting.
    "ever_opened": False,
}
_ABS_TRACT_BREAKER_THRESHOLD = 2      # consecutive persistent failures before tripping
_ABS_TRACT_BREAKER_COOLDOWN = 180.0   # seconds to stay open; measured recovery is ~90-105s

# Throttle: enforce a minimum gap between any two abs-tract requests so
# sustained parallel batches don't hit upstream rate limits. With 5 workers
# all needing Goodreads simultaneously the burst would otherwise be 5x.
_ABS_TRACT_THROTTLE_LOCK = threading.Lock()
_ABS_TRACT_LAST_REQUEST_TIME: list[float] = [0.0]
_ABS_TRACT_THROTTLE_DELAY = 0.5  # seconds between requests (global, across all workers)
# A Goodreads search is up to 4 requests (search + 3 book pages): its pacer
# keeps the same 0.5 s gap between them, and the breaker above decides.
_GOODREADS_PACER = GoodreadsPacer(fail_threshold=sys.maxsize)


def _abs_tract_breaker_is_open() -> bool:
    with _ABS_TRACT_BREAKER_LOCK:
        return time.time() < _ABS_TRACT_BREAKER["open_until"]


def abs_tract_breaker_ever_opened() -> bool:
    """Whether the breaker has tripped at least once since it was last reset.

    Unlike _abs_tract_breaker_is_open(), this stays True for the rest of the
    run even after the cooldown elapses and calls start succeeding again, so
    an end-of-run summary can report "Goodreads was rate-limited during this
    run" instead of only knowing about it while the breaker is still open.
    """
    with _ABS_TRACT_BREAKER_LOCK:
        return bool(_ABS_TRACT_BREAKER["ever_opened"])


def _abs_tract_breaker_record(success: bool) -> None:
    with _ABS_TRACT_BREAKER_LOCK:
        if success:
            _ABS_TRACT_BREAKER["consecutive_failures"] = 0
            _ABS_TRACT_BREAKER["logged_open"] = False
            return
        _ABS_TRACT_BREAKER["consecutive_failures"] += 1
        if _ABS_TRACT_BREAKER["consecutive_failures"] >= _ABS_TRACT_BREAKER_THRESHOLD:
            _ABS_TRACT_BREAKER["open_until"] = time.time() + _ABS_TRACT_BREAKER_COOLDOWN
            _ABS_TRACT_BREAKER["ever_opened"] = True


def _abs_tract_throttle() -> None:
    """Block until at least _ABS_TRACT_THROTTLE_DELAY seconds have passed since
    the last request.  Serializes across all worker threads so 5 concurrent
    workers don't fire simultaneously and trigger upstream rate limits.
    """
    with _ABS_TRACT_THROTTLE_LOCK:
        now = time.time()
        gap = _ABS_TRACT_LAST_REQUEST_TIME[0] + _ABS_TRACT_THROTTLE_DELAY - now
        if gap > 0:
            time.sleep(gap)
        _ABS_TRACT_LAST_REQUEST_TIME[0] = time.time()


def abs_tract_search(
    title: str,
    author: str,
    provider: str,
    abs_tract_url: str,
    limit: int,
    existing_asin: str = "",
    kindle_region: str = "us",
    timeout: int = 20,
    retries: int = 2,
    log: list | None = None,
) -> list[dict]:
    """Search an abs-tract provider (Goodreads/Kindle) and normalize results.

    abs-tract is a standalone Audiobookshelf custom metadata provider, separate
    from abs-agg. Endpoints:
      goodreads -> /goodreads/search?query=...&author=...
      kindle    -> /kindle/<region>/search?query=...&author=...

    Kindle Store ASINs are *ebook* ASINs, not Audible audiobook ASINs, so the
    Kindle match's ASIN is never adopted as the book's ASIN (we keep any existing
    one). Kindle is useful here for its high-quality cover, not identity.

    Goodreads is read directly from its public XML (app/goodreads_shelves.py,
    shared with Enrichment Forge), so it needs no abs-tract URL; the
    throttle, retries and breaker here still guard it.
    """
    import urllib.error as _urlerror
    import urllib.parse as _urlparse
    import urllib.request as _urlrequest

    if not abs_tract_url and provider != "goodreads":
        return []

    # If the breaker is open (upstream is blocking us), skip the call entirely
    # rather than hang for the full timeout on every remaining book.
    if _abs_tract_breaker_is_open():
        if log is not None:
            with _ABS_TRACT_BREAKER_LOCK:
                _already = _ABS_TRACT_BREAKER["logged_open"]
                _ABS_TRACT_BREAKER["logged_open"] = True
            if not _already:
                log.append(
                    "  abs-tract circuit open (upstream blocking) -> skipping "
                    "Goodreads/Kindle for the cooldown window"
                )
        return []

    _abs_tract_throttle()

    if provider == "kindle":
        path = f"kindle/{kindle_region.strip('/')}/search"
    else:
        path = f"{provider}/search"
    params: dict[str, str] = {"query": title}
    if author:
        params["author"] = author
    url = f"{abs_tract_url.rstrip('/')}/{path}?{_urlparse.urlencode(params)}"

    # abs-tract scrapes Goodreads/Amazon live, so a single request can fail
    # transiently (timeout, rate-limit, scraper hiccup) especially during a long
    # batch run. Swallowing those as [] makes a book that *is* on Goodreads look
    # like a genuine miss. Retry transient failures with backoff and surface a
    # distinct log line so a real "no results" is distinguishable from an error.
    _RETRYABLE_HTTP = {429, 500, 502, 503, 504}
    raw = None
    last_err = ""
    for _attempt in range(max(1, retries)):
        try:
            if provider == "goodreads":
                found = goodreads_search_books(title, author, pacer=_GOODREADS_PACER, limit=min(limit, 3), timeout=timeout)
                if found["status"] == "failed":
                    raise OSError("Goodreads request failed")
                raw = {"matches": found["matches"]}
            else:
                req = _urlrequest.Request(url, headers={"Accept": "application/json"})
                with _urlrequest.urlopen(req, timeout=timeout) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
            break
        except _urlerror.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            if exc.code not in _RETRYABLE_HTTP:
                break
        except (_urlerror.URLError, OSError, TimeoutError) as exc:
            last_err = type(exc).__name__
        except Exception as exc:  # malformed JSON etc.
            last_err = type(exc).__name__
            break
        if _attempt < max(1, retries) - 1:
            time.sleep(0.75 * (2 ** _attempt))  # 0.75s, 1.5s, 3s ...

    if raw is None:
        _abs_tract_breaker_record(success=False)
        if log is not None:
            log.append(
                f"  {provider} request failed after {max(1, retries)} tries "
                f"({last_err or 'unknown error'}) -> treated as no result"
            )
        return []

    _abs_tract_breaker_record(success=True)
    products = []
    for match in (raw.get("matches", []) or [])[:limit]:
        if provider == "kindle":
            asin = existing_asin  # never trust a Kindle ebook ASIN as the audiobook ASIN
        else:
            asin = match.get("asin", "") or existing_asin
        products.append(_abs_match_to_product(match, provider, asin))
    return products


def audiobook_guild_search(
    title: str,
    author: str,
    limit: int,
    existing_asin: str = "",
    log: list | None = None,
    series: str = "",
    number: str = "",
) -> list[dict]:
    """Search Audiobook Guild (app/audiobook_guild.py) and normalize its books
    to the Audible product shape. The store has no ASIN, so the file's own is
    kept; unlike Goodreads, it lists each book's runtime."""
    found = audiobook_guild.search_books(title, author, series=series, number=number, limit=min(limit, 3))
    if found["status"] == "failed" and log is not None:
        log.append("  Audiobook Guild request failed -> treated as no result")
    products = []
    for match in found["matches"]:
        product = _abs_match_to_product(match, "audiobookguild", existing_asin)
        product["runtime_length_min"] = match.get("runtime_minutes")
        products.append(product)
    return products


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

@trace(CHOOSE, capture=[])
def detect_special_provider(clues: dict) -> str | None:
    """Return the abs-agg provider id if the file is a known dramatized production.

    Checks multiple signals so 'Dramatized Adaptation' is an indicator but not
    the sole trigger -- publisher name, series name, and raw composer tag are
    all considered.
    """
    # 1. Publisher name matches a known GA/SBT imprint in the catalog
    special = special_provider_for(clues.get("publisher", ""))
    if special:
        return special

    # 2. Series name contains the producer name (e.g. "The Mistborn Saga (GraphicAudio)")
    series = clues.get("series", "") or ""
    if "graphicaudio" in series.lower():
        return "graphicaudio"
    if "soundbooth" in series.lower():
        return "soundbooththeater"

    # 3. Composer/writer raw tag (©wrt / "composer") -- GraphicAudio embeds its name there.
    #    mutagen uses ©wrt; ffprobe (probe_file fallback) uses the lowercase "composer" key.
    raw_tags = clues.get("_raw_tags") or {}
    _composer_vals: list[str] = []
    for tag_key in ("©wrt", "\xa9wrt"):
        for val in (raw_tags.get(tag_key) or []):
            try:
                _composer_vals.append(
                    bytes(val).decode("utf-8", "ignore") if hasattr(val, "__bytes__") else str(val)
                )
            except Exception:
                pass
    if not _composer_vals:
        _ffprobe_comp = str(raw_tags.get("composer", "") or "")
        if _ffprobe_comp:
            _composer_vals.append(_ffprobe_comp)
    for _cv in _composer_vals:
        if "graphicaudio" in _cv.lower():
            return "graphicaudio"
        if "soundbooth" in _cv.lower():
            return "soundbooththeater"

    # 4. "[Dramatized Adaptation]" marker in the title, subtitle, or narrator tag.
    #    All three are used by GA/SBT productions; the marker frequently lands in
    #    the title (e.g. "Storm Front (Dramatized Adaptation)") where the earlier
    #    publisher/series/composer signals never see it, so a title-only marker
    #    must still trigger the dedicated-catalog search.
    title = clues.get("title", "") or ""
    subtitle = clues.get("subtitle", "") or ""
    narrator = clues.get("narrator", "") or ""
    for _sig in (title, subtitle, narrator):
        _sig_lower = _sig.lower()
        if "dramatized" in _sig_lower and "adaptation" in _sig_lower:
            return "graphicaudio"

    return None


# ---------------------------------------------------------------------------
# Audible client (thread-local) and cached search
# ---------------------------------------------------------------------------

_thread_local = threading.local()

# Audible's catalog API answers without a login: the same product, search and
# chapter data the logged-in client gets, for any marketplace.
PUBLIC_AUDIBLE_DOMAINS = {
    "us": "audible.com", "uk": "audible.co.uk", "ca": "audible.ca", "au": "audible.com.au",
    "de": "audible.de", "fr": "audible.fr", "it": "audible.it", "es": "audible.es",
    "in": "audible.in", "jp": "audible.co.jp",
}


class AudibleThrottle:
    """One back-off shared by every Audible catalog request in the process.

    When Audible throttles a request (429/503), every worker waits before its
    next request, rather than each retrying on its own while the others keep
    asking. The wait is Audible's Retry-After when it sends one, else 2 s,
    doubling (to 30 s) while throttling continues after a wait, and back to
    2 s after a request succeeds."""

    FIRST_WAIT_S = 2.0
    MAX_WAIT_S = 30.0

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] | None = None):
        self._clock, self._sleep = clock, sleep or (lambda seconds: time.sleep(seconds))
        self._lock = threading.Lock()
        self.resume_at = 0.0
        self._wait = 0.0

    def wait_turn(self) -> None:
        with self._lock:
            delay = self.resume_at - self._clock()
        if delay > 0:
            self._sleep(delay)

    def throttled(self, retry_after: float | None) -> None:
        with self._lock:
            now = self._clock()
            if now < self.resume_at:
                return  # already backing off: the other workers' requests were in flight
            self._wait = min(self.MAX_WAIT_S, self._wait * 2 if self._wait else self.FIRST_WAIT_S)
            self.resume_at = now + (retry_after if retry_after else self._wait)

    def succeeded(self) -> None:
        with self._lock:
            self._wait = 0.0


_AUDIBLE_THROTTLE = AudibleThrottle()
_THROTTLED = (429, 503)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    try:
        value = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return min(value, AudibleThrottle.MAX_WAIT_S) if value > 0 else None


class PublicAudibleClient:
    """Login-free stand-in for audible.Client, for catalog calls only.

    Same ``get(path, params)`` shape and return value, so audible_search,
    audible_lookup_by_asin and audible_lookup_chapters work unchanged. Account
    endpoints (library, licenses) need a real login and fail here.
    """

    def __init__(self, region: str = "", timeout: float = 20.0, retries: int = 2,
                 transport: httpx.BaseTransport | None = None, throttled_retries: int = 6):
        region = (region or os.environ.get("AUDIBLE_PUBLIC_REGION", "") or "us").lower()
        self.base_url = f"https://api.{PUBLIC_AUDIBLE_DOMAINS.get(region, 'audible.com')}/1.0/"
        self.timeout = timeout
        self.retries = retries
        # Throttling ends when Audible says so: up to ~1.5 min of shared waits.
        self.throttled_retries = throttled_retries
        # One connection kept open for every request: opening a new one each
        # time (urllib) made a catalog call ~500 ms instead of ~210 ms.
        self._http = httpx.Client(timeout=timeout, headers={"Accept": "application/json"}, transport=transport)

    def get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url + path.lstrip("/")
        failures = throttles = 0
        while True:
            _AUDIBLE_THROTTLE.wait_turn()
            try:
                resp = self._http.get(url, params=params)
                resp.raise_for_status()
                _AUDIBLE_THROTTLE.succeeded()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in _THROTTLED:
                    # Audible is throttling: everyone waits, then this request again.
                    throttles += 1
                    if throttles > self.throttled_retries:
                        raise
                    _AUDIBLE_THROTTLE.throttled(_retry_after_seconds(exc.response))
                    continue
                # A transient upstream error: back off and retry.
                if status not in (500, 502, 504) or failures == self.retries:
                    raise
            except httpx.TransportError:
                if failures == self.retries:
                    raise
            failures += 1
            time.sleep(1.5 * failures)


def get_catalog_client(auth_file: str, password: str | None = None, public_region: str = ""):
    """The logged-in client when an auth file exists, else the public catalog.

    public_region picks the public catalog of that marketplace even when an
    auth file exists (the "Audible public catalog" provider).
    """
    if not public_region and auth_file and os.path.isfile(auth_file):
        kwargs = {"password": password} if password else {}
        auth = audible.Authenticator.from_file(auth_file, **kwargs)
        return audible.Client(auth=auth)
    return PublicAudibleClient(region=public_region)


def get_thread_client(auth_file: str, password: str | None = None) -> audible.Client:
    if not hasattr(_thread_local, "client"):
        _thread_local.client = get_catalog_client(auth_file, password)
    return _thread_local.client


def audible_search_cache_key(query: str, limit: int, title: str = "", author: str = "") -> tuple:
    if title:
        return ("title+author", title.lower(), author.lower(), limit)
    return (query.lower(), limit)


def cached_audible_search(
    client: audible.Client,
    query: str,
    limit: int,
    api_delay_ms: int,
    cache: dict,
    cache_lock: threading.Lock,
    in_flight: dict,
    title: str = "",
    author: str = "",
) -> list[dict]:
    key = audible_search_cache_key(query, limit, title, author)
    while True:
        with cache_lock:
            if key in cache:
                return cache[key]
            if key not in in_flight:
                event = threading.Event()
                in_flight[key] = event
                break
            event = in_flight[key]
        event.wait(timeout=60)
    failed = False
    try:
        results = audible_search(client, query, limit, title=title, author=author)
        if api_delay_ms > 0:
            time.sleep(api_delay_ms / 1000)
    except Exception:
        results, failed = [], True
    finally:
        with cache_lock:
            if not failed:  # a failed search is asked again, never remembered as "no results"
                cache[key] = results
            in_flight.pop(key, None)
        event.set()
    return results
