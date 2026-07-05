"""Cálculo de las alertas del sistema. Todas se derivan en vivo del estado actual
de cliente/caso (no se guardan como filas de alerta aparte) y se filtran por
ejecutivo_actual igual que la vista por defecto de la pestaña Casos — ver
Configuración y Alertas en CLAUDE.md.

Los umbrales de tiempo se calculan con julianday('now') de SQLite (siempre UTC),
no con datetime.now() de Python, para no mezclar UTC (lo que guardan
datetime('now') en fecha_creacion/estado_solicitud_fecha_cambio/
constancia_recibida_fecha) con hora local y arrastrar un corrimiento horario.
"""

from gestor_credito.db.database import ESTADO_DESEMBOLSADA, ESTADO_EN_ESPERA_CONSTANCIA

HORAS_ALERTA_DOCUMENTOS = 24
DIAS_ALERTA_CONSTANCIA_PENDIENTE = 7
HORAS_ALERTA_CONSTANCIA_EN_MANO = 48


def alertas_documentos_pendientes(conn, ejecutivo_actual=None):
    """Clientes nuevos sin documentos_completos_fecha, con >= 24h desde su alta.

    Sigue activa indefinidamente (no se apaga por tiempo) hasta que se marque
    documentos_completos_fecha con marcar_documentos_completos(). El ejecutivo
    de referencia es el del primer caso que dio de alta a ese cliente (la
    columna vive en cliente, no en caso — ver CLAUDE.md, Alerta 1).
    """
    query = """
        SELECT cliente.id, cliente.nombre, cliente.cedula, cliente.fecha_creacion,
               (
                   SELECT caso.ejecutivo FROM caso
                   WHERE caso.cliente_id = cliente.id
                   ORDER BY caso.fecha_creacion_registro ASC, caso.id ASC
                   LIMIT 1
               ) AS ejecutivo_alta
        FROM cliente
        WHERE cliente.documentos_completos_fecha IS NULL
          AND (julianday('now') - julianday(cliente.fecha_creacion)) * 24 >= ?
        ORDER BY cliente.fecha_creacion ASC
    """
    filas = conn.execute(query, (HORAS_ALERTA_DOCUMENTOS,)).fetchall()

    if ejecutivo_actual:
        filas = [f for f in filas if f[4] == ejecutivo_actual]

    return [
        {"cliente_id": f[0], "nombre": f[1], "cedula": f[2], "fecha_creacion": f[3]}
        for f in filas
    ]


def alertas_constancia_pendiente(conn, ejecutivo_actual=None):
    """Casos en 'En espera de constancia' con >= 7 días desde
    estado_solicitud_fecha_cambio."""
    query = """
        SELECT caso.id, caso.clave_caso, caso.ejecutivo, cliente.nombre, cliente.cedula,
               caso.estado_solicitud_fecha_cambio
        FROM caso
        JOIN cliente ON cliente.id = caso.cliente_id
        WHERE caso.estado_solicitud = ?
          AND (julianday('now') - julianday(caso.estado_solicitud_fecha_cambio)) >= ?
        ORDER BY caso.estado_solicitud_fecha_cambio ASC
    """
    filas = conn.execute(
        query, (ESTADO_EN_ESPERA_CONSTANCIA, DIAS_ALERTA_CONSTANCIA_PENDIENTE)
    ).fetchall()

    if ejecutivo_actual:
        filas = [f for f in filas if f[2] == ejecutivo_actual]

    return [
        {
            "caso_id": f[0], "clave_caso": f[1], "ejecutivo": f[2],
            "nombre": f[3], "cedula": f[4], "estado_solicitud_fecha_cambio": f[5],
        }
        for f in filas
    ]


def alertas_constancia_en_mano(conn, ejecutivo_actual=None):
    """Casos donde se detectó constancia recibida (transición 'En espera de
    constancia' -> 'En proceso' durante un import, ver excel_importer.py) hace
    >= 48h y que todavía no llegaron a Desembolsada.

    Se asume que al llegar a Desembolsada el caso ya está resuelto y esta
    alerta puntual deja de tener sentido — a confirmar con el usuario si no es
    así.
    """
    query = """
        SELECT caso.id, caso.clave_caso, caso.ejecutivo, cliente.nombre, cliente.cedula,
               caso.constancia_recibida_fecha, caso.estado_solicitud
        FROM caso
        JOIN cliente ON cliente.id = caso.cliente_id
        WHERE caso.constancia_recibida_fecha IS NOT NULL
          AND caso.estado_solicitud != ?
          AND (julianday('now') - julianday(caso.constancia_recibida_fecha)) * 24 >= ?
        ORDER BY caso.constancia_recibida_fecha ASC
    """
    filas = conn.execute(
        query, (ESTADO_DESEMBOLSADA, HORAS_ALERTA_CONSTANCIA_EN_MANO)
    ).fetchall()

    if ejecutivo_actual:
        filas = [f for f in filas if f[2] == ejecutivo_actual]

    return [
        {
            "caso_id": f[0], "clave_caso": f[1], "ejecutivo": f[2],
            "nombre": f[3], "cedula": f[4], "constancia_recibida_fecha": f[5],
            "estado_solicitud": f[6],
        }
        for f in filas
    ]


def marcar_documentos_completos(conn, cliente_id):
    """Apaga para siempre la Alerta 'Documentos pendientes' de ese cliente."""
    conn.execute(
        "UPDATE cliente SET documentos_completos_fecha = datetime('now'), "
        "fecha_actualizacion = datetime('now') WHERE id = ?",
        (cliente_id,),
    )
    conn.commit()
