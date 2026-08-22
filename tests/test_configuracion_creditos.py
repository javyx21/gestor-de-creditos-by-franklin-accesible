"""Pruebas de extremo a extremo de "Configuración ▸ Configuración de Reporte
de Créditos" (agregada 2026-07-12) — mismo patrón que
test_configuracion_calculadora.py: panel real (no mocks) contra una base de
datos temporal. El wx.FileDialog de "Seleccionar archivo Excel..." no se
puede invocar en una prueba automatizada (es modal e interactivo), así que se
bypasea fijando panel._file_path_creditos directamente, exactamente el mismo
estado que _on_seleccionar_archivo_creditos() deja tras una selección real.

Hasta 2026-08-22 esta era una de 3 categorías dentro de un único
ConfiguracionPanel con árbol interno — ahora es su propia clase
(ConfiguracionCreditosPanel), abierta directo desde el menú de cascada
"Configuración" (ver main_frame.py)."""

import openpyxl
import wx
import pytest

from gestor_credito.db import database
from gestor_credito.ui.configuracion_panel import ConfiguracionCreditosPanel


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


def _frame_con_status_bar():
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    return frame


@pytest.fixture
def panel(app, conn):
    frame = _frame_con_status_bar()
    panel = ConfiguracionCreditosPanel(frame)
    yield panel
    frame.Destroy()


HEADERS = [
    "FECHA_DESEMBOLSO", "FECHA_VENCIMIENTO", "NO_CREDITO", "NOMBRE_CLIENTE",
    "ESTADO_CREDITO", "MONTO_DESEMBOLSADO", "EMPRESA_DE_CONVENIO",
    "NO_IDENTIFICACION", "PLAZO_CREDITO", "CUOTAS_PAGADAS",
]


def _escribir_excel_creditos(path, filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for fila in filas:
        ws.append(fila)
    wb.save(path)


def _seleccionar_archivo_simulado(panel, path):
    """Bypasea el wx.FileDialog real: deja el panel exactamente en el mismo
    estado que _on_seleccionar_archivo_creditos() tras elegir un archivo."""
    panel._file_path_creditos = str(path)
    panel.archivo_creditos_texto.SetValue(str(path))
    panel.importar_creditos_btn.Enable()


def test_importar_deshabilitado_hasta_elegir_archivo(panel):
    assert not panel.importar_creditos_btn.IsEnabled()


def test_importar_reporte_crea_creditos_nuevos(panel, conn, tmp_path, monkeypatch):
    # _on_importar_creditos() muestra un wx.MessageBox real de "Importación
    # completada" al terminar con éxito (ver configuracion_panel.py, mismo
    # patrón que _on_importar() de la bitácora) — bypaseado acá para no
    # colgar la prueba headless con un modal real.
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)

    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel_creditos(excel_path, [
        ["2025-06-30", "2027-05-30", "001985", "KARLA CORTEZ", "Corriente",
         2007.04, "AGROSACO", "0012510940057N", 23, 24],
    ])

    _seleccionar_archivo_simulado(panel, excel_path)
    panel._on_importar_creditos(None)

    assert "Créditos nuevos: 1" in panel.resultado_creditos_texto.GetValue()
    assert "Créditos actualizados: 0" in panel.resultado_creditos_texto.GetValue()

    total = conn.execute("SELECT COUNT(*) FROM reporte_credito").fetchone()[0]
    assert total == 1


def test_reimportar_actualiza_no_duplica(panel, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)

    excel_path = tmp_path / "reporte.xlsx"
    _escribir_excel_creditos(excel_path, [
        ["2025-06-30", "2027-05-30", "001985", "KARLA CORTEZ", "Corriente",
         2007.04, "AGROSACO", "0012510940057N", 23, 24],
    ])
    _seleccionar_archivo_simulado(panel, excel_path)
    panel._on_importar_creditos(None)

    _escribir_excel_creditos(excel_path, [
        ["2025-06-30", "2027-05-30", "001985", "KARLA CORTEZ", "Cancelado",
         2007.04, "AGROSACO", "0012510940057N", 23, 46],
    ])
    _seleccionar_archivo_simulado(panel, excel_path)
    panel._on_importar_creditos(None)

    assert "Créditos actualizados: 1" in panel.resultado_creditos_texto.GetValue()
    total = conn.execute("SELECT COUNT(*) FROM reporte_credito").fetchone()[0]
    assert total == 1
    estado = conn.execute("SELECT estado_credito FROM reporte_credito").fetchone()[0]
    assert estado == "Cancelado"


def test_importar_archivo_invalido_muestra_error_sin_reventar(panel, conn, tmp_path, monkeypatch):
    # _on_importar_creditos() muestra un wx.MessageBox real ante un error (ver
    # configuracion_panel.py) — un modal real colgaría esta prueba headless,
    # así que se reemplaza por un stub que no bloquea, igual que el resto de
    # la app trataría un OK del usuario.
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)

    excel_path = tmp_path / "no_existe.xlsx"
    _seleccionar_archivo_simulado(panel, excel_path)

    panel._on_importar_creditos(None)  # no debe lanzar

    assert "Error al importar" in panel.resultado_creditos_texto.GetValue()
