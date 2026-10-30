"""Kirjahaun yhdistävä palvelu: haku useasta lähteestä, välimuisti,
deduplikointi ja kirjailijaesittelyn varahaku Wikipediasta."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from providers import UNKNOWN_AUTHOR, BookResult, make_http_client
from providers.covers import fetch_cover
from providers.finna import FinnaProvider
from providers.openlibrary import OpenLibraryProvider
from providers.wikipedia import WikipediaBios

log = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 4000
MAX_BIO_CHARS = 3000


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
        seen: set[tuple[str, str]] = set()
        merged: list[BookResult] = []
        for results in per_source.values():  # ensisijainen lähde ensin
            for result in results:
                dedupe_key = (result.title.casefold(), result.author.casefold())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                merged.append(result)
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
        result.summary = result.summary[:MAX_SUMMARY_CHARS]
        result.author_bio = result.author_bio[:MAX_BIO_CHARS]
        return result

    def download_cover(self, result: BookResult) -> tuple[bytes, str] | None:
        if self.http is None:
            return None
        return fetch_cover(self.http, result.cover_url)


def build_default_service() -> BookService:
    http = make_http_client()
    return BookService(
        [FinnaProvider(http), OpenLibraryProvider(http)],
        WikipediaBios(http),
        http,
    )
