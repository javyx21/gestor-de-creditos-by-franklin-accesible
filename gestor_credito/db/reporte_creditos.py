from gestor_credito.calculo.avance_credito import calcular_avance_pago, es_elegible_refinanciamiento
from gestor_credito.db.casos import clasificar_termino_busqueda

# Confirmado con el usuario (2026-07-12): el Excel real no trae un estado
# literal "Activo" — los valores reales de ESTADO_CREDITO son Corriente,
# Cancelado, Saneado, Vencido, Trámite y Prorrogado (este último descubierto
# 2026-08-21, ver ESTADO_CREDITO_PRORROGADO). "Corriente" es el que
# corresponde a "Activo" — sigue siendo un valor válido para `estado`
# (crédito al día), aunque ya no tiene su propia entrada en el selector
# "Estado" del panel (ver ESTADO_OPCIONES en creditos_panel.py — pedido
# explícito del usuario, 2026-08-22: "solo tres estados").
ESTADO_CREDITO_ACTIVO = "Corriente"

# Vista "Cancelados" del selector "Estado" (pedido explícito del usuario,
# 2026-08-22, reemplaza a la antigua "Finalizados para reenganche"):
# igualdad de texto simple, NO la condición compuesta que existía antes.
# Confirmado explícitamente: un crédito con cuotas ya completas pero cuyo
# estado_credito todavía dice "Corriente" NO debe aparecer acá — "si el
# sistema dice que está activo, eso está prohibido [tratarlo como
# cancelado]". Ese caso especial vive en CreditosPanel (ver
# _es_caso_especial_activo_con_cuotas_completas), con su propio color/sonido,
# separado de este filtro.
ESTADO_CREDITO_CANCELADO = "Cancelado"

# Alerta visual/sonora en la lista de Historial de Créditos (pedido explícito
# del usuario, 2026-08-21): mismo equivalente auditivo/visual que ya tiene
# Casos para "Documentos pendientes" (ver casos_panel.py), acá para créditos
# en alguno de estos estados — ver CreditosPanel._es_credito_en_alerta,
# _refrescar_lista, _on_seleccionar_credito. No cambia ningún filtro
# existente: es puramente decorativo sobre las filas que ya se muestran.
ESTADO_CREDITO_VENCIDO = "Vencido"
ESTADO_CREDITO_SANEADO = "Saneado"
# Descubierto validando contra un reporte real (2026-08-21): existe un sexto
# valor real de ESTADO_CREDITO no documentado hasta ahora, "Prorrogado" — el
# usuario confirmó que debe tratarse igual que Vencido/Saneado para esta
# alerta ("ese cliente es un cliente especial y no deberíamos de darle
# crédito").
ESTADO_CREDITO_PRORROGADO = "Prorrogado"
ESTADOS_CREDITO_ALERTA = (ESTADO_CREDITO_VENCIDO, ESTADO_CREDITO_SANEADO, ESTADO_CREDITO_PRORROGADO)

# Sentinel para pedir explícitamente que buscar_creditos() no filtre por
# estado_credito en absoluto, sin importar si hay término de búsqueda.
# Distinto de omitir el parámetro `estado` (que por defecto sí filtra a
# ESTADO_CREDITO_ACTIVO, para no cambiar el comportamiento de cualquier
# llamado existente que no pase `estado`). Es el valor por defecto real del
# selector "Estado" del panel (ver _INDICE_ESTADO_POR_DEFECTO en
# creditos_panel.py).
ESTADO_TODOS = "__todos__"

# Sentinel para el selector "Estado" de Historial de Créditos: vista de
# créditos elegibles para refinanciamiento (pedido explícito del usuario,
# 2026-08-21). NO es una condición SQL simple — depende del cruce de avance
# de pago (ver gestor_credito/calculo/avance_credito.py), así que se filtra
# Y se ordena en Python después de traer las filas, no con un WHERE/ORDER BY
# — ver _fila_es_elegible_refinanciamiento()/_avance_pago_de_fila() más
# abajo. Orden (pedido explícito del usuario, 2026-08-22): por % de avance
# de pago descendente — el que le falta menos por pagar primero, hasta
# llegar a los que están justo en el umbral (50%).
ESTADO_ELEGIBLES_REFINANCIAMIENTO = "__elegibles_refinanciamiento__"

# Índices de columna dentro de las tuplas que devuelve buscar_creditos() (ver
# _SELECT_BASE más abajo).
_INDICE_CEDULA = 2
_INDICE_NOMBRE = 3

_SELECT_BASE = """
    SELECT id, no_credito, cedula, nombre_cliente, fecha_desembolso, fecha_vencimiento,
           monto_desembolsado, estado_credito, empresa_convenio, plazo_credito, numero_cuotas,
           cuotas_pagadas, estado_credito_fecha_cambio, saldo_principal, saldo_intereses,
           dias_en_mora, es_convenio, fecha_ultimo_pago_principal
    FROM reporte_credito
"""


def buscar_creditos(conn, termino=None, estado=ESTADO_CREDITO_ACTIVO, empresa=None):
    """Consulta del módulo Historial de Créditos.

    Filtros, todos combinables con AND:
    - `termino`: cédula (si trae algún dígito) o nombre (si es solo letras) —
      misma clasificación que buscar_casos() en db/casos.py. Ambas
      comparaciones son insensibles a mayúsculas y se hacen en Python con
      str.upper(), no con el UPPER() de SQLite (mismo motivo/mismo fix que
      buscar_casos(), reporte real del usuario 2026-07-12: UPPER() de SQLite
      es solo ASCII y no pliega Ñ/vocales acentuadas).
    - `estado`: por defecto ESTADO_CREDITO_ACTIVO ("Corriente") — todavía
      válido como valor programático, pero el panel ya no expone esa opción
      por su cuenta (ver ESTADO_OPCIONES en creditos_panel.py). Pasar
      ESTADO_TODOS para no filtrar por estado en absoluto (el valor por
      defecto real del selector del panel),
      ESTADO_CREDITO_CANCELADO ("Cancelado", igualdad simple) para la vista
      "Cancelados", o ESTADO_ELEGIBLES_REFINANCIAMIENTO para la vista de
      candidatos a refinanciamiento (condición Python, no SQL — ver arriba).
    - `empresa`: nombre exacto de empresa_convenio — reduce los resultados a
      una sola empresa en vez de listar todas globalmente (pedido explícito
      del usuario 2026-08-16); ver obtener_empresas_convenio() para la lista
      de empresas realmente presentes en este reporte.

    Orden del resultado:
    - ESTADO_CREDITO_CANCELADO: por fecha_ultimo_pago_principal DESCENDENTE
      — pedido explícito del usuario (2026-08-22): el que pagó por última
      vez más recientemente va primero. NO se usa estado_credito_fecha_cambio
      para esto — bug real encontrado el mismo día validando con datos
      reales: en una base recién importada, esa columna guarda cuándo el
      IMPORT detectó el estado "Cancelado", no cuándo se canceló de verdad
      (2,997 créditos "Cancelado" reales quedaron con solo 5 valores
      distintos, los pocos segundos que tardó el import completo — el orden
      salía prácticamente aleatorio). fecha_ultimo_pago_principal sí es un
      dato real de MIDESA (98% de cobertura en los "Cancelado" reales, 2,933
      de 2,997) — los créditos sin esa fecha cargada (64 son créditos reales
      y completos, con saldo en cero, que MIDESA simplemente no les cargó
      esta fecha en su sistema) quedan al final: SQLite ya ordena NULL al
      final en DESC por defecto, sin necesitar lógica aparte.
    - ESTADO_ELEGIBLES_REFINANCIAMIENTO: por % de avance de pago
      descendente (ver _avance_pago_de_fila) — el que le falta menos por
      pagar primero.
    - Cualquier otro valor de `estado` (incluido el default): por
      fecha_desembolso descendente, como siempre."""
    termino = (termino or "").strip()
    empresa = (empresa or "").strip() or None

    # Clasificar (y así validar) el término ANTES de consultar la base de
    # datos, igual que la versión original — un término inválido no debe ni
    # llegar a ejecutar la consulta.
    tipo = clasificar_termino_busqueda(termino) if termino else None

    condiciones = []
    parametros = []

    if estado == ESTADO_TODOS or estado == ESTADO_ELEGIBLES_REFINANCIAMIENTO:
        # Elegibles para refinanciamiento no tiene una condición SQL simple
        # (depende del cruce de avance de pago) — se trae todo y se filtra
        # en Python más abajo, ver _fila_es_elegible_refinanciamiento().
        pass
    elif estado is not None:
        condiciones.append("estado_credito = ?")
        parametros.append(estado)

    if empresa is not None:
        condiciones.append("empresa_convenio = ?")
        parametros.append(empresa)

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    orden = (
        "fecha_ultimo_pago_principal DESC, id DESC"
        if estado == ESTADO_CREDITO_CANCELADO
        else "fecha_desembolso DESC, id DESC"
    )
    filas = conn.execute(f"{_SELECT_BASE} {where} ORDER BY {orden}", parametros).fetchall()

    if estado == ESTADO_ELEGIBLES_REFINANCIAMIENTO:
        filas = [f for f in filas if _fila_es_elegible_refinanciamiento(f)]
        # El % de avance nunca es None acá: _fila_es_elegible_refinanciamiento
        # ya exige estado_avance == "ok" (y por lo tanto avance_pago no nulo)
        # para devolver True — ver es_elegible_refinanciamiento().
        filas.sort(key=_avance_pago_de_fila, reverse=True)

    if not termino:
        return filas

    termino_mayus = termino.upper()
    indice = _INDICE_CEDULA if tipo == "cedula" else _INDICE_NOMBRE
    return [f for f in filas if termino_mayus in (f[indice] or "").upper()]


def _desempaquetar_para_avance(fila):
    (
        _id, _no_credito, _cedula, _nombre_cliente, _fecha_desembolso, _fecha_vencimiento,
        monto_desembolsado, estado_credito, _empresa_convenio, plazo_credito, numero_cuotas,
        cuotas_pagadas, _estado_credito_fecha_cambio, saldo_principal, saldo_intereses,
        dias_en_mora, es_convenio, _fecha_ultimo_pago_principal,
    ) = fila
    return (
        estado_credito, dias_en_mora, es_convenio,
        saldo_principal, saldo_intereses, monto_desembolsado,
        cuotas_pagadas, numero_cuotas, plazo_credito,
    )


def _fila_es_elegible_refinanciamiento(fila):
    """Aplica el cruce de avance de pago (ver
    gestor_credito/calculo/avance_credito.py) para decidir si una fila de
    _SELECT_BASE califica para refinanciamiento — pedido explícito del
    usuario (2026-08-21)."""
    (
        estado_credito, dias_en_mora, es_convenio,
        saldo_principal, saldo_intereses, monto_desembolsado,
        cuotas_pagadas, numero_cuotas, plazo_credito,
    ) = _desempaquetar_para_avance(fila)
    avance_pago, estado_avance = calcular_avance_pago(
        saldo_principal, saldo_intereses, monto_desembolsado,
        cuotas_pagadas, numero_cuotas, plazo_credito,
    )
    return es_elegible_refinanciamiento(
        estado_credito, dias_en_mora, es_convenio, avance_pago, estado_avance,
    )


def _avance_pago_de_fila(fila):
    """% de avance de pago de una fila de _SELECT_BASE — usado para ordenar
    la vista "Elegibles para refinanciar" (pedido explícito del usuario,
    2026-08-22: de mayor a menor avance)."""
    (
        _estado_credito, _dias_en_mora, _es_convenio,
        saldo_principal, saldo_intereses, monto_desembolsado,
        cuotas_pagadas, numero_cuotas, plazo_credito,
    ) = _desempaquetar_para_avance(fila)
    avance_pago, _estado_avance = calcular_avance_pago(
        saldo_principal, saldo_intereses, monto_desembolsado,
        cuotas_pagadas, numero_cuotas, plazo_credito,
    )
    return avance_pago


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
