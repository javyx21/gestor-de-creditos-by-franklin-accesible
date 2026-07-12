import calendar
from datetime import date, timedelta

# Únicas dos periodicidades habilitadas en el Excel de referencia
# (recursos/calculadora.xlsx, validación de datos de Calculadora!B13: lista
# "Mensual,Quincenal") — la hoja "Calculo Plan de pago" internamente sabe de
# más periodicidades (Semanal, Bimensual, etc., tabla AF11:AG18) pero nunca
# están habilitadas para elegir, así que no se replican acá: no hay forma de
# verificarlas contra un caso real y agregarlas sin verificación sería
# replicar fórmulas a ciegas, justo lo que se pidió evitar.
PERIODICIDAD_MENSUAL = "Mensual"
PERIODICIDAD_QUINCENAL = "Quincenal"
PERIODICIDADES_VALIDAS = (PERIODICIDAD_MENSUAL, PERIODICIDAD_QUINCENAL)


def _ultimo_dia_del_mes(anio, mes):
    return calendar.monthrange(anio, mes)[1]


def _edate(fecha, meses):
    """Réplica de Excel EDATE(fecha, meses): mismo día del mes, `meses`
    meses después (o antes, si es negativo); si el mes destino tiene menos
    días que `fecha.day`, se recorta al último día de ese mes (mismo
    comportamiento de Excel, p. ej. EDATE(31-ene, 1) = 28-feb)."""
    total_meses = fecha.month - 1 + meses
    anio = fecha.year + total_meses // 12
    mes = total_meses % 12 + 1
    dia = min(fecha.day, _ultimo_dia_del_mes(anio, mes))
    return date(anio, mes, dia)


def _es_domingo(fecha):
    return fecha.weekday() == 6


def primera_fecha_pago(fecha_desembolso, periodicidad):
    """Réplica de Calculadora!B17: la primera cuota NO usa la lógica de
    "mismo día del mes" de las siguientes (ver siguiente_fecha_pago) — es
    simplemente desembolso + 30 días corridos (Mensual) o +15 (Quincenal),
    sin ajuste de domingo. El día de esta fecha es el que ancla todas las
    fechas mensuales siguientes (ver `dia_referencia` abajo)."""
    if periodicidad == PERIODICIDAD_MENSUAL:
        return fecha_desembolso + timedelta(days=30)
    if periodicidad == PERIODICIDAD_QUINCENAL:
        return fecha_desembolso + timedelta(days=15)
    raise ValueError(f"Periodicidad no soportada: {periodicidad!r}")


def siguiente_fecha_pago(fecha_anterior, periodicidad, dia_referencia):
    """Réplica de 'Calculo Plan de pago'!B13 (y las filas siguientes de esa
    misma columna): calcula la fecha de la próxima cuota a partir de la
    fecha de la cuota anterior.

    `dia_referencia` es el día del mes de la PRIMERA cuota del préstamo
    (J7='=DAY(J5)' en el Excel) — es el ancla que todas las cuotas
    mensuales intentan mantener.

    Quincenal: +15 días corridos; si esa fecha cae domingo, +16 en su lugar
    (corre al lunes).

    Mensual: EDATE (mismo día del mes) un mes adelante; si esa fecha cae
    domingo, se corre un día (al lunes). Truco no obvio, verificado contra
    un cronograma real de 24 cuotas vía Excel/COM: cuando una cuota fue
    corrida por caer domingo, su día del mes queda en `dia_referencia + 1`
    (p. ej. ancla=10, corrida a 11) — si no se corrigiera, el próximo
    EDATE partiría de ese 11 y el "día ancla" se desplazaría un día para
    siempre. Por eso, si la fecha anterior tiene día = dia_referencia+1, el
    EDATE del próximo mes se calcula desde (fecha_anterior - 1 día) en vez
    de fecha_anterior directamente, devolviendo el ancla a su día original
    antes de avanzar el mes."""
    if periodicidad == PERIODICIDAD_QUINCENAL:
        candidata = fecha_anterior + timedelta(days=15)
        if _es_domingo(candidata):
            return fecha_anterior + timedelta(days=16)
        return candidata

    if periodicidad == PERIODICIDAD_MENSUAL:
        if fecha_anterior.day == dia_referencia + 1:
            candidata = _edate(fecha_anterior - timedelta(days=1), 1)
        else:
            candidata = _edate(fecha_anterior, 1)
        if _es_domingo(candidata):
            return candidata + timedelta(days=1)
        return candidata

    raise ValueError(f"Periodicidad no soportada: {periodicidad!r}")


class CuotaCronograma:
    """Una fila del cronograma: cuota `numero` (1-indexado), con su fecha,
    los días reales transcurridos desde la cuota anterior, y el desglose
    capital/interés/total de esa cuota, más el saldo insoluto después de
    pagarla."""

    __slots__ = ("numero", "fecha", "dias", "capital", "interes", "cuota", "saldo")

    def __init__(self, numero, fecha, dias, capital, interes, cuota, saldo):
        self.numero = numero
        self.fecha = fecha
        self.dias = dias
        self.capital = capital
        self.interes = interes
        self.cuota = cuota
        self.saldo = saldo


def generar_cronograma(principal, tasa_anual, plazo_cuotas, periodicidad, fecha_desembolso):
    """Réplica del sistema "Nivelada" (K3=1) de 'Calculo Plan de pago':
    genera el cronograma completo de `plazo_cuotas` cuotas de monto
    constante (capital+interés), usando días reales de calendario entre
    pagos y tasa efectiva por período = días × (tasa_anual/360) — no
    meses/años "de libro", sino el mismo actual/360 que usa el Excel.

    Deliberadamente NO incluye Seguro, Comisión ni Gasto Legal — el Excel
    de referencia los soporta pero están apagados en el caso real
    analizado, y el usuario pidió dejarlos fuera de esta primera versión
    (ver CLAUDE.md). Tampoco soporta los sistemas "Decreciente" ni
    "Vencimiento" (K3=2/3) por la misma razón: no hay un caso real para
    verificarlos todavía.

    La fórmula de la cuota nivelada es la anualidad clásica con factores de
    descuento por período variable (cada período puede tener una cantidad
    distinta de días):

        Cuota = Principal / Σ(t=1..n) [ 1 / Π(k=1..t) (1+E_k) ]

    donde E_k = días_k × (tasa_anual/360). Se llega a esta fórmula
    reconstruyendo a mano el método del Excel (que la resuelve distinto,
    con productos y sumas de columnas auxiliares) y verificando
    numéricamente que ambos métodos dan el mismo resultado, cuota por
    cuota, contra un cronograma real de 24 pagos leído directamente de
    Excel vía COM (ver tests/test_amortizacion.py).
    """
    if periodicidad not in PERIODICIDADES_VALIDAS:
        raise ValueError(f"Periodicidad no soportada: {periodicidad!r}")
    if plazo_cuotas < 1:
        raise ValueError("plazo_cuotas debe ser al menos 1")

    fechas = [primera_fecha_pago(fecha_desembolso, periodicidad)]
    dia_referencia = fechas[0].day
    for _ in range(plazo_cuotas - 1):
        fechas.append(siguiente_fecha_pago(fechas[-1], periodicidad, dia_referencia))

    fecha_anterior = fecha_desembolso
    dias = []
    for fecha in fechas:
        dias.append((fecha - fecha_anterior).days)
        fecha_anterior = fecha

    coeficientes = [d * (tasa_anual / 360) for d in dias]

    # Cuota nivelada: ver fórmula en el docstring.
    factor_acumulado = 1.0
    suma_descuentos = 0.0
    for e in coeficientes:
        factor_acumulado *= 1 + e
        suma_descuentos += 1 / factor_acumulado
    cuota = principal / suma_descuentos

    filas = []
    saldo = principal
    for numero, (fecha, dia_count, e) in enumerate(zip(fechas, dias, coeficientes), start=1):
        interes = e * saldo
        capital = cuota - interes
        saldo -= capital
        filas.append(CuotaCronograma(numero, fecha, dia_count, capital, interes, cuota, saldo))

    return filas


def calcular_cuota(principal, tasa_anual, plazo_cuotas, periodicidad, fecha_desembolso):
    """Atajo cuando solo hace falta el monto de la cuota (Calculadora!B14),
    sin el cronograma completo."""
    cronograma = generar_cronograma(principal, tasa_anual, plazo_cuotas, periodicidad, fecha_desembolso)
    return cronograma[0].cuota
