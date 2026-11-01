"""Sähköposti-ilmoitukset: uudet kirjaukset kaikille, kommentit ja peukut kirjauksen tekijälle.

Rakenne: sovellus lisää tapahtuman `notifications`-jonoon (store.add_notification), ja
taustasäie (NotifierThread) käy jonon läpi, muodostaa viestit ja lähettää ne SMTP:llä.
Näin lähetys ei hidasta pyyntöjä, ja epäonnistunut lähetys yritetään uudelleen.
SMTP-palvelin on yleensä paikallinen välityspalvelin (Postfix-rele), joka hoitaa
varsinaisen lähetyksen ulos; ks. README.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr

from store import NOTIFY_COLUMNS, Store

log = logging.getLogger(__name__)

# Uudelleenyritysten välit minuutteina; viimeisen jälkeen ilmoitus hylätään.
BACKOFF_MINUTES = (1, 5, 15, 60, 240, 720)
KEEP_HANDLED_DAYS = 30
POLL_SECONDS = 20


_ADDRESS_RE = re.compile(r"^[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+$")


def parse_sender(raw: str, default_name: str = "Kirjapäiväkirja") -> str:
    """Muodosta kelvollinen From-arvo. Hyväksyy pelkän osoitteen (`info@example.com`) tai
    muodon `Nimi <info@example.com>`; kaikki muu (esim. kulmasulkeet unohtuneet) hylätään,
    koska nimi ja osoite sulautuisivat muuten yhdeksi rikkinäiseksi osoitteeksi."""
    name, address = parseaddr(raw.strip())
    if not _ADDRESS_RE.match(address):
        raise ValueError(
            f"MAIL_FROM ei ole kelvollinen sähköpostiosoite: {raw!r}. "
            "Käytä muotoa info@example.com tai Nimi <info@example.com> (kulmasulkeet kuuluvat muotoon)."
        )
    return formataddr((name or default_name, address))


@dataclass
class MailConfig:
    host: str
    port: int = 587
    user: str = ""
    password: str = ""
    security: str = "none"  # none | starttls | ssl
    sender: str = ""
    public_url: str = ""    # esim. https://esimerkki.fi/kp/ (linkit viesteissä)
    like_delay_minutes: int = 10

    @property
    def address(self) -> str:
        """Pelkkä lähettäjän osoite (SMTP:n kuoren MAIL FROM)."""
        return parseaddr(self.sender)[1]

    @classmethod
    def from_env(cls) -> "MailConfig | None":
        """None, jos MAIL_HOST puuttuu: ilmoitukset ovat silloin pois päältä."""
        host = os.getenv("MAIL_HOST", "").strip()
        if not host:
            return None
        raw_sender = os.getenv("MAIL_FROM", "").strip()
        if not raw_sender:
            raise ValueError("MAIL_FROM puuttuu: aseta lähettäjän osoite, esim. info@esimerkki.fi")
        sender = parse_sender(raw_sender, os.getenv("MAIL_FROM_NAME", "Kirjapäiväkirja").strip() or "Kirjapäiväkirja")
        security = os.getenv("MAIL_SECURITY", "none").strip().lower()
        if security not in ("none", "starttls", "ssl"):
            raise ValueError("MAIL_SECURITY pitää olla none, starttls tai ssl")
        public_url = os.getenv("PUBLIC_URL", "").strip()
        return cls(
            host=host,
            port=int(os.getenv("MAIL_PORT", "587")),
            user=os.getenv("MAIL_USER", ""),
            password=os.getenv("MAIL_PASSWORD", ""),
            security=security,
            sender=sender,
            public_url=(public_url.rstrip("/") + "/") if public_url else "",
            like_delay_minutes=int(os.getenv("LIKE_DELAY_MINUTES", "10")),
        )


class SmtpMailer:
    """Yksinkertainen SMTP-lähettäjä (stdlib). Nostaa poikkeuksen, jos lähetys epäonnistuu."""

    def __init__(self, config: MailConfig):
        self.config = config

    def build(self, to: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.config.sender
        message["To"] = to
        message["Subject"] = one_line(subject, 200)
        message["Date"] = formatdate(localtime=False)
        domain = parseaddr(self.config.sender)[1].rpartition("@")[2] or "localhost"
        message["Message-ID"] = make_msgid(domain=domain)
        message["Auto-Submitted"] = "auto-generated"  # ei automaattivastauksia
        message.set_content(body)
        return message

    def send(self, to: str, subject: str, body: str) -> None:
        cfg = self.config
        message = self.build(to, subject, body)
        context = ssl.create_default_context()
        if cfg.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20, context=context)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
        with server:
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if cfg.user:
                server.login(cfg.user, cfg.password)
            server.send_message(message, from_addr=cfg.address)  # kuoren lähettäjä = pelkkä osoite


# --- viestien sisältö -------------------------------------------------------


def one_line(text: str, limit: int = 120) -> str:
    """Yksirivinen teksti otsikkoon: rivinvaihdot ja ohjausmerkit pois (header-injektio)."""
    clean = re.sub(r"[\x00-\x1f\x7f]+", " ", text or "")
    clean = " ".join(clean.split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _excerpt(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} ja {names[1]}"
    return f"{names[0]}, {names[1]} ja {len(names) - 2} muuta"


def _footer(config: MailConfig) -> str:
    lines = ["", "--", "Tämä on Kirjapäiväkirjan automaattinen ilmoitus."]
    if config.public_url:
        lines.append(f"Voit valita, mistä ilmoituksista saat viestin: {config.public_url}#/settings")
    return "\n".join(lines) + "\n"


def _entry_link(config: MailConfig, entry: dict) -> str:
    return f"Avaa kirjaus: {config.public_url}#/entry/{entry['id']}\n" if config.public_url else ""


def build_message(store: Store, config: MailConfig, kind: str, group: list[dict]) -> tuple[str, str, str] | None:
    """(vastaanottaja, otsikko, runko) tai None, jos viestiä ei enää pidä lähettää
    (kirjaus/kommentti poistettu tai käyttäjä ehti kytkeä ilmoituksen pois)."""
    first = group[0]
    recipient = store.get_user(first["recipient_id"])
    entry = store.get_entry(first["entry_id"])
    if not recipient or not entry or "@" not in recipient["email"]:
        return None
    if not recipient[NOTIFY_COLUMNS[kind]]:
        return None
    title = one_line(entry["book"]["title"], 100)
    greeting = f"Hei {one_line(recipient['display_name'], 60)},\n\n"
    link = _entry_link(config, entry)

    if kind == "new_entry":
        actor = one_line(entry["user_name"], 60)
        lines = [f'{actor} on kirjannut luetuksi kirjan "{title}" ({one_line(entry["book"]["author"], 80)}).']
        if entry["rating"]:
            lines.append("Arvio: " + "★" * entry["rating"] + "☆" * (5 - entry["rating"]) + f" ({entry['rating']}/5)")
        if entry["note"]:
            lines += ["", _excerpt(entry["note"], 400)]
        subject = f"{actor} kirjasi kirjan {title}"
        body = greeting + "\n".join(lines) + "\n\n" + link
    elif kind == "comment":
        comment = store.get_comment(first["comment_id"]) if first["comment_id"] else None
        if comment is None:
            return None
        actor = one_line(comment["user_name"], 60)
        subject = f"{actor} kommentoi kirjaustasi: {title}"
        body = greeting + f'{actor} kommentoi kirjaustasi "{title}":\n\n{_excerpt(comment["body"], 500)}\n\n' + link
    else:  # like: yhdistetään saman kirjauksen peukut yhteen viestiin
        still_liking = {liker["user_id"] for liker in store.list_likers(entry["id"])}
        actor_ids = list(dict.fromkeys(n["actor_id"] for n in group if n["actor_id"] in still_liking))
        names = [one_line(store.get_user(i)["display_name"], 60) for i in actor_ids if store.get_user(i)]
        if not names:
            return None
        verb = "peukutti" if len(names) == 1 else "peukuttivat"
        subject = f"{_names(names)} {verb} kirjaustasi: {title}"
        body = greeting + f'{_names(names)} {verb} kirjaustasi "{title}".\n\n' + link
    return recipient["email"], subject, body + _footer(config)


# --- ilmoitusten lisäys jonoon ---------------------------------------------


def queue_new_entry(store: Store, config: MailConfig, entry: dict, now: datetime | None = None) -> int:
    """Uusi kirjaus: ilmoitus kaikille muille, jotka haluavat sellaisia. Palauttaa jonoon lisättyjen määrän."""
    send_after = _iso(now or datetime.now(timezone.utc))
    recipients = store.list_notification_recipients("new_entry", exclude_user_id=entry["user_id"])
    for user in recipients:
        store.add_notification("new_entry", user["id"], entry["id"], entry["user_id"], send_after)
    return len(recipients)


def queue_comment(store: Store, config: MailConfig, entry: dict, comment: dict, now: datetime | None = None) -> bool:
    """Kommentti: ilmoitus kirjauksen tekijälle (ei omasta kommentista)."""
    owner = store.get_user(entry["user_id"])
    if not owner or owner["id"] == comment["user_id"] or not owner["notify_comments"]:
        return False
    send_after = _iso(now or datetime.now(timezone.utc))
    store.add_notification("comment", owner["id"], entry["id"], comment["user_id"], send_after, comment_id=comment["id"])
    return True


def queue_like(store: Store, config: MailConfig, entry: dict, actor_id: int, now: datetime | None = None) -> bool:
    """Peukku: ilmoitus kirjauksen tekijälle viiveellä, jotta usea peukku mahtuu yhteen viestiin.
    Sama henkilö ei laukaise viestiä uudelleen peukun perumisen jälkeen."""
    owner = store.get_user(entry["user_id"])
    if not owner or owner["id"] == actor_id or not owner["notify_likes"]:
        return False
    send_after = _iso((now or datetime.now(timezone.utc)) + timedelta(minutes=config.like_delay_minutes))
    return store.add_notification("like", owner["id"], entry["id"], actor_id, send_after, unique=True) is not None


# --- jonon käsittely --------------------------------------------------------


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def process_due(store: Store, mailer, config: MailConfig, now: datetime | None = None) -> dict:
    """Lähetä erääntyneet ilmoitukset. Palauttaa laskurit {sent, retried, failed, skipped}."""
    now = now or datetime.now(timezone.utc)
    stats = {"sent": 0, "retried": 0, "failed": 0, "skipped": 0}
    seen: set[int] = set()
    for row in store.due_notifications(_iso(now)):
        if row["id"] in seen:
            continue
        group = [row]
        if row["kind"] == "like":
            group = store.unhandled_notifications("like", row["recipient_id"], row["entry_id"])
        ids = [n["id"] for n in group]
        seen.update(ids)
        message = build_message(store, config, row["kind"], group)
        if message is None:
            store.finish_notifications(ids, _iso(now), "skipped")
            stats["skipped"] += 1
            continue
        try:
            mailer.send(*message)
        except Exception as exc:  # noqa: BLE001 - mikä tahansa lähetysvirhe yritetään uudelleen
            attempts = max(n["attempts"] for n in group)
            error = f"{type(exc).__name__}: {exc}"[:300]
            if attempts >= len(BACKOFF_MINUTES):
                store.finish_notifications(ids, _iso(now), f"failed: {error}")
                stats["failed"] += 1
                log.error("Notification %s given up: %s", ids, error)
            else:
                retry_at = now + timedelta(minutes=BACKOFF_MINUTES[attempts])
                store.retry_notifications(ids, _iso(retry_at), error)
                stats["retried"] += 1
                log.warning("Notification %s failed, retry at %s: %s", ids, retry_at, error)
            continue
        store.finish_notifications(ids, _iso(now))
        stats["sent"] += 1
    return stats


class NotifierThread:
    """Taustasäie, joka käy jonon läpi säännöllisesti."""

    def __init__(self, store: Store, mailer, config: MailConfig, interval: float = POLL_SECONDS):
        self.store, self.mailer, self.config, self.interval = store, mailer, config, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
        self._last_purge = datetime.min.replace(tzinfo=timezone.utc)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                process_due(self.store, self.mailer, self.config)
                now = datetime.now(timezone.utc)
                if now - self._last_purge > timedelta(hours=1):
                    self.store.purge_notifications(_iso(now - timedelta(days=KEEP_HANDLED_DAYS)))
                    self._last_purge = now
            except Exception:  # noqa: BLE001 - säie ei saa kuolla
                log.exception("Notification run failed")
            self._stop.wait(self.interval)
