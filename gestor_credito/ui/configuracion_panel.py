import wx

from gestor_credito.db.casos import obtener_ejecutivos
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, guardar_valor, obtener_valor
from gestor_credito.db.database import get_connection
from gestor_credito.importer.excel_importer import import_bitacora
from gestor_credito.ui.accesibilidad import activar_con_enter
from gestor_credito.ui.logo import AppLogo


class ConfiguracionPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        self._file_path = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Configuración")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_seccion_agente(), 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self._crear_seccion_importar(), 1, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self._cargar_agente_actual()

        # wx.Choice envuelve un combobox nativo de Windows que se queda con la
        # tecla Enter antes de que llegue a un EVT_KEY_DOWN normal (probado:
        # con EVT_KEY_DOWN en el propio control, Enter seguía sin hacer nada).
        # EVT_CHAR_HOOK sí la intercepta más arriba, antes que el control
        # nativo la consuma — necesario para que Enter dispare el guardado
        # estando parado en la lista, sin depender de Tab hasta el botón
        # (falla de teclado real, WCAG 2.1.1, confirmada por el usuario).
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _crear_seccion_agente(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Mi agente / ejecutivo")
        contenedor = box.GetStaticBox()

        # Todos los agentes vienen de la bitácora importada (columna
        # Ejecutivo), así que no hace falta un campo de texto libre para
        # escribir uno a mano: una lista cerrada (wx.Choice) alcanza. Se
        # descartó a propósito un wx.ComboBox editable acá: ese widget ya se
        # probó y se abandonó después de un reporte real con NVDA (quedaba
        # ambiguo si se estaba escribiendo texto libre o navegando el
        # historial del desplegable).
        fila = wx.BoxSizer(wx.HORIZONTAL)

        existentes_label = wx.StaticText(contenedor, label="Escoge un agente:")
        self.agentes_choice = wx.Choice(contenedor, choices=[])
        self.agentes_choice.SetName("Escoge un agente")

        guardar_btn = wx.Button(contenedor, label="&Guardar y usar este agente")
        guardar_btn.Bind(wx.EVT_BUTTON, self._on_guardar_agente)
        activar_con_enter(guardar_btn)

        for control in (existentes_label, self.agentes_choice, guardar_btn):
            fila.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        box.Add(fila, 0, wx.BOTTOM, 4)

        self.agente_mensaje = wx.StaticText(contenedor, label="")
        box.Add(self.agente_mensaje, 0)

        return box

    def _crear_seccion_importar(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Importar bitácora de MIDESA")
        contenedor = box.GetStaticBox()

        fila_archivo = wx.BoxSizer(wx.HORIZONTAL)
        archivo_label = wx.StaticText(contenedor, label="Archivo seleccionado:")
        self.archivo_texto = wx.TextCtrl(contenedor, style=wx.TE_READONLY)
        self.archivo_texto.SetName("Archivo Excel seleccionado")
        fila_archivo.Add(archivo_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        fila_archivo.Add(self.archivo_texto, 1)
        box.Add(fila_archivo, 0, wx.EXPAND | wx.BOTTOM, 8)

        botones = wx.BoxSizer(wx.HORIZONTAL)
        seleccionar_btn = wx.Button(contenedor, label="&Seleccionar archivo Excel...")
        seleccionar_btn.Bind(wx.EVT_BUTTON, self._on_seleccionar_archivo)
        activar_con_enter(seleccionar_btn)
        botones.Add(seleccionar_btn, 0, wx.RIGHT, 8)

        self.importar_btn = wx.Button(contenedor, label="&Importar")
        self.importar_btn.Disable()
        self.importar_btn.Bind(wx.EVT_BUTTON, self._on_importar)
        activar_con_enter(self.importar_btn)
        botones.Add(self.importar_btn, 0)
        box.Add(botones, 0, wx.BOTTOM, 8)

        resultado_label = wx.StaticText(contenedor, label="Resultado de la importación:")
        box.Add(resultado_label, 0, wx.BOTTOM, 4)

        self.resultado_texto = wx.TextCtrl(
            contenedor, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 200)
        )
        self.resultado_texto.SetName("Resultado de la importación")
        box.Add(self.resultado_texto, 1, wx.EXPAND)

        return box

    def _cargar_agente_actual(self):
        conn = get_connection()
        try:
            actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            ejecutivos = obtener_ejecutivos(conn)
        finally:
            conn.close()

        self._mostrar_agentes_existentes(ejecutivos)
        self._seleccionar_agente_actual(actual)

    def _mostrar_agentes_existentes(self, ejecutivos):
        self.agentes_choice.Set(ejecutivos)
        self.agentes_choice.Enable(bool(ejecutivos))

    def _seleccionar_agente_actual(self, actual):
        if not actual:
            return
        indice = self.agentes_choice.FindString(actual)
        if indice != wx.NOT_FOUND:
            self.agentes_choice.SetSelection(indice)

    def _on_char_hook(self, event):
        if (
            event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and wx.Window.FindFocus() is self.agentes_choice
        ):
            self._on_guardar_agente(event)
            return
        event.Skip()

    def _on_guardar_agente(self, event):
        valor = self.agentes_choice.GetStringSelection()
        if not valor:
            mensaje = "Seleccioná un agente de la lista antes de guardar."
            self.agente_mensaje.SetLabel(mensaje)
            wx.MessageBox(mensaje, "Ningún agente seleccionado", wx.OK | wx.ICON_ERROR, self)
            return

        self._guardar_agente(valor)

    def _guardar_agente(self, valor):
        conn = get_connection()
        try:
            guardar_valor(conn, CLAVE_EJECUTIVO_ACTUAL, valor)
        finally:
            conn.close()

        self.agente_mensaje.SetLabel(f"Agente configurado: {valor}")
        self.GetTopLevelParent().SetStatusText(f"Agente configurado: {valor}")

    def _on_seleccionar_archivo(self, event):
        with wx.FileDialog(
            self,
            "Seleccionar archivo Excel de la bitácora",
            wildcard="Archivos Excel (*.xlsx)|*.xlsx",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialogo:
            if dialogo.ShowModal() == wx.ID_CANCEL:
                return
            self._file_path = dialogo.GetPath()
            self.archivo_texto.SetValue(self._file_path)
            self.importar_btn.Enable()

    def _on_importar(self, event):
        if not self._file_path:
            return

        try:
            resumen = import_bitacora(self._file_path)
        except Exception as exc:
            mensaje = f"Error al importar: {exc}"
            self.resultado_texto.SetValue(mensaje)
            self.GetTopLevelParent().SetStatusText("Error al importar")
            wx.MessageBox(mensaje, "Error al importar", wx.OK | wx.ICON_ERROR, self)
            return

        lineas = [
            f"Clientes nuevos: {resumen.clientes_nuevos}",
            f"Casos nuevos: {resumen.casos_nuevos}",
            f"Casos actualizados: {resumen.casos_actualizados}",
            f"Filas omitidas: {len(resumen.filas_omitidas)}",
        ]
        resumen_mensaje = "\n".join(lineas)

        for fila_numero, motivo in resumen.filas_omitidas:
            lineas.append(f"  Fila {fila_numero}: {motivo}")

        self.resultado_texto.SetValue("\n".join(lineas))
        self.GetTopLevelParent().SetStatusText("Importación completada")

        if resumen.filas_omitidas:
            resumen_mensaje += (
                "\n\nRevisá el detalle de las filas omitidas en el cuadro "
                "de resultado de la importación."
            )
        wx.MessageBox(resumen_mensaje, "Importación completada", wx.OK | wx.ICON_INFORMATION, self)

        # Un import puede traer agentes/ejecutivos nuevos que todavía no existían.
        conn = get_connection()
        try:
            actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            ejecutivos = obtener_ejecutivos(conn)
        finally:
            conn.close()
        self._mostrar_agentes_existentes(ejecutivos)
        self._seleccionar_agente_actual(actual)
