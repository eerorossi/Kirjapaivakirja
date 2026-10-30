"""Kansikuvan lataus. Osoite tulee aina palvelimen omasta lähdehausta, ei asiakkaalta."""
from __future__ import annotations

from urllib.parse import urlsplit

import httpx

ALLOWED_COVER_HOSTS = {"api.finna.fi", "covers.openlibrary.org"}
MAX_COVER_BYTES = 3_000_000
# Finna palauttaa puuttuvan kannen tilalle 10x10 läpinäkyvän gifin: se on
# pieni eikä ole jpeg/png/webp, joten molemmat suodattavat sen pois.
MIN_COVER_BYTES = 1_000


def image_extension(data: bytes) -> str | None:
    """Tunnista kuvatyyppi sisällöstä (ei luoteta Content-Typeen)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def fetch_cover(http: httpx.Client, url: str | None) -> tuple[bytes, str] | None:
    """Palauttaa (tavut, tiedostopääte) tai None, jos kantta ei saatu tai se on kelvoton."""
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_COVER_HOSTS:
        return None
    buffer = bytearray()
    try:
        with http.stream("GET", url, headers={"Accept": "image/*"}) as response:
            if response.status_code != 200:
                return None
            for chunk in response.iter_bytes():
                buffer += chunk
                if len(buffer) > MAX_COVER_BYTES:
                    return None
    except httpx.HTTPError:
        return None
    data = bytes(buffer)
    if len(data) < MIN_COVER_BYTES:
        return None
    extension = image_extension(data)
    return (data, extension) if extension else None
