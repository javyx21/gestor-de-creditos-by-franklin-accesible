"""Operaciones de borrado sobre cliente/caso. Ambas funciones son irreversibles
a propósito: la UI (casos_panel.py, configuracion_panel.py) pide confirmación
con un wx.MessageBox Sí/No antes de llamarlas — ver CLAUDE.md."""


def eliminar_cliente(conn, cliente_id):
    """Borra un cliente y TODOS sus casos (un cliente puede tener varios casos
    a lo largo del tiempo — ver CLAUDE.md). caso.cliente_id no tiene
    ON DELETE CASCADE en el esquema (evita depender de una migración en bases
    ya creadas), así que los casos se borran primero, en la misma conexión."""
    conn.execute("DELETE FROM caso WHERE cliente_id = ?", (cliente_id,))
    conn.execute("DELETE FROM cliente WHERE id = ?", (cliente_id,))
    conn.commit()


def contar_casos(conn, cliente_id):
    """Cuántos casos tiene este cliente — usado en la confirmación de
    eliminar_cliente() para que el usuario vea cuánto historial va a perder
    antes de confirmar."""
    (total,) = conn.execute(
        "SELECT COUNT(*) FROM caso WHERE cliente_id = ?", (cliente_id,)
    ).fetchone()
    return total


def vaciar_base_datos(conn):
    """Borra TODOS los clientes y casos. No toca la tabla configuracion:
    conserva el agente configurado (confirmado con el usuario, para no tener
    que reconfigurarlo después de limpiar datos de prueba)."""
    conn.execute("DELETE FROM caso")
    conn.execute("DELETE FROM cliente")
    conn.commit()
