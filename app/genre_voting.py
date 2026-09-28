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

from app.genre_taxonomy import MAIN_ORDER, PROGRESSION_KINDS, STRONG_MAINS, classify

SERIES_SOURCE = "series-source"
_MAINSTREAM = ("Mystery", "Thriller", "Horror", "Romance")
_NON_FICTION_SUBS = {"History", "Biography", "Science", "Politics", "Psychology", "Religion", "Society",
                     "True Crime", "Arts", "Language", "Writing", "Self-Help", "Literary Criticism"}
_REAL_SF_SUBS = ("Space Opera", "Military Science Fiction", "Post-Apocalyptic", "Hard Science Fiction")
# Crowd shelving: Goodreads readers shelve progression and harem fantasy as
# "litrpg" loosely (Cradle, Dragon Emperor), so a strong genre from Goodreads
# alone needs a second source like any other genre.
# The library's own current genres count the same way: v1 wrote Goodreads'
# loose LitRPG into ABS, and it must not come back on its own.
_CROWD_SOURCES = {"goodreads", "abs_existing"}
MAX_SUBS = 5
MAX_CANDIDATES = 10


def book_vote(voters: dict[str, list[str]]) -> dict[str, Any]:
    """One book's vote: {"main": set, "sub": Counter, "evidence": {genre:
    set(sources)}, "sub_evidence": {sub: set(sources)}, "other": set of main
    genres some source named that didn't pass}."""
    votes: collections.Counter = collections.Counter()
    subs: collections.Counter = collections.Counter()
    evidence: dict[str, set[str]] = collections.defaultdict(set)
    sub_evidence: dict[str, set[str]] = collections.defaultdict(set)
    for source, labels in voters.items():
        mains, source_subs = classify([labels])
        for genre in mains:
            votes[genre] += 1
            evidence[genre].add(source)
        for sub in source_subs:
            subs[sub] += 1
            sub_evidence[sub].add(source)
    needed = 2 if len(voters) >= 2 else 1
    main = {g for g, c in votes.items()
            if c >= needed or (g in STRONG_MAINS and evidence[g] - _CROWD_SOURCES)}
    fallback = {g: c for g, c in votes.items() if not (g in STRONG_MAINS and not evidence[g] - _CROWD_SOURCES)}
    if not main and fallback:
        # Nothing agreed: fall back to the best-supported genre(s), at most two,
        # never a strong genre only crowd shelving named.
        votes = collections.Counter(fallback)
        top = max(votes.values())
        tied = sorted((g for g, c in votes.items() if c == top), key=MAIN_ORDER.index)
        main = set(tied[:2])
    return {"main": main, "sub": subs, "evidence": {g: evidence[g] for g in main},
            "sub_evidence": dict(sub_evidence), "other": set(votes) - main}


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
    sub_evidence: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    mentioned: collections.Counter = collections.Counter()  # any support at all, for suggestions
    for vote in voted:
        for genre in vote["main"]:
            main_votes[genre] += 1
            evidence[genre].update(vote["evidence"].get(genre, ()))
        for sub in vote["sub"]:
            sub_votes[sub] += 1
            sub_evidence[sub].update(vote.get("sub_evidence", {}).get(sub, ()))
        mentioned.update(set(vote["main"]) | set(vote.get("other", ())) | set(vote["sub"]))

    series_mains: list[str] = []
    if not standalone:
        if series_labels:
            series_mains = list(classify([[]], series_labels)[0])
        if pf_progression:
            # progressionfantasy.co.uk's "Non-LitRPG" list is broad (it has The
            # Dresden Files): trust it only when corroborated or uncontested.
            corroborated = any(main_votes[g] > 0 or mentioned[g] > 0 for g in ("Progression Fantasy", "Cultivation"))
            conflict = any(main_votes[g] >= threshold for g in _MAINSTREAM)
            if corroborated or not conflict:
                series_mains.append("Progression Fantasy")
            # The listing also confirms readers' "cultivation" shelving, which
            # alone is crowd evidence (Cradle).
            if mentioned["Cultivation"] >= threshold:
                series_mains.append("Cultivation")
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

    # No cap on main genres: every genre the evidence supports is kept.
    progression_kind = any(g in mains for g in PROGRESSION_KINDS)
    if progression_kind and "Progression Fantasy" in mains:
        mains.remove("Progression Fantasy")

    if "Non-Fiction" in mains:
        sub_votes = collections.Counter({k: v for k, v in sub_votes.items() if k in _NON_FICTION_SUBS})
    else:
        sub_votes = collections.Counter({k: v for k, v in sub_votes.items() if k not in _NON_FICTION_SUBS})
    subs = [s for s, c in sorted(sub_votes.items(), key=lambda kv: (-kv[1], kv[0]))
            if c >= threshold and s not in mains and not s.endswith("?")][:MAX_SUBS]
    if progression_kind:
        # LitRPG and Cultivation are progression fantasy: keep the umbrella as
        # a subgenre so a Progression Fantasy collection still gathers them.
        subs = ["Progression Fantasy"] + [s for s in subs if s != "Progression Fantasy"]
        sub_evidence["Progression Fantasy"].update(evidence.get("Progression Fantasy", {}))
        if not sub_evidence["Progression Fantasy"]:
            sub_evidence["Progression Fantasy"]["implied"] = 1
    excluded_subs = _NON_FICTION_SUBS if "Non-Fiction" not in mains else set()
    candidates = [g for g, _c in sorted(mentioned.items(), key=lambda kv: (-kv[1], kv[0]))
                  if g not in mains and g not in subs and not g.endswith("?") and g not in excluded_subs][:MAX_CANDIDATES]
    return {
        "main": mains,
        "sub": subs,
        "candidates": candidates,
        "evidence": {**{g: dict(evidence[g]) for g in mains}, **{s: dict(sub_evidence[s]) for s in subs}},
        "series_evidence": list(series_evidence) if not standalone else [],
        "agreement": "ok" if mains else "none",
    }
