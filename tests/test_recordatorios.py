from datetime import datetime, timedelta

import pytest

from gestor_credito.db import database
from gestor_credito.db.recordatorios import (
    actualizar_recordatorio,
    buscar_datos_credito_por_cedula,
    crear_recordatorio,
    eliminar_recordatorio,
    esta_vencido,
    listar_recordatorios,
    marcar_atendido,
    obtener_recordatorios_vencidos,
    posponer_recordatorio,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _crear(conn, nombre="Juan Perez", cedula="001-0000001-1", celular="8091234567",
           empresa="MIDESA", fecha_llamar="2026-01-10", hora_llamar="09:00", ejecutivo="fmartinez"):
    return crear_recordatorio(conn, nombre, cedula, celular, empresa, fecha_llamar, hora_llamar, ejecutivo)


def _hace_minutos(minutos):
    return datetime.now() - timedelta(minutes=minutos)


def _en_minutos(minutos):
    return datetime.now() + timedelta(minutes=minutos)


# --- CRUD básico -------------------------------------------------------------

def test_crear_y_listar_recordatorio(conn):
    _crear(conn)

    filas = listar_recordatorios(conn)

    assert len(filas) == 1
    assert filas[0]["nombre"] == "Juan Perez"
    assert filas[0]["cedula"] == "001-0000001-1"
    assert filas[0]["atendido"] == 0
    assert filas[0]["pospuesto_hasta"] is None


def test_actualizar_recordatorio(conn):
    recordatorio_id = _crear(conn)

    actualizar_recordatorio(
        conn, recordatorio_id, "Juana Perez", "001-0000001-1", "8099999999",
        "NICAES", "2026-02-15", "14:30",
    )

    fila = listar_recordatorios(conn)[0]
    assert fila["nombre"] == "Juana Perez"
    assert fila["celular"] == "8099999999"
    assert fila["empresa_convenio"] == "NICAES"
    assert fila["fecha_llamar"] == "2026-02-15"
    assert fila["hora_llamar"] == "14:30"


def test_eliminar_recordatorio(conn):
    recordatorio_id = _crear(conn)

    eliminar_recordatorio(conn, recordatorio_id)

    assert listar_recordatorios(conn) == []


def test_marcar_atendido(conn):
    recordatorio_id = _crear(conn)
    ahora = datetime(2026, 1, 10, 9, 5)

    marcar_atendido(conn, recordatorio_id, ahora=ahora)

    fila = listar_recordatorios(conn)[0]
    assert fila["atendido"] == 1
    assert fila["fecha_atendido"] == "2026-01-10 09:05:00"


def test_listar_recordatorios_scoped_por_ejecutivo(conn):
    _crear(conn, nombre="De Fernanda", ejecutivo="fmartinez")
    _crear(conn, nombre="De Otro Agente", ejecutivo="otro")
    _crear(conn, nombre="Legado sin agente", ejecutivo=None)

    filas = listar_recordatorios(conn, ejecutivo_actual="fmartinez")

    nombres = {f["nombre"] for f in filas}
    assert nombres == {"De Fernanda", "Legado sin agente"}


def test_listar_recordatorios_sin_ejecutivo_actual_trae_todos(conn):
    _crear(conn, nombre="Uno", ejecutivo="fmartinez")
    _crear(conn, nombre="Dos", ejecutivo="otro")

    filas = listar_recordatorios(conn)

    assert {f["nombre"] for f in filas} == {"Uno", "Dos"}


# --- esta_vencido / obtener_recordatorios_vencidos ---------------------------

def test_esta_vencido_true_cuando_ya_paso_la_hora():
    ahora = datetime(2026, 1, 10, 9, 5)
    recordatorio = {"fecha_llamar": "2026-01-10", "hora_llamar": "09:00", "pospuesto_hasta": None}

    assert esta_vencido(recordatorio, ahora) is True


def test_esta_vencido_false_cuando_todavia_no_llega_la_hora():
    ahora = datetime(2026, 1, 10, 8, 55)
    recordatorio = {"fecha_llamar": "2026-01-10", "hora_llamar": "09:00", "pospuesto_hasta": None}

    assert esta_vencido(recordatorio, ahora) is False


def test_esta_vencido_false_mientras_pospuesto_no_haya_llegado():
    ahora = datetime(2026, 1, 10, 9, 5)
    recordatorio = {
        "fecha_llamar": "2026-01-10", "hora_llamar": "09:00",
        "pospuesto_hasta": "2026-01-10 09:10:00",
    }

    assert esta_vencido(recordatorio, ahora) is False


def test_esta_vencido_true_cuando_ya_paso_la_posposicion():
    ahora = datetime(2026, 1, 10, 9, 15)
    recordatorio = {
        "fecha_llamar": "2026-01-10", "hora_llamar": "09:00",
        "pospuesto_hasta": "2026-01-10 09:10:00",
    }

    assert esta_vencido(recordatorio, ahora) is True


def test_obtener_recordatorios_vencidos_excluye_atendidos(conn):
    ahora = datetime.now()
    recordatorio_id = _crear(
        conn, fecha_llamar=(ahora - timedelta(minutes=10)).strftime("%Y-%m-%d"),
        hora_llamar=(ahora - timedelta(minutes=10)).strftime("%H:%M"),
    )
    marcar_atendido(conn, recordatorio_id)

    assert obtener_recordatorios_vencidos(conn, ahora=ahora) == []


def test_obtener_recordatorios_vencidos_excluye_no_vencidos(conn):
    ahora = datetime.now()
    futuro = ahora + timedelta(hours=1)
    _crear(conn, fecha_llamar=futuro.strftime("%Y-%m-%d"), hora_llamar=futuro.strftime("%H:%M"))

    assert obtener_recordatorios_vencidos(conn, ahora=ahora) == []


def test_obtener_recordatorios_vencidos_incluye_vencidos_no_atendidos(conn):
    ahora = datetime.now()
    pasado = ahora - timedelta(minutes=5)
    _crear(conn, nombre="A Llamar Ya", fecha_llamar=pasado.strftime("%Y-%m-%d"), hora_llamar=pasado.strftime("%H:%M"))

    vencidos = obtener_recordatorios_vencidos(conn, ahora=ahora)

    assert len(vencidos) == 1
    assert vencidos[0]["nombre"] == "A Llamar Ya"


def test_posponer_recordatorio_lo_saca_de_vencidos_hasta_que_pase_el_plazo(conn):
    ahora = datetime.now()
    pasado = ahora - timedelta(minutes=5)
    recordatorio_id = _crear(
        conn, fecha_llamar=pasado.strftime("%Y-%m-%d"), hora_llamar=pasado.strftime("%H:%M")
    )

    posponer_recordatorio(conn, recordatorio_id, minutos=5, ahora=ahora)

    assert obtener_recordatorios_vencidos(conn, ahora=ahora) == []
    assert obtener_recordatorios_vencidos(conn, ahora=ahora + timedelta(minutes=6)) != []


# --- buscar_datos_credito_por_cedula -----------------------------------------
# Busca en Historial de Créditos (reporte_credito), NO en Casos — corregido
# 2026-09-07 tras un reporte real del usuario ("estás buscando en los
# clientes de Casos... es en el histórico que tienes que buscar").

def _crear_credito(conn, no_credito, cedula, nombre_cliente, empresa_convenio, fecha_desembolso):
    conn.execute(
        """
        INSERT INTO reporte_credito
            (no_credito, cedula, nombre_cliente, empresa_convenio, fecha_desembolso)
        VALUES (?, ?, ?, ?, ?)
        """,
        (no_credito, cedula, nombre_cliente, empresa_convenio, fecha_desembolso),
    )
    conn.commit()


def test_buscar_datos_credito_por_cedula_sin_coincidencia(conn):
    assert buscar_datos_credito_por_cedula(conn, "000-0000000-0") is None


def test_buscar_datos_credito_por_cedula_no_autocompleta_telefono(conn):
    # reporte_credito no tiene columna de teléfono — el campo Celular del
    # formulario de Recordatorios de Llamada siempre queda para llenar a mano.
    _crear_credito(conn, "C-1", "001-1111111-1", "Cliente Con Credito", "MIDESA", "2026-01-01")

    datos = buscar_datos_credito_por_cedula(conn, "001-1111111-1")

    assert datos == {"nombre": "Cliente Con Credito", "telefono": None, "empresa_convenio": "MIDESA"}


def test_buscar_datos_credito_por_cedula_usa_el_credito_mas_reciente(conn):
    _crear_credito(conn, "C-1", "001-2222222-2", "Cliente Con Creditos", "MIDESA", "2025-01-01")
    _crear_credito(conn, "C-2", "001-2222222-2", "Cliente Con Creditos", "NICAES", "2026-01-01")

    datos = buscar_datos_credito_por_cedula(conn, "001-2222222-2")

    assert datos["empresa_convenio"] == "NICAES"


def test_buscar_datos_credito_por_cedula_es_insensible_a_mayusculas(conn):
    # Pedido explícito del usuario: la letra final de una cédula (p. ej.
    # "...010Q") tiene que encontrarse sin importar si se busca en mayúscula
    # o minúscula, nunca quedar sin resultado por eso.
    _crear_credito(conn, "C-1", "2011307810010Q", "Cliente Con Letra", "MIDESA", "2026-01-01")

    assert buscar_datos_credito_por_cedula(conn, "2011307810010q") is not None
    assert buscar_datos_credito_por_cedula(conn, "2011307810010Q") is not None
