from gestor_credito.catalogos import formatear_microseguro


def test_formatear_microseguro_expande_abreviaturas():
    assert formatear_microseguro("S") == "Sí"
    assert formatear_microseguro("N") == "No"


def test_formatear_microseguro_es_insensible_a_mayusculas_y_espacios():
    assert formatear_microseguro("s") == "Sí"
    assert formatear_microseguro(" n ") == "No"


def test_formatear_microseguro_deja_valores_completos_tal_cual():
    assert formatear_microseguro("No aplica") == "No aplica"
    assert formatear_microseguro("Por confirmar") == "Por confirmar"


def test_formatear_microseguro_valor_vacio():
    assert formatear_microseguro(None) == ""
    assert formatear_microseguro("") == ""
