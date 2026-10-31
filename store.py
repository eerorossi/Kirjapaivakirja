from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'manual',
    source_id TEXT,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    year INTEGER,
    isbn TEXT,
    summary TEXT NOT NULL DEFAULT '',
    summary_source TEXT,
    author_bio TEXT NOT NULL DEFAULT '',
    author_bio_source TEXT,
    cover_path TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    book_id INTEGER NOT NULL REFERENCES books(id),
    read_on TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_read_on ON entries(read_on);
CREATE INDEX IF NOT EXISTS idx_entries_user ON entries(user_id);
CREATE INDEX IF NOT EXISTS idx_entries_book ON entries(book_id);

CREATE TABLE IF NOT EXISTS likes (
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, user_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_entry ON comments(entry_id, id);
"""

# Sallitut lajittelut (S5). Kirjan nimi ja kirjailija lajitellaan
# kirjainkoosta riippumatta (FOLD-kollaatio, ks. _connect).
SORT_ORDERS = {
    "newest": "entries.read_on DESC, entries.id DESC",
    "title": "books.title COLLATE FOLD ASC, entries.read_on DESC, entries.id DESC",
    "author": (
        "books.author COLLATE FOLD ASC, books.title COLLATE FOLD ASC, "
        "entries.read_on DESC, entries.id DESC"
    ),
}

_ENTRY_SELECT = (
    "SELECT entries.*, users.display_name AS user_name, "
    "books.title AS book_title, books.author AS book_author, books.year AS book_year, "
    "(books.cover_path IS NOT NULL) AS book_has_cover, "
    "(SELECT COUNT(*) FROM likes WHERE likes.entry_id = entries.id) AS like_count, "
    "(SELECT COUNT(*) FROM comments WHERE comments.entry_id = entries.id) AS comment_count "
    "FROM entries "
    "JOIN users ON users.id = entries.user_id "
    "JOIN books ON books.id = entries.book_id "
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fold(value: str | None) -> str:
    return (value or "").casefold()


def _fold_collation(a: str, b: str) -> int:
    a, b = _fold(a), _fold(b)
    return (a > b) - (a < b)


def _entry_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "read_on": row["read_on"],
        "note": row["note"],
        "rating": row["rating"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "like_count": row["like_count"],
        "comment_count": row["comment_count"],
        "liked_by_me": False,  # täydennetään _mark_liked:llä, kun katsoja tunnetaan
        "book": {
            "id": row["book_id"],
            "title": row["book_title"],
            "author": row["book_author"],
            "year": row["book_year"],
            "has_cover": bool(row["book_has_cover"]),
        },
    }


def _mark_liked(conn: sqlite3.Connection, entries: list[dict], viewer_id: int | None) -> list[dict]:
    """Merkitse, mitkä kirjauksista katsoja on peukuttanut (yksi kysely)."""
    if viewer_id is None or not entries:
        return entries
    marks = ",".join("?" * len(entries))
    liked = {
        row["entry_id"]
        for row in conn.execute(
            f"SELECT entry_id FROM likes WHERE user_id = ? AND entry_id IN ({marks})",
            [viewer_id, *(e["id"] for e in entries)],
        )
    }
    for entry in entries:
        entry["liked_by_me"] = entry["id"] in liked
    return entries


class Store:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("DB_PATH", "/app/data/kirjapaivakirja.db")
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = self._connect()
        conn.executescript(SCHEMA)
        self._migrate(conn)
        conn.commit()
        conn.close()

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Lisää myöhemmin tulleet sarakkeet jo olemassa olevaan tietokantaan
        (CREATE TABLE IF NOT EXISTS ei muuta vanhaa taulua)."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(books)")}
        if "author_bio_source" not in columns:
            conn.execute("ALTER TABLE books ADD COLUMN author_bio_source TEXT")
        if "summary_source" not in columns:
            conn.execute("ALTER TABLE books ADD COLUMN summary_source TEXT")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # SQLiten oma NOCASE/lower() käsittelee vain ASCII-merkit, joten
        # ä/ö/å tarvitsevat oman kollaation ja funktion.
        conn.create_collation("FOLD", _fold_collation)
        conn.create_function("fold", 1, _fold, deterministic=True)
        return conn

    @contextmanager
    def _session(self):
        """Yhteys, joka commitoidaan onnistuessa ja suljetaan aina."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- users ---------------------------------------------------------

    def get_user_by_email(self, email: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user(self, user_id: int) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_user(self, email: str, display_name: str) -> dict:
        conn = self._connect()
        cursor = conn.execute(
            "INSERT INTO users (email, display_name, created_at) VALUES (?, ?, ?)",
            (email, display_name, _now()),
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return self.get_user(user_id)

    def get_or_create_user(self, email: str, display_name: str) -> dict:
        user = self.get_user_by_email(email)
        if user is None:
            return self.create_user(email, display_name)
        if user["display_name"] != display_name:
            # Pidä nimi ajan tasalla Authelian kanssa.
            conn = self._connect()
            conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                (display_name, user["id"]),
            )
            conn.commit()
            conn.close()
            user["display_name"] = display_name
        return user

    def list_users(self) -> list[dict]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM users ORDER BY display_name").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # --- books ---------------------------------------------------------

    def create_book(
        self,
        title: str,
        author: str,
        *,
        year: int | None = None,
        isbn: str | None = None,
        summary: str = "",
        summary_source: str | None = None,
        author_bio: str = "",
        author_bio_source: str | None = None,
        source: str = "manual",
        source_id: str | None = None,
        cover_path: str | None = None,
        created_by: int | None = None,
    ) -> dict:
        with self._session() as conn:
            cursor = conn.execute(
                "INSERT INTO books (source, source_id, title, author, year, isbn, "
                "summary, summary_source, author_bio, author_bio_source, cover_path, "
                "created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source, source_id, title, author, year, isbn,
                    summary, summary_source, author_bio, author_bio_source, cover_path,
                    created_by, _now(),
                ),
            )
            return self._get_book(conn, cursor.lastrowid)

    @staticmethod
    def _get_book(conn: sqlite3.Connection, book_id: int) -> dict | None:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return dict(row) if row else None

    def get_book(self, book_id: int) -> dict | None:
        with self._session() as conn:
            return self._get_book(conn, book_id)

    def get_book_by_source(self, source: str, source_id: str) -> dict | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE source = ? AND source_id = ?",
                (source, source_id),
            ).fetchone()
            return dict(row) if row else None

    def set_cover_path(self, book_id: int, cover_path: str | None) -> None:
        with self._session() as conn:
            conn.execute(
                "UPDATE books SET cover_path = ? WHERE id = ?", (cover_path, book_id)
            )

    def set_summary(self, book_id: int, summary: str, source: str | None = None) -> None:
        with self._session() as conn:
            conn.execute(
                "UPDATE books SET summary = ?, summary_source = ? WHERE id = ?",
                (summary, source, book_id),
            )

    def list_books(self, q: str | None = None, limit: int = 50) -> list[dict]:
        """Hae omasta tietokannasta nimen tai kirjailijan osalla (ei ulkoista hakua)."""
        query = "SELECT * FROM books"
        params: list = []
        if q and q.strip():
            needle = _fold(q.strip())
            query += " WHERE instr(fold(title), ?) > 0 OR instr(fold(author), ?) > 0"
            params += [needle, needle]
        query += " ORDER BY title COLLATE FOLD, id LIMIT ?"
        params.append(limit)
        with self._session() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    # --- entries -------------------------------------------------------

    def list_entries(
        self,
        user_id: int | None = None,
        book_id: int | None = None,
        sort: str = "newest",
        viewer_id: int | None = None,
    ) -> list[dict]:
        if sort not in SORT_ORDERS:
            raise ValueError(f"Unknown sort: {sort}")
        query = _ENTRY_SELECT + "WHERE 1=1"
        params: list = []
        if user_id is not None:
            query += " AND entries.user_id = ?"
            params.append(user_id)
        if book_id is not None:
            query += " AND entries.book_id = ?"
            params.append(book_id)
        query += " ORDER BY " + SORT_ORDERS[sort]
        with self._session() as conn:
            entries = [_entry_dict(r) for r in conn.execute(query, params).fetchall()]
            return _mark_liked(conn, entries, viewer_id)

    def list_feed(
        self, viewer_id: int, before_id: int | None = None, limit: int = 20
    ) -> tuple[list[dict], int | None]:
        """Kaikkien käyttäjien kirjaukset, uusimmin kirjattu ensin (So1).

        Palauttaa (kirjaukset, next_before); next_before on None, kun lisää ei ole."""
        query = _ENTRY_SELECT + "WHERE 1=1"
        params: list = []
        if before_id is not None:
            query += " AND entries.id < ?"
            params.append(before_id)
        query += " ORDER BY entries.id DESC LIMIT ?"
        params.append(limit + 1)
        with self._session() as conn:
            entries = [_entry_dict(r) for r in conn.execute(query, params).fetchall()]
            more = len(entries) > limit
            entries = _mark_liked(conn, entries[:limit], viewer_id)
        return entries, (entries[-1]["id"] if more else None)

    @staticmethod
    def _get_entry(conn: sqlite3.Connection, entry_id: int) -> dict | None:
        row = conn.execute(
            _ENTRY_SELECT + "WHERE entries.id = ?", (entry_id,)
        ).fetchone()
        return _entry_dict(row) if row else None

    def get_entry(self, entry_id: int, viewer_id: int | None = None) -> dict | None:
        with self._session() as conn:
            entry = self._get_entry(conn, entry_id)
            if entry is not None:
                _mark_liked(conn, [entry], viewer_id)
            return entry

    # --- peukutukset (So2, So4) ---------------------------------------

    def add_like(self, entry_id: int, user_id: int) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO likes (entry_id, user_id, created_at) VALUES (?, ?, ?)",
                (entry_id, user_id, _now()),
            )

    def remove_like(self, entry_id: int, user_id: int) -> None:
        with self._session() as conn:
            conn.execute(
                "DELETE FROM likes WHERE entry_id = ? AND user_id = ?", (entry_id, user_id)
            )

    def count_likes(self, entry_id: int) -> int:
        with self._session() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM likes WHERE entry_id = ?", (entry_id,)
            ).fetchone()[0]

    def list_likers(self, entry_id: int) -> list[dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT likes.user_id, users.display_name AS user_name, likes.created_at "
                "FROM likes JOIN users ON users.id = likes.user_id "
                "WHERE likes.entry_id = ? ORDER BY likes.created_at, likes.user_id",
                (entry_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- kommentit (So3, So5) -----------------------------------------

    _COMMENT_SELECT = (
        "SELECT comments.id, comments.entry_id, comments.user_id, comments.body, "
        "comments.created_at, users.display_name AS user_name "
        "FROM comments JOIN users ON users.id = comments.user_id "
    )

    def add_comment(self, entry_id: int, user_id: int, body: str) -> dict:
        with self._session() as conn:
            cursor = conn.execute(
                "INSERT INTO comments (entry_id, user_id, body, created_at) VALUES (?, ?, ?, ?)",
                (entry_id, user_id, body, _now()),
            )
            row = conn.execute(
                self._COMMENT_SELECT + "WHERE comments.id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_comments(self, entry_id: int) -> list[dict]:
        with self._session() as conn:
            rows = conn.execute(
                self._COMMENT_SELECT + "WHERE comments.entry_id = ? ORDER BY comments.id",
                (entry_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_comment(self, comment_id: int) -> dict | None:
        with self._session() as conn:
            row = conn.execute(
                self._COMMENT_SELECT + "WHERE comments.id = ?", (comment_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_comment(self, comment_id: int) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))

    def create_entry(
        self,
        user_id: int,
        book_id: int,
        read_on: str,
        note: str = "",
        rating: int | None = None,
    ) -> dict:
        now = _now()
        with self._session() as conn:
            cursor = conn.execute(
                "INSERT INTO entries "
                "(user_id, book_id, read_on, note, rating, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, book_id, read_on, note, rating, now, now),
            )
            return self._get_entry(conn, cursor.lastrowid)

    def update_entry(
        self, entry_id: int, read_on: str, note: str, rating: int | None
    ) -> dict | None:
        with self._session() as conn:
            conn.execute(
                "UPDATE entries SET read_on = ?, note = ?, rating = ?, updated_at = ? "
                "WHERE id = ?",
                (read_on, note, rating, _now(), entry_id),
            )
            return self._get_entry(conn, entry_id)

    def delete_entry(self, entry_id: int) -> dict | None:
        """Poista kirjaus. Jos kirjalla ei ole enää kirjauksia, kirja poistetaan
        myös ja se palautetaan (vaihe 2: kansikuvan siivous levyltä).
        Palauttaa poistetun orpokirjan tai None."""
        with self._session() as conn:
            row = conn.execute(
                "SELECT book_id FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return None
            book_id = row["book_id"]
            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            remaining = conn.execute(
                "SELECT 1 FROM entries WHERE book_id = ? LIMIT 1", (book_id,)
            ).fetchone()
            if remaining is not None:
                return None
            orphan = self._get_book(conn, book_id)
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            return orphan
