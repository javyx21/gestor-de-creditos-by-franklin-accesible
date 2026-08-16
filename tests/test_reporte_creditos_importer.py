from datetime import datetime

import openpyxl
import pytest

from gestor_credito.db import database
from gestor_credito.importer.reporte_creditos_importer import import_reporte_creditos

# Encabezados EXACTOS del reporte real (recursos/reporte.xlsx, hoja "REPORTE
# DE DATOS DE CREDITOS") — limpios, con guion bajo, sin saltos de línea ni
# sufijos (a diferencia de la bitácora de MIDESA). Se incluyen columnas de
# más (NO_CLIENTE_SIAF, PRODUCTO_CREDITO, etc.) que el reporte real trae pero
# que este módulo no mapea — deben ignorarse sin romper el import.
HEADERS = [
    "FECHA_DESEMBOLSO", "FECHA_VENCIMIENTO", "NO_CREDITO", "NO_CLIENTE_SIAF",
    "NOMBRE_CLIENTE", "ESTADO_CREDITO", "PRODUCTO_CREDITO", "SALDO_PRINCIPAL",
    "MONTO_DESEMBOLSADO", "EMPRESA_DE_CONVENIO", "NO_IDENTIFICACION",
    "MONTO_GARANTIA", "PLAZO_CREDITO", "NUMERO_CUOTAS", "CUOTAS_PAGADAS",
]


def _fila(**overrides):
    base = {
        "FECHA_DESEMBOLSO": datetime(2025, 6, 30),
        "FECHA_VENCIMIENTO": datetime(2027, 5, 30),
        "NO_CREDITO": "001985",
        "NO_CLIENTE_SIAF": "6294",
        "NOMBRE_CLIENTE": "KARLA VANESSA CORTEZ SELVA",
        "ESTADO_CREDITO": "Corriente",
        "PRODUCTO_CREDITO": "CREDINOMINA",
        "SALDO_PRINCIPAL": 1132.2337,
        "MONTO_DESEMBOLSADO": 2007.0443,
        "EMPRESA_DE_CONVENIO": "AGROSACO",
        "NO_IDENTIFICACION": "0012510940057N",
        "MONTO_GARANTIA": 976.88,
        "PLAZO_CREDITO": 23,
        "NUMERO_CUOTAS": 46,
        "CUOTAS_PAGADAS": 24,
    }
    base.update(overrides)
    return [base[h] for h in HEADERS]


def _escribir_excel(path, filas, headers=HEADERS):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for fila in filas:
        ws.append(fila)
    wb.save(path)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    return database


def test_importa_credito_nuevo(db, tmp_path):
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila()])

    resumen = import_reporte_creditos(excel_path)

    assert resumen.creditos_nuevos == 1
    assert resumen.creditos_actualizados == 0
    assert resumen.filas_omitidas == []

    conn = db.get_connection()
    try:
        fila = conn.execute(
            "SELECT no_credito, cedula, nombre_cliente, fecha_desembolso, fecha_vencimiento, "
            "monto_desembolsado, estado_credito, empresa_convenio, plazo_credito, numero_cuotas, "
            "cuotas_pagadas FROM reporte_credito"
        ).fetchone()
    finally:
        conn.close()

    assert fila == (
        "001985", "0012510940057N", "KARLA VANESSA CORTEZ SELVA", "2025-06-30", "2027-05-30",
        2007.0443, "Corriente", "AGROSACO", 23, 46, 24,
    )


def test_reimportar_mismo_credito_actualiza_no_duplica(db, tmp_path):
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila(ESTADO_CREDITO="Corriente")])
    import_reporte_creditos(excel_path)

    _escribir_excel(excel_path, [_fila(ESTADO_CREDITO="Cancelado", CUOTAS_PAGADAS=46)])
    resumen = import_reporte_creditos(excel_path)

    assert resumen.creditos_nuevos == 0
    assert resumen.creditos_actualizados == 1

    conn = db.get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM reporte_credito").fetchone()[0]
        estado, cuotas = conn.execute(
            "SELECT estado_credito, cuotas_pagadas FROM reporte_credito WHERE no_credito = '001985'"
        ).fetchone()
    finally:
        conn.close()

    assert total == 1
    assert estado == "Cancelado"
    assert cuotas == 46


def test_fila_sin_no_credito_o_cedula_se_omite(db, tmp_path):
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [
        _fila(NO_CREDITO=""),
        _fila(NO_CREDITO="002", NO_IDENTIFICACION=""),
        _fila(NO_CREDITO="003"),
    ])

    resumen = import_reporte_creditos(excel_path)

    assert resumen.creditos_nuevos == 1
    assert len(resumen.filas_omitidas) == 2


def test_no_credito_como_numero_se_guarda_como_texto(db, tmp_path):
    """Mismo tipo de defensa que No. Presolicitud en excel_importer.py:
    NO_CREDITO puede venir como número crudo de Excel en vez de texto."""
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila(NO_CREDITO=1985)])

    import_reporte_creditos(excel_path)

    conn = db.get_connection()
    try:
        no_credito = conn.execute("SELECT no_credito FROM reporte_credito").fetchone()[0]
    finally:
        conn.close()

    assert no_credito == "1985"


def test_columnas_no_mapeadas_del_reporte_real_se_ignoran(db, tmp_path):
    """SALDO_PRINCIPAL, MONTO_GARANTIA, PRODUCTO_CREDITO y NO_CLIENTE_SIAF
    existen en el Excel real pero no forman parte del mapeo pedido — deben
    ignorarse sin romper nada. NUMERO_CUOTAS sí se mapea (ver
    test_numero_cuotas_se_importa)."""
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila()])

    resumen = import_reporte_creditos(excel_path)
    assert resumen.creditos_nuevos == 1


def test_falta_columna_obligatoria_lanza_error(db, tmp_path):
    excel_path = tmp_path / "reporte.xlsx"
    headers_sin_cedula = [h for h in HEADERS if h != "NO_IDENTIFICACION"]
    _escribir_excel(excel_path, [
        [v for h, v in zip(HEADERS, _fila()) if h != "NO_IDENTIFICACION"]
    ], headers=headers_sin_cedula)

    with pytest.raises(ValueError):
        import_reporte_creditos(excel_path)


def test_fila_sin_nombre_cliente_se_omite(db, tmp_path):
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila(NOMBRE_CLIENTE="")])

    resumen = import_reporte_creditos(excel_path)

    assert resumen.creditos_nuevos == 0
    assert len(resumen.filas_omitidas) == 1


def test_reimportar_con_no_credito_sin_ceros_actualiza_no_duplica(db, tmp_path):
    """Reporte real del usuario (2026-08-16): un reimport puede traer
    NO_CREDITO con un formato numérico distinto al ya guardado (p. ej. si
    Excel entregó la celda como número en vez de texto), y antes esto creaba
    un crédito duplicado en vez de actualizar el existente."""
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila(NO_CREDITO="001985", ESTADO_CREDITO="Corriente")])
    import_reporte_creditos(excel_path)

    _escribir_excel(excel_path, [_fila(NO_CREDITO="1985", ESTADO_CREDITO="Cancelado")])
    resumen = import_reporte_creditos(excel_path)

    assert resumen.creditos_nuevos == 0
    assert resumen.creditos_actualizados == 1

    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT no_credito, estado_credito FROM reporte_credito").fetchall()
    finally:
        conn.close()

    # Se mantiene un solo crédito, con el no_credito original ("001985", con
    # ceros) intacto — la reimportación solo actualiza los demás campos.
    assert filas == [("001985", "Cancelado")]


def test_fila_con_dato_invalido_no_pierde_las_demas_filas_del_lote(db, tmp_path):
    """Reporte real del usuario (2026-08-16): antes, una excepción sin
    capturar en una sola fila (p. ej. texto no numérico en PLAZO_CREDITO)
    revertía TODA la importación al propagarse hasta afuera del bucle, ya
    que conn.commit() solo ocurre una vez al final."""
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [
        _fila(NO_CREDITO="001"),
        _fila(NO_CREDITO="002", PLAZO_CREDITO="no aplica"),
        _fila(NO_CREDITO="003"),
    ])

    resumen = import_reporte_creditos(excel_path)

    assert resumen.creditos_nuevos == 2
    assert len(resumen.filas_omitidas) == 1
    assert resumen.filas_omitidas[0][0] == 3  # fila 2 de datos = fila 3 del Excel

    conn = db.get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM reporte_credito").fetchone()[0]
    finally:
        conn.close()

    assert total == 2


def test_numero_cuotas_se_importa(db, tmp_path):
    """Agregado 2026-08-16 junto con el filtro de cuotas pendientes de
    Historial de Créditos: antes NUMERO_CUOTAS se ignoraba, sin esa columna
    no hay forma de calcular cuántas cuotas le faltan a un cliente."""
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila(NUMERO_CUOTAS=46)])

    import_reporte_creditos(excel_path)

    conn = db.get_connection()
    try:
        numero_cuotas = conn.execute("SELECT numero_cuotas FROM reporte_credito").fetchone()[0]
    finally:
        conn.close()

    assert numero_cuotas == 46


def test_estado_credito_fecha_cambio_se_estampa_al_insertar(db, tmp_path):
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila()])
    import_reporte_creditos(excel_path)

    conn = db.get_connection()
    try:
        fecha = conn.execute(
            "SELECT estado_credito_fecha_cambio FROM reporte_credito"
        ).fetchone()[0]
    finally:
        conn.close()

    assert fecha is not None


def test_estado_credito_fecha_cambio_no_se_toca_si_el_estado_no_cambia(db, tmp_path):
    """Mismo patrón que estado_solicitud_fecha_cambio en caso
    (excel_importer.py): un reimport que no cambia estado_credito no debe
    pisar la fecha, o la vista "Finalizados" ordenaría mal por "más
    recientemente reimportado" en vez de "más recientemente pagado"."""
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila(ESTADO_CREDITO="Cancelado")])
    import_reporte_creditos(excel_path)

    conn = db.get_connection()
    try:
        fecha_original = conn.execute(
            "SELECT estado_credito_fecha_cambio FROM reporte_credito"
        ).fetchone()[0]
    finally:
        conn.close()

    # Reimport con el mismo estado, pero otro dato cambiado (monto): no debe
    # tocar estado_credito_fecha_cambio.
    _escribir_excel(excel_path, [_fila(ESTADO_CREDITO="Cancelado", MONTO_DESEMBOLSADO=999.0)])
    import_reporte_creditos(excel_path)

    conn = db.get_connection()
    try:
        fecha_tras_reimport = conn.execute(
            "SELECT estado_credito_fecha_cambio FROM reporte_credito"
        ).fetchone()[0]
    finally:
        conn.close()

    assert fecha_tras_reimport == fecha_original


def test_estado_credito_fecha_cambio_se_actualiza_si_el_estado_cambia(db, tmp_path):
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila(ESTADO_CREDITO="Corriente")])
    import_reporte_creditos(excel_path)

    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE reporte_credito SET estado_credito_fecha_cambio = '2000-01-01 00:00:00'"
        )
        conn.commit()
    finally:
        conn.close()

    _escribir_excel(excel_path, [_fila(ESTADO_CREDITO="Cancelado")])
    import_reporte_creditos(excel_path)

    conn = db.get_connection()
    try:
        fecha = conn.execute(
            "SELECT estado_credito_fecha_cambio FROM reporte_credito"
        ).fetchone()[0]
    finally:
        conn.close()

    assert fecha != "2000-01-01 00:00:00"


def test_encabezados_con_espacio_en_vez_de_guion_bajo_tambien_matchean(db, tmp_path):
    """_normalize_header() convierte "_" a espacio antes de buscar el alias,
    así que encabezados con espacio en vez de guion bajo (o las variantes con
    preposición que usó el usuario al pedir el módulo, "NOMBRE del CLIENTE",
    "PLAZO del CREDITO") también deben reconocerse."""
    headers_alternativos = [
        "FECHA_DESEMBOLSO", "FECHA_VENCIMIENTO", "NO_CREDITO", "NO_CLIENTE_SIAF",
        "NOMBRE del CLIENTE", "ESTADO_CREDITO", "PRODUCTO_CREDITO", "SALDO_PRINCIPAL",
        "MONTO_DESEMBOLSADO", "EMPRESA_DE_CONVENIO", "NO_IDENTIFICACION",
        "MONTO_GARANTIA", "PLAZO del CREDITO", "NUMERO_CUOTAS", "CUOTAS_PAGADAS",
    ]
    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel(excel_path, [_fila()], headers=headers_alternativos)

    resumen = import_reporte_creditos(excel_path)
    assert resumen.creditos_nuevos == 1
