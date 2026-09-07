from datetime import datetime

import wx

from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, obtener_valor
from gestor_credito.db.database import get_connection
from gestor_credito.db.recordatorios import (
    actualizar_recordatorio,
    buscar_datos_cliente_por_cedula,
    crear_recordatorio,
    eliminar_recordatorio,
    esta_vencido,
    listar_recordatorios,
    marcar_atendido,
)
from gestor_credito.ui.accesibilidad import activar_con_enter, nombre_accesible
from gestor_credito.ui.fechas import formatear_fecha, parsear_fecha_ui
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import SONIDO_BORRAR, SONIDO_FILA_RECORDATORIO_VENCIDO, reproducir_sonido

COLUMNAS = ["Fecha a llamar", "Hora", "Nombre", "Cédula", "Celular", "Empresa", "Estado"]

FORMATO_HORA_UI = "%H:%M"


def parsear_hora_ui(texto):
    """'HH:MM' (24 horas) tal como lo escribe el oficial. None si el texto no
    tiene exactamente ese formato — mismo criterio que parsear_fecha_ui en
    ui/fechas.py, pero local a este módulo porque es el único que necesita
    entrada manual de hora en toda la app."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return datetime.strptime(texto, FORMATO_HORA_UI).strftime(FORMATO_HORA_UI)
    except ValueError:
        return None


class RecordatoriosPanel(wx.Panel):
    """Pestaña "Recordatorios de Llamada" (Ctrl+5) — pedido explícito del
    usuario (2026-09-07), deliberadamente aparte de Notificaciones, que
    calificó de inútil para llamar su atención de verdad (ver CLAUDE.md). Acá
    la alarma real vive en MainFrame (wx.Timer) + RecordatorioAlarmaDialog;
    este panel es solo el formulario de alta/edición y la lista de consulta,
    mismo patrón visual que Casos (formulario + wx.ListCtrl + edición al
    seleccionar fila), pero sin ninguna relación de datos con cliente/caso —
    ver CELDA_VACIA/colores reutilizados de CasosPanel para el resaltado en
    rojo de una fila vencida.
    """

    CELDA_VACIA = "Celda vacía"
    _COLOR_FONDO_VENCIDO = wx.Colour(255, 214, 214)
    _COLOR_TEXTO_VENCIDO = wx.Colour(139, 0, 0)

    def __init__(self, parent):
        super().__init__(parent)

        self._filas = []
        self._recordatorio_seleccionado_id = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Recordatorios de Llamada")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_formulario(), 0, wx.EXPAND | wx.ALL, 8)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        nombre_accesible(self.lista, "Lista de recordatorios de llamada")
        for indice, columna in enumerate(COLUMNAS):
            self.lista.InsertColumn(indice, columna)
            self.lista.SetColumnWidth(indice, wx.LIST_AUTOSIZE_USEHEADER)
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_seleccionar)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        self.mensaje_texto = wx.StaticText(self, label="")
        sizer.Add(self.mensaje_texto, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)
        self._cargar_recordatorios()

    def _crear_formulario(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Agregar / editar recordatorio")
        contenedor = box.GetStaticBox()

        fila1 = wx.BoxSizer(wx.HORIZONTAL)
        cedula_label = wx.StaticText(contenedor, label="Cédula:")
        # TE_PROCESS_ENTER + EVT_TEXT_ENTER: Enter sobre este campo dispara el
        # autocompletado, además de EVT_KILL_FOCUS (perder el foco tabulando
        # hacia el siguiente campo) — pedido explícito del usuario: "si
        # coloco cédula el mismo jale nombre del cliente empresa".
        self.cedula_texto = wx.TextCtrl(contenedor, style=wx.TE_PROCESS_ENTER)
        nombre_accesible(self.cedula_texto, "Cédula")
        self.cedula_texto.Bind(wx.EVT_TEXT_ENTER, lambda event: self._autocompletar_por_cedula())
        self.cedula_texto.Bind(wx.EVT_KILL_FOCUS, self._on_perder_foco_cedula)

        nombre_label = wx.StaticText(contenedor, label="Nombre:")
        self.nombre_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.nombre_texto, "Nombre")

        for control in (cedula_label, self.cedula_texto, nombre_label, self.nombre_texto):
            fila1.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        box.Add(fila1, 0, wx.BOTTOM, 8)

        fila2 = wx.BoxSizer(wx.HORIZONTAL)
        celular_label = wx.StaticText(contenedor, label="Celular:")
        self.celular_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.celular_texto, "Celular")

        empresa_label = wx.StaticText(contenedor, label="Empresa:")
        self.empresa_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.empresa_texto, "Empresa")

        for control in (celular_label, self.celular_texto, empresa_label, self.empresa_texto):
            fila2.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        box.Add(fila2, 0, wx.BOTTOM, 8)

        fila3 = wx.BoxSizer(wx.HORIZONTAL)
        fecha_label = wx.StaticText(contenedor, label="Fecha a llamar (DD/MM/AAAA):")
        self.fecha_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.fecha_texto, "Fecha a llamar")

        hora_label = wx.StaticText(contenedor, label="Hora a llamar (HH:MM):")
        self.hora_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.hora_texto, "Hora a llamar")

        for control in (fecha_label, self.fecha_texto, hora_label, self.hora_texto):
            fila3.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        box.Add(fila3, 0, wx.BOTTOM, 8)

        fila_botones = wx.BoxSizer(wx.HORIZONTAL)

        # El mismo botón alterna etiqueta ("A&gregar recordatorio" / "&Guardar
        # cambios") según si hay una fila seleccionada — mnemónico "g" en
        # ambos casos, mismo criterio "Alt+G para guardar" ya documentado en
        # otros módulos (Casos, Configuración).
        self.guardar_btn = wx.Button(contenedor, label="A&gregar recordatorio")
        self.guardar_btn.Bind(wx.EVT_BUTTON, self._on_guardar)
        activar_con_enter(self.guardar_btn)
        fila_botones.Add(self.guardar_btn, 0, wx.RIGHT, 8)

        self.marcar_atendido_btn = wx.Button(contenedor, label="&Marcar como atendida")
        self.marcar_atendido_btn.Bind(wx.EVT_BUTTON, self._on_marcar_atendido)
        self.marcar_atendido_btn.Disable()
        activar_con_enter(self.marcar_atendido_btn)
        fila_botones.Add(self.marcar_atendido_btn, 0, wx.RIGHT, 8)

        self.eliminar_btn = wx.Button(contenedor, label="Elimina&r")
        self.eliminar_btn.Bind(wx.EVT_BUTTON, self._on_eliminar)
        self.eliminar_btn.Disable()
        activar_con_enter(self.eliminar_btn)
        fila_botones.Add(self.eliminar_btn, 0)

        box.Add(fila_botones, 0)

        return box

    # ---- Autocompletado por cédula -----------------------------------------

    def _on_perder_foco_cedula(self, event):
        self._autocompletar_por_cedula()
        event.Skip()

    def _autocompletar_por_cedula(self):
        """Pedido explícito del usuario: "si coloco añadir cédula el mismo
        jale nombre del cliente empresa... si no existe pues lo añado yo".
        Rellena Nombre/Celular/Empresa SOLO en los campos que estén vacíos
        (nunca pisa algo que el oficial ya haya escrito a mano), y no hace
        nada si la cédula no coincide con ningún cliente existente."""
        cedula = self.cedula_texto.GetValue().strip()
        if not cedula:
            return

        conn = get_connection()
        try:
            datos = buscar_datos_cliente_por_cedula(conn, cedula)
        finally:
            conn.close()

        if datos is None:
            return

        if not self.nombre_texto.GetValue().strip() and datos["nombre"]:
            self.nombre_texto.SetValue(datos["nombre"])
        if not self.celular_texto.GetValue().strip() and datos["telefono"]:
            self.celular_texto.SetValue(datos["telefono"])
        if not self.empresa_texto.GetValue().strip() and datos["empresa_convenio"]:
            self.empresa_texto.SetValue(datos["empresa_convenio"])

    # ---- Alta / edición -----------------------------------------------------

    def _on_guardar(self, event):
        nombre = self.nombre_texto.GetValue().strip()
        cedula = self.cedula_texto.GetValue().strip() or None
        celular = self.celular_texto.GetValue().strip() or None
        empresa = self.empresa_texto.GetValue().strip() or None
        fecha_iso = parsear_fecha_ui(self.fecha_texto.GetValue())
        hora = parsear_hora_ui(self.hora_texto.GetValue())

        if not nombre:
            self.mensaje_texto.SetLabel("Escribí el nombre de a quién hay que llamar.")
            return
        if fecha_iso is None:
            self.mensaje_texto.SetLabel("La fecha a llamar debe tener el formato DD/MM/AAAA.")
            return
        if hora is None:
            self.mensaje_texto.SetLabel("La hora a llamar debe tener el formato HH:MM (24 horas).")
            return

        conn = get_connection()
        try:
            if self._recordatorio_seleccionado_id is None:
                ejecutivo_actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
                crear_recordatorio(
                    conn, nombre, cedula, celular, empresa, fecha_iso, hora, ejecutivo_actual
                )
                mensaje = "Recordatorio agregado."
            else:
                actualizar_recordatorio(
                    conn, self._recordatorio_seleccionado_id, nombre, cedula, celular,
                    empresa, fecha_iso, hora,
                )
                mensaje = "Cambios guardados."
        finally:
            conn.close()

        self._limpiar_formulario_interno()
        self._cargar_recordatorios()
        self.mensaje_texto.SetLabel(mensaje)

    def _on_marcar_atendido(self, event):
        if self._recordatorio_seleccionado_id is None:
            return

        conn = get_connection()
        try:
            marcar_atendido(conn, self._recordatorio_seleccionado_id)
        finally:
            conn.close()

        self._limpiar_formulario_interno()
        self._cargar_recordatorios()
        self.mensaje_texto.SetLabel("Recordatorio marcado como atendido.")

    def _on_eliminar(self, event):
        if self._recordatorio_seleccionado_id is None:
            return

        nombre = self.nombre_texto.GetValue().strip() or "(sin nombre)"
        confirmacion = wx.MessageBox(
            f"¿Eliminar el recordatorio de llamar a {nombre}?", "Eliminar recordatorio",
            wx.YES_NO | wx.ICON_WARNING, self,
        )
        if confirmacion != wx.YES:
            return

        conn = get_connection()
        try:
            eliminar_recordatorio(conn, self._recordatorio_seleccionado_id)
        finally:
            conn.close()

        reproducir_sonido(SONIDO_BORRAR)
        self._limpiar_formulario_interno()
        self._cargar_recordatorios()
        self.mensaje_texto.SetLabel(f"Recordatorio de {nombre} eliminado.")

    # ---- Ctrl+D / recarga de pestaña ----------------------------------------

    def recargar(self):
        """Se llama al entrar a esta pestaña y tras cerrar cualquier diálogo
        del menú (ver MainFrame) — un cambio de ejecutivo_actual en
        Configuración debe reflejarse sin recargar a mano."""
        self._cargar_recordatorios()

    def limpiar_formulario(self):
        """Atajo GLOBAL Ctrl+D cuando esta es la pestaña activa (ver
        MainFrame._limpiar_segun_pestana_activa) — mismo criterio del resto
        de la app."""
        self._limpiar_formulario_interno()
        reproducir_sonido(SONIDO_BORRAR)

    def _limpiar_formulario_interno(self):
        indice = self.lista.GetFirstSelected()
        if indice != wx.NOT_FOUND:
            estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
            self.lista.SetItemState(indice, 0, estado)

        self._recordatorio_seleccionado_id = None
        self.cedula_texto.SetValue("")
        self.nombre_texto.SetValue("")
        self.celular_texto.SetValue("")
        self.empresa_texto.SetValue("")
        self.fecha_texto.SetValue("")
        self.hora_texto.SetValue("")
        self.guardar_btn.SetLabel("A&gregar recordatorio")
        self.marcar_atendido_btn.Disable()
        self.eliminar_btn.Disable()
        self.mensaje_texto.SetLabel("")

    # ---- Lista ---------------------------------------------------------------

    def _cargar_recordatorios(self):
        conn = get_connection()
        try:
            ejecutivo_actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            self._filas = listar_recordatorios(conn, ejecutivo_actual)
        finally:
            conn.close()
        self._refrescar_lista()

    def _refrescar_lista(self):
        ahora = datetime.now()
        self.lista.Freeze()
        try:
            self.lista.DeleteAllItems()
            for fila in self._filas:
                vencido = not fila["atendido"] and esta_vencido(fila, ahora)
                estado_texto = "Atendida" if fila["atendido"] else ("Vencido" if vencido else "Pendiente")
                valores = [
                    formatear_fecha(fila["fecha_llamar"]), fila["hora_llamar"] or "",
                    fila["nombre"] or "", fila["cedula"] or "", fila["celular"] or "",
                    fila["empresa_convenio"] or "", estado_texto,
                ]
                valores = [valor if valor else self.CELDA_VACIA for valor in valores]
                indice = self.lista.InsertItem(self.lista.GetItemCount(), valores[0])
                for columna, valor in enumerate(valores[1:], start=1):
                    self.lista.SetItem(indice, columna, valor)

                if vencido:
                    self.lista.SetItemBackgroundColour(indice, self._COLOR_FONDO_VENCIDO)
                    self.lista.SetItemTextColour(indice, self._COLOR_TEXTO_VENCIDO)
        finally:
            self.lista.Thaw()

    def _on_seleccionar(self, event):
        indice = event.GetIndex()
        fila = self._filas[indice]

        self._recordatorio_seleccionado_id = fila["id"]
        self.cedula_texto.SetValue(fila["cedula"] or "")
        self.nombre_texto.SetValue(fila["nombre"] or "")
        self.celular_texto.SetValue(fila["celular"] or "")
        self.empresa_texto.SetValue(fila["empresa_convenio"] or "")
        self.fecha_texto.SetValue(formatear_fecha(fila["fecha_llamar"]))
        self.hora_texto.SetValue(fila["hora_llamar"] or "")
        self.guardar_btn.SetLabel("&Guardar cambios")
        self.marcar_atendido_btn.Enable(not fila["atendido"])
        self.eliminar_btn.Enable()
        self.mensaje_texto.SetLabel("")

        # Equivalente auditivo del resaltado en rojo (ver _refrescar_lista),
        # mismo criterio que CasosPanel._on_seleccionar_caso.
        if not fila["atendido"] and esta_vencido(fila, datetime.now()):
            reproducir_sonido(SONIDO_FILA_RECORDATORIO_VENCIDO)
