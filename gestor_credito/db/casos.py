import re

from gestor_credito.catalogos import (
    ESTADO_DESEMBOLSADA,
    ESTADO_EN_ESPERA_CONSTANCIA,
    ESTADO_EN_PROCESO,
    ESTADOS_CERRADOS,
)
from gestor_credito.db.alertas import completar_documentos_por_desembolso

# Índices de columna dentro de las tuplas que devuelve _seleccionar_casos().
_INDICE_CASO_ID = 0
_INDICE_EJECUTIVO = 3
_INDICE_NOMBRE = 5
_INDICE_CEDULA = 6
_INDICE_ESTADO_SOLICITUD = 11
_INDICE_CLIENTE_ID = 17
_INDICE_DOCUMENTOS_COMPLETOS_FECHA = 18

_PATRON_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚÑÜáéíóúñü ]+$")
_PATRON_CEDULA = re.compile(r"^[0-9A-Za-z-]+$")

# Valores del combobox "Filtrar por alerta" de la pestaña Casos. A diferencia
# de las alertas de Notificaciones (ver gestor_credito/db/alertas.py), acá NO
# se aplica ningún umbral de tiempo (7 días / 24h / 48h) — es un filtro de
# ESTADO actual, no de alerta vencida. Con la primera versión (reusando los
# umbrales de Notificaciones) el combobox mostraba 0 filas para cualquier
# opción específica apenas se importaba la bitácora, porque nada llevaba
# todavía 7 días/24h/48h en ese estado — reporte real del usuario, confirmado
# contra la base real (19 casos en "En espera de constancia", 0 con >=7 días).
FILTRO_ALERTA_TODOS = "todos"
FILTRO_ALERTA_DOCUMENTOS_PENDIENTES = "documentos_pendientes"
FILTRO_ALERTA_CONSTANCIA_PENDIENTE = "constancia_pendiente"
FILTRO_ALERTA_CONSTANCIA_EN_MANO = "constancia_en_mano"


def clasificar_termino_busqueda(termino):
    """Decide si un término de búsqueda combinado (cédula o nombre) es uno u
    otro. Devuelve 'cedula' o 'nombre'. Lanza ValueError con un mensaje apto
    para mostrar al usuario si el término no es válido para ninguno de los dos
    (p. ej. trae símbolos que no son ni dígitos ni letras).

    No es tolerante con tildes: una letra con un acento que no coincida con el
    dato real simplemente no vas a encontrar coincidencia (búsqueda exacta en
    ese sentido), en vez de normalizar/adivinar. Es insensible a mayúsculas.
    """
    termino = termino.strip()

    if any(caracter.isdigit() for caracter in termino):
        # Las cédulas reales de la bitácora pueden traer un sufijo de letra
        # (p. ej. "2011307810010Q"), por eso alcanza con que tenga un dígito.
        if _PATRON_CEDULA.fullmatch(termino):
            return "cedula"
        raise ValueError("Ese texto no es válido para buscar por cédula.")

    if _PATRON_NOMBRE.fullmatch(termino):
        return "nombre"

    raise ValueError(
        "Ingresá solo números (para buscar por cédula) o letras (para buscar por nombre)."
    )


def buscar_casos(conn, ejecutivo_actual=None, termino=None, filtro_alerta=None):
    """Búsqueda de la pestaña Casos.

    Sin término: filtra por ejecutivo_actual (el agente configurado, o trae
    todo si todavía no hay agente configurado) y, además, por filtro_alerta si
    no es None/FILTRO_ALERTA_TODOS. Este filtro por ejecutivo se aplica en SQL
    (ver _seleccionar_casos), no trayendo todo el historial de todos los
    agentes para descartar la mayoría en Python — optimización real
    (2026-07-12): reporte del usuario de lentitud real al cambiar de pestaña
    (recargar() corre siempre, ver MainFrame) a medida que se acumulan casos
    de más agentes con el uso diario. El resultado final es idéntico al de
    antes, solo más barato de calcular; ya existía un índice
    (idx_caso_ejecutivo) para esta columna, sin usar hasta ahora.

    Con término: busca por cédula (si el término trae algún dígito) o por
    nombre (si es solo letras), e IGNORA tanto ejecutivo_actual como
    filtro_alerta — una búsqueda específica por cédula/nombre tiene prioridad
    sobre ambos filtros, aunque el resultado sea de otro agente o no cumpla el
    filtro de alerta seleccionado. Ambos tipos de búsqueda son insensibles a
    mayúsculas (reporte real del usuario, 2026-07-12: una cédula real
    guardada en mayúsculas —p. ej. con sufijo "Q"— no aparecía si se
    tipeaba en minúscula, ya sea a propósito o por tener Bloq Mayús
    desactivado). Se compara con str.upper() de Python, no UPPER() de
    SQLite, mismo motivo que ya usa la comparación por nombre: UPPER() en
    SQLite es solo ASCII y no pliega correctamente Ñ/vocales acentuadas
    (irrelevante para cédulas en sí, pero mantiene una sola forma de
    comparar en todo este módulo).
    """
    termino = (termino or "").strip()

    if termino:
        # Un término específico busca en TODOS los agentes por diseño, así
        # que acá sí hace falta traer todo el historial — ver docstring.
        filas = _seleccionar_casos(conn)
        tipo = clasificar_termino_busqueda(termino)
        termino_mayus = termino.upper()
        if tipo == "cedula":
            filas = [f for f in filas if termino_mayus in (f[_INDICE_CEDULA] or "").upper()]
        else:
            filas = [f for f in filas if termino_mayus in (f[_INDICE_NOMBRE] or "").upper()]
        return filas

    filas = _seleccionar_casos(conn, ejecutivo_actual=ejecutivo_actual)

    if filtro_alerta and filtro_alerta != FILTRO_ALERTA_TODOS:
        filas = _filtrar_por_alerta(filas, filtro_alerta)

    return filas


def _filtrar_por_alerta(filas, filtro_alerta):
    # Un caso en estado cerrado (Desembolsada, No aplica, Cliente desistió) ya
    # no tiene nada pendiente con el cliente, así que se excluye de los 3
    # filtros por igual, sin importar si técnicamente cumpliría la condición
    # de cada uno (p. ej. documentos_completos_fecha todavía NULL en un caso
    # ya Desembolsada) — reporte real del usuario.
    filas = [f for f in filas if f[_INDICE_ESTADO_SOLICITUD] not in ESTADOS_CERRADOS]

    if filtro_alerta == FILTRO_ALERTA_DOCUMENTOS_PENDIENTES:
        return [f for f in filas if f[_INDICE_DOCUMENTOS_COMPLETOS_FECHA] is None]

    if filtro_alerta == FILTRO_ALERTA_CONSTANCIA_PENDIENTE:
        return [f for f in filas if f[_INDICE_ESTADO_SOLICITUD] == ESTADO_EN_ESPERA_CONSTANCIA]

    if filtro_alerta == FILTRO_ALERTA_CONSTANCIA_EN_MANO:
        # Antes chequeaba constancia_recibida_fecha (solo se estampaba si el
        # importador VEÍA la transición en vivo dentro de un mismo import) —
        # un caso importado por primera vez ya en "En proceso" nunca
        # calificaba, aunque la constancia ya estuviera en mano. Bug real
        # reportado por el usuario, mismo fix que alertas_constancia_en_mano()
        # en db/alertas.py: usar el estado actual directamente.
        return [f for f in filas if f[_INDICE_ESTADO_SOLICITUD] == ESTADO_EN_PROCESO]

    return filas


def _seleccionar_casos(conn, ejecutivo_actual=None):
    # El orden de las primeras 17 columnas de este SELECT (hasta observaciones)
    # es el orden exacto en que deben mostrarse en la lista de la pestaña Casos
    # (ver COLUMNAS en casos_panel.py). cliente_id, documentos_completos_fecha y
    # constancia_recibida_fecha se agregan al final, sin alterar ese orden: no
    # se muestran como columna de la lista, solo se usan para precargar/editar
    # el checkbox "Documentos completados" del panel de edición y para el
    # filtro "Filtrar por alerta" (ver _filtrar_por_alerta más arriba).
    query = """
        SELECT caso.id,
               caso.fecha_registro,
               caso.no_presolicitud,
               caso.ejecutivo,
               caso.empresa_convenio,
               cliente.nombre,
               cliente.cedula,
               cliente.telefono,
               caso.monto_solicitado,
               caso.destino_credito,
               caso.microseguro,
               caso.estado_solicitud,
               caso.etapa_proceso,
               caso.responsable_actual,
               caso.decision,
               caso.motivo_no_aplica,
               caso.observaciones,
               caso.cliente_id,
               cliente.documentos_completos_fecha,
               caso.constancia_recibida_fecha
        FROM caso
        JOIN cliente ON cliente.id = caso.cliente_id
        {where}
        ORDER BY caso.fecha_registro DESC, caso.id DESC
    """
    if ejecutivo_actual:
        return conn.execute(
            query.format(where="WHERE caso.ejecutivo = ?"), (ejecutivo_actual,)
        ).fetchall()
    return conn.execute(query.format(where="")).fetchall()


def obtener_ejecutivos(conn):
    filas = conn.execute(
        "SELECT DISTINCT ejecutivo FROM caso "
        "WHERE ejecutivo IS NOT NULL AND ejecutivo != '' ORDER BY ejecutivo"
    ).fetchall()
    return [fila[0] for fila in filas]


def actualizar_edicion_manual(conn, caso_id, estado_solicitud, etapa_proceso):
    """Aplica una edición manual desde la app (no una importación de Excel).

    No toca constancia_recibida_fecha: esa fecha SOLO la marca el importador al
    detectar el cambio de estado en el Excel, nunca una edición manual.
    """
    estado_anterior, cliente_id = conn.execute(
        "SELECT estado_solicitud, cliente_id FROM caso WHERE id = ?", (caso_id,)
    ).fetchone()

    set_sql = [
        "estado_solicitud = ?",
        "etapa_proceso = ?",
        "origen_ultima_modificacion = 'manual'",
        "fecha_actualizacion_registro = datetime('now')",
    ]
    params = [estado_solicitud, etapa_proceso]

    if estado_solicitud != estado_anterior:
        set_sql.append("estado_solicitud_fecha_cambio = datetime('now')")

    params.append(caso_id)
    conn.execute(f"UPDATE caso SET {', '.join(set_sql)} WHERE id = ?", params)
    conn.commit()

    # Un caso que llega a Desembolsada evidentemente tuvo sus documentos
    # completos para llegar hasta ahí — ver completar_documentos_por_desembolso.
    if estado_solicitud == ESTADO_DESEMBOLSADA:
        completar_documentos_por_desembolso(conn, cliente_id)


def actualizar_responsable_actual(conn, caso_id, responsable_actual):
    """Cambia quién tiene el caso en su poder, desde el menú contextual de
    Casos (ver casos_panel.py)."""
    conn.execute(
        "UPDATE caso SET responsable_actual = ?, origen_ultima_modificacion = 'manual', "
        "fecha_actualizacion_registro = datetime('now') WHERE id = ?",
        (responsable_actual, caso_id),
    )
    conn.commit()


def eliminar_caso(conn, caso_id):
    """Borra solo este caso. El cliente y sus demás casos no se ven afectados
    (a diferencia de eliminar_cliente() en db/clientes.py, que borra todo el
    historial) — ver menú contextual y botón de Casos."""
    conn.execute("DELETE FROM caso WHERE id = ?", (caso_id,))
    conn.commit()
