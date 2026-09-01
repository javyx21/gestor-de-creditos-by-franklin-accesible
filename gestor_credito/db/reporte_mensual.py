"""Reporte Mensual de Casos: Desembolsados (con/sin microseguro), No aplica,
Cliente desistió y Pendientes — para seguimiento de comisiones (ver
CLAUDE.md, sección "Reporte Mensual de Casos").

Lógica confirmada explícitamente con el usuario:

- Un caso cuenta como Desembolsado si existe un crédito correspondiente en
  reporte_credito (Historial de Créditos, que se actualiza automático desde
  el sistema real de MIDESA) — esto tiene PRIORIDAD sobre caso.estado_solicitud,
  que lo editan los compañeros a mano y puede quedar desactualizado ("esta se
  actualiza con el sistema, en cambio el de Casos es manual... es con esta
  que me voy a ir"). Ver _emparejar_creditos().
- El "mes" de un Desembolsado es el mes real de reporte_credito.fecha_desembolso
  del crédito emparejado — fecha exacta de MIDESA, no una aproximación.
- Para emparejar el crédito correcto cuando un mismo cliente tiene varios
  créditos a lo largo del tiempo (43% de las cédulas reales del reporte
  tienen más de uno, hasta 18), se usa el ejemplo confirmado por el usuario:
  un caso registrado en agosto nunca puede corresponder a un crédito
  desembolsado en enero (sería de un caso viejo del mismo cliente) — solo
  califica un crédito con fecha_desembolso >= fecha_registro del caso, y de
  esos, el más próximo. Cada crédito se asigna como mucho a un caso.
- Si NO hay crédito emparejado, se usa caso.estado_solicitud tal cual
  (incluida Desembolsada, con estado_solicitud_fecha_cambio como fecha
  aproximada — un compañero pudo haberlo marcado a mano antes de que
  aparezca en el histórico). No aplica y Cliente desistió también usan
  estado_solicitud_fecha_cambio, a falta de otra fecha real (fecha_decision
  del Excel de MIDESA está prácticamente vacía en la práctica, validado
  contra un archivo real: 0 de 455 casos "Desembolsada" la traían llena).
- Pendientes NUNCA se filtra por mes: es la lista viva de todo lo que sigue
  abierto ahora mismo, para que nada se pierda de vista entre un mes y el
  siguiente — el día que se resuelva, cae solo en el mes real en que
  realmente se resolvió.
"""

from gestor_credito.catalogos import (
    ESTADO_CLIENTE_DESISTIO,
    ESTADO_DESEMBOLSADA,
    ESTADO_NO_APLICA,
    formatear_microseguro,
)

# Bug real encontrado por el usuario (2026-08-31, cliente Harry Tinoco Benly):
# un caso que un compañero YA marcó explícitamente como "Cliente desistió"
# (con su motivo, "no quería el monto que le ofrecían") le estaba robando el
# crédito de Historial a otro caso más nuevo del MISMO cliente que sí seguía
# genuinamente pendiente — terminaba mostrado como "Desembolsado" con el
# motivo de desistimiento pegado, y el caso realmente pendiente se quedaba
# sin su crédito real. La regla "Historial manda" (ver el docstring del
# módulo) tiene sentido para un caso cuyo estado_solicitud todavía no se
# actualizó (sigue en un estado ABIERTO aunque ya se haya desembolsado de
# verdad) — pero NO tiene sentido para un caso que un humano ya cerró de
# forma explícita y negativa: ahí no hay ninguna duda que resolver, así que
# nunca debe competir por un crédito de Historial que casi seguro pertenece
# a otro caso distinto de la misma persona.
_ESTADOS_CERRADOS_SIN_EMPAREJAR = frozenset({ESTADO_NO_APLICA, ESTADO_CLIENTE_DESISTIO})

_COLUMNAS_CASO = (
    "id", "clave_caso", "fecha_registro", "estado_solicitud",
    "estado_solicitud_fecha_cambio", "microseguro", "motivo_no_aplica",
    "empresa_convenio", "nombre", "cedula",
)


def generar_reporte_mensual(conn, anio, mes, ejecutivo=None):
    """Calcula el Reporte Mensual de Casos para (anio, mes) y, opcionalmente,
    un `ejecutivo` específico (None = todos los agentes).

    Devuelve un dict:
        {
            "desembolsados": [entrada, ...],     # filtrados a (anio, mes)
            "con_microseguro": int,
            "sin_microseguro": int,
            "no_aplica": [entrada, ...],          # filtrados a (anio, mes)
            "cliente_desistio": [entrada, ...],   # filtrados a (anio, mes)
            "pendientes": [entrada, ...],         # SIEMPRE, sin filtrar por mes
        }
    Cada `entrada` es un dict: caso_id, clave_caso, nombre, cedula,
    empresa_convenio, microseguro ("Sí"/"No"/tal cual), motivo_no_aplica,
    fecha (ISO, real del evento — None para Pendientes).
    """
    casos = _seleccionar_casos_para_reporte(conn, ejecutivo)
    creditos_por_cedula = _seleccionar_creditos_por_cedula(conn)

    casos_por_cedula = {}
    for caso in casos:
        casos_por_cedula.setdefault(caso["cedula"], []).append(caso)

    resultado = {
        "desembolsados": [], "con_microseguro": 0, "sin_microseguro": 0,
        "no_aplica": [], "cliente_desistio": [], "pendientes": [],
    }

    for cedula, casos_cliente in casos_por_cedula.items():
        casos_cliente.sort(key=lambda c: c["fecha_registro"] or "")
        creditos_cliente = sorted(
            creditos_por_cedula.get(cedula, []), key=lambda c: c["fecha_desembolso"] or ""
        )

        # Un caso ya cerrado de forma negativa y explícita (No aplica /
        # Cliente desistió) nunca entra a competir por un crédito de
        # Historial — ver _ESTADOS_CERRADOS_SIN_EMPAREJAR arriba. Solo los
        # casos "candidatos" (abiertos, o ya Desembolsada) participan del
        # emparejamiento; así un crédito real nunca se lo termina llevando
        # el caso equivocado de la misma persona.
        candidatos = [
            caso for caso in casos_cliente
            if caso["estado_solicitud"] not in _ESTADOS_CERRADOS_SIN_EMPAREJAR
        ]
        cerrados_sin_emparejar = [
            caso for caso in casos_cliente
            if caso["estado_solicitud"] in _ESTADOS_CERRADOS_SIN_EMPAREJAR
        ]

        emparejados = _emparejar_creditos(candidatos, creditos_cliente)

        for caso in candidatos:
            credito = emparejados.get(caso["id"])
            if credito is not None:
                _clasificar_con_credito(resultado, caso, credito, anio, mes)
            else:
                _clasificar_sin_credito(resultado, caso, anio, mes)

        for caso in cerrados_sin_emparejar:
            _clasificar_sin_credito(resultado, caso, anio, mes)

    # Total de casos REGISTRADOS ese mes (por fecha_registro) — pedido
    # explícito del usuario: "cuántos casos hice en el mes", sin importar si
    # ya se resolvieron o siguen pendientes. Independiente de las categorías
    # de arriba (que clasifican por cuándo se RESOLVIÓ el caso, no por
    # cuándo se registró) — un caso puede contarse acá y, si todavía no se
    # resuelve, no aparecer en ninguna de las otras categorías este mes.
    resultado["total_registrados"] = sum(
        1 for caso in casos if _mes_de_fecha(caso["fecha_registro"]) == (anio, mes)
    )

    return resultado


def _emparejar_creditos(casos_cliente, creditos_cliente):
    """casos_cliente: casos de UN cliente, orden ascendente por fecha_registro.
    creditos_cliente: filas de reporte_credito de esa misma cédula, orden
    ascendente por fecha_desembolso.

    Empareja cada caso con el crédito de fecha_desembolso más próxima que sea
    >= su fecha_registro (nunca uno anterior) y que no se le haya asignado ya
    a un caso anterior del mismo cliente. Devuelve {caso_id: fila_credito_o_None}."""
    resultado = {}
    disponibles = list(creditos_cliente)
    for caso in casos_cliente:
        fecha_registro = caso["fecha_registro"]
        candidato = None
        if fecha_registro:
            for credito in disponibles:
                if credito["fecha_desembolso"] and credito["fecha_desembolso"] >= fecha_registro:
                    candidato = credito
                    break
        resultado[caso["id"]] = candidato
        if candidato is not None:
            disponibles.remove(candidato)
    return resultado


def _clasificar_con_credito(resultado, caso, credito, anio, mes):
    fecha = credito["fecha_desembolso"]
    if _mes_de_fecha(fecha) == (anio, mes):
        _agregar_desembolsado(resultado, caso, fecha)


def _clasificar_sin_credito(resultado, caso, anio, mes):
    estado = caso["estado_solicitud"]
    fecha = caso["estado_solicitud_fecha_cambio"]

    if estado == ESTADO_DESEMBOLSADA:
        if _mes_de_fecha(fecha) == (anio, mes):
            _agregar_desembolsado(resultado, caso, fecha)
        return

    if estado == ESTADO_NO_APLICA:
        if _mes_de_fecha(fecha) == (anio, mes):
            resultado["no_aplica"].append(_entrada(caso, fecha))
        return

    if estado == ESTADO_CLIENTE_DESISTIO:
        if _mes_de_fecha(fecha) == (anio, mes):
            resultado["cliente_desistio"].append(_entrada(caso, fecha))
        return

    # Todo lo demás (En espera de constancia, En proceso, Pendiente de
    # información, Devuelta para corrección, o cualquier valor no
    # reconocido) es Pendiente — vista siempre viva, sin filtrar por mes.
    resultado["pendientes"].append(_entrada(caso, None))


def _agregar_desembolsado(resultado, caso, fecha):
    resultado["desembolsados"].append(_entrada(caso, fecha))
    if formatear_microseguro(caso["microseguro"]) == "Sí":
        resultado["con_microseguro"] += 1
    else:
        resultado["sin_microseguro"] += 1


def _entrada(caso, fecha):
    return {
        "caso_id": caso["id"],
        "clave_caso": caso["clave_caso"],
        "nombre": caso["nombre"],
        "cedula": caso["cedula"],
        "empresa_convenio": caso["empresa_convenio"],
        "microseguro": formatear_microseguro(caso["microseguro"]),
        "motivo_no_aplica": caso["motivo_no_aplica"],
        "fecha": fecha,
    }


def _mes_de_fecha(fecha_iso):
    """'AAAA-MM-DD...' -> (año, mes) como enteros, o None si no se puede
    interpretar (fecha vacía o con un formato inesperado)."""
    if not fecha_iso or len(fecha_iso) < 7:
        return None
    try:
        return int(fecha_iso[0:4]), int(fecha_iso[5:7])
    except ValueError:
        return None


def _seleccionar_casos_para_reporte(conn, ejecutivo):
    query = """
        SELECT caso.id, caso.clave_caso, caso.fecha_registro, caso.estado_solicitud,
               caso.estado_solicitud_fecha_cambio, caso.microseguro, caso.motivo_no_aplica,
               caso.empresa_convenio, cliente.nombre, cliente.cedula
        FROM caso
        JOIN cliente ON cliente.id = caso.cliente_id
        {where}
    """
    if ejecutivo:
        filas = conn.execute(query.format(where="WHERE caso.ejecutivo = ?"), (ejecutivo,)).fetchall()
    else:
        filas = conn.execute(query.format(where="")).fetchall()

    return [dict(zip(_COLUMNAS_CASO, fila)) for fila in filas]


def _seleccionar_creditos_por_cedula(conn):
    """Todos los créditos con fecha_desembolso conocida, agrupados por
    cédula — sin filtrar por ejecutivo (reporte_credito no tiene esa
    columna, no depende de qué agente lleva el caso en Casos)."""
    filas = conn.execute(
        "SELECT cedula, fecha_desembolso FROM reporte_credito WHERE fecha_desembolso IS NOT NULL"
    ).fetchall()

    agrupado = {}
    for cedula, fecha_desembolso in filas:
        agrupado.setdefault(cedula, []).append({"fecha_desembolso": fecha_desembolso})
    return agrupado
