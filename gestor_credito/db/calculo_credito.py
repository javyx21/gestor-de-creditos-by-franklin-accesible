_COLUMNAS = (
    "empresa_convenio", "tasa_interes", "fecha_ingreso_empresa",
    "salario_bruto_cordobas", "ingresos_extra_cordobas", "monto_credito_usd",
    "plazo_meses", "periodicidad", "tipo_cambio", "deuda_activa_cordobas",
    "pasivo_laboral_cordobas", "salario_neto_cordobas", "cuota_usd",
    "cobertura_pasivo_laboral", "nivel_endeudamiento",
)


def obtener_simulacion(conn, caso_id):
    """Última simulación guardada para `caso_id`, como dict, o None si
    todavía no se guardó ninguna. Incluye tanto las entradas (empresa, tasa,
    salario, plazo, etc.) como los resultados calculados en su momento — ver
    el comentario de calculo_credito en db/database.py sobre por qué se
    guardan juntos."""
    fila = conn.execute(
        f"SELECT {', '.join(_COLUMNAS)}, fecha_calculo "
        "FROM calculo_credito WHERE caso_id = ?",
        (caso_id,),
    ).fetchone()
    if fila is None:
        return None
    return dict(zip(_COLUMNAS + ("fecha_calculo",), fila))


def guardar_simulacion(conn, caso_id, datos):
    """Guarda (o reemplaza, si ya había una) la simulación de `caso_id`.
    `datos` es un dict con exactamente las claves de _COLUMNAS. A propósito
    NO se guarda historial — UNIQUE(caso_id) en el esquema hace que esto sea
    un upsert: solo la última simulación de cada caso queda guardada."""
    columnas = ", ".join(_COLUMNAS)
    marcadores = ", ".join(f":{col}" for col in _COLUMNAS)
    actualizaciones = ", ".join(f"{col} = excluded.{col}" for col in _COLUMNAS)
    conn.execute(
        f"INSERT INTO calculo_credito (caso_id, {columnas}, fecha_calculo) "
        f"VALUES (:caso_id, {marcadores}, datetime('now')) "
        f"ON CONFLICT(caso_id) DO UPDATE SET {actualizaciones}, fecha_calculo = datetime('now')",
        {**datos, "caso_id": caso_id},
    )
    conn.commit()
