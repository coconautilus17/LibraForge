"""Genre voting for Enrichment Forge v2.

Per book: each source's labels are classified on their own; a main genre
needs two sources agreeing, or one source for the high-precision strong set
(LitRPG, Progression Fantasy, Harem). Per series: a main genre needs 25% of
the books that voted, series-level sources count as full support, then
conflicts are resolved (Fantasy vs Science Fiction ratio, Non-Fiction is
exclusive, at most three mains). Every surviving genre keeps its evidence:
how many books each source supported it on.

Ported from the full-library prototype (docs/design/efv2-prototype/pipeline_v2.py).
"""
from __future__ import annotations

import collections
import math
from typing import Any

from app.genre_taxonomy import MAIN_ORDER, STRONG_MAINS, classify

SERIES_SOURCE = "series-source"
_MAINSTREAM = ("Mystery", "Thriller", "Horror", "Romance")
_NON_FICTION_SUBS = {"History", "Biography", "Science", "Politics", "Psychology", "Religion", "Society",
                     "True Crime", "Arts", "Language", "Writing", "Self-Help", "Literary Criticism"}
_REAL_SF_SUBS = ("Space Opera", "Military Science Fiction", "Post-Apocalyptic", "Hard Science Fiction")
MAX_MAINS = 3
# Crowd shelving: Goodreads readers shelve progression and harem fantasy as
# "litrpg" loosely (Cradle, Dragon Emperor), so a strong genre from Goodreads
# alone needs a second source like any other genre.
_CROWD_SOURCES = {"goodreads"}
MAX_SUBS = 5


def book_vote(voters: dict[str, list[str]]) -> dict[str, Any]:
    """{"main": set, "sub": Counter, "evidence": {genre: set(sources)}} for one book."""
    votes: collections.Counter = collections.Counter()
    subs: collections.Counter = collections.Counter()
    evidence: dict[str, set[str]] = collections.defaultdict(set)
    for source, labels in voters.items():
        mains, source_subs = classify([labels])
        for genre in mains:
            votes[genre] += 1
            evidence[genre].add(source)
        subs.update(source_subs)
    needed = 2 if len(voters) >= 2 else 1
    main = {g for g, c in votes.items()
            if c >= needed or (g in STRONG_MAINS and evidence[g] - _CROWD_SOURCES)}
    if not main and votes:
        # Nothing agreed: fall back to the best-supported genre(s), at most two.
        top = max(votes.values())
        tied = sorted((g for g, c in votes.items() if c == top), key=MAIN_ORDER.index)
        main = set(tied[:2])
    return {"main": main, "sub": subs, "evidence": {g: evidence[g] for g in main}}


def vote_unit(
    book_votes: list[dict[str, Any]],
    *,
    series_labels: list[str],
    series_evidence: list[str],
    pf_progression: bool,
    standalone: bool,
) -> dict[str, Any]:
    """Series (or standalone) result: main genres, subgenres, per-genre
    evidence {genre: {source: books}}, series evidence and agreement."""
    voted = [v for v in book_votes if v["main"]]
    n = len(voted) or 1  # books with no vote (no matches, no audio) never dilute
    threshold = 1 if n < 4 else math.ceil(0.25 * n)
    main_votes: collections.Counter = collections.Counter()
    sub_votes: collections.Counter = collections.Counter()
    evidence: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for vote in voted:
        for genre in vote["main"]:
            main_votes[genre] += 1
            evidence[genre].update(vote["evidence"].get(genre, ()))
        for sub in vote["sub"]:
            sub_votes[sub] += 1

    series_mains: list[str] = []
    if not standalone:
        if series_labels:
            series_mains = list(classify([[]], series_labels)[0])
        if pf_progression:
            # progressionfantasy.co.uk's "Non-LitRPG" list is broad (it has The
            # Dresden Files): trust it only when corroborated or uncontested.
            corroborated = main_votes["Progression Fantasy"] > 0 or sub_votes.get("Cultivation", 0) > 0
            conflict = any(main_votes[g] >= threshold for g in _MAINSTREAM)
            if corroborated or not conflict:
                series_mains.append("Progression Fantasy")
    for genre in series_mains:
        main_votes[genre] = max(main_votes[genre], threshold)
        evidence[genre][SERIES_SOURCE] += 1

    mains = [g for g in MAIN_ORDER if main_votes[g] >= threshold]
    fiction = [g for g in mains if g != "Non-Fiction"]
    if "Non-Fiction" in mains and fiction:
        if main_votes["Non-Fiction"] > max(main_votes[g] for g in fiction):
            mains = ["Non-Fiction"]
        else:
            mains.remove("Non-Fiction")
    if "Fantasy" in mains and "Science Fiction" in mains:
        fantasy, scifi = main_votes["Fantasy"], main_votes["Science Fiction"]
        if min(fantasy, scifi) < 0.5 * max(fantasy, scifi):
            mains.remove("Fantasy" if fantasy < scifi else "Science Fiction")
    if ("LitRPG" in mains and "Science Fiction" in mains
            and sub_votes.get("Cyberpunk", 0) >= main_votes["Science Fiction"] * 0.8
            and not any(sub_votes.get(s) for s in _REAL_SF_SUBS)):
        mains.remove("Science Fiction")
        sub_votes.pop("Cyberpunk", None)
    if "Classics" in mains and main_votes["Classics"] < max(1, math.ceil(0.5 * n)):
        mains.remove("Classics")

    strong = [g for g in mains if g in STRONG_MAINS]
    rest = sorted((g for g in mains if g not in STRONG_MAINS), key=lambda g: (-main_votes[g], MAIN_ORDER.index(g)))
    # Strong genres are what readers of this audience browse by, so they are
    # kept first, but one broad genre always survives when there is one.
    keep_rest = rest[:max(1, MAX_MAINS - len(strong))]
    keep_strong = strong[:MAX_MAINS - len(keep_rest)]
    mains = sorted(keep_rest + keep_strong, key=MAIN_ORDER.index)

    if "Non-Fiction" in mains:
        sub_votes = collections.Counter({k: v for k, v in sub_votes.items() if k in _NON_FICTION_SUBS})
    else:
        sub_votes = collections.Counter({k: v for k, v in sub_votes.items() if k not in _NON_FICTION_SUBS})
    subs = [s for s, c in sorted(sub_votes.items(), key=lambda kv: (-kv[1], kv[0]))
            if c >= threshold and s not in mains and not s.endswith("?")][:MAX_SUBS]
    return {
        "main": mains,
        "sub": subs,
        "evidence": {g: dict(evidence[g]) for g in mains},
        "series_evidence": list(series_evidence) if not standalone else [],
        "agreement": "ok" if mains else "none",
    }
