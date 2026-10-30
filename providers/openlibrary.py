"""Open Library – kansainvälinen täydennys sekä kirjailijan esittely.

Dokumentaatio: https://openlibrary.org/dev/docs/api/search
Käyttöohje: tunnista itsesi User-Agentilla ja vältä sadan pyynnön sarjoja.
Siksi haku on yksi pyyntö, ja tarkat tiedot haetaan vain valitulle kirjalle.
"""
from __future__ import annotations

import re

from . import (
    UNKNOWN_AUTHOR,
    BookResult,
    ProviderError,
    get_json,
    parse_year,
    pick_isbn,
)

OL_BASE = "https://openlibrary.org"
COVERS_BASE = "https://covers.openlibrary.org"
SEARCH_FIELDS = "key,title,author_name,author_key,first_publish_year,isbn,cover_i"

_WORK_KEY = re.compile(r"^/works/(OL\d+W)$")
_WORK_ID = re.compile(r"^OL\d+W$")
_AUTHOR_KEY = re.compile(r"^/authors/(OL\d+A)$")
_SOURCES_SEPARATOR = re.compile(r"\n-{3,}")


def _text(value) -> str:
    """Open Libraryn teksti on joko merkkijono tai {'type': ..., 'value': ...}."""
    if isinstance(value, dict):
        value = value.get("value")
    return value.strip() if isinstance(value, str) else ""


def _cover_url(cover_id) -> str | None:
    if isinstance(cover_id, int) and cover_id > 0:
        # default=false: puuttuvasta kannesta tulee 404 eikä paikkamerkkikuvaa.
        return f"{COVERS_BASE}/b/id/{cover_id}-L.jpg?default=false"
    return None


class OpenLibraryProvider:
    name = "openlibrary"

    def __init__(self, http, base: str = OL_BASE):
        self.http = http
        self.base = base

    def search(self, query: str, limit: int = 10) -> list[BookResult]:
        data = get_json(
            self.http,
            f"{self.base}/search.json",
            params={"q": query, "limit": limit, "fields": SEARCH_FIELDS},
        )
        docs = data.get("docs") if isinstance(data, dict) else None
        results: list[BookResult] = []
        for doc in docs or []:
            if not isinstance(doc, dict):
                continue
            match = _WORK_KEY.match(str(doc.get("key") or ""))
            title = str(doc.get("title") or "").strip()
            if not match or not title:
                continue
            authors = doc.get("author_name")
            author = authors[0] if isinstance(authors, list) and authors else UNKNOWN_AUTHOR
            results.append(
                BookResult(
                    source=self.name,
                    source_id=match.group(1),
                    title=title,
                    author=str(author).strip() or UNKNOWN_AUTHOR,
                    year=parse_year(doc.get("first_publish_year")),
                    isbn=pick_isbn(doc.get("isbn")),
                    cover_url=_cover_url(doc.get("cover_i")),
                )
            )
        return results

    def get(self, source_id: str) -> BookResult | None:
        if not _WORK_ID.match(source_id):
            return None
        work = get_json(self.http, f"{self.base}/works/{source_id}.json", allow_404=True)
        if not isinstance(work, dict):
            return None
        title = str(work.get("title") or "").strip()
        if not title:
            return None

        covers = [c for c in work.get("covers") or [] if isinstance(c, int) and c > 0]
        author_name, bio, bio_url = UNKNOWN_AUTHOR, "", None
        author_olid = self._first_author_olid(work)
        if author_olid:
            try:
                author = get_json(
                    self.http, f"{self.base}/authors/{author_olid}.json", allow_404=True
                )
            except ProviderError:
                author = None  # kirja kelpaa ilman kirjailijan lisätietoja
            if isinstance(author, dict):
                author_name = str(author.get("name") or "").strip() or UNKNOWN_AUTHOR
                bio = _SOURCES_SEPARATOR.split(_text(author.get("bio")).replace("\r\n", "\n"))[0].strip()
                if bio:
                    bio_url = f"{self.base}/authors/{author_olid}"

        return BookResult(
            source=self.name,
            source_id=source_id,
            title=title,
            author=author_name,
            year=parse_year(work.get("first_publish_date")),
            summary=_text(work.get("description")),
            cover_url=_cover_url(covers[0]) if covers else None,
            author_bio=bio,
            author_bio_source=bio_url,
        )

    @staticmethod
    def _first_author_olid(work: dict) -> str | None:
        for entry in work.get("authors") or []:
            if not isinstance(entry, dict):
                continue
            ref = entry.get("author") if isinstance(entry.get("author"), dict) else entry
            match = _AUTHOR_KEY.match(str(ref.get("key") or ""))
            if match:
                return match.group(1)
        return None
