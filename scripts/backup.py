#!/usr/bin/env python3
"""Varmuuskopio ja palautus: SQLite-tietokanta + kansikuvat yhdeksi tar.gz-tiedostoksi.

Aja kontissa (sovelluksen ei tarvitse olla pysäytettynä; tietokanta kopioidaan
SQLiten omalla backup-rajapinnalla, joten kopio on aina eheä):

    docker compose exec -T kirjapaivakirja python scripts/backup.py backup

Palautus (pysäytä sovellus ensin):

    docker compose stop
    docker compose run --rm kirjapaivakirja python scripts/backup.py restore /app/data/backups/<tiedosto>.tar.gz
    docker compose start

Ympäristömuuttujat: DB_PATH, COVERS_DIR, BACKUP_DIR (oletus /app/data/backups),
BACKUP_KEEP (montako uusinta varmuuskopiota säilytetään, oletus 14).
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime

DB_NAME = "kirjapaivakirja.db"
COVERS_PREFIX = "covers/"
ARCHIVE_RE = re.compile(r"^kirjapaivakirja-\d{8}-\d{6}\.tar\.gz$")
SAFE_COVER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def create_backup(db_path: str, covers_dir: str, backup_dir: str, keep: int = 14) -> str:
    """Luo varmuuskopio ja poista vanhimmat, kunnes `keep` uusinta on jäljellä. Palauttaa polun."""
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(backup_dir, f"kirjapaivakirja-{stamp}.tar.gz")
    with tempfile.TemporaryDirectory(dir=backup_dir) as tmp:
        snapshot = os.path.join(tmp, DB_NAME)
        source = sqlite3.connect(db_path)
        try:
            dest = sqlite3.connect(snapshot)
            try:
                source.backup(dest)  # eheä kopio myös käytön aikana
            finally:
                dest.close()
        finally:
            source.close()
        partial = target + ".part"
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(snapshot, arcname=DB_NAME)
            if os.path.isdir(covers_dir):
                for name in sorted(os.listdir(covers_dir)):
                    path = os.path.join(covers_dir, name)
                    if os.path.isfile(path) and SAFE_COVER_RE.match(name):
                        archive.add(path, arcname=COVERS_PREFIX + name)
        os.replace(partial, target)  # valmis tiedosto ilmestyy kerralla
    _rotate(backup_dir, keep)
    return target


def _rotate(backup_dir: str, keep: int) -> None:
    archives = sorted(n for n in os.listdir(backup_dir) if ARCHIVE_RE.match(n))
    for name in archives[: max(0, len(archives) - max(1, keep))]:
        os.remove(os.path.join(backup_dir, name))


def restore_backup(archive_path: str, db_path: str, covers_dir: str) -> None:
    """Palauta varmuuskopio. Vanhat tiedot jäävät talteen (.before-restore); sovellus on pysäytettävä."""
    with tempfile.TemporaryDirectory() as tmp:
        covers_tmp = os.path.join(tmp, "covers")
        os.makedirs(covers_tmp)
        db_tmp = os.path.join(tmp, DB_NAME)
        found_db = False
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    raise ValueError(f"Odottamaton kohde arkistossa: {member.name}")
                if member.name == DB_NAME:
                    found_db = True
                    dest = db_tmp
                elif member.name.startswith(COVERS_PREFIX) and SAFE_COVER_RE.match(member.name[len(COVERS_PREFIX):]):
                    dest = os.path.join(covers_tmp, member.name[len(COVERS_PREFIX):])
                else:
                    raise ValueError(f"Odottamaton tiedosto arkistossa: {member.name}")
                with archive.extractfile(member) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        if not found_db:
            raise ValueError("Arkistossa ei ole tietokantaa")
        check = sqlite3.connect(db_tmp)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Arkiston tietokanta ei ole eheä")
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"Arkiston tietokanta ei ole kelvollinen: {exc}") from exc
        finally:
            check.close()

        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        if os.path.exists(db_path):
            shutil.move(db_path, db_path + ".before-restore")
        for suffix in ("-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                os.remove(db_path + suffix)
        shutil.move(db_tmp, db_path)

        old_covers = covers_dir.rstrip("/") + ".before-restore"
        if os.path.isdir(old_covers):
            shutil.rmtree(old_covers)
        if os.path.isdir(covers_dir):
            os.rename(covers_dir, old_covers)
        shutil.move(covers_tmp, covers_dir)


def main(argv: list[str]) -> int:
    db_path = os.getenv("DB_PATH", f"/app/data/{DB_NAME}")
    covers_dir = os.getenv("COVERS_DIR", "/app/data/covers")
    backup_dir = os.getenv("BACKUP_DIR", "/app/data/backups")
    if len(argv) >= 2 and argv[1] == "backup":
        if not os.path.exists(db_path):
            print(f"Tietokantaa ei löydy: {db_path}", file=sys.stderr)
            return 1
        keep = int(os.getenv("BACKUP_KEEP", "14"))
        target = create_backup(db_path, covers_dir, backup_dir, keep)
        print(f"Varmuuskopio valmis: {target} ({os.path.getsize(target) // 1024} kt)")
        return 0
    if len(argv) == 3 and argv[1] == "restore":
        restore_backup(argv[2], db_path, covers_dir)
        print(f"Palautettu: {argv[2]}. Vanhat tiedot: {db_path}.before-restore ja {covers_dir}.before-restore")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
