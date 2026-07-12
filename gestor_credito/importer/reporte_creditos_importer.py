import re
from datetime import date, datetime

import openpyxl

from gestor_credito.db.database import get_connection

DATE_FIELDS = {"fecha_desembolso", "fecha_vencimiento"}
INT_FIELDS = {"plazo_credito", "cuotas_pagadas"}
FLOAT_FIELDS = {"monto_desembolsado"}

_ESPACIOS_MULTIPLES = re.compile(r"\s+")

# Encabezado del Excel (normalizado) -> columna interna. Los encabezados reales
# de recursos/reporte.xlsx ("REPORTE DE DATOS DE CREDITOS") usan guion bajo
# (p. ej. "NO_IDENTIFICACION"), sin saltos de línea ni sufijos — mucho más
# limpios que la bitácora de MIDESA. _normalize_header() igual convierte "_" a
# espacio antes de buscar acá, para tolerar tanto "NO_CREDITO" como una futura
# variante con espacios ("NO CREDITO"), y se incluyen también las formas con
# preposición que usó el usuario al pedir el módulo ("NOMBRE del CLIENTE",
# "PLAZO del CREDITO") por si un reporte futuro trae esos encabezados en vez
# de los que tiene el archivo real. Los VALORES de las celdas no se tocan,
# solo los encabezados.
COLUMN_ALIASES = {
    "fecha desembolso": "fecha_desembolso",
    "fecha vencimiento": "fecha_vencimiento",
    "no credito": "no_credito",
    "monto desembolsado": "monto_desembolsado",
    "nombre cliente": "nombre_cliente",
    "nombre del cliente": "nombre_cliente",
    "estado credito": "estado_credito",
    "empresa de convenio": "empresa_convenio",
    "empresa convenio": "empresa_convenio",
    "no identificacion": "cedula",
    "plazo credito": "plazo_credito",
    "plazo del credito": "plazo_credito",
    "cuotas pagadas": "cuotas_pagadas",
}

CREDITO_COLUMNS = [
    "cedula", "nombre_cliente", "fecha_desembolso", "fecha_vencimiento",
    "monto_desembolsado", "estado_credito", "empresa_convenio",
    "plazo_credito", "cuotas_pagadas",
]


class ImportResumenCreditos:
    def __init__(self):
        self.creditos_nuevos = 0
        self.creditos_actualizados = 0
        self.filas_omitidas = []

    def __repr__(self):
        return (
            f"ImportResumenCreditos(creditos_nuevos={self.creditos_nuevos}, "
            f"creditos_actualizados={self.creditos_actualizados}, "
            f"filas_omitidas={len(self.filas_omitidas)})"
        )


def import_reporte_creditos(file_path):
    """Lee recursos/reporte.xlsx (o .xls/.xlsm — cualquier archivo que
    openpyxl pueda abrir) y hace upsert de cada fila contra reporte_credito,
    igual que import_bitacora() hace con caso: no_credito es la clave real,
    así que una reimportación periódica actualiza la fila existente en vez de
    duplicarla. Nunca borra filas que ya no aparezcan en un reimport
    posterior — mismo criterio que la bitácora."""
    resumen = ImportResumenCreditos()

    workbook = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    sheet = workbook.active
    headers = _read_headers(sheet)

    faltantes = {"no_credito", "cedula"} - headers.keys()
    if faltantes:
        raise ValueError(
            f"Faltan columnas obligatorias en el Excel: {', '.join(sorted(faltantes))}"
        )

    conn = get_connection()
    try:
        for row_number, row in enumerate(sheet.iter_rows(min_row=2), start=2):
            data = _row_to_dict(row, headers)
            no_credito = (data.get("no_credito") or "").strip()
            cedula = (data.get("cedula") or "").strip()

            if not no_credito or not cedula:
                resumen.filas_omitidas.append((row_number, "falta No. Crédito o Cédula"))
                continue

            nuevo = _upsert_credito(conn, no_credito, data)
            if nuevo:
                resumen.creditos_nuevos += 1
            else:
                resumen.creditos_actualizados += 1

        conn.commit()
    finally:
        conn.close()

    return resumen


def _read_headers(sheet):
    headers = {}
    primera_fila = next(sheet.iter_rows(min_row=1, max_row=1))
    for col_index, cell in enumerate(primera_fila):
        field = COLUMN_ALIASES.get(_normalize_header(cell.value))
        if field:
            headers[field] = col_index
    return headers


def _normalize_header(value):
    text = str(value or "").replace("_", " ").replace("\n", " ").replace("\r", " ")
    text = _ESPACIOS_MULTIPLES.sub(" ", text)
    return text.strip().lower()


def _row_to_dict(row, headers):
    data = {}
    for field, col_index in headers.items():
        value = row[col_index].value if col_index < len(row) else None

        if field in DATE_FIELDS:
            value = _normalize_date(value)
        elif field in INT_FIELDS:
            value = _to_int(value)
        elif field in FLOAT_FIELDS:
            value = _to_float(value)
        elif value is not None:
            # Todo lo demás se guarda como texto, incluso si Excel entregó un
            # número (mismo motivo que en excel_importer.py: NO_CREDITO/
            # NO_IDENTIFICACION podrían venir como número en algún reporte).
            value = str(value).strip()

        data[field] = value
    return data


def _normalize_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _to_int(value):
    if value in (None, ""):
        return None
    return int(value)


def _to_float(value):
    if value in (None, ""):
        return None
    return float(value)


def _upsert_credito(conn, no_credito, data):
    existing = conn.execute(
        "SELECT id FROM reporte_credito WHERE no_credito = ?", (no_credito,)
    ).fetchone()

    valores = {column: data.get(column) for column in CREDITO_COLUMNS}

    if existing is None:
        columnas = ["no_credito", *CREDITO_COLUMNS]
        placeholders = ", ".join("?" for _ in columnas)
        params = [no_credito, *valores.values()]
        conn.execute(
            f"INSERT INTO reporte_credito ({', '.join(columnas)}) VALUES ({placeholders})",
            params,
        )
        return True

    credito_id = existing[0]
    set_sql = [f"{column} = ?" for column in CREDITO_COLUMNS]
    set_sql.append("fecha_actualizacion_registro = datetime('now')")
    params = [*valores.values(), credito_id]
    conn.execute(f"UPDATE reporte_credito SET {', '.join(set_sql)} WHERE id = ?", params)
    return False
