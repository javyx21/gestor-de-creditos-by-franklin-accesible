"""Pruebas de extremo a extremo del panel "Recordatorios de Llamada"
(RecordatoriosPanel) — construyen el panel real (no mocks) contra una base de
datos temporal, mismo patrón que test_creditos_panel.py."""

from datetime import datetime, timedelta

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.db.recordatorios import listar_recordatorios
from gestor_credito.ui.recordatorios_panel import RecordatoriosPanel, parsear_hora_ui


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
def panel(app, conn):
    # CreateStatusBar(): _autocompletar_por_cedula usa
    # self.GetTopLevelParent().SetStatusText(...) para avisar el resultado de
    # la búsqueda por cédula (ver ese método) — sin barra de estado, wx lanza
    # un wxAssertionError real (confirmado corriendo esta prueba sin esto).
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    notebook = wx.Notebook(frame)
    p = RecordatoriosPanel(notebook)
    notebook.AddPage(p, "Recordatorios de Llamada")
    yield p
    frame.Destroy()


def _llenar_formulario(panel, nombre="Juan Perez", cedula="001-0000001-1",
                        celular="8091234567", empresa="MIDESA",
                        fecha="10/01/2026", hora="09:00", comentarios=""):
    panel.nombre_texto.SetValue(nombre)
    panel.cedula_texto.SetValue(cedula)
    panel.celular_texto.SetValue(celular)
    panel.empresa_texto.SetValue(empresa)
    panel.fecha_texto.SetValue(fecha)
    panel.hora_texto.SetValue(hora)
    panel.comentarios_texto.SetValue(comentarios)


def _filas_lista(panel, columna):
    return [panel.lista.GetItemText(i, columna) for i in range(panel.lista.GetItemCount())]


# --- parsear_hora_ui ----------------------------------------------------------

def test_parsear_hora_ui_valida():
    assert parsear_hora_ui("09:05") == "09:05"


def test_parsear_hora_ui_invalida():
    assert parsear_hora_ui("25:99") is None


def test_parsear_hora_ui_vacia():
    assert parsear_hora_ui("") is None


# --- Alta ----------------------------------------------------------------------

def test_agregar_recordatorio_valido(panel):
    _llenar_formulario(panel)

    panel._guardar()

    assert _filas_lista(panel, 2) == ["Juan Perez"]
    assert panel.mensaje_texto.GetLabel() == "Recordatorio agregado."
    # El formulario se limpia solo después de guardar.
    assert panel.nombre_texto.GetValue() == ""


def test_agregar_sin_nombre_no_guarda(panel):
    _llenar_formulario(panel, nombre="")

    panel._guardar()

    assert panel.lista.GetItemCount() == 0
    assert "nombre" in panel.mensaje_texto.GetLabel().lower()


def test_agregar_con_fecha_invalida_no_guarda(panel):
    _llenar_formulario(panel, fecha="10-01-2026")

    panel._guardar()

    assert panel.lista.GetItemCount() == 0
    assert "fecha" in panel.mensaje_texto.GetLabel().lower()


def test_agregar_con_hora_invalida_no_guarda(panel):
    _llenar_formulario(panel, hora="9pm")

    panel._guardar()

    assert panel.lista.GetItemCount() == 0
    assert "hora" in panel.mensaje_texto.GetLabel().lower()


def test_agregar_recordatorio_guarda_comentarios(panel, conn):
    # Pedido explícito del usuario: contexto de por qué hay que llamar.
    _llenar_formulario(panel, comentarios="Pendiente enviar estado de cuenta")

    panel._guardar()

    assert listar_recordatorios(conn)[0]["comentarios"] == "Pendiente enviar estado de cuenta"


def test_agregar_recordatorio_sin_comentarios_queda_vacio_en_la_lista(panel):
    _llenar_formulario(panel)

    panel._guardar()

    assert _filas_lista(panel, 6) == [panel.CELDA_VACIA]


# --- Ctrl+R: enfocar_resultados -------------------------------------------------
# Pedido explícito del usuario, 2026-09-07: "con control r vamos a caer en la
# lista, ese lo dejaremos como comando universal en las listas de clientes
# menos en las calculadoras".

def test_enfocar_resultados_selecciona_y_enfoca_la_primera_fila(panel):
    _llenar_formulario(panel)
    panel._guardar()

    panel.enfocar_resultados()

    assert panel.lista.GetFirstSelected() == 0


def test_enfocar_resultados_sin_filas_no_lanza(panel):
    panel.enfocar_resultados()  # no debe lanzar, lista vacía


# --- Ocultar/revelar el bloque de campos ----------------------------------------
# Pedido explícito del usuario, 2026-09-07: "mientras no vayamos a añadir a
# alguien estos campos deben de estar ocultos" — y el botón que agrega/guarda
# tiene que quedar SIEMPRE visible (corregido tras señalar que un botón
# aparte solo para revelar el formulario era redundante).

def test_bloque_de_campos_oculto_por_defecto(panel):
    assert panel._panel_formulario.IsShown() is False


def test_click_en_agregar_con_bloque_oculto_solo_lo_revela(panel, conn):
    panel._on_click_guardar(None)

    assert panel._panel_formulario.IsShown() is True
    assert panel.lista.GetItemCount() == 0  # no guardó nada, solo reveló


def test_click_en_agregar_con_bloque_visible_guarda(panel):
    panel._on_click_guardar(None)  # primer clic: revela
    _llenar_formulario(panel)

    panel._on_click_guardar(None)  # segundo clic: guarda

    assert _filas_lista(panel, 2) == ["Juan Perez"]


def test_ctrl_shift_a_revela_el_bloque(panel):
    evento = wx.KeyEvent(wx.EVT_CHAR_HOOK.typeId)
    evento.SetControlDown(True)
    evento.SetShiftDown(True)
    evento.SetKeyCode(ord("A"))

    panel._on_atajo(evento)

    assert panel._panel_formulario.IsShown() is True


def test_guardar_oculta_el_bloque_de_nuevo(panel):
    _llenar_formulario(panel)
    panel._mostrar_formulario()

    panel._guardar()

    assert panel._panel_formulario.IsShown() is False


def test_marcar_atendido_oculta_el_bloque_de_nuevo(panel):
    _llenar_formulario(panel)
    panel._guardar()
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    panel._on_marcar_atendido(None)

    assert panel._panel_formulario.IsShown() is False


def test_eliminar_oculta_el_bloque_de_nuevo(panel, monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.YES)
    _llenar_formulario(panel)
    panel._guardar()
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    panel._on_eliminar(None)

    assert panel._panel_formulario.IsShown() is False


def test_seleccionar_fila_revela_el_bloque(panel):
    _llenar_formulario(panel)
    panel._guardar()
    assert panel._panel_formulario.IsShown() is False  # se ocultó al guardar

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    assert panel._panel_formulario.IsShown() is True


def test_limpiar_formulario_oculta_el_bloque(panel):
    panel._mostrar_formulario()

    panel.limpiar_formulario()

    assert panel._panel_formulario.IsShown() is False


# --- Ctrl+Enter en Comentarios guarda ---------------------------------------------
# Pedido explícito del usuario: Enter solo hace salto de línea normal;
# Ctrl+Enter guarda, como si se hiciera Tab hasta el botón y se lo presionara.

def _evento_tecla(keycode, ctrl=False):
    evento = wx.KeyEvent(wx.EVT_KEY_DOWN.typeId)
    evento.SetControlDown(ctrl)
    evento.SetKeyCode(keycode)
    return evento


def test_ctrl_enter_en_comentarios_guarda(panel):
    panel._mostrar_formulario()
    _llenar_formulario(panel, comentarios="Motivo de la llamada")

    panel._on_tecla_comentarios(_evento_tecla(wx.WXK_RETURN, ctrl=True))

    assert _filas_lista(panel, 2) == ["Juan Perez"]


def test_enter_solo_en_comentarios_no_guarda(panel, monkeypatch):
    llamadas = []
    monkeypatch.setattr(panel, "_guardar", lambda: llamadas.append(1))
    panel._mostrar_formulario()

    evento = _evento_tecla(wx.WXK_RETURN, ctrl=False)
    panel._on_tecla_comentarios(evento)

    assert llamadas == []
    assert evento.GetSkipped()  # se dejó pasar para el salto de línea nativo


# --- Selección / edición -------------------------------------------------------

def test_seleccionar_fila_carga_el_formulario(panel):
    _llenar_formulario(panel, comentarios="Llamar por atraso en cuota")
    panel._guardar()

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    assert panel.nombre_texto.GetValue() == "Juan Perez"
    assert panel.comentarios_texto.GetValue() == "Llamar por atraso en cuota"
    assert panel.guardar_btn.GetLabel() == "&Guardar cambios"
    assert panel.marcar_atendido_btn.IsEnabled()
    assert panel.eliminar_btn.IsEnabled()


def test_guardar_cambios_sobre_fila_seleccionada_actualiza(panel):
    _llenar_formulario(panel)
    panel._guardar()
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    panel.nombre_texto.SetValue("Juana Perez")
    panel._guardar()

    assert _filas_lista(panel, 2) == ["Juana Perez"]
    assert panel.mensaje_texto.GetLabel() == "Cambios guardados."


def test_marcar_atendido(panel, monkeypatch):
    sonidos = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorios_panel.reproducir_sonido", lambda nombre: sonidos.append(nombre)
    )
    _llenar_formulario(panel)
    panel._guardar()
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    panel._on_marcar_atendido(None)

    assert _filas_lista(panel, 7) == ["Atendida"]


def test_eliminar_con_confirmacion(panel, monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.YES)
    _llenar_formulario(panel)
    panel._guardar()
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    panel._on_eliminar(None)

    assert panel.lista.GetItemCount() == 0


def test_eliminar_sin_confirmacion_no_borra(panel, monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.NO)
    _llenar_formulario(panel)
    panel._guardar()
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    panel._on_eliminar(None)

    assert panel.lista.GetItemCount() == 1


# --- Ctrl+D --------------------------------------------------------------------

def test_limpiar_formulario_reproduce_sonido_y_limpia_campos(panel, monkeypatch):
    sonidos = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorios_panel.reproducir_sonido", lambda nombre: sonidos.append(nombre)
    )
    _llenar_formulario(panel)

    panel.limpiar_formulario()

    assert panel.nombre_texto.GetValue() == ""
    assert panel.guardar_btn.GetLabel() == "A&gregar recordatorio"
    assert len(sonidos) == 1


# --- Autocompletado por cédula --------------------------------------------------
# Busca en Historial de Créditos (reporte_credito), NO en Casos — corregido
# 2026-09-07 tras un reporte real del usuario ("es en el histórico que
# tienes que buscar, no en casos"). reporte_credito no tiene columna de
# teléfono, así que Celular nunca se autocompleta desde acá.

def _crear_credito(conn, cedula, nombre_cliente, empresa, no_credito="C-1"):
    conn.execute(
        "INSERT INTO reporte_credito (no_credito, cedula, nombre_cliente, empresa_convenio, "
        "fecha_desembolso) VALUES (?, ?, ?, ?, '2026-01-01')",
        (no_credito, cedula, nombre_cliente, empresa),
    )
    conn.commit()


def test_autocompletar_por_cedula_rellena_campos_vacios(panel, conn):
    _crear_credito(conn, "001-9999999-9", "Cliente Existente", "NICAES")
    panel.cedula_texto.SetValue("001-9999999-9")

    panel._autocompletar_por_cedula()

    assert panel.nombre_texto.GetValue() == "Cliente Existente"
    assert panel.celular_texto.GetValue() == ""  # reporte_credito no tiene teléfono
    assert panel.empresa_texto.GetValue() == "NICAES"


def test_autocompletar_por_cedula_no_pisa_campo_ya_escrito(panel, conn):
    _crear_credito(conn, "001-9999999-9", "Cliente Existente", "NICAES")
    panel.cedula_texto.SetValue("001-9999999-9")
    panel.nombre_texto.SetValue("Nombre Escrito A Mano")

    panel._autocompletar_por_cedula()

    assert panel.nombre_texto.GetValue() == "Nombre Escrito A Mano"
    assert panel.empresa_texto.GetValue() == "NICAES"


def test_autocompletar_por_cedula_sin_coincidencia_no_hace_nada(panel):
    panel.cedula_texto.SetValue("000-0000000-0")

    panel._autocompletar_por_cedula()  # no debe lanzar

    assert panel.nombre_texto.GetValue() == ""


def test_autocompletar_por_cedula_minuscula_encuentra_y_normaliza_a_mayuscula(panel, conn):
    # Pedido explícito del usuario: minúscula/mayúscula debe ser indiferente
    # (nunca un error), y el cuadro debe quedar en MAYÚSCULA después.
    _crear_credito(conn, "2011307810010Q", "Cliente Con Letra", "MIDESA")
    panel.cedula_texto.SetValue("2011307810010q")

    panel._autocompletar_por_cedula()

    assert panel.cedula_texto.GetValue() == "2011307810010Q"
    assert panel.nombre_texto.GetValue() == "Cliente Con Letra"


def test_guardar_normaliza_cedula_a_mayuscula_aunque_no_se_haya_buscado(panel, conn):
    # Defensa extra: aunque por algún motivo _guardar se dispare sin pasar
    # por _autocompletar_por_cedula, la cédula guardada nunca debe quedar en
    # minúscula.
    _llenar_formulario(panel, cedula="001-0000001-1q")

    panel._guardar()

    assert listar_recordatorios(conn)[0]["cedula"] == "001-0000001-1Q"


def test_autocompletar_por_cedula_encontrado_avisa_por_voz(panel, conn, monkeypatch):
    # Bug real reportado por el usuario: rellenar Nombre/Celular/Empresa con
    # SetValue() no avisaba nada por voz porque el foco se queda en Cédula —
    # ver el docstring de _autocompletar_por_cedula.
    voces = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorios_panel.anunciar_voz_nvda", lambda texto: voces.append(texto)
    )
    _crear_credito(conn, "001-9999999-9", "Cliente Existente", "NICAES")
    panel.cedula_texto.SetValue("001-9999999-9")

    panel._autocompletar_por_cedula()

    assert len(voces) == 1
    assert "Cliente Existente" in voces[0]


def test_autocompletar_por_cedula_sin_coincidencia_avisa_por_voz(panel, monkeypatch):
    # Segunda mitad del mismo bug: tampoco avisaba nada cuando NO encontraba
    # a nadie, así que presionar Enter con una cédula que sí existe (pero
    # con un typo, por ejemplo) se sentía exactamente igual que si no
    # hubiera pasado nada.
    voces = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorios_panel.anunciar_voz_nvda", lambda texto: voces.append(texto)
    )
    panel.cedula_texto.SetValue("000-0000000-0")

    panel._autocompletar_por_cedula()

    assert len(voces) == 1
    assert "000-0000000-0" in voces[0]


def test_cambiar_cedula_de_fila_seleccionada_desengancha_y_guardar_crea_otro(panel, conn):
    # Bug real reportado por el usuario ("sobreescribí un cliente por encima
    # de otro"): seleccionar una fila para verla dejaba el formulario
    # "enganchado" a ese registro; si después el oficial escribía la cédula
    # de OTRA persona sin darse cuenta, "Guardar cambios" pisaba el registro
    # viejo en vez de crear uno nuevo.
    _llenar_formulario(panel, nombre="Primera Persona", cedula="001-1111111-1")
    panel._guardar()
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)
    assert panel.guardar_btn.GetLabel() == "&Guardar cambios"

    # El oficial escribe la cédula de una persona DISTINTA sin limpiar antes.
    panel.cedula_texto.SetValue("002-2222222-2")
    panel._autocompletar_por_cedula()

    assert panel.guardar_btn.GetLabel() == "A&gregar recordatorio"
    assert panel.nombre_texto.GetValue() == ""  # ya no arrastra "Primera Persona"

    panel.nombre_texto.SetValue("Segunda Persona")
    panel.fecha_texto.SetValue("10/01/2026")
    panel.hora_texto.SetValue("09:00")
    panel._guardar()

    nombres = _filas_lista(panel, 2)
    assert nombres == ["Primera Persona", "Segunda Persona"]  # las dos existen, ninguna se pisó


# --- Resaltado de filas vencidas -------------------------------------------------

def test_fila_vencida_se_resalta_y_suena_al_seleccionar(panel, conn, monkeypatch):
    sonidos = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorios_panel.reproducir_sonido", lambda nombre: sonidos.append(nombre)
    )
    pasado = datetime.now() - timedelta(minutes=10)
    _llenar_formulario(
        panel, nombre="Vencido Ya",
        fecha=pasado.strftime("%d/%m/%Y"), hora=pasado.strftime("%H:%M"),
    )
    panel._guardar()

    assert _filas_lista(panel, 7) == ["Vencido"]
    color_fondo = panel.lista.GetItemBackgroundColour(0)
    assert color_fondo == panel._COLOR_FONDO_VENCIDO

    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, panel.lista.GetId())
    evento.SetIndex(0)
    panel._on_seleccionar(evento)

    assert sonidos  # sonó al menos una vez
