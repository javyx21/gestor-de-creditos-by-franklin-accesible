from datetime import datetime, timedelta, timezone

import pytest

from gestor_credito.db import database
from gestor_credito.db.alertas import (
    alertas_constancia_en_mano,
    alertas_constancia_pendiente,
    alertas_documentos_pendientes,
    marcar_documentos_completos,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _hace(horas=0, dias=0):
    """Fecha/hora UTC "hace X horas/días", en el mismo formato que datetime('now')
    de SQLite (siempre UTC), para poder controlar los umbrales en los tests."""
    momento = datetime.now(timezone.utc) - timedelta(hours=horas, days=dias)
    return momento.strftime("%Y-%m-%d %H:%M:%S")


def _crear_cliente(conn, cedula="001-0000001-1", nombre="Juan Perez",
                    fecha_creacion=None, documentos_completos_fecha=None):
    cur = conn.execute(
        "INSERT INTO cliente (cedula, nombre, telefono, fecha_creacion, documentos_completos_fecha) "
        "VALUES (?, ?, '8091234567', ?, ?)",
        (cedula, nombre, fecha_creacion or _hace(), documentos_completos_fecha),
    )
    conn.commit()
    return cur.lastrowid


def _crear_caso(conn, cliente_id, clave_caso="P-9001", ejecutivo="Maria Gomez",
                 estado_solicitud="En proceso", estado_solicitud_fecha_cambio=None,
                 constancia_recibida_fecha=None, fecha_creacion_registro=None):
    cur = conn.execute(
        """
        INSERT INTO caso (cliente_id, clave_caso, ejecutivo, estado_solicitud,
                           estado_solicitud_fecha_cambio, constancia_recibida_fecha,
                           fecha_creacion_registro)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cliente_id, clave_caso, ejecutivo, estado_solicitud,
            estado_solicitud_fecha_cambio or _hace(), constancia_recibida_fecha,
            fecha_creacion_registro or _hace(),
        ),
    )
    conn.commit()
    return cur.lastrowid


# --- Alerta "Documentos pendientes" -----------------------------------------

def test_documentos_pendientes_activa_a_las_24h(conn):
    cliente_id = _crear_cliente(conn, fecha_creacion=_hace(horas=25))
    _crear_caso(conn, cliente_id, ejecutivo="Maria Gomez")

    activas = alertas_documentos_pendientes(conn)

    assert len(activas) == 1
    assert activas[0]["cliente_id"] == cliente_id


def test_documentos_pendientes_no_activa_antes_de_24h(conn):
    cliente_id = _crear_cliente(conn, fecha_creacion=_hace(horas=1))
    _crear_caso(conn, cliente_id)

    assert alertas_documentos_pendientes(conn) == []


def test_documentos_pendientes_sigue_activa_pasadas_48h(conn):
    # No se apaga sola por tiempo, solo al marcar documentos_completos_fecha.
    cliente_id = _crear_cliente(conn, fecha_creacion=_hace(dias=30))
    _crear_caso(conn, cliente_id)

    activas = alertas_documentos_pendientes(conn)

    assert len(activas) == 1


def test_documentos_pendientes_se_apaga_al_marcar_completo(conn):
    cliente_id = _crear_cliente(conn, fecha_creacion=_hace(dias=10))
    _crear_caso(conn, cliente_id)

    marcar_documentos_completos(conn, cliente_id)

    assert alertas_documentos_pendientes(conn) == []


def test_documentos_pendientes_no_activa_si_todos_los_casos_estan_cerrados(conn):
    """Bug real reportado por el usuario en producción: un cliente cuyo único
    crédito ya está Desembolsada obviamente tuvo documentos completos para
    llegar hasta ahí — no debería seguir alertando para siempre solo porque
    nadie marcó documentos_completos_fecha a mano. Mismo criterio que ya usa
    el filtro de Casos (FILTRO_ALERTA_DOCUMENTOS_PENDIENTES)."""
    cliente_id = _crear_cliente(conn, fecha_creacion=_hace(dias=10))
    _crear_caso(conn, cliente_id, estado_solicitud="Desembolsada")

    assert alertas_documentos_pendientes(conn) == []


def test_documentos_pendientes_activa_si_al_menos_un_caso_sigue_abierto(conn):
    cliente_id = _crear_cliente(conn, fecha_creacion=_hace(dias=10))
    _crear_caso(conn, cliente_id, clave_caso="P-1", estado_solicitud="Desembolsada")
    _crear_caso(conn, cliente_id, clave_caso="P-2", estado_solicitud="En proceso")

    activas = alertas_documentos_pendientes(conn)

    assert len(activas) == 1
    assert activas[0]["cliente_id"] == cliente_id


def test_documentos_pendientes_filtra_por_ejecutivo(conn):
    cliente_1 = _crear_cliente(conn, cedula="001-0000001-1", fecha_creacion=_hace(dias=2))
    _crear_caso(conn, cliente_1, clave_caso="P-1", ejecutivo="Maria Gomez")
    cliente_2 = _crear_cliente(conn, cedula="001-0000002-2", fecha_creacion=_hace(dias=2))
    _crear_caso(conn, cliente_2, clave_caso="P-2", ejecutivo="Pedro Diaz")

    activas = alertas_documentos_pendientes(conn, ejecutivo_actual="Maria Gomez")

    assert len(activas) == 1
    assert activas[0]["cliente_id"] == cliente_1


# --- Alerta "Constancia pendiente" ------------------------------------------

def test_constancia_pendiente_activa_a_los_7_dias(conn):
    cliente_id = _crear_cliente(conn)
    caso_id = _crear_caso(
        conn, cliente_id, estado_solicitud="En espera de constancia",
        estado_solicitud_fecha_cambio=_hace(dias=7, horas=1),
    )

    activas = alertas_constancia_pendiente(conn)

    assert len(activas) == 1
    assert activas[0]["caso_id"] == caso_id


def test_constancia_pendiente_no_activa_antes_de_7_dias(conn):
    cliente_id = _crear_cliente(conn)
    _crear_caso(
        conn, cliente_id, estado_solicitud="En espera de constancia",
        estado_solicitud_fecha_cambio=_hace(dias=6),
    )

    assert alertas_constancia_pendiente(conn) == []


def test_constancia_pendiente_requiere_estado_en_espera(conn):
    cliente_id = _crear_cliente(conn)
    _crear_caso(
        conn, cliente_id, estado_solicitud="En proceso",
        estado_solicitud_fecha_cambio=_hace(dias=10),
    )

    assert alertas_constancia_pendiente(conn) == []


# --- Alerta "Constancia en mano" --------------------------------------------

def test_constancia_en_mano_activa_a_las_48h(conn):
    cliente_id = _crear_cliente(conn)
    caso_id = _crear_caso(
        conn, cliente_id, estado_solicitud="En proceso",
        estado_solicitud_fecha_cambio=_hace(horas=49),
    )

    activas = alertas_constancia_en_mano(conn)

    assert len(activas) == 1
    assert activas[0]["caso_id"] == caso_id


def test_constancia_en_mano_no_activa_antes_de_48h(conn):
    cliente_id = _crear_cliente(conn)
    _crear_caso(
        conn, cliente_id, estado_solicitud="En proceso",
        estado_solicitud_fecha_cambio=_hace(horas=10),
    )

    assert alertas_constancia_en_mano(conn) == []


def test_constancia_en_mano_activa_aunque_nunca_se_detecto_la_transicion(conn):
    """Bug real reportado por el usuario: un caso importado por primera vez ya
    en "En proceso" (constancia_recibida_fecha nunca se estampa, porque no hubo
    ninguna transición "En espera de constancia" -> "En proceso" que el
    importador pudiera ver en vivo) debe activar esta alerta igual, usando
    estado_solicitud_fecha_cambio en vez de constancia_recibida_fecha."""
    cliente_id = _crear_cliente(conn)
    caso_id = _crear_caso(
        conn, cliente_id, estado_solicitud="En proceso",
        estado_solicitud_fecha_cambio=_hace(horas=49), constancia_recibida_fecha=None,
    )

    activas = alertas_constancia_en_mano(conn)

    assert len(activas) == 1
    assert activas[0]["caso_id"] == caso_id


def test_constancia_en_mano_se_apaga_al_salir_de_en_proceso(conn):
    cliente_id = _crear_cliente(conn)
    _crear_caso(
        conn, cliente_id, estado_solicitud="Desembolsada",
        estado_solicitud_fecha_cambio=_hace(horas=100),
    )

    assert alertas_constancia_en_mano(conn) == []
