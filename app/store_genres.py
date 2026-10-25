"""Genre names from Audible's foreign stores, learned from Audible itself (#442).

An ABS match against another store, or against the US store's Spanish pages,
writes that store's category names ("Fantasía, Acción y aventura"). Audible
returns a store's whole genre tree in one request per language, and a
category keeps its ID across languages on its store, so fetching each tree in
its own language and in English translates every category without a
hand-kept table. Spain, Italy and Japan answer only in their own language:
their names are still recognised as store genres (never the user's own), and
Spain's are paired with the US store's Spanish categories by their wording.

The table is cached in a JSON file (configure()) and refetched monthly;
app/genre_taxonomy.py's hand-kept FOREIGN_STORE_ALIASES covers the common
Spanish and French names before the first fetch or when Audible is down.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# (store, its own language, English on that store or "" when it has none)
STORE_TREES = (
    ("us", "es-US", "en-US"), ("de", "de-DE", "en-GB"), ("fr", "fr-FR", "en-GB"), ("ca", "fr-CA", "en-CA"),
    ("es", "es-ES", ""), ("it", "it-IT", ""), ("jp", "ja-JP", ""),
)
MAX_AGE = 30 * 86400
RETRY_AFTER = 86400

_lock = threading.Lock()
_path: Path | None = None
_table: dict[str, Any] = {}
_last_attempt = 0.0


Tree = dict[str, tuple[str, str, str]]  # category id -> (name, root name, parent id)


def fetch_tree(store: str, locale: str) -> Tree:
    """One store's genre tree in one language."""
    from app.fixer.search import PublicAudibleClient

    data = PublicAudibleClient(region=store).get(
        "catalog/categories", {"root": "Genres", "categories_num_levels": "5", "locale": locale})
    out: Tree = {}

    def walk(nodes: list[dict[str, Any]], root: str, parent: str) -> None:
        for node in nodes or []:
            name = str(node.get("name") or "").strip()
            if node.get("id") and name:
                out[str(node["id"])] = (name, root or name, parent)
            walk(node.get("children") or [], root or name, str(node.get("id") or ""))

    walk(data.get("categories") or [], "", "")
    return out


_STOPWORDS = {"y", "e", "de", "del", "la", "el", "los", "las", "en", "para", "a", "con", "di", "il", "lo", "per", "and", "&"}


def _words(name: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    return [w[:6] for w in re.findall(r"[a-z]+", plain) if w not in _STOPWORDS]


def _likeness(a: str, b: str) -> float:
    """Shared words of two names in one language ("Enfermedad física y
    trastornos" / "Enfermedades Físicas"), words compared by their start."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return 2 * len(set(wa) & set(wb)) / (len(set(wa)) + len(set(wb)))


def align_trees(own: Tree, ref: Tree) -> dict[str, str]:
    """{own id: ref id} for two stores' trees in the same language. Audible's
    stores share one structure but word it differently and number it apart:
    categories are paired level by level, under paired parents, by their
    wording, and a single category left on each side is the other's."""
    kids: dict[tuple[int, str], list[str]] = {}
    for side, tree in ((0, own), (1, ref)):
        for cid, (_, _, parent) in tree.items():
            kids.setdefault((side, parent), []).append(cid)
    matched: dict[str, str] = {}

    def pair(own_parent: str, ref_parent: str) -> None:
        mine, theirs = kids.get((0, own_parent), []), kids.get((1, ref_parent), [])
        scored = sorted(((_likeness(own[o][0], ref[r][0]), o, r) for o in mine for r in theirs), reverse=True)
        found: dict[str, str] = {}
        for score, o, r in scored:
            if score < 0.5:
                break
            if o not in found and r not in found.values():
                found[o] = r
        left_mine = [o for o in mine if o not in found]
        left_theirs = [r for r in theirs if r not in found.values()]
        if len(left_mine) == 1 and len(left_theirs) == 1:
            found[left_mine[0]] = left_theirs[0]
        for o, r in found.items():
            matched[o] = r
            pair(o, r)

    pair("", "")
    return matched


def build_table(fetch: Callable[[str, str], Tree] = fetch_tree) -> dict[str, Any]:
    """{"foreign": {name: [english name, english root] or []}, "composites": [...],
    "joined": [...]}. Names are lowercase except the composites, which keep the
    store's spelling. The root is "" when the name sits under several roots."""
    trees = {(store, own, english): (fetch(store, own), fetch(store, english) if english else {})
             for store, own, english in STORE_TREES}
    english_names = {node[0].lower() for _, en in trees.values() for node in en.values()}
    composites: set[str] = {node[0] for pair in trees.values() for tree in pair for node in tree.values() if "," in node[0]}
    # The English for each store's category: by its ID on a store that speaks
    # English, else through a store in the same language that does (Spain's
    # Spanish through the US store's).
    english_of: list[tuple[str, tuple[str, str, str] | None]] = []
    for (store, own_locale, english), (own, en) in trees.items():
        if english:
            english_of += [(node[0], en.get(cid)) for cid, node in own.items()]
            continue
        language = own_locale.split("-")[0]
        ref = next(((o, e) for (s, ol, el), (o, e) in trees.items() if el and ol.split("-")[0] == language), None)
        matched = align_trees(own, ref[0]) if ref else {}
        english_of += [(node[0], ref[1].get(matched[cid]) if cid in matched else None) for cid, node in own.items()]

    foreign: dict[str, list[str]] = {}
    roots: dict[str, set[str]] = {}
    for name, target in english_of:
        key = name.lower()
        # A store name that is English as well ("Fantasy", "Thriller" in
        # Italy and Germany) is no foreign genre.
        if key in english_names:
            continue
        if target:
            if not foreign.get(key):
                foreign[key] = [target[0].lower(), ""]
            roots.setdefault(key, set()).add(target[1].lower())
        else:
            foreign.setdefault(key, [])  # known to be a store genre, no English
    for key, found in roots.items():
        if len(found) == 1:
            foreign[key][1] = next(iter(found))
    joined = sorted({name for name in english_names if " & " in name})
    return {"fetched_at": time.time(), "foreign": foreign, "composites": sorted(composites), "joined": joined}


def configure(path: Path) -> None:
    """Use `path` as the cache, loading what an earlier fetch saved there."""
    global _path, _table
    _path = Path(path)
    try:
        _table = json.loads(_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _table = {}
    except (OSError, ValueError) as exc:
        logger.warning("Store genre table %s unreadable: %s", _path, exc)
        _table = {}


def _stale(now: float) -> bool:
    return now - float(_table.get("fetched_at") or 0) >= MAX_AGE and now - _last_attempt >= RETRY_AFTER


def refresh_in_background() -> None:
    """Start a refetch when the table is stale, without waiting for it: the
    hand-kept aliases cover the meantime. LIBRAFORGE_STORE_GENRE_FETCH=0 turns
    the fetch off (the test suite)."""
    if os.environ.get("LIBRAFORGE_STORE_GENRE_FETCH", "1") == "0" or not _stale(time.time()):
        return
    threading.Thread(target=refresh_if_stale, name="store-genres", daemon=True).start()


def refresh_if_stale(fetch: Callable[[str, str], dict[str, tuple[str, str]]] = fetch_tree) -> None:
    """Refetch the trees when the table is a month old (or missing). A failed
    fetch keeps the old table and waits a day before trying again."""
    global _table, _last_attempt
    with _lock:
        now = time.time()
        if not _stale(now):
            return
        _last_attempt = now
        try:
            table = build_table(fetch)
        except Exception as exc:  # network, throttling, a changed response
            logger.warning("Could not fetch Audible's store genre trees: %s", exc)
            return
        if not table["foreign"]:
            return
        _table = table
        if _path:
            try:
                _path.parent.mkdir(parents=True, exist_ok=True)
                _path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
            except OSError as exc:
                logger.warning("Could not save the store genre table to %s: %s", _path, exc)


def set_table(table: dict[str, Any]) -> None:
    """Install a table directly (tests)."""
    global _table
    _table = table


def english_for(label: str) -> tuple[str, str] | None:
    """(English name, English root category) of a foreign store genre, lowercase."""
    found = (_table.get("foreign") or {}).get(label.strip().lower())
    return (found[0], found[1]) if found else None


def is_store_genre(label: str) -> bool:
    """True for a genre name only a foreign Audible store uses."""
    return label.strip().lower() in (_table.get("foreign") or {})


def composites() -> list[str]:
    """Store genre names that contain a comma themselves."""
    return list(_table.get("composites") or [])


def joined_names() -> list[str]:
    """English store genre names joined by "&" ("arts & entertainment"), lowercase."""
    return list(_table.get("joined") or [])
