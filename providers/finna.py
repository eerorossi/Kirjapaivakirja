"""Finna (Kansalliskirjasto) – suomalaiset kirjat ja kirjastojen metatiedot.

Rajapinta: https://api.finna.fi/v1 (ei avainta). Ajantasainen dokumentaatio:
https://api.finna.fi/v1?swagger
"""
from __future__ import annotations

from . import (
    UNKNOWN_AUTHOR,
    BookResult,
    get_json,
    normalize_author,
    parse_year,
    pick_isbn,
)

FINNA_BASE = "https://api.finna.fi"
FIELDS = ["id", "title", "nonPresenterAuthors", "year", "summary", "isbns", "images"]
AUTHOR_ROLES = ("kirjoittaja", "aut", "author", "tekijä")


class FinnaProvider:
    name = "finna"

    def __init__(self, http, base: str = FINNA_BASE):
        self.http = http
        self.base = base

    def search(self, query: str, limit: int = 10) -> list[BookResult]:
        params = [
            ("lookfor", query),
            ("type", "AllFields"),
            ("filter[]", 'format:"0/Book/"'),
            ("limit", str(limit)),
            ("lng", "fi"),
        ] + [("field[]", f) for f in FIELDS]
        data = get_json(self.http, f"{self.base}/v1/search", params=params)
        records = data.get("records") if isinstance(data, dict) else None
        results = (self._parse(r) for r in records or [] if isinstance(r, dict))
        return [r for r in results if r is not None]

    def get(self, source_id: str) -> BookResult | None:
        params = [("id", source_id)] + [("field[]", f) for f in FIELDS]
        data = get_json(self.http, f"{self.base}/v1/record", params=params, allow_404=True)
        records = data.get("records") if isinstance(data, dict) else None
        if not records or not isinstance(records[0], dict):
            return None
        return self._parse(records[0])

    def _parse(self, rec: dict) -> BookResult | None:
        record_id = rec.get("id")
        title = str(rec.get("title") or "").strip().rstrip(" /:").strip()
        if not record_id or not title:
            return None
        summary = rec.get("summary")
        if isinstance(summary, list):
            summary = "\n\n".join(str(s).strip() for s in summary if str(s).strip())
        return BookResult(
            source=self.name,
            source_id=str(record_id),
            title=title,
            author=self._author(rec.get("nonPresenterAuthors")),
            year=parse_year(rec.get("year")),
            isbn=pick_isbn(rec.get("isbns")),
            summary=str(summary or "").strip(),
            cover_url=self._cover(rec.get("images")),
        )

    @staticmethod
    def _author(authors) -> str:
        entries = [a for a in authors or [] if isinstance(a, dict) and a.get("name")]
        if not entries:
            return UNKNOWN_AUTHOR
        # Suosi varsinaista kirjoittajaa kuvittajan/toimittajan edelle.
        for entry in entries:
            role = str(entry.get("role") or "").casefold()
            if not role or role in AUTHOR_ROLES:
                return normalize_author(entry["name"]) or UNKNOWN_AUTHOR
        return normalize_author(entries[0]["name"]) or UNKNOWN_AUTHOR

    def _cover(self, images) -> str | None:
        if not isinstance(images, list) or not images or not isinstance(images[0], str):
            return None
        url = images[0]
        if url.startswith("/"):
            url = self.base + url
        if "size=" not in url:
            url += ("&" if "?" in url else "?") + "size=large"
        return url
