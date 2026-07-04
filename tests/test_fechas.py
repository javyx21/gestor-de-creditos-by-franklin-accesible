from gestor_credito.ui.fechas import formatear_fecha, parsear_fecha_ui


def test_formatear_fecha_convierte_iso_a_ui():
    assert formatear_fecha("2021-12-23") == "23/12/2021"


def test_formatear_fecha_vacia():
    assert formatear_fecha(None) == ""
    assert formatear_fecha("") == ""


def test_formatear_fecha_valor_no_reconocido_se_devuelve_tal_cual():
    assert formatear_fecha("no es una fecha") == "no es una fecha"


def test_parsear_fecha_ui_convierte_a_iso():
    assert parsear_fecha_ui("23/12/2021") == "2021-12-23"


def test_parsear_fecha_ui_vacia_devuelve_none():
    assert parsear_fecha_ui("") is None
    assert parsear_fecha_ui(None) is None


def test_parsear_fecha_ui_formato_invalido_devuelve_none():
    assert parsear_fecha_ui("2021-12-23") is None
    assert parsear_fecha_ui("32/13/2021") is None
    assert parsear_fecha_ui("no es una fecha") is None


def test_formatear_y_parsear_son_inversas():
    iso = "2026-06-24"
    assert parsear_fecha_ui(formatear_fecha(iso)) == iso
