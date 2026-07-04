CLAVE_EJECUTIVO_ACTUAL = "ejecutivo_actual"


def obtener_valor(conn, clave):
    fila = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila[0] if fila else None


def guardar_valor(conn, clave, valor):
    conn.execute(
        "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, valor),
    )
    conn.commit()
