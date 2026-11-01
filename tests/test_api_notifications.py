"""Ilmoitusten jonotus API-toiminnoista ja ilmoitusasetukset."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import notifier
from helpers import auth
from main import create_app
from test_api import make_book, make_entry
from test_notifier import CONFIG, FakeMailer

A = auth("a@example.com", "Aino Ääkkönen")
B = auth("b@example.com", "Bertta")
C = auth("c@example.com", "Cecilia")
LATER = datetime.now(timezone.utc) + timedelta(days=1)


@pytest.fixture
def mail_client(store):
    mailer = FakeMailer()
    app = create_app(store, mail_config=CONFIG, mailer=mailer, start_notifier=False)
    with TestClient(app) as client:
        for headers in (A, B, C):  # luo käyttäjät
            client.get("/api/me", headers=headers)
        client.mailer = mailer
        yield client


def queued(store, kind=None):
    rows = store.due_notifications(LATER.isoformat())
    return [r for r in rows if kind is None or r["kind"] == kind]


def send_all(store, client):
    notifier.process_due(store, client.mailer, CONFIG, LATER)
    return client.mailer.sent


def test_nothing_is_queued_when_email_is_not_configured(client, store):
    client.get("/api/me", headers=B)
    make_entry(client, make_book(client, A)["id"], A)
    assert queued(store) == []
    assert client.get("/api/settings", headers=A).json()["email_enabled"] is False


def test_new_entry_notifies_everyone_but_the_author(mail_client, store):
    make_entry(mail_client, make_book(mail_client, A)["id"], A)
    mails = send_all(store, mail_client)
    assert sorted(m[0] for m in mails) == ["b@example.com", "c@example.com"]
    assert all("kirjasi kirjan Kalevala" in m[1] for m in mails)


def test_new_entry_respects_opt_out(mail_client, store):
    mail_client.put("/api/settings", json={"notify_new_books": False, "notify_comments": True, "notify_likes": True}, headers=B)
    make_entry(mail_client, make_book(mail_client, A)["id"], A)
    assert [m[0] for m in send_all(store, mail_client)] == ["c@example.com"]


def test_comment_notifies_entry_owner_only_for_others_comments(mail_client, store):
    entry = make_entry(mail_client, make_book(mail_client, A)["id"], A)
    send_all(store, mail_client)  # tyhjennä uuden kirjauksen viestit
    mail_client.mailer.sent.clear()
    mail_client.post(f"/api/entries/{entry['id']}/comments", json={"body": "Hieno!"}, headers=B)
    mail_client.post(f"/api/entries/{entry['id']}/comments", json={"body": "Kiitos!"}, headers=A)  # oma kommentti
    mails = send_all(store, mail_client)
    assert [(m[0], m[1].split(":")[0]) for m in mails] == [("a@example.com", "Bertta kommentoi kirjaustasi")]
    assert "Hieno!" in mails[0][2]


def test_like_is_delayed_deduplicated_and_never_for_own_entry(mail_client, store):
    entry = make_entry(mail_client, make_book(mail_client, A)["id"], A)
    url = f"/api/entries/{entry['id']}/like"
    mail_client.put(url, headers=B)
    mail_client.put(url, headers=B)            # toinen peukutus ei tuplaa
    mail_client.delete(url, headers=B)
    mail_client.put(url, headers=B)            # peru ja lisää uudelleen: ei uutta ilmoitusta
    mail_client.put(url, headers=A)            # oma kirjaus: ei ilmoitusta
    likes = queued(store, "like")
    assert len(likes) == 1 and likes[0]["recipient_id"] == store.get_user_by_email("a@example.com")["id"]
    assert likes[0]["send_after"] > datetime.now(timezone.utc).isoformat()  # viive: ei lähde heti


def test_queue_failure_never_breaks_the_action(mail_client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("jono rikki")

    monkeypatch.setattr(notifier, "queue_new_entry", boom)
    book = make_book(mail_client, A)
    r = mail_client.post("/api/entries", json={"book_id": book["id"], "read_on": "2026-10-01"}, headers=A)
    assert r.status_code == 201


def test_settings_roundtrip_and_validation(mail_client):
    assert mail_client.get("/api/settings").status_code == 401
    assert mail_client.get("/api/settings", headers=A).json() == {
        "email_enabled": True, "notify_new_books": True, "notify_comments": True, "notify_likes": True,
    }
    body = {"notify_new_books": False, "notify_comments": True, "notify_likes": False}
    assert mail_client.put("/api/settings", json=body, headers=A).json() == {"email_enabled": True, **body}
    assert mail_client.get("/api/settings", headers=A).json()["notify_likes"] is False
    assert mail_client.get("/api/settings", headers=B).json()["notify_likes"] is True  # käyttäjäkohtainen
    assert mail_client.put("/api/settings", json={"notify_new_books": True}, headers=A).status_code == 422
