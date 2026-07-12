import pytest

from gestor_credito.db import database
from gestor_credito.db.reporte_creditos import ESTADO_CREDITO_ACTIVO, buscar_creditos


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _crear_credito(conn, no_credito, cedula="001-1234567-8", nombre="Juan Perez",
                    estado="Corriente", fecha_desembolso="2026-06-01", **overrides):
    valores = {
        "no_credito": no_credito,
        "cedula": cedula,
        "nombre_cliente": nombre,
        "fecha_desembolso": fecha_desembolso,
        "fecha_vencimiento": "2027-06-01",
        "monto_desembolsado": 1000.0,
        "estado_credito": estado,
        "empresa_convenio": "MIDESA",
        "plazo_credito": 24,
        "cuotas_pagadas": 3,
    }
    valores.update(overrides)
    columnas = ", ".join(valores.keys())
    placeholders = ", ".join("?" for _ in valores)
    conn.execute(
        f"INSERT INTO reporte_credito ({columnas}) VALUES ({placeholders})",
        list(valores.values()),
    )
    conn.commit()


def test_estado_activo_es_corriente():
    assert ESTADO_CREDITO_ACTIVO == "Corriente"


def test_vista_por_defecto_solo_muestra_corriente(conn):
    _crear_credito(conn, "C-1", cedula="001", nombre="Ana Lopez", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", nombre="Beto Cruz", estado="Cancelado")
    _crear_credito(conn, "C-3", cedula="003", nombre="Carla Ruiz", estado="Vencido")
    _crear_credito(conn, "C-4", cedula="004", nombre="Dario Vega", estado="Saneado")
    _crear_credito(conn, "C-5", cedula="005", nombre="Elsa Mora", estado="Trámite")

    filas = buscar_creditos(conn)

    no_creditos = [f[1] for f in filas]
    assert no_creditos == ["C-1"]


def test_busqueda_por_cedula_muestra_todo_el_historial_sin_filtrar_por_estado(conn):
    _crear_credito(conn, "C-1", cedula="0012510940057N", estado="Corriente",
                    fecha_desembolso="2026-06-30")
    _crear_credito(conn, "C-2", cedula="0012510940057N", estado="Cancelado",
                    fecha_desembolso="2025-06-16")
    _crear_credito(conn, "C-3", cedula="999", estado="Corriente")

    filas = buscar_creditos(conn, termino="0012510940057N")

    no_creditos = [f[1] for f in filas]
    assert no_creditos == ["C-1", "C-2"]


def test_busqueda_por_cedula_es_parcial(conn):
    _crear_credito(conn, "C-1", cedula="0012510940057N")

    filas = buscar_creditos(conn, termino="2510940057")
    assert [f[1] for f in filas] == ["C-1"]


def test_busqueda_por_cedula_es_insensible_a_mayusculas(conn):
    # Mismo reporte real del usuario (2026-07-12) que en Casos: una cédula
    # con sufijo de letra en mayúscula no se encontraba en minúscula.
    _crear_credito(conn, "C-1", cedula="0012510940057N")

    filas = buscar_creditos(conn, termino="0012510940057n")
    assert [f[1] for f in filas] == ["C-1"]


def test_busqueda_por_nombre_es_insensible_a_mayusculas_y_parcial(conn):
    _crear_credito(conn, "C-1", nombre="Karla Vanessa Cortez Selva")

    filas = buscar_creditos(conn, termino="vanessa")
    assert [f[1] for f in filas] == ["C-1"]


def test_busqueda_por_nombre_no_tolera_tildes_incorrectas(conn):
    _crear_credito(conn, "C-1", nombre="PEÑA")

    assert buscar_creditos(conn, termino="PENA") == []
    assert [f[1] for f in buscar_creditos(conn, termino="PEÑA")] == ["C-1"]


def test_termino_invalido_propaga_error(conn):
    with pytest.raises(ValueError):
        buscar_creditos(conn, termino="#$%")


def test_historial_ordenado_del_mas_reciente_al_mas_antiguo(conn):
    _crear_credito(conn, "C-1", cedula="001", nombre="Karla Cortez", fecha_desembolso="2024-01-01")
    _crear_credito(conn, "C-2", cedula="001", nombre="Karla Cortez", fecha_desembolso="2026-06-30")
    _crear_credito(conn, "C-3", cedula="001", nombre="Karla Cortez", fecha_desembolso="2025-03-15")

    filas = buscar_creditos(conn, termino="001")
    assert [f[1] for f in filas] == ["C-2", "C-3", "C-1"]


def test_no_credito_es_unico_reimportar_actualiza_no_duplica(conn):
    _crear_credito(conn, "C-1", estado="Corriente")
    with pytest.raises(Exception):
        # UNIQUE(no_credito): un INSERT directo duplicado debe fallar a nivel
        # de esquema (la lógica real de upsert vive en el importador, no acá).
        _crear_credito(conn, "C-1", estado="Cancelado")
