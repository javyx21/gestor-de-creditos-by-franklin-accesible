from datetime import datetime

# La base de datos guarda las fechas en formato ISO ("AAAA-MM-DD") porque así
# ordenan y comparan correctamente. Estas funciones son la frontera con la UI:
# convierten esa fecha interna al formato que el usuario pidió ver (DD/MM/AAAA)
# y de vuelta, para los filtros que escribe a mano.

FORMATO_ISO = "%Y-%m-%d"
FORMATO_UI = "%d/%m/%Y"


def formatear_fecha(fecha_iso):
    """'AAAA-MM-DD' -> 'DD/MM/AAAA'. Si no viene en ese formato, se devuelve
    tal cual en vez de fallar (puede ser un valor crudo no reconocido)."""
    if not fecha_iso:
        return ""
    try:
        return datetime.strptime(fecha_iso, FORMATO_ISO).strftime(FORMATO_UI)
    except ValueError:
        return fecha_iso


def parsear_fecha_ui(texto):
    """'DD/MM/AAAA' (como lo escribe el usuario) -> 'AAAA-MM-DD' (formato interno
    usado para comparar contra la base de datos). None si el texto no tiene
    exactamente ese formato."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return datetime.strptime(texto, FORMATO_UI).strftime(FORMATO_ISO)
    except ValueError:
        return None
