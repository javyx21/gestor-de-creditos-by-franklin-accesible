import wx

from gestor_credito.db.casos import obtener_ejecutivos
from gestor_credito.db.clientes import vaciar_base_datos
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, guardar_valor, obtener_valor
from gestor_credito.db.convenios import eliminar_convenio, guardar_tasa, listar_convenios
from gestor_credito.db.database import get_connection
from gestor_credito.importer.excel_importer import import_bitacora
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.logo import AppLogo


def _formatear_tasa_porcentaje(tasa):
    """Tasa (fracción, 0.18 = 18%) a texto plano de porcentaje sin ceros de
    más (18, 18.5, 33.33) — a propósito NO se usa un simple f"{tasa:.0%}"
    acá (el que sí usa el resto de la app solo para mostrar, ver
    calculadora_panel.py): esa versión redondea a porcentaje entero, y este
    valor se vuelve a cargar en el cuadro de edición de tasa — redondear ahí
    arriesgaría perder precisión real de una tasa no entera (18.5%) cada vez
    que alguien solo abre la fila para mirarla y sin querer la vuelve a
    guardar."""
    texto = f"{tasa * 100:.4f}".rstrip("0").rstrip(".")
    return texto


class ConfiguracionPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        self._file_path = None
        self._convenios_cargados = []

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Configuración")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_arbol_y_contenido(), 1, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self._cargar_agente_actual()
        self._cargar_convenios()

        # wx.Choice envuelve un combobox nativo de Windows que se queda con la
        # tecla Enter antes de que llegue a un EVT_KEY_DOWN normal (probado:
        # con EVT_KEY_DOWN en el propio control, Enter seguía sin hacer nada).
        # EVT_CHAR_HOOK sí la intercepta más arriba, antes que el control
        # nativo la consuma — necesario para que Enter dispare el guardado
        # estando parado en la lista, sin depender de Tab hasta el botón
        # (falla de teclado real, WCAG 2.1.1, confirmada por el usuario). El
        # mismo handler ahora también resuelve Enter/Tab sobre el árbol de
        # categorías (ver _on_char_hook más abajo).
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        # Estado inicial: "Configuración de Casos" seleccionada y mostrada
        # (mismo contenido que se veía de entrada antes de existir el árbol),
        # con el foco arrancando en el árbol — punto de entrada de la nueva
        # navegación, pedido explícito del usuario (2026-07-12).
        self.arbol_categorias.SelectItem(self.item_casos)
        self._mostrar_panel(self.panel_casos)
        self.arbol_categorias.SetFocus()

    # ---- Árbol de categorías + panel de contenido -----------------------

    def _crear_arbol_y_contenido(self):
        """Reestructuración pedida explícitamente por el usuario (2026-07-12):
        un wx.TreeCtrl a la izquierda con dos categorías principales
        ("Configuración de Casos", "Configuración de la Calculadora") y el
        contenido correspondiente a la derecha, en vez de las secciones
        apiladas que tenía este panel antes. Mismo control ya usado y
        probado en este proyecto para Notificaciones (self.arbol en
        notificaciones_panel.py) — wx.TreeCtrl es un control nativo de
        Windows con soporte MSAA/UIA de fábrica, no uno nuevo para la app.

        Navegación, tal como la pidió el usuario:
        - Flechas arriba/abajo sobre el árbol: mueven la selección entre
          categorías — comportamiento nativo del control, sin acción extra
          de este código. A propósito NO cambia el panel visible por sí
          sola (mismo criterio que ya usan filtro_alerta_choice/
          agentes_choice/empresa_choice en el resto de la app: arrastrar
          flechas es "mirar", no "confirmar").
        - Enter sobre el árbol: "activa" (muestra) la sección
          correspondiente a la categoría seleccionada, sin mover el foco —
          para poder seguir comparando categorías antes de decidir.
        - Tab sobre el árbol: además de activar la sección, mueve el foco
          directo al primer campo editable de esa sección — sin depender de
          haber presionado Enter antes, para que "Tab" funcione siempre tal
          cual se pidió, sin importar el orden de teclas que use la persona.
        Ver _on_char_hook.
        """
        fila = wx.BoxSizer(wx.HORIZONTAL)

        self.arbol_categorias = wx.TreeCtrl(
            self, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_NO_LINES,
            size=(220, -1),
        )
        nombre_accesible(self.arbol_categorias, "Categorías de configuración")
        raiz = self.arbol_categorias.AddRoot("Configuración")
        self.item_casos = self.arbol_categorias.AppendItem(raiz, "Configuración de Casos")
        self.item_calculadora = self.arbol_categorias.AppendItem(raiz, "Configuración de la Calculadora")
        self.arbol_categorias.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_seleccionar_categoria)
        fila.Add(self.arbol_categorias, 0, wx.EXPAND | wx.RIGHT, 8)

        self.sizer_derecha = wx.BoxSizer(wx.VERTICAL)
        self.panel_casos = wx.Panel(self)
        self.panel_calculadora = wx.Panel(self)
        self._crear_contenido_casos(self.panel_casos)
        self._crear_contenido_calculadora(self.panel_calculadora)
        self.sizer_derecha.Add(self.panel_casos, 1, wx.EXPAND)
        self.sizer_derecha.Add(self.panel_calculadora, 1, wx.EXPAND)
        fila.Add(self.sizer_derecha, 1, wx.EXPAND)

        return fila

    def _mostrar_panel(self, panel_a_mostrar):
        for panel in (self.panel_casos, self.panel_calculadora):
            self.sizer_derecha.Show(panel, panel is panel_a_mostrar)
        self.sizer_derecha.Layout()

    def _panel_para_item(self, item):
        return self.panel_calculadora if item == self.item_calculadora else self.panel_casos

    def _primer_control_para_item(self, item):
        return self.convenios_lista if item == self.item_calculadora else self.agentes_choice

    def _activar_categoria_seleccionada(self, enfocar_primer_campo=False):
        item = self.arbol_categorias.GetSelection()
        if not item.IsOk():
            return
        self._mostrar_panel(self._panel_para_item(item))
        if enfocar_primer_campo:
            self._primer_control_para_item(item).SetFocus()

    def _on_seleccionar_categoria(self, event):
        """Reporte real del usuario (2026-07-12): arrastrando las flechas
        entre "Configuración de Casos"/"Configuración de la Calculadora",
        NVDA no indicaba cuál quedaba seleccionada — a diferencia de
        convenios_lista (un wx.ListCtrl), donde SÍ se escucha el estado
        "seleccionado" de forma nativa. Un wx.TreeCtrl de selección simple
        no expone ese mismo aviso: moverse con flechas cambia el foco Y la
        selección a la vez, así que NVDA no lo trata como un estado
        "adicional" digno de anunciarse por separado (a diferencia de una
        lista, donde foco y selección pueden diferir). Se anuncia acá de
        forma explícita, por voz — mismo mecanismo ya usado en esta app
        para cualquier estado que resultó no ser confiable por la vía
        nativa (ver anunciar_voz_nvda en accesibilidad.py) — en cada cambio
        de selección del árbol, sea por flechas o por clic.

        Texto corto ("Casos"/"Calculadora"), no el texto completo del ítem
        del árbol ("Configuración de Casos"/"Configuración de la
        Calculadora") — mismo criterio que ya se aplicó al anuncio de
        cambio de pestaña en main_frame.py: "Configuración" ya es el
        título de esta misma pantalla, repetirlo en cada flecha es
        redundante (pedido explícito del usuario, mismo día, sobre el
        anuncio de pestañas: "no es necesario repetir la palabra")."""
        item = event.GetItem()
        if item.IsOk():
            nombre_corto = "Calculadora" if item == self.item_calculadora else "Casos"
            anunciar_voz_nvda(f"{nombre_corto}, seleccionado")
        event.Skip()

    def _on_char_hook(self, event):
        codigo = event.GetKeyCode()
        foco = wx.Window.FindFocus()

        if foco is self.agentes_choice and codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_guardar_agente(event)
            return

        if foco is self.arbol_categorias:
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self._activar_categoria_seleccionada()
                return
            if codigo == wx.WXK_TAB and not event.ShiftDown() and not event.ControlDown():
                self._activar_categoria_seleccionada(enfocar_primer_campo=True)
                return

        # Reporte real del usuario (2026-07-12): parado en el cuadro de
        # tasa, presionar Enter no hacía nada — había que ir a buscar el
        # botón "Guardar cambios" a mano. wx.TextCtrl de una sola línea no
        # confirma Enter como clic de botón por sí solo (mismo motivo por
        # el que existe activar_con_enter para botones sueltos); acá el
        # arreglo es tomar el valor y guardar directo, sin exigir Tab hasta
        # el botón.
        if foco is self.convenio_tasa_texto and codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_guardar_convenio(event, mensaje_hablado="Tasa actualizada.")
            return

        event.Skip()

    # ---- Configuración de Casos ------------------------------------------

    def _crear_contenido_casos(self, panel):
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._crear_seccion_agente(panel), 0, wx.EXPAND | wx.BOTTOM, 8)
        sizer.Add(self._crear_seccion_importar(panel), 1, wx.EXPAND | wx.BOTTOM, 8)
        sizer.Add(self._crear_seccion_peligro(panel), 0, wx.EXPAND)
        panel.SetSizer(sizer)

    def _crear_seccion_agente(self, panel):
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Mi agente / ejecutivo")
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
        nombre_accesible(self.agentes_choice, "Escoge un agente")

        guardar_btn = wx.Button(contenedor, label="&Guardar y usar este agente")
        guardar_btn.Bind(wx.EVT_BUTTON, self._on_guardar_agente)
        activar_con_enter(guardar_btn)

        for control in (existentes_label, self.agentes_choice, guardar_btn):
            fila.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        box.Add(fila, 0, wx.BOTTOM, 4)

        self.agente_mensaje = wx.StaticText(contenedor, label="")
        box.Add(self.agente_mensaje, 0)

        return box

    def _crear_seccion_importar(self, panel):
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Importar bitácora de MIDESA")
        contenedor = box.GetStaticBox()

        fila_archivo = wx.BoxSizer(wx.HORIZONTAL)
        archivo_label = wx.StaticText(contenedor, label="Archivo seleccionado:")
        self.archivo_texto = wx.TextCtrl(contenedor, style=wx.TE_READONLY)
        nombre_accesible(self.archivo_texto, "Archivo Excel seleccionado")
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
            contenedor, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 150)
        )
        nombre_accesible(self.resultado_texto, "Resultado de la importación")
        box.Add(self.resultado_texto, 1, wx.EXPAND)

        return box

    def _crear_seccion_peligro(self, panel):
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Mantenimiento de datos")
        contenedor = box.GetStaticBox()

        descripcion = wx.StaticText(
            contenedor,
            label="Borra TODOS los clientes y casos guardados (se conserva el agente configurado). "
            "Esta acción no se puede deshacer.",
        )
        box.Add(descripcion, 0, wx.BOTTOM, 8)

        vaciar_btn = wx.Button(contenedor, label="&Eliminar toda la base de datos")
        vaciar_btn.Bind(wx.EVT_BUTTON, self._on_vaciar_base_datos)
        activar_con_enter(vaciar_btn)
        box.Add(vaciar_btn, 0, wx.BOTTOM, 4)

        self.peligro_mensaje = wx.StaticText(contenedor, label="")
        box.Add(self.peligro_mensaje, 0)

        return box

    def _on_vaciar_base_datos(self, event):
        mensaje = (
            "¿Eliminar TODOS los clientes y casos guardados?\n\n"
            "El agente configurado se conserva. Esta acción no se puede deshacer."
        )
        confirmacion = wx.MessageBox(
            mensaje, "Eliminar toda la base de datos", wx.YES_NO | wx.ICON_WARNING, self
        )
        if confirmacion != wx.YES:
            return

        conn = get_connection()
        try:
            vaciar_base_datos(conn)
            actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            ejecutivos = obtener_ejecutivos(conn)
        finally:
            conn.close()

        # Vaciar la base puede dejar sin agentes la lista (obtener_ejecutivos()
        # sale de caso.ejecutivo, que ya no tiene filas) — se refresca igual
        # que después de un import, con el mismo fallback seguro si el agente
        # configurado ya no aparece en la lista.
        self._mostrar_agentes_existentes(ejecutivos)
        self._seleccionar_agente_actual(actual)

        mensaje_ok = "Base de datos vaciada. Se eliminaron todos los clientes y casos."
        self.peligro_mensaje.SetLabel(mensaje_ok)
        self.GetTopLevelParent().SetStatusText(mensaje_ok)

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

    # ---- Configuración de la Calculadora (empresas convenio / tasas) ----
    # Pedido explícito del usuario (2026-07-12): poder editar, añadir y
    # eliminar empresas convenio y sus tasas desde acá — hasta ahora
    # calculadora_panel.py solo las mostraba de solo lectura (ver CLAUDE.md,
    # sección Calculadora de Crédito: "editar tasas, agregar empresas... es
    # trabajo futuro"). Reutiliza listar_convenios/guardar_tasa (ya
    # existían, guardar_tasa ya hacía upsert) más el nuevo eliminar_convenio
    # (db/convenios.py). El tipo de cambio sigue sin ser editable a
    # propósito — sigue fijo en TIPO_CAMBIO_FIJO (calculadora_panel.py), eso
    # no fue parte de este pedido.

    def _crear_contenido_calculadora(self, panel):
        sizer = wx.BoxSizer(wx.VERTICAL)
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Empresas convenio y tasas de interés")
        contenedor = box.GetStaticBox()

        self.convenios_lista = wx.ListCtrl(contenedor, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.convenios_lista.InsertColumn(0, "Empresa convenio", width=280)
        self.convenios_lista.InsertColumn(1, "Tasa de interés", width=140)
        nombre_accesible(self.convenios_lista, "Lista de empresas convenio y tasas")
        self.convenios_lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_seleccionar_convenio)
        box.Add(self.convenios_lista, 1, wx.EXPAND | wx.BOTTOM, 8)

        fila_campos = wx.BoxSizer(wx.HORIZONTAL)
        empresa_label = wx.StaticText(contenedor, label="Empresa convenio:")
        self.convenio_empresa_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.convenio_empresa_texto, "Empresa convenio")
        tasa_label = wx.StaticText(contenedor, label="Tasa de interés (%):")
        self.convenio_tasa_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.convenio_tasa_texto, "Tasa de interés en porcentaje")
        for control in (empresa_label, self.convenio_empresa_texto, tasa_label, self.convenio_tasa_texto):
            fila_campos.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        box.Add(fila_campos, 0, wx.BOTTOM, 8)

        botones = wx.BoxSizer(wx.HORIZONTAL)
        self.guardar_convenio_btn = wx.Button(contenedor, label="&Guardar cambios")
        self.guardar_convenio_btn.Bind(wx.EVT_BUTTON, self._on_guardar_convenio)
        activar_con_enter(self.guardar_convenio_btn)
        botones.Add(self.guardar_convenio_btn, 0, wx.RIGHT, 8)

        self.nueva_empresa_btn = wx.Button(contenedor, label="&Nueva empresa")
        self.nueva_empresa_btn.Bind(wx.EVT_BUTTON, self._on_nueva_empresa)
        activar_con_enter(self.nueva_empresa_btn)
        botones.Add(self.nueva_empresa_btn, 0, wx.RIGHT, 8)

        self.eliminar_convenio_btn = wx.Button(contenedor, label="Elimina&r empresa")
        self.eliminar_convenio_btn.Disable()
        self.eliminar_convenio_btn.Bind(wx.EVT_BUTTON, self._on_eliminar_convenio)
        activar_con_enter(self.eliminar_convenio_btn)
        botones.Add(self.eliminar_convenio_btn, 0)
        box.Add(botones, 0, wx.BOTTOM, 4)

        self.convenio_mensaje = wx.StaticText(contenedor, label="")
        box.Add(self.convenio_mensaje, 0)

        sizer.Add(box, 1, wx.EXPAND)
        panel.SetSizer(sizer)

    def _cargar_convenios(self):
        conn = get_connection()
        try:
            self._convenios_cargados = listar_convenios(conn)
        finally:
            conn.close()

        self.convenios_lista.DeleteAllItems()
        for fila, (empresa, tasa) in enumerate(self._convenios_cargados):
            self.convenios_lista.InsertItem(fila, empresa)
            texto_tasa = "sin configurar" if tasa is None else f"{_formatear_tasa_porcentaje(tasa)}%"
            self.convenios_lista.SetItem(fila, 1, texto_tasa)

    def _on_seleccionar_convenio(self, event):
        empresa, tasa = self._convenios_cargados[event.GetIndex()]
        self.convenio_empresa_texto.SetValue(empresa)
        self.convenio_tasa_texto.SetValue(_formatear_tasa_porcentaje(tasa) if tasa is not None else "")
        self.eliminar_convenio_btn.Enable()

    def _seleccionar_fila_por_empresa(self, empresa):
        """Re-selecciona en la lista la fila de `empresa` después de
        guardar — reporte real del usuario (2026-07-12): tras guardar, la
        fila editada quedaba sin resaltar (DeleteAllItems()/InsertItem() en
        _cargar_convenios() no preserva la selección de wx.ListCtrl) y
        `eliminar_convenio_btn` seguía habilitado aunque nada estuviera
        realmente seleccionado — daba la sensación de que el cambio no
        había quedado guardado, aunque los datos en sí sí persistían bien
        (verificado con pruebas exhaustivas, ver tests/test_configuracion_panel.py).
        Reseleccionar la fila deja lista/campos/botón coherentes entre sí y
        confirma, de forma visible y audible, cuál es el valor que quedó
        realmente guardado."""
        indice = next(
            (i for i, (empresa_existente, _tasa) in enumerate(self._convenios_cargados)
             if empresa_existente == empresa),
            None,
        )
        if indice is None:
            self.eliminar_convenio_btn.Disable()
            return
        self.convenios_lista.SetItemState(-1, 0, wx.LIST_STATE_SELECTED)
        self.convenios_lista.SetItemState(
            indice, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
            wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
        )
        self.convenios_lista.EnsureVisible(indice)
        self.eliminar_convenio_btn.Enable()

    def _on_nueva_empresa(self, event):
        self.convenios_lista.SetItemState(-1, 0, wx.LIST_STATE_SELECTED)
        self.convenio_empresa_texto.SetValue("")
        self.convenio_tasa_texto.SetValue("")
        self.eliminar_convenio_btn.Disable()
        self.convenio_mensaje.SetLabel("")
        self.convenio_empresa_texto.SetFocus()

    def _on_guardar_convenio(self, event, mensaje_hablado=None):
        empresa_tecleada = self.convenio_empresa_texto.GetValue().strip()
        if not empresa_tecleada:
            wx.MessageBox(
                "Escribí el nombre de la empresa convenio.",
                "Empresa requerida", wx.OK | wx.ICON_ERROR, self,
            )
            return

        tasa_texto = self.convenio_tasa_texto.GetValue().strip()
        tasa = None
        if tasa_texto:
            try:
                tasa = float(tasa_texto.replace(",", ".")) / 100
            except ValueError:
                wx.MessageBox(
                    "La tasa de interés debe ser un número, por ejemplo 18.",
                    "Tasa inválida", wx.OK | wx.ICON_ERROR, self,
                )
                return
            if tasa < 0:
                wx.MessageBox(
                    "La tasa de interés no puede ser negativa.",
                    "Tasa inválida", wx.OK | wx.ICON_ERROR, self,
                )
                return

        # Reporte real del usuario (2026-07-12): "MIDESA" y "midesa" habían
        # quedado coexistiendo como si fueran dos empresas distintas —
        # empresa_convenio es TEXT PRIMARY KEY, y SQLite compara claves de
        # texto con colación BINARY (sensible a mayúsculas) por defecto, así
        # que guardar_tasa() nunca las trató como la misma fila. Acá, antes
        # de guardar, se busca una coincidencia SIN distinguir mayúsculas
        # contra lo ya cargado — si existe, se reutiliza el nombre EXACTO ya
        # guardado (no el que se acaba de tipear) para que la escritura
        # actualice esa misma fila en vez de crear una casi-duplicada.
        coincidencia = next(
            (empresa_existente for empresa_existente, _tasa in self._convenios_cargados
             if empresa_existente.upper() == empresa_tecleada.upper()),
            None,
        )
        empresa = coincidencia or empresa_tecleada
        ya_existia = coincidencia is not None

        conn = get_connection()
        try:
            guardar_tasa(conn, empresa, tasa)
        finally:
            conn.close()

        self._cargar_convenios()
        self._seleccionar_fila_por_empresa(empresa)
        accion = "actualizada" if ya_existia else "agregada"
        mensaje = f"Empresa convenio {accion}: {empresa}."
        self.convenio_mensaje.SetLabel(mensaje)
        self.GetTopLevelParent().SetStatusText(mensaje)
        # Reporte real del usuario (2026-07-12): "el lector de pantalla se
        # queda en silencio al confirmar acciones" — SetStatusText ya
        # dispara anunciar_texto_estado (evento de región viva MSAA), pero
        # ese mecanismo ya se había confirmado antes como no confiable para
        # este tipo de confirmación puntual (ver anunciar_voz_nvda en
        # accesibilidad.py, agregada exactamente por el mismo motivo para
        # "Filtrar por alerta" en Casos). mensaje_hablado permite un texto
        # más corto y específico ("Tasa actualizada.") cuando se confirma
        # desde el propio cuadro de tasa (Enter ahí) en vez de repetir el
        # mensaje largo con el nombre de la empresa.
        anunciar_voz_nvda(mensaje_hablado or mensaje)

    def _on_eliminar_convenio(self, event):
        empresa = self.convenio_empresa_texto.GetValue().strip()
        if not empresa:
            return

        confirmacion = wx.MessageBox(
            f'¿Eliminar la empresa convenio "{empresa}" y su tasa?',
            "Eliminar empresa convenio", wx.YES_NO | wx.ICON_WARNING, self,
        )
        if confirmacion != wx.YES:
            return

        conn = get_connection()
        try:
            eliminar_convenio(conn, empresa)
        finally:
            conn.close()

        self._cargar_convenios()
        self._on_nueva_empresa(event)
        mensaje = f'Empresa convenio "{empresa}" eliminada.'
        self.convenio_mensaje.SetLabel(mensaje)
        self.GetTopLevelParent().SetStatusText(mensaje)
        # Mismo motivo que en _on_guardar_convenio: SetStatusText por sí
        # solo no se escucha de forma confiable.
        anunciar_voz_nvda(mensaje)
