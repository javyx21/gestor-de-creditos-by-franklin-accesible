"""Pruebas del modal de alarma de "Recordatorios de Llamada"
(RecordatorioAlarmaDialog) — se construye directo con una lista de filas de
prueba, SIN ShowModal() real ni depender del wx.Timer real disparando solo
(no hay MainLoop en las pruebas, ver test_main_frame.py para el mismo
criterio con el temporizador de MainFrame). Se invoca el método del tick de
sonido directamente en vez de esperar el temporizador real."""

import wx
import pytest

from gestor_credito.db import database
from gestor_credito.db.recordatorios import crear_recordatorio, listar_recordatorios
from gestor_credito.ui.recordatorio_alarma_dialog import RecordatorioAlarmaDialog


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


class _EventoFalso:
    def __init__(self):
        self.skip_llamado = False

    def Skip(self):
        self.skip_llamado = True


def _crear_fila_vencida(conn, nombre="Juan Perez", cedula="001", celular="8091234567",
                         empresa="MIDESA", comentarios=None):
    recordatorio_id = crear_recordatorio(
        conn, nombre, cedula, celular, empresa, "2026-01-10", "09:00", "fmartinez", comentarios
    )
    return {
        "id": recordatorio_id, "nombre": nombre, "cedula": cedula, "celular": celular,
        "empresa_convenio": empresa, "fecha_llamar": "2026-01-10", "hora_llamar": "09:00",
        "comentarios": comentarios,
    }


@pytest.fixture
def dialogo(app, conn, monkeypatch):
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.anunciar_voz_nvda", lambda texto: None
    )
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.reproducir_sonido", lambda nombre: None
    )
    filas = [_crear_fila_vencida(conn)]
    d = RecordatorioAlarmaDialog(None, filas)
    yield d
    d.Destroy()


def test_suena_tres_veces_en_total(app, conn, monkeypatch):
    sonidos = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.anunciar_voz_nvda", lambda texto: None
    )
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.reproducir_sonido", lambda nombre: sonidos.append(nombre)
    )
    filas = [_crear_fila_vencida(conn)]
    d = RecordatorioAlarmaDialog(None, filas)
    try:
        # __init__ ya disparó el primer tick; el wx.Timer real no dispara
        # solo sin MainLoop, así que se simulan los otros dos a mano.
        d._on_tick_sonido(None)
        d._on_tick_sonido(None)

        assert len(sonidos) == 3
    finally:
        d.Destroy()


def test_anuncia_por_voz_al_mostrarse(app, conn, monkeypatch):
    voces = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.anunciar_voz_nvda", lambda texto: voces.append(texto)
    )
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.reproducir_sonido", lambda nombre: None
    )
    filas = [_crear_fila_vencida(conn, nombre="Ana Rojas", cedula="002", celular="8092223333", empresa="NICAES")]
    d = RecordatorioAlarmaDialog(None, filas)
    try:
        assert len(voces) == 1
        assert "Ana Rojas" in voces[0]
        assert "002" in voces[0]
        assert "NICAES" in voces[0]
        assert "8092223333" in voces[0]
    finally:
        d.Destroy()


def test_anuncia_por_voz_incluye_el_comentario(app, conn, monkeypatch):
    # Pedido explícito del usuario: el contexto de la llamada tiene que
    # estar disponible justo cuando suena la alarma, no solo en la lista.
    voces = []
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.anunciar_voz_nvda", lambda texto: voces.append(texto)
    )
    monkeypatch.setattr(
        "gestor_credito.ui.recordatorio_alarma_dialog.reproducir_sonido", lambda nombre: None
    )
    filas = [_crear_fila_vencida(conn, comentarios="Pendiente enviar estado de cuenta")]
    d = RecordatorioAlarmaDialog(None, filas)
    try:
        assert "Pendiente enviar estado de cuenta" in voces[0]
    finally:
        d.Destroy()


def test_lista_muestra_todos_los_recordatorios(dialogo):
    assert dialogo.lista.GetItemCount() == 1
    assert dialogo.lista.GetItemText(0, 2) == "Juan Perez"


def test_marcar_atendida_marca_en_bd_y_cierra_si_no_queda_ninguna(dialogo, conn, monkeypatch):
    llamadas_end_modal = []
    monkeypatch.setattr(dialogo, "EndModal", lambda codigo: llamadas_end_modal.append(codigo))
    estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
    dialogo.lista.SetItemState(0, estado, estado)

    dialogo._on_marcar_atendida(None)

    filas = listar_recordatorios(conn)
    assert filas[0]["atendido"] == 1
    assert llamadas_end_modal == [wx.ID_OK]


def test_marcar_atendida_sin_seleccion_no_hace_nada(dialogo, conn):
    dialogo.lista.SetItemState(0, 0, wx.LIST_STATE_SELECTED)

    dialogo._on_marcar_atendida(None)  # no debe lanzar

    filas = listar_recordatorios(conn)
    assert filas[0]["atendido"] == 0


def test_posponer_pospone_en_bd_y_deja_que_el_cierre_nativo_continue(dialogo, conn):
    evento = _EventoFalso()

    dialogo._on_posponer(evento)

    filas = listar_recordatorios(conn)
    assert filas[0]["pospuesto_hasta"] is not None
    assert evento.skip_llamado is True


def test_posponer_btn_usa_id_cancel_para_que_escape_lo_dispare_gratis(dialogo):
    assert dialogo.posponer_btn.GetId() == wx.ID_CANCEL
