import wx

from gestor_credito.db.database import get_connection
from gestor_credito.db.recordatorios import marcar_atendido, posponer_recordatorio
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.fechas import formatear_fecha
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import SONIDO_ACTUALIZACION_DISPONIBLE, reproducir_sonido

MINUTOS_POSPONER = 5

# Pedido explícito del usuario: "que suene tres veces el sonidito... el de
# cuando hay disponible una actualización" — reutiliza SONIDO_ACTUALIZACION_DISPONIBLE
# tal cual, sin un .wav propio.
_REPETICIONES_SONIDO = 3
_INTERVALO_SONIDO_MS = 800

COLUMNAS = ["Fecha", "Hora", "Nombre", "Cédula", "Celular", "Empresa"]


class RecordatorioAlarmaDialog(wx.Dialog):
    """La alarma real que "invade la pantalla" al llegar la hora de un
    recordatorio de llamada (ver MainFrame._on_verificar_recordatorios) —
    pedido explícito del usuario tras rechazar Notificaciones por no llamar su
    atención de verdad ("que suene pero que suene en serio").

    Al mostrarse suena 3 veces SONIDO_ACTUALIZACION_DISPONIBLE (mismo sonido
    de "hay actualización disponible", pedido explícito) y anuncia por voz a
    quién hay que llamar. "&Marcar como atendida" apaga la alarma para
    siempre para la fila seleccionada; "&Posponer 5 minutos" (id=wx.ID_CANCEL,
    así Escape lo dispara gratis vía el manejo nativo de wx.Dialog, sin
    EVT_CHAR_HOOK a mano) pospone TODO lo que siga listado acá — el
    temporizador de MainFrame vuelve a mostrar este mismo ciclo (sonido x3 +
    voz + modal) pasado ese tiempo si para entonces sigue sin atenderse."""

    def __init__(self, parent, recordatorios):
        super().__init__(
            parent, title="Recordatorio de llamada",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._recordatorios = list(recordatorios)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Tenés llamadas pendientes")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        nombre_accesible(self.lista, "Recordatorios de llamada pendientes")
        for indice, columna in enumerate(COLUMNAS):
            self.lista.InsertColumn(indice, columna)
            self.lista.SetColumnWidth(indice, wx.LIST_AUTOSIZE_USEHEADER)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        fila_botones = wx.BoxSizer(wx.HORIZONTAL)

        self.atendida_btn = wx.Button(self, label="&Marcar como atendida")
        self.atendida_btn.Bind(wx.EVT_BUTTON, self._on_marcar_atendida)
        activar_con_enter(self.atendida_btn)
        fila_botones.Add(self.atendida_btn, 0, wx.RIGHT, 8)

        self.posponer_btn = wx.Button(
            self, id=wx.ID_CANCEL, label=f"&Posponer {MINUTOS_POSPONER} minutos"
        )
        self.Bind(wx.EVT_BUTTON, self._on_posponer, self.posponer_btn)
        activar_con_enter(self.posponer_btn)
        fila_botones.Add(self.posponer_btn, 0)

        sizer.Add(fila_botones, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.SetSize((640, 360))

        self._refrescar_lista()
        if self.lista.GetItemCount() > 0:
            estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
            self.lista.SetItemState(0, estado, estado)

        # Sonido en ráfaga de 3, espaciado (no wx.MilliSleep bloqueante, que
        # frenaría a NVDA mientras se arma el diálogo) — wx.Timer propio de
        # este diálogo, no el temporizador de 30s de MainFrame.
        self._sonidos_reproducidos = 0
        self._temporizador_sonido = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick_sonido, self._temporizador_sonido)
        self._on_tick_sonido(None)
        self._temporizador_sonido.Start(_INTERVALO_SONIDO_MS)

        anunciar_voz_nvda(self._resumen_hablado())

    def _resumen_hablado(self):
        primero = self._recordatorios[0]
        base = (
            f"Recordatorio de llamada: llamar a {primero['nombre']}, "
            f"cédula {primero['cedula'] or 'sin cédula'}, "
            f"{primero['empresa_convenio'] or 'sin empresa'}, "
            f"teléfono {primero['celular'] or 'sin teléfono'}."
        )
        if len(self._recordatorios) > 1:
            return f"Tenés {len(self._recordatorios)} recordatorios de llamada pendientes. {base}"
        return base

    def _on_tick_sonido(self, event):
        self._sonidos_reproducidos += 1
        reproducir_sonido(SONIDO_ACTUALIZACION_DISPONIBLE)
        if self._sonidos_reproducidos >= _REPETICIONES_SONIDO:
            self._temporizador_sonido.Stop()

    def _refrescar_lista(self):
        self.lista.DeleteAllItems()
        for recordatorio in self._recordatorios:
            valores = [
                formatear_fecha(recordatorio["fecha_llamar"]), recordatorio["hora_llamar"] or "",
                recordatorio["nombre"] or "", recordatorio["cedula"] or "",
                recordatorio["celular"] or "", recordatorio["empresa_convenio"] or "",
            ]
            indice = self.lista.InsertItem(self.lista.GetItemCount(), valores[0])
            for columna, valor in enumerate(valores[1:], start=1):
                self.lista.SetItem(indice, columna, valor)

    def _on_marcar_atendida(self, event):
        indice = self.lista.GetFirstSelected()
        if indice == wx.NOT_FOUND:
            return

        recordatorio = self._recordatorios.pop(indice)
        conn = get_connection()
        try:
            marcar_atendido(conn, recordatorio["id"])
        finally:
            conn.close()

        if not self._recordatorios:
            self._temporizador_sonido.Stop()
            self.EndModal(wx.ID_OK)
            return

        self._refrescar_lista()
        nuevo_indice = min(indice, len(self._recordatorios) - 1)
        estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
        self.lista.SetItemState(nuevo_indice, estado, estado)

    def _on_posponer(self, event):
        """Pospone TODO lo que siga en la lista (lo que el usuario no marcó
        como atendido en esta misma ventana) — Escape dispara este mismo
        botón gratis por ser id=wx.ID_CANCEL. event.Skip() al final para que,
        además de esta acción, corra el cierre nativo de wx.Dialog para un
        botón con este id (ver docstring de la clase)."""
        conn = get_connection()
        try:
            for recordatorio in self._recordatorios:
                posponer_recordatorio(conn, recordatorio["id"], minutos=MINUTOS_POSPONER)
        finally:
            conn.close()

        self._temporizador_sonido.Stop()
        event.Skip()
