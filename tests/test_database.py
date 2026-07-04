from gestor_credito.db import database


def test_init_db_creates_file(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)

    database.init_db()

    assert db_file.exists()
