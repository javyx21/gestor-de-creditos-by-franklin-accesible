import sqlite3
import sys
from pathlib import Path

from gestor_credito.catalogos import ESTADO_DESEMBOLSADA, ESTADO_EN_ESPERA_CONSTANCIA, ESTADO_EN_PROCESO


def _directorio_base():
    """Carpeta base para data/gestor_credito.db.

    Empaquetada con PyInstaller, __file__ apunta adentro de la carpeta interna
    del bundle (p. ej. _internal/), no junto al .exe — usar eso tal cual
    dejaría la base de datos enterrada ahí en vez de junto al ejecutable, y
    rompería del todo con un empaquetado --onefile (esa carpeta es temporal,
    se borra al cerrar la app y se vuelve a crear vacía en el próximo inicio,
    perdiendo todos los datos). sys.executable sí apunta siempre al .exe real
    en cualquier modo de empaquetado, así que la base de datos queda visible
    junto a él, persistiendo entre ejecuciones — necesario para que la app sea
    realmente portable en un pendrive."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


DB_PATH = _directorio_base() / "data" / "gestor_credito.db"

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

-- Tasa de interés anual por empresa convenio, para la Calculadora de crédito
-- (panel independiente, ver ui/calculadora_panel.py) — reemplaza la hoja
-- "Convenios" del Excel de referencia (recursos/calculadora.xlsx). tasa_interes
-- puede ser NULL: dos empresas reales del Excel de origen (GRUPO TALSE,
-- LABORATORIOS ROMAN) no tenían tasa definida ahí tampoco — se preserva ese
-- vacío en vez de inventar un valor, ver db/convenios.py.
CREATE TABLE IF NOT EXISTS convenio_tasa (
    empresa_convenio TEXT PRIMARY KEY,
    tasa_interes REAL,
    fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Última simulación de capacidad crediticia por caso (panel Calculadora,
-- completamente separado de Casos — no se referencia desde casos_panel.py a
-- propósito, ver CLAUDE.md). UNIQUE(caso_id): a propósito NO se guarda
-- historial, "Guardar simulación" pisa la fila anterior de ese caso. Se
-- guardan las ENTRADAS junto con los RESULTADOS calculados en su momento,
-- no solo el resultado — así, si más adelante cambia una tasa o la fórmula,
-- una simulación guardada sigue reflejando lo que realmente se calculó
-- cuando se guardó, en vez de derivar (y posiblemente cambiar) un resultado
-- recalculado con datos nuevos.
CREATE TABLE IF NOT EXISTS calculo_credito (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id INTEGER NOT NULL UNIQUE REFERENCES caso(id),

    empresa_convenio TEXT NOT NULL,
    tasa_interes REAL NOT NULL,
    fecha_ingreso_empresa TEXT NOT NULL,
    salario_bruto_cordobas REAL NOT NULL,
    ingresos_extra_cordobas REAL NOT NULL DEFAULT 0,
    monto_credito_usd REAL NOT NULL,
    plazo_meses INTEGER NOT NULL,
    periodicidad TEXT NOT NULL,
    tipo_cambio REAL NOT NULL,
    deuda_activa_cordobas REAL NOT NULL DEFAULT 0,

    pasivo_laboral_cordobas REAL NOT NULL,
    salario_neto_cordobas REAL NOT NULL,
    cuota_usd REAL NOT NULL,
    cobertura_pasivo_laboral REAL NOT NULL,
    nivel_endeudamiento REAL NOT NULL,

    fecha_calculo TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Reporte periódico de créditos ya desembolsados (recursos/reporte.xlsx),
-- módulo nuevo e independiente ("Historial de Créditos") — NO se referencia
-- desde cliente/caso a propósito, mismo criterio de independencia ya usado
-- para convenio_tasa/calculo_credito (ver CLAUDE.md, Calculadora de Crédito):
-- cedula/nombre_cliente son columnas propias de este reporte, no una FK a
-- cliente. no_credito es UNIQUE: es la clave real del Excel de origen (sin
-- duplicados verificados en el reporte real), así que una reimportación
-- periódica actualiza la fila existente en vez de duplicarla, igual que
-- clave_caso en la bitácora de MIDESA.
CREATE TABLE IF NOT EXISTS reporte_credito (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    no_credito TEXT NOT NULL UNIQUE,
    cedula TEXT NOT NULL,
    nombre_cliente TEXT NOT NULL,
    fecha_desembolso TEXT,
    fecha_vencimiento TEXT,
    monto_desembolsado REAL,
    estado_credito TEXT,
    empresa_convenio TEXT,
    plazo_credito INTEGER,

    -- Número TOTAL de cuotas del crédito (no confundir con plazo_credito, que
    -- está en meses — ver la misma distinción ya documentada para
    -- Calculadora!B11 en CLAUDE.md). Agregada 2026-08-16 junto con el filtro
    -- "cuotas pendientes" de Historial de Créditos: sin esta columna no hay
    -- forma de calcular cuántas cuotas le faltan a un cliente para terminar.
    numero_cuotas INTEGER,
    cuotas_pagadas INTEGER,

    -- Agregadas 2026-08-21 a pedido explícito del usuario: NO se muestran
    -- como columnas propias en Historial de Créditos (ui/creditos_panel.py)
    -- — solo alimentan la columna calculada "Saldo a la fecha" = SALDO_PRINCIPAL
    -- + SALDO_INTERESES, mismo criterio ya usado para "Cuotas Pendientes"
    -- (se calcula al mostrar, nunca se guarda como su propia columna aparte).
    saldo_principal REAL,
    saldo_intereses REAL,

    -- Desde cuándo estado_credito tiene su valor actual — mismo patrón que
    -- caso.estado_solicitud_fecha_cambio (ver Domain model). Se usa para
    -- ordenar la vista "Finalizados (Cancelado)" por más recientemente
    -- pagado, no por fecha_desembolso (que es la fecha de inicio del
    -- crédito, no la de su cierre). NOT NULL DEFAULT solo aplica a bases de
    -- datos nuevas (CREATE TABLE); _migrar_reporte_credito() más abajo la
    -- agrega y rellena a mano en bases ya existentes, porque SQLite no
    -- admite un DEFAULT no constante en ALTER TABLE ADD COLUMN.
    estado_credito_fecha_cambio TEXT NOT NULL DEFAULT (datetime('now')),

    fecha_actualizacion_registro TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reporte_credito_cedula ON reporte_credito(cedula);
CREATE INDEX IF NOT EXISTS idx_reporte_credito_estado ON reporte_credito(estado_credito);
CREATE INDEX IF NOT EXISTS idx_reporte_credito_empresa ON reporte_credito(empresa_convenio);
"""

# Tasas reales extraídas de la hoja "Convenios" del Excel de referencia
# (recursos/calculadora.xlsx) — el usuario confirmó (2026-07-11) que siguen
# vigentes. Se siembran con INSERT OR IGNORE: solo llenan la tabla si está
# vacía para esa empresa, nunca pisan una tasa que ya se haya editado a mano
# desde la app (ver db/convenios.py:guardar_tasa). None = la empresa no
# tenía tasa definida en el Excel de origen tampoco (ver comentario en
# CREATE TABLE convenio_tasa arriba) — se siembra igual, con NULL, en vez de
# omitirla, para que aparezca en la lista y quede claro que falta asignarle
# una tasa.
CONVENIOS_INICIALES = [
    ("ACEITERA EL REAL", 0.33),
    ("AGROSACO", 0.41),
    ("AIRTEC", 0.41),
    ("BLP", 0.45),
    ("CAFE LAS FLORES", 0.36),
    ("CLUB TERRAZA", 0.45),
    ("CASCO SAFETY", 0.36),
    ("DIVECO", 0.45),
    ("EL HALCON", 0.45),
    ("EL ZOCALO", 0.36),
    ("FORMUNICA", 0.45),
    ("GRUPO TALSE", None),
    ("GSQ Nicaragua", 0.36),
    ("HANTER METALS", 0.45),
    ("IMMSA", 0.36),
    ("INDENICSA", 0.33),
    ("JOHN MAY", 0.45),
    ("LA NANI CAFÉ", 0.36),
    ("LABORATORIOS ROMAN", None),
    ("LALA", 0.45),
    ("MANPOWER", 0.45),
    ("MI VIEJO RANCHITO", 0.36),
    ("MULTIPERFILES", 0.45),
    ("PANADERIA LA NANI", 0.45),
    ("RAPIDITO TO GO", 0.45),
    ("REPSA", 0.36),
    ("SPORT LINE", 0.45),
    ("MIDESA", 0.18),
    ("NICAES", 0.60),
]


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrar_reporte_credito(conn):
    """Agrega a bases de datos YA EXISTENTES las columnas que
    'CREATE TABLE IF NOT EXISTS' no toca en una tabla que ya existe
    (2026-08-16, filtros nuevos de Historial de Créditos). numero_cuotas se
    agrega nullable — las filas ya importadas no tienen ese dato hasta el
    próximo reimport, y no hay forma de reconstruirlo retroactivamente desde
    lo que ya se guardó. estado_credito_fecha_cambio no puede llevar
    DEFAULT (datetime('now')) en un ALTER TABLE (SQLite lo rechaza por ser un
    valor no constante — confirmado empíricamente), así que se agrega sin
    default y se rellena una sola vez con la fecha de la migración; a partir
    de ahí, reporte_creditos_importer.py la mantiene igual que
    estado_solicitud_fecha_cambio en caso: la pisa a 'ahora' solo cuando
    estado_credito realmente cambia, nunca en cada reimport."""
    # El CREATE TABLE IF NOT EXISTS de arriba ya corrió: la tabla existe
    # siempre acá, con todas las columnas (base nueva) o con las columnas
    # viejas nada más (base ya existente, creada antes de este cambio).
    columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(reporte_credito)")}

    if "numero_cuotas" not in columnas:
        conn.execute("ALTER TABLE reporte_credito ADD COLUMN numero_cuotas INTEGER")

    if "estado_credito_fecha_cambio" not in columnas:
        conn.execute("ALTER TABLE reporte_credito ADD COLUMN estado_credito_fecha_cambio TEXT")
        conn.execute(
            "UPDATE reporte_credito SET estado_credito_fecha_cambio = datetime('now') "
            "WHERE estado_credito_fecha_cambio IS NULL"
        )

    if "saldo_principal" not in columnas:
        conn.execute("ALTER TABLE reporte_credito ADD COLUMN saldo_principal REAL")

    if "saldo_intereses" not in columnas:
        conn.execute("ALTER TABLE reporte_credito ADD COLUMN saldo_intereses REAL")


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _migrar_reporte_credito(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO convenio_tasa (empresa_convenio, tasa_interes) VALUES (?, ?)",
            CONVENIOS_INICIALES,
        )
        conn.commit()
    finally:
        conn.close()
