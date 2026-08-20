"""Pruebas de gestor_credito/ui/actualizacion_dialog.py — todo lo de
actualizaciones vive acá desde 2026-08-20 (submenú nativo "Ayuda >
Actualizaciones", ver main_frame.py y la historia completa en el docstring
de ayuda_panel.py), después de que el usuario rechazara dos intentos
anteriores (botones al fondo de la lista de atajos, y luego un
wx.TreeCtrl calcado de ConfiguracionPanel).

Mockea verificar_actualizacion/descargar_actualizacion/aplicar_actualizacion
tal como quedaron importados en este módulo (no en actualizador.py) y corre
ejecutar_en_segundo_plano() de forma síncrona — mismo patrón que
tests/test_creditos_panel.py y el extinto tests/test_ayuda_panel.py.

ActualizacionDisponibleDialog.ShowModal() abre un bucle de eventos modal
propio que bloquearía la prueba indefinidamente sin una ventana real
cerrándolo — por eso, en las pruebas de buscar_actualizaciones() que
encuentran una versión nueva, se reemplaza la clase del diálogo por un doble
de prueba que no bloquea. El diálogo en sí (su contenido y el botón
Instalar) se prueba aparte, construyéndolo directo sin pasar por ShowModal."""

import wx
import pytest

from gestor_credito.actualizador.actualizador import ActualizacionDisponible
from gestor_credito.ui import actualizacion_dialog as modulo
from gestor_credito.ui.actualizacion_dialog import (
    ActualizacionDisponibleDialog,
    buscar_actualizaciones,
    mostrar_informacion_version,
)
from gestor_credito.version import VERSION


@pytest.fixture(scope="module")
def app():
    return wx.App()


@pytest.fixture
def parent(app):
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()


@pytest.fixture(autouse=True)
def _sin_hilos(monkeypatch):
    monkeypatch.setattr(modulo, "ejecutar_en_segundo_plano", lambda trabajo, callback: callback(trabajo()))


class _DialogoFalso:
    instancias = []

    def __init__(self, parent, actualizacion):
        self.parent = parent
        self.actualizacion = actualizacion
        self.mostrado = False
        self.destruido = False
        _DialogoFalso.instancias.append(self)

    def ShowModal(self):
        self.mostrado = True

    def Destroy(self):
        self.destruido = True


@pytest.fixture(autouse=True)
def _limpiar_instancias():
    _DialogoFalso.instancias.clear()
    yield
    _DialogoFalso.instancias.clear()


# ---- buscar_actualizaciones -------------------------------------------------


def test_buscar_actualizaciones_ya_actualizado_no_abre_dialogo(parent, monkeypatch):
    monkeypatch.setattr(modulo, "verificar_actualizacion", lambda: None)
    monkeypatch.setattr(modulo, "ActualizacionDisponibleDialog", _DialogoFalso)
    mensajes = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: mensajes.append(a))

    llamadas = []
    buscar_actualizaciones(parent, lambda valor: llamadas.append(valor))

    assert llamadas == [None]
    assert _DialogoFalso.instancias == []
    assert len(mensajes) == 1
    assert "más reciente" in mensajes[0][0]


def test_buscar_actualizaciones_error_no_llama_al_completar(parent, monkeypatch):
    def _falla():
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(modulo, "verificar_actualizacion", _falla)
    monkeypatch.setattr(modulo, "ActualizacionDisponibleDialog", _DialogoFalso)
    mensajes = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: mensajes.append(a))

    llamadas = []
    buscar_actualizaciones(parent, lambda valor: llamadas.append(valor))

    assert llamadas == []
    assert _DialogoFalso.instancias == []
    assert "sin conexión" in mensajes[0][0]


def test_buscar_actualizaciones_version_nueva_abre_el_dialogo(parent, monkeypatch):
    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")
    monkeypatch.setattr(modulo, "verificar_actualizacion", lambda: disponible)
    monkeypatch.setattr(modulo, "ActualizacionDisponibleDialog", _DialogoFalso)

    llamadas = []
    buscar_actualizaciones(parent, lambda valor: llamadas.append(valor))

    assert llamadas == [disponible]
    assert len(_DialogoFalso.instancias) == 1
    assert _DialogoFalso.instancias[0].actualizacion is disponible
    assert _DialogoFalso.instancias[0].mostrado
    assert _DialogoFalso.instancias[0].destruido


# ---- mostrar_informacion_version --------------------------------------------


def test_informacion_version_sin_busqueda_previa(parent, monkeypatch):
    mensajes = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: mensajes.append(a))

    mostrar_informacion_version(parent, False, None)

    assert "no se buscaron actualizaciones" in mensajes[0][0].lower()
    assert VERSION in mensajes[0][0]


def test_informacion_version_ya_actualizado(parent, monkeypatch):
    mensajes = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: mensajes.append(a))

    mostrar_informacion_version(parent, True, None)

    assert "más reciente" in mensajes[0][0]


def test_informacion_version_con_novedades(parent, monkeypatch):
    disponible = ActualizacionDisponible(
        version="9.9.9", url_descarga="https://x", sha256="abc", notas="- Novedad 1"
    )
    mensajes = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: mensajes.append(a))

    mostrar_informacion_version(parent, True, disponible)

    assert "9.9.9" in mensajes[0][0]
    assert "Novedad 1" in mensajes[0][0]


# ---- ActualizacionDisponibleDialog ------------------------------------------


def test_dialogo_muestra_las_notas(parent):
    disponible = ActualizacionDisponible(
        version="9.9.9", url_descarga="https://x", sha256="abc", notas="Cambios de prueba"
    )
    dialogo = ActualizacionDisponibleDialog(parent, disponible)
    try:
        assert dialogo.notas_texto.GetValue() == "Cambios de prueba"
    finally:
        dialogo.Destroy()


def test_dialogo_sin_notas_muestra_mensaje_por_defecto(parent):
    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")
    dialogo = ActualizacionDisponibleDialog(parent, disponible)
    try:
        assert dialogo.notas_texto.GetValue() != ""
    finally:
        dialogo.Destroy()


def _disparar(boton):
    boton.Command(wx.CommandEvent(wx.EVT_BUTTON.typeId, boton.GetId()))


def test_instalar_flujo_completo_termina_el_proceso(parent, monkeypatch):
    # Bug real reproducido en vivo CUATRO VECES (2026-08-20), cada intento
    # descartando la teoría del anterior — ver el comentario extenso en
    # actualizacion_dialog.py para la historia completa (wx.Exit() directo,
    # EndModal()+CallAfter, os._exit(), y hasta un TerminateProcess() por
    # ctypes directo, ninguno cerraba el proceso de verdad en la práctica).
    # Fix definitivo: reusar `taskkill /F /PID <pid>` como subproceso — el
    # único mecanismo que efectivamente cerró estos procesos colgados
    # durante todo el diagnóstico en vivo de esta sesión. Monkeypatchear
    # subprocess.Popen acá es OBLIGATORIO — la llamada real terminaría el
    # proceso de pytest mismo si llega a ejecutarse de verdad.
    llamadas_popen = []
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda args, **kw: llamadas_popen.append(args))

    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")
    dialogo = ActualizacionDisponibleDialog(parent, disponible)

    descargas = []
    monkeypatch.setattr(
        modulo, "descargar_actualizacion",
        lambda url, sha256, destino: descargas.append((url, sha256, destino)),
    )
    aplicaciones = []
    monkeypatch.setattr(modulo, "aplicar_actualizacion", lambda ruta_zip: aplicaciones.append(ruta_zip))

    _disparar(dialogo.instalar_btn)

    assert len(descargas) == 1
    assert descargas[0][0] == "https://x"
    assert descargas[0][1] == "abc"
    assert len(aplicaciones) == 1
    assert len(llamadas_popen) == 1
    assert llamadas_popen[0][:3] == ["taskkill", "/F", "/PID"]
    dialogo.Destroy()


def test_instalar_descarga_fallida_reactiva_el_boton(parent, monkeypatch):
    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")
    dialogo = ActualizacionDisponibleDialog(parent, disponible)

    def _falla_descarga(url, sha256, destino):
        raise RuntimeError("checksum no coincide")

    monkeypatch.setattr(modulo, "descargar_actualizacion", _falla_descarga)
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: None)
    salidas = []
    monkeypatch.setattr(wx, "Exit", lambda: salidas.append(1))

    _disparar(dialogo.instalar_btn)

    assert salidas == []
    assert dialogo.instalar_btn.IsEnabled()
    dialogo.Destroy()
