from dataclasses import dataclass
from datetime import date

from gestor_credito.calculo.amortizacion import (
    PERIODICIDAD_MENSUAL,
    PERIODICIDAD_QUINCENAL,
    calcular_cuota,
)
from gestor_credito.calculo.deducciones import calcular_salario_neto_mensual
from gestor_credito.calculo.pasivo_laboral import calcular_pasivo_laboral

# Calculadora!B14 NO usa la cuota nivelada cruda de 'Calculo Plan de pago'!I12
# tal cual: le suma un margen fijo en Dólares antes de mostrarla/usarla para
# endeudamiento — un $1 extra por cuota si es Quincenal, $2 si es Mensual.
# Este margen NO se propaga al cronograma interno (F12:F108 siguen usando la
# cuota cruda $P$12 sin el +1/+2, ver amortizacion.py). Confirmado con el
# usuario (2026-07-12): es el costo de un servicio de asistencia funeraria,
# US$2 mensuales en total — se cobra completo (+2) si la cuota es Mensual, o
# repartido a mitad (+1) por cuota si es Quincenal, ya que en ese caso hay dos
# cuotas por mes. No es redondeo ni colchón de cobranza; el Excel no lo
# etiqueta en ningún lado, pero el motivo de negocio ya está confirmado.
MARGEN_CUOTA_USD = {
    PERIODICIDAD_QUINCENAL: 1,
    PERIODICIDAD_MENSUAL: 2,
}


def _numero_de_cuotas(plazo_meses, periodicidad):
    """Calculadora!B11 ("Plazo") siempre está en MESES, sin importar la
    periodicidad — 'Calculo Plan de pago'!F4 la convierte a número real de
    cuotas: x2 si es Quincenal (dos pagos por mes), x1 si es Mensual."""
    if periodicidad == PERIODICIDAD_QUINCENAL:
        return plazo_meses * 2
    return plazo_meses


@dataclass
class ResultadoCapacidad:
    """Réplica de los resultados de Calculadora!B8:B19 del Excel de
    referencia. Todo lo monetario en Córdobas también tiene su par en
    Dólares (sufijo _usd), igual que las columnas B/C de esa hoja."""

    pasivo_laboral_cordobas: float
    pasivo_laboral_usd: float
    salario_neto_cordobas: float
    salario_neto_usd: float
    cuota_usd: float
    cuota_cordobas: float
    cobertura_pasivo_laboral: float
    nivel_endeudamiento: float


def evaluar_capacidad(
    *,
    fecha_ingreso,
    salario_bruto_mensual_cordobas,
    ingresos_extra_cordobas,
    monto_credito_usd,
    plazo_meses,
    periodicidad,
    tasa_anual,
    tipo_cambio,
    deuda_activa_cordobas=0,
    fecha_desembolso=None,
    fecha_calculo=None,
):
    """Réplica del panel de resultados de Calculadora (B8 a B19): dado todo
    lo que en el Excel se captura a mano (empresa ya resuelta a `tasa_anual`
    por quien llama, ver db/convenios.py — este módulo no conoce de
    empresas ni tasas por convenio, solo recibe la tasa ya resuelta), calcula
    pasivo laboral, salario neto, cuota, cobertura de pasivo laboral y nivel
    de endeudamiento.

    `monto_credito_usd`: el monto SIEMPRE se maneja en Dólares en esta app
    (a diferencia del Excel, que lo capturaba en B10 ya en USD también, así
    que no hay diferencia real — solo se deja explícito en el nombre del
    parámetro).

    `plazo_meses`: igual que Calculadora!B11 ("Plazo") — SIEMPRE en meses,
    incluso si `periodicidad` es Quincenal (en ese caso el número real de
    cuotas es el doble, ver _numero_de_cuotas()).

    `deuda_activa_cordobas`: cuotas de deudas activas externas del cliente
    (Calculadora!C15), en Córdobas — resta capacidad de pago aunque no sean
    deudas con esta financiera. 0 si no tiene.

    `fecha_desembolso`/`fecha_calculo`: por defecto hoy, igual que
    B21='=TODAY()' y B18='=TODAY()' en el Excel — normalmente solo se pasan
    explícitos en tests, para que el resultado sea determinista.
    """
    if fecha_desembolso is None:
        fecha_desembolso = date.today()
    if fecha_calculo is None:
        fecha_calculo = date.today()

    pasivo_laboral_cordobas = calcular_pasivo_laboral(
        fecha_ingreso, salario_bruto_mensual_cordobas, fecha_calculo
    )
    pasivo_laboral_usd = pasivo_laboral_cordobas / tipo_cambio

    salario_neto_cordobas = calcular_salario_neto_mensual(
        salario_bruto_mensual_cordobas, ingresos_extra_cordobas
    )
    salario_neto_usd = salario_neto_cordobas / tipo_cambio

    numero_cuotas = _numero_de_cuotas(plazo_meses, periodicidad)
    cuota_cruda_usd = calcular_cuota(
        monto_credito_usd, tasa_anual, numero_cuotas, periodicidad, fecha_desembolso
    )
    cuota_usd = cuota_cruda_usd + MARGEN_CUOTA_USD[periodicidad]
    cuota_cordobas = cuota_usd * tipo_cambio

    cobertura_pasivo_laboral = monto_credito_usd / pasivo_laboral_usd

    cuota_mensual_equivalente_usd = (
        cuota_usd * 2 if periodicidad == PERIODICIDAD_QUINCENAL else cuota_usd
    )
    deuda_activa_usd = deuda_activa_cordobas / tipo_cambio
    nivel_endeudamiento = (
        cuota_mensual_equivalente_usd + deuda_activa_usd
    ) / salario_neto_usd

    return ResultadoCapacidad(
        pasivo_laboral_cordobas=pasivo_laboral_cordobas,
        pasivo_laboral_usd=pasivo_laboral_usd,
        salario_neto_cordobas=salario_neto_cordobas,
        salario_neto_usd=salario_neto_usd,
        cuota_usd=cuota_usd,
        cuota_cordobas=cuota_cordobas,
        cobertura_pasivo_laboral=cobertura_pasivo_laboral,
        nivel_endeudamiento=nivel_endeudamiento,
    )
