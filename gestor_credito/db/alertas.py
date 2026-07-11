"""Cálculo de las alertas del sistema. Todas se derivan en vivo del estado actual
de cliente/caso (no se guardan como filas de alerta aparte) y se filtran por
ejecutivo_actual igual que la vista por defecto de la pestaña Casos — ver
Configuración y Alertas en CLAUDE.md.

Los umbrales de tiempo se calculan con julianday('now') de SQLite (siempre UTC),
no con datetime.now() de Python, para no mezclar UTC (lo que guardan
datetime('now') en fecha_creacion/estado_solicitud_fecha_cambio) con hora
local y arrastrar un corrimiento horario.

Regla general de las 3 alertas, confirmada con el usuario tras un bug real
reportado (ver alertas_constancia_en_mano): el punto de partida del conteo se
marca la PRIMERA VEZ que el sistema detecta que el caso/cliente entró en el
estado correspondiente — sea porque vio la transición en vivo durante un
import, o porque el caso/cliente ya venía así desde la primera vez que se
importó — y esa fecha NUNCA se recalcula por una reimportación que no cambia
nada; solo se reinicia si el estado realmente cambia. Si cada reimportación
diaria reiniciara el conteo para los casos sin cambios, ninguna alerta
llegaría a dispararse nunca. `cliente.fecha_creacion` (Alerta 1) y
`caso.estado_solicitud_fecha_cambio` (Alertas 2 y 3) ya se comportan así por
diseño — se estampan una vez al insertar y solo se tocan de nuevo cuando el
valor relevante cambia de verdad (ver actualizar_edicion_manual en db/casos.py
y el importador)."""

from gestor_credito.catalogos import ESTADOS_CERRADOS
from gestor_credito.db.database import ESTADO_EN_ESPERA_CONSTANCIA, ESTADO_EN_PROCESO

HORAS_ALERTA_DOCUMENTOS = 24
DIAS_ALERTA_CONSTANCIA_PENDIENTE = 7
HORAS_ALERTA_CONSTANCIA_EN_MANO = 48


def alertas_documentos_pendientes(conn, ejecutivo_actual=None):
    """Clientes nuevos sin documentos_completos_fecha, con >= 24h desde su alta,
    y que tengan AL MENOS UN caso todavía abierto (no Desembolsada/No aplica/
    Cliente desistió).

    Sigue activa indefinidamente (no se apaga por tiempo) hasta que se marque
    documentos_completos_fecha con marcar_documentos_completos(). El ejecutivo
    de referencia es el del primer caso que dio de alta a ese cliente (la
    columna vive en cliente, no en caso — ver CLAUDE.md, Alerta 1).

    La exclusión de clientes con TODOS sus casos ya cerrados se agregó tras un
    bug real reportado por el usuario en producción: un cliente cuyo único
    crédito ya estaba Desembolsada (evidentemente con documentos completos
    para haber llegado hasta ahí) seguía apareciendo para siempre en esta
    alerta si nadie había marcado documentos_completos_fecha a mano — 42 casos
    así se acumularon en su base real. Mismo criterio que ya usaba
    FILTRO_ALERTA_DOCUMENTOS_PENDIENTES en db/casos.py para el filtro de
    Casos, ahora también acá para que ambas vistas coincidan. Un cliente con
    AL MENOS UN caso todavía abierto (aunque tenga otros ya cerrados) sigue
    alertando con normalidad.
    """
    placeholders = ", ".join("?" for _ in ESTADOS_CERRADOS)
    query = f"""
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
          AND EXISTS (
              SELECT 1 FROM caso
              WHERE caso.cliente_id = cliente.id
                AND caso.estado_solicitud NOT IN ({placeholders})
          )
        ORDER BY cliente.fecha_creacion ASC
    """
    filas = conn.execute(query, (HORAS_ALERTA_DOCUMENTOS, *ESTADOS_CERRADOS)).fetchall()

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
    """Casos actualmente en 'En proceso' (constancia en mano, a la espera de
    darle respuesta al cliente) con >= 48h desde estado_solicitud_fecha_cambio
    — el mismo mecanismo que alertas_constancia_pendiente(), no un campo
    aparte. Se abandonó constancia_recibida_fecha (que el importador solo
    estampaba al VER en vivo la transición 'En espera de constancia' ->
    'En proceso' dentro de un mismo import) porque un caso importado por
    primera vez ya en 'En proceso' — la constancia ya estaba en mano antes de
    entrar a esta app — nunca disparaba esta alerta sin importar cuánto
    tiempo pasara: bug real reportado por el usuario. estado_solicitud_fecha_cambio
    ya cumple la regla general (ver arriba) sola, así que reusarla resuelve el
    bug para todos los casos, pasados y futuros, sin campo ni migración
    nuevos. Al quedar acotada a estado_solicitud == 'En proceso', ya no hace
    falta excluir Desembolsada aparte: en cuanto el estado cambia a lo que
    sea, deja de calificar."""
    query = """
        SELECT caso.id, caso.clave_caso, caso.ejecutivo, cliente.nombre, cliente.cedula,
               caso.estado_solicitud_fecha_cambio
        FROM caso
        JOIN cliente ON cliente.id = caso.cliente_id
        WHERE caso.estado_solicitud = ?
          AND (julianday('now') - julianday(caso.estado_solicitud_fecha_cambio)) * 24 >= ?
        ORDER BY caso.estado_solicitud_fecha_cambio ASC
    """
    filas = conn.execute(
        query, (ESTADO_EN_PROCESO, HORAS_ALERTA_CONSTANCIA_EN_MANO)
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


def marcar_documentos_completos(conn, cliente_id):
    """Apaga para siempre la Alerta 'Documentos pendientes' de ese cliente."""
    conn.execute(
        "UPDATE cliente SET documentos_completos_fecha = datetime('now'), "
        "fecha_actualizacion = datetime('now') WHERE id = ?",
        (cliente_id,),
    )
    conn.commit()


def marcar_documentos_pendientes(conn, cliente_id):
    """Reversa manual de marcar_documentos_completos: reactiva la Alerta
    'Documentos pendientes' para este cliente. Solo se ofrece desde el menú
    contextual de Casos, no desde el panel de edición principal (que solo
    permite marcar como completo) — pedido explícito del usuario para poder
    corregir un cliente marcado por error o al que después le faltó un
    documento."""
    conn.execute(
        "UPDATE cliente SET documentos_completos_fecha = NULL, "
        "fecha_actualizacion = datetime('now') WHERE id = ?",
        (cliente_id,),
    )
    conn.commit()


def completar_documentos_por_desembolso(conn, cliente_id):
    """Si un caso del cliente llega a ESTADO_DESEMBOLSADA, sus documentos
    evidentemente estaban completos para que el crédito se desembolsara —
    esto cierra sola la Alerta 'Documentos pendientes' en vez de dejarla en
    blanco para siempre. Se llama desde el importador (_upsert_caso, tanto al
    insertar un caso nuevo ya Desembolsada como al actualizar uno existente
    a ese estado) y desde actualizar_edicion_manual() en db/casos.py, para
    cubrir tanto el reimport de Excel como el cambio manual de estado.

    NO pisa una fecha ya existente (WHERE documentos_completos_fecha IS
    NULL): si el usuario ya la había marcado antes a mano (con una fecha real
    distinta), esa fecha original se respeta. Idempotente: llamarla de nuevo
    sobre un cliente ya marcado no hace nada.

    Agregada tras un reporte real del usuario (2026-07-11): sin esto, un
    cliente cuyo único crédito llegaba a Desembolsada quedaba con
    documentos_completos_fecha en NULL para siempre — sin alertar (por la
    exclusión de casos cerrados ya existente, ver alertas_documentos_pendientes),
    pero también sin ninguna acción automática que cerrara el dato. Se
    detectaron 78 clientes reales en ese estado; ver el backfill puntual en
    el historial de commits (no es una migración de esquema, solo un UPDATE
    de datos)."""
    conn.execute(
        "UPDATE cliente SET documentos_completos_fecha = datetime('now'), "
        "fecha_actualizacion = datetime('now') "
        "WHERE id = ? AND documentos_completos_fecha IS NULL",
        (cliente_id,),
    )
    conn.commit()
