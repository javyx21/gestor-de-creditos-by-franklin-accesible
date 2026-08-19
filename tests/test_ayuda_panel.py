"""Pruebas del flujo de actualizaciones agregado a AyudaPanel (2026-08-19,
ver CLAUDE.md sección Actualizaciones): "Buscar actualizaciones" y
"Actualizar ahora" — dos botones, el segundo deshabilitado hasta que el
primero encuentre una versión más nueva, pedido explícito del usuario.

Mockea verificar_actualizacion/descargar_actualizacion/aplicar_actualizacion
tal como quedaron importados en ayuda_panel.py (no en el módulo
actualizador.py de origen) y corre ejecutar_en_segundo_plano() de forma
síncrona, mismo patrón ya usado en tests/test_creditos_panel.py — sin esto,
cada llamada necesitaría bombear el bucle de eventos de wx en una prueba
headless sin MainLoop."""

import wx
import pytest

from gestor_credito.actualizador.actualizador import ActualizacionDisponible
from gestor_credito.ui.ayuda_panel import AyudaPanel


@pytest.fixture(scope="module")
def app():
    return wx.App()


@pytest.fixture(autouse=True)
def _sin_hilos(monkeypatch):
    monkeypatch.setattr(
        "gestor_credito.ui.ayuda_panel.ejecutar_en_segundo_plano",
        lambda trabajo, callback: callback(trabajo()),
    )


@pytest.fixture
def panel(app):
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    panel = AyudaPanel(frame)
    yield panel
    frame.Destroy()


def _disparar(boton):
    boton.Command(wx.CommandEvent(wx.EVT_BUTTON.typeId, boton.GetId()))


def test_buscar_actualizacion_encuentra_version_nueva(panel, monkeypatch):
    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")
    monkeypatch.setattr("gestor_credito.ui.ayuda_panel.verificar_actualizacion", lambda: disponible)

    _disparar(panel.buscar_actualizacion_btn)

    assert panel.actualizar_ahora_btn.IsEnabled()
    assert "9.9.9" in panel.actualizacion_mensaje.GetLabel()


def test_buscar_actualizacion_ya_esta_al_dia(panel, monkeypatch):
    monkeypatch.setattr("gestor_credito.ui.ayuda_panel.verificar_actualizacion", lambda: None)

    _disparar(panel.buscar_actualizacion_btn)

    assert not panel.actualizar_ahora_btn.IsEnabled()
    assert "más reciente" in panel.actualizacion_mensaje.GetLabel()


def test_buscar_actualizacion_error_muestra_messagebox(panel, monkeypatch):
    def _falla():
        raise RuntimeError("sin conexión")

    monkeypatch.setattr("gestor_credito.ui.ayuda_panel.verificar_actualizacion", _falla)

    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *args, **kwargs: llamadas.append(args))

    _disparar(panel.buscar_actualizacion_btn)

    assert not panel.actualizar_ahora_btn.IsEnabled()
    assert len(llamadas) == 1
    assert "sin conexión" in llamadas[0][0]


def test_actualizar_ahora_sin_busqueda_previa_no_hace_nada(panel, monkeypatch):
    llamado = []
    monkeypatch.setattr("gestor_credito.ui.ayuda_panel.descargar_actualizacion", lambda *a, **k: llamado.append(1))

    _disparar(panel.actualizar_ahora_btn)

    assert llamado == []


def test_actualizar_ahora_flujo_completo_cierra_la_app(panel, monkeypatch):
    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")
    monkeypatch.setattr("gestor_credito.ui.ayuda_panel.verificar_actualizacion", lambda: disponible)
    _disparar(panel.buscar_actualizacion_btn)

    descargas = []
    monkeypatch.setattr(
        "gestor_credito.ui.ayuda_panel.descargar_actualizacion",
        lambda url, sha256, destino: descargas.append((url, sha256, destino)),
    )
    aplicaciones = []
    monkeypatch.setattr(
        "gestor_credito.ui.ayuda_panel.aplicar_actualizacion",
        lambda ruta_zip: aplicaciones.append(ruta_zip),
    )
    salidas = []
    monkeypatch.setattr(wx, "Exit", lambda: salidas.append(1))

    _disparar(panel.actualizar_ahora_btn)

    assert len(descargas) == 1
    assert descargas[0][0] == "https://x"
    assert descargas[0][1] == "abc"
    assert len(aplicaciones) == 1
    assert salidas == [1]


def test_actualizar_ahora_descarga_fallida_reactiva_botones(panel, monkeypatch):
    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")
    monkeypatch.setattr("gestor_credito.ui.ayuda_panel.verificar_actualizacion", lambda: disponible)
    _disparar(panel.buscar_actualizacion_btn)

    def _falla_descarga(url, sha256, destino):
        raise RuntimeError("checksum no coincide")

    monkeypatch.setattr("gestor_credito.ui.ayuda_panel.descargar_actualizacion", _falla_descarga)
    monkeypatch.setattr(wx, "MessageBox", lambda *args, **kwargs: None)
    salidas = []
    monkeypatch.setattr(wx, "Exit", lambda: salidas.append(1))

    _disparar(panel.actualizar_ahora_btn)

    assert salidas == []
    assert panel.buscar_actualizacion_btn.IsEnabled()
    assert panel.actualizar_ahora_btn.IsEnabled()
