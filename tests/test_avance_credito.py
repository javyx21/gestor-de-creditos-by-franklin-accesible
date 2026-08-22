"""Pruebas de gestor_credito/calculo/avance_credito.py — módulo puro (sin
DB/UI), pedido explícito del usuario (2026-08-21): filtro robusto de
"Próximos a finalizar" / elegibilidad para refinanciamiento en Historial de
Créditos."""

import pytest

from gestor_credito.calculo.avance_credito import (
    TOLERANCIA_PUNTOS_PORCENTUALES,
    UMBRAL_ELEGIBLE_REFINANCIAMIENTO,
    calcular_avance_pago,
    es_elegible_refinanciamiento,
)


# ---- calcular_avance_pago -------------------------------------------------

def test_avance_por_dinero_se_calcula_correctamente():
    # Saldo 500 de un crédito de 1000 -> 50% de avance.
    avance, estado = calcular_avance_pago(
        saldo_principal=400, saldo_intereses=100, monto_desembolsado=1000,
        cuotas_pagadas=12, numero_cuotas=24, plazo_credito=24,
    )
    assert avance == pytest.approx(0.5)
    assert estado == "ok"


def test_sin_monto_desembolsado_es_sin_datos():
    avance, estado = calcular_avance_pago(
        saldo_principal=100, saldo_intereses=10, monto_desembolsado=None,
        cuotas_pagadas=5, numero_cuotas=10, plazo_credito=10,
    )
    assert avance is None
    assert estado == "sin_datos"


def test_monto_desembolsado_cero_es_sin_datos():
    avance, estado = calcular_avance_pago(
        saldo_principal=100, saldo_intereses=10, monto_desembolsado=0,
        cuotas_pagadas=5, numero_cuotas=10, plazo_credito=10,
    )
    assert avance is None
    assert estado == "sin_datos"


def test_sin_saldo_principal_o_intereses_es_sin_datos():
    avance, estado = calcular_avance_pago(
        saldo_principal=None, saldo_intereses=10, monto_desembolsado=1000,
        cuotas_pagadas=5, numero_cuotas=10, plazo_credito=10,
    )
    assert avance is None
    assert estado == "sin_datos"


def test_sin_datos_de_cuotas_acepta_el_avance_por_dinero_solo():
    avance, estado = calcular_avance_pago(
        saldo_principal=200, saldo_intereses=50, monto_desembolsado=1000,
        cuotas_pagadas=None, numero_cuotas=None, plazo_credito=24,
    )
    assert avance == pytest.approx(0.75)
    assert estado == "ok"


def test_avance_por_dinero_y_por_cuotas_coinciden_es_ok():
    # Dinero: 1 - 500/1000 = 50%. Cuotas: 12/24 = 50%. Coinciden exacto.
    avance, estado = calcular_avance_pago(
        saldo_principal=450, saldo_intereses=50, monto_desembolsado=1000,
        cuotas_pagadas=12, numero_cuotas=24, plazo_credito=24,
    )
    assert avance == pytest.approx(0.5)
    assert estado == "ok"


def test_diferencia_dentro_de_la_tolerancia_es_ok():
    # Dinero: 50%. Cuotas: 12/24=50%... probamos justo en el límite (15 pts).
    # Cuotas pagadas 9/24 = 37.5% -> diferencia de 12.5 puntos, dentro de 15.
    avance, estado = calcular_avance_pago(
        saldo_principal=450, saldo_intereses=50, monto_desembolsado=1000,
        cuotas_pagadas=9, numero_cuotas=24, plazo_credito=24,
    )
    assert estado == "ok"


def test_diferencia_fuera_de_la_tolerancia_es_inconsistente():
    # Dinero: 50%. Cuotas: 2/24 = 8.3% -> diferencia de ~41.7 puntos, > 15.
    avance, estado = calcular_avance_pago(
        saldo_principal=450, saldo_intereses=50, monto_desembolsado=1000,
        cuotas_pagadas=2, numero_cuotas=24, plazo_credito=24,
    )
    assert avance == pytest.approx(0.5)  # el avance por dinero se sigue devolviendo
    assert estado == "inconsistente"


def test_numero_cuotas_menor_que_plazo_es_inconsistente():
    # Ninguna periodicidad real da menos de una cuota por mes.
    avance, estado = calcular_avance_pago(
        saldo_principal=400, saldo_intereses=100, monto_desembolsado=1000,
        cuotas_pagadas=5, numero_cuotas=3, plazo_credito=24,
    )
    assert estado == "inconsistente"


def test_tolerancia_es_15_puntos_confirmado_por_el_usuario():
    assert TOLERANCIA_PUNTOS_PORCENTUALES == 15


# ---- es_elegible_refinanciamiento -----------------------------------------

def _elegible(estado_credito="Corriente", dias_en_mora=0, es_convenio="S",
              avance_pago=0.6, estado_avance="ok"):
    return es_elegible_refinanciamiento(
        estado_credito, dias_en_mora, es_convenio, avance_pago, estado_avance,
    )


def test_umbral_es_50_por_ciento_confirmado_por_el_usuario():
    assert UMBRAL_ELEGIBLE_REFINANCIAMIENTO == 0.50


@pytest.mark.parametrize("estado", ["Vencido", "Saneado", "Prorrogado", "Cancelado"])
def test_estados_no_elegibles_descalifican_sin_importar_el_avance(estado):
    assert _elegible(estado_credito=estado, avance_pago=0.99) is False


def test_mora_real_descalifica_aunque_el_estado_diga_corriente():
    assert _elegible(estado_credito="Corriente", dias_en_mora=5, avance_pago=0.99) is False


def test_sin_mora_dias_en_mora_cero_no_descalifica():
    assert _elegible(dias_en_mora=0) is True


def test_es_convenio_n_descalifica():
    assert _elegible(es_convenio="N", avance_pago=0.99) is False


def test_es_convenio_s_no_descalifica():
    assert _elegible(es_convenio="S") is True


def test_avance_no_confiable_no_califica_automatico():
    assert _elegible(estado_avance="inconsistente", avance_pago=0.99) is False
    assert _elegible(estado_avance="sin_datos", avance_pago=None) is False


def test_avance_exactamente_50_por_ciento_si_califica():
    assert _elegible(avance_pago=0.50) is True


def test_avance_menor_a_50_por_ciento_no_califica():
    assert _elegible(avance_pago=0.49) is False


def test_credito_ya_refinanciado_antes_puede_volver_a_calificar():
    # Pedido explícito del usuario (2026-08-21): "claro que sí se puede
    # volver a refinanciar un crédito... siempre y cuando cumpla con la
    # primera regla" — no hay ningún parámetro de "ya refinanciado antes"
    # en la firma de la función a propósito, la elegibilidad no distingue
    # ese historial.
    assert _elegible(avance_pago=0.75) is True
