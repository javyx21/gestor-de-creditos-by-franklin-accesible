import json
from datetime import date, datetime
from pathlib import Path

import pytest

from gestor_credito.calculo.pasivo_laboral import calcular_pasivo_laboral

FIXTURES = Path(__file__).parent / "fixtures"


def _casos():
    data = json.loads((FIXTURES / "golden_cases.json").read_text(encoding="utf-8"))
    for caso in data:
        entrada = caso["entrada"]
        salida = caso["salida"]
        yield pytest.param(
            datetime.fromisoformat(entrada["fecha_ingreso"]).date(),
            entrada["salario"],
            float(salida["pasivo_laboral_cordobas"]),
            id=entrada["empresa"],
        )


@pytest.mark.parametrize("fecha_ingreso,salario,esperado", list(_casos()))
def test_pasivo_laboral_contra_excel_real(fecha_ingreso, salario, esperado):
    # Los 4 casos se calcularon con fecha_calculo = hoy en el momento en que
    # se generó el fixture (ver recursos/golden_cases.json) — se fija acá
    # el mismo valor para que la comparación sea determinista sin importar
    # cuándo corra el test.
    fecha_calculo = date(2026, 7, 11)
    resultado = calcular_pasivo_laboral(fecha_ingreso, salario, fecha_calculo)
    assert resultado == pytest.approx(esperado, abs=0.01)


def test_tope_de_cinco_meses_de_salario():
    # Colaborador con 20 años de antigüedad: sin tope, el cálculo daría muy
    # por encima de 5 meses de salario.
    resultado = calcular_pasivo_laboral(date(2006, 1, 1), 10000, date(2026, 1, 1))
    assert resultado == pytest.approx(50000, abs=0.01)


def test_menos_de_un_anio_es_proporcional():
    # A los 6 meses (mitad de año), el pasivo laboral debe ser ~medio mes
    # de salario, no un mes completo.
    resultado = calcular_pasivo_laboral(date(2026, 1, 1), 10000, date(2026, 7, 1))
    assert resultado == pytest.approx(5000, abs=50)
