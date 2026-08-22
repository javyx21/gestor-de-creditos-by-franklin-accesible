import pytest

from gestor_credito.db import database
from gestor_credito.db.reporte_creditos import (
    ESTADO_CREDITO_ACTIVO,
    ESTADO_CREDITO_CANCELADO,
    ESTADO_CREDITO_PRORROGADO,
    ESTADO_CREDITO_SANEADO,
    ESTADO_CREDITO_VENCIDO,
    ESTADO_ELEGIBLES_REFINANCIAMIENTO,
    ESTADOS_CREDITO_ALERTA,
    ESTADO_TODOS,
    buscar_creditos,
    obtener_empresas_convenio,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _crear_credito(conn, no_credito, cedula="001-1234567-8", nombre="Juan Perez",
                    estado="Corriente", fecha_desembolso="2026-06-01", **overrides):
    valores = {
        "no_credito": no_credito,
        "cedula": cedula,
        "nombre_cliente": nombre,
        "fecha_desembolso": fecha_desembolso,
        "fecha_vencimiento": "2027-06-01",
        "monto_desembolsado": 1000.0,
        "estado_credito": estado,
        "empresa_convenio": "MIDESA",
        "plazo_credito": 24,
        "numero_cuotas": 24,
        "cuotas_pagadas": 3,
    }
    valores.update(overrides)
    columnas = ", ".join(valores.keys())
    placeholders = ", ".join("?" for _ in valores)
    conn.execute(
        f"INSERT INTO reporte_credito ({columnas}) VALUES ({placeholders})",
        list(valores.values()),
    )
    conn.commit()


def test_estado_activo_es_corriente():
    assert ESTADO_CREDITO_ACTIVO == "Corriente"


def test_vista_por_defecto_solo_muestra_corriente(conn):
    _crear_credito(conn, "C-1", cedula="001", nombre="Ana Lopez", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", nombre="Beto Cruz", estado="Cancelado")
    _crear_credito(conn, "C-3", cedula="003", nombre="Carla Ruiz", estado="Vencido")
    _crear_credito(conn, "C-4", cedula="004", nombre="Dario Vega", estado="Saneado")
    _crear_credito(conn, "C-5", cedula="005", nombre="Elsa Mora", estado="Trámite")

    filas = buscar_creditos(conn)

    no_creditos = [f[1] for f in filas]
    assert no_creditos == ["C-1"]


def test_busqueda_por_cedula_con_estado_activo_por_defecto_no_muestra_cancelados(conn):
    # 2026-08-16: antes, un término de búsqueda ignoraba automáticamente el
    # filtro de estado para mostrar todo el historial del cliente. Eso quedó
    # reemplazado por el selector "Estado" explícito del panel — buscar_creditos()
    # ahora respeta su valor por defecto (ESTADO_CREDITO_ACTIVO) igual con o
    # sin término de búsqueda. Ver test siguiente para pedir explícitamente
    # el historial completo con ESTADO_TODOS.
    _crear_credito(conn, "C-1", cedula="0012510940057N", estado="Corriente",
                    fecha_desembolso="2026-06-30")
    _crear_credito(conn, "C-2", cedula="0012510940057N", estado="Cancelado",
                    fecha_desembolso="2025-06-16")
    _crear_credito(conn, "C-3", cedula="999", estado="Corriente")

    filas = buscar_creditos(conn, termino="0012510940057N")

    no_creditos = [f[1] for f in filas]
    assert no_creditos == ["C-1"]


def test_busqueda_con_estado_todos_muestra_todo_el_historial_del_cliente(conn):
    _crear_credito(conn, "C-1", cedula="0012510940057N", estado="Corriente",
                    fecha_desembolso="2026-06-30")
    _crear_credito(conn, "C-2", cedula="0012510940057N", estado="Cancelado",
                    fecha_desembolso="2025-06-16")
    _crear_credito(conn, "C-3", cedula="999", estado="Corriente")

    filas = buscar_creditos(conn, termino="0012510940057N", estado=ESTADO_TODOS)

    no_creditos = [f[1] for f in filas]
    assert no_creditos == ["C-1", "C-2"]


def test_cancelados_es_igualdad_simple_no_incluye_finalizado_ni_tramite(conn):
    # Pedido explícito del usuario (2026-08-22): "Cancelados" reemplaza a la
    # vieja "Finalizados (para reenganche)", pero ya NO es la condición
    # compuesta que había antes — solo estado_credito = "Cancelado" literal.
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente",
                    numero_cuotas=24, cuotas_pagadas=3)
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado",
                    numero_cuotas=24, cuotas_pagadas=24)
    _crear_credito(conn, "C-3", cedula="003", estado="Finalizado",
                    numero_cuotas=24, cuotas_pagadas=24)
    _crear_credito(conn, "C-4", cedula="004", estado="Saneado",
                    numero_cuotas=24, cuotas_pagadas=3)

    filas = buscar_creditos(conn, estado=ESTADO_CREDITO_CANCELADO)

    assert [f[1] for f in filas] == ["C-2"]


def test_cancelados_no_incluye_corriente_con_cuotas_completas(conn):
    # Pedido explícito del usuario (2026-08-22), confirmado dos veces: un
    # crédito con cuotas ya completas pero estado_credito todavía "Corriente"
    # NO debe aparecer en "Cancelados" — "si el sistema dice que está
    # activo, eso está prohibido" tratarlo distinto. Ese caso vive aparte
    # (ver CreditosPanel._es_caso_especial_activo_con_cuotas_completas), acá
    # solo se confirma que buscar_creditos() no lo cuela por accidente.
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=24)

    assert buscar_creditos(conn, estado=ESTADO_CREDITO_CANCELADO) == []


def test_cancelados_ordena_por_fecha_ultimo_pago_principal_mas_reciente_primero(conn):
    # Pedido explícito del usuario (2026-08-22): el que pagó por última vez
    # más recientemente va primero. NO se usa estado_credito_fecha_cambio —
    # bug real encontrado el mismo día: en una base recién importada esa
    # columna guarda cuándo el import detectó el estado, no cuándo se
    # canceló de verdad.
    _crear_credito(conn, "C-1", estado="Cancelado", fecha_desembolso="2020-01-01",
                    fecha_ultimo_pago_principal="2026-08-01")
    _crear_credito(conn, "C-2", estado="Cancelado", fecha_desembolso="2026-01-01",
                    fecha_ultimo_pago_principal="2026-08-10")

    filas = buscar_creditos(conn, estado=ESTADO_CREDITO_CANCELADO)

    assert [f[1] for f in filas] == ["C-2", "C-1"]


def test_cancelados_sin_fecha_ultimo_pago_queda_al_final(conn):
    # Confirmado con datos reales (2026-08-22): 64 de 2,997 créditos
    # "Cancelado" reales no traen esta fecha (créditos completos, saldo en
    # cero, dato simplemente no cargado por MIDESA) — SQLite ya los deja al
    # final en DESC por defecto, sin lógica aparte.
    _crear_credito(conn, "C-1", estado="Cancelado", fecha_ultimo_pago_principal=None)
    _crear_credito(conn, "C-2", estado="Cancelado", fecha_ultimo_pago_principal="2026-08-01")

    filas = buscar_creditos(conn, estado=ESTADO_CREDITO_CANCELADO)

    assert [f[1] for f in filas] == ["C-2", "C-1"]


def test_filtro_por_empresa(conn):
    _crear_credito(conn, "C-1", empresa_convenio="AGROSACO")
    _crear_credito(conn, "C-2", cedula="002", empresa_convenio="IMMSA")

    filas = buscar_creditos(conn, empresa="AGROSACO")

    assert [f[1] for f in filas] == ["C-1"]


def test_obtener_empresas_convenio_solo_lista_las_del_reporte(conn):
    # Pedido explícito del usuario (2026-08-16): "evitando listar todas las
    # empresas globalmente" — no debe salir del catálogo convenio_tasa
    # (29 empresas sembradas por init_db), solo las que de verdad tienen un
    # crédito en reporte_credito.
    _crear_credito(conn, "C-1", empresa_convenio="AGROSACO")
    _crear_credito(conn, "C-2", cedula="002", empresa_convenio="IMMSA")
    _crear_credito(conn, "C-3", cedula="003", empresa_convenio="AGROSACO")

    assert obtener_empresas_convenio(conn) == ["AGROSACO", "IMMSA"]


def test_filtros_se_combinan_con_busqueda(conn):
    _crear_credito(conn, "C-1", cedula="001", nombre="Ana Lopez", empresa_convenio="AGROSACO")
    _crear_credito(conn, "C-2", cedula="001", nombre="Ana Lopez", empresa_convenio="IMMSA")
    _crear_credito(conn, "C-3", cedula="002", nombre="Beto Cruz", empresa_convenio="AGROSACO")

    filas = buscar_creditos(conn, termino="Ana Lopez", empresa="AGROSACO")

    assert [f[1] for f in filas] == ["C-1"]


def test_busqueda_por_cedula_es_parcial(conn):
    _crear_credito(conn, "C-1", cedula="0012510940057N")

    filas = buscar_creditos(conn, termino="2510940057")
    assert [f[1] for f in filas] == ["C-1"]


def test_busqueda_por_cedula_es_insensible_a_mayusculas(conn):
    # Mismo reporte real del usuario (2026-07-12) que en Casos: una cédula
    # con sufijo de letra en mayúscula no se encontraba en minúscula.
    _crear_credito(conn, "C-1", cedula="0012510940057N")

    filas = buscar_creditos(conn, termino="0012510940057n")
    assert [f[1] for f in filas] == ["C-1"]


def test_busqueda_por_nombre_es_insensible_a_mayusculas_y_parcial(conn):
    _crear_credito(conn, "C-1", nombre="Karla Vanessa Cortez Selva")

    filas = buscar_creditos(conn, termino="vanessa")
    assert [f[1] for f in filas] == ["C-1"]


def test_busqueda_por_nombre_no_tolera_tildes_incorrectas(conn):
    _crear_credito(conn, "C-1", nombre="PEÑA")

    assert buscar_creditos(conn, termino="PENA") == []
    assert [f[1] for f in buscar_creditos(conn, termino="PEÑA")] == ["C-1"]


def test_termino_invalido_propaga_error(conn):
    with pytest.raises(ValueError):
        buscar_creditos(conn, termino="#$%")


def test_historial_ordenado_del_mas_reciente_al_mas_antiguo(conn):
    _crear_credito(conn, "C-1", cedula="001", nombre="Karla Cortez", fecha_desembolso="2024-01-01")
    _crear_credito(conn, "C-2", cedula="001", nombre="Karla Cortez", fecha_desembolso="2026-06-30")
    _crear_credito(conn, "C-3", cedula="001", nombre="Karla Cortez", fecha_desembolso="2025-03-15")

    filas = buscar_creditos(conn, termino="001")
    assert [f[1] for f in filas] == ["C-2", "C-3", "C-1"]


def test_no_credito_es_unico_reimportar_actualiza_no_duplica(conn):
    _crear_credito(conn, "C-1", estado="Corriente")
    with pytest.raises(Exception):
        # UNIQUE(no_credito): un INSERT directo duplicado debe fallar a nivel
        # de esquema (la lógica real de upsert vive en el importador, no acá).
        _crear_credito(conn, "C-1", estado="Cancelado")


# ---- Prorrogado, sexto estado real descubierto (2026-08-21) --------------

def test_prorrogado_esta_en_estados_credito_alerta():
    assert ESTADO_CREDITO_PRORROGADO == "Prorrogado"
    assert ESTADOS_CREDITO_ALERTA == (
        ESTADO_CREDITO_VENCIDO, ESTADO_CREDITO_SANEADO, ESTADO_CREDITO_PRORROGADO,
    )


# ---- ESTADO_ELEGIBLES_REFINANCIAMIENTO (pedido explícito del usuario, ----
# ---- 2026-08-21) -----------------------------------------------------------

def _credito_elegible(conn, no_credito, **overrides):
    """Crédito que por defecto pasa todas las reglas de elegibilidad: 50%
    de avance por dinero, cuotas coherentes (12/24 = 50% también, dentro de
    la tolerancia), sin mora, activo en la empresa convenio."""
    valores = dict(
        estado="Corriente", monto_desembolsado=1000.0, saldo_principal=450.0,
        saldo_intereses=50.0, numero_cuotas=24, cuotas_pagadas=12, plazo_credito=24,
        dias_en_mora=0, es_convenio="S",
    )
    valores.update(overrides)
    _crear_credito(conn, no_credito, **valores)


def test_elegibles_refinanciamiento_incluye_credito_que_cumple_todo(conn):
    _credito_elegible(conn, "C-1")

    filas = buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO)

    assert [f[1] for f in filas] == ["C-1"]


@pytest.mark.parametrize("estado_malo", ["Vencido", "Saneado", "Prorrogado", "Cancelado"])
def test_elegibles_refinanciamiento_excluye_estados_no_elegibles(conn, estado_malo):
    _credito_elegible(conn, "C-1", estado=estado_malo)

    assert buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO) == []


def test_elegibles_refinanciamiento_excluye_mora_real_aunque_diga_corriente(conn):
    _credito_elegible(conn, "C-1", dias_en_mora=10)

    assert buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO) == []


def test_elegibles_refinanciamiento_excluye_no_activo_en_convenio(conn):
    _credito_elegible(conn, "C-1", es_convenio="N")

    assert buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO) == []


def test_elegibles_refinanciamiento_excluye_avance_menor_a_50_por_ciento(conn):
    # Saldo 800 de 1000 -> solo 20% de avance.
    _credito_elegible(conn, "C-1", saldo_principal=750.0, saldo_intereses=50.0,
                       cuotas_pagadas=5)

    assert buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO) == []


def test_elegibles_refinanciamiento_excluye_avance_inconsistente(conn):
    # Dinero: 50%. Cuotas: 1/24 = ~4% -> diferencia muy por encima de la
    # tolerancia, no se adivina cuál creerle.
    _credito_elegible(conn, "C-1", cuotas_pagadas=1)

    assert buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO) == []


def test_elegibles_refinanciamiento_permite_credito_ya_refinanciado_antes(conn):
    # Pedido explícito del usuario: un crédito ya refinanciado antes puede
    # volver a calificar — no hay ninguna columna de "ya refinanciado" que
    # lo excluya acá. Saldo 200 de 1000 (80% avance por dinero) y 20/24
    # cuotas pagadas (~83.3%, dentro de la tolerancia de 15 puntos).
    _credito_elegible(conn, "C-1", saldo_principal=150.0, saldo_intereses=50.0,
                       cuotas_pagadas=20)

    filas = buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO)
    assert [f[1] for f in filas] == ["C-1"]


def test_elegibles_refinanciamiento_se_combina_con_busqueda(conn):
    _credito_elegible(conn, "C-1", cedula="001", nombre="Ana Lopez")
    _credito_elegible(conn, "C-2", cedula="002", nombre="Beto Cruz")

    filas = buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO, termino="Ana Lopez")

    assert [f[1] for f in filas] == ["C-1"]


def test_elegibles_refinanciamiento_ordena_por_avance_descendente(conn):
    # Pedido explícito del usuario (2026-08-22): el que le falta menos por
    # pagar (mayor % de avance) va primero, hasta llegar a los que están
    # justo en el umbral (50%).
    _credito_elegible(conn, "C-1", saldo_principal=450.0, saldo_intereses=50.0,
                       cuotas_pagadas=12)  # 50% avance (el umbral, al final)
    _credito_elegible(conn, "C-2", cedula="002", saldo_principal=50.0, saldo_intereses=0.0,
                       cuotas_pagadas=23)  # 95% avance (casi listo, primero)
    _credito_elegible(conn, "C-3", cedula="003", saldo_principal=250.0, saldo_intereses=50.0,
                       cuotas_pagadas=18)  # 70% avance (en el medio)

    filas = buscar_creditos(conn, estado=ESTADO_ELEGIBLES_REFINANCIAMIENTO)

    assert [f[1] for f in filas] == ["C-2", "C-3", "C-1"]


def test_todos_los_estados_mantiene_el_orden_por_fecha_de_desembolso(conn):
    # Pedido explícito del usuario (2026-08-22): "donde me muestra todos los
    # créditos tiene que mantener el orden original, que va por fecha de
    # desembolso" — sin cambios acá, a diferencia de Elegibles/Cancelados.
    _crear_credito(conn, "C-1", fecha_desembolso="2024-01-01")
    _crear_credito(conn, "C-2", cedula="002", fecha_desembolso="2026-06-30")
    _crear_credito(conn, "C-3", cedula="003", fecha_desembolso="2025-03-15")

    filas = buscar_creditos(conn, estado=ESTADO_TODOS)

    assert [f[1] for f in filas] == ["C-2", "C-3", "C-1"]
