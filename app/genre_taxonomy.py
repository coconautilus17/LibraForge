"""Controlled genre vocabulary for Enrichment Forge v2.

Every source (Audible ladders, Goodreads shelves, AudioSilo, Open Library
subjects, progressionfantasy.co.uk, the HaremLit wiki, keywords, existing ABS
genres/tags) speaks its own dialect. Each label is lowercased, aliased, then
mapped here to (main genres, subgenres) so votes from different sources can be
counted together. Main genres are the collection-worthy ones.

Ported from the full-library prototype (docs/design/efv2-prototype/, 86%
benchmark recall vs 54% before). "Audiobook" is deliberately absent: it is a
format, never a genre.
"""
from __future__ import annotations

import collections
import math
import re
from typing import Any

MAIN_ORDER = ["Fantasy","Science Fiction","LitRPG","Progression Fantasy","Harem","Thriller","Mystery","Horror","Romance","Humor",
            "Historical Fiction","Young Adult","Children's","Classics","Literary Fiction","Non-Fiction","Audio Drama"]
# source label (lowercase) -> (main genres, subgenres)
LABEL_MAP: dict[str, tuple[list[str], list[str]]] = {
 "fantasy":(["Fantasy"],[]), "epic":([],["Epic Fantasy?"]), "epic fantasy":(["Fantasy"],["Epic Fantasy"]), "high fantasy":(["Fantasy"],["Epic Fantasy"]),
 "urban":(["Fantasy"],["Urban Fantasy"]), "urban fantasy":(["Fantasy"],["Urban Fantasy"]), "paranormal & urban":(["Fantasy"],["Urban Fantasy"]),
 "paranormal":([],["Paranormal"]), "supernatural":([],["Paranormal"]), "occult":(["Horror"],["Occult"]),
 "sword & sorcery":(["Fantasy"],["Sword & Sorcery"]), "dragons & mythical creatures":(["Fantasy"],["Dragons"]), "dragons":(["Fantasy"],["Dragons"]),
 "dark fantasy":(["Fantasy"],["Dark Fantasy"]), "gaslamp":(["Fantasy"],["Gaslamp Fantasy"]), "fairy tales":(["Fantasy"],["Fairy Tales"]),
 "myths & legends":(["Fantasy"],["Mythology"]), "arthurian":(["Fantasy"],["Arthurian"]), "coming of age":([],["Coming of Age"]),
 "portal fantasy":(["Fantasy"],["Portal Fantasy"]), "isekai":(["Fantasy"],["Portal Fantasy"]), "alt-history":([],["Alternate History"]),
 "science fiction":(["Science Fiction"],[]), "space opera":(["Science Fiction"],["Space Opera"]), "hard science fiction":(["Science Fiction"],["Hard Science Fiction"]),
 "military science fiction":(["Science Fiction"],["Military Science Fiction"]), "cyberpunk":(["Science Fiction"],["Cyberpunk"]),
 "post-apocalyptic":(["Science Fiction"],["Post-Apocalyptic"]), "apocalyptic":(["Science Fiction"],["Post-Apocalyptic"]), "dystopian":(["Science Fiction"],["Dystopian"]),
 "first contact":(["Science Fiction"],["First Contact"]), "alien invasion":(["Science Fiction"],["Alien Invasion"]), "space exploration":(["Science Fiction"],["Space Exploration"]),
 "galactic empire":(["Science Fiction"],["Space Opera"]), "time travel":(["Science Fiction"],["Time Travel"]), "alternate history":([],["Alternate History"]),
 "steampunk":([],["Steampunk"]), "superhero":([],["Superhero"]), "superheroes":([],["Superhero"]), "genetic engineering":(["Science Fiction"],[]),
 "litrpg":(["LitRPG"],[]), "gamelit":(["LitRPG"],["GameLit"]), "dungeon core":(["LitRPG"],["Dungeon Core"]), "dungeon":([],["Dungeon"]),
 "progression fantasy":(["Progression Fantasy"],[]), "cultivation":(["Progression Fantasy"],["Cultivation"]), "xianxia":(["Progression Fantasy"],["Cultivation"]), "wuxia":(["Progression Fantasy"],["Cultivation"]),
 "haremlit":(["Harem"],[]), "harem":(["Harem"],[]),
 "action & adventure":([],["Action & Adventure"]), "adventure":([],["Action & Adventure"]), "action":([],["Action & Adventure"]),
 "military":([],["Military"]), "war & military":([],["Military"]),
 "humor":(["Humor"],[]), "humorous":(["Humor"],[]), "humour":(["Humor"],[]), "comedy":(["Humor"],[]), "dark humor":(["Humor"],["Dark Humor"]), "satire":(["Humor"],["Satire"]),
 "romantic comedy":(["Romance","Humor"],[]), "romance":(["Romance"],[]), "romantic":(["Romance"],[]), "romantic suspense":(["Romance","Thriller"],[]),
 "thriller":(["Thriller"],[]), "thriller & suspense":(["Thriller"],[]), "suspense":(["Thriller"],[]), "crime thrillers":(["Thriller"],["Crime"]),
 "technothrillers":(["Thriller"],["Technothriller"]), "espionage":(["Thriller"],["Espionage"]), "political":([],["Political"]), "legal thrillers":(["Thriller"],["Legal"]),
 "international mystery & crime":(["Mystery"],["Crime"]), "mystery":(["Mystery"],[]), "crime":(["Mystery"],["Crime"]), "crime fiction":(["Mystery"],["Crime"]),
 "women sleuths":(["Mystery"],["Amateur Sleuth"]), "private investigators":(["Mystery"],["Private Investigator"]), "police procedurals":(["Mystery"],["Police Procedural"]),
 "hard-boiled":(["Mystery"],["Hard-Boiled"]), "cozy":(["Mystery"],["Cozy Mystery"]), "traditional detectives":(["Mystery"],[]),
 "horror":(["Horror"],[]), "ghosts":(["Horror"],["Ghosts"]), "vampires":([],["Vampires"]), "zombies":(["Horror"],["Zombies"]),
 "historical":([],["Historical?"]), "historical fiction":(["Historical Fiction"],[]),
 "classics":(["Classics"],[]), "world literature":(["Literary Fiction"],[]), "literary fiction":(["Literary Fiction"],[]),
 "young adult":(["Young Adult"],[]), "teen & young adult":(["Young Adult"],[]), "children's audiobooks":(["Children's"],[]),
 "radio drama":(["Audio Drama"],[]), "dramatizations":(["Audio Drama"],[]),
 "movie, tv & video game tie-ins":([],["Media Tie-In"]), "anthologies & short stories":([],["Short Stories"]),
 "history":(["Non-Fiction"],["History"]), "biographies & memoirs":(["Non-Fiction"],["Biography"]), "science & engineering":(["Non-Fiction"],["Science"]),
 "politics & social sciences":(["Non-Fiction"],["Politics"]), "freedom & security":(["Non-Fiction"],["Politics"]),
}
_HAREM_NEGATION = r"\b(no|not an?|non-|without an?|isn't an?|never an?)\s*harem"

YA=(["Young Adult"],[])
LABEL_MAP.update({
 "fantasy & magic":(["Fantasy","Young Adult"],[]), "growing up & facts of life":YA, "social & life skills":YA, "family life":YA, "friendship":YA,
 "self esteem & self image":YA, "self-esteem":YA, "difficult situations":YA, "physical & emotional abuse":YA,
 "animals":(["Children's"],[]), "animal fiction":(["Children's"],[]), "mice":(["Children's"],[]), "hamsters":(["Children's"],[]), "guinea pigs & squirrels":(["Children's"],[]),
 "bedtime & dreaming":(["Children's"],[]), "explore the world":(["Children's"],[]), "holidays":([],[]),
 "humorous fiction":(["Humor"],[]), "comedy & humor":(["Humor"],[]), "comic":([],["Graphic Novel"]), "manga":([],["Graphic Novel"]), "graphic novel":([],["Graphic Novel"]),
 "legal":(["Thriller"],["Legal"]), "law & crime":(["Mystery"],["Crime"]), "psychological":(["Thriller"],["Psychological"]),
 "thrillers & suspense":(["Thriller"],[]), "domestic thrillers":(["Thriller"],["Domestic"]), "serial killers":(["Thriller"],["Crime"]), "terrorism":(["Thriller"],[]),
 "medical & forensic":(["Thriller"],["Medical"]), "medical":(["Thriller"],["Medical"]),
 "mysteries":(["Mystery"],[]), "amateur sleuths":(["Mystery"],["Amateur Sleuth"]), "mysteries & detectives":(["Mystery"],[]), "noir":(["Mystery"],["Noir"]),
 "magical realism":(["Literary Fiction"],["Magical Realism"]), "metaphysical & visionary":(["Literary Fiction"],[]), "women's fiction":(["Literary Fiction"],[]),
 "sagas":([],["Family Saga"]), "scary stories":(["Horror"],[]), "gothic":(["Horror"],["Gothic"]),
 "apocalyptic & post-apocalyptic":(["Science Fiction"],["Post-Apocalyptic"]), "aliens":(["Science Fiction"],["Aliens"]),
 "greek & roman":([],["Historical?"]), "ancient":([],["Historical?"]), "medieval":([],["Historical?"]), "europe":([],["Historical?"]),
 "world war ii & holocaust":([],["Historical?"]), "military & wars":([],["Historical?"]), "history & culture":([],["Historical?"]),
 "westerns":([],["Western"]), "christian fiction":([],["Christian Fiction"]), "sea adventures":([],["Action & Adventure"]),
 "short stories":([],["Short Stories"]), "anthologies":([],["Short Stories"]), "collections":([],["Short Stories"]),
 "drama & plays":(["Classics"],["Drama"]), "shakespeare":(["Classics"],["Drama"]), "classic":(["Classics"],[]),
 "non fiction":(["Non-Fiction"],[]), "nonfiction":(["Non-Fiction"],[]), "science":(["Non-Fiction"],["Science"]), "psychology":(["Non-Fiction"],["Psychology"]),
 "politics":(["Non-Fiction"],["Politics"]), "politics & government":(["Non-Fiction"],["Politics"]), "sociology":(["Non-Fiction"],["Society"]),
 "criminology":(["Non-Fiction"],["True Crime"]), "violence in society":(["Non-Fiction"],["Society"]), "religion":(["Non-Fiction"],["Religion"]),
 "religion & spirituality":(["Non-Fiction"],["Religion"]), "spirituality":(["Non-Fiction"],["Religion"]), "memoir":(["Non-Fiction"],["Biography"]),
 "music":(["Non-Fiction"],["Arts"]), "art":(["Non-Fiction"],["Arts"]), "words":(["Non-Fiction"],["Language"]), "language & grammar":(["Non-Fiction"],["Language"]),
 "language learning":(["Non-Fiction"],["Language"]), "writing & publishing":(["Non-Fiction"],["Writing"]), "literary history & criticism":(["Non-Fiction"],["Literary Criticism"]),
 "entertainment & performing arts":(["Non-Fiction"],["Arts"]), "performing arts":(["Non-Fiction"],["Arts"]), "personal success":(["Non-Fiction"],["Self-Help"]),
 "death & dying":(["Non-Fiction"],[]), "unexplained mysteries":(["Non-Fiction"],["Paranormal"]), "ministry & evangelism":(["Non-Fiction"],["Religion"]),
})
LABEL_MAP.setdefault("erotica", (["Romance"], ["Erotica"]))
_KEYWORDS = {"litrpg":r"\blit\s?rpg\b|\bgamelit\b","progression fantasy":r"progression fantasy","cultivation":r"\bcultivation\b|\bxianxia\b|\bwuxia\b",
    "portal fantasy":r"\bisekai\b|portal fantasy","harem":r"\bharem\b","dungeon core":r"dungeon core"}
_ALIASES = {"juvenile fiction":"young adult","juvenile literature":"young adult","fiction, coming of age":"coming of age","school stories":"young adult","smut":"erotica",
 "childrens":"children's audiobooks","comedy humor":"humor","thriller suspense":"thriller","legal thriller":"legal","fantasy comedy":"humor",
 "detective and mystery stories":"mystery","women detectives":"amateur sleuths","fiction, horror":"horror","fiction, thrillers, general":"thriller","fiction, suspense":"suspense",
 "hard science-fiction":"hard science fiction","science-fiction":"science fiction","genre:litrpg":"litrpg","genre:science fantasy":"fantasy","world":"history",
 "action adventure":"action & adventure","sword sorcery":"sword & sorcery","post apocalyptic":"post-apocalyptic","cozy mystery":"cozy","paranormal romance":"romance",
 "womens fiction":"women's fiction","historical romance":"romance","true crime":"criminology","biography memoir":"memoir","religion spirituality":"religion",
 "self help":"personal success","ghost stories":"ghosts","fairy tales folklore":"fairy tales","military history":"history","war military fiction":"war & military",
 "police procedural":"police procedurals","psychological thriller":"psychological","hard boiled":"hard-boiled","arts entertainment":"art","social sciences":"sociology",
 "fiction, fantasy, general":"fantasy","fiction, science fiction, general":"science fiction","fiction, mystery & detective, general":"mystery","horror tales":"horror",
 "erotic fiction":"erotica","science fiction":"science fiction","fantasy fiction":"fantasy","thrillers (fiction)":"thriller","detective and mystery fiction":"mystery",
 "non-fiction":"non fiction","biography":"memoir","children's":"children's audiobooks"}


STRONG_MAINS = {"LitRPG", "Progression Fantasy", "Harem"}

# Composite Audible category names that contain a comma themselves.
_COMPOSITES = ("Mystery, Thriller & Suspense", "Movie, TV & Video Game Tie-Ins")


def normalize_label(label: Any) -> str:
    """Lowercase, drop AudioSilo's '(g)'/'(t)' suffix, apply aliases."""
    text = re.sub(r"\((g|t)\)$", "", str(label or "").lower()).strip()
    return _ALIASES.get(text, text)


def labels_from_genres(values: Any) -> list[str]:
    """Split genre strings / Audible ladder paths into normalized labels."""
    out: list[str] = []
    for value in values or []:
        text = str(value)
        for comp in _COMPOSITES:
            text = text.replace(comp, comp.replace(",", "\u00a7"))
        for part in re.split(r"\s*[,:;/]\s*", text):
            part = part.replace("\u00a7", ",").strip()
            if not part or part.lower() == "mystery, thriller & suspense":
                continue
            label = normalize_label(part)
            if label and label not in _NOT_GENRES:
                out.append(label)
    return out


def labels_from_text(text: str) -> list[str]:
    """Keyword labels from a summary/description ('LitRPG', 'cultivation'...).
    'not a harem' style negations never count as harem."""
    out = []
    for label, pattern in _KEYWORDS.items():
        if label == "harem" and re.search(_HAREM_NEGATION, text or "", re.I):
            continue
        if re.search(pattern, text or "", re.I):
            out.append(label)
    return out


_NOT_GENRES = {"audiobook", "audiobooks", "audio book", "audio books", "fiction", "literature & fiction",
               "genre fiction", "science fiction & fantasy", "miscellaneous"}


_SF_SUBGENRES = ("Space Opera", "Hard Science Fiction", "Military Science Fiction", "Post-Apocalyptic", "Dystopian",
                 "First Contact", "Space Exploration", "Alien Invasion", "Time Travel")


def classify(books_labels: list[list[str]], extra_labels: Any = (), cap_sub: int = 5) -> tuple[list[str], list[str]]:
    """(main genres, subgenres) for a group of books, one label list per book.

    A genre needs support from 25% of the books that have any label (at least
    1). `extra_labels` are series-level labels (progressionfantasy.co.uk,
    HaremLit wiki) and count as full support.
    """
    labelled = sum(1 for labels in books_labels if labels) or 1
    threshold = 1 if labelled < 4 else math.ceil(0.25 * labelled)
    main: collections.Counter = collections.Counter()
    sub: collections.Counter = collections.Counter()
    for labels in books_labels:
        book_mains: set[str] = set()
        book_subs: set[str] = set()
        for label in labels:
            if label in LABEL_MAP:
                book_mains.update(LABEL_MAP[label][0])
                book_subs.update(LABEL_MAP[label][1])
        main.update(book_mains)
        sub.update(book_subs)
    for label in extra_labels:
        if label in LABEL_MAP:
            for m in LABEL_MAP[label][0]:
                main[m] = max(main[m], threshold)
            for s in LABEL_MAP[label][1]:
                sub[s] = max(sub[s], threshold)

    mains = [m for m in MAIN_ORDER if main[m] >= threshold]
    # Fantasy vs Science Fiction: keep both only when neither is under half the other.
    if "Fantasy" in mains and "Science Fiction" in mains:
        fantasy, scifi = main["Fantasy"], main["Science Fiction"]
        if min(fantasy, scifi) < 0.5 * max(fantasy, scifi):
            mains.remove("Fantasy" if fantasy < scifi else "Science Fiction")
    if "Young Adult" in mains and "Children's" in mains:
        mains.remove("Children's" if main["Children's"] < main["Young Adult"] else "Young Adult")
    # Audible files LitRPG under Science Fiction > Cyberpunk; without any real
    # SF subgenre that is a shelving artifact, not science fiction.
    if "LitRPG" in mains:
        if "Science Fiction" in mains and not sum(sub[s] for s in _SF_SUBGENRES):
            mains.remove("Science Fiction")
        if "Science Fiction" not in mains:
            sub["Cyberpunk"] = 0

    # Ambiguous subgenres ("Epic" alone, "Historical") resolve against the mains.
    if sub.get("Epic Fantasy?", 0) >= threshold and "Fantasy" not in mains and "Science Fiction" not in mains:
        mains.insert(0, "Fantasy")
    if sub.get("Epic Fantasy?"):
        if "Fantasy" in mains:
            sub["Epic Fantasy"] += sub["Epic Fantasy?"]
        del sub["Epic Fantasy?"]
    if sub.get("Historical?"):
        count = sub.pop("Historical?")
        if "Fantasy" in mains:
            sub["Historical Fantasy"] += count
        elif "Non-Fiction" in mains:
            sub["History"] += count
        elif count >= threshold and not ({"Science Fiction", "Thriller", "Mystery"} & set(mains)):
            mains.append("Historical Fiction")
    if "Military" in sub:
        count = sub.pop("Military")
        if "Science Fiction" in mains:
            sub["Military Science Fiction"] += count
        elif "Thriller" in mains:
            sub["Military Thriller"] += count
    if sub.get("Paranormal") and not mains:
        mains.append("Fantasy")
    if not mains and main:
        mains = [max(main, key=main.get)]
    subs = [s for s, c in sorted(sub.items(), key=lambda kv: (-kv[1], kv[0])) if c >= threshold and s not in mains][:cap_sub]
    return mains, subs
