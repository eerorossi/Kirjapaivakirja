"""API-testit kirjahaulle, tuonnille ja kansikuville (feikkilähteet, ei verkkoa)."""
import os

import httpx
import pytest
from fakes import Fake, FakeWiki, result
from fastapi.testclient import TestClient
from helpers import auth

from main import create_app
from service import BookService

A = auth("a@example.com", "Aino")
B = auth("b@example.com", "Bertta")
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000
COVER_URL = "https://api.finna.fi/Cover/Show?id=fikka.1&index=0&size=large"


def cover_http(body=JPEG, status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, content=body)))


@pytest.fixture
def env(store, tmp_path):
    """(client, covers_dir, provider, wiki). Kirjan fikka.1 tiedot löytyvät feikkilähteestä."""
    book = result(
        "fikka", "fikka.1", "Tuntematon sotilas", "Väinö Linna",
        year=1954, isbn="978-951", summary="Sotaromaani.", cover_url=COVER_URL,
    )
    provider = Fake("fikka", results=[book], details={"fikka.1": book})
    wiki = FakeWiki(("Linna oli kirjailija.", "https://fi.wikipedia.org/wiki/V%C3%A4in%C3%B6_Linna"))
    service = BookService([provider], wiki, cover_http())
    covers_dir = str(tmp_path / "covers")
    with TestClient(create_app(store, service, covers_dir)) as client:
        yield client, covers_dir, provider, wiki


def import_book(client, headers=A, source="fikka", source_id="fikka.1"):
    return client.post("/api/books/import", json={"source": source, "source_id": source_id}, headers=headers)


# --- haku ----------------------------------------------------------------


def test_search_requires_auth_and_min_length(env):
    client, *_ = env
    assert client.get("/api/books/search", params={"q": "linna"}).status_code == 401
    assert client.get("/api/books/search", params={"q": "l"}, headers=A).status_code == 422
    assert client.get("/api/books/search", params={"q": " l "}, headers=A).status_code == 422
    assert client.get("/api/books/search", headers=A).status_code == 422


def test_search_returns_results_and_unavailable_sources(env, store, tmp_path):
    client, *_ = env
    body = client.get("/api/books/search", params={"q": "linna"}, headers=A).json()
    assert body["unavailable"] == []
    (r,) = body["results"]
    assert (r["source"], r["source_id"], r["title"], r["author"]) == ("fikka", "fikka.1", "Tuntematon sotilas", "Väinö Linna")

    down = BookService([Fake("fikka", fail=True), Fake("ol", [result("ol", "OL1W")])])
    with TestClient(create_app(store, down, str(tmp_path / "c"))) as c2:
        body = c2.get("/api/books/search", params={"q": "linna"}, headers=A).json()
    assert body["unavailable"] == ["fikka"] and len(body["results"]) == 1


def test_search_route_is_not_shadowed_by_book_id_route(env):
    client, *_ = env
    assert client.get("/api/books/search", params={"q": "linna"}, headers=A).status_code == 200


# --- tuonti ----------------------------------------------------------------


def test_import_creates_book_with_details_bio_and_cover(env):
    client, covers_dir, _, wiki = env
    r = import_book(client)
    assert r.status_code == 201, r.text
    book = r.json()
    assert (book["title"], book["author"], book["year"], book["isbn"]) == ("Tuntematon sotilas", "Väinö Linna", 1954, "978-951")
    assert book["summary"] == "Sotaromaani."
    assert book["author_bio"] == "Linna oli kirjailija."
    assert book["author_bio_source"] == "https://fi.wikipedia.org/wiki/V%C3%A4in%C3%B6_Linna"
    assert (book["source"], book["source_id"]) == ("fikka", "fikka.1")
    assert book["has_cover"] is True
    assert "cover_path" not in book  # levypolkua ei paljasteta
    assert os.listdir(covers_dir) == [f"{book['id']}.jpg"]
    assert wiki.calls == ["Väinö Linna"]


def test_import_twice_returns_existing_book(env):
    client, covers_dir, provider, wiki = env
    first = import_book(client, A)
    second = import_book(client, B)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get("/api/books", headers=A).json()) == 1
    assert wiki.calls == ["Väinö Linna"]  # toista hakua ei tehty


def test_import_without_cover_still_works(store, tmp_path):
    book = result("fikka", "fikka.2", "Ei kantta", "X", cover_url=None)
    service = BookService([Fake("fikka", details={"fikka.2": book})], None, cover_http())
    with TestClient(create_app(store, service, str(tmp_path / "c"))) as client:
        r = import_book(client, source_id="fikka.2")
        assert r.status_code == 201 and r.json()["has_cover"] is False
        assert client.get(f"/api/books/{r.json()['id']}/cover", headers=A).status_code == 404


def test_import_with_broken_cover_download_keeps_book(store, tmp_path):
    book = result("fikka", "fikka.3", "Rikkinäinen kansi", "X", cover_url=COVER_URL)
    service = BookService([Fake("fikka", details={"fikka.3": book})], None, cover_http(status=500))
    with TestClient(create_app(store, service, str(tmp_path / "c"))) as client:
        r = import_book(client, source_id="fikka.3")
        assert r.status_code == 201 and r.json()["has_cover"] is False


def test_import_validation_and_errors(env, store, tmp_path):
    client, *_ = env
    assert import_book(client, source="tuntematon").status_code == 422
    for bad in ("../x", "a b", "a/b", "", "x" * 101, "id;drop"):
        assert import_book(client, source_id=bad).status_code == 422, bad
    assert client.post("/api/books/import", json={"source": "fikka"}, headers=A).status_code == 422
    assert client.post("/api/books/import", json={"source": "fikka", "source_id": "a"}).status_code == 401
    assert import_book(client, source_id="fikka.404").status_code == 404

    down = BookService([Fake("fikka", get_fail=True)])
    with TestClient(create_app(store, down, str(tmp_path / "c"))) as c2:
        assert import_book(c2).status_code == 502


def test_client_cannot_inject_cover_url_or_fields(env):
    """Asiakas voi antaa vain source+source_id; ylimääräiset kentät (esim. cover_url) ohitetaan."""
    client, covers_dir, *_ = env
    r = client.post(
        "/api/books/import",
        json={"source": "fikka", "source_id": "fikka.1", "cover_url": "http://169.254.169.254/", "title": "Hakkeroitu"},
        headers=A,
    )
    assert r.status_code == 201 and r.json()["title"] == "Tuntematon sotilas"


# --- kansikuva ---------------------------------------------------------------


def test_cover_served_with_right_type_to_any_user(env):
    client, *_ = env
    book = import_book(client, A).json()
    r = client.get(f"/api/books/{book['id']}/cover", headers=B)
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 401
    assert client.get("/api/books/999/cover", headers=A).status_code == 404


def test_manual_book_has_no_cover(env):
    client, *_ = env
    book = client.post("/api/books", json={"title": "T", "author": "A"}, headers=A).json()
    assert book["has_cover"] is False
    assert client.get(f"/api/books/{book['id']}/cover", headers=A).status_code == 404


def test_cover_removed_when_last_entry_deleted(env):
    client, covers_dir, *_ = env
    book = import_book(client, A).json()
    entries = [
        client.post("/api/entries", json={"book_id": book["id"], "read_on": "2026-10-01"}, headers=h).json()
        for h in (A, B)
    ]
    assert os.listdir(covers_dir) == [f"{book['id']}.jpg"]
    client.delete(f"/api/entries/{entries[0]['id']}", headers=A)
    assert os.listdir(covers_dir) == [f"{book['id']}.jpg"]  # B:n kirjaus vielä jäljellä
    client.delete(f"/api/entries/{entries[1]['id']}", headers=B)
    assert os.listdir(covers_dir) == []
    assert client.get(f"/api/books/{book['id']}", headers=A).status_code == 404


def test_entry_includes_has_cover(env):
    client, *_ = env
    book = import_book(client, A).json()
    entry = client.post("/api/entries", json={"book_id": book["id"], "read_on": "2026-10-01"}, headers=A).json()
    assert entry["book"]["has_cover"] is True
    assert client.get("/api/entries", headers=A).json()[0]["book"]["has_cover"] is True
