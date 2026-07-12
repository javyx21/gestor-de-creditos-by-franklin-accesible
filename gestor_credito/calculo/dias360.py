from datetime import date, timedelta


def _es_ultimo_dia_de_febrero(fecha):
    return fecha.month == 2 and (fecha + timedelta(days=1)).month == 3


def dias360(inicio, fin):
    """Réplica de Excel DAYS360(inicio, fin) en su método por defecto (US/NASD,
    method=FALSE) — NO la variante europea (30E/360). Se usa para "Pasivo
    Laboral" (ver calculo/pasivo_laboral.py), que en el Excel original llama
    a DAYS360(fecha_ingreso, fecha_cálculo) sin tercer argumento.

    No hay una función DAYS360 en la librería estándar de Python, así que se
    reconstruyó a mano. La regla NASD tiene dos ajustes:
      1. Si el día de `inicio` es 31, o `inicio` cae en el último día de
         febrero (28 o 29 según el año), se trata como si fuera día 30.
      2. Si el día de `fin` es 31 Y el de `inicio` (ya ajustado por la regla
         1) es 30, `fin` también se trata como día 30.
    Documentado así por Microsoft, pero se verificó empíricamente contra un
    Excel real (COM, no solo la documentación) con 11 pares de fechas
    cubriendo los casos borde (31, fin de febrero en año bisiesto y no
    bisiesto, doble 31, etc.) antes de confiar en esta implementación — ver
    los casos en tests/test_dias360.py, tomados 1:1 de esa verificación.
    """
    d1, m1, y1 = inicio.day, inicio.month, inicio.year
    d2, m2, y2 = fin.day, fin.month, fin.year

    if d1 == 31 or _es_ultimo_dia_de_febrero(inicio):
        d1 = 30
    if d2 == 31 and d1 == 30:
        d2 = 30

    return (y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1)
