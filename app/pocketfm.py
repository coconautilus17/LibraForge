"""Pocket FM show metadata, read from the public show page.

Pocket FM publishes audio series (Supreme Magus, Shadow Slave, ...) that
Audible doesn't carry. Its API (api.pocketfm.com) requires an app session,
so LibraForge reads only the public show page a browser gets, whose
schema.org PodcastSeries block holds the series-level metadata. There is no
public search, so a show is looked up by its link; Pocket FM has no volumes,
so book numbers come from the local folders.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from app.manual_candidates import build_manual_candidate_row

SHOW_URL = "https://pocketfm.com/show/{show_id}"
_SHOW_ID_RE = re.compile(
    r"^(?:(?:https?://)?(?:www\.)?pocketfm\.com/show/)?(?P<id>[0-9a-f]{40})/?(?:[?#].*)?$",
    re.IGNORECASE,
)
_LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)
# Credits that name no author: Pocket FM's placeholders and its AI voice.
_PLACEHOLDER_CREATORS = {"anonymous", "new", "pocket fm", "unknown", "virtual voice"}
_LANGUAGES = {
    "de": "German", "en": "English", "es": "Spanish", "fr": "French", "hi": "Hindi",
    "it": "Italian", "ja": "Japanese", "pt": "Portuguese",
}


def parse_show_id(value: str) -> str:
    """The 40-hex show id from a pocketfm.com/show/ link or a bare id, else ""."""
    match = _SHOW_ID_RE.match(str(value or "").strip())
    return match.group("id").lower() if match else ""


def parse_show_page(page: str) -> dict[str, Any]:
    """Series metadata from the page's PodcastSeries block ({} when absent)."""
    for block in _LD_JSON_RE.findall(page or ""):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if not isinstance(item, dict) or item.get("@type") != "PodcastSeries":
                continue
            creators = [
                str(c.get("name") or "").strip()
                for c in item.get("creator") or []
                if isinstance(c, dict)
            ]
            author = next((c for c in creators if c and c.lower() not in _PLACEHOLDER_CREATORS), "")
            genres = item.get("genre") or []
            language = str(item.get("inLanguage") or "").strip().lower()
            return {
                "title": str(item.get("name") or "").strip(),
                "author": author,
                "genre": ", ".join(g.strip() for g in (genres if isinstance(genres, list) else [genres]) if g.strip()),
                "language": _LANGUAGES.get(language, language),
                "year": str(item.get("datePublished") or "")[:4],
                "cover_url": str(item.get("image") or ""),
                "summary": str(item.get("description") or "").strip(),
                "episodes": item.get("numberOfEpisodes"),
            }
    return {}


def fetch_show(show_id: str, timeout: int = 20) -> dict[str, Any]:
    """Fetch and parse one public show page."""
    request = urllib.request.Request(
        SHOW_URL.format(show_id=show_id),
        headers={"User-Agent": "Mozilla/5.0 (LibraForge)", "Accept": "text/html"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_show_page(response.read().decode("utf-8", errors="replace"))


def show_to_manual_row(show: dict[str, Any], link: str) -> dict[str, Any]:
    """A Manual Review result row for the show as a series. The title is the
    show's name; the book's own title and number are set per book."""
    return build_manual_candidate_row(
        provider="pocketfm",
        query=link,
        title=show.get("title", ""),
        author=show.get("author", ""),
        series=show.get("title", ""),
        year=show.get("year", ""),
        cover_url=show.get("cover_url", ""),
        summary=show.get("summary", ""),
        genre=show.get("genre", ""),
        language=show.get("language", ""),
    )
