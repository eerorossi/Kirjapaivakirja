from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("DB_PATH", "/app/data/kirjapaivakirja.db")
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = self._connect()
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

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
