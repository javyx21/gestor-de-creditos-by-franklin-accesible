"""Pruebas de los atajos GLOBALES Ctrl+F/Ctrl+D/Ctrl+1..3 de MainFrame, cuyo
efecto ahora depende de la pestaña activa del notebook (pedido explícito del
usuario, 2026-07-12) — ver MainFrame._enfocar_busqueda_segun_pestana_activa /
_limpiar_segun_pestana_activa / _ir_a_casos (etc.). Construye un MainFrame
real (no mocks) contra una base de datos temporal, mismo patrón que el resto
de la suite."""

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


def test_limpiar_en_casos_llama_limpiar_todo(frame, monkeypatch):
    # 2026-08-16: Ctrl+D unifica en Casos lo que antes eran dos atajos
    # separados (Alt+L para el panel de edición, Alt+V para la búsqueda) en
    # un solo método, CasosPanel.limpiar_todo().
    llamadas = []
    monkeypatch.setattr(frame.casos_panel, "limpiar_todo", lambda: llamadas.append(1))
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


# Ctrl+1/Ctrl+2/Ctrl+3 — pedido explícito del usuario, 2026-08-16: navegación
# rápida directa a una pestaña específica, sin depender de Ctrl+Tab (que solo
# avanza/retrocede en orden). Se prueba desde las tres pestañas de origen
# posibles para confirmar que el destino no depende de la pestaña de partida.
def test_ctrl_1_va_a_casos_desde_cualquier_pestana(frame):
    _ir_a_pestana(frame, frame.creditos_panel)
    frame._ir_a_casos()
    assert frame.notebook.GetCurrentPage() is frame.casos_panel


def test_ctrl_2_va_a_calculadora_desde_cualquier_pestana(frame):
    _ir_a_pestana(frame, frame.creditos_panel)
    frame._ir_a_calculadora()
    assert frame.notebook.GetCurrentPage() is frame.calculadora_panel


def test_ctrl_3_va_a_creditos_desde_cualquier_pestana(frame):
    _ir_a_pestana(frame, frame.casos_panel)
    frame._ir_a_creditos()
    assert frame.notebook.GetCurrentPage() is frame.creditos_panel


def test_ir_a_pestana_recarga_datos_y_anuncia_por_voz(frame, monkeypatch):
    # self.notebook.SetSelection() dispara EVT_NOTEBOOK_PAGE_CHANGED en esta
    # app (verificado empíricamente) — _ir_a_creditos() no debe duplicar la
    # lógica de _on_cambiar_pestana(), solo dejar que el evento la dispare
    # sola, igual que un clic de mouse o Ctrl+Tab.
    llamadas_recargar = []
    llamadas_voz = []
    monkeypatch.setattr(frame.creditos_panel, "recargar", lambda: llamadas_recargar.append(1))
    monkeypatch.setattr(
        "gestor_credito.ui.main_frame.anunciar_voz_nvda",
        lambda texto: llamadas_voz.append(texto),
    )
    _ir_a_pestana(frame, frame.casos_panel)

    frame._ir_a_creditos()

    assert llamadas_recargar == [1]
    assert llamadas_voz == ["Historial de Créditos"]


def test_ctrl_1_repetido_en_casos_no_falla(frame):
    # Pedir la pestaña que ya está activa no debe lanzar ni tener efecto
    # distinto a quedarse donde está.
    _ir_a_pestana(frame, frame.casos_panel)
    frame._ir_a_casos()
    assert frame.notebook.GetCurrentPage() is frame.casos_panel


# ---- Ayuda > Actualizaciones (submenú nativo, 2026-08-20) -------------------
# Ver gestor_credito/ui/actualizacion_dialog.py: MainFrame solo guarda el
# estado de la última búsqueda (para que "Información sobre la versión" no
# tenga que volver a golpear la red) y delega toda la lógica real ahí.


def test_estado_inicial_de_actualizaciones_no_verificado(frame):
    assert frame._ultima_busqueda_actualizacion_realizada is False
    assert frame._ultima_actualizacion_encontrada is None


def test_buscar_actualizaciones_actualiza_el_estado_guardado(frame, monkeypatch):
    from gestor_credito.actualizador.actualizador import ActualizacionDisponible

    disponible = ActualizacionDisponible(version="9.9.9", url_descarga="https://x", sha256="abc")

    def _buscar_falso(parent, al_completar):
        al_completar(disponible)

    monkeypatch.setattr("gestor_credito.ui.main_frame.buscar_actualizaciones", _buscar_falso)

    frame._on_buscar_actualizaciones(None)

    assert frame._ultima_busqueda_actualizacion_realizada is True
    assert frame._ultima_actualizacion_encontrada is disponible


def test_informacion_version_usa_el_estado_guardado(frame, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.main_frame.mostrar_informacion_version",
        lambda parent, realizada, encontrada: llamadas.append((parent, realizada, encontrada)),
    )

    frame._on_informacion_version(None)

    assert llamadas == [(frame, False, None)]
