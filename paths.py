"""Polkuprefiksin käsittely (Caddy julkaisee sovelluksen polun /kp alla)."""
from __future__ import annotations

import re

_PREFIX = re.compile(r"/[A-Za-z0-9._~\-]+(?:/[A-Za-z0-9._~\-]+)*")


def base_href(prefix: str | None) -> str:
    """Muodosta <base href>-arvo X-Forwarded-Prefix-headerista.

    '/kp' -> '/kp/', puuttuva tai epäilyttävä arvo -> '/'. Arvo päätyy HTML:ään,
    joten vain tavalliset polkumerkit hyväksytään (ei lainausmerkkejä, '//' tai '..'-temppuja
    ulkoisiin osoitteisiin)."""
    prefix = (prefix or "").strip().rstrip("/")
    if prefix and _PREFIX.fullmatch(prefix) and ".." not in prefix.split("/"):
        return prefix + "/"
    return "/"
