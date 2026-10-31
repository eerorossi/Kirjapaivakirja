"""Kirjahaun yhdistävä palvelu: haku useasta lähteestä, välimuisti,
deduplikointi ja kirjailijaesittelyn varahaku Wikipediasta."""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from providers import UNKNOWN_AUTHOR, BookResult, make_http_client
from providers.covers import fetch_cover
from providers.finna import FINNA_BASE, FinnaProvider
from providers.openlibrary import COVERS_BASE, OpenLibraryProvider
from providers.wikipedia import WikipediaBios

log = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 4000
MAX_BIO_CHARS = 3000
SIBLING_SEARCH_LIMIT = 50
MAX_COVER_ATTEMPTS = 10


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def _richness(result: BookResult) -> int:
    return bool(result.cover_url) + bool(result.summary)


class BookService:
    def __init__(self, providers, wiki=None, http=None, cache_ttl: float = 600.0, cache_max: int = 200):
        self.providers = {p.name: p for p in providers}  # järjestys = ensisijaisuus
        self.wiki = wiki
        self.http = http
        self._cache: dict[str, tuple[float, list[BookResult]]] = {}
        self._cache_ttl = cache_ttl
        self._cache_max = cache_max
        self._lock = threading.Lock()

    def has_source(self, name: str) -> bool:
        return name in self.providers

    def close(self) -> None:
        if self.http is not None:
            self.http.close()

    # --- haku ------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> dict:
        """Palauttaa {'results': [BookResult], 'unavailable': [lähteen nimi]}."""
        key = " ".join(query.casefold().split())
        cached = self._cache_get(key)
        if cached is not None:
            return {"results": cached, "unavailable": []}

        per_source: dict[str, list[BookResult]] = {}
        unavailable: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, len(self.providers))) as pool:
            futures = {n: pool.submit(p.search, query, limit) for n, p in self.providers.items()}
            for name, future in futures.items():
                try:
                    per_source[name] = future.result()
                except Exception as exc:  # yksi lähde ei saa kaataa koko hakua
                    log.warning("Book source %s failed: %s", name, exc)
                    unavailable.append(name)

        results = self._merge(per_source)
        if not unavailable:  # vajaata tulosta ei jäädä muistamaan
            self._cache_put(key, results)
        return {"results": results, "unavailable": unavailable}

    @staticmethod
    def _merge(per_source: dict[str, list[BookResult]]) -> list[BookResult]:
        # Sama teos on usein monena tietueena, joista vain osalla on kansi tai kuvaus:
        # säilytetään ensimmäisen paikka, mutta rikkain tietue.
        position: dict[tuple[str, str], int] = {}
        merged: list[BookResult] = []
        for results in per_source.values():  # ensisijainen lähde ensin
            for result in results:
                dedupe_key = (result.title.casefold(), result.author.casefold())
                if dedupe_key not in position:
                    position[dedupe_key] = len(merged)
                    merged.append(result)
                elif _richness(result) > _richness(merged[position[dedupe_key]]):
                    merged[position[dedupe_key]] = result
        return merged

    def _cache_get(self, key: str) -> list[BookResult] | None:
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            self._cache.pop(key, None)
            return None

    def _cache_put(self, key: str, results: list[BookResult]) -> None:
        with self._lock:
            if len(self._cache) >= self._cache_max:
                self._cache.pop(next(iter(self._cache)))  # vanhin pois
            self._cache[key] = (time.monotonic() + self._cache_ttl, results)

    # --- yksittäisen kirjan tiedot ---------------------------------------

    def fetch(self, source: str, source_id: str) -> BookResult | None:
        """Hae kirjan tiedot lähteestä ja täydennä kirjailijan esittely tarvittaessa."""
        result = self.providers[source].get(source_id)
        if result is None:
            return None
        if not result.author_bio and self.wiki is not None and result.author != UNKNOWN_AUTHOR:
            found = self.wiki.lookup(result.author)
            if found:
                result.author_bio, result.author_bio_source = found
        self._enrich(result)
        if not result.summary and self.wiki is not None and result.author != UNKNOWN_AUTHOR:
            found = self.wiki.lookup_book(result.title, result.author)
            if found:
                result.summary, result.summary_source = found
        result.summary = result.summary[:MAX_SUMMARY_CHARS]
        result.author_bio = result.author_bio[:MAX_BIO_CHARS]
        return result

    def _enrich(self, result: BookResult) -> None:
        """Täydennä puuttuva kuvaus ja kansi saman teoksen muista tietueista.

        Finnassa kansi ja kuvaus ovat usein eri painosten tietueilla, joten haetaan
        samannimiset ja samankirjailijaiset tietueet samasta lähteestä. Kansi
        yritetään lisäksi ISBN:llä Open Libraryn kansipalvelusta."""
        siblings: list[BookResult] = []
        needs_more = not result.summary or not result.cover_url
        if needs_more and result.author != UNKNOWN_AUTHOR:
            query = f"{result.title} {result.author}"
            try:
                found = self.providers[result.source].search(query, SIBLING_SEARCH_LIMIT)
            except Exception as exc:  # täydennys on bonus, tuonti ei saa kaatua siihen
                log.warning("Sibling lookup in %s failed: %s", result.source, exc)
                found = []
            title, author = _norm(result.title), _norm(result.author)
            siblings = [
                r for r in found
                if r.source_id != result.source_id
                and _norm(r.title) == title and _norm(r.author) == author
            ]
        if not result.summary:
            result.summary = next((r.summary for r in siblings if r.summary), "")

        urls: list[str] = [u for u in [result.cover_url] if u]
        urls += [r.cover_url for r in siblings if r.cover_url]
        isbns: list[str] = []
        for isbn in [result.isbn] + [r.isbn for r in siblings]:
            clean = re.sub(r"[^0-9Xx]", "", isbn or "")
            if clean and clean not in isbns:
                isbns.append(clean)
        for isbn in isbns[:3]:  # ISBN-haku: Finnan oma kansipalvelu, sitten Open Library
            urls.append(f"{FINNA_BASE}/Cover/Show?isbn={isbn}&size=large")
            urls.append(f"{COVERS_BASE}/b/isbn/{isbn}-L.jpg?default=false")
        unique = list(dict.fromkeys(urls))
        result.cover_url = unique[0] if unique else None
        result.extra_cover_urls = unique[1:]

    def download_cover(self, result: BookResult) -> tuple[bytes, str] | None:
        if self.http is None:
            return None
        candidates = [u for u in [result.cover_url, *result.extra_cover_urls] if u]
        for url in candidates[:MAX_COVER_ATTEMPTS]:
            cover = fetch_cover(self.http, url)
            if cover:
                return cover
        return None


def build_default_service() -> BookService:
    http = make_http_client()
    return BookService(
        [FinnaProvider(http), OpenLibraryProvider(http)],
        WikipediaBios(http),
        http,
    )
