"""Capa de datos de "Recordatorios de Llamada" — pestaña deliberadamente
aparte de Notificaciones (ver CLAUDE.md: el usuario la rechazó por no llamar
su atención de verdad). Un recordatorio es solo nombre/cédula/celular/empresa
más fecha y hora a llamar, sin FK a cliente/caso — mismo criterio de
independencia que convenio_tasa/calculo_credito. buscar_datos_cliente_por_cedula
es un asistente de autocompletado opcional (ver recordatorios_panel.py), nunca
un vínculo obligatorio: si la cédula no existe todavía como cliente, el
oficial llena los datos a mano.

fecha_llamar/hora_llamar son una cita en HORA LOCAL puesta por el oficial, a
diferencia de las columnas de alertas.py (documentos_completos_fecha,
estado_solicitud_fecha_cambio) que están selladas en UTC vía datetime('now')
de SQLite y se comparan con julianday('now'). Mezclar ambos criterios sería un
error de husos horarios, así que toda la lógica de "¿ya se cumplió/pospuso la
hora?" vive acá, en Python, con datetime.now() local (ver esta_vencido/
obtener_recordatorios_vencidos) — nunca en SQL con datetime('now')."""

from datetime import datetime, timedelta

FORMATO_DATETIME = "%Y-%m-%d %H:%M:%S"
FORMATO_FECHA_HORA_LLAMAR = "%Y-%m-%d %H:%M"

_COLUMNAS = (
    "id", "nombre", "cedula", "celular", "empresa_convenio",
    "fecha_llamar", "hora_llamar", "ejecutivo", "atendido",
    "fecha_atendido", "pospuesto_hasta",
)


def _fila_a_dict(fila):
    return dict(zip(_COLUMNAS, fila))


def crear_recordatorio(conn, nombre, cedula, celular, empresa_convenio, fecha_llamar, hora_llamar, ejecutivo):
    cur = conn.execute(
        """
        INSERT INTO recordatorio_llamada
            (nombre, cedula, celular, empresa_convenio, fecha_llamar, hora_llamar, ejecutivo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (nombre, cedula, celular, empresa_convenio, fecha_llamar, hora_llamar, ejecutivo),
    )
    conn.commit()
    return cur.lastrowid


def actualizar_recordatorio(conn, recordatorio_id, nombre, cedula, celular, empresa_convenio, fecha_llamar, hora_llamar):
    conn.execute(
        """
        UPDATE recordatorio_llamada
        SET nombre = ?, cedula = ?, celular = ?, empresa_convenio = ?,
            fecha_llamar = ?, hora_llamar = ?
        WHERE id = ?
        """,
        (nombre, cedula, celular, empresa_convenio, fecha_llamar, hora_llamar, recordatorio_id),
    )
    conn.commit()


def eliminar_recordatorio(conn, recordatorio_id):
    conn.execute("DELETE FROM recordatorio_llamada WHERE id = ?", (recordatorio_id,))
    conn.commit()


def marcar_atendido(conn, recordatorio_id, ahora=None):
    momento = (ahora or datetime.now()).strftime(FORMATO_DATETIME)
    conn.execute(
        "UPDATE recordatorio_llamada SET atendido = 1, fecha_atendido = ? WHERE id = ?",
        (momento, recordatorio_id),
    )
    conn.commit()


def posponer_recordatorio(conn, recordatorio_id, minutos=5, ahora=None):
    """Pospone UN recordatorio puntual `minutos` desde `ahora` (o desde
    datetime.now() local si no se pasa) — ver RecordatorioAlarmaDialog, que
    llama esto una vez por cada fila que sigue listada al presionar
    "Posponer"/Escape."""
    momento = (ahora or datetime.now()) + timedelta(minutes=minutos)
    conn.execute(
        "UPDATE recordatorio_llamada SET pospuesto_hasta = ? WHERE id = ?",
        (momento.strftime(FORMATO_DATETIME), recordatorio_id),
    )
    conn.commit()


def listar_recordatorios(conn, ejecutivo_actual=None):
    """Todos los recordatorios (atendidos o no), para la lista de la pestaña.
    Igual que Casos: con ejecutivo_actual configurado, solo se ven los propios
    más los recordatorios legado sin agente asignado (ejecutivo NULL)."""
    query = f"SELECT {', '.join(_COLUMNAS)} FROM recordatorio_llamada"
    parametros = ()
    if ejecutivo_actual:
        query += " WHERE ejecutivo = ? OR ejecutivo IS NULL"
        parametros = (ejecutivo_actual,)
    query += " ORDER BY fecha_llamar, hora_llamar"
    filas = conn.execute(query, parametros).fetchall()
    return [_fila_a_dict(fila) for fila in filas]


def esta_vencido(recordatorio, ahora):
    """True si `recordatorio` (dict con al menos fecha_llamar/hora_llamar/
    pospuesto_hasta) ya se cumplió y no está actualmente pospuesto más allá de
    `ahora` — no mira `atendido` acá, eso lo filtra el caller (ver
    obtener_recordatorios_vencidos y RecordatoriosPanel._refrescar_lista, que
    reutilizan esta misma función para no duplicar la comparación de fechas)."""
    try:
        momento_llamar = datetime.strptime(
            f"{recordatorio['fecha_llamar']} {recordatorio['hora_llamar']}",
            FORMATO_FECHA_HORA_LLAMAR,
        )
    except (ValueError, TypeError):
        return False
    if momento_llamar > ahora:
        return False

    pospuesto_hasta = recordatorio.get("pospuesto_hasta")
    if pospuesto_hasta:
        try:
            if datetime.strptime(pospuesto_hasta, FORMATO_DATETIME) > ahora:
                return False
        except ValueError:
            pass
    return True


def obtener_recordatorios_vencidos(conn, ejecutivo_actual=None, ahora=None):
    """Recordatorios NO atendidos cuya fecha/hora (o posposición) ya se
    cumplió contra `ahora` (datetime.now() local si no se pasa — parámetro
    solo para pruebas deterministas, mismo criterio que _hace() en
    test_alertas.py). Es lo que dispara la alarma real, ver
    MainFrame._on_verificar_recordatorios."""
    ahora = ahora or datetime.now()
    pendientes = [r for r in listar_recordatorios(conn, ejecutivo_actual) if not r["atendido"]]
    vencidos = [r for r in pendientes if esta_vencido(r, ahora)]
    vencidos.sort(key=lambda r: (r["fecha_llamar"] or "", r["hora_llamar"] or ""))
    return vencidos


def buscar_datos_cliente_por_cedula(conn, cedula):
    """Autocompletado pedido explícitamente por el usuario: si `cedula` ya
    existe como cliente, trae su nombre/teléfono y la empresa convenio de su
    caso más reciente (por fecha_registro) — cédula es la clave natural
    durable del dominio (ver CLAUDE.md). None si no hay ningún cliente con esa
    cédula (el oficial la llena a mano, tal como pidió)."""
    fila = conn.execute(
        """
        SELECT cliente.nombre, cliente.telefono, caso.empresa_convenio
        FROM cliente
        LEFT JOIN caso ON caso.cliente_id = cliente.id
        WHERE cliente.cedula = ?
        ORDER BY caso.fecha_registro DESC
        LIMIT 1
        """,
        (cedula,),
    ).fetchone()
    if fila is None:
        return None
    return {"nombre": fila[0], "telefono": fila[1], "empresa_convenio": fila[2]}
