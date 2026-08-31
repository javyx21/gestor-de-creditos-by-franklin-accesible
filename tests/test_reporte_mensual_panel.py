"""Pruebas de extremo a extremo de ReporteMensualPanel — construyen el panel
real (no mocks) contra una base de datos temporal, mismo patrón que
test_creditos_panel.py."""

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.ui.reporte_mensual_panel import OPCION_TODOS_LOS_AGENTES, ReporteMensualPanel


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


def _crear_cliente_y_caso(conn, cedula, nombre, ejecutivo="Maria Gomez",
                           estado="En proceso", fecha_registro="2026-08-01",
                           estado_solicitud_fecha_cambio=None, microseguro=None):
    cur = conn.execute(
        "INSERT INTO cliente (cedula, nombre, telefono) VALUES (?, ?, ?)",
        (cedula, nombre, "8091234567"),
    )
    cliente_id = cur.lastrowid
    clave = f"P-{cliente_id}"
    columnas = [
        "cliente_id", "no_presolicitud", "clave_caso", "ejecutivo",
        "estado_solicitud", "fecha_registro", "microseguro",
    ]
    valores = [cliente_id, clave, clave, ejecutivo, estado, fecha_registro, microseguro]
    if estado_solicitud_fecha_cambio:
        columnas.append("estado_solicitud_fecha_cambio")
        valores.append(estado_solicitud_fecha_cambio)
    placeholders = ", ".join("?" for _ in columnas)
    conn.execute(f"INSERT INTO caso ({', '.join(columnas)}) VALUES ({placeholders})", valores)
    conn.commit()


def _frame_con_status_bar():
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    return frame


@pytest.fixture
def panel(app, conn):
    frame = _frame_con_status_bar()
    panel = ReporteMensualPanel(frame)
    yield panel
    frame.Destroy()


def test_construye_sin_datos_sin_reventar(panel):
    assert "Desembolsados: 0" in panel.desembolsados_label.GetLabel()
    assert "Pendientes" in panel.pendientes_label.GetLabel()


def test_recargar_refleja_datos_reales_del_mes_elegido(panel, conn):
    _crear_cliente_y_caso(
        conn, "001", "Juan Perez", estado="Desembolsada", microseguro="S",
        estado_solicitud_fecha_cambio="2026-08-10 09:00:00",
    )
    _crear_cliente_y_caso(conn, "002", "Ana Lopez", estado="En proceso")

    panel.mes_choice.SetSelection(7)  # agosto (índice 7 = mes 8)
    panel.anio_spin.SetValue(2026)
    panel.recargar()

    assert "Desembolsados: 1" in panel.desembolsados_label.GetLabel()
    assert "con microseguro: 1" in panel.desembolsados_label.GetLabel()
    assert "Pendientes (no depende del mes elegido): 1" in panel.pendientes_label.GetLabel()


def test_toggle_detalle_llena_el_arbol(panel, conn):
    _crear_cliente_y_caso(conn, "001", "Juan Perez", estado="En proceso")
    panel.recargar()

    assert not panel.arbol.IsShown()
    panel.detalle_check.SetValue(True)
    panel._on_toggle_detalle(None)

    assert panel.arbol.IsShown()
    raiz = panel.arbol.GetRootItem()
    assert panel.arbol.GetChildrenCount(raiz, recursively=False) == 4  # 4 categorías


def test_filtro_de_agente_todos_incluye_todos(app, conn):
    _crear_cliente_y_caso(conn, "001", "Juan Perez", ejecutivo="Maria Gomez")
    _crear_cliente_y_caso(conn, "002", "Ana Lopez", ejecutivo="Pedro Lopez")

    # Construido DESPUÉS de sembrar los casos a propósito: la lista de
    # agentes se carga una sola vez, en __init__ (ver _cargar_agentes) —
    # igual que en uso real, donde _PanelDialog reconstruye el panel entero
    # cada vez que se abre el diálogo desde el menú, así que siempre ve los
    # agentes ya existentes en ese momento.
    frame = _frame_con_status_bar()
    panel = ReporteMensualPanel(frame)

    idx = panel.agente_choice.FindString(OPCION_TODOS_LOS_AGENTES)
    panel.agente_choice.SetSelection(idx)
    panel.recargar()

    assert "Pendientes (no depende del mes elegido): 2" in panel.pendientes_label.GetLabel()

    idx_maria = panel.agente_choice.FindString("Maria Gomez")
    panel.agente_choice.SetSelection(idx_maria)
    panel.recargar()

    assert "Pendientes (no depende del mes elegido): 1" in panel.pendientes_label.GetLabel()
    frame.Destroy()


def test_guardar_reporte_en_ruta_crea_el_archivo(panel, conn, tmp_path):
    _crear_cliente_y_caso(
        conn, "001", "Juan Perez", estado="Desembolsada",
        estado_solicitud_fecha_cambio="2026-08-10 09:00:00",
    )
    panel.mes_choice.SetSelection(7)
    panel.anio_spin.SetValue(2026)
    panel.recargar()

    ruta = tmp_path / "reporte.xlsx"
    panel._guardar_reporte_en_ruta(str(ruta), "Agosto", 2026)

    assert ruta.exists()
