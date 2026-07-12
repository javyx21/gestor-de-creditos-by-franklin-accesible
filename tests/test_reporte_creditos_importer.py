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
            "monto_desembolsado, estado_credito, empresa_convenio, plazo_credito, cuotas_pagadas "
            "FROM reporte_credito"
        ).fetchone()
    finally:
        conn.close()

    assert fila == (
        "001985", "0012510940057N", "KARLA VANESSA CORTEZ SELVA", "2025-06-30", "2027-05-30",
        2007.0443, "Corriente", "AGROSACO", 23, 24,
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
    """SALDO_PRINCIPAL, MONTO_GARANTIA, NUMERO_CUOTAS, PRODUCTO_CREDITO y
    NO_CLIENTE_SIAF existen en el Excel real pero no forman parte del mapeo
    pedido (ver sección 1 del pedido) — deben ignorarse sin romper nada."""
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
