"""Kirjailijan esittely Wikipediasta (suomi ensin, sitten englanti).

Käyttää REST-rajapinnan tiivistelmää: /api/rest_v1/page/summary/{otsikko}.
Wikipedian tekstit ovat CC BY-SA -lisensoituja, joten esittelyn mukana
tallennetaan lähdeosoite, joka näytetään käyttöliittymässä.
"""
from __future__ import annotations

from urllib.parse import quote

from . import UNKNOWN_AUTHOR, ProviderError, get_json

# Nimi voi osua väärään henkilöön (esim. samanniminen jalkapalloilija), joten
# esittely hyväksytään vain, jos kuvaus tai alkuteksti viittaa kirjoittajaan.
WRITER_WORDS = (
    "kirjailija", "kirjoittaja", "runoilija", "näytelmäkirjailija", "dekkaristi",
    "toimittaja", "sarjakuva", "käsikirjoittaja", "esseisti", "kääntäjä",
    "writer", "author", "novelist", "poet", "playwright", "essayist",
    "journalist", "cartoonist", "screenwriter",
)


# Kirjan artikkeli hyväksytään vain, jos se kertoo teoksesta (ei elokuvasta tms.).
BOOK_WORDS = (
    "romaani", "kirja", "teos", "novelli", "runokokoelma", "näytelmä",
    "kertomus", "tietokirja", "esseekokoelma", "sarjakuva", "runoelma",
)


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:].lower()


class WikipediaBios:
    def __init__(self, http, langs: tuple[str, ...] = ("fi", "en")):
        self.http = http
        self.langs = langs

    def lookup(self, name: str) -> tuple[str, str] | None:
        """Palauttaa (esittely, lähde-URL) tai None. Ei koskaan nosta virhettä."""
        name = " ".join((name or "").split())
        if not name or name == UNKNOWN_AUTHOR:
            return None
        title = quote(name.replace(" ", "_"), safe="")
        for lang in self.langs:
            try:
                data = get_json(
                    self.http,
                    f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}",
                    allow_404=True,
                )
            except ProviderError:
                continue
            found = self._accept(data, lang, title)
            if found:
                return found
        return None

    def lookup_book(self, title: str, author: str) -> tuple[str, str] | None:
        """Kirjan kuvaus suomenkielisestä Wikipediasta: (teksti, lähde-URL) tai None.

        Tarkkuus on kattavuutta tärkeämpää: artikkeli hyväksytään vain, jos se
        mainitsee kirjan lajin (romaani, teos…) ja kirjailijan sukunimen."""
        title = " ".join((title or "").split())
        parts = (author or "").split()
        if not title or not parts or author == UNKNOWN_AUTHOR:
            return None
        stem = parts[-1].casefold()
        stem = stem[: max(4, len(stem) - 2)]  # taivutus: Waltari -> Waltarin
        names = [title, _sentence_case(title)]
        names += [f"{n} (romaani)" for n in names[:2]] + [f"{names[1]} (kirja)"]
        for name in dict.fromkeys(names):
            quoted = quote(name.replace(" ", "_"), safe="")
            try:
                data = get_json(
                    self.http,
                    f"https://fi.wikipedia.org/api/rest_v1/page/summary/{quoted}",
                    allow_404=True,
                )
            except ProviderError:
                continue
            if not isinstance(data, dict) or data.get("type") != "standard":
                continue
            extract = str(data.get("extract") or "").strip()
            haystack = f"{data.get('description') or ''} {extract}".casefold()
            if not extract or stem not in haystack or not any(w in haystack for w in BOOK_WORDS):
                continue
            desktop = (data.get("content_urls") or {}).get("desktop") or {}
            return extract, desktop.get("page") or f"https://fi.wikipedia.org/wiki/{quoted}"
        return None

    @staticmethod
    def _accept(data, lang: str, title: str) -> tuple[str, str] | None:
        if not isinstance(data, dict) or data.get("type") != "standard":
            return None  # esim. disambiguation-sivu
        extract = str(data.get("extract") or "").strip()
        haystack = f"{data.get('description') or ''} {extract}".casefold()
        if not extract or not any(word in haystack for word in WRITER_WORDS):
            return None
        desktop = (data.get("content_urls") or {}).get("desktop") or {}
        url = desktop.get("page") or f"https://{lang}.wikipedia.org/wiki/{title}"
        return extract, url
