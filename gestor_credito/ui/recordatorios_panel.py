from datetime import datetime

import wx

from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, obtener_valor
from gestor_credito.db.database import get_connection
from gestor_credito.db.recordatorios import (
    actualizar_recordatorio,
    buscar_datos_credito_por_cedula,
    crear_recordatorio,
    eliminar_recordatorio,
    esta_vencido,
    listar_recordatorios,
    marcar_atendido,
)
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.fechas import formatear_fecha, parsear_fecha_ui
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import SONIDO_BORRAR, SONIDO_FILA_RECORDATORIO_VENCIDO, reproducir_sonido

COLUMNAS = [
    "Fecha a llamar", "Hora", "Nombre", "Cédula", "Celular", "Empresa", "Comentarios", "Estado",
]

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
        # Cédula "dueña" de lo que hay actualmente en Nombre/Celular/Empresa/
        # Fecha/Hora — de una fila seleccionada de la lista, o de la última
        # búsqueda por cédula que sí encontró/dejó algo cargado. Ver
        # _autocompletar_por_cedula: si la Cédula cambia respecto a esto, se
        # asume que el oficial ahora quiere otra persona y se desengancha
        # (bug real reportado por el usuario: guardar terminaba pisando el
        # registro de OTRO cliente porque el formulario seguía "abierto" con
        # los datos de la fila que había quedado seleccionada).
        self._cedula_cargada = None

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

        # Ctrl+Shift+A (pedido explícito del usuario, 2026-09-07): revela el
        # bloque de alta/edición y deja el foco en Cédula, sin importar qué
        # control de esta pestaña tenga el foco en ese momento — mismo
        # mecanismo EVT_CHAR_HOOK a nivel de panel que ya usa
        # CalculadoraSimplePanel para sus propios atajos Ctrl+Shift+<letra>,
        # sin chequeo de FindFocus() a propósito.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_atajo)

    def _on_atajo(self, event):
        if (
            event.ControlDown() and event.ShiftDown() and not event.AltDown()
            and event.GetKeyCode() == ord("A")
        ):
            self._mostrar_formulario()
            return
        event.Skip()

    def _crear_formulario(self):
        """Devuelve un sizer con DOS piezas, pedido explícito del usuario
        (2026-09-07): mientras no se esté agendando a nadie, los campos
        (Cédula...Comentarios, Marcar atendida, Eliminar) tienen que estar
        OCULTOS — no solo deshabilitados, fuera de la vista y del orden de
        Tab — y el botón que agrega/guarda ("A&gregar recordatorio"/"&Guardar
        cambios") tiene que quedar SIEMPRE visible fuera de ese bloque (antes
        vivía adentro, lo cual lo dejaba oculto también — sin forma de
        activarlo — corregido tras el reporte del usuario). Ese mismo botón
        hace doble función (ver _on_click_guardar): si el bloque está
        oculto, lo revela y deja el foco en Cédula; si ya está visible,
        guarda de verdad.

        self._panel_formulario envuelve el wx.StaticBoxSizer completo en un
        wx.Panel propio — Show()/Hide() sobre ESE panel oculta/revela el
        StaticBox y todos sus campos de un solo golpe (un wx.StaticBoxSizer
        por sí solo no tiene una única ventana para esconder)."""
        externo = wx.BoxSizer(wx.VERTICAL)

        self.guardar_btn = wx.Button(self, label="A&gregar recordatorio")
        self.guardar_btn.Bind(wx.EVT_BUTTON, self._on_click_guardar)
        activar_con_enter(self.guardar_btn)
        externo.Add(self.guardar_btn, 0, wx.BOTTOM, 8)

        self._panel_formulario = wx.Panel(self)
        box = wx.StaticBoxSizer(wx.VERTICAL, self._panel_formulario, "Agendar recordatorio")
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

        # Agregado 2026-09-07, pedido explícito del usuario: contexto de POR
        # QUÉ hay que llamar (ej. "pendiente enviar estado de cuenta") — fila
        # propia, no compartida con otro campo, porque necesita más ancho que
        # los de arriba. Multilínea: un motivo de llamada no siempre entra en
        # una sola línea.
        fila4 = wx.BoxSizer(wx.VERTICAL)
        comentarios_label = wx.StaticText(contenedor, label="Comentarios (contexto de la llamada):")
        self.comentarios_texto = wx.TextCtrl(contenedor, style=wx.TE_MULTILINE, size=(-1, 60))
        nombre_accesible(self.comentarios_texto, "Comentarios")
        # Enter solo: salto de línea normal (comportamiento nativo de un
        # TextCtrl multilínea, no se toca). Ctrl+Enter: guarda de una vez,
        # como si se hiciera Tab hasta el botón y se lo presionara — pedido
        # explícito del usuario, 2026-09-07.
        self.comentarios_texto.Bind(wx.EVT_KEY_DOWN, self._on_tecla_comentarios)
        fila4.Add(comentarios_label, 0, wx.BOTTOM, 4)
        fila4.Add(self.comentarios_texto, 0, wx.EXPAND)
        box.Add(fila4, 0, wx.EXPAND | wx.BOTTOM, 8)

        fila_botones = wx.BoxSizer(wx.HORIZONTAL)

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

        self._panel_formulario.SetSizer(box)
        self._panel_formulario.Hide()
        externo.Add(self._panel_formulario, 0, wx.EXPAND)

        return externo

    # ---- Autocompletado por cédula -----------------------------------------

    def _on_perder_foco_cedula(self, event):
        self._autocompletar_por_cedula()
        event.Skip()

    def _autocompletar_por_cedula(self):
        """Pedido explícito del usuario: "si coloco añadir cédula el mismo
        jale nombre del cliente empresa... si no existe pues lo añado yo".

        Tres bugs reales corregidos acá (reportes del usuario, 2026-09-07):
        1. Rellenar Nombre/Celular/Empresa con SetValue() no avisaba NADA por
           voz — el foco se queda en Cédula, así que NVDA nunca anunciaba el
           cambio en esos otros campos (SetValue() no dispara ningún anuncio
           de accesibilidad por sí solo). Ahora SIEMPRE se anuncia por voz el
           resultado, se haya encontrado o no.
        2. Si había una fila seleccionada (o una búsqueda anterior) y el
           oficial cambia la Cédula a otra persona sin darse cuenta de que el
           formulario seguía "enganchado" a esa fila, "Guardar cambios"
           terminaba PISANDO el registro viejo con los datos de la persona
           nueva en vez de crear un registro aparte. Ver _cedula_cargada:
           un cambio de Cédula respecto a lo ya cargado desengancha la fila
           seleccionada y limpia los campos que pertenecían a esa persona
           anterior, antes de buscar la nueva.
        3. Buscaba en Casos (cliente/caso) — el usuario aclaró que tiene que
           buscar en Historial de Créditos (reporte_credito, pestaña Ctrl+3)
           en su lugar: "no me sale la persona... es en el histórico que
           tienes que buscar, no en casos". Ver
           db.recordatorios.buscar_datos_credito_por_cedula. Esa tabla no
           tiene columna de teléfono, así que Celular nunca se autocompleta
           desde acá — el oficial siempre lo llena a mano.
        4. La letra final de una cédula (p. ej. "...010Q") en minúscula no
           encontraba nada — pedido explícito del usuario: tiene que ser
           indiferente, nunca un error. Se normaliza a MAYÚSCULA acá mismo
           (se reescribe el cuadro con .upper(), ver más abajo) antes de
           buscar y de guardar, para que el dato quede siempre consistente
           sin importar cómo se haya tecleado.
        """
        cedula = self.cedula_texto.GetValue().strip().upper()
        if not cedula:
            return
        self.cedula_texto.ChangeValue(cedula)

        # Si NADA se había cargado todavía (_cedula_cargada es None: primera
        # vez que se busca en este formulario), no hay nada de qué
        # desengancharse — así, escribir el Nombre a mano ANTES de terminar
        # de tipear la Cédula sigue funcionando (no se pisa). Solo se limpia
        # cuando la Cédula cambia respecto a una identidad que YA estaba
        # cargada (fila seleccionada, o una búsqueda anterior en esta misma
        # sesión del formulario).
        if self._cedula_cargada is not None and cedula != self._cedula_cargada:
            self._desvincular_fila_seleccionada()

        conn = get_connection()
        try:
            datos = buscar_datos_credito_por_cedula(conn, cedula)
        finally:
            conn.close()

        self._cedula_cargada = cedula

        if datos is None:
            mensaje = (
                f"No se encontró ningún crédito con la cédula {cedula} en Historial de "
                "Créditos. Completá los datos a mano."
            )
            self.mensaje_texto.SetLabel(mensaje)
            self.GetTopLevelParent().SetStatusText(mensaje)
            anunciar_voz_nvda(mensaje)
            return

        if not self.nombre_texto.GetValue().strip() and datos["nombre"]:
            self.nombre_texto.SetValue(datos["nombre"])
        if not self.celular_texto.GetValue().strip() and datos["telefono"]:
            self.celular_texto.SetValue(datos["telefono"])
        if not self.empresa_texto.GetValue().strip() and datos["empresa_convenio"]:
            self.empresa_texto.SetValue(datos["empresa_convenio"])

        mensaje = f"Cliente encontrado: {datos['nombre']}."
        self.mensaje_texto.SetLabel(mensaje)
        self.GetTopLevelParent().SetStatusText(mensaje)
        anunciar_voz_nvda(mensaje)

    # ---- Mostrar/ocultar el bloque de alta/edición ---------------------------

    def _mostrar_formulario(self):
        """Revela Cédula...Comentarios/Marcar atendida/Eliminar y deja el
        foco en Cédula — vía Ctrl+Shift+A, o al presionar "Agregar
        recordatorio" mientras el bloque está oculto (ver
        _on_click_guardar). No limpia nada: si ya había algo tecleado, se
        respeta (solo importa cuando el bloque YA estaba oculto, y el
        bloque solo queda oculto con los campos ya vacíos, ver
        _ocultar_formulario)."""
        self._panel_formulario.Show()
        self.Layout()
        self.cedula_texto.SetFocus()

    def _ocultar_formulario(self):
        """Vuelve al estado por defecto pedido explícitamente por el
        usuario: "mientras no vayamos a añadir a alguien estos campos deben
        de estar ocultos". Se llama después de completar cualquier acción
        sobre un recordatorio (guardar, marcar atendida, eliminar) y desde
        Ctrl+D — nunca a medias con datos sin guardar todavía en pantalla."""
        self._panel_formulario.Hide()
        self.Layout()

    # ---- Alta / edición -----------------------------------------------------

    def _on_click_guardar(self, event):
        """El único botón visible por defecto hace doble función (pedido
        explícito del usuario tras señalar que tener un botón aparte solo
        para revelar el formulario era redundante): si el bloque de campos
        todavía está oculto, este clic lo revela (equivalente a Ctrl+Shift+A)
        en vez de intentar guardar nada; si ya está visible, sí guarda de
        verdad."""
        if not self._panel_formulario.IsShown():
            self._mostrar_formulario()
            return
        self._guardar()

    def _on_tecla_comentarios(self, event):
        """Ctrl+Enter en el cuadro Comentarios guarda de una vez (como si se
        hiciera Tab hasta el botón y se lo presionara) — pedido explícito
        del usuario. Enter SOLO (sin Ctrl) se deja pasar sin tocar
        (event.Skip()) para que el TextCtrl multilínea inserte su salto de
        línea normal, comportamiento nativo que no hay que romper."""
        if (
            event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and event.ControlDown()
        ):
            self._guardar()
            return
        event.Skip()

    def _guardar(self):
        nombre = self.nombre_texto.GetValue().strip()
        # .upper(): misma normalización que _autocompletar_por_cedula — por
        # si "Guardar" se dispara sin haber pasado por ahí (defensa extra,
        # no debería pasar en el flujo normal ya que salir del cuadro
        # Cédula con Tab dispara EVT_KILL_FOCUS antes del clic del botón).
        cedula = self.cedula_texto.GetValue().strip().upper() or None
        celular = self.celular_texto.GetValue().strip() or None
        empresa = self.empresa_texto.GetValue().strip() or None
        comentarios = self.comentarios_texto.GetValue().strip() or None
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
                    conn, nombre, cedula, celular, empresa, fecha_iso, hora, ejecutivo_actual,
                    comentarios,
                )
                mensaje = "Recordatorio agregado."
            else:
                actualizar_recordatorio(
                    conn, self._recordatorio_seleccionado_id, nombre, cedula, celular,
                    empresa, fecha_iso, hora, comentarios,
                )
                mensaje = "Cambios guardados."
        finally:
            conn.close()

        self._limpiar_formulario_interno()
        self._ocultar_formulario()
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
        self._ocultar_formulario()
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
        self._ocultar_formulario()
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
        de la app. También vuelve a ocultar el bloque de campos: Ctrl+D es
        "cancelar/empezar de cero", así que si estaba abierto por Ctrl+Shift+A
        o por haber seleccionado una fila, se cierra de nuevo."""
        self._limpiar_formulario_interno()
        self._ocultar_formulario()
        reproducir_sonido(SONIDO_BORRAR)

    def enfocar_resultados(self):
        """Atajo GLOBAL Ctrl+R (pedido explícito del usuario, 2026-09-07:
        "con control r vamos a caer en la lista, ese lo dejaremos como
        comando universal en las listas de clientes menos en las
        calculadoras") — lleva el foco a la lista de recordatorios. Si no
        hay ningún ítem seleccionado todavía, selecciona el primero para que
        las flechas funcionen de inmediato al llegar con el atajo, mismo
        criterio que CasosPanel.enfocar_resultados()/
        CreditosPanel.enfocar_resultados()."""
        if self.lista.GetItemCount() == 0:
            self.lista.SetFocus()
            return

        if self.lista.GetFirstSelected() == -1:
            estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
            self.lista.SetItemState(0, estado, estado)

        self.lista.SetFocus()

    def _desvincular_fila_seleccionada(self):
        """Deja de editar la fila seleccionada (si había una) y borra
        Nombre/Celular/Empresa/Comentarios/Fecha/Hora — esos datos
        pertenecían a la persona anterior, ya no corresponden. Cédula NO se
        toca acá a propósito: quien llama a esto (_autocompletar_por_cedula)
        lo hace justo después de leer lo que el oficial ya tecleó ahí, para
        buscar con ese valor."""
        indice = self.lista.GetFirstSelected()
        if indice != wx.NOT_FOUND:
            estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
            self.lista.SetItemState(indice, 0, estado)

        self._recordatorio_seleccionado_id = None
        self.nombre_texto.SetValue("")
        self.celular_texto.SetValue("")
        self.empresa_texto.SetValue("")
        self.comentarios_texto.SetValue("")
        self.fecha_texto.SetValue("")
        self.hora_texto.SetValue("")
        self.guardar_btn.SetLabel("A&gregar recordatorio")
        self.marcar_atendido_btn.Disable()
        self.eliminar_btn.Disable()

    def _limpiar_formulario_interno(self):
        self._desvincular_fila_seleccionada()
        self._cedula_cargada = None
        self.cedula_texto.SetValue("")
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
                # Saltos de línea aplanados a espacio: una celda de
                # wx.ListCtrl con \n adentro se lee/ve mal, el texto completo
                # con formato sigue disponible al seleccionar la fila (ver
                # _on_seleccionar, que carga el valor real en el cuadro).
                comentarios_fila = (fila["comentarios"] or "").replace("\n", " ").replace("\r", " ")
                valores = [
                    formatear_fecha(fila["fecha_llamar"]), fila["hora_llamar"] or "",
                    fila["nombre"] or "", fila["cedula"] or "", fila["celular"] or "",
                    fila["empresa_convenio"] or "", comentarios_fila, estado_texto,
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

        # Revela el bloque de campos para poder editar la fila (sin mover el
        # foco: EVT_LIST_ITEM_SELECTED dispara en cada flecha mientras se
        # navega la lista, así que robarle el foco a la lista en cada tecla
        # sería un desastre — el foco se queda donde estaba, normalmente en
        # la propia lista).
        if not self._panel_formulario.IsShown():
            self._panel_formulario.Show()
            self.Layout()

        self._recordatorio_seleccionado_id = fila["id"]
        self._cedula_cargada = fila["cedula"] or ""
        self.cedula_texto.SetValue(fila["cedula"] or "")
        self.nombre_texto.SetValue(fila["nombre"] or "")
        self.celular_texto.SetValue(fila["celular"] or "")
        self.empresa_texto.SetValue(fila["empresa_convenio"] or "")
        self.comentarios_texto.SetValue(fila["comentarios"] or "")
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
