"""Pruebas de los atajos GLOBALES Ctrl+F/Alt+L de MainFrame, cuyo efecto
ahora depende de la pestaña activa del notebook (pedido explícito del
usuario, 2026-07-12) — ver MainFrame._enfocar_busqueda_segun_pestana_activa /
_limpiar_segun_pestana_activa. Construye un MainFrame real (no mocks) contra
una base de datos temporal, mismo patrón que el resto de la suite."""

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.ui.main_frame import MainFrame


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


@pytest.fixture
def frame(app, conn):
    # MainFrame.__init__ llama database.init_db() — necesita que el
    # monkeypatch de DB_PATH ya esté aplicado, por eso `conn` es un
    # parámetro explícito de este fixture (garantiza el orden correcto,
    # lección real aprendida antes en esta misma suite con CalculadoraPanel).
    f = MainFrame(None, "Gestor de Crédito (prueba)")
    yield f
    f.Destroy()


def _ir_a_pestana(frame, panel):
    indice = frame.notebook.FindPage(panel)
    frame.notebook.SetSelection(indice)


def test_limpiar_en_calculadora_llama_limpiar_formulario(frame, monkeypatch):
    llamadas = []
    monkeypatch.setattr(frame.calculadora_panel, "limpiar_formulario", lambda: llamadas.append(1))
    _ir_a_pestana(frame, frame.calculadora_panel)

    frame._limpiar_segun_pestana_activa()

    assert llamadas == [1]


def test_limpiar_en_casos_llama_limpiar_edicion(frame, monkeypatch):
    llamadas = []
    monkeypatch.setattr(frame.casos_panel, "limpiar_edicion", lambda: llamadas.append(1))
    _ir_a_pestana(frame, frame.casos_panel)

    frame._limpiar_segun_pestana_activa()

    assert llamadas == [1]


def test_limpiar_en_creditos_llama_limpiar_busqueda(frame, monkeypatch):
    llamadas = []
    monkeypatch.setattr(frame.creditos_panel, "limpiar_busqueda", lambda: llamadas.append(1))
    _ir_a_pestana(frame, frame.creditos_panel)

    frame._limpiar_segun_pestana_activa()

    assert llamadas == [1]


def test_enfocar_busqueda_en_casos_llama_su_propio_metodo(frame, monkeypatch):
    llamadas = []
    monkeypatch.setattr(frame.casos_panel, "enfocar_busqueda", lambda: llamadas.append(1))
    _ir_a_pestana(frame, frame.casos_panel)

    frame._enfocar_busqueda_segun_pestana_activa()

    assert llamadas == [1]


def test_enfocar_busqueda_en_creditos_llama_su_propio_metodo(frame, monkeypatch):
    llamadas = []
    monkeypatch.setattr(frame.creditos_panel, "enfocar_busqueda", lambda: llamadas.append(1))
    _ir_a_pestana(frame, frame.creditos_panel)

    frame._enfocar_busqueda_segun_pestana_activa()

    assert llamadas == [1]


def test_enfocar_busqueda_en_calculadora_no_hace_nada(frame, monkeypatch):
    # La Calculadora no tiene un cuadro de búsqueda equivalente — pedido
    # explícito del usuario, 2026-07-12: solo Casos e Historial de Créditos
    # tienen un comportamiento definido para Ctrl+F.
    llamadas_casos = []
    llamadas_creditos = []
    monkeypatch.setattr(frame.casos_panel, "enfocar_busqueda", lambda: llamadas_casos.append(1))
    monkeypatch.setattr(frame.creditos_panel, "enfocar_busqueda", lambda: llamadas_creditos.append(1))
    _ir_a_pestana(frame, frame.calculadora_panel)

    frame._enfocar_busqueda_segun_pestana_activa()  # no debe lanzar

    assert llamadas_casos == []
    assert llamadas_creditos == []


def test_enfocar_resultados_en_casos_llama_su_propio_metodo(frame, monkeypatch):
    llamadas = []
    monkeypatch.setattr(frame.casos_panel, "enfocar_resultados", lambda: llamadas.append(1))
    _ir_a_pestana(frame, frame.casos_panel)

    frame._enfocar_resultados_segun_pestana_activa()

    assert llamadas == [1]


def test_enfocar_resultados_en_creditos_llama_su_propio_metodo(frame, monkeypatch):
    # Pedido explícito del usuario: "el comando Ctrl+R que lleva a la lista
    # igual tiene que funcionar con el apartado del historial de créditos".
    llamadas = []
    monkeypatch.setattr(frame.creditos_panel, "enfocar_resultados", lambda: llamadas.append(1))
    _ir_a_pestana(frame, frame.creditos_panel)

    frame._enfocar_resultados_segun_pestana_activa()

    assert llamadas == [1]


def test_enfocar_resultados_en_calculadora_no_hace_nada(frame, monkeypatch):
    llamadas_casos = []
    llamadas_creditos = []
    monkeypatch.setattr(frame.casos_panel, "enfocar_resultados", lambda: llamadas_casos.append(1))
    monkeypatch.setattr(frame.creditos_panel, "enfocar_resultados", lambda: llamadas_creditos.append(1))
    _ir_a_pestana(frame, frame.calculadora_panel)

    frame._enfocar_resultados_segun_pestana_activa()  # no debe lanzar

    assert llamadas_casos == []
    assert llamadas_creditos == []
