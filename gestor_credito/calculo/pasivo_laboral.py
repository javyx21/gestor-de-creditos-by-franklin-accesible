import math
from datetime import date

from gestor_credito.calculo.dias360 import dias360

# Tope legal: la indemnización por antigüedad nunca puede superar 5 meses de
# salario, sin importar cuántos años lleve el colaborador (Código del
# Trabajo de Nicaragua, Arto. 45). Puede cambiar si la ley cambia — no se
# encontró en el Excel de referencia ninguna otra fuente de este número más
# que la constante 5 metida directo en la fórmula de B8.
TOPE_MESES_SALARIO = 5

# Primeros 3 años: 1 mes de salario por año completo. Años adicionales: 20
# de los 30 días de un mes por año (en vez del mes completo). También viene
# directo de la fórmula de B8, sin una celda de configuración aparte.
AÑOS_CON_MES_COMPLETO = 3
FRACCION_MES_AÑOS_ADICIONALES = 20 / 30


def calcular_pasivo_laboral(fecha_ingreso, salario_bruto, fecha_calculo=None):
    """Réplica de Calculadora!B8 del Excel de referencia (recursos/calculadora.xlsx):
    una aproximación de la indemnización por antigüedad nicaragüense (Código
    del Trabajo, Arto. 45) — 1 mes de salario por cada uno de los primeros 3
    años, 20/30 de mes por cada año adicional, con tope de 5 meses de
    salario en total.

    Se replica la fórmula del Excel LITERAL, no una versión "corregida" de
    manual — el negocio ya toma decisiones de crédito con este número tal
    cual sale hoy del Excel, así que la fidelidad bit a bit importa más que
    la elegancia matemática. La fórmula original mezcla INT() de una forma
    un poco particular en el componente de "años adicionales"; se mantiene
    igual aquí a propósito.

    fecha_calculo: por defecto hoy (igual que B18='=TODAY()' en el Excel).
    Devuelve el pasivo laboral en la misma moneda que `salario_bruto` (el
    Excel lo calcula en Córdobas, sobre B7; la conversión a Dólares es
    responsabilidad de quien llama, igual que C8='=B8/C2' en el Excel).
    """
    if fecha_calculo is None:
        fecha_calculo = date.today()

    años = dias360(fecha_ingreso, fecha_calculo) / 360

    if math.floor(años) >= AÑOS_CON_MES_COMPLETO:
        componente_primeros_años = salario_bruto * AÑOS_CON_MES_COMPLETO
    else:
        componente_primeros_años = salario_bruto * años

    if años > AÑOS_CON_MES_COMPLETO:
        meses_equivalentes = (
            math.floor(años - AÑOS_CON_MES_COMPLETO) * 12
            + (años - math.floor(años)) * 12
        )
        tasa_mensual_adicional = (salario_bruto * FRACCION_MES_AÑOS_ADICIONALES) / 12
        componente_años_adicionales = meses_equivalentes * tasa_mensual_adicional
    else:
        componente_años_adicionales = 0

    total = componente_primeros_años + componente_años_adicionales
    tope = salario_bruto * TOPE_MESES_SALARIO

    return min(total, tope)
