import pytest

from gestor_credito.db import database
from gestor_credito.db.casos import (
    FILTRO_ALERTA_CONSTANCIA_EN_MANO,
    FILTRO_ALERTA_CONSTANCIA_PENDIENTE,
    FILTRO_ALERTA_DOCUMENTOS_PENDIENTES,
    FILTRO_ALERTA_TODOS,
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


def test_edicion_manual_a_desembolsada_completa_documentos_del_cliente(conn):
    # Reporte real del usuario (2026-07-11): un caso que llega a Desembolsada
    # evidentemente tuvo sus documentos completos para llegar hasta ahí, pero
    # nada lo marcaba así — quedaba pendiente para siempre.
    caso_id = _crear_cliente_y_caso(conn, estado="En proceso")

    actualizar_edicion_manual(conn, caso_id, "Desembolsada", "Desembolso")

    (documentos_completos_fecha,) = conn.execute(
        "SELECT cliente.documentos_completos_fecha FROM cliente "
        "JOIN caso ON caso.cliente_id = cliente.id WHERE caso.id = ?",
        (caso_id,),
    ).fetchone()

    assert documentos_completos_fecha is not None


def test_edicion_manual_a_desembolsada_no_pisa_fecha_ya_marcada(conn):
    caso_id = _crear_cliente_y_caso(conn, estado="En proceso")
    conn.execute(
        "UPDATE cliente SET documentos_completos_fecha = '2026-01-01 00:00:00' "
        "WHERE id = (SELECT cliente_id FROM caso WHERE id = ?)",
        (caso_id,),
    )
    conn.commit()

    actualizar_edicion_manual(conn, caso_id, "Desembolsada", "Desembolso")

    (documentos_completos_fecha,) = conn.execute(
        "SELECT cliente.documentos_completos_fecha FROM cliente "
        "JOIN caso ON caso.cliente_id = cliente.id WHERE caso.id = ?",
        (caso_id,),
    ).fetchone()

    assert documentos_completos_fecha == "2026-01-01 00:00:00"


# --- filtro_alerta de buscar_casos -------------------------------------------
# A diferencia de las alertas de Notificaciones (gestor_credito/db/alertas.py),
# este filtro es de ESTADO actual, sin umbral de tiempo — un caso recién
# importado ya debe aparecer, sin esperar 7 días/24h/48h (ver comentario junto
# a FILTRO_ALERTA_TODOS en casos.py).

def test_filtro_documentos_pendientes_muestra_estado_actual_sin_umbral(conn):
    caso_pendiente = _crear_cliente_y_caso(conn, cedula="001-0000001-1", no_presolicitud="P-1")
    caso_completo = _crear_cliente_y_caso(conn, cedula="001-0000002-2", no_presolicitud="P-2")
    conn.execute(
        "UPDATE cliente SET documentos_completos_fecha = datetime('now') WHERE id = "
        "(SELECT cliente_id FROM caso WHERE id = ?)",
        (caso_completo,),
    )
    conn.commit()

    resultado = buscar_casos(conn, filtro_alerta=FILTRO_ALERTA_DOCUMENTOS_PENDIENTES)

    assert [f[0] for f in resultado] == [caso_pendiente]


def test_filtro_constancia_pendiente_muestra_estado_actual_sin_umbral(conn):
    caso_en_espera = _crear_cliente_y_caso(
        conn, cedula="001-0000001-1", no_presolicitud="P-1", estado="En espera de constancia"
    )
    _crear_cliente_y_caso(
        conn, cedula="001-0000002-2", no_presolicitud="P-2", estado="En proceso"
    )

    resultado = buscar_casos(conn, filtro_alerta=FILTRO_ALERTA_CONSTANCIA_PENDIENTE)

    assert [f[0] for f in resultado] == [caso_en_espera]


def test_filtro_constancia_en_mano_muestra_estado_actual_sin_umbral(conn):
    """Se basa directamente en estado_solicitud == "En proceso", sin importar
    constancia_recibida_fecha (bug real reportado por el usuario: un caso
    importado directo en "En proceso", sin que el importador viera nunca la
    transición, antes no aparecía en este filtro aunque debiera)."""
    caso_en_mano_detectado = _crear_cliente_y_caso(
        conn, cedula="001-0000001-1", no_presolicitud="P-1", estado="En proceso"
    )
    conn.execute(
        "UPDATE caso SET constancia_recibida_fecha = datetime('now') WHERE id = ?",
        (caso_en_mano_detectado,),
    )
    caso_en_mano_sin_transicion_vista = _crear_cliente_y_caso(
        conn, cedula="001-0000002-2", no_presolicitud="P-2", estado="En proceso"
    )
    caso_desembolsado = _crear_cliente_y_caso(
        conn, cedula="001-0000003-3", no_presolicitud="P-3", estado="Desembolsada"
    )
    conn.execute(
        "UPDATE caso SET constancia_recibida_fecha = datetime('now') WHERE id = ?",
        (caso_desembolsado,),
    )
    conn.commit()

    resultado = buscar_casos(conn, filtro_alerta=FILTRO_ALERTA_CONSTANCIA_EN_MANO)

    ids_resultado = [f[0] for f in resultado]
    assert set(ids_resultado) == {caso_en_mano_detectado, caso_en_mano_sin_transicion_vista}
    assert caso_desembolsado not in ids_resultado


@pytest.mark.parametrize(
    "filtro_alerta",
    [
        FILTRO_ALERTA_DOCUMENTOS_PENDIENTES,
        FILTRO_ALERTA_CONSTANCIA_PENDIENTE,
        FILTRO_ALERTA_CONSTANCIA_EN_MANO,
    ],
)
@pytest.mark.parametrize("estado_cerrado", ["Desembolsada", "No aplica", "Cliente desistió"])
def test_filtro_excluye_casos_en_estado_cerrado(conn, filtro_alerta, estado_cerrado):
    # Un caso cerrado no debe aparecer bajo NINGÚN filtro de alerta, aunque
    # técnicamente cumpla la condición de ese filtro (documentos_completos_fecha
    # NULL, constancia_recibida_fecha marcada, etc.) — el caso ya no tiene nada
    # pendiente con el cliente.
    caso_cerrado = _crear_cliente_y_caso(
        conn, cedula="001-0000001-1", no_presolicitud="P-1", estado=estado_cerrado
    )
    conn.execute(
        "UPDATE caso SET constancia_recibida_fecha = datetime('now') WHERE id = ?",
        (caso_cerrado,),
    )
    conn.commit()

    resultado = buscar_casos(conn, filtro_alerta=filtro_alerta)

    assert resultado == []


def test_filtro_todos_no_filtra(conn):
    _crear_cliente_y_caso(conn, cedula="001-0000001-1", no_presolicitud="P-1")
    _crear_cliente_y_caso(conn, cedula="001-0000002-2", no_presolicitud="P-2")

    resultado = buscar_casos(conn, filtro_alerta=FILTRO_ALERTA_TODOS)

    assert len(resultado) == 2


def test_termino_de_busqueda_ignora_filtro_de_alerta(conn):
    # El caso no cumple el filtro de alerta seleccionado (estado "En proceso",
    # no "En espera de constancia"), pero como hay término de búsqueda, el
    # filtro de alerta se ignora igual que ejecutivo_actual.
    _crear_cliente_y_caso(
        conn, cedula="001-0000001-1", nombre="Armando Pena", estado="En proceso"
    )

    resultado = buscar_casos(
        conn, termino="Armando", filtro_alerta=FILTRO_ALERTA_CONSTANCIA_PENDIENTE
    )

    assert len(resultado) == 1


def test_filtro_combina_con_ejecutivo_actual(conn):
    caso_agente_1 = _crear_cliente_y_caso(
        conn, cedula="001-0000001-1", no_presolicitud="P-1", ejecutivo="Maria Gomez"
    )
    _crear_cliente_y_caso(
        conn, cedula="001-0000002-2", no_presolicitud="P-2", ejecutivo="Pedro Diaz"
    )

    resultado = buscar_casos(
        conn, ejecutivo_actual="Maria Gomez", filtro_alerta=FILTRO_ALERTA_DOCUMENTOS_PENDIENTES
    )

    assert [f[0] for f in resultado] == [caso_agente_1]
