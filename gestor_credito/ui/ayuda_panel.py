import tempfile
from pathlib import Path

import wx

from gestor_credito.actualizador.actualizador import (
    aplicar_actualizacion,
    descargar_actualizacion,
    verificar_actualizacion,
)
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, ejecutar_en_segundo_plano, nombre_accesible
from gestor_credito.ui.atajos import ATAJOS
from gestor_credito.ui.logo import AppLogo
from gestor_credito.version import VERSION


class AyudaPanel(wx.Panel):
    """Lista de referencia de TODOS los atajos de teclado documentados de la
    app (ver gestor_credito/ui/atajos.py — única fuente de verdad: globales
    de Casos, mnemónicos de botón/menú de cualquier pantalla, y atajos de
    sistema como Esc). Un wx.ListCtrl de 3 columnas (Atajo, Sección, Acción),
    igual de estilo que la lista de Casos, para que NVDA pueda recorrerla
    celda por celda con Ctrl+Alt+flechas como ya hace en esa pantalla — mismo
    patrón, no una tabla nueva con reglas distintas. La columna Sección deja
    ubicar de un vistazo en qué pantalla vive cada atajo (p. ej. "Importar"
    está en Configuración, no en Casos).

    "Buscar actualizaciones"/"Actualizar ahora" (2026-08-19) viven en esta
    misma pantalla, no en Configuración — pedido explícito del usuario: "en
    alt aparece configuración y a la par ayuda, dentro de ayuda estaría
    buscar actualizaciones" — a diferencia de todo lo demás en Configuración
    (agente, import de bitácora/reporte, tasas), que son ajustes que se
    tocan una vez y quedan; buscar actualizaciones es más una consulta
    puntual ("¿hay algo nuevo?"), más parecida en espíritu a mirar los
    atajos de teclado que a configurar algo — de ahí que comparta pantalla
    con esa lista en vez de sumar una cuarta categoría al árbol de
    Configuración."""

    def __init__(self, parent):
        super().__init__(parent)

        self._actualizacion_disponible = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Ayuda — Atajos de teclado")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        nombre_accesible(self.lista, "Lista de atajos de teclado")
        self.lista.InsertColumn(0, "Atajo")
        self.lista.InsertColumn(1, "Sección")
        self.lista.InsertColumn(2, "Acción")
        for _modificador, _tecla, texto, seccion, descripcion, _accion in ATAJOS:
            indice = self.lista.InsertItem(self.lista.GetItemCount(), texto)
            self.lista.SetItem(indice, 1, seccion)
            self.lista.SetItem(indice, 2, descripcion)
        self.lista.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self.lista.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
        self.lista.SetColumnWidth(2, wx.LIST_AUTOSIZE_USEHEADER)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        sizer.Add(self._crear_seccion_actualizaciones(), 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)

    # ---- Actualizaciones --------------------------------------------------

    def _crear_seccion_actualizaciones(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Actualizaciones")
        contenedor = box.GetStaticBox()

        version_label = wx.StaticText(contenedor, label=f"Versión instalada: {VERSION}")
        box.Add(version_label, 0, wx.BOTTOM, 8)

        botones = wx.BoxSizer(wx.HORIZONTAL)
        self.buscar_actualizacion_btn = wx.Button(contenedor, label="&Buscar actualizaciones")
        self.buscar_actualizacion_btn.Bind(wx.EVT_BUTTON, self._on_buscar_actualizacion)
        activar_con_enter(self.buscar_actualizacion_btn)
        botones.Add(self.buscar_actualizacion_btn, 0, wx.RIGHT, 8)

        # Deshabilitado hasta que "Buscar actualizaciones" confirme que hay
        # una versión más nueva disponible — mismo patrón de gateo que
        # guardar_btn en calculadora_panel.py o importar_btn en
        # configuracion_panel.py: la acción "final" (acá, la más delicada de
        # todas, cierra la app) queda inalcanzable hasta que hay algo real
        # que aplicar, sin necesidad de deshabilitar ningún otro control de
        # la pantalla (ver la lección sobre Enable(False) en bloque, CLAUDE.md
        # — acá es un único botón, no una sección entera).
        self.actualizar_ahora_btn = wx.Button(contenedor, label="&Actualizar ahora")
        self.actualizar_ahora_btn.Disable()
        self.actualizar_ahora_btn.Bind(wx.EVT_BUTTON, self._on_actualizar_ahora)
        activar_con_enter(self.actualizar_ahora_btn)
        botones.Add(self.actualizar_ahora_btn, 0)
        box.Add(botones, 0, wx.BOTTOM, 8)

        self.actualizacion_mensaje = wx.StaticText(contenedor, label="")
        box.Add(self.actualizacion_mensaje, 0)

        return box

    def _fijar_mensaje_actualizacion(self, texto, anunciar=True):
        self.actualizacion_mensaje.SetLabel(texto)
        self.GetTopLevelParent().SetStatusText(texto)
        # SetStatusText ya dispara anunciar_texto_estado (evento de región
        # viva MSAA), pero ese mecanismo ya se confirmó poco confiable para
        # una confirmación puntual como esta (mismo motivo documentado para
        # anunciar_voz_nvda en accesibilidad.py) — se anuncia también por voz
        # de forma directa.
        if anunciar:
            anunciar_voz_nvda(texto)

    def _on_buscar_actualizacion(self, event):
        self.buscar_actualizacion_btn.Disable()
        self.actualizar_ahora_btn.Disable()
        self._actualizacion_disponible = None
        self._fijar_mensaje_actualizacion("Buscando actualizaciones...")

        def trabajo():
            try:
                return True, verificar_actualizacion()
            except RuntimeError as exc:
                return False, str(exc)

        ejecutar_en_segundo_plano(trabajo, self._on_verificacion_completa)

    def _on_verificacion_completa(self, resultado):
        exito, valor = resultado
        self.buscar_actualizacion_btn.Enable()

        if not exito:
            self._fijar_mensaje_actualizacion(f"No se pudo buscar actualizaciones: {valor}")
            wx.MessageBox(valor, "No se pudo buscar actualizaciones", wx.OK | wx.ICON_ERROR, self)
            return

        if valor is None:
            self._fijar_mensaje_actualizacion(f"Ya tenés la versión más reciente ({VERSION}).")
            return

        self._actualizacion_disponible = valor
        self.actualizar_ahora_btn.Enable()
        self._fijar_mensaje_actualizacion(f"Versión {valor.version} disponible.")

    def _on_actualizar_ahora(self, event):
        actualizacion = self._actualizacion_disponible
        if actualizacion is None:
            return

        self.buscar_actualizacion_btn.Disable()
        self.actualizar_ahora_btn.Disable()
        self._fijar_mensaje_actualizacion(f"Descargando versión {actualizacion.version}...")

        def trabajo():
            destino = Path(tempfile.gettempdir()) / f"GestorDeCredito_{actualizacion.version}.zip"
            try:
                descargar_actualizacion(actualizacion.url_descarga, actualizacion.sha256, destino)
                return True, destino
            except RuntimeError as exc:
                return False, str(exc)

        ejecutar_en_segundo_plano(trabajo, self._on_descarga_completa)

    def _on_descarga_completa(self, resultado):
        exito, valor = resultado

        if not exito:
            self.buscar_actualizacion_btn.Enable()
            self.actualizar_ahora_btn.Enable()
            self._fijar_mensaje_actualizacion(f"No se pudo descargar la actualización: {valor}")
            wx.MessageBox(valor, "No se pudo descargar la actualización", wx.OK | wx.ICON_ERROR, self)
            return

        try:
            aplicar_actualizacion(valor)
        except RuntimeError as exc:
            self.buscar_actualizacion_btn.Enable()
            self.actualizar_ahora_btn.Enable()
            self._fijar_mensaje_actualizacion(f"No se pudo aplicar la actualización: {exc}")
            wx.MessageBox(str(exc), "No se pudo aplicar la actualización", wx.OK | wx.ICON_ERROR, self)
            return

        # El proceso actualizador externo ya está lanzado y esperando a que
        # este cierre (ver aplicar_actualizacion() en actualizador.py) — el
        # anuncio por voz sale ANTES de wx.Exit() porque, una vez cerrada la
        # app, no queda nada corriendo que pueda seguir hablando.
        anunciar_voz_nvda("Actualización descargada. Cerrando la aplicación para aplicarla.")
        wx.Exit()
