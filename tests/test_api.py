from helpers import auth

A = auth("a@example.com", "Aino Ääkkönen")
B = auth("b@example.com", "Bertta")


def make_book(client, headers=A, **over):
    body = {"title": "Kalevala", "author": "Elias Lönnrot", **over}
    r = client.post("/api/books", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def make_entry(client, book_id, headers=A, **over):
    body = {"book_id": book_id, "read_on": "2026-10-01", "note": "hyvä", "rating": 4, **over}
    r = client.post("/api/entries", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# --- kirjat ------------------------------------------------------------


def test_books_require_auth(client):
    assert client.get("/api/books").status_code == 401
    assert client.post("/api/books", json={"title": "x", "author": "y"}).status_code == 401
    assert client.get("/api/entries").status_code == 401


def test_create_and_get_book(client):
    book = make_book(client, year=1835, isbn=" 978 ", summary=" Eepos ")
    assert book["title"] == "Kalevala" and book["year"] == 1835
    assert book["isbn"] == "978" and book["summary"] == "Eepos"
    assert client.get(f"/api/books/{book['id']}", headers=B).json()["id"] == book["id"]


def test_book_validation(client):
    for body in (
        {"title": "x"},
        {"author": "y"},
        {"title": "   ", "author": "y"},
        {"title": "x", "author": ""},
        {"title": "x", "author": "y", "year": 0},
    ):
        assert client.post("/api/books", json=body, headers=A).status_code == 422, body


def test_get_missing_book_is_404(client):
    assert client.get("/api/books/999", headers=A).status_code == 404


def test_list_books_search(client):
    make_book(client, title="Ääretön", author="X")
    make_book(client)
    r = client.get("/api/books", params={"q": "äärET"}, headers=A)
    assert [b["title"] for b in r.json()] == ["Ääretön"]
    assert len(client.get("/api/books", headers=A).json()) == 2


# --- kirjaukset --------------------------------------------------------


def test_create_entry(client):
    book = make_book(client)
    e = make_entry(client, book["id"])
    assert e["read_on"] == "2026-10-01" and e["rating"] == 4 and e["note"] == "hyvä"
    assert e["user_name"] == "Aino Ääkkönen"
    assert e["book"]["title"] == "Kalevala"


def test_entry_without_rating_or_note(client):
    book = make_book(client)
    r = client.post("/api/entries", json={"book_id": book["id"], "read_on": "2026-10-01"}, headers=A)
    assert r.status_code == 201
    assert r.json()["rating"] is None and r.json()["note"] == ""


def test_entry_validation(client):
    book = make_book(client)
    ok = {"book_id": book["id"], "read_on": "2026-10-01"}
    for bad in ({"rating": 0}, {"rating": 6}, {"read_on": "huomenna"}, {"read_on": None}):
        r = client.post("/api/entries", json={**ok, **bad}, headers=A)
        assert r.status_code == 422, bad
    assert client.post("/api/entries", json={"read_on": "2026-10-01"}, headers=A).status_code == 422


def test_entry_for_unknown_book_is_404(client):
    r = client.post("/api/entries", json={"book_id": 999, "read_on": "2026-10-01"}, headers=A)
    assert r.status_code == 404


def test_everyone_can_read_each_others_entries(client):
    e = make_entry(client, make_book(client)["id"])
    assert client.get(f"/api/entries/{e['id']}", headers=B).status_code == 200
    assert len(client.get("/api/entries", headers=B).json()) == 1
    assert client.get("/api/entries/999", headers=B).status_code == 404


def test_update_own_entry(client):
    e = make_entry(client, make_book(client)["id"])
    r = client.put(
        f"/api/entries/{e['id']}",
        json={"read_on": "2026-11-02", "note": "  uusi  ", "rating": None},
        headers=A,
    )
    assert r.status_code == 200
    assert (r.json()["read_on"], r.json()["note"], r.json()["rating"]) == ("2026-11-02", "uusi", None)


def test_cannot_update_or_delete_others_entry(client):
    e = make_entry(client, make_book(client)["id"], headers=A)
    body = {"read_on": "2026-11-02", "note": "hakkerointi"}
    assert client.put(f"/api/entries/{e['id']}", json=body, headers=B).status_code == 403
    assert client.delete(f"/api/entries/{e['id']}", headers=B).status_code == 403
    still = client.get(f"/api/entries/{e['id']}", headers=A).json()
    assert still["note"] == "hyvä"


def test_update_and_delete_missing_entry_is_404(client):
    body = {"read_on": "2026-11-02"}
    assert client.put("/api/entries/999", json=body, headers=A).status_code == 404
    assert client.delete("/api/entries/999", headers=A).status_code == 404


def test_delete_own_entry_and_orphan_book(client):
    book = make_book(client)
    e1 = make_entry(client, book["id"], headers=A)
    e2 = make_entry(client, book["id"], headers=B)
    assert client.delete(f"/api/entries/{e1['id']}", headers=A).status_code == 204
    assert client.get(f"/api/entries/{e1['id']}", headers=A).status_code == 404
    assert client.get(f"/api/books/{book['id']}", headers=A).status_code == 200
    assert client.delete(f"/api/entries/{e2['id']}", headers=B).status_code == 204
    assert client.get(f"/api/books/{book['id']}", headers=A).status_code == 404


def test_list_filters_and_sorting(client):
    kal = make_book(client, title="Kalevala", author="Lönnrot")
    aap = make_book(client, title="Aapinen", author="Cygnaeus")
    make_entry(client, kal["id"], headers=A, read_on="2026-01-01")
    make_entry(client, aap["id"], headers=A, read_on="2026-02-01")
    make_entry(client, kal["id"], headers=B, read_on="2026-03-01")

    def get(**params):
        r = client.get("/api/entries", params=params, headers=A)
        assert r.status_code == 200, r.text
        return r.json()

    assert [e["read_on"] for e in get()] == ["2026-03-01", "2026-02-01", "2026-01-01"]
    assert [e["book"]["title"] for e in get(sort="title")] == ["Aapinen", "Kalevala", "Kalevala"]
    assert [e["book"]["author"] for e in get(sort="author")] == ["Cygnaeus", "Lönnrot", "Lönnrot"]
    me_id = client.get("/api/me", headers=A).json()["id"]
    assert len(get(user_id=me_id)) == 2
    assert len(get(book_id=kal["id"])) == 2
    assert client.get("/api/entries", params={"sort": "satunnainen"}, headers=A).status_code == 422
