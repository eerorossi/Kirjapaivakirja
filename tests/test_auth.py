import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import create_app  # noqa: E402
from store import Store  # noqa: E402


@pytest.fixture
def client(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    with TestClient(create_app(store)) as c:
        yield c


def test_me_without_header_is_401(client):
    assert client.get("/api/me").status_code == 401


def test_me_creates_user_from_headers(client):
    # Authelia lähettää nimen UTF-8-tavuina; httpx koodaisi str-arvon ASCII:ksi.
    r = client.get(
        "/api/me",
        headers=[
            (b"remote-email", b"testi@example.com"),
            (b"remote-name", "Testi Käyttäjä".encode("utf-8")),
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "testi@example.com"
    assert body["display_name"] == "Testi Käyttäjä"
    again = client.get("/api/me", headers={"Remote-Email": "testi@example.com"}).json()
    assert again["id"] == body["id"]


def test_utf8_name_sent_as_raw_bytes(client):
    raw = "Åsa Öström".encode("utf-8")
    r = client.get("/api/me", headers=[(b"remote-email", b"asa@example.com"), (b"remote-name", raw)])
    assert r.json()["display_name"] == "Åsa Öström"


def test_name_falls_back_to_email_prefix(client):
    r = client.get("/api/me", headers={"Remote-Email": "matti.meikalainen@example.com"})
    assert r.json()["display_name"] == "matti.meikalainen"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Kirjapäiväkirja" in r.text
