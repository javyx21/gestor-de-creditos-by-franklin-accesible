import pytest

from gestor_credito.db import database
from gestor_credito.db.convenios import eliminar_convenio, guardar_tasa, listar_convenios, obtener_tasa


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def test_se_siembran_las_empresas_reales_del_excel(conn):
    assert obtener_tasa(conn, "IMMSA") == 0.36
    assert obtener_tasa(conn, "NICAES") == 0.60
    assert obtener_tasa(conn, "MIDESA") == 0.18


def test_empresas_sin_tasa_definida_en_el_excel_original_devuelven_none(conn):
    assert obtener_tasa(conn, "GRUPO TALSE") is None
    assert obtener_tasa(conn, "LABORATORIOS ROMAN") is None


def test_empresa_desconocida_devuelve_none(conn):
    assert obtener_tasa(conn, "EMPRESA QUE NO EXISTE") is None


def test_obtener_tasa_ignora_espacios_de_mas(conn):
    assert obtener_tasa(conn, "  IMMSA  ") == 0.36


def test_guardar_tasa_crea_una_empresa_nueva(conn):
    guardar_tasa(conn, "EMPRESA NUEVA", 0.5)
    assert obtener_tasa(conn, "EMPRESA NUEVA") == 0.5


def test_guardar_tasa_actualiza_una_existente(conn):
    guardar_tasa(conn, "IMMSA", 0.40)
    assert obtener_tasa(conn, "IMMSA") == 0.40


def test_listar_convenios_incluye_las_29_empresas_sembradas(conn):
    convenios = listar_convenios(conn)
    assert len(convenios) == 29
    assert ("IMMSA", 0.36) in convenios
    assert ("GRUPO TALSE", None) in convenios


def test_eliminar_convenio_la_quita_de_la_lista(conn):
    eliminar_convenio(conn, "IMMSA")
    assert obtener_tasa(conn, "IMMSA") is None
    assert "IMMSA" not in [empresa for empresa, _tasa in listar_convenios(conn)]


def test_eliminar_convenio_de_una_empresa_inexistente_no_falla(conn):
    eliminar_convenio(conn, "EMPRESA QUE NO EXISTE")
