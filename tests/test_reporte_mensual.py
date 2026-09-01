import pytest

from gestor_credito.db import database
from gestor_credito.db.reporte_mensual import generar_reporte_mensual


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _crear_cliente_y_caso(conn, cedula="001-1234567-8", nombre="Juan Perez",
                           ejecutivo="Maria Gomez", estado="En espera de constancia",
                           fecha_registro="2026-08-01", estado_solicitud_fecha_cambio=None,
                           microseguro=None, motivo_no_aplica=None, empresa_convenio="MIDESA",
                           no_presolicitud=None):
    cliente = conn.execute("SELECT id FROM cliente WHERE cedula = ?", (cedula,)).fetchone()
    if cliente is None:
        cur = conn.execute(
            "INSERT INTO cliente (cedula, nombre, telefono) VALUES (?, ?, ?)",
            (cedula, nombre, "8091234567"),
        )
        cliente_id = cur.lastrowid
    else:
        cliente_id = cliente[0]

    clave = no_presolicitud or f"P-{cliente_id}-{fecha_registro}"
    columnas = [
        "cliente_id", "no_presolicitud", "clave_caso", "ejecutivo", "empresa_convenio",
        "estado_solicitud", "fecha_registro", "microseguro", "motivo_no_aplica",
    ]
    valores = [
        cliente_id, clave, clave, ejecutivo, empresa_convenio,
        estado, fecha_registro, microseguro, motivo_no_aplica,
    ]
    if estado_solicitud_fecha_cambio:
        columnas.append("estado_solicitud_fecha_cambio")
        valores.append(estado_solicitud_fecha_cambio)

    placeholders = ", ".join("?" for _ in columnas)
    cur = conn.execute(
        f"INSERT INTO caso ({', '.join(columnas)}) VALUES ({placeholders})", valores,
    )
    conn.commit()
    return cur.lastrowid


def _crear_credito(conn, no_credito, cedula, fecha_desembolso, nombre="Juan Perez"):
    conn.execute(
        "INSERT INTO reporte_credito (no_credito, cedula, nombre_cliente, fecha_desembolso, "
        "estado_credito) VALUES (?, ?, ?, ?, 'Corriente')",
        (no_credito, cedula, nombre, fecha_desembolso),
    )
    conn.commit()


# --- La regla de Juan: nunca emparejar con un crédito anterior al caso -----

def test_credito_anterior_a_la_fecha_de_registro_no_se_empareja(conn):
    # Ejemplo exacto confirmado con el usuario: presolicitud de agosto, un
    # crédito de enero de la misma cédula NO puede ser el de este caso.
    _crear_cliente_y_caso(conn, cedula="001", fecha_registro="2026-08-01")
    _crear_credito(conn, "C-1", "001", "2026-01-15")

    resultado = generar_reporte_mensual(conn, 2026, 1)
    assert resultado["desembolsados"] == []
    # Sin un crédito posterior a agosto todavía, el caso sigue pendiente.
    assert len(resultado["pendientes"]) == 1


def test_credito_posterior_se_empareja_y_cuenta_en_su_mes_real(conn):
    _crear_cliente_y_caso(conn, cedula="001", fecha_registro="2026-08-01")
    _crear_credito(conn, "C-1", "001", "2026-01-15")  # anterior, se ignora
    _crear_credito(conn, "C-2", "001", "2026-09-10")  # posterior, este es el bueno

    resultado_agosto = generar_reporte_mensual(conn, 2026, 8)
    assert resultado_agosto["desembolsados"] == []
    assert resultado_agosto["pendientes"] == []  # ya tiene crédito emparejado, no está "sin resolver"

    resultado_septiembre = generar_reporte_mensual(conn, 2026, 9)
    assert len(resultado_septiembre["desembolsados"]) == 1
    assert resultado_septiembre["desembolsados"][0]["fecha"] == "2026-09-10"


def test_credito_mas_cercano_se_prioriza_sobre_uno_mas_lejano(conn):
    _crear_cliente_y_caso(conn, cedula="001", fecha_registro="2026-08-01")
    _crear_credito(conn, "C-1", "001", "2026-11-01")
    _crear_credito(conn, "C-2", "001", "2026-09-05")  # el más próximo a fecha_registro

    resultado = generar_reporte_mensual(conn, 2026, 9)
    assert len(resultado["desembolsados"]) == 1
    assert resultado["desembolsados"][0]["fecha"] == "2026-09-05"


def test_dos_casos_del_mismo_cliente_no_comparten_el_mismo_credito(conn):
    _crear_cliente_y_caso(
        conn, cedula="001", fecha_registro="2026-06-01", no_presolicitud="P-1",
    )
    _crear_cliente_y_caso(
        conn, cedula="001", fecha_registro="2026-08-01", no_presolicitud="P-2",
    )
    _crear_credito(conn, "C-1", "001", "2026-07-01")  # corresponde al caso de junio
    _crear_credito(conn, "C-2", "001", "2026-09-01")  # corresponde al caso de agosto

    resultado_julio = generar_reporte_mensual(conn, 2026, 7)
    resultado_septiembre = generar_reporte_mensual(conn, 2026, 9)

    assert len(resultado_julio["desembolsados"]) == 1
    assert resultado_julio["desembolsados"][0]["clave_caso"] == "P-1"
    assert len(resultado_septiembre["desembolsados"]) == 1
    assert resultado_septiembre["desembolsados"][0]["clave_caso"] == "P-2"


# --- Historial de Créditos manda sobre estado_solicitud manual -------------

def test_historial_manda_aunque_casos_diga_otro_estado(conn):
    # El caso sigue diciendo "Pendiente de información" en Casos (nadie lo
    # actualizó a mano todavía), pero Historial de Créditos ya muestra el
    # crédito real desembolsado — pedido explícito del usuario: esta fuente
    # manda, no lo que diga Casos.
    _crear_cliente_y_caso(
        conn, cedula="001", fecha_registro="2026-08-01",
        estado="Pendiente de información",
    )
    _crear_credito(conn, "C-1", "001", "2026-08-20")

    resultado = generar_reporte_mensual(conn, 2026, 8)
    assert len(resultado["desembolsados"]) == 1
    assert resultado["pendientes"] == []


# --- Sin crédito emparejado: se usa estado_solicitud tal cual ---------------

def test_sin_credito_desembolsada_manual_usa_fecha_de_cambio_de_estado(conn):
    _crear_cliente_y_caso(
        conn, cedula="001", estado="Desembolsada",
        estado_solicitud_fecha_cambio="2026-08-15 10:00:00",
    )
    resultado = generar_reporte_mensual(conn, 2026, 8)
    assert len(resultado["desembolsados"]) == 1
    assert resultado["pendientes"] == []


def test_no_aplica_incluye_motivo_y_filtra_por_mes(conn):
    _crear_cliente_y_caso(
        conn, cedula="001", estado="No aplica", motivo_no_aplica="Ingresos insuficientes",
        estado_solicitud_fecha_cambio="2026-08-05 09:00:00",
    )
    resultado_agosto = generar_reporte_mensual(conn, 2026, 8)
    resultado_julio = generar_reporte_mensual(conn, 2026, 7)

    assert len(resultado_agosto["no_aplica"]) == 1
    assert resultado_agosto["no_aplica"][0]["motivo_no_aplica"] == "Ingresos insuficientes"
    assert resultado_julio["no_aplica"] == []


def test_cliente_desistio_filtra_por_mes(conn):
    _crear_cliente_y_caso(
        conn, cedula="001", estado="Cliente desistió",
        estado_solicitud_fecha_cambio="2026-08-05 09:00:00",
    )
    resultado = generar_reporte_mensual(conn, 2026, 8)
    assert len(resultado["cliente_desistio"]) == 1


def test_pendiente_no_se_filtra_por_mes(conn):
    _crear_cliente_y_caso(
        conn, cedula="001", estado="En proceso",
        estado_solicitud_fecha_cambio="2026-06-01 09:00:00",
    )
    # Sin importar qué mes se consulte, un caso genuinamente abierto siempre
    # aparece en Pendientes — pedido explícito del usuario, para que nada se
    # pierda de vista entre un mes y el siguiente.
    for mes in (6, 7, 8, 9):
        resultado = generar_reporte_mensual(conn, 2026, mes)
        assert len(resultado["pendientes"]) == 1


# --- Microseguro -------------------------------------------------------

def test_desglose_de_microseguro_en_desembolsados(conn):
    _crear_cliente_y_caso(
        conn, cedula="001", nombre="Con Seguro", estado="Desembolsada",
        microseguro="S", estado_solicitud_fecha_cambio="2026-08-05 09:00:00",
    )
    _crear_cliente_y_caso(
        conn, cedula="002", nombre="Sin Seguro", estado="Desembolsada",
        microseguro="N", estado_solicitud_fecha_cambio="2026-08-06 09:00:00",
    )
    resultado = generar_reporte_mensual(conn, 2026, 8)
    assert len(resultado["desembolsados"]) == 2
    assert resultado["con_microseguro"] == 1
    assert resultado["sin_microseguro"] == 1


# --- Un caso cerrado negativo (No aplica/Cliente desistió) nunca le roba el
# --- crédito de Historial a otro caso del mismo cliente ---------------------

def test_cliente_desistio_no_le_roba_el_credito_a_otro_caso_del_mismo_cliente(conn):
    # Bug real reportado por el usuario (2026-08-31, cliente real "Harry
    # Tinoco Benly"): un caso viejo marcado "Cliente desistió" (con motivo)
    # y fecha_registro más temprana que un caso nuevo "En proceso" del MISMO
    # cliente — antes del fix, el caso desistido se quedaba con el único
    # crédito disponible de Historial (por ser el más antiguo) y aparecía
    # como "Desembolsado" con el motivo de desistimiento pegado, mientras el
    # caso realmente pendiente se quedaba sin su crédito real.
    _crear_cliente_y_caso(
        conn, cedula="001", no_presolicitud="P-VIEJO", fecha_registro="2026-06-01",
        estado="Cliente desistió", motivo_no_aplica="No le gustó el monto ofrecido",
        estado_solicitud_fecha_cambio="2026-08-05 09:00:00",
    )
    _crear_cliente_y_caso(
        conn, cedula="001", no_presolicitud="P-NUEVO", fecha_registro="2026-07-01",
        estado="En proceso",
    )
    _crear_credito(conn, "C-1", "001", "2026-08-28")

    resultado = generar_reporte_mensual(conn, 2026, 8)

    # El caso desistido sigue clasificado como Cliente desistió — nunca
    # entra a competir por créditos.
    assert len(resultado["cliente_desistio"]) == 1
    assert resultado["cliente_desistio"][0]["clave_caso"] == "P-VIEJO"

    # El caso realmente pendiente es el que se queda con el crédito real.
    assert len(resultado["desembolsados"]) == 1
    entrada = resultado["desembolsados"][0]
    assert entrada["clave_caso"] == "P-NUEVO"
    assert entrada["fecha"] == "2026-08-28"
    assert entrada["motivo_no_aplica"] is None


def test_no_aplica_tampoco_le_roba_el_credito(conn):
    _crear_cliente_y_caso(
        conn, cedula="001", no_presolicitud="P-VIEJO", fecha_registro="2026-06-01",
        estado="No aplica", motivo_no_aplica="Ingresos insuficientes",
        estado_solicitud_fecha_cambio="2026-08-05 09:00:00",
    )
    _crear_cliente_y_caso(
        conn, cedula="001", no_presolicitud="P-NUEVO", fecha_registro="2026-07-01",
        estado="En proceso",
    )
    _crear_credito(conn, "C-1", "001", "2026-08-28")

    resultado = generar_reporte_mensual(conn, 2026, 8)

    assert len(resultado["no_aplica"]) == 1
    assert len(resultado["desembolsados"]) == 1
    assert resultado["desembolsados"][0]["clave_caso"] == "P-NUEVO"


# --- Total de casos registrados en el mes -----------------------------------

def test_total_registrados_cuenta_por_fecha_de_registro_sin_importar_estado(conn):
    _crear_cliente_y_caso(conn, cedula="001", fecha_registro="2026-08-01", estado="En proceso")
    _crear_cliente_y_caso(
        conn, cedula="002", fecha_registro="2026-08-15", estado="Desembolsada",
        estado_solicitud_fecha_cambio="2026-08-20 09:00:00",
    )
    _crear_cliente_y_caso(conn, cedula="003", fecha_registro="2026-07-31", estado="En proceso")

    resultado = generar_reporte_mensual(conn, 2026, 8)
    assert resultado["total_registrados"] == 2


# --- Filtro por ejecutivo ------------------------------------------------

def test_filtra_por_ejecutivo(conn):
    _crear_cliente_y_caso(conn, cedula="001", ejecutivo="Maria Gomez", estado="En proceso")
    _crear_cliente_y_caso(conn, cedula="002", ejecutivo="Pedro Lopez", estado="En proceso")

    resultado = generar_reporte_mensual(conn, 2026, 8, ejecutivo="Maria Gomez")
    assert len(resultado["pendientes"]) == 1
    assert resultado["pendientes"][0]["cedula"] == "001"
