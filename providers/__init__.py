"""Ulkoiset kirjatietolähteet. Jokainen lähde on `BookProvider`-rajapinnan takana,
jotta lähteitä voi lisätä ja vaihtaa muuttamatta muuta sovellusta."""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx

DEFAULT_USER_AGENT = "Kirjapaivakirja/1.0 (+https://github.com/eerorossi/Kirjapaivakirja)"
UNKNOWN_AUTHOR = "Tuntematon kirjailija"


class ProviderError(Exception):
    """Ulkoinen palvelu ei vastannut tai vastasi odottamattomasti."""


@dataclass
class BookResult:
    source: str
    source_id: str
    title: str
    author: str
    year: int | None = None
    isbn: str | None = None
    summary: str = ""
    # Palvelin johtaa osoitteen itse lähteen vastauksesta. Asiakkaan antamaa
    # kansikuva-URL:ia ei koskaan käytetä (SSRF).
    cover_url: str | None = None
    author_bio: str = ""
    author_bio_source: str | None = None  # URL, josta esittely on peräisin

    def to_dict(self) -> dict:
        return asdict(self)


class BookProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 10) -> list[BookResult]: ...

    def get(self, source_id: str) -> BookResult | None: ...


def make_http_client() -> httpx.Client:
    """Yhteinen HTTP-asiakas: tunnistettava User-Agent, lyhyet aikakatkaisut.

    User-Agent ei sisällä käyttäjien sähköposteja tai muita henkilötietoja;
    halutessasi voit lisätä oman yhteystiedon ympäristömuuttujalla HTTP_USER_AGENT.
    """
    return httpx.Client(
        headers={
            "User-Agent": os.getenv("HTTP_USER_AGENT", DEFAULT_USER_AGENT),
            "Accept": "application/json",
        },
        timeout=httpx.Timeout(6.0, connect=4.0),
        follow_redirects=True,
    )


def get_json(
    http: httpx.Client,
    url: str,
    *,
    params: Any = None,
    allow_404: bool = False,
) -> Any:
    """GET + JSON. Verkko-, HTTP- ja JSON-virheet muutetaan ProviderErroriksi."""
    try:
        response = http.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{url}: {exc.__class__.__name__}") from exc
    if response.status_code == 404 and allow_404:
        return None
    if response.status_code != 200:
        raise ProviderError(f"{url}: HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{url}: invalid JSON") from exc


_DATES_AFTER_COMMA = re.compile(r",?\s*\d{3,4}\??\s*-\s*(\d{3,4})?\.?$")
_PARENTHESES = re.compile(r"\s*\([^)]*\)")


def normalize_author(name: str | None) -> str:
    """'Linna, Väinö' / 'Tolkien, J. R. R. (1892-1973)' -> 'Väinö Linna' / 'J. R. R. Tolkien'."""
    name = _PARENTHESES.sub("", name or "").strip()
    name = _DATES_AFTER_COMMA.sub("", name).strip(" ,")
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return " ".join(name.split())


def parse_year(value: Any) -> int | None:
    # Neljä numeroa, joita ei ympäröi muut numerot ("c1954.", "July 29, 1954").
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def pick_isbn(values: Any) -> str | None:
    """Suosi 13-numeroista ISBN:ää; muuten ensimmäinen."""
    if not isinstance(values, list):
        return None
    candidates = [v for v in values[:50] if isinstance(v, str) and v.strip()]
    for value in candidates:
        if len(re.sub(r"[^0-9Xx]", "", value)) == 13:
            return value.strip()
    return candidates[0].strip() if candidates else None
