"""Pruebas de extremo a extremo de "Configuración ▸ Configuración de Casos"
(agente/ejecutivo actual, importar bitácora de MIDESA, vaciar la base de
datos) — construyen un ConfiguracionCasosPanel real (no mocks) contra una
base de datos temporal, mismo patrón que test_configuracion_calculadora.py y
test_configuracion_creditos.py.

Hasta 2026-08-22 esta era una de 3 categorías dentro de un único
ConfiguracionPanel con árbol interno — ahora es su propia clase, abierta
directo desde el menú de cascada "Configuración" (ver main_frame.py)."""

import openpyxl
import wx
import pytest

from gestor_credito.db import database
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, obtener_valor
from gestor_credito.ui.configuracion_panel import ConfiguracionCasosPanel


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
    panel = ConfiguracionCasosPanel(frame)
    yield panel
    frame.Destroy()


HEADERS = [
    "ID Caso", "Fecha Registro", "Canal/Origen", "No. Presolicitud", "Ejecutivo",
    "Constancia Solicitada", "Empresa Convenio", "Nombre del Cliente", "Identificación",
    "Teléfono", "Monto Solicitado", "Destino del Crédito", "Microseguro",
    "Estado Solicitud", "Etapa Proceso", "Responsable Actual", "Fecha Última Gestión",
    "Próxima Gestión", "Días en Gestión", "Alerta Seguimiento",
    "¿Requiere registro/acción SIAF?", "Fecha Envío SIAF", "Fecha Decisión", "Decisión",
    "Motivo No Aplica/Desistimiento", "Observaciones",
]


def _fila(**overrides):
    base = {
        "ID Caso": "C-001",
        "Fecha Registro": "2026-06-20",
        "Canal/Origen": "Web",
        "No. Presolicitud": "P-9001",
        "Ejecutivo": "Maria Gomez",
        "Constancia Solicitada": "2026-06-21",
        "Empresa Convenio": "Acme SRL",
        "Nombre del Cliente": "Juan Perez",
        "Identificación": "001-1234567-8",
        "Teléfono": "8091234567",
        "Monto Solicitado": 50000,
        "Destino del Crédito": "Consumo",
        "Microseguro": "Si",
        "Estado Solicitud": "En espera de constancia",
        "Etapa Proceso": "Verificación",
        "Responsable Actual": "Maria Gomez",
        "Fecha Última Gestión": "2026-06-25",
        "Próxima Gestión": "2026-07-01",
        "Días en Gestión": 5,
        "Alerta Seguimiento": "No",
        "¿Requiere registro/acción SIAF?": "No",
        "Fecha Envío SIAF": None,
        "Fecha Decisión": None,
        "Decisión": None,
        "Motivo No Aplica/Desistimiento": None,
        "Observaciones": "Cliente contactado",
    }
    base.update(overrides)
    return [base[h] for h in HEADERS]


def _escribir_excel(path, filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for fila in filas:
        ws.append(fila)
    wb.save(path)


def _seleccionar_archivo_simulado(panel, path):
    """Bypasea el wx.FileDialog real: deja el panel exactamente en el mismo
    estado que _on_seleccionar_archivo() tras elegir un archivo."""
    panel._file_path = str(path)
    panel.archivo_texto.SetValue(str(path))
    panel.importar_btn.Enable()


def test_sin_agentes_el_choice_queda_deshabilitado(panel):
    assert panel.agentes_choice.GetCount() == 0
    assert not panel.agentes_choice.IsEnabled()


def test_importar_deshabilitado_hasta_elegir_archivo(panel):
    assert not panel.importar_btn.IsEnabled()


def test_importar_bitacora_crea_caso_y_agrega_agente_a_la_lista(panel, conn, tmp_path, monkeypatch):
    # _on_importar() muestra un wx.MessageBox real de "Importación
    # completada" al terminar — bypaseado acá para no colgar la prueba
    # headless con un modal real (mismo patrón que test_configuracion_creditos.py).
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)

    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila()])

    _seleccionar_archivo_simulado(panel, excel_path)
    panel._on_importar(None)

    assert "Clientes nuevos: 1" in panel.resultado_texto.GetValue()
    assert "Casos nuevos: 1" in panel.resultado_texto.GetValue()
    assert panel.agentes_choice.FindString("Maria Gomez") != wx.NOT_FOUND

    total_casos = conn.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
    assert total_casos == 1


def test_importar_archivo_invalido_muestra_error_sin_reventar(panel, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)

    excel_path = tmp_path / "no_existe.xlsx"
    _seleccionar_archivo_simulado(panel, excel_path)

    panel._on_importar(None)  # no debe lanzar

    assert "Error al importar" in panel.resultado_texto.GetValue()


def test_guardar_agente_lo_persiste_como_ejecutivo_actual(panel, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila(Ejecutivo="Maria Gomez")])
    _seleccionar_archivo_simulado(panel, excel_path)
    panel._on_importar(None)

    indice = panel.agentes_choice.FindString("Maria Gomez")
    panel.agentes_choice.SetSelection(indice)
    panel._on_guardar_agente(None)

    assert obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL) == "Maria Gomez"
    assert "Maria Gomez" in panel.agente_mensaje.GetLabel()


def test_guardar_agente_sin_seleccion_muestra_error(panel, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: llamadas.append(a) or wx.OK)

    panel._on_guardar_agente(None)

    assert llamadas  # se avisó, sin reventar
    assert obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL) is None


def test_vaciar_base_de_datos_borra_casos_y_conserva_el_agente(
    panel, conn, tmp_path, monkeypatch
):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila(Ejecutivo="Maria Gomez")])
    _seleccionar_archivo_simulado(panel, excel_path)
    panel._on_importar(None)

    indice = panel.agentes_choice.FindString("Maria Gomez")
    panel.agentes_choice.SetSelection(indice)
    panel._on_guardar_agente(None)

    # _on_vaciar_base_datos() pide confirmación con un wx.MessageBox real
    # (YES_NO) — bypaseado devolviendo wx.YES directo, equivalente a que el
    # usuario confirme.
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.YES)
    panel._on_vaciar_base_datos(None)

    total_casos = conn.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
    total_clientes = conn.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    assert total_casos == 0
    assert total_clientes == 0
    assert obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL) == "Maria Gomez"


def test_vaciar_base_de_datos_cancelada_no_borra_nada(panel, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.OK)
    excel_path = tmp_path / "bitacora.xlsx"
    _escribir_excel(excel_path, [_fila()])
    _seleccionar_archivo_simulado(panel, excel_path)
    panel._on_importar(None)

    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.NO)
    panel._on_vaciar_base_datos(None)

    total_casos = conn.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
    assert total_casos == 1
