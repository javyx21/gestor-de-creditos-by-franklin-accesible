"""Pruebas de extremo a extremo del panel "Historial de Créditos"
(CreditosPanel) — construyen el panel real (no mocks) contra una base de
datos temporal, mismo patrón que test_configuracion_panel.py."""

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.ui.creditos_panel import _INDICE_ESTADO_POR_DEFECTO, COLUMNAS, CreditosPanel


@pytest.fixture(scope="module")
def app():
    return wx.App()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _crear_credito(conn, no_credito, cedula="001", nombre="Juan Perez",
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


def _frame_con_status_bar():
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    return frame


@pytest.fixture(autouse=True)
def _sin_hilos(monkeypatch):
    """Corre ejecutar_en_segundo_plano() de forma síncrona en las pruebas —
    2026-08-16, junto con la carga asíncrona de CreditosPanel (ver
    ui/accesibilidad.py). Sin esto, cada carga real (una consulta a SQLite en
    un hilo aparte más wx.CallAfter) necesitaría bombear el bucle de eventos
    de wx y esperar al hilo, algo frágil y lento en una prueba headless sin
    MainLoop. ejecutar_en_segundo_plano() está aislada como función de módulo
    justo para permitir este reemplazo por una versión síncrona."""
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.ejecutar_en_segundo_plano",
        lambda trabajo, callback: callback(trabajo()),
    )


@pytest.fixture
def panel(app, conn):
    frame = _frame_con_status_bar()
    notebook = wx.Notebook(frame)
    panel = CreditosPanel(notebook)
    notebook.AddPage(panel, "Historial de Créditos")
    yield panel
    frame.Destroy()


def _filas_lista(panel, columna):
    return [panel.lista.GetItemText(i, columna) for i in range(panel.lista.GetItemCount())]


def test_nombre_accesible_de_la_lista():
    # No requiere BD/panel real: solo confirma que las columnas están en el
    # orden pedido por el usuario (ver sección 1 del pedido). "Número de
    # Cuotas"/"Cuotas Pagadas"/"Cuotas Pendientes" separadas 2026-08-16 (antes
    # una sola columna "Número de Cuotas" mostraba en realidad cuotas_pagadas).
    assert COLUMNAS == [
        "Fecha Desembolso", "Fecha Vencimiento", "No. Crédito", "Monto Desembolsado",
        "Saldo a la fecha", "Nombre del Cliente", "Identificación", "Empresa Convenio",
        "Estado del Crédito", "Plazo del Crédito", "Número de Cuotas", "Cuotas Pagadas",
        "Cuotas Pendientes",
    ]


def test_vista_por_defecto_muestra_todos_los_estados(panel, conn):
    # Pedido explícito del usuario (2026-08-21): "cuando borremos filtro
    # queden... en general... todos" — el filtro por defecto es "Todos los
    # estados" (único selector que se comporta así hoy — "Activos" ya no
    # tiene su propia entrada en el combo, ver ESTADO_OPCIONES en
    # creditos_panel.py, pedido explícito del usuario 2026-08-22).
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado")
    panel.recargar()

    assert panel.lista.GetItemCount() == 2


def test_buscar_por_cedula_encuentra_credito_sin_cambiar_filtro(panel, conn):
    # El filtro por defecto YA es "Todos los estados" (pedido explícito del
    # usuario, 2026-08-21) — buscar un cliente sin crédito activo no
    # depende de tocar el combo primero.
    _crear_credito(conn, "C-1", cedula="0012510940057N", estado="Corriente",
                    fecha_desembolso="2025-06-30")
    _crear_credito(conn, "C-2", cedula="0012510940057N", estado="Cancelado",
                    fecha_desembolso="2026-06-30")

    panel.busqueda_texto.SetValue("0012510940057N")
    panel._buscar()

    assert _filas_lista(panel, 2) == ["C-2", "C-1"]  # más reciente primero


def test_vaciar_busqueda_vuelve_a_la_vista_por_defecto(panel, conn):
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado")

    # Se elige "Cancelados" a propósito (distinto del valor por defecto,
    # "Todos los estados" — pedido explícito del usuario, 2026-08-21) para
    # confirmar que limpiar_busqueda() lo vuelve a dejar en el default real.
    panel.estado_choice.SetSelection(2)  # "Cancelados"
    panel.busqueda_texto.SetValue("001")
    panel._cargar_creditos(avisar_sin_resultados=False)
    assert panel.lista.GetItemCount() == 0  # "001" es Corriente, Cancelados lo excluye

    panel.limpiar_busqueda()
    assert panel.busqueda_texto.GetValue() == ""
    assert panel.estado_choice.GetSelection() == _INDICE_ESTADO_POR_DEFECTO
    assert panel.empresa_choice.GetSelection() == 0
    assert sorted(_filas_lista(panel, 2)) == ["C-1", "C-2"]


def test_busqueda_invalida_no_revienta_y_deja_la_lista_vacia(panel, conn, monkeypatch):
    # _cargar_creditos() muestra un wx.MessageBox real ante un término
    # inválido (mismo criterio que CasosPanel) — bypaseado acá para no
    # colgar la prueba headless con un modal real.
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)

    _crear_credito(conn, "C-1", estado="Corriente")

    panel.busqueda_texto.SetValue("#$%")
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert panel.lista.GetItemCount() == 0


def test_celda_vacia_para_campos_sin_valor(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente", empresa_convenio=None, plazo_credito=None)
    panel.recargar()

    fila_empresa = _filas_lista(panel, 7)  # columna "Empresa Convenio"
    fila_plazo = _filas_lista(panel, 9)  # columna "Plazo del Crédito"
    assert fila_empresa == [CreditosPanel.CELDA_VACIA]
    assert fila_plazo == [CreditosPanel.CELDA_VACIA]


def test_saldo_a_la_fecha_suma_principal_e_intereses(panel, conn):
    # Pedido explícito del usuario (2026-08-21): "el saldo a la fecha es la
    # suma de saldo principal más el saldo de intereses" — saldo_principal y
    # saldo_intereses en sí no tienen columna propia visible (ver COLUMNAS).
    _crear_credito(conn, "C-1", estado="Corriente", saldo_principal=1000.50, saldo_intereses=25.75)
    panel.recargar()

    assert _filas_lista(panel, 4) == ["1026.25"]  # columna "Saldo a la fecha"


def test_saldo_a_la_fecha_vacio_si_falta_alguno_de_los_dos(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente", saldo_principal=1000.0, saldo_intereses=None)
    panel.recargar()

    assert _filas_lista(panel, 4) == [CreditosPanel.CELDA_VACIA]


def test_seleccionar_credito_actualiza_la_etiqueta(panel, conn):
    _crear_credito(conn, "C-1", cedula="001", nombre="Juan Perez", estado="Corriente")
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert "Juan Perez" in panel.credito_seleccionado_texto.GetLabel()
    assert "001" in panel.credito_seleccionado_texto.GetLabel()
    assert "C-1" in panel.credito_seleccionado_texto.GetLabel()


def test_recargar_ve_una_reimportacion_reciente(panel, conn):
    panel.recargar()
    assert panel.lista.GetItemCount() == 0

    _crear_credito(conn, "C-1", estado="Corriente")
    panel.recargar()
    assert panel.lista.GetItemCount() == 1


def test_enfocar_busqueda_selecciona_todo_el_texto_previo(panel, conn):
    # Atajo GLOBAL Ctrl+F cuando esta pestaña está activa (pedido explícito
    # del usuario, 2026-07-12) — ver MainFrame._enfocar_busqueda_segun_pestana_activa.
    # No se verifica el foco real de Windows (poco fiable en una prueba
    # headless sin bucle de eventos): alcanza con confirmar que no lanza y
    # que selecciona el texto existente, mismo patrón usado para
    # CasosPanel.enfocar_busqueda().
    panel.busqueda_texto.SetValue("001")
    panel.enfocar_busqueda()  # no debe lanzar


def test_enfocar_resultados_selecciona_el_primer_item_si_no_hay_seleccion(panel, conn):
    # Atajo GLOBAL Ctrl+R cuando esta pestaña está activa (pedido explícito
    # del usuario, 2026-07-12: "el comando Ctrl+R que lleva a la lista igual
    # tiene que funcionar con el apartado del historial de créditos").
    _crear_credito(conn, "C-1", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", estado="Corriente")
    panel.recargar()
    assert panel.lista.GetFirstSelected() == -1

    panel.enfocar_resultados()

    assert panel.lista.GetFirstSelected() == 0


def test_enfocar_resultados_sin_filas_no_falla(panel, conn):
    panel.recargar()
    assert panel.lista.GetItemCount() == 0
    panel.enfocar_resultados()  # no debe lanzar


def test_empresa_choice_solo_lista_empresas_del_reporte(panel, conn):
    # Pedido explícito del usuario (2026-08-16): "evitando listar todas las
    # empresas globalmente" — no debe salir el catálogo completo de
    # convenio_tasa (29 empresas sembradas por init_db), solo AGROSACO/IMMSA.
    _crear_credito(conn, "C-1", empresa_convenio="AGROSACO")
    _crear_credito(conn, "C-2", cedula="002", empresa_convenio="IMMSA")
    panel.recargar()

    opciones = [panel.empresa_choice.GetString(i) for i in range(panel.empresa_choice.GetCount())]
    assert opciones == ["Todas las empresas", "AGROSACO", "IMMSA"]


def test_filtro_por_empresa_restringe_la_lista(panel, conn):
    _crear_credito(conn, "C-1", empresa_convenio="AGROSACO")
    _crear_credito(conn, "C-2", cedula="002", empresa_convenio="IMMSA")
    panel.recargar()

    panel.empresa_choice.SetSelection(2)  # "IMMSA" (índice 0 = Todas, 1 = AGROSACO)
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert _filas_lista(panel, 2) == ["C-2"]


def test_filtro_por_estado_cancelados(panel, conn):
    # "Cancelados" reemplaza a la vieja "Finalizados (para reenganche)"
    # (pedido explícito del usuario, 2026-08-22) — igualdad simple, ya NO
    # incluye cuotas completas con otro estado (ver
    # test_filtro_cancelados_no_incluye_corriente_con_cuotas_completas).
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=3)
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado",
                    numero_cuotas=24, cuotas_pagadas=24)

    panel.estado_choice.SetSelection(2)  # "Cancelados"
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert _filas_lista(panel, 2) == ["C-2"]


def test_filtro_cancelados_no_incluye_corriente_con_cuotas_completas(panel, conn):
    # Confirmado explícitamente por el usuario (2026-08-22): "si el sistema
    # dice que está activo, eso está prohibido" tratarlo como cancelado —
    # ese caso especial vive en la alerta amarilla, no en este filtro.
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=24)

    panel.estado_choice.SetSelection(2)  # "Cancelados"
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert panel.lista.GetItemCount() == 0


def test_limpiar_busqueda_reproduce_el_sonido_de_borrado(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_BORRAR

    panel.limpiar_busqueda()

    assert llamadas == [SONIDO_BORRAR]


# ---- Alerta visual/sonora para créditos Vencido/Saneado (pedido explícito ---
# ---- del usuario, 2026-08-21 — mismo equivalente que Documentos ------------
# ---- pendientes ya tiene en Casos) -----------------------------------------

def test_fila_vencido_se_resalta_en_rojo(panel, conn):
    _crear_credito(conn, "C-1", estado="Vencido")
    panel.recargar()  # "Todos los estados" ya es el default

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CREDITO_ALERTA
    assert panel.lista.GetItemTextColour(0) == CreditosPanel._COLOR_TEXTO_CREDITO_ALERTA


def test_fila_saneado_se_resalta_en_rojo(panel, conn):
    _crear_credito(conn, "C-1", estado="Saneado")
    panel.recargar()  # "Todos los estados" ya es el default

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CREDITO_ALERTA
    assert panel.lista.GetItemTextColour(0) == CreditosPanel._COLOR_TEXTO_CREDITO_ALERTA


def test_fila_corriente_no_se_resalta(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente")
    panel.recargar()

    color_defecto = panel.lista.GetItemBackgroundColour(0)
    assert color_defecto != CreditosPanel._COLOR_FONDO_CREDITO_ALERTA


def test_seleccionar_credito_vencido_reproduce_el_sonido(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_CREDITO_VENCIDO_SANEADO

    _crear_credito(conn, "C-1", estado="Vencido")
    panel.recargar()  # "Todos los estados" ya es el default

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_CREDITO_VENCIDO_SANEADO]


def test_seleccionar_credito_saneado_reproduce_el_sonido(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_CREDITO_VENCIDO_SANEADO

    _crear_credito(conn, "C-1", estado="Saneado")
    panel.recargar()  # "Todos los estados" ya es el default

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_CREDITO_VENCIDO_SANEADO]


def test_seleccionar_credito_corriente_no_reproduce_sonido(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    _crear_credito(conn, "C-1", estado="Corriente")
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == []


# ---- Ampliación de la alerta: Prorrogado y mora real (pedido explícito ---
# ---- del usuario, 2026-08-21) ---------------------------------------------

def test_fila_prorrogado_se_resalta_en_rojo(panel, conn):
    _crear_credito(conn, "C-1", estado="Prorrogado")
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CREDITO_ALERTA


def test_fila_corriente_con_mora_real_se_resalta_aunque_diga_corriente(panel, conn):
    # Confirmado con datos reales (2026-08-21): 98 de 1,777 créditos
    # "Corriente" ya tenían dias_en_mora > 0 — el sistema de origen no les
    # había actualizado el estado todavía.
    _crear_credito(conn, "C-1", estado="Corriente", dias_en_mora=15)
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CREDITO_ALERTA


def test_fila_corriente_sin_mora_no_se_resalta(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente", dias_en_mora=0)
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) != CreditosPanel._COLOR_FONDO_CREDITO_ALERTA


def test_seleccionar_credito_prorrogado_reproduce_el_sonido(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_CREDITO_VENCIDO_SANEADO

    _crear_credito(conn, "C-1", estado="Prorrogado")
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_CREDITO_VENCIDO_SANEADO]


def test_seleccionar_credito_en_mora_real_reproduce_el_sonido(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_CREDITO_VENCIDO_SANEADO

    _crear_credito(conn, "C-1", estado="Corriente", dias_en_mora=3)
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_CREDITO_VENCIDO_SANEADO]


# ---- "Revisar manualmente" (avance de pago inconsistente, pedido -----
# ---- explícito del usuario, 2026-08-21) -----------------------------------

def _credito_con_avance_inconsistente(conn, no_credito, **overrides):
    """Corriente, sin mora — solo el cruce de avance de pago no cuadra
    (dinero: 50%, cuotas: ~4.2%, diferencia muy por encima de los 15 puntos
    de tolerancia)."""
    valores = dict(
        estado="Corriente", dias_en_mora=0, monto_desembolsado=1000.0,
        saldo_principal=450.0, saldo_intereses=50.0,
        numero_cuotas=24, cuotas_pagadas=1, plazo_credito=24,
    )
    valores.update(overrides)
    _crear_credito(conn, no_credito, **valores)


def test_fila_con_avance_inconsistente_se_resalta(panel, conn):
    _credito_con_avance_inconsistente(conn, "C-1")
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CREDITO_ALERTA


def test_seleccionar_credito_avance_inconsistente_reproduce_sonido_revisar_manualmente(
    panel, conn, monkeypatch
):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_REVISAR_MANUALMENTE

    _credito_con_avance_inconsistente(conn, "C-1")
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_REVISAR_MANUALMENTE]


def test_credito_vencido_con_avance_inconsistente_solo_suena_la_alerta_principal(
    panel, conn, monkeypatch
):
    # Un crédito Vencido con datos de avance inconsistentes solo debe sonar
    # UNA vez — la alerta de estado/mora es más urgente, gana sobre "revisar
    # manualmente" (ver CreditosPanel._refrescar_lista/_on_seleccionar_credito).
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_CREDITO_VENCIDO_SANEADO

    _credito_con_avance_inconsistente(conn, "C-1", estado="Vencido")
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_CREDITO_VENCIDO_SANEADO]


def test_credito_sin_datos_de_avance_no_dispara_revision_manual(panel, conn):
    # Sin saldo_principal/saldo_intereses cargados no hay nada que cruzar
    # ("sin_datos") — eso NO es lo mismo que "inconsistente", no debe
    # resaltarse (mismo criterio que test_fila_corriente_sin_mora_no_se_resalta).
    _crear_credito(conn, "C-1", estado="Corriente", dias_en_mora=0)
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) != CreditosPanel._COLOR_FONDO_CREDITO_ALERTA


# ---- "Elegibles para refinanciar" / "Cancelados" en el selector Estado ---

def test_estado_opciones_son_exactamente_estas_tres():
    # Pedido explícito del usuario (2026-08-22): "es más lógico que solo
    # tengamos tres" — reemplaza al esquema anterior de 4 opciones.
    from gestor_credito.ui.creditos_panel import ESTADO_OPCIONES

    textos = [texto for texto, _valor in ESTADO_OPCIONES]
    assert textos == ["Todos los estados", "Elegibles para refinanciar", "Cancelados"]


def test_elegibles_para_refinanciar_se_ordena_por_avance_descendente(panel, conn):
    # Pedido explícito del usuario (2026-08-22): el que le falta menos por
    # pagar (mayor % de avance) va primero.
    _credito_elegible = dict(
        estado="Corriente", dias_en_mora=0, monto_desembolsado=1000.0, plazo_credito=24,
        numero_cuotas=24, es_convenio="S",
    )
    _crear_credito(conn, "C-1", cedula="001", saldo_principal=450.0, saldo_intereses=50.0,
                    cuotas_pagadas=12, **_credito_elegible)  # 50%
    _crear_credito(conn, "C-2", cedula="002", saldo_principal=50.0, saldo_intereses=0.0,
                    cuotas_pagadas=23, **_credito_elegible)  # 95%
    _crear_credito(conn, "C-3", cedula="003", saldo_principal=250.0, saldo_intereses=50.0,
                    cuotas_pagadas=18, **_credito_elegible)  # 70%

    panel.estado_choice.SetSelection(1)  # "Elegibles para refinanciar"
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert _filas_lista(panel, 2) == ["C-2", "C-3", "C-1"]


def test_cancelados_se_ordena_por_fecha_de_cancelacion_mas_reciente_primero(panel, conn):
    # Pedido explícito del usuario (2026-08-22): "si estamos a 21 de agosto
    # y el cliente canceló el 15 de agosto, ese es el que me tiene que salir
    # de primero". Usa fecha_ultimo_pago_principal, no
    # estado_credito_fecha_cambio — bug real encontrado el mismo día (ver
    # tests/test_reporte_creditos.py).
    _crear_credito(conn, "C-1", cedula="001", estado="Cancelado",
                    fecha_ultimo_pago_principal="2026-07-30")
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado",
                    fecha_ultimo_pago_principal="2026-08-15")
    _crear_credito(conn, "C-3", cedula="003", estado="Cancelado",
                    fecha_ultimo_pago_principal="2026-08-01")

    panel.estado_choice.SetSelection(2)  # "Cancelados"
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert _filas_lista(panel, 2) == ["C-2", "C-3", "C-1"]


def test_todos_los_estados_mantiene_orden_por_fecha_de_desembolso(panel, conn):
    # Pedido explícito del usuario (2026-08-22): "donde me muestra todos los
    # créditos tiene que mantener el orden original" — sin cambios acá.
    _crear_credito(conn, "C-1", cedula="001", fecha_desembolso="2024-01-01")
    _crear_credito(conn, "C-2", cedula="002", fecha_desembolso="2026-06-30")
    _crear_credito(conn, "C-3", cedula="003", fecha_desembolso="2025-03-15")
    panel.recargar()

    assert _filas_lista(panel, 2) == ["C-2", "C-3", "C-1"]


# ---- "Caso especial": Corriente con cuotas ya completas (pedido -----------
# ---- explícito del usuario, 2026-08-22) ------------------------------------

def test_caso_especial_se_resalta_en_amarillo(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=24)
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CASO_ESPECIAL
    assert panel.lista.GetItemTextColour(0) == CreditosPanel._COLOR_TEXTO_CASO_ESPECIAL


def test_caso_especial_no_se_confunde_con_la_alerta_roja(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=24)
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) != CreditosPanel._COLOR_FONDO_CREDITO_ALERTA


def test_caso_especial_cuotas_pagadas_mayor_que_numero_tambien_cuenta(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=25)
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CASO_ESPECIAL


def test_credito_cancelado_no_es_caso_especial(panel, conn):
    # El caso especial exige estado_credito == Corriente — un Cancelado con
    # cuotas completas es simplemente un Cancelado normal (ver filtro
    # "Cancelados"), no pasa por acá.
    _crear_credito(conn, "C-1", estado="Cancelado", numero_cuotas=24, cuotas_pagadas=24)
    panel.recargar()

    assert panel.lista.GetItemBackgroundColour(0) != CreditosPanel._COLOR_FONDO_CASO_ESPECIAL


def test_seleccionar_caso_especial_reproduce_su_propio_sonido(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_CASO_ESPECIAL_CUOTAS_COMPLETAS

    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=24)
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_CASO_ESPECIAL_CUOTAS_COMPLETAS]


def test_credito_vencido_con_cuotas_completas_solo_suena_la_alerta_principal(panel, conn, monkeypatch):
    # La alerta de estado/mora real es más urgente y gana sobre el caso
    # especial — mismo criterio que ya existe frente a "revisar manualmente"
    # (ver test_credito_vencido_con_avance_inconsistente_solo_suena_la_alerta_principal).
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_FILA_CREDITO_VENCIDO_SANEADO

    _crear_credito(conn, "C-1", estado="Vencido", numero_cuotas=24, cuotas_pagadas=24)
    panel.recargar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_credito(evento)

    assert llamadas == [SONIDO_FILA_CREDITO_VENCIDO_SANEADO]
