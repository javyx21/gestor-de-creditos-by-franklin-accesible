import pytest

from gestor_credito.db import database
from gestor_credito.db.casos import (
    actualizar_edicion_manual,
    buscar_casos,
    clasificar_termino_busqueda,
    obtener_ejecutivos,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _crear_cliente_y_caso(conn, cedula="001-1234567-8", ejecutivo="Maria Gomez",
                           estado="En espera de constancia", nombre="Juan Perez",
                           no_presolicitud="P-9001"):
    cur = conn.execute(
        "INSERT INTO cliente (cedula, nombre, telefono) VALUES (?, ?, ?)",
        (cedula, nombre, "8091234567"),
    )
    cliente_id = cur.lastrowid
    cur = conn.execute(
        """
        INSERT INTO caso (cliente_id, no_presolicitud, clave_caso, ejecutivo,
                           estado_solicitud, etapa_proceso, fecha_registro)
        VALUES (?, ?, ?, ?, ?, 'Verificacion', '2026-06-20')
        """,
        (cliente_id, no_presolicitud, no_presolicitud, ejecutivo, estado),
    )
    conn.commit()
    return cur.lastrowid


# --- clasificar_termino_busqueda -------------------------------------------

def test_clasificar_solo_digitos_es_cedula():
    assert clasificar_termino_busqueda("12345678") == "cedula"


def test_clasificar_cedula_con_sufijo_de_letra():
    assert clasificar_termino_busqueda("2011307810010Q") == "cedula"


def test_clasificar_cedula_con_guiones():
    assert clasificar_termino_busqueda("001-1234567-8") == "cedula"


def test_clasificar_solo_letras_es_nombre():
    assert clasificar_termino_busqueda("Armando") == "nombre"
    assert clasificar_termino_busqueda("PEÑA") == "nombre"


def test_clasificar_caracter_invalido_lanza_error():
    with pytest.raises(ValueError):
        clasificar_termino_busqueda("armando@")
    with pytest.raises(ValueError):
        clasificar_termino_busqueda("#$%")


# --- buscar_casos ------------------------------------------------------------

def test_buscar_sin_termino_filtra_por_agente_configurado(conn):
    _crear_cliente_y_caso(conn, cedula="001-0000001-1", ejecutivo="Maria Gomez")
    _crear_cliente_y_caso(conn, cedula="001-0000002-2", ejecutivo="Pedro Diaz")

    resultado = buscar_casos(conn, ejecutivo_actual="Maria Gomez")

    assert len(resultado) == 1
    assert resultado[0][6] == "001-0000001-1"


def test_buscar_sin_termino_ni_agente_trae_todo(conn):
    _crear_cliente_y_caso(conn, cedula="001-0000001-1", ejecutivo="Maria Gomez")
    _crear_cliente_y_caso(conn, cedula="001-0000002-2", ejecutivo="Pedro Diaz")

    resultado = buscar_casos(conn, ejecutivo_actual=None)

    assert len(resultado) == 2


def test_buscar_por_cedula_ignora_el_filtro_de_agente(conn):
    _crear_cliente_y_caso(conn, cedula="001-0000001-1", ejecutivo="Maria Gomez")
    _crear_cliente_y_caso(conn, cedula="001-0000002-2", ejecutivo="Pedro Diaz")

    # Agente configurado es "Maria Gomez", pero busco la cédula de un caso de Pedro Diaz.
    resultado = buscar_casos(conn, ejecutivo_actual="Maria Gomez", termino="0000002")

    assert len(resultado) == 1
    assert resultado[0][6] == "001-0000002-2"
    assert resultado[0][3] == "Pedro Diaz"


def test_buscar_por_nombre_es_insensible_a_mayusculas(conn):
    _crear_cliente_y_caso(conn, nombre="ARMANDO JAVIER PEÑA ARIAS")

    resultado = buscar_casos(conn, termino="armando")

    assert len(resultado) == 1


def test_buscar_por_nombre_no_tolera_tildes_incorrectas(conn):
    _crear_cliente_y_caso(conn, nombre="ARMANDO JAVIER PEÑA ARIAS")

    # "pena" sin tilde no debe encontrar "PEÑA".
    resultado = buscar_casos(conn, termino="pena")

    assert resultado == []


def test_buscar_termino_invalido_propaga_error(conn):
    _crear_cliente_y_caso(conn)

    with pytest.raises(ValueError):
        buscar_casos(conn, termino="armando@")


def test_obtener_ejecutivos_sin_duplicados(conn):
    _crear_cliente_y_caso(conn, cedula="001-0000001-1", ejecutivo="Maria Gomez")
    _crear_cliente_y_caso(conn, cedula="001-0000002-2", ejecutivo="Maria Gomez")

    assert obtener_ejecutivos(conn) == ["Maria Gomez"]


def test_edicion_manual_actualiza_estado_y_etapa(conn):
    caso_id = _crear_cliente_y_caso(conn)

    actualizar_edicion_manual(conn, caso_id, "Aprobado", "Desembolso")

    fila = conn.execute(
        "SELECT estado_solicitud, etapa_proceso, origen_ultima_modificacion FROM caso WHERE id = ?",
        (caso_id,),
    ).fetchone()

    assert fila == ("Aprobado", "Desembolso", "manual")


def test_edicion_manual_no_marca_constancia_recibida(conn):
    caso_id = _crear_cliente_y_caso(conn, estado="En espera de constancia")

    actualizar_edicion_manual(conn, caso_id, "Aprobado", "Desembolso")

    (constancia_recibida,) = conn.execute(
        "SELECT constancia_recibida_fecha FROM caso WHERE id = ?", (caso_id,)
    ).fetchone()

    assert constancia_recibida is None


def test_edicion_manual_resetea_fecha_cambio_solo_si_estado_cambia(conn):
    caso_id = _crear_cliente_y_caso(conn, estado="En espera de constancia")
    fecha_original = conn.execute(
        "SELECT estado_solicitud_fecha_cambio FROM caso WHERE id = ?", (caso_id,)
    ).fetchone()[0]

    actualizar_edicion_manual(conn, caso_id, "En espera de constancia", "Nueva etapa")

    fecha_sin_cambio_estado = conn.execute(
        "SELECT estado_solicitud_fecha_cambio FROM caso WHERE id = ?", (caso_id,)
    ).fetchone()[0]

    assert fecha_sin_cambio_estado == fecha_original
