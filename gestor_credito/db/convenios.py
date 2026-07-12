def obtener_tasa(conn, empresa_convenio):
    """Tasa de interés anual para `empresa_convenio`, o None si la empresa no
    está en convenio_tasa o si está pero sin tasa asignada todavía (ver
    CONVENIOS_INICIALES en db/database.py — dos empresas reales del Excel de
    origen no tenían tasa definida ahí tampoco).

    Comparación TRIM() de ambos lados a propósito: el `caso.empresa_convenio`
    real importado de MIDESA no siempre coincide carácter a carácter con el
    nombre "oficial" de convenio_tasa (p. ej. un caso real trae
    "CAFE LAS FLORES CHAIN" mientras que el convenio es "CAFE LAS FLORES") —
    TRIM() por sí solo no arregla ese tipo de discrepancia (son nombres
    distintos, no solo espacios de más), así que esta función solo cubre el
    caso de espacios sueltos; una discrepancia real de nombre simplemente no
    encuentra tasa y devuelve None. Por eso el panel de la Calculadora NO
    da por sentado que la empresa del caso siempre resuelve una tasa: deja
    elegir la empresa de una lista en vez de fijarla de solo lectura."""
    fila = conn.execute(
        "SELECT tasa_interes FROM convenio_tasa WHERE TRIM(empresa_convenio) = TRIM(?)",
        (empresa_convenio or "",),
    ).fetchone()
    return fila[0] if fila else None


def listar_convenios(conn):
    """Todas las empresas convenio conocidas con su tasa (None si no tiene
    asignada), ordenadas alfabéticamente — para poblar el wx.Choice de
    empresa en el panel de la Calculadora."""
    filas = conn.execute(
        "SELECT empresa_convenio, tasa_interes FROM convenio_tasa ORDER BY empresa_convenio"
    ).fetchall()
    return [(fila[0], fila[1]) for fila in filas]


def guardar_tasa(conn, empresa_convenio, tasa_interes):
    """Crea o actualiza la tasa de una empresa convenio. `tasa_interes` en
    formato fracción (0.36 = 36%), igual que el resto de la app."""
    conn.execute(
        "INSERT INTO convenio_tasa (empresa_convenio, tasa_interes, fecha_actualizacion) "
        "VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(empresa_convenio) DO UPDATE SET "
        "tasa_interes = excluded.tasa_interes, fecha_actualizacion = excluded.fecha_actualizacion",
        (empresa_convenio, tasa_interes),
    )
    conn.commit()
