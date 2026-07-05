from datetime import datetime

import openpyxl
import pytest

from gestor_credito.db import database
from gestor_credito.importer.excel_importer import import_bitacora

# Encabezados EXACTOS de la plantilla real de MIDESA ("MachoteBaseDeDatos.xlsx",
# hoja 01_Bitacora_Piloto): incluyen un salto de línea interno y un sufijo
# "(Manual)"/"(Auto)" pegado al nombre del campo.
HEADERS_REALES = [
    "ID Caso\n(Auto)",
    "Fecha Registro\n(Manual)",
    "Canal / Origen\n(Manual)",
    "No. PRESOLICITUD",
    "Ejecutivo\n(Manual)",
    "Constancia Solicitada",
    "Empresa Convenio\n(Manual)",
    "Nombre del Cliente\n(Manual)",
    "Identificación\n(Manual)",
    "Teléfono\n(Manual)",
    "Monto Solicitado\n(Manual)",
    "Destino del credito",
    "Microseguro\n(Manual)",
    "Estado Solicitud\n(Manual)",
    "Etapa Proceso\n(Manual)",
    "Responsable Actual\n(Manual)",
    "Fecha Última Gestión\n(Manual)",
    "Próxima Gestión\n(Manual)",
    "Días en Gestión\n(Auto)",
    "Alerta Seguimiento\n(Auto)",
    "¿Requiere registro/acción SIAF?\n(Manual)",
    "Fecha Envío SIAF\n(Manual)",
    "Fecha Decisión\n(Manual)",
    "Decisión\n(Manual)",
    "Motivo No Aplica / Desistimiento\n(Manual)",
    "Observaciones\n(Manual)",
]

HEADERS = [
    "ID Caso", "Fecha Registro", "Canal/Origen", "No. Presolicitud", "Ejecutivo",
    "Constancia Solicitada", "Empresa Convenio", "Nombre del Cliente", "Identificación",
    "Teléfono", "Monto Solicitado", "Destino del Crédito", "Microseguro",
    "Estado Solicitud", "Etapa Proceso", "Responsable Actual", "Fecha Última Gestión",
    "Próxima Gestión", "Días en Gestión", "Alerta Seguimiento",
    "¿Requiere registro/acción SIAF?", "Fecha Envío SIAF", "Fecha Decisión", "Decisión",
    "Motivo No Aplica/Desistimiento", "Observaciones",
]


def _fila(**overrides):
    base = {
        "ID Caso": "C-001",
        "Fecha Registro": "2026-06-20",
        "Canal/Origen": "Web",
        "No. Presolicitud": "P-9001",
        "Ejecutivo": "Maria Gomez",
        "Constancia Solicitada": "2026-06-21",
        "Empresa Convenio": "Acme SRL",
        "Nombre del Cliente": "Juan Perez",
        "Identificación": "001-1234567-8",
        "Teléfono": "8091234567",
        "Monto Solicitado": 50000,
        "Destino del Crédito": "Consumo",
        "Microseguro": "Si",
        "Estado Solicitud": "En espera de constancia",
        "Etapa Proceso": "Verificación",
        "Responsable Actual": "Maria Gomez",
        "Fecha Última Gestión": "2026-06-25",
        "Próxima Gestión": "2026-07-01",
        "Días en Gestión": 5,
        "Alerta Seguimiento": "No",
        "¿Requiere registro/acción SIAF?": "No",
        "Fecha Envío SIAF": None,
        "Fecha Decisión": None,
        "Decisión": None,
        "Motivo No Aplica/Desistimiento": None,
        "Observaciones": "Cliente contactado",
    }
    base.update(overrides)
    return [base[h] for h in HEADERS]


def _escribir_excel(path, filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for fila in filas:
        ws.append(fila)
    wb.save(path)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    return database


def test_importa_caso_nuevo(db, tmp_path):
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila()])

    resumen = import_bitacora(excel_path)

    assert resumen.clientes_nuevos == 1
    assert resumen.casos_nuevos == 1
    assert resumen.casos_actualizados == 0

    conn = db.get_connection()
    cliente = conn.execute("SELECT cedula, nombre FROM cliente").fetchone()
    caso = conn.execute(
        "SELECT clave_caso, estado_solicitud, constancia_recibida_fecha FROM caso"
    ).fetchone()
    conn.close()

    assert cliente == ("001-1234567-8", "Juan Perez")
    assert caso[0] == "P-9001"
    assert caso[1] == "En espera de constancia"
    assert caso[2] is None


def test_reimportar_mismo_caso_no_duplica(db, tmp_path):
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila()])
    import_bitacora(excel_path)

    resumen = import_bitacora(excel_path)

    assert resumen.clientes_nuevos == 0
    assert resumen.casos_nuevos == 0
    assert resumen.casos_actualizados == 1

    conn = db.get_connection()
    total_casos = conn.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
    total_clientes = conn.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    conn.close()

    assert total_casos == 1
    assert total_clientes == 1


def test_cambio_a_en_proceso_marca_constancia_recibida(db, tmp_path):
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila(**{"Estado Solicitud": "En espera de constancia"})])
    import_bitacora(excel_path)

    excel_path_2 = tmp_path / "bitacora_2.xlsx"
    _escribir_excel(excel_path_2, [_fila(**{"Estado Solicitud": "En proceso"})])
    import_bitacora(excel_path_2)

    conn = db.get_connection()
    caso = conn.execute(
        "SELECT estado_solicitud, constancia_recibida_fecha FROM caso"
    ).fetchone()
    conn.close()

    assert caso[0] == "En proceso"
    assert caso[1] is not None


def test_cambio_a_otro_estado_no_marca_constancia_recibida(db, tmp_path):
    # Solo la transición puntual "En espera de constancia" -> "En proceso" marca
    # constancia_recibida_fecha; salir hacia cualquier otro estado no cuenta.
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila(**{"Estado Solicitud": "En espera de constancia"})])
    import_bitacora(excel_path)

    excel_path_2 = tmp_path / "bitacora_2.xlsx"
    _escribir_excel(excel_path_2, [_fila(**{"Estado Solicitud": "No aplica"})])
    import_bitacora(excel_path_2)

    conn = db.get_connection()
    caso = conn.execute(
        "SELECT estado_solicitud, constancia_recibida_fecha FROM caso"
    ).fetchone()
    conn.close()

    assert caso[0] == "No aplica"
    assert caso[1] is None


def test_fila_sin_cedula_se_omite(db, tmp_path):
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila(**{"Identificación": None})])

    resumen = import_bitacora(excel_path)

    assert resumen.clientes_nuevos == 0
    assert resumen.casos_nuevos == 0
    assert len(resumen.filas_omitidas) == 1


def test_importa_con_encabezados_reales_de_midesa(db, tmp_path):
    """Reproduce el archivo real: encabezados con '\\n(Manual)'/'\\n(Auto)' y un
    No. Presolicitud que a veces viene vacío (usa ID Caso) y a veces numérico."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS_REALES)
    ws.append([
        "PIL-0001", datetime(2026, 6, 1), None, None, "FMARTINEZ", 1,
        "CAFE LAS FLORES MOMBACHO", "ARMANDO JAVIER PEÑA ARIAS", "2011307810010Q",
        "84812204", 938.68, "MEJORA DE VIVIENDA", "S", "Desembolsada", "Desembolso",
        "Auxiliar de Negocios", None, None, 33, "Cerrado", None, None, None, None,
        None, "Observacion 1",
    ])
    ws.append([
        "PIL-0002", datetime(2026, 6, 1), None, 2877, "FMARTINEZ", 1,
        "IMMSA", "JOSE LUIS BARQUERO MARTINEZ", "0010609981042P", "58528567",
        878.68, "CONSUMO", "S", "Desembolsada", "Desembolso", "Auxiliar de Negocios",
        None, None, 33, "Cerrado", None, None, None, None, None, None,
    ])
    excel_path = tmp_path / "MachoteBaseDeDatos.xlsx"
    wb.save(excel_path)

    resumen = import_bitacora(excel_path)

    assert resumen.clientes_nuevos == 2
    assert resumen.casos_nuevos == 2
    assert resumen.filas_omitidas == []

    conn = db.get_connection()
    claves = {fila[0] for fila in conn.execute("SELECT clave_caso FROM caso").fetchall()}
    conn.close()

    assert claves == {"PIL-0001", "2877"}


def test_cliente_existente_puede_tener_varios_casos(db, tmp_path):
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila(**{"No. Presolicitud": "P-9001"})])
    import_bitacora(excel_path)

    excel_path_2 = tmp_path / "bitacora_2.xlsx"
    _escribir_excel(excel_path_2, [_fila(**{"No. Presolicitud": "P-9002"})])
    resumen = import_bitacora(excel_path_2)

    assert resumen.clientes_nuevos == 0
    assert resumen.casos_nuevos == 1

    conn = db.get_connection()
    total_casos = conn.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
    conn.close()

    assert total_casos == 2
