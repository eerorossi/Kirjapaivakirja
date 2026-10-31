"""Vaihe 4: peukutukset, kommentit ja syöte (So1–So5)."""
from helpers import auth
from test_api import make_book, make_entry

A = auth("a@example.com", "Aino Ääkkönen")
B = auth("b@example.com", "Bertta")
C = auth("c@example.com", "Cecilia")


def entry_of(client, headers=A):
    return make_entry(client, make_book(client, headers)["id"], headers)


def test_social_endpoints_require_auth(client):
    e = entry_of(client)
    for method, path in (
        ("get", "/api/feed"),
        ("put", f"/api/entries/{e['id']}/like"),
        ("delete", f"/api/entries/{e['id']}/like"),
        ("get", f"/api/entries/{e['id']}/likes"),
        ("get", f"/api/entries/{e['id']}/comments"),
        ("post", f"/api/entries/{e['id']}/comments"),
        ("delete", "/api/comments/1"),
    ):
        assert getattr(client, method)(path).status_code == 401, (method, path)


def test_feed_shows_everyones_entries_newest_logged_first(client):
    first, second = entry_of(client, A), entry_of(client, B)
    feed = client.get("/api/feed", headers=C).json()
    assert [e["id"] for e in feed["entries"]] == [second["id"], first["id"]]
    assert feed["entries"][0]["user_name"] == "Bertta" and feed["next_before"] is None


def test_feed_pagination_and_limit_validation(client):
    ids = [entry_of(client, A)["id"] for _ in range(3)]
    page = client.get("/api/feed?limit=2", headers=A).json()
    assert [e["id"] for e in page["entries"]] == [ids[2], ids[1]] and page["next_before"] == ids[1]
    rest = client.get(f"/api/feed?limit=2&before={page['next_before']}", headers=A).json()
    assert [e["id"] for e in rest["entries"]] == [ids[0]] and rest["next_before"] is None
    for bad in ("limit=0", "limit=51"):
        assert client.get(f"/api/feed?{bad}", headers=A).status_code == 422


def test_like_toggle_is_idempotent_and_visible_in_feed(client):
    e = entry_of(client, A)
    url = f"/api/entries/{e['id']}/like"
    assert client.put(url, headers=B).json() == {"liked": True, "like_count": 1}
    assert client.put(url, headers=B).json() == {"liked": True, "like_count": 1}
    assert client.put(url, headers=C).json()["like_count"] == 2
    seen_by_b = client.get("/api/feed", headers=B).json()["entries"][0]
    assert seen_by_b["like_count"] == 2 and seen_by_b["liked_by_me"] is True
    assert client.get(f"/api/entries/{e['id']}", headers=A).json()["liked_by_me"] is False
    assert client.delete(url, headers=B).json() == {"liked": False, "like_count": 1}
    assert client.delete(url, headers=B).json() == {"liked": False, "like_count": 1}


def test_like_missing_entry_is_404(client):
    assert client.put("/api/entries/999/like", headers=A).status_code == 404
    assert client.delete("/api/entries/999/like", headers=A).status_code == 404


def test_only_entry_owner_sees_who_liked(client):
    e = entry_of(client, A)
    client.put(f"/api/entries/{e['id']}/like", headers=B)
    likers = client.get(f"/api/entries/{e['id']}/likes", headers=A)
    assert likers.status_code == 200 and [x["user_name"] for x in likers.json()] == ["Bertta"]
    assert client.get(f"/api/entries/{e['id']}/likes", headers=C).status_code == 403
    assert client.get("/api/entries/999/likes", headers=A).status_code == 404


def test_comment_create_list_and_validation(client):
    e = entry_of(client, A)
    url = f"/api/entries/{e['id']}/comments"
    made = client.post(url, json={"body": "  Hieno kirja!  "}, headers=B)
    assert made.status_code == 201
    body = made.json()
    assert body["body"] == "Hieno kirja!" and body["user_name"] == "Bertta" and body["can_delete"] is True
    listed = client.get(url, headers=C).json()
    assert [c["body"] for c in listed] == ["Hieno kirja!"] and listed[0]["can_delete"] is False
    assert client.get(f"/api/entries/{e['id']}", headers=C).json()["comment_count"] == 1
    for bad in ({"body": ""}, {"body": "   "}, {"body": "x" * 2001}, {}):
        assert client.post(url, json=bad, headers=B).status_code == 422, bad
    assert client.post("/api/entries/999/comments", json={"body": "x"}, headers=B).status_code == 404


def test_comment_text_is_stored_verbatim_not_interpreted(client):
    e = entry_of(client, A)
    text = '<img src=x onerror="alert(1)">'
    client.post(f"/api/entries/{e['id']}/comments", json={"body": text}, headers=B)
    assert client.get(f"/api/entries/{e['id']}/comments", headers=A).json()[0]["body"] == text


def test_comment_delete_by_author_or_entry_owner_only(client):
    e = entry_of(client, A)
    url = f"/api/entries/{e['id']}/comments"
    by_b = client.post(url, json={"body": "B:n"}, headers=B).json()
    by_c = client.post(url, json={"body": "C:n"}, headers=C).json()
    assert client.delete(f"/api/comments/{by_b['id']}", headers=C).status_code == 403  # ulkopuolinen
    assert client.delete(f"/api/comments/{by_b['id']}", headers=B).status_code == 204  # kirjoittaja
    assert client.delete(f"/api/comments/{by_c['id']}", headers=A).status_code == 204  # kirjauksen omistaja
    assert client.get(url, headers=A).json() == []
    assert client.delete(f"/api/comments/{by_b['id']}", headers=B).status_code == 404


def test_deleting_entry_removes_likes_and_comments(client):
    e = entry_of(client, A)
    client.put(f"/api/entries/{e['id']}/like", headers=B)
    c = client.post(f"/api/entries/{e['id']}/comments", json={"body": "x"}, headers=B).json()
    assert client.delete(f"/api/entries/{e['id']}", headers=A).status_code == 204
    assert client.delete(f"/api/comments/{c['id']}", headers=B).status_code == 404
