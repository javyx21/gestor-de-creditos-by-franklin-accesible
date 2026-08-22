"""Avance de pago y elegibilidad para refinanciamiento, Historial de Créditos
— pedido explícito del usuario (2026-08-21). Pura, sin DB/UI, mismo criterio
que el resto de gestor_credito/calculo/: recibe los números ya extraídos de
reporte_credito y no toca la base de datos ni ningún control de pantalla.

Las cadenas de estado ("Vencido", "Saneado", "Prorrogado", "Cancelado") se
duplican acá en vez de importarlas de db/reporte_creditos.py a propósito —
mantiene este módulo sin ninguna dependencia hacia db/, igual que el resto
de calculo/."""

# Confirmado con el usuario: si el % de avance calculado por dinero (saldo
# vs. monto desembolsado) y por cuotas (cuotas pagadas vs. número de cuotas)
# difieren más que esto, el dato no es confiable — se marca "inconsistente"
# en vez de usar cualquiera de los dos números a ciegas.
TOLERANCIA_PUNTOS_PORCENTUALES = 15

# Confirmado con el usuario: a partir de 50% de avance de pago (o menos de
# 50% restante, dicho al revés) es candidato a refinanciamiento. Sin piso de
# tiempo desde el desembolso — un crédito puede tener plazo tan corto como 3
# meses, así que un mínimo de meses fijo descalificaría casos legítimos.
UMBRAL_ELEGIBLE_REFINANCIAMIENTO = 0.50

# Estados que descalifican de plano para refinanciamiento, sin importar el %
# de avance — confirmado con el usuario: un crédito ya refinanciado antes SÍ
# puede volver a calificar (no está en esta lista), la descalificación es
# solo por el estado actual del crédito.
_ESTADOS_NO_ELEGIBLES_REFINANCIAMIENTO = ("Vencido", "Saneado", "Prorrogado", "Cancelado")


def calcular_avance_pago(saldo_principal, saldo_intereses, monto_desembolsado,
                          cuotas_pagadas, numero_cuotas, plazo_credito):
    """Devuelve (porcentaje_avance, estado) — estado es uno de:

    - "sin_datos": falta saldo_principal, saldo_intereses o monto_desembolsado
      (o este último es <= 0) — no hay nada que calcular, no es una alerta,
      simplemente no aplica todavía para ese crédito.
    - "ok": el % por dinero se pudo calcular y, si había datos de cuotas para
      cruzarlo, ambos caminos coinciden dentro de TOLERANCIA_PUNTOS_PORCENTUALES.
    - "inconsistente": hay datos de ambos caminos pero no coinciden (o el
      chequeo estructural de plazo vs. número de cuotas falla) — pedido
      explícito del usuario: esto NO se resuelve adivinando cuál de los dos
      números confiar, se marca para revisión manual (ver
      CreditosPanel._requiere_revision_manual).

    El % de avance devuelto SIEMPRE es el calculado por dinero (1 − saldo a
    la fecha / monto desembolsado) — es el que el usuario pidió medir
    ("porcentaje... de un monto"); el de cuotas se usa solo para validar,
    nunca se devuelve ni se promedia con el de dinero."""
    if monto_desembolsado is None or monto_desembolsado <= 0:
        return None, "sin_datos"
    if saldo_principal is None or saldo_intereses is None:
        return None, "sin_datos"

    avance_dinero = 1 - ((saldo_principal + saldo_intereses) / monto_desembolsado)

    if cuotas_pagadas is None or numero_cuotas is None or numero_cuotas <= 0:
        # Sin datos de cuotas no hay con qué cruzar — se acepta el dato de
        # dinero solo, no se puede exigir una validación que no tiene con
        # qué hacerse.
        return avance_dinero, "ok"

    # Chequeo estructural: ningún crédito real tiene menos cuotas que meses
    # de plazo (la periodicidad más lenta es una cuota por mes) — si esto no
    # calza, el dato de plazo o de número de cuotas de esa fila es sospechoso
    # y no conviene confiar en el % por cuotas para validar nada.
    if plazo_credito is not None and plazo_credito > 0 and numero_cuotas < plazo_credito:
        return avance_dinero, "inconsistente"

    avance_cuotas = cuotas_pagadas / numero_cuotas
    diferencia_puntos = abs(avance_dinero - avance_cuotas) * 100
    if diferencia_puntos > TOLERANCIA_PUNTOS_PORCENTUALES:
        return avance_dinero, "inconsistente"

    return avance_dinero, "ok"


def es_elegible_refinanciamiento(estado_credito, dias_en_mora, es_convenio,
                                  avance_pago, estado_avance):
    """True si el crédito califica para ofrecer refinanciamiento — pedido
    explícito del usuario (2026-08-21). Descalifica de plano: estado
    Vencido/Saneado/Prorrogado/Cancelado, mora real (dias_en_mora > 0 aunque
    el estado diga Corriente — mismo criterio que la alerta de fila, ver
    CreditosPanel._es_credito_en_alerta), o cliente ya no activo en la
    empresa convenio (es_convenio == 'N'). Si el % de avance no es confiable
    (estado_avance != 'ok'), tampoco califica automáticamente — no se
    adivina, queda para revisión manual."""
    if estado_credito in _ESTADOS_NO_ELEGIBLES_REFINANCIAMIENTO:
        return False
    if dias_en_mora is not None and dias_en_mora > 0:
        return False
    if es_convenio == "N":
        return False
    if estado_avance != "ok" or avance_pago is None:
        return False
    return avance_pago >= UMBRAL_ELEGIBLE_REFINANCIAMIENTO
