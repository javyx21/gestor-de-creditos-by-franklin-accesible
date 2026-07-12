# Tasas y bandas de ley (INSS laboral e IR sobre rentas del trabajo,
# Nicaragua). Van en constantes con nombre, no metidas directo en las
# fórmulas, porque son valores que la ley puede cambiar — a diferencia del
# resto de este módulo, que replica la lógica de negocio del Excel de
# referencia (recursos/calculadora.xlsx, hoja Calculadora, B23:B27), estos
# números en concreto conviene revisarlos contra la ley vigente antes de
# confiar en ellos a largo plazo.
TASA_INSS_LABORAL = 0.07

# (límite superior de la banda anual en Córdobas, tasa marginal de la banda)
# Primera banda (hasta 100,000) está exenta (tasa 0) y no se lista acá.
BANDAS_IR_ANUAL = [
    (200_000, 0.15),
    (350_000, 0.20),
    (500_000, 0.25),
]
LIMITE_EXENTO_IR_ANUAL = 100_000
TASA_IR_MAXIMA = 0.30


def calcular_inss(salario_bruto_mensual):
    """Réplica de Calculadora!B23 (=B7*0.07)."""
    return salario_bruto_mensual * TASA_INSS_LABORAL


def calcular_salario_neto_inss(salario_bruto_mensual):
    """Réplica de Calculadora!B24 (=B7-B23): salario bruto menos INSS,
    ANTES de restar el IR (que se calcula sobre el anualizado, ver abajo)."""
    return salario_bruto_mensual - calcular_inss(salario_bruto_mensual)


def calcular_ir_anual(salario_anual_neto_inss):
    """Réplica de Calculadora!B27: impuesto sobre la renta anual, calculado
    por bandas progresivas sobre el salario ANUAL ya neto de INSS (B26 en
    el Excel = B24*12). Devuelve el IR del año completo — quien llama debe
    dividir entre 12 para el descuento mensual (igual que B25='=B27/12')."""
    if salario_anual_neto_inss <= LIMITE_EXENTO_IR_ANUAL:
        return 0.0

    acumulado = 0.0
    limite_anterior = LIMITE_EXENTO_IR_ANUAL
    for limite, tasa in BANDAS_IR_ANUAL:
        if salario_anual_neto_inss <= limite:
            return acumulado + (salario_anual_neto_inss - limite_anterior) * tasa
        acumulado += (limite - limite_anterior) * tasa
        limite_anterior = limite

    return acumulado + (salario_anual_neto_inss - limite_anterior) * TASA_IR_MAXIMA


def calcular_salario_neto_mensual(salario_bruto_mensual, ingresos_extra=0):
    """Réplica de Calculadora!B9 (=B7-B23-B25+D9): salario bruto menos INSS
    menos la cuota mensual de IR (IR anual / 12), más cualquier ingreso
    adicional/extra declarado (D9 en el Excel — comisiones, otro empleo,
    etc., no tiene deducciones propias)."""
    inss = calcular_inss(salario_bruto_mensual)
    salario_neto_inss = salario_bruto_mensual - inss
    ir_anual = calcular_ir_anual(salario_neto_inss * 12)
    ir_mensual = ir_anual / 12
    return salario_bruto_mensual - inss - ir_mensual + ingresos_extra
