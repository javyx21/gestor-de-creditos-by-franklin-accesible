from gestor_credito.db.casos import clasificar_termino_busqueda

# Confirmado con el usuario (2026-07-12): el Excel real no trae un estado
# literal "Activo" — los valores reales de ESTADO_CREDITO son Corriente,
# Cancelado, Saneado, Vencido y Trámite. "Corriente" es el que corresponde a
# "Activo" en la vista por defecto (crédito al día, pagándose con normalidad).
ESTADO_CREDITO_ACTIVO = "Corriente"

# Alerta visual/sonora en la lista de Historial de Créditos (pedido explícito
# del usuario, 2026-08-21): mismo equivalente auditivo/visual que ya tiene
# Casos para "Documentos pendientes" (ver casos_panel.py), acá para créditos
# en alguno de estos dos estados — ver CreditosPanel._es_credito_en_alerta,
# _refrescar_lista, _on_seleccionar_credito. No cambia ningún filtro
# existente: es puramente decorativo sobre las filas que ya se muestran.
ESTADO_CREDITO_VENCIDO = "Vencido"
ESTADO_CREDITO_SANEADO = "Saneado"
ESTADOS_CREDITO_ALERTA = (ESTADO_CREDITO_VENCIDO, ESTADO_CREDITO_SANEADO)

# Estados textuales que el usuario considera "finalizado" (pedido explícito,
# 2026-08-16, segunda ronda: "estado sea 'Cancelado' / 'Finalizado'"). Ninguna
# fila real verificada usa literalmente "Finalizado" (los valores reales de
# ESTADO_CREDITO son Corriente/Cancelado/Saneado/Vencido/Trámite), pero se
# incluye por si un reporte futuro lo trae así — no hace daño buscar un valor
# que hoy no existe.
_ESTADOS_CREDITO_CERRADOS = ("Cancelado", "Finalizado")

# Sentinel para el selector "Estado" de Historial de Créditos: vista de
# "Créditos finalizados" (campañas de reenganche). NO es una simple igualdad
# de texto — es una condición compuesta (ver _condicion_finalizado() más
# abajo), a propósito: estado_credito en _ESTADOS_CREDITO_CERRADOS, O BIEN
# cuotas pendientes <= 0. Verificado empíricamente contra el reporte real
# (2026-08-16, recursos/reporte.xlsx): casi toda fila con estado_credito ==
# "Cancelado" tiene cuotas_pagadas >= numero_cuotas (2717 de 2717), pero hay
# 22 filas reales con cuotas_pagadas >= numero_cuotas cuyo estado_credito
# todavía dice "Trámite" (el sistema de origen no había actualizado el
# estado) — sin la parte de "cuotas pendientes <= 0", esos 22 clientes ya
# terminaron de pagar pero quedarían invisibles para una campaña de
# reenganche hasta que MIDESA actualice su estado, algo que puede tardar.
ESTADO_CREDITO_FINALIZADO = "__finalizado__"

# Sentinel para pedir explícitamente que buscar_creditos() no filtre por
# estado_credito en absoluto, sin importar si hay término de búsqueda.
# Distinto de omitir el parámetro `estado` (que por defecto sí filtra a
# ESTADO_CREDITO_ACTIVO, para no cambiar el comportamiento de cualquier
# llamado existente que no pase `estado`).
ESTADO_TODOS = "__todos__"

# Índices de columna dentro de las tuplas que devuelve buscar_creditos() (ver
# _SELECT_BASE más abajo).
_INDICE_CEDULA = 2
_INDICE_NOMBRE = 3

_SELECT_BASE = """
    SELECT id, no_credito, cedula, nombre_cliente, fecha_desembolso, fecha_vencimiento,
           monto_desembolsado, estado_credito, empresa_convenio, plazo_credito, numero_cuotas,
           cuotas_pagadas, estado_credito_fecha_cambio, saldo_principal, saldo_intereses
    FROM reporte_credito
"""

_CONDICION_CUOTAS_CERO_O_MENOS = (
    "(numero_cuotas IS NOT NULL AND cuotas_pagadas IS NOT NULL "
    "AND (numero_cuotas - cuotas_pagadas) <= 0)"
)


def buscar_creditos(conn, termino=None, estado=ESTADO_CREDITO_ACTIVO, empresa=None,
                     cuotas_pendientes_maximo=None):
    """Consulta del módulo Historial de Créditos.

    Filtros, todos combinables con AND:
    - `termino`: cédula (si trae algún dígito) o nombre (si es solo letras) —
      misma clasificación que buscar_casos() en db/casos.py. Ambas
      comparaciones son insensibles a mayúsculas y se hacen en Python con
      str.upper(), no con el UPPER() de SQLite (mismo motivo/mismo fix que
      buscar_casos(), reporte real del usuario 2026-07-12: UPPER() de SQLite
      es solo ASCII y no pliega Ñ/vocales acentuadas).
    - `estado`: por defecto ESTADO_CREDITO_ACTIVO ("Corriente" — vista por
      defecto de la pestaña). Pasar ESTADO_CREDITO_FINALIZADO para la vista
      de créditos ya pagados en su totalidad (condición compuesta, ver
      constante arriba — NO es una simple igualdad de texto), o ESTADO_TODOS
      para no filtrar por estado en absoluto — usado por el selector
      "Estado" del panel (2026-08-16: antes, un término de búsqueda ignoraba
      automáticamente el filtro de estado para mostrar el historial completo
      del cliente; eso quedó reemplazado por este control explícito, ver
      CLAUDE.md).
    - `empresa`: nombre exacto de empresa_convenio — reduce los resultados a
      una sola empresa en vez de listar todas globalmente (pedido explícito
      del usuario 2026-08-16); ver obtener_empresas_convenio() para la lista
      de empresas realmente presentes en este reporte. Se combina con
      cualquier valor de `estado` — p. ej. "Próximos a finalizar en IMMSA" es
      estado=ESTADO_CREDITO_ACTIVO + empresa="IMMSA" + cuotas_pendientes_maximo=2.
    - `cuotas_pendientes_maximo`: entero — coincidencia contra
      (numero_cuotas - cuotas_pagadas) <= N (NO es igualdad exacta), para
      ubicar clientes a N cuotas o menos de terminar su crédito ("Próximos a
      finalizar" — pedido explícito del usuario 2026-08-16, campañas de
      reenganche; sus propios ejemplos fueron "<= 2" y "<= 3"). Combinado con
      el `estado` por defecto (ESTADO_CREDITO_ACTIVO), esto ES el filtro
      "Próximos a finalizar" — no hay un parámetro aparte para eso, es esta
      misma combinación. Filas sin numero_cuotas o cuotas_pagadas cargados
      nunca matchean (no hay forma de calcular cuántas cuotas les faltan).

    El resultado queda ordenado del crédito más reciente al más antiguo. Al
    ver específicamente ESTADO_CREDITO_FINALIZADO, "más reciente" se define
    por estado_credito_fecha_cambio (desde cuándo ese crédito está en su
    estado_credito actual, ver columna en database.py) en vez de
    fecha_desembolso, para que la vista de "finalizados recientemente"
    (campañas de reenganche) muestre primero los que terminaron de pagar
    hace menos tiempo, no los que se desembolsaron hace menos tiempo (dos
    fechas distintas)."""
    termino = (termino or "").strip()
    empresa = (empresa or "").strip() or None

    # Clasificar (y así validar) el término ANTES de consultar la base de
    # datos, igual que la versión original — un término inválido no debe ni
    # llegar a ejecutar la consulta.
    tipo = clasificar_termino_busqueda(termino) if termino else None

    condiciones = []
    parametros = []

    if estado == ESTADO_TODOS:
        pass
    elif estado == ESTADO_CREDITO_FINALIZADO:
        placeholders = ", ".join("?" for _ in _ESTADOS_CREDITO_CERRADOS)
        condiciones.append(f"(estado_credito IN ({placeholders}) OR {_CONDICION_CUOTAS_CERO_O_MENOS})")
        parametros.extend(_ESTADOS_CREDITO_CERRADOS)
    elif estado is not None:
        condiciones.append("estado_credito = ?")
        parametros.append(estado)

    if empresa is not None:
        condiciones.append("empresa_convenio = ?")
        parametros.append(empresa)

    if cuotas_pendientes_maximo is not None:
        condiciones.append(
            "numero_cuotas IS NOT NULL AND cuotas_pagadas IS NOT NULL "
            "AND (numero_cuotas - cuotas_pagadas) <= ?"
        )
        parametros.append(cuotas_pendientes_maximo)

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    orden = (
        "estado_credito_fecha_cambio DESC, id DESC"
        if estado == ESTADO_CREDITO_FINALIZADO
        else "fecha_desembolso DESC, id DESC"
    )
    filas = conn.execute(f"{_SELECT_BASE} {where} ORDER BY {orden}", parametros).fetchall()

    if not termino:
        return filas

    termino_mayus = termino.upper()
    indice = _INDICE_CEDULA if tipo == "cedula" else _INDICE_NOMBRE
    return [f for f in filas if termino_mayus in (f[indice] or "").upper()]


def obtener_empresas_convenio(conn):
    """Empresas realmente presentes en reporte_credito, no el catálogo global
    de convenio_tasa (que puede incluir empresas sin ningún crédito en este
    reporte, o nombrarlas distinto — ver comentario sobre "CAFE LAS FLORES
    CHAIN" vs "CAFE LAS FLORES" en CLAUDE.md/calculadora_panel.py). Pedido
    explícito del usuario (2026-08-16): el selector "Empresa" de Historial de
    Créditos debe segmentar los créditos de este reporte, no listar todas las
    empresas globalmente."""
    filas = conn.execute(
        "SELECT DISTINCT empresa_convenio FROM reporte_credito "
        "WHERE empresa_convenio IS NOT NULL AND empresa_convenio != '' "
        "ORDER BY empresa_convenio"
    ).fetchall()
    return [fila[0] for fila in filas]
