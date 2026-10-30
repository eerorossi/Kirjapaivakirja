#!/usr/bin/env python3
"""Täydennä jo tallennettujen kirjojen puuttuva kuvaus ja kansikuva.

Hakee ulkoisesta lähteestä uudelleen kirjat, joilta puuttuu kuvaus tai kansi.
Ei koske olemassa oleviin tietoihin eikä kirjauksiin. Aja kontissa:

    docker compose exec kirjapaivakirja python scripts/refresh_books.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import ProviderError  # noqa: E402
from service import build_default_service  # noqa: E402
from store import Store  # noqa: E402


def main() -> int:
    store = Store()
    service = build_default_service()
    covers_dir = os.getenv("COVERS_DIR", "/app/data/covers")
    try:
        for book in store.list_books(limit=100000):
            if not service.has_source(book["source"] or ""):
                continue  # käsin lisätty kirja
            missing_summary = not book["summary"]
            missing_cover = not book["cover_path"]
            if not (missing_summary or missing_cover):
                continue
            label = f"#{book['id']} {book['title']}"
            try:
                result = service.fetch(book["source"], book["source_id"])
            except ProviderError as exc:
                print(f"{label}: lähde ei vastannut ({exc})")
                continue
            if result is None:
                print(f"{label}: ei löytynyt lähteestä")
                continue
            done = []
            if missing_summary and result.summary:
                store.set_summary(book["id"], result.summary)
                done.append("kuvaus")
            if missing_cover:
                cover = service.download_cover(result)
                if cover:
                    data, extension = cover
                    os.makedirs(covers_dir, exist_ok=True)
                    name = f"{book['id']}.{extension}"
                    with open(os.path.join(covers_dir, name), "wb") as handle:
                        handle.write(data)
                    store.set_cover_path(book["id"], name)
                    done.append("kansi")
            print(f"{label}: {', '.join(done) if done else 'ei uutta täydennettävää'}")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
