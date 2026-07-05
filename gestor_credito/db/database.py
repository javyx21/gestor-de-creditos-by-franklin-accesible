import sqlite3
from pathlib import Path

from gestor_credito.catalogos import ESTADO_DESEMBOLSADA, ESTADO_EN_ESPERA_CONSTANCIA, ESTADO_EN_PROCESO

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "gestor_credito.db"

__all__ = [
    "DB_PATH", "ESTADO_EN_ESPERA_CONSTANCIA", "ESTADO_EN_PROCESO", "ESTADO_DESEMBOLSADA",
    "get_connection", "init_db",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS cliente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cedula TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    telefono TEXT,

    -- NULL = Alerta 1 (documentación de cliente nuevo pendiente) sigue activa para este
    -- cliente. Se marca a mano en la app; una vez puesta, la alerta se apaga para siempre.
    documentos_completos_fecha TEXT,

    fecha_creacion TEXT NOT NULL DEFAULT (datetime('now')),
    fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS caso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES cliente(id),

    -- Identificadores traídos del Excel. clave_caso = COALESCE(no_presolicitud, id_caso),
    -- calculada por el importador; es la que junto a cliente_id define si un caso ya existe.
    id_caso TEXT,
    no_presolicitud TEXT,
    clave_caso TEXT NOT NULL,

    -- Columnas tal como vienen en la bitácora de MIDESA. Las fechas siempre se toman
    -- del Excel, nunca de la fecha en la que se importa el archivo.
    fecha_registro TEXT,
    canal_origen TEXT,
    ejecutivo TEXT,
    empresa_convenio TEXT,
    monto_solicitado REAL,
    destino_credito TEXT,
    microseguro TEXT,
    estado_solicitud TEXT,
    etapa_proceso TEXT,
    responsable_actual TEXT,
    fecha_ultima_gestion TEXT,
    proxima_gestion TEXT,
    dias_en_gestion INTEGER,
    alerta_seguimiento TEXT,
    requiere_siaf TEXT,
    fecha_envio_siaf TEXT,
    fecha_decision TEXT,
    decision TEXT,
    motivo_no_aplica TEXT,
    observaciones TEXT,

    -- Informativa, tal como viene de la columna "Constancia Solicitada" del Excel real
    -- (valor numérico, p. ej. 1 — no es una fecha pese al nombre de la columna; su
    -- significado exacto está sin confirmar). No dispara ninguna alerta por sí sola
    -- (ver estado_solicitud_fecha_cambio, que es lo que sí usa la Alerta 2).
    constancia_solicitada TEXT,

    -- Desde cuándo estado_solicitud tiene su valor actual. Se actualiza a la fecha/hora
    -- del sistema cada vez que estado_solicitud cambia (por import o por edición manual).
    -- Alerta 2 = estado_solicitud == 'En espera de constancia' Y han pasado >= 7 días desde aquí.
    estado_solicitud_fecha_cambio TEXT NOT NULL DEFAULT (datetime('now')),

    -- NO viene del Excel. La pone el IMPORTADOR automáticamente (fecha del sistema en el
    -- momento de importar) al detectar que estado_solicitud pasó específicamente de
    -- 'En espera de constancia' a 'En proceso' (no cualquier otro valor). Dispara la
    -- Alerta "Constancia en mano" (48h para dar respuesta, ver gestor_credito/alertas.py).
    constancia_recibida_fecha TEXT,

    -- Auditoría interna, no viene del Excel.
    origen_ultima_modificacion TEXT NOT NULL DEFAULT 'excel',
    fecha_creacion_registro TEXT NOT NULL DEFAULT (datetime('now')),
    fecha_actualizacion_registro TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE (cliente_id, clave_caso)
);

-- Ajustes de la app. Uso previsto: fila ('ejecutivo_actual', '<usuario configurado>') que
-- controla para qué agente se muestran las Alertas 1 y 2 (ver Configuración en CLAUDE.md).
CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_caso_ejecutivo ON caso(ejecutivo);
CREATE INDEX IF NOT EXISTS idx_caso_fecha_registro ON caso(fecha_registro);
CREATE INDEX IF NOT EXISTS idx_caso_estado_solicitud ON caso(estado_solicitud);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
