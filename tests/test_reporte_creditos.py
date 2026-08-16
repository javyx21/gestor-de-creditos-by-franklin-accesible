import pytest

from gestor_credito.db import database
from gestor_credito.db.reporte_creditos import (
    ESTADO_CREDITO_ACTIVO,
    ESTADO_CREDITO_FINALIZADO,
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


def test_vista_finalizados_incluye_cancelado_y_finalizado(conn):
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente",
                    numero_cuotas=24, cuotas_pagadas=3)
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado",
                    numero_cuotas=24, cuotas_pagadas=24)
    _crear_credito(conn, "C-3", cedula="003", estado="Finalizado",
                    numero_cuotas=24, cuotas_pagadas=24)
    _crear_credito(conn, "C-4", cedula="004", estado="Saneado",
                    numero_cuotas=24, cuotas_pagadas=3)

    filas = buscar_creditos(conn, estado=ESTADO_CREDITO_FINALIZADO)

    assert sorted(f[1] for f in filas) == ["C-2", "C-3"]


def test_vista_finalizados_incluye_cuotas_pendientes_cero_aunque_el_estado_no_diga_cancelado(conn):
    # Reporte real (2026-08-16): 22 créditos verificados en recursos/reporte.xlsx
    # ya tienen cuotas_pagadas >= numero_cuotas pero su estado_credito todavía
    # dice "Trámite" (el sistema de origen no actualizó el estado) — sin esta
    # condición, esos clientes ya terminaron de pagar pero quedarían invisibles
    # para una campaña de reenganche.
    _crear_credito(conn, "C-1", estado="Trámite", numero_cuotas=24, cuotas_pagadas=24)
    _crear_credito(conn, "C-2", cedula="002", estado="Trámite",
                    numero_cuotas=24, cuotas_pagadas=3)

    filas = buscar_creditos(conn, estado=ESTADO_CREDITO_FINALIZADO)

    assert [f[1] for f in filas] == ["C-1"]


def test_vista_finalizados_no_incluye_filas_sin_numero_cuotas_ni_estado_cerrado(conn):
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=None, cuotas_pagadas=None)

    assert buscar_creditos(conn, estado=ESTADO_CREDITO_FINALIZADO) == []


def test_vista_finalizados_ordena_por_estado_credito_fecha_cambio_mas_reciente_primero(conn):
    # "Finalizados recientemente" (pedido explícito del usuario, 2026-08-16,
    # campañas de reenganche) se ordena por CUÁNDO se detectó el cierre
    # (estado_credito_fecha_cambio), no por fecha_desembolso (que es la fecha
    # de inicio del crédito, no la de su cierre) — un crédito desembolsado
    # hace mucho puede haberse cancelado ayer.
    _crear_credito(conn, "C-1", estado="Cancelado", fecha_desembolso="2020-01-01",
                    estado_credito_fecha_cambio="2026-08-01 00:00:00")
    _crear_credito(conn, "C-2", estado="Cancelado", fecha_desembolso="2026-01-01",
                    estado_credito_fecha_cambio="2026-08-10 00:00:00")

    filas = buscar_creditos(conn, estado=ESTADO_CREDITO_FINALIZADO)

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


def test_filtro_por_cuotas_pendientes_maximo_es_menor_o_igual(conn):
    # "Próximos a finalizar" (pedido explícito del usuario, 2026-08-16 segunda
    # ronda): <=, no coincidencia exacta — sus propios ejemplos fueron "<= 2"
    # y "<= 3".
    _crear_credito(conn, "C-1", numero_cuotas=24, cuotas_pagadas=24)  # 0 pendientes
    _crear_credito(conn, "C-2", cedula="002", numero_cuotas=24, cuotas_pagadas=22)  # 2 pendientes
    _crear_credito(conn, "C-3", cedula="003", numero_cuotas=24, cuotas_pagadas=18)  # 6 pendientes

    filas = buscar_creditos(conn, estado=ESTADO_TODOS, cuotas_pendientes_maximo=2)

    assert sorted(f[1] for f in filas) == ["C-1", "C-2"]


def test_filtro_cuotas_pendientes_maximo_ignora_filas_sin_numero_cuotas(conn):
    _crear_credito(conn, "C-1", numero_cuotas=None, cuotas_pagadas=22)

    assert buscar_creditos(conn, estado=ESTADO_TODOS, cuotas_pendientes_maximo=2) == []


def test_proximos_a_finalizar_es_activos_mas_cuotas_pendientes_maximo(conn):
    # El pedido de negocio ("Próximos a finalizar": estado Activo Y cuotas
    # pendientes <= N) no tiene un parámetro dedicado — es exactamente esta
    # combinación de `estado` (por defecto ESTADO_CREDITO_ACTIVO) y
    # `cuotas_pendientes_maximo` (ver CLAUDE.md).
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=22)  # activo, 2 pend.
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado",
                    numero_cuotas=24, cuotas_pagadas=24)  # finalizado, 0 pend. — no es "activo"
    _crear_credito(conn, "C-3", cedula="003", estado="Corriente",
                    numero_cuotas=24, cuotas_pagadas=18)  # activo, 6 pend. — supera el umbral

    filas = buscar_creditos(conn, cuotas_pendientes_maximo=2)  # estado por defecto: Activos

    assert [f[1] for f in filas] == ["C-1"]


def test_filtros_se_combinan_con_busqueda(conn):
    _crear_credito(conn, "C-1", cedula="001", nombre="Ana Lopez",
                    empresa_convenio="AGROSACO", numero_cuotas=24, cuotas_pagadas=22)
    _crear_credito(conn, "C-2", cedula="001", nombre="Ana Lopez",
                    empresa_convenio="IMMSA", numero_cuotas=24, cuotas_pagadas=22)
    _crear_credito(conn, "C-3", cedula="002", nombre="Beto Cruz",
                    empresa_convenio="AGROSACO", numero_cuotas=24, cuotas_pagadas=22)

    filas = buscar_creditos(
        conn, termino="Ana Lopez", empresa="AGROSACO", cuotas_pendientes_maximo=2
    )

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
