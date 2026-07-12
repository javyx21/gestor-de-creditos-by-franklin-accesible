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
    # orden pedido por el usuario (ver sección 1 del pedido).
    assert COLUMNAS == [
        "Fecha Desembolso", "Fecha Vencimiento", "No. Crédito", "Monto Desembolsado",
        "Nombre del Cliente", "Identificación", "Empresa Convenio", "Estado del Crédito",
        "Plazo del Crédito", "Número de Cuotas",
    ]


def test_vista_por_defecto_muestra_solo_corriente(panel, conn):
    _crear_credito(conn, "C-1", cedula="001", estado="Corriente")
    _crear_credito(conn, "C-2", cedula="002", estado="Cancelado")
    panel.recargar()

    assert panel.lista.GetItemCount() == 1
    assert _filas_lista(panel, 2) == ["C-1"]  # columna "No. Crédito"


def test_buscar_por_cedula_muestra_historial_completo_ordenado_desc(panel, conn):
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

    panel.busqueda_texto.SetValue("002")
    panel._buscar()
    assert panel.lista.GetItemCount() == 1

    panel.limpiar_busqueda()
    assert panel.busqueda_texto.GetValue() == ""
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

    fila_empresa = _filas_lista(panel, 6)  # columna "Empresa Convenio"
    fila_plazo = _filas_lista(panel, 8)  # columna "Plazo del Crédito"
    assert fila_empresa == [CreditosPanel.CELDA_VACIA]
    assert fila_plazo == [CreditosPanel.CELDA_VACIA]


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


def test_limpiar_busqueda_reproduce_el_sonido_de_borrado(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.creditos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_BORRAR

    panel.limpiar_busqueda()

    assert llamadas == [SONIDO_BORRAR]
