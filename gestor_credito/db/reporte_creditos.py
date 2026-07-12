from gestor_credito.db.casos import clasificar_termino_busqueda

# Confirmado con el usuario (2026-07-12): el Excel real no trae un estado
# literal "Activo" — los valores reales de ESTADO_CREDITO son Corriente,
# Cancelado, Saneado, Vencido y Trámite. "Corriente" es el que corresponde a
# "Activo" en la vista por defecto (crédito al día, pagándose con normalidad).
ESTADO_CREDITO_ACTIVO = "Corriente"

# Índices de columna dentro de las tuplas que devuelve buscar_creditos() (ver
# _SELECT_BASE más abajo).
_INDICE_CEDULA = 2
_INDICE_NOMBRE = 3

_SELECT_BASE = """
    SELECT id, no_credito, cedula, nombre_cliente, fecha_desembolso, fecha_vencimiento,
           monto_desembolsado, estado_credito, empresa_convenio, plazo_credito, cuotas_pagadas
    FROM reporte_credito
"""


def buscar_creditos(conn, termino=None):
    """Consulta del módulo Historial de Créditos.

    Sin término: vista por defecto, solo créditos en estado
    ESTADO_CREDITO_ACTIVO ("Corriente").

    Con término: busca por cédula (si trae algún dígito) o por nombre (si es
    solo letras) — misma clasificación que buscar_casos() en db/casos.py — e
    ignora el filtro de estado por defecto, mostrando TODO el historial del
    cliente (cualquier estado), para poder consultar un crédito ya
    Cancelado/Saneado/Vencido, no solo los activos. Ambas comparaciones
    (cédula y nombre) son insensibles a mayúsculas y se hacen en Python con
    str.upper(), no con el UPPER() de SQLite — mismo motivo/mismo fix que
    buscar_casos() (reporte real del usuario, 2026-07-12): una cédula
    guardada en mayúsculas no aparecía si se tipeaba en minúscula, y
    UPPER() de SQLite además es solo ASCII (no pliega Ñ/vocales acentuadas).

    En ambos casos, el resultado queda ordenado del crédito más reciente al
    más antiguo (fecha_desembolso DESC) — pedido explícito del usuario para
    el historial de un cliente con múltiples créditos."""
    termino = (termino or "").strip()

    if termino:
        tipo = clasificar_termino_busqueda(termino)
        filas = conn.execute(f"{_SELECT_BASE} ORDER BY fecha_desembolso DESC, id DESC").fetchall()
        termino_mayus = termino.upper()
        if tipo == "cedula":
            return [f for f in filas if termino_mayus in (f[_INDICE_CEDULA] or "").upper()]
        return [f for f in filas if termino_mayus in (f[_INDICE_NOMBRE] or "").upper()]

    query = f"{_SELECT_BASE} WHERE estado_credito = ? ORDER BY fecha_desembolso DESC, id DESC"
    return conn.execute(query, (ESTADO_CREDITO_ACTIVO,)).fetchall()
