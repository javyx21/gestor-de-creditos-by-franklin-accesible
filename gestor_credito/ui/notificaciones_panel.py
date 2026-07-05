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


def _texto_alerta(tipo, alerta):
    nombre = alerta["nombre"] or "(sin nombre)"
    cedula = alerta["cedula"] or "(sin cédula)"

    if tipo == TIPO_DOCUMENTOS:
        desde = _formatear_transcurrido(alerta["fecha_creacion"])
        return f"{nombre} — Cédula {cedula} — Desde {desde}"

    # Constancia pendiente y Constancia en mano comparten el mismo campo de
    # referencia (estado_solicitud_fecha_cambio) — ver alertas.py.
    caso = alerta["clave_caso"] or "(sin número)"
    desde = _formatear_transcurrido(alerta["estado_solicitud_fecha_cambio"])
    return f"{nombre} — Cédula {cedula} — Caso {caso} — Desde {desde}"


class NotificacionesPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Notificaciones")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        actualizar_btn = wx.Button(self, label="&Actualizar")
        actualizar_btn.Bind(wx.EVT_BUTTON, lambda event: self.recargar())
        activar_con_enter(actualizar_btn)
        sizer.Add(actualizar_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Árbol en vez de una lista plana: 3 nodos de categoría (uno por tipo
        # de alerta) que agrupan sus alertas activas como hijos, para que no
        # se mezclen visualmente ni al leer con NVDA (reporte del usuario:
        # con todo en una sola lista "se iba a mezclar y va a ser errores").
        # wx.TreeCtrl es un control nativo de Windows con soporte MSAA/UIA de
        # fábrica, igual que el resto de los widgets estándar de la app.
        self.arbol = wx.TreeCtrl(self, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT)
        self.arbol.SetName("Árbol de alertas activas")
        self.arbol.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_seleccionar)
        sizer.Add(self.arbol, 1, wx.EXPAND | wx.ALL, 8)

        self.marcar_btn = wx.Button(self, label="&Marcar documentos completados")
        self.marcar_btn.Disable()
        self.marcar_btn.Bind(wx.EVT_BUTTON, self._on_marcar_completo)
        activar_con_enter(self.marcar_btn)
        sizer.Add(self.marcar_btn, 0, wx.ALL, 8)

        self.mensaje_texto = wx.StaticText(self, label="")
        sizer.Add(self.mensaje_texto, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)
        # sonido=True (default): este panel solo se crea cuando el usuario abre
        # "Herramientas > Notificaciones..." desde el menú (ver MainFrame), así
        # que abrirlo es el mismo momento en que antes "entrar a la pestaña"
        # sonaba si había algo activo.
        self.recargar()

    def recargar(self, sonido=True):
        """Vuelve a calcular las alertas activas y reconstruye el árbol. Se
        llama al construir este panel (al abrir el menú, ver MainFrame), con
        "Actualizar", y tras marcar documentos completados (desde acá o desde
        Casos).
        sonido=False se usa en el primer load y después de marcar (para no
        repetir el sonido de algo que el usuario ya está resolviendo).
        """
        conn = get_connection()
        try:
            ejecutivo_actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            documentos = alertas_documentos_pendientes(conn, ejecutivo_actual)
            constancia_pendiente = alertas_constancia_pendiente(conn, ejecutivo_actual)
            constancia_en_mano = alertas_constancia_en_mano(conn, ejecutivo_actual)
        finally:
            conn.close()

        self._reconstruir_arbol(
            (
                (TIPO_DOCUMENTOS, documentos),
                (TIPO_CONSTANCIA_PENDIENTE, constancia_pendiente),
                (TIPO_CONSTANCIA_EN_MANO, constancia_en_mano),
            )
        )

        if sonido:
            if documentos:
                reproducir_sonido(SONIDO_DOCUMENTOS_PENDIENTES)
            if constancia_pendiente:
                reproducir_sonido(SONIDO_CONSTANCIA_PENDIENTE)
            if constancia_en_mano:
                reproducir_sonido(SONIDO_CONSTANCIA_EN_MANO)

        total = len(documentos) + len(constancia_pendiente) + len(constancia_en_mano)
        mensaje = f"{total} alerta(s) activa(s)." if total else "Sin alertas activas."
        self.mensaje_texto.SetLabel(mensaje)
        self.GetTopLevelParent().SetStatusText(mensaje)

    def _reconstruir_arbol(self, grupos):
        self.arbol.DeleteAllItems()
        raiz = self.arbol.AddRoot("Alertas")

        for tipo, alertas in grupos:
            nodo_categoria = self.arbol.AppendItem(raiz, f"{tipo} ({len(alertas)})")
            for alerta in alertas:
                hijo = self.arbol.AppendItem(nodo_categoria, _texto_alerta(tipo, alerta))
                self.arbol.SetItemData(hijo, (tipo, alerta))

        self.arbol.ExpandAll()
        self.marcar_btn.Disable()

    def _on_seleccionar(self, event):
        item = event.GetItem()
        datos = self.arbol.GetItemData(item) if item.IsOk() else None
        self.marcar_btn.Enable(bool(datos) and datos[0] == TIPO_DOCUMENTOS)

    def _on_marcar_completo(self, event):
        item = self.arbol.GetSelection()
        if not item.IsOk():
            return

        datos = self.arbol.GetItemData(item)
        if not datos or datos[0] != TIPO_DOCUMENTOS:
            return

        _tipo, alerta = datos
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
