#!/usr/bin/env python3
"""Savutesti oikeita ulkoisia rajapintoja vastaan (Finna, Open Library, Wikipedia).

Automaattitestit käyttävät kiinteitä vastauksia, joten ne eivät huomaa, jos
jokin palvelu muuttaa vastaustaan. Aja tämä käsin koneella, jolla on verkko:

    python scripts/smoke_providers.py                    # oletushaku
    python scripts/smoke_providers.py "Tove Jansson"
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import ProviderError, make_http_client  # noqa: E402
from providers.covers import fetch_cover  # noqa: E402
from providers.finna import FinnaProvider  # noqa: E402
from providers.openlibrary import OpenLibraryProvider  # noqa: E402
from providers.wikipedia import WikipediaBios  # noqa: E402

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"  [{'OK' if ok else 'VIRHE'}] {label}{(' — ' + detail) if detail else ''}")


def show(result) -> None:
    print(f"      {result.source_id}: {result.title!r} / {result.author!r} / {result.year} / isbn={result.isbn}")
    print(f"      kansi={'kyllä' if result.cover_url else 'ei'}, synopsi={len(result.summary)} merkkiä, "
          f"esittely={len(result.author_bio)} merkkiä")


def main() -> int:
    query = " ".join(sys.argv[1:]) or "Tuntematon sotilas"
    http = make_http_client()
    print(f"Haku: {query!r}\n")

    for provider in (FinnaProvider(http), OpenLibraryProvider(http)):
        print(f"{provider.name}:")
        try:
            results = provider.search(query)
        except ProviderError as exc:
            check("haku", False, str(exc))
            continue
        check("haku palautti tuloksia", bool(results), f"{len(results)} kpl")
        for r in results[:3]:
            show(r)
        if not results:
            continue
        try:
            detail = provider.get(results[0].source_id)
        except ProviderError as exc:
            check("tietojen haku", False, str(exc))
            continue
        check("tietojen haku (get)", detail is not None)
        if detail is None:
            continue
        show(detail)
        if detail.cover_url:
            cover = fetch_cover(http, detail.cover_url)
            check("kansikuva ladattavissa", cover is not None,
                  f"{len(cover[0])} tavua, .{cover[1]}" if cover else detail.cover_url)
        else:
            print("      (ei kansikuvaa tälle tulokselle)")
        print()

    print("wikipedia:")
    for name in ("Väinö Linna", "Tove Jansson", "J. R. R. Tolkien"):
        found = WikipediaBios(http).lookup(name)
        check(f"esittely: {name}", found is not None, (found[1] if found else "ei löytynyt"))
        if found:
            print(f"      {found[0][:110]}…")

    print(f"\n{'Kaikki OK' if not failures else f'{failures} virhettä'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
