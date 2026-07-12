import json
from datetime import date, datetime
from pathlib import Path

import pytest

from gestor_credito.calculo.amortizacion import calcular_cuota, generar_cronograma

FIXTURES = Path(__file__).parent / "fixtures"

# Cronogramas reales de 'Calculo Plan de pago' (recursos/calculadora.xlsx),
# leídos fila por fila directamente de Excel vía COM — no reconstruidos a
# mano. Cubren Mensual y Quincenal, tasas y plazos distintos, y un caso
# (MIDESA_mensual_24) que atraviesa naturalmente una fecha que cae domingo
# y el consiguiente ajuste de "día ancla" al mes siguiente — ver el
# docstring de siguiente_fecha_pago() en amortizacion.py.
CASOS = [
    ("IMMSA_mensual_12", 1500, 0.36, 12, "Mensual"),
    ("LALA_quincenal_6", 600, 0.45, 12, "Quincenal"),
    ("MIDESA_mensual_24", 3000, 0.18, 24, "Mensual"),
    ("NICAES_quincenal_4", 800, 0.60, 8, "Quincenal"),
]


def _cargar_cronograma_esperado(nombre):
    data = json.loads((FIXTURES / "golden_cronogramas.json").read_text(encoding="utf-8"))
    caso = data[nombre]
    desembolso = datetime.fromisoformat(caso["desembolso"]).date()
    filas = []
    for fila in caso["filas"]:
        filas.append(
            {
                "fecha": datetime.fromisoformat(fila["fecha"]).date(),
                "capital": float(fila["capital"]),
                "interes": float(fila["interes"]),
                "cuota": float(fila["cuota"]),
                "saldo": float(fila["saldo"]),
            }
        )
    return desembolso, filas


@pytest.mark.parametrize("nombre,principal,tasa,plazo,periodicidad", CASOS)
def test_cronograma_contra_excel_real(nombre, principal, tasa, plazo, periodicidad):
    desembolso, esperado = _cargar_cronograma_esperado(nombre)
    cronograma = generar_cronograma(principal, tasa, plazo, periodicidad, desembolso)

    assert len(cronograma) == len(esperado)
    for fila, fila_esperada in zip(cronograma, esperado):
        assert fila.fecha == fila_esperada["fecha"]
        assert fila.capital == pytest.approx(fila_esperada["capital"], abs=1e-6)
        assert fila.interes == pytest.approx(fila_esperada["interes"], abs=1e-6)
        assert fila.cuota == pytest.approx(fila_esperada["cuota"], abs=1e-6)
        assert fila.saldo == pytest.approx(fila_esperada["saldo"], abs=1e-6)


@pytest.mark.parametrize("nombre,principal,tasa,plazo,periodicidad", CASOS)
def test_calcular_cuota_contra_excel_real(nombre, principal, tasa, plazo, periodicidad):
    desembolso, esperado = _cargar_cronograma_esperado(nombre)
    cuota = calcular_cuota(principal, tasa, plazo, periodicidad, desembolso)
    assert cuota == pytest.approx(esperado[0]["cuota"], abs=1e-6)


def test_ultima_cuota_salda_el_saldo():
    cronograma = generar_cronograma(1000, 0.30, 6, "Mensual", date(2026, 1, 15))
    assert cronograma[-1].saldo == pytest.approx(0, abs=1e-6)


def test_periodicidad_invalida():
    with pytest.raises(ValueError):
        generar_cronograma(1000, 0.30, 6, "Semanal", date(2026, 1, 15))
