"""Audible / ABS search helpers and per-provider HTTP clients.

All functions here are either pure transformations or call only external HTTP
services (Audible API, ABS, abs-agg, abs-tract). They do not touch the local
filesystem and have no dependency on the fixer script itself.
"""

from __future__ import annotations

import json
import threading
import time

import audible

from app.debug_trace import trace, CHOOSE
from app.fixer.scoring import clean_provider_genres
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
    ]
)


def audible_search(client: audible.Client, query: str, limit: int) -> list[dict]:
    response = client.get(
        "catalog/products",
        params={
            "keywords": query,
            "num_results": limit,
            "response_groups": RESPONSE_GROUPS,
        },
    )

    return response.get("products", []) or []


def audible_lookup_by_asin(client: audible.Client, asin: str) -> dict | None:
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
            params={"response_groups": RESPONSE_GROUPS},
        )
        product = response.get("product") or None
        if product:
            return product
    except Exception:
        pass
    # Fallback: keyword search -- some ASINs surface here but not via direct lookup
    try:
        results = audible_search(client, asin_upper, 5)
        for p in results:
            if str(p.get("asin", "") or "").upper() == asin_upper:
                return p
    except Exception:
        pass
    return None


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
            "_abs_provider": provider,
            "_abs_isbn": match.get("isbn", "") or "",
            "_abs_genres": clean_provider_genres(match.get("genres") or []),
        })
    return products


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
        "_abs_provider": provider,
        "_abs_isbn": match.get("isbn", "") or "",
        "_abs_genres": clean_provider_genres(match.get("genres") or []),
    }


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
_ABS_TRACT_BREAKER = {"consecutive_failures": 0, "open_until": 0.0, "logged_open": False}
_ABS_TRACT_BREAKER_THRESHOLD = 2      # consecutive persistent failures before tripping
_ABS_TRACT_BREAKER_COOLDOWN = 180.0   # seconds to stay open; measured recovery is ~90-105s

# Throttle: enforce a minimum gap between any two abs-tract requests so
# sustained parallel batches don't hit upstream rate limits. With 5 workers
# all needing Goodreads simultaneously the burst would otherwise be 5x.
_ABS_TRACT_THROTTLE_LOCK = threading.Lock()
_ABS_TRACT_LAST_REQUEST_TIME: list[float] = [0.0]
_ABS_TRACT_THROTTLE_DELAY = 0.5  # seconds between requests (global, across all workers)


def _abs_tract_breaker_is_open() -> bool:
    with _ABS_TRACT_BREAKER_LOCK:
        return time.time() < _ABS_TRACT_BREAKER["open_until"]


def _abs_tract_breaker_record(success: bool) -> None:
    with _ABS_TRACT_BREAKER_LOCK:
        if success:
            _ABS_TRACT_BREAKER["consecutive_failures"] = 0
            _ABS_TRACT_BREAKER["logged_open"] = False
            return
        _ABS_TRACT_BREAKER["consecutive_failures"] += 1
        if _ABS_TRACT_BREAKER["consecutive_failures"] >= _ABS_TRACT_BREAKER_THRESHOLD:
            _ABS_TRACT_BREAKER["open_until"] = time.time() + _ABS_TRACT_BREAKER_COOLDOWN


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
    """
    import urllib.error as _urlerror
    import urllib.parse as _urlparse
    import urllib.request as _urlrequest

    if not abs_tract_url:
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

    # 4. "[Dramatized Adaptation]" in subtitle or narrator tag -- both are used
    #    by GA/SBT productions; narrator is more common in practice.
    subtitle = clues.get("subtitle", "") or ""
    narrator = clues.get("narrator", "") or ""
    for _sig in (subtitle, narrator):
        if "dramatized" in _sig.lower() and "adaptation" in _sig.lower():
            return "graphicaudio"

    return None


# ---------------------------------------------------------------------------
# Audible client (thread-local) and cached search
# ---------------------------------------------------------------------------

_thread_local = threading.local()


def get_thread_client(auth_file: str, password: str | None = None) -> audible.Client:
    if not hasattr(_thread_local, "client"):
        kwargs = {"password": password} if password else {}
        auth = audible.Authenticator.from_file(auth_file, **kwargs)
        _thread_local.client = audible.Client(auth=auth)
    return _thread_local.client


def cached_audible_search(
    client: audible.Client,
    query: str,
    limit: int,
    api_delay_ms: int,
    cache: dict,
    cache_lock: threading.Lock,
    in_flight: dict,
) -> list[dict]:
    key = (query.lower(), limit)
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
    try:
        results = audible_search(client, query, limit)
        if api_delay_ms > 0:
            time.sleep(api_delay_ms / 1000)
    except Exception:
        results = []
    finally:
        with cache_lock:
            cache[key] = results
            in_flight.pop(key, None)
        event.set()
    return results
