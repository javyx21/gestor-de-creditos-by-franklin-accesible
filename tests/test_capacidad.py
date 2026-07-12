import json
from datetime import date, datetime
from pathlib import Path

import pytest

from gestor_credito.calculo.capacidad import evaluar_capacidad

FIXTURES = Path(__file__).parent / "fixtures"

# fecha_calculo/fecha_desembolso fijas al día en que se generó el fixture
# (ver recursos/golden_cases.json), no date.today(): tanto Pasivo Laboral
# como el cronograma de pagos dependen de "hoy", así que hay que fijarlo
# para que la comparación contra el Excel real sea determinista.
FECHA_FIJA = date(2026, 7, 11)


def _casos():
    data = json.loads((FIXTURES / "golden_cases.json").read_text(encoding="utf-8"))
    for caso in data:
        yield pytest.param(caso["entrada"], caso["salida"], id=caso["entrada"]["empresa"])


@pytest.mark.parametrize("entrada,esperado", list(_casos()))
def test_evaluar_capacidad_contra_excel_real(entrada, esperado):
    resultado = evaluar_capacidad(
        fecha_ingreso=datetime.fromisoformat(entrada["fecha_ingreso"]).date(),
        salario_bruto_mensual_cordobas=entrada["salario"],
        ingresos_extra_cordobas=entrada["extra"],
        monto_credito_usd=entrada["monto"],
        plazo_meses=entrada["plazo"],
        periodicidad=entrada["periodicidad"],
        tasa_anual=esperado["tasa"],
        tipo_cambio=entrada["tipo_cambio"],
        deuda_activa_cordobas=entrada["deuda"],
        fecha_desembolso=FECHA_FIJA,
        fecha_calculo=FECHA_FIJA,
    )

    assert resultado.pasivo_laboral_cordobas == pytest.approx(
        float(esperado["pasivo_laboral_cordobas"]), abs=0.01
    )
    assert resultado.pasivo_laboral_usd == pytest.approx(esperado["pasivo_laboral_usd"], abs=0.01)
    assert resultado.salario_neto_cordobas == pytest.approx(
        float(esperado["salario_neto_total_cordobas"]), abs=0.01
    )
    assert resultado.cuota_usd == pytest.approx(esperado["cuota_usd"], abs=0.01)
    assert resultado.cuota_cordobas == pytest.approx(
        float(esperado["cuota_cordobas"]), abs=0.01
    )
    assert resultado.cobertura_pasivo_laboral == pytest.approx(
        esperado["cobertura_pasivo"], abs=0.0005
    )
    assert resultado.nivel_endeudamiento == pytest.approx(esperado["endeudamiento"], abs=0.0005)
