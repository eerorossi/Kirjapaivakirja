from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import get_current_user
from paths import base_href
from providers import ProviderError
from service import BookService, build_default_service
from store import Store

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

SOURCE_ID_RE = re.compile(r"[A-Za-z0-9._:\-]+")
COVER_MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(min_length=1, max_length=300)
    year: Optional[int] = Field(default=None, ge=1, le=2200)
    isbn: Optional[str] = Field(default=None, max_length=32)
    summary: str = Field(default="", max_length=10000)


class ImportIn(BaseModel):
    source: str = Field(min_length=1, max_length=40)
    source_id: str = Field(min_length=1, max_length=100)


class EntryIn(BaseModel):
    book_id: int
    read_on: date
    note: str = Field(default="", max_length=20000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)


class EntryUpdate(BaseModel):
    read_on: date
    note: str = Field(default="", max_length=20000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_books(request: Request) -> BookService:
    return request.app.state.books


def _public_book(book: dict) -> dict:
    """Kirja ulos API:sta: levypolkua ei paljasteta, vain tieto kannen olemassaolosta."""
    out = {k: v for k, v in book.items() if k != "cover_path"}
    out["has_cover"] = bool(book.get("cover_path"))
    return out


def _cover_file(covers_dir: str, book: dict | None) -> str | None:
    name = (book or {}).get("cover_path")
    if not name or os.path.basename(name) != name:
        return None
    path = os.path.join(covers_dir, name)
    return path if os.path.isfile(path) else None


def _remove_cover(covers_dir: str, book: dict) -> None:
    path = _cover_file(covers_dir, book)
    if path:
        try:
            os.remove(path)
        except OSError as exc:
            log.warning("Could not remove cover %s: %s", path, exc)


def _own_entry(store: Store, entry_id: int, user: dict) -> dict:
    """Hae kirjaus ja varmista, että se kuuluu kirjautuneelle käyttäjälle (S4)."""
    entry = store.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not your entry")
    return entry


def create_app(
    store: Store | None = None,
    books: BookService | None = None,
    covers_dir: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or Store()
        app.state.books = books or build_default_service()
        app.state.covers_dir = covers_dir or os.getenv("COVERS_DIR", "/app/data/covers")
        try:
            yield
        finally:
            if books is None:  # suljetaan vain itse luotu HTTP-asiakas
                app.state.books.close()

    app = FastAPI(title="Kirjapäiväkirja", lifespan=lifespan)

    @app.get("/api/me")
    def me(user: dict = Depends(get_current_user)) -> dict:
        return {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
        }

    # --- kirjat --------------------------------------------------------

    @app.get("/api/books")
    def list_books(
        q: Optional[str] = Query(default=None, max_length=200),
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> list[dict]:
        return [_public_book(b) for b in store.list_books(q)]

    @app.post("/api/books", status_code=201)
    def create_book(
        body: BookIn,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> dict:
        title, author = body.title.strip(), body.author.strip()
        if not title or not author:
            raise HTTPException(status_code=422, detail="Title and author are required")
        book = store.create_book(
            title,
            author,
            year=body.year,
            isbn=(body.isbn or "").strip() or None,
            summary=body.summary.strip(),
            created_by=user["id"],
        )
        return _public_book(book)

    # Huom: /search ja /import on määriteltävä ennen /{book_id}-reittejä.
    @app.get("/api/books/search")
    def search_books(
        q: str = Query(min_length=2, max_length=200),
        user: dict = Depends(get_current_user),
        books: BookService = Depends(get_books),
    ) -> dict:
        query = q.strip()
        if len(query) < 2:
            raise HTTPException(status_code=422, detail="Query too short")
        found = books.search(query)
        return {
            "results": [r.to_dict() for r in found["results"]],
            "unavailable": found["unavailable"],
        }

    @app.post("/api/books/import", status_code=201)
    def import_book(
        body: ImportIn,
        response: Response,
        request: Request,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
        books: BookService = Depends(get_books),
    ) -> dict:
        """Tallenna haettu kirja omaan tietokantaan (tiedot + kansikuva).

        Asiakas antaa vain lähteen ja tunnisteen; kaikki tiedot ja kansikuvan
        osoite haetaan palvelimella lähteestä."""
        if not books.has_source(body.source) or not SOURCE_ID_RE.fullmatch(body.source_id):
            raise HTTPException(status_code=422, detail="Unknown source or invalid source_id")

        existing = store.get_book_by_source(body.source, body.source_id)
        if existing:
            response.status_code = 200
            return _public_book(existing)

        try:
            result = books.fetch(body.source, body.source_id)
        except ProviderError as exc:
            log.warning("Import from %s failed: %s", body.source, exc)
            raise HTTPException(status_code=502, detail="Book source unavailable")
        if result is None:
            raise HTTPException(status_code=404, detail="Book not found in source")

        try:
            book = store.create_book(
                result.title,
                result.author,
                year=result.year,
                isbn=result.isbn,
                summary=result.summary,
                author_bio=result.author_bio,
                author_bio_source=result.author_bio_source,
                source=body.source,
                source_id=body.source_id,
                created_by=user["id"],
            )
        except sqlite3.IntegrityError:
            # Toinen käyttäjä ehti tuoda saman kirjan samaan aikaan.
            existing = store.get_book_by_source(body.source, body.source_id)
            if existing is None:
                raise
            response.status_code = 200
            return _public_book(existing)

        cover = books.download_cover(result)
        if cover:
            data, extension = cover
            covers_dir = request.app.state.covers_dir
            name = f"{book['id']}.{extension}"
            try:
                os.makedirs(covers_dir, exist_ok=True)
                with open(os.path.join(covers_dir, name), "wb") as handle:
                    handle.write(data)
                store.set_cover_path(book["id"], name)
            except OSError as exc:  # kirja kelpaa ilman kantta
                log.warning("Could not save cover for book %s: %s", book["id"], exc)
        return _public_book(store.get_book(book["id"]))

    @app.get("/api/books/{book_id}")
    def get_book(
        book_id: int,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> dict:
        book = store.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Book not found")
        return _public_book(book)

    @app.get("/api/books/{book_id}/cover")
    def book_cover(
        book_id: int,
        request: Request,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> FileResponse:
        path = _cover_file(request.app.state.covers_dir, store.get_book(book_id))
        if path is None:
            raise HTTPException(status_code=404, detail="No cover")
        extension = path.rsplit(".", 1)[-1]
        return FileResponse(
            path,
            media_type=COVER_MEDIA_TYPES.get(extension, "application/octet-stream"),
            headers={"Cache-Control": "private, max-age=86400"},
        )

    # --- kirjaukset ----------------------------------------------------

    @app.get("/api/entries")
    def list_entries(
        user_id: Optional[int] = None,
        book_id: Optional[int] = None,
        sort: Literal["newest", "title", "author"] = "newest",
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> list[dict]:
        return store.list_entries(user_id=user_id, book_id=book_id, sort=sort)

    @app.post("/api/entries", status_code=201)
    def create_entry(
        body: EntryIn,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> dict:
        if store.get_book(body.book_id) is None:
            raise HTTPException(status_code=404, detail="Book not found")
        return store.create_entry(
            user["id"], body.book_id, body.read_on.isoformat(),
            body.note.strip(), body.rating,
        )

    @app.get("/api/entries/{entry_id}")
    def get_entry(
        entry_id: int,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> dict:
        entry = store.get_entry(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        return entry

    @app.put("/api/entries/{entry_id}")
    def update_entry(
        entry_id: int,
        body: EntryUpdate,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> dict:
        _own_entry(store, entry_id, user)
        return store.update_entry(
            entry_id, body.read_on.isoformat(), body.note.strip(), body.rating
        )

    @app.delete("/api/entries/{entry_id}", status_code=204, response_class=Response)
    def delete_entry(
        entry_id: int,
        request: Request,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> Response:
        _own_entry(store, entry_id, user)
        orphan = store.delete_entry(entry_id)
        if orphan:  # viimeinen kirjaus poistui -> kirja ja sen kansikuva pois
            _remove_cover(request.app.state.covers_dir, orphan)
        return Response(status_code=204)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index(request: Request) -> HTMLResponse:
        # <base href> saa sovelluksen suhteelliset polut (api/..., static/...) toimimaan
        # myös polkuprefiksin (/kp) takana, vaikka sivu avattaisiin ilman loppukauttaviivaa.
        with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as handle:
            html = handle.read()
        href = base_href(request.headers.get("x-forwarded-prefix"))
        html = html.replace("<!--BASE-->", f'<base href="{href}">')
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
