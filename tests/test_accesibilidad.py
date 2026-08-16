"""Pruebas de ejecutar_en_segundo_plano() (ui/accesibilidad.py) — agregado
2026-08-16 junto con la carga asíncrona de Historial de Créditos, para
verificar el mecanismo real (hilo + wx.CallAfter), no solo la versión
síncrona que usan las pruebas de CreditosPanel vía monkeypatch."""

import threading
import time

import wx
import pytest

from gestor_credito.ui.accesibilidad import ejecutar_en_segundo_plano


@pytest.fixture(scope="module")
def app():
    return wx.App()


def _esperar(evento, timeout=5):
    """Bombea el bucle de eventos de wx hasta que `evento` se active o se
    cumpla el timeout — sin una wx.MainLoop corriendo (como en una prueba
    headless), wx.CallAfter necesita este bombeo manual para procesarse."""
    inicio = time.time()
    while not evento.is_set() and time.time() - inicio < timeout:
        wx.YieldIfNeeded()
        time.sleep(0.01)
    return evento.is_set()


def test_trabajo_corre_en_otro_hilo_y_callback_en_el_principal(app):
    hilo_llamador = threading.current_thread()
    resultado = {}
    evento = threading.Event()

    def trabajo():
        resultado["trabajo_en_otro_hilo"] = threading.current_thread() is not hilo_llamador
        return 42

    def callback(valor):
        resultado["valor"] = valor
        resultado["callback_en_hilo_principal"] = threading.current_thread() is hilo_llamador
        evento.set()

    ejecutar_en_segundo_plano(trabajo, callback)

    assert _esperar(evento), "el callback nunca llegó"
    assert resultado["trabajo_en_otro_hilo"] is True
    assert resultado["callback_en_hilo_principal"] is True
    assert resultado["valor"] == 42


def test_no_bloquea_el_hilo_llamador_mientras_trabajo_corre(app):
    # El punto entero del mecanismo: llamar a ejecutar_en_segundo_plano()
    # debe volver de inmediato, sin esperar a que `trabajo` termine.
    liberar = threading.Event()
    evento_callback = threading.Event()

    def trabajo():
        liberar.wait(timeout=5)
        return "listo"

    def callback(valor):
        evento_callback.set()

    inicio = time.time()
    ejecutar_en_segundo_plano(trabajo, callback)
    duracion = time.time() - inicio

    assert duracion < 0.5, "ejecutar_en_segundo_plano() bloqueó al hilo llamador"

    liberar.set()
    assert _esperar(evento_callback)
