"""Catálogos de valores fijos, tomados de la hoja 02_Catalogos de la plantilla
real de MIDESA (MachoteBaseDeDatos.xlsx). Son los únicos valores válidos para
estos campos — usarlos para poblar cualquier control de selección cerrada."""

ESTADOS_SOLICITUD = [
    "En espera de constancia",
    "En proceso",
    "Desembolsada",
    "No aplica",
    "Cliente desistió",
    "Pendiente de información",
    "Devuelta para corrección",
]

ETAPAS_PROCESO = [
    "Pre-solicitud",
    "Completar expediente / requisitos",
    "Solicitud formal",
    "Aprobación",
    "Formalización",
    "Desembolso",
    "Cierre",
]

ESTADO_EN_ESPERA_CONSTANCIA = ESTADOS_SOLICITUD[0]
ESTADO_DESEMBOLSADA = ESTADOS_SOLICITUD[2]

# El catálogo oficial de Microseguro usa palabras completas (Sí/No/No aplica/Por
# confirmar), pero la bitácora real trae abreviaturas de una letra ("S"/"N") para
# Sí/No. Esto expande esas abreviaturas para mostrar en la UI; cualquier otro
# valor (ya completo, vacío, u otra variante del catálogo) se deja tal cual.
_MICROSEGURO_ABREVIADO = {"S": "Sí", "N": "No"}


def formatear_microseguro(valor):
    if not valor:
        return valor or ""
    return _MICROSEGURO_ABREVIADO.get(valor.strip().upper(), valor)
