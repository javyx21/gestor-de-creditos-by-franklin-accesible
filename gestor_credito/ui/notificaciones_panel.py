from datetime import datetime, timezone

import wx

from gestor_credito.db.alertas import (
    alertas_constancia_en_mano,
    alertas_constancia_pendiente,
    alertas_documentos_pendientes,
    marcar_documentos_completos,
)
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, obtener_valor
from gestor_credito.db.database import get_connection
from gestor_credito.ui.accesibilidad import activar_con_enter
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import (
    SONIDO_CONSTANCIA_EN_MANO,
    SONIDO_CONSTANCIA_PENDIENTE,
    SONIDO_DOCUMENTOS_PENDIENTES,
    reproducir_sonido,
)

COLUMNAS = ["Tipo de alerta", "Nombre", "Identificación", "Caso", "Desde"]

TIPO_DOCUMENTOS = "Documentos pendientes"
TIPO_CONSTANCIA_PENDIENTE = "Constancia pendiente"
TIPO_CONSTANCIA_EN_MANO = "Constancia en mano"

_FORMATO_FECHA_UTC = "%Y-%m-%d %H:%M:%S"


def _formatear_transcurrido(fecha_utc_texto):
    """'AAAA-MM-DD HH:MM:SS' (formato de datetime('now') de SQLite, siempre UTC)
    -> 'hace X h'/'hace X día(s)', para que NVDA lea algo útil en vez de un
    timestamp crudo. Si no viene en ese formato, se devuelve tal cual."""
    if not fecha_utc_texto:
        return ""
    try:
        momento = datetime.strptime(fecha_utc_texto, _FORMATO_FECHA_UTC).replace(tzinfo=timezone.utc)
    except ValueError:
        return fecha_utc_texto

    horas = (datetime.now(timezone.utc) - momento).total_seconds() / 3600
    if horas < 48:
        return f"hace {int(horas)} h"
    return f"hace {int(horas // 24)} día(s)"


class NotificacionesPanel(wx.Panel):
    CELDA_VACIA = "Celda vacía"

    def __init__(self, parent):
        super().__init__(parent)

        self._alertas = []  # lista paralela a las filas de self.lista: [(tipo, dict), ...]

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Notificaciones")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        actualizar_btn = wx.Button(self, label="&Actualizar")
        actualizar_btn.Bind(wx.EVT_BUTTON, lambda event: self.recargar())
        activar_con_enter(actualizar_btn)
        sizer.Add(actualizar_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.lista.SetName("Lista de alertas activas")
        for indice, columna in enumerate(COLUMNAS):
            self.lista.InsertColumn(indice, columna)
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_seleccionar)
        self.lista.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_deseleccionar)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        self.marcar_btn = wx.Button(self, label="&Marcar documentos completados")
        self.marcar_btn.Disable()
        self.marcar_btn.Bind(wx.EVT_BUTTON, self._on_marcar_completo)
        activar_con_enter(self.marcar_btn)
        sizer.Add(self.marcar_btn, 0, wx.ALL, 8)

        self.mensaje_texto = wx.StaticText(self, label="")
        sizer.Add(self.mensaje_texto, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)
        self.recargar(sonido=False)

    def recargar(self, sonido=True):
        """Vuelve a calcular las alertas activas. Se llama al entrar a esta
        pestaña (ver MainFrame), con "Actualizar", y tras marcar documentos
        completados. sonido=False se usa en el primer load y después de marcar
        (para no repetir el sonido de algo que el usuario ya está resolviendo).
        """
        conn = get_connection()
        try:
            ejecutivo_actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            documentos = alertas_documentos_pendientes(conn, ejecutivo_actual)
            constancia_pendiente = alertas_constancia_pendiente(conn, ejecutivo_actual)
            constancia_en_mano = alertas_constancia_en_mano(conn, ejecutivo_actual)
        finally:
            conn.close()

        self._alertas = (
            [(TIPO_DOCUMENTOS, alerta) for alerta in documentos]
            + [(TIPO_CONSTANCIA_PENDIENTE, alerta) for alerta in constancia_pendiente]
            + [(TIPO_CONSTANCIA_EN_MANO, alerta) for alerta in constancia_en_mano]
        )
        self._refrescar_lista()

        if sonido:
            if documentos:
                reproducir_sonido(SONIDO_DOCUMENTOS_PENDIENTES)
            if constancia_pendiente:
                reproducir_sonido(SONIDO_CONSTANCIA_PENDIENTE)
            if constancia_en_mano:
                reproducir_sonido(SONIDO_CONSTANCIA_EN_MANO)

        total = len(self._alertas)
        mensaje = f"{total} alerta(s) activa(s)." if total else "Sin alertas activas."
        self.mensaje_texto.SetLabel(mensaje)
        self.GetTopLevelParent().SetStatusText(mensaje)

    def _refrescar_lista(self):
        self.lista.DeleteAllItems()
        for tipo, alerta in self._alertas:
            valores = self._alerta_a_columnas(tipo, alerta)
            indice = self.lista.InsertItem(self.lista.GetItemCount(), valores[0])
            for columna, valor in enumerate(valores[1:], start=1):
                self.lista.SetItem(indice, columna, valor)

        for columna in range(len(COLUMNAS)):
            self.lista.SetColumnWidth(columna, wx.LIST_AUTOSIZE_USEHEADER)

        self.marcar_btn.Disable()

    @classmethod
    def _alerta_a_columnas(cls, tipo, alerta):
        if tipo == TIPO_DOCUMENTOS:
            caso = ""
            desde = _formatear_transcurrido(alerta["fecha_creacion"])
        elif tipo == TIPO_CONSTANCIA_PENDIENTE:
            caso = alerta["clave_caso"]
            desde = _formatear_transcurrido(alerta["estado_solicitud_fecha_cambio"])
        else:
            caso = alerta["clave_caso"]
            desde = _formatear_transcurrido(alerta["constancia_recibida_fecha"])

        valores = [tipo, alerta["nombre"], alerta["cedula"], caso, desde]
        return [valor if valor else cls.CELDA_VACIA for valor in valores]

    def _on_seleccionar(self, event):
        tipo, _alerta = self._alertas[event.GetIndex()]
        self.marcar_btn.Enable(tipo == TIPO_DOCUMENTOS)

    def _on_deseleccionar(self, event):
        self.marcar_btn.Disable()

    def _on_marcar_completo(self, event):
        seleccion = self.lista.GetFirstSelected()
        if seleccion == wx.NOT_FOUND:
            return

        tipo, alerta = self._alertas[seleccion]
        if tipo != TIPO_DOCUMENTOS:
            return

        conn = get_connection()
        try:
            marcar_documentos_completos(conn, alerta["cliente_id"])
        finally:
            conn.close()

        nombre = alerta["nombre"]
        self.recargar(sonido=False)
        mensaje = f"Documentos completados marcados para {nombre}."
        self.mensaje_texto.SetLabel(mensaje)
        self.GetTopLevelParent().SetStatusText(mensaje)
