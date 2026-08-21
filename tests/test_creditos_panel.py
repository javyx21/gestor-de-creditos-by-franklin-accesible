"""Pruebas de extremo a extremo del panel "Historial de Créditos"
(CreditosPanel) — construyen el panel real (no mocks) contra una base de
datos temporal, mismo patrón que test_configuracion_panel.py."""

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.ui.creditos_panel import COLUMNAS, CreditosPanel


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


def test_vista_por_defecto_muestra_solo_corriente(panel, conn):
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado")
    panel.recargar()

    assert panel.lista.GetItemCount() == 1
    assert _filas_lista(panel, 2) == ["C-1"]  # columna "No. Crédito"


def test_buscar_por_cedula_respeta_el_estado_activo_por_defecto(panel, conn):
    # 2026-08-16: el selector "Estado" reemplazó el auto-historial-completo
    # que antes disparaba cualquier término de búsqueda — con el valor por
    # defecto ("Activos"), un crédito Cancelado no aparece aunque coincida
    # la cédula. Ver el test siguiente para pedir el historial completo.
    _crear_credito(conn, "C-1", cedula="0012510940057N", estado="Corriente",
                    fecha_desembolso="2025-06-30")
    _crear_credito(conn, "C-2", cedula="0012510940057N", estado="Cancelado",
                    fecha_desembolso="2026-06-30")

    panel.busqueda_texto.SetValue("0012510940057N")
    panel._buscar()

    assert _filas_lista(panel, 2) == ["C-1"]


def test_buscar_por_cedula_con_estado_todos_muestra_historial_completo_ordenado_desc(panel, conn):
    _crear_credito(conn, "C-1", cedula="0012510940057N", estado="Corriente",
                    fecha_desembolso="2025-06-30")
    _crear_credito(conn, "C-2", cedula="0012510940057N", estado="Cancelado",
                    fecha_desembolso="2026-06-30")

    panel.estado_choice.SetSelection(2)  # "Todos los estados"
    panel.busqueda_texto.SetValue("0012510940057N")
    panel._buscar()

    assert _filas_lista(panel, 2) == ["C-2", "C-1"]  # más reciente primero


def test_vaciar_busqueda_vuelve_a_la_vista_por_defecto(panel, conn):
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado")

    # Además de la búsqueda, cambia los tres filtros nuevos — limpiar_busqueda()
    # debe resetear todo, no solo el cuadro de texto (2026-08-16).
    panel.estado_choice.SetSelection(2)  # "Todos los estados"
    panel.busqueda_texto.SetValue("002")
    panel._buscar()
    assert panel.lista.GetItemCount() == 1

    panel.limpiar_busqueda()
    assert panel.busqueda_texto.GetValue() == ""
    assert panel.estado_choice.GetSelection() == 0
    assert panel.empresa_choice.GetSelection() == 0
    assert panel.cuotas_pendientes_texto.GetValue() == ""
    assert _filas_lista(panel, 2) == ["C-1"]


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


def test_filtro_por_estado_finalizados(panel, conn):
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=3)
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado",
                    numero_cuotas=24, cuotas_pagadas=24)
    # Cuotas ya completas pero estado_credito todavía sin actualizar a
    # Cancelado en el sistema de origen — también cuenta como finalizado
    # (ver ESTADO_CREDITO_FINALIZADO en db/reporte_creditos.py).
    _crear_credito(conn, "C-3", cedula="003", estado="Trámite",
                    numero_cuotas=24, cuotas_pagadas=24)

    panel.estado_choice.SetSelection(1)  # "Finalizados (para reenganche)"
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert sorted(_filas_lista(panel, 2)) == ["C-2", "C-3"]


def test_filtro_por_cuotas_pendientes_maximo_es_menor_o_igual(panel, conn):
    # "Próximos a finalizar" (pedido explícito del usuario, 2026-08-16
    # segunda ronda): <=, no coincidencia exacta.
    _crear_credito(conn, "C-1", numero_cuotas=24, cuotas_pagadas=24)  # 0 pendientes
    _crear_credito(conn, "C-2", cedula="002", numero_cuotas=24, cuotas_pagadas=22)  # 2 pendientes
    _crear_credito(conn, "C-3", cedula="003", numero_cuotas=24, cuotas_pagadas=18)  # 6 pendientes

    panel.estado_choice.SetSelection(2)  # "Todos los estados"
    panel.cuotas_pendientes_texto.SetValue("2")
    panel._buscar()

    assert sorted(_filas_lista(panel, 2)) == ["C-1", "C-2"]


def test_proximos_a_finalizar_es_activos_mas_cuotas_pendientes_maximo(panel, conn):
    # El filtro de negocio "Próximos a finalizar" no es un control aparte:
    # es Estado="Activos" (el valor por defecto del panel) combinado con el
    # campo "Cuotas pendientes (máximo)" — ver CLAUDE.md.
    _crear_credito(conn, "C-1", estado="Corriente", numero_cuotas=24, cuotas_pagadas=22)  # activo, 2 pend.
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado",
                    numero_cuotas=24, cuotas_pagadas=24)  # finalizado, no debe aparecer

    panel.cuotas_pendientes_texto.SetValue("2")
    panel._buscar()

    assert _filas_lista(panel, 2) == ["C-1"]


def test_cuotas_pendientes_invalidas_muestra_mensaje_y_no_revienta(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: llamadas.append(a) or wx.OK)

    _crear_credito(conn, "C-1")
    panel.cuotas_pendientes_texto.SetValue("no es un número")
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert panel.lista.GetItemCount() == 0
    assert len(llamadas) == 1


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
    panel.estado_choice.SetSelection(2)  # "Todos los estados"
    panel._cargar_creditos(avisar_sin_resultados=False)

    assert panel.lista.GetItemBackgroundColour(0) == CreditosPanel._COLOR_FONDO_CREDITO_ALERTA
    assert panel.lista.GetItemTextColour(0) == CreditosPanel._COLOR_TEXTO_CREDITO_ALERTA


def test_fila_saneado_se_resalta_en_rojo(panel, conn):
    _crear_credito(conn, "C-1", estado="Saneado")
    panel.estado_choice.SetSelection(2)  # "Todos los estados"
    panel._cargar_creditos(avisar_sin_resultados=False)

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
    panel.estado_choice.SetSelection(2)  # "Todos los estados"
    panel._cargar_creditos(avisar_sin_resultados=False)

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
    panel.estado_choice.SetSelection(2)  # "Todos los estados"
    panel._cargar_creditos(avisar_sin_resultados=False)

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


def test_vista_por_defecto_de_activos_no_cambia_con_la_alerta_nueva(panel, conn):
    # Pedido explícito del usuario (2026-08-21): la alerta es puramente
    # decorativa sobre lo que ya se muestra — la vista por defecto
    # ("Activos") sigue excluyendo Vencido/Saneado exactamente igual que
    # antes de este cambio, ningún filtro se tocó.
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", estado="Vencido")
    _crear_credito(conn, "C-3", cedula="003", estado="Saneado")
    panel.recargar()

    assert panel.lista.GetItemCount() == 1
    assert _filas_lista(panel, 2) == ["C-1"]
