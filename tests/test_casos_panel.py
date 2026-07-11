from gestor_credito.db.casos import (
    FILTRO_ALERTA_CONSTANCIA_EN_MANO,
    FILTRO_ALERTA_CONSTANCIA_PENDIENTE,
    FILTRO_ALERTA_DOCUMENTOS_PENDIENTES,
    FILTRO_ALERTA_TODOS,
)
from gestor_credito.ui.casos_panel import CasosPanel


def test_mensaje_cantidad_nombra_el_filtro_documentos_pendientes():
    assert CasosPanel._mensaje_cantidad(7, None, FILTRO_ALERTA_DOCUMENTOS_PENDIENTES) == (
        "7 caso(s) con documentos pendientes"
    )


def test_mensaje_cantidad_nombra_el_filtro_constancia_pendiente():
    assert CasosPanel._mensaje_cantidad(10, None, FILTRO_ALERTA_CONSTANCIA_PENDIENTE) == (
        "10 caso(s) en espera de constancia"
    )


def test_mensaje_cantidad_nombra_el_filtro_constancia_en_mano():
    assert CasosPanel._mensaje_cantidad(3, None, FILTRO_ALERTA_CONSTANCIA_EN_MANO) == (
        "3 caso(s) con constancia en mano sin respuesta"
    )


def test_mensaje_cantidad_generico_sin_filtro():
    assert CasosPanel._mensaje_cantidad(57, None, FILTRO_ALERTA_TODOS) == "57 caso(s) encontrados"


def test_mensaje_cantidad_con_termino_ignora_el_filtro():
    # Un término de búsqueda (cédula/nombre) ignora filtro_alerta (ver
    # buscar_casos en db/casos.py) — el mensaje también debe quedar genérico.
    assert CasosPanel._mensaje_cantidad(2, "armando", FILTRO_ALERTA_DOCUMENTOS_PENDIENTES) == (
        "2 caso(s) encontrados"
    )


def test_mensaje_cantidad_cero_tambien_nombra_el_filtro():
    assert CasosPanel._mensaje_cantidad(0, None, FILTRO_ALERTA_DOCUMENTOS_PENDIENTES) == (
        "0 caso(s) con documentos pendientes"
    )
