import importlib.util
import os
import sqlite3
import tarfile

import pytest

_spec = importlib.util.spec_from_file_location(
    "backup_script", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "backup.py")
)
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


@pytest.fixture
def env(store, tmp_path):
    user = store.create_user("a@example.com", "Aino")
    book = store.create_book("Kalevala", "Elias Lönnrot")
    store.create_entry(user["id"], book["id"], "2026-10-01", note="hyvä")
    covers = tmp_path / "covers"
    covers.mkdir()
    (covers / "1.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 50)
    return store, str(covers), str(tmp_path / "backups")


def test_backup_contains_consistent_db_and_covers(env):
    store, covers, out = env
    path = backup.create_backup(store.db_path, covers, out)
    assert os.path.basename(path).startswith("kirjapaivakirja-") and path.endswith(".tar.gz")
    with tarfile.open(path) as archive:
        assert sorted(archive.getnames()) == ["covers/1.jpg", "kirjapaivakirja.db"]
    assert [n for n in os.listdir(out) if not n.endswith(".tar.gz")] == []  # ei jäänteitä


def test_backup_works_without_covers_dir(env):
    store, _covers, out = env
    path = backup.create_backup(store.db_path, "/ei/ole/olemassa", out)
    with tarfile.open(path) as archive:
        assert archive.getnames() == ["kirjapaivakirja.db"]


def test_rotation_keeps_newest_and_ignores_foreign_files(env):
    store, covers, out = env
    os.makedirs(out)
    for stamp in ("20250101-000000", "20250102-000000", "20250103-000000"):
        open(os.path.join(out, f"kirjapaivakirja-{stamp}.tar.gz"), "wb").close()
    open(os.path.join(out, "muistiinpano.txt"), "w").close()
    backup.create_backup(store.db_path, covers, out, keep=2)
    names = sorted(os.listdir(out))
    assert "muistiinpano.txt" in names
    archives = [n for n in names if n.endswith(".tar.gz")]
    assert len(archives) == 2 and "kirjapaivakirja-20250101-000000.tar.gz" not in archives
    assert "kirjapaivakirja-20250103-000000.tar.gz" in archives  # toiseksi uusin säilyy


def test_restore_brings_back_data_and_keeps_previous(env, tmp_path):
    store, covers, out = env
    path = backup.create_backup(store.db_path, covers, out)
    # myöhempi muutos, joka palautuksen pitää kumota
    store.create_book("Uusi kirja", "Joku")
    os.remove(os.path.join(covers, "1.jpg"))
    open(os.path.join(covers, "2.jpg"), "wb").write(b"x")

    backup.restore_backup(path, store.db_path, covers)

    titles = [b["title"] for b in store.list_books()]
    assert titles == ["Kalevala"]
    assert os.listdir(covers) == ["1.jpg"]
    assert os.path.exists(store.db_path + ".before-restore")
    assert sorted(os.listdir(covers + ".before-restore")) == ["2.jpg"]
    conn = sqlite3.connect(store.db_path)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def _evil_archive(tmp_path, name, data=b"x"):
    import io
    path = str(tmp_path / "evil.tar.gz")
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return path


@pytest.mark.parametrize("name", ["../x", "/etc/passwd", "covers/../../x", "covers/a/b.jpg", "covers/..", "covers/.hidden", "muu.txt"])
def test_restore_rejects_unexpected_archive_members(env, tmp_path, name):
    store, covers, _out = env
    evil = _evil_archive(tmp_path, name)
    with pytest.raises(ValueError):
        backup.restore_backup(evil, store.db_path, covers)
    assert [b["title"] for b in store.list_books()] == ["Kalevala"]  # ei kosketa nykyiseen dataan


def test_restore_rejects_archive_without_valid_database(env, tmp_path):
    store, covers, _out = env
    with pytest.raises(ValueError):
        backup.restore_backup(_evil_archive(tmp_path, "covers/1.jpg"), store.db_path, covers)
    with pytest.raises(ValueError):  # ei SQLite-tiedosto
        backup.restore_backup(_evil_archive(tmp_path, "kirjapaivakirja.db", b"ei tietokanta" * 20), store.db_path, covers)
    assert [b["title"] for b in store.list_books()] == ["Kalevala"]
