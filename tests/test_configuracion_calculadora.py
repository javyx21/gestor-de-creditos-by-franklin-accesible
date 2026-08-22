"""Pruebas de extremo a extremo de "Configuración ▸ Configuración de la
Calculadora" (empresas convenio / tasas) — construyen un
ConfiguracionCalculadoraPanel real (no mocks) contra una base de datos
temporal, y simulan exactamente el escenario reportado por el usuario
(2026-07-12): varios cambios consecutivos de tasa, reapertura del panel,
alta y baja de empresas — verificando en cada paso que lo que la base de
datos tiene, lo que _convenios_cargados (el caché en memoria del panel)
tiene, y lo que la lista/campos muestran en pantalla coinciden entre sí. No
se pudo reproducir ninguna divergencia con estas pruebas, pero quedan como
regresión permanente.

Hasta 2026-08-22 este panel era una de 3 categorías dentro de un único
ConfiguracionPanel con árbol interno — ahora es su propia clase, abierta
directo desde el menú de cascada "Configuración" (ver main_frame.py)."""

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.db.convenios import obtener_tasa
from gestor_credito.ui.configuracion_panel import ConfiguracionCalculadoraPanel


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
    """ConfiguracionCalculadoraPanel llama self.GetTopLevelParent().SetStatusText(...)
    tras cada guardado (igual que en la app real, donde el padre real es
    _PanelDialog, que expone su propio SetStatusText) — un wx.Frame liso
    no tiene barra de estado a menos que se la pidamos explícitamente."""
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    return frame


@pytest.fixture
def panel(app, conn):
    frame = _frame_con_status_bar()
    panel = ConfiguracionCalculadoraPanel(frame)
    yield panel
    frame.Destroy()


def _seleccionar_empresa(panel, empresa):
    """Simula seleccionar en convenios_lista la fila de `empresa` (por
    nombre, no por índice fijo — el orden alfabético puede desplazarse si
    se agregó/borró alguna empresa antes en la misma prueba)."""
    indice = next(i for i, (e, _t) in enumerate(panel._convenios_cargados) if e == empresa)
    panel.convenios_lista.SetItemState(indice, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.convenios_lista.GetId())
    evento.SetIndex(indice)
    panel._on_seleccionar_convenio(evento)


def _tasa_en_lista(panel, empresa):
    """Tasa (como texto porcentaje, p. ej. '60%') que la lista MUESTRA
    actualmente para `empresa`, leyendo la celda real del widget — no el
    caché _convenios_cargados — para detectar justo el tipo de divergencia
    entre "dato interno" y "lo que se ve en pantalla" que reportó el
    usuario."""
    for fila in range(panel.convenios_lista.GetItemCount()):
        if panel.convenios_lista.GetItemText(fila, 0) == empresa:
            return panel.convenios_lista.GetItemText(fila, 1)
    return None


def _editar_tasa(panel, empresa, nueva_tasa_texto):
    _seleccionar_empresa(panel, empresa)
    panel.convenio_tasa_texto.SetValue(nueva_tasa_texto)
    panel._on_guardar_convenio(None)


def test_una_edicion_persiste_en_bd_cache_y_lista(panel, conn):
    _editar_tasa(panel, "MIDESA", "60")

    assert obtener_tasa(conn, "MIDESA") == 0.6
    assert dict(panel._convenios_cargados)["MIDESA"] == 0.6
    assert _tasa_en_lista(panel, "MIDESA") == "60%"
    assert panel.convenio_tasa_texto.GetValue() == "60"


def test_dos_ediciones_consecutivas_de_la_misma_empresa_persisten_ambas(panel, conn):
    _editar_tasa(panel, "MIDESA", "60")
    _editar_tasa(panel, "MIDESA", "70")

    assert obtener_tasa(conn, "MIDESA") == 0.7
    assert dict(panel._convenios_cargados)["MIDESA"] == 0.7
    assert _tasa_en_lista(panel, "MIDESA") == "70%"
    assert panel.convenio_tasa_texto.GetValue() == "70"


def test_cinco_ediciones_consecutivas_persisten_la_ultima(panel, conn):
    for valor in ("20", "35", "41.5", "60", "18"):
        _editar_tasa(panel, "MIDESA", valor)

    assert obtener_tasa(conn, "MIDESA") == 0.18
    assert _tasa_en_lista(panel, "MIDESA") == "18%"


def test_reabrir_el_panel_muestra_el_ultimo_valor_guardado(app, conn):
    frame = _frame_con_status_bar()
    panel1 = ConfiguracionCalculadoraPanel(frame)
    _editar_tasa(panel1, "MIDESA", "60")
    _editar_tasa(panel1, "MIDESA", "70")
    frame.Destroy()

    # "Reabrir el panel" = una instancia nueva de ConfiguracionCalculadoraPanel,
    # tal cual hace _PanelDialog en main_frame.py cada vez que se abre
    # Configuración > Configuración de la Calculadora (nunca reutiliza una
    # instancia anterior).
    frame2 = _frame_con_status_bar()
    panel2 = ConfiguracionCalculadoraPanel(frame2)
    assert dict(panel2._convenios_cargados)["MIDESA"] == 0.7
    assert _tasa_en_lista(panel2, "MIDESA") == "70%"
    frame2.Destroy()


def test_ediciones_alternadas_de_dos_empresas_no_se_mezclan(panel, conn):
    _editar_tasa(panel, "MIDESA", "60")
    _editar_tasa(panel, "NICAES", "10")
    _editar_tasa(panel, "MIDESA", "70")
    _editar_tasa(panel, "NICAES", "20")

    assert obtener_tasa(conn, "MIDESA") == 0.7
    assert obtener_tasa(conn, "NICAES") == 0.2
    assert _tasa_en_lista(panel, "MIDESA") == "70%"
    assert _tasa_en_lista(panel, "NICAES") == "20%"


def test_guardar_reselecciona_la_fila_editada_y_habilita_eliminar(panel, conn):
    _editar_tasa(panel, "MIDESA", "60")

    seleccionadas = [
        panel.convenios_lista.GetItemText(i, 0)
        for i in range(panel.convenios_lista.GetItemCount())
        if panel.convenios_lista.GetItemState(i, wx.LIST_STATE_SELECTED)
    ]
    assert seleccionadas == ["MIDESA"]
    assert panel.eliminar_convenio_btn.IsEnabled()


def test_agregar_empresa_nueva_y_luego_editarla_persiste(panel, conn):
    panel._on_nueva_empresa(None)
    panel.convenio_empresa_texto.SetValue("EMPRESA DE PRUEBA")
    panel.convenio_tasa_texto.SetValue("18.5")
    panel._on_guardar_convenio(None)
    assert obtener_tasa(conn, "EMPRESA DE PRUEBA") == 0.185

    _editar_tasa(panel, "EMPRESA DE PRUEBA", "22")
    assert obtener_tasa(conn, "EMPRESA DE PRUEBA") == 0.22
    assert _tasa_en_lista(panel, "EMPRESA DE PRUEBA") == "22%"


def test_eliminar_empresa_la_quita_y_no_reaparece_al_reabrir(app, conn):
    frame = _frame_con_status_bar()
    panel1 = ConfiguracionCalculadoraPanel(frame)
    panel1._on_nueva_empresa(None)
    panel1.convenio_empresa_texto.SetValue("EMPRESA DE PRUEBA")
    panel1.convenio_tasa_texto.SetValue("18.5")
    panel1._on_guardar_convenio(None)

    _seleccionar_empresa(panel1, "EMPRESA DE PRUEBA")
    # eliminar_convenio() en sí (la escritura a la base) — sin pasar por
    # _on_eliminar_convenio, que abre un wx.MessageBox de confirmación y
    # bloquearía la prueba esperando una respuesta interactiva.
    from gestor_credito.db.convenios import eliminar_convenio
    eliminar_convenio(conn, "EMPRESA DE PRUEBA")
    panel1._cargar_convenios()
    panel1._on_nueva_empresa(None)
    frame.Destroy()

    assert obtener_tasa(conn, "EMPRESA DE PRUEBA") is None

    frame2 = _frame_con_status_bar()
    panel2 = ConfiguracionCalculadoraPanel(frame2)
    assert "EMPRESA DE PRUEBA" not in dict(panel2._convenios_cargados)
    assert _tasa_en_lista(panel2, "EMPRESA DE PRUEBA") is None
    frame2.Destroy()


def test_tasa_vacia_se_guarda_como_sin_configurar(panel, conn):
    _editar_tasa(panel, "GRUPO TALSE", "")
    assert obtener_tasa(conn, "GRUPO TALSE") is None
    assert _tasa_en_lista(panel, "GRUPO TALSE") == "sin configurar"

    _editar_tasa(panel, "GRUPO TALSE", "25")
    assert obtener_tasa(conn, "GRUPO TALSE") == 0.25


def test_escribir_empresa_existente_en_minuscula_no_crea_duplicado(panel, conn):
    # Reporte real del usuario (2026-07-12): "MIDESA"/"midesa" habían
    # quedado coexistiendo como dos filas — empresa_convenio es TEXT
    # PRIMARY KEY con colación BINARY (sensible a mayúsculas) por defecto.
    panel._on_nueva_empresa(None)
    panel.convenio_empresa_texto.SetValue("midesa")
    panel.convenio_tasa_texto.SetValue("60")
    panel._on_guardar_convenio(None)

    filas_midesa = [e for e, _t in panel._convenios_cargados if e.upper() == "MIDESA"]
    assert filas_midesa == ["MIDESA"]  # una sola fila, con la capitalización original
    assert obtener_tasa(conn, "MIDESA") == 0.6

    total = conn.execute("SELECT COUNT(*) FROM convenio_tasa").fetchone()[0]
    assert total == 29  # no se agregó ninguna fila nueva


def test_enter_en_cuadro_de_tasa_guarda_igual_que_el_boton(panel, conn):
    _seleccionar_empresa(panel, "MIDESA")
    panel.convenio_tasa_texto.SetValue("60")
    panel._on_guardar_convenio(None, mensaje_hablado="Tasa actualizada.")

    assert obtener_tasa(conn, "MIDESA") == 0.6
    assert _tasa_en_lista(panel, "MIDESA") == "60%"
