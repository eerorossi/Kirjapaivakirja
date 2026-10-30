from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import get_current_user
from store import Store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(min_length=1, max_length=300)
    year: Optional[int] = Field(default=None, ge=1, le=2200)
    isbn: Optional[str] = Field(default=None, max_length=32)
    summary: str = Field(default="", max_length=10000)


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


def _own_entry(store: Store, entry_id: int, user: dict) -> dict:
    """Hae kirjaus ja varmista, että se kuuluu kirjautuneelle käyttäjälle (S4)."""
    entry = store.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not your entry")
    return entry


def create_app(store: Store | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or Store()
        yield

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
        return store.list_books(q)

    @app.post("/api/books", status_code=201)
    def create_book(
        body: BookIn,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> dict:
        title, author = body.title.strip(), body.author.strip()
        if not title or not author:
            raise HTTPException(status_code=422, detail="Title and author are required")
        return store.create_book(
            title,
            author,
            year=body.year,
            isbn=(body.isbn or "").strip() or None,
            summary=body.summary.strip(),
            created_by=user["id"],
        )

    @app.get("/api/books/{book_id}")
    def get_book(
        book_id: int,
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> dict:
        book = store.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Book not found")
        return book

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
        user: dict = Depends(get_current_user),
        store: Store = Depends(get_store),
    ) -> Response:
        _own_entry(store, entry_id, user)
        store.delete_entry(entry_id)
        return Response(status_code=204)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return app


app = create_app()
