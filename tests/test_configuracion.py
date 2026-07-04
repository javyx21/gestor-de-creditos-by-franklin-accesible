import pytest

from gestor_credito.db import database
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, guardar_valor, obtener_valor


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def test_obtener_valor_no_configurado_devuelve_none(conn):
    assert obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL) is None


def test_guardar_y_obtener_valor(conn):
    guardar_valor(conn, CLAVE_EJECUTIVO_ACTUAL, "fmartinez")

    assert obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL) == "fmartinez"


def test_guardar_valor_sobrescribe_el_anterior(conn):
    guardar_valor(conn, CLAVE_EJECUTIVO_ACTUAL, "fmartinez")
    guardar_valor(conn, CLAVE_EJECUTIVO_ACTUAL, "osanchez")

    assert obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL) == "osanchez"
