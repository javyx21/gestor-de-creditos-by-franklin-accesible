"""Pruebas de AyudaPanel: solo la lista de atajos de teclado. Actualizaciones
ya no vive acá — ver tests/test_actualizacion_dialog.py y el submenú
"Ayuda > Actualizaciones" en main_frame.py (ver ayuda_panel.py docstring para
la historia completa de por qué)."""

import wx
import pytest

from gestor_credito.ui.atajos import ATAJOS
from gestor_credito.ui.ayuda_panel import AyudaPanel


@pytest.fixture(scope="module")
def app():
    return wx.App()


@pytest.fixture
def panel(app):
    frame = wx.Frame(None)
    panel = AyudaPanel(frame)
    yield panel
    frame.Destroy()


def test_lista_tiene_una_fila_por_atajo(panel):
    assert panel.lista.GetItemCount() == len(ATAJOS)


def test_primera_fila_coincide_con_el_primer_atajo_registrado(panel):
    _modificador, _tecla, texto, seccion, descripcion, _accion = ATAJOS[0]
    assert panel.lista.GetItemText(0, 0) == texto
    assert panel.lista.GetItemText(0, 1) == seccion
    assert panel.lista.GetItemText(0, 2) == descripcion
