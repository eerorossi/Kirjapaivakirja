"""Ilmoitusjono ja viestit ilman verkkoa: FakeMailer kerää lähetetyt viestit."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import notifier
from email.header import decode_header, make_header
from email.utils import parseaddr
from notifier import MailConfig, SmtpMailer, build_message, one_line, process_due

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
CONFIG = MailConfig(host="rele", sender="Kirjapäiväkirja <ilmoitukset@example.com>", public_url="https://x.example/kp/")


def display(sender: str) -> tuple[str, str]:
    """(näkyvä nimi purettuna, osoite) From-arvosta."""
    name, address = parseaddr(sender)
    return str(make_header(decode_header(name))), address


class FakeMailer:
    def __init__(self, fail=0):
        self.sent, self.fail = [], fail

    def send(self, to, subject, body):
        if self.fail:
            self.fail -= 1
            raise ConnectionError("rele alhaalla")
        self.sent.append((to, subject, body))


@pytest.fixture
def world(store):
    a = store.create_user("a@example.com", "Aino Ääkkönen")
    b = store.create_user("b@example.com", "Bertta")
    c = store.create_user("c@example.com", "Cecilia")
    book = store.create_book("Täällä Pohjantähden alla", "Väinö Linna")
    entry = store.create_entry(a["id"], book["id"], "2026-10-30", note="Hieno.\n\nToinen kappale.", rating=4)
    return store, a, b, c, entry


def enqueue(store, kind, recipient, entry, actor, minutes=0, **kw):
    return store.add_notification(kind, recipient["id"], entry["id"], actor["id"],
                                  (NOW + timedelta(minutes=minutes)).isoformat(), **kw)


# --- asetukset ja jono ------------------------------------------------------


def test_notify_prefs_default_on_and_recipients_exclude_actor(world):
    store, a, b, c, _ = world
    assert [u["id"] for u in store.list_notification_recipients("new_entry", exclude_user_id=a["id"])] == [b["id"], c["id"]]
    store.set_notify_prefs(b["id"], new_books=False, comments=True, likes=True)
    assert [u["id"] for u in store.list_notification_recipients("new_entry", exclude_user_id=a["id"])] == [c["id"]]
    assert store.get_user(b["id"])["notify_new_books"] == 0
    with pytest.raises(KeyError):
        store.list_notification_recipients("1; DROP TABLE users", exclude_user_id=a["id"])


def test_migration_adds_notify_columns_to_old_users_table(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, "
                 "display_name TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO users (email, display_name, created_at) VALUES ('v@example.com', 'Vanha', 'x')")
    conn.commit()
    conn.close()
    from store import Store
    user = Store(path).get_user_by_email("v@example.com")
    assert (user["notify_new_books"], user["notify_comments"], user["notify_likes"]) == (1, 1, 1)


def test_add_like_reports_whether_new(world):
    store, a, b, _, entry = world
    assert store.add_like(entry["id"], b["id"]) is True
    assert store.add_like(entry["id"], b["id"]) is False


def test_unique_notification_is_not_queued_twice(world):
    store, a, b, _, entry = world
    assert enqueue(store, "like", a, entry, b, unique=True) is not None
    assert enqueue(store, "like", a, entry, b, unique=True) is None  # peruttu ja uudelleen lisätty peukku


def test_deleting_entry_drops_its_notifications(world):
    store, a, b, _, entry = world
    enqueue(store, "new_entry", b, entry, a)
    store.delete_entry(entry["id"])
    assert store.due_notifications((NOW + timedelta(days=1)).isoformat()) == []


# --- viestit ----------------------------------------------------------------


def test_new_entry_mail(world):
    store, a, b, _, entry = world
    enqueue(store, "new_entry", b, entry, a)
    mailer = FakeMailer()
    assert process_due(store, mailer, CONFIG, NOW)["sent"] == 1
    to, subject, body = mailer.sent[0]
    assert to == "b@example.com"
    assert subject == "Aino Ääkkönen kirjasi kirjan Täällä Pohjantähden alla"
    assert "Hei Bertta," in body and "Väinö Linna" in body and "★★★★☆ (4/5)" in body
    assert "Hieno." in body and "https://x.example/kp/#/entry/1" in body and "#/settings" in body


def test_comment_mail_and_deleted_comment_is_skipped(world):
    store, a, b, _, entry = world
    first = store.add_comment(entry["id"], b["id"], "Mahtava kirja!")
    gone = store.add_comment(entry["id"], b["id"], "Poistettava")
    enqueue(store, "comment", a, entry, b, comment_id=first["id"])
    enqueue(store, "comment", a, entry, b, comment_id=gone["id"])
    store.delete_comment(gone["id"])
    mailer = FakeMailer()
    assert process_due(store, mailer, CONFIG, NOW) == {"sent": 1, "retried": 0, "failed": 0, "skipped": 1}
    to, subject, body = mailer.sent[0]
    assert to == "a@example.com" and subject.startswith("Bertta kommentoi kirjaustasi")
    assert "Mahtava kirja!" in body


def test_likes_are_combined_into_one_mail_after_delay(world):
    store, a, b, c, entry = world
    store.add_like(entry["id"], b["id"])
    store.add_like(entry["id"], c["id"])
    enqueue(store, "like", a, entry, b, minutes=10)
    enqueue(store, "like", a, entry, c, minutes=12)
    mailer = FakeMailer()
    assert process_due(store, mailer, CONFIG, NOW)["sent"] == 0  # viive ei ole kulunut
    assert process_due(store, mailer, CONFIG, NOW + timedelta(minutes=10))["sent"] == 1
    assert len(mailer.sent) == 1  # myös vielä erääntymätön toinen peukku mukaan samaan viestiin
    assert mailer.sent[0][1] == "Bertta ja Cecilia peukuttivat kirjaustasi: Täällä Pohjantähden alla"
    assert process_due(store, mailer, CONFIG, NOW + timedelta(hours=1))["sent"] == 0  # ei toista viestiä


def test_like_mail_skipped_if_everyone_unliked(world):
    store, a, b, _, entry = world
    store.add_like(entry["id"], b["id"])
    enqueue(store, "like", a, entry, b)
    store.remove_like(entry["id"], b["id"])
    mailer = FakeMailer()
    assert process_due(store, mailer, CONFIG, NOW)["skipped"] == 1 and mailer.sent == []


def test_preference_turned_off_after_queueing_is_respected(world):
    store, a, b, _, entry = world
    enqueue(store, "new_entry", b, entry, a)
    store.set_notify_prefs(b["id"], False, True, True)
    mailer = FakeMailer()
    assert process_due(store, mailer, CONFIG, NOW)["skipped"] == 1 and mailer.sent == []


def test_many_likers_summary():
    assert notifier._names(["A", "B", "C", "D"]) == "A, B ja 2 muuta"


# --- uudelleenyritys --------------------------------------------------------


def test_failed_send_is_retried_with_backoff_and_then_succeeds(world):
    store, a, b, _, entry = world
    enqueue(store, "new_entry", b, entry, a)
    mailer = FakeMailer(fail=1)
    assert process_due(store, mailer, CONFIG, NOW)["retried"] == 1
    assert process_due(store, mailer, CONFIG, NOW + timedelta(seconds=30))["sent"] == 0  # takaisinkytkentä: 1 min
    assert process_due(store, mailer, CONFIG, NOW + timedelta(minutes=1))["sent"] == 1
    assert len(mailer.sent) == 1


def test_gives_up_after_last_backoff(world):
    store, a, b, _, entry = world
    enqueue(store, "new_entry", b, entry, a)
    mailer = FakeMailer(fail=99)
    moment, totals = NOW, {"retried": 0, "failed": 0}
    for _ in range(len(notifier.BACKOFF_MINUTES) + 1):
        stats = process_due(store, mailer, CONFIG, moment)
        totals["retried"] += stats["retried"]
        totals["failed"] += stats["failed"]
        moment += timedelta(days=1)
    assert totals == {"retried": len(notifier.BACKOFF_MINUTES), "failed": 1}
    assert process_due(store, mailer, CONFIG, moment)["sent"] == 0  # ei yritetä enää


def test_purge_removes_only_old_handled(world):
    store, a, b, c, entry = world
    enqueue(store, "new_entry", b, entry, a)
    enqueue(store, "new_entry", c, entry, a, minutes=60 * 24 * 60)  # kaukana tulevaisuudessa, käsittelemätön
    process_due(store, FakeMailer(), CONFIG, NOW)
    assert store.purge_notifications((NOW - timedelta(days=1)).isoformat()) == 0
    assert store.purge_notifications((NOW + timedelta(days=1)).isoformat()) == 1


# --- SMTP ja turvallisuus ---------------------------------------------------


def test_one_line_strips_header_injection():
    assert one_line("Kirja\r\nBcc: x@evil.example") == "Kirja Bcc: x@evil.example"
    assert "\n" not in one_line("a\nb" * 100) and len(one_line("x" * 500, 50)) == 50


def test_hostile_titles_cannot_inject_headers(world):
    store, a, b, _, _ = world
    book = store.create_book("Kirja\r\nBcc: x@evil.example", "Tekijä\nX")
    entry = store.create_entry(a["id"], book["id"], "2026-10-31", note="x")
    enqueue(store, "new_entry", b, entry, a)
    sent = []

    class Capture(SmtpMailer):
        def send(self, to, subject, body):
            sent.append(self.build(to, subject, body))

    process_due(store, Capture(CONFIG), CONFIG, NOW)
    message = sent[0]
    assert message["Bcc"] is None and message["To"] == "b@example.com"
    assert "\n" not in message["Subject"]


def test_smtp_mailer_builds_utf8_message_and_sends(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def ehlo(self):
            calls.append("ehlo")

        def starttls(self, context=None):
            calls.append("starttls")

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, message, from_addr=None):
            calls.append(("send", message["To"], message["Subject"], message.get_content()))

    monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
    config = MailConfig(host="smtp.example", port=587, user="u", password="p", security="starttls",
                        sender="Kirjapäiväkirja <ilmoitukset@example.com>")
    SmtpMailer(config).send("b@example.com", "Älä lue tätä", "Hyvää päivää, äö")
    assert ("connect", "smtp.example", 587) in calls and "starttls" in calls and ("login", "u", "p") in calls
    assert calls[-1][:3] == ("send", "b@example.com", "Älä lue tätä") and "äö" in calls[-1][3]

    message = SmtpMailer(config).build("b@example.com", "x", "y")
    assert message["Auto-Submitted"] == "auto-generated" and message["Message-ID"].endswith("@example.com>")


def test_parse_sender_accepts_plain_address_and_named_form():
    assert display(notifier.parse_sender("info@example.com")) == ("Kirjapäiväkirja", "info@example.com")
    assert display(notifier.parse_sender("Kirjapäiväkirja <info@example.com>")) == ("Kirjapäiväkirja", "info@example.com")
    assert notifier.parse_sender("Lukupiiri <info@example.com>") == "Lukupiiri <info@example.com>"
    assert display(notifier.parse_sender("info@example.com", "Äänekoski")) == ("Äänekoski", "info@example.com")


@pytest.mark.parametrize("raw", [
    "Kirjapäiväkirja info.rossinen@gmail.com",   # kulmasulkeet unohtuneet: nimi ja osoite sulautuisivat
    "info.rossinen",
    "<>",
    "a@b",
    "x@y.fi, z@y.fi",
])
def test_parse_sender_rejects_malformed_values(raw):
    with pytest.raises(ValueError):
        notifier.parse_sender(raw)


def test_smtp_mailer_uses_plain_address_as_envelope_sender(monkeypatch):
    seen = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *e): return False
        def ehlo(self): pass
        def send_message(self, message, from_addr=None, **kw):
            seen["from_addr"], seen["header"] = from_addr, message["From"]

    monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
    config = MailConfig(host="h", sender=notifier.parse_sender("info@example.com"))
    SmtpMailer(config).send("b@example.com", "x", "y")
    assert seen["from_addr"] == "info@example.com"
    assert display(seen["header"]) == ("Kirjapäiväkirja", "info@example.com")


def test_config_from_env(monkeypatch):
    for name in ("MAIL_HOST", "MAIL_FROM", "MAIL_PORT", "MAIL_SECURITY", "PUBLIC_URL"):
        monkeypatch.delenv(name, raising=False)
    assert MailConfig.from_env() is None  # ilmoitukset pois, kun MAIL_HOST puuttuu
    monkeypatch.setenv("MAIL_HOST", "mail-relay")
    with pytest.raises(ValueError):
        MailConfig.from_env()  # MAIL_FROM puuttuu
    monkeypatch.setenv("MAIL_FROM", "Kirjapäiväkirja a@example.com")  # kulmasulkeet puuttuvat
    with pytest.raises(ValueError):
        MailConfig.from_env()
    monkeypatch.setenv("MAIL_FROM", "a@example.com")
    monkeypatch.setenv("PUBLIC_URL", "https://x.example/kp")
    config = MailConfig.from_env()
    assert (config.host, config.port, config.security, config.public_url) == ("mail-relay", 587, "none", "https://x.example/kp/")
    assert display(config.sender) == ("Kirjapäiväkirja", "a@example.com") and config.address == "a@example.com"
    monkeypatch.setenv("MAIL_SECURITY", "väärä")
    with pytest.raises(ValueError):
        MailConfig.from_env()
