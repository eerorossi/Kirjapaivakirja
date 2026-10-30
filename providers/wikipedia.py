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
