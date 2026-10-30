import sqlite3

import pytest


def _user(store, n=1):
    return store.create_user(f"u{n}@example.com", f"Käyttäjä {n}")


def _book(store, title="Kalevala", author="Elias Lönnrot", **kw):
    return store.create_book(title, author, **kw)


def test_create_and_get_book(store):
    u = _user(store)
    b = _book(store, year=1835, isbn="123", summary="Eepos", created_by=u["id"])
    assert b["source"] == "manual" and b["source_id"] is None
    assert store.get_book(b["id"])["title"] == "Kalevala"
    assert store.get_book(999) is None


def test_list_books_search_ignores_case_incl_scandinavian_letters(store):
    _book(store, "Ääretön", "Matti Meikäläinen")
    _book(store, "Kalevala", "Elias Lönnrot")
    assert [b["title"] for b in store.list_books("ÄÄRET")] == ["Ääretön"]
    assert [b["title"] for b in store.list_books("lönnrot")] == ["Kalevala"]
    assert len(store.list_books()) == 2
    assert store.list_books("ei löydy") == []


def test_rating_must_be_1_to_5_or_null(store):
    u, b = _user(store), _book(store)
    store.create_entry(u["id"], b["id"], "2026-01-01", rating=None)
    store.create_entry(u["id"], b["id"], "2026-01-02", rating=5)
    for bad in (0, 6):
        with pytest.raises(sqlite3.IntegrityError):
            store.create_entry(u["id"], b["id"], "2026-01-03", rating=bad)


def test_foreign_keys_enforced(store):
    u = _user(store)
    with pytest.raises(sqlite3.IntegrityError):
        store.create_entry(u["id"], 999, "2026-01-01")


def test_sorting_newest_title_author(store):
    u = _user(store)
    banaani = _book(store, "banaani", "Zed")
    aapinen = _book(store, "Aapinen", "Yrjö")
    zorro = _book(store, "Zorro", "Ahti")
    aani = _book(store, "ääni", "Åke")
    for book, day in [
        (banaani, "2026-03-01"),
        (aapinen, "2026-01-01"),
        (zorro, "2026-04-01"),
        (aani, "2026-02-01"),
    ]:
        store.create_entry(u["id"], book["id"], day)

    def titles(sort):
        return [e["book"]["title"] for e in store.list_entries(sort=sort)]

    assert titles("newest") == ["Zorro", "banaani", "ääni", "Aapinen"]
    # Kirjainkoosta riippumaton: b ennen Z:aa, ä/å Z:n jälkeen.
    assert titles("title") == ["Aapinen", "banaani", "Zorro", "ääni"]
    assert titles("author") == ["Zorro", "Aapinen", "banaani", "ääni"]  # Ahti, Yrjö, Zed, Åke


def test_same_book_sorted_newest_first_within_title(store):
    u, b = _user(store), _book(store)
    store.create_entry(u["id"], b["id"], "2026-01-01", note="vanha")
    store.create_entry(u["id"], b["id"], "2026-05-01", note="uusi")
    assert [e["note"] for e in store.list_entries(sort="title")] == ["uusi", "vanha"]


def test_filters_by_user_and_book(store):
    u1, u2 = _user(store, 1), _user(store, 2)
    b1, b2 = _book(store, "A", "x"), _book(store, "B", "y")
    store.create_entry(u1["id"], b1["id"], "2026-01-01")
    store.create_entry(u2["id"], b1["id"], "2026-01-02")
    store.create_entry(u2["id"], b2["id"], "2026-01-03")
    assert len(store.list_entries()) == 3
    assert len(store.list_entries(user_id=u2["id"])) == 2
    assert len(store.list_entries(book_id=b1["id"])) == 2
    assert len(store.list_entries(user_id=u2["id"], book_id=b2["id"])) == 1


def test_unknown_sort_raises(store):
    with pytest.raises(ValueError):
        store.list_entries(sort="x; DROP TABLE entries")


def test_entry_contains_user_and_book_info(store):
    u, b = _user(store), _book(store, year=1835)
    e = store.create_entry(u["id"], b["id"], "2026-01-01", "hyvä", 4)
    assert e["user_name"] == "Käyttäjä 1"
    assert e["book"] == {
        "id": b["id"], "title": "Kalevala", "author": "Elias Lönnrot",
        "year": 1835, "has_cover": False,
    }
    store.set_cover_path(b["id"], f"{b['id']}.jpg")
    assert store.get_entry(e["id"])["book"]["has_cover"] is True
    assert (e["note"], e["rating"], e["read_on"]) == ("hyvä", 4, "2026-01-01")


def test_update_entry(store):
    u, b = _user(store), _book(store)
    e = store.create_entry(u["id"], b["id"], "2026-01-01", "a", 3)
    upd = store.update_entry(e["id"], "2026-02-02", "b", None)
    assert (upd["read_on"], upd["note"], upd["rating"]) == ("2026-02-02", "b", None)
    assert upd["created_at"] == e["created_at"]
    assert upd["updated_at"] >= e["updated_at"]


def test_delete_entry_removes_orphan_book_only_when_last(store):
    u1, u2 = _user(store, 1), _user(store, 2)
    b = _book(store)
    e1 = store.create_entry(u1["id"], b["id"], "2026-01-01")
    e2 = store.create_entry(u2["id"], b["id"], "2026-01-02")
    assert store.delete_entry(e1["id"]) is None
    assert store.get_book(b["id"]) is not None
    orphan = store.delete_entry(e2["id"])
    assert orphan["id"] == b["id"]
    assert store.get_book(b["id"]) is None
    assert store.list_entries() == []


def test_delete_missing_entry_is_noop(store):
    assert store.delete_entry(123) is None


def test_get_book_by_source_and_unique_constraint(store):
    b = _book(store, source="finna", source_id="fikka.1", author_bio_source="https://x.example")
    assert store.get_book_by_source("finna", "fikka.1")["id"] == b["id"]
    assert store.get_book_by_source("finna", "fikka.2") is None
    assert store.get_book_by_source("openlibrary", "fikka.1") is None
    with pytest.raises(sqlite3.IntegrityError):
        _book(store, source="finna", source_id="fikka.1")
    # Käsin lisätyillä (source_id NULL) ei ole uniikkiutta.
    _book(store)
    _book(store)


def test_set_cover_path(store):
    b = _book(store)
    assert b["cover_path"] is None
    store.set_cover_path(b["id"], f"{b['id']}.png")
    assert store.get_book(b["id"])["cover_path"] == f"{b['id']}.png"
    store.set_cover_path(b["id"], None)
    assert store.get_book(b["id"])["cover_path"] is None


def test_migration_adds_author_bio_source_to_old_database(tmp_path):
    """Vaiheen 1 tietokanta (ilman author_bio_source-saraketta) päivittyy käynnistyksessä."""
    from store import Store

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL DEFAULT 'manual',
            source_id TEXT, title TEXT NOT NULL, author TEXT NOT NULL, year INTEGER, isbn TEXT,
            summary TEXT NOT NULL DEFAULT '', author_bio TEXT NOT NULL DEFAULT '', cover_path TEXT,
            created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, UNIQUE(source, source_id));
        INSERT INTO books (title, author, created_at) VALUES ('Vanha', 'Kirjoittaja', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    store = Store(path)
    old = store.get_book(1)
    assert old["title"] == "Vanha" and old["author_bio_source"] is None
    new = store.create_book("Uusi", "X", author_bio_source="https://example.org")
    assert new["author_bio_source"] == "https://example.org"
    Store(path)  # toinen käynnistys ei kaadu (sarake on jo olemassa)
