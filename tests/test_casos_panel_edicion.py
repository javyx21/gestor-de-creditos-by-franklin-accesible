"""Pruebas de CasosPanel.limpiar_edicion() y limpiar_todo(). limpiar_edicion()
ya no está atado directo a ningún atajo de teclado (hasta 2026-07-12 lo
estaba, a Alt+L) — desde 2026-08-16 el atajo GLOBAL Ctrl+L cuando la pestaña
activa es Casos llama a limpiar_todo(), que combina limpiar_edicion() con
limpiar_busqueda() en un solo gesto (ver CLAUDE.md, "Estandarización del
atajo para limpiar"). Mismo patrón de panel real contra base de datos
temporal que test_configuracion_panel.py."""

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.ui.casos_panel import CasosPanel


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


def _crear_cliente_y_caso(conn, cedula="001-1234567-8", nombre="Juan Perez",
                          estado="En espera de constancia", no_presolicitud="P-9001"):
    cur = conn.execute(
        "INSERT INTO cliente (cedula, nombre, telefono) VALUES (?, ?, ?)",
        (cedula, nombre, "8091234567"),
    )
    cliente_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO caso (cliente_id, no_presolicitud, clave_caso, ejecutivo,
                           estado_solicitud, etapa_proceso, fecha_registro)
        VALUES (?, ?, ?, 'Maria Gomez', ?, 'Verificacion', '2026-06-20')
        """,
        (cliente_id, no_presolicitud, no_presolicitud, estado),
    )
    conn.commit()


def _frame_con_status_bar():
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    return frame


@pytest.fixture
def panel(app, conn):
    frame = _frame_con_status_bar()
    panel = CasosPanel(frame)
    yield panel
    frame.Destroy()


def test_limpiar_edicion_sin_nada_seleccionado_no_falla(panel, conn):
    panel.limpiar_edicion()  # no debe lanzar
    assert panel.caso_seleccionado_texto.GetLabel() == "Ningún caso seleccionado"


def test_limpiar_edicion_resetea_el_panel_tras_seleccionar_un_caso(panel, conn):
    _crear_cliente_y_caso(conn)
    panel._cargar_casos(avisar_sin_resultados=False)

    estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
    panel.lista.SetItemState(0, estado, estado)
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_caso(evento)

    assert panel._caso_seleccionado_id is not None
    assert panel.guardar_btn.IsEnabled()
    assert panel.eliminar_btn.IsEnabled()

    panel.limpiar_edicion()

    assert panel._caso_seleccionado_id is None
    assert panel._cliente_seleccionado_id is None
    assert panel.caso_seleccionado_texto.GetLabel() == "Ningún caso seleccionado"
    assert not panel.guardar_btn.IsEnabled()
    assert not panel.eliminar_btn.IsEnabled()
    assert panel.estado_choice.GetSelection() == wx.NOT_FOUND
    assert panel.etapa_choice.GetSelection() == wx.NOT_FOUND
    assert panel.lista.GetFirstSelected() == -1
    assert panel.mensaje_texto.GetLabel() == ""


def test_limpiar_edicion_no_toca_la_busqueda_ni_el_filtro(panel, conn):
    _crear_cliente_y_caso(conn)
    panel.busqueda_texto.SetValue("algo")
    panel.filtro_alerta_choice.SetSelection(1)

    panel.limpiar_edicion()

    assert panel.busqueda_texto.GetValue() == "algo"
    assert panel.filtro_alerta_choice.GetSelection() == 1


def test_limpiar_edicion_reproduce_el_sonido_de_borrado(panel, conn, monkeypatch):
    # Pedido explícito del usuario: "la acción de borrar siempre tiene que
    # hacer llamado al sonido".
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.casos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_BORRAR

    panel.limpiar_edicion()

    assert llamadas == [SONIDO_BORRAR]


def test_limpiar_todo_resetea_edicion_y_busqueda_juntos(panel, conn):
    # Ctrl+L (2026-08-16) unifica lo que antes eran dos acciones separadas
    # (Alt+L para el panel de edición, Alt+V para la búsqueda/filtro).
    _crear_cliente_y_caso(conn)
    panel._cargar_casos(avisar_sin_resultados=False)
    estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
    panel.lista.SetItemState(0, estado, estado)
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar_caso(evento)

    panel.busqueda_texto.SetValue("algo")
    panel.filtro_alerta_choice.SetSelection(1)
    assert panel._caso_seleccionado_id is not None

    panel.limpiar_todo()

    assert panel._caso_seleccionado_id is None
    assert panel.caso_seleccionado_texto.GetLabel() == "Ningún caso seleccionado"
    assert panel.busqueda_texto.GetValue() == ""
    assert panel.filtro_alerta_choice.GetSelection() == 0


def test_limpiar_todo_reproduce_el_sonido_de_borrado_una_sola_vez(panel, conn, monkeypatch):
    # No debe sonar dos veces por combinar internamente las rutinas que
    # limpiar_busqueda()/limpiar_edicion() usan por separado.
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.casos_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_BORRAR

    panel.limpiar_todo()

    assert llamadas == [SONIDO_BORRAR]
