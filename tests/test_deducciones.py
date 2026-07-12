import json
from pathlib import Path

import pytest

from gestor_credito.calculo.deducciones import (
    calcular_inss,
    calcular_ir_anual,
    calcular_salario_neto_inss,
    calcular_salario_neto_mensual,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _casos():
    data = json.loads((FIXTURES / "golden_cases.json").read_text(encoding="utf-8"))
    for caso in data:
        entrada = caso["entrada"]
        salida = caso["salida"]
        yield pytest.param(
            entrada["salario"],
            entrada["extra"],
            float(salida["inss"]),
            float(salida["salario_neto_inss"]),
            float(salida["ir_anual"]),
            float(salida["salario_neto_total_cordobas"]),
            id=entrada["empresa"],
        )


@pytest.mark.parametrize(
    "salario,extra,inss_esperado,neto_inss_esperado,ir_esperado,neto_total_esperado",
    list(_casos()),
)
def test_deducciones_contra_excel_real(
    salario, extra, inss_esperado, neto_inss_esperado, ir_esperado, neto_total_esperado
):
    assert calcular_inss(salario) == pytest.approx(inss_esperado, abs=0.01)

    neto_inss = calcular_salario_neto_inss(salario)
    assert neto_inss == pytest.approx(neto_inss_esperado, abs=0.01)

    ir_anual = calcular_ir_anual(neto_inss * 12)
    assert ir_anual == pytest.approx(ir_esperado, abs=0.01)

    neto_total = calcular_salario_neto_mensual(salario, extra)
    assert neto_total == pytest.approx(neto_total_esperado, abs=0.01)


def test_ir_exento_bajo_cien_mil():
    assert calcular_ir_anual(100_000) == 0
    assert calcular_ir_anual(99_999) == 0


def test_ir_tasa_maxima_sobre_quinientos_mil():
    # Banda superior a 500,000: 15000+30000+37500 acumulado + 30% del exceso.
    resultado = calcular_ir_anual(600_000)
    assert resultado == pytest.approx(15000 + 30000 + 37500 + 100_000 * 0.30, abs=0.01)
