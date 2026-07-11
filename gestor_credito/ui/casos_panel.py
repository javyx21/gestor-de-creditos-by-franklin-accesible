import wx

from gestor_credito.catalogos import (
    ESTADO_DESEMBOLSADA,
    ESTADOS_CERRADOS,
    ETAPA_DESEMBOLSO,
    ETAPAS_PROCESO,
    ESTADOS_SOLICITUD,
    RESPONSABLES_ACTUALES,
    formatear_microseguro,
)
from gestor_credito.db.alertas import marcar_documentos_completos, marcar_documentos_pendientes
from gestor_credito.db.casos import (
    FILTRO_ALERTA_CONSTANCIA_EN_MANO,
    FILTRO_ALERTA_CONSTANCIA_PENDIENTE,
    FILTRO_ALERTA_DOCUMENTOS_PENDIENTES,
    FILTRO_ALERTA_TODOS,
    actualizar_edicion_manual,
    actualizar_responsable_actual,
    buscar_casos,
    eliminar_caso,
)
from gestor_credito.db.clientes import contar_casos, eliminar_cliente
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, obtener_valor
from gestor_credito.db.database import get_connection
from gestor_credito.ui.accesibilidad import activar_con_enter
from gestor_credito.ui.fechas import formatear_fecha
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import (
    SONIDO_BORRAR,
    SONIDO_FILA_DOCUMENTOS_PENDIENTES,
    reproducir_sonido,
)

# Orden y set de columnas pedido por el usuario para la lista de Casos. Debe
# coincidir en orden con el SELECT interno de buscar_casos() en gestor_credito/db/casos.py.
COLUMNAS = [
    "Fecha Registro", "No. Presolicitud", "Ejecutivo", "Empresa Convenio",
    "Nombre del Cliente", "Identificación", "Teléfono", "Monto Solicitado",
    "Destino del Crédito", "Microseguro", "Estado Solicitud", "Etapa Proceso",
    "Responsable Actual", "Decisión", "Motivo No Aplica / Desistimiento", "Observaciones",
]

# Posición de estado_solicitud/documentos_completos_fecha dentro de las tuplas
# que devuelve buscar_casos() (ver el SELECT de _seleccionar_casos() en
# gestor_credito/db/casos.py) — se usan para el resaltado en rojo de la fila y
# el sonido de navegación, ninguno de los dos es una columna visible.
_INDICE_ESTADO_SOLICITUD_FILA = 11
_INDICE_DOCUMENTOS_COMPLETOS_FECHA_FILA = 18

# Opciones del combobox "Filtrar por alerta": (texto mostrado, valor interno
# de gestor_credito/db/casos.py). Solo aplica con la búsqueda vacía — con un
# término de cédula/nombre escrito, se ignora igual que ejecutivo_actual.
FILTRO_ALERTA_OPCIONES = [
    ("Todos", FILTRO_ALERTA_TODOS),
    ("Documentos pendientes", FILTRO_ALERTA_DOCUMENTOS_PENDIENTES),
    ("En espera de constancia", FILTRO_ALERTA_CONSTANCIA_PENDIENTE),
    ("Constancia en mano sin respuesta", FILTRO_ALERTA_CONSTANCIA_EN_MANO),
]


class CasosPanel(wx.Panel):
    CELDA_VACIA = "Celda vacía"

    # Resalta en rojo, para el vidente, la fila de un caso con documentos
    # pendientes (mismo criterio que FILTRO_ALERTA_DOCUMENTOS_PENDIENTES: caso
    # no cerrado + documentos_completos_fecha aún NULL). Fondo rosado claro +
    # texto rojo oscuro en vez de rojo puro: contraste ~7.5:1 (negro/blanco
    # sobre esta combinación pasa WCAG AAA, no solo el mínimo AA de 4.5:1),
    # verificado a mano antes de fijar estos valores — no cambiar los colores
    # sin volver a chequear el contraste. Pedido explícito del usuario junto
    # con SONIDO_FILA_DOCUMENTOS_PENDIENTES (ver sonido.py) como equivalente
    # auditivo para el usuario ciego que navega la misma lista con NVDA — el
    # color solo no basta (WCAG 1.4.1), por eso van los dos juntos.
    _COLOR_FONDO_DOCUMENTOS_PENDIENTES = wx.Colour(255, 214, 214)
    _COLOR_TEXTO_DOCUMENTOS_PENDIENTES = wx.Colour(139, 0, 0)

    def __init__(self, parent):
        super().__init__(parent)

        self._filas = []
        self._caso_seleccionado_id = None
        self._caso_seleccionado_no_presolicitud = None
        self._cliente_seleccionado_id = None
        self._cliente_seleccionado_nombre = None
        self._cliente_seleccionado_cedula = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Casos")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_busqueda(), 0, wx.EXPAND | wx.ALL, 8)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.lista.SetName("Lista de casos")
        for indice, columna in enumerate(COLUMNAS):
            self.lista.InsertColumn(indice, columna)
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_seleccionar_caso)
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self._on_menu_contextual)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        sizer.Add(self._crear_panel_edicion(), 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self._cargar_casos(avisar_sin_resultados=False)

    def _crear_busqueda(self):
        box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Buscar")
        contenedor = box.GetStaticBox()

        label = wx.StaticText(contenedor, label="Cédula o nombre del cliente:")
        self.busqueda_texto = wx.TextCtrl(contenedor, style=wx.TE_PROCESS_ENTER)
        self.busqueda_texto.SetName("Buscar por cédula o nombre")
        self.busqueda_texto.Bind(wx.EVT_TEXT_ENTER, lambda event: self._cargar_casos())

        buscar_btn = wx.Button(contenedor, label="&Buscar")
        buscar_btn.Bind(wx.EVT_BUTTON, lambda event: self._cargar_casos())
        activar_con_enter(buscar_btn)

        limpiar_btn = wx.Button(contenedor, label="&Limpiar búsqueda")
        limpiar_btn.Bind(wx.EVT_BUTTON, self._on_limpiar_busqueda)
        activar_con_enter(limpiar_btn)

        filtro_label = wx.StaticText(contenedor, label="Filtrar por alerta:")
        self.filtro_alerta_choice = wx.Choice(
            contenedor, choices=[texto for texto, _valor in FILTRO_ALERTA_OPCIONES]
        )
        self.filtro_alerta_choice.SetName("Filtrar por alerta")
        self.filtro_alerta_choice.SetSelection(0)
        self.filtro_alerta_choice.Bind(
            wx.EVT_CHOICE, lambda event: self._cargar_casos(avisar_sin_resultados=False)
        )

        for control in (label, self.busqueda_texto, buscar_btn, limpiar_btn, filtro_label, self.filtro_alerta_choice):
            box.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        return box

    def _crear_panel_edicion(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Editar caso seleccionado")
        contenedor = box.GetStaticBox()

        self.caso_seleccionado_texto = wx.StaticText(contenedor, label="Ningún caso seleccionado")
        box.Add(self.caso_seleccionado_texto, 0, wx.BOTTOM, 8)

        # Es del cliente, no del caso (documentos_completos_fecha vive en
        # cliente — ver CLAUDE.md), por eso el label lo aclara: marcar acá
        # apaga la Alerta "Documentos pendientes" para todos los casos de ese
        # cliente, no solo el seleccionado. Se marca al tildar el checkbox
        # (acción inmediata, sin depender de "Guardar cambios" ni de esperar a
        # que la alerta ya esté activa en Notificaciones — pedido explícito
        # del usuario: poder decir "ya completó, ignoralo" apenas ve el caso).
        # Es de una sola vía: una vez marcado (documentos_completos_fecha ya
        # tiene valor) el checkbox queda tildado y deshabilitado, no se puede
        # desmarcar desde acá.
        self.documentos_completos_check = wx.CheckBox(
            contenedor, label="Documentos completados (cliente)"
        )
        self.documentos_completos_check.Bind(wx.EVT_CHECKBOX, self._on_documentos_completos_check)
        self.documentos_completos_check.Disable()
        box.Add(self.documentos_completos_check, 0, wx.BOTTOM, 8)

        fila = wx.BoxSizer(wx.HORIZONTAL)

        estado_label = wx.StaticText(contenedor, label="Estado Solicitud:")
        self.estado_choice = wx.Choice(contenedor, choices=ESTADOS_SOLICITUD)
        self.estado_choice.SetName("Estado Solicitud")

        etapa_label = wx.StaticText(contenedor, label="Etapa Proceso:")
        self.etapa_choice = wx.Choice(contenedor, choices=ETAPAS_PROCESO)
        self.etapa_choice.SetName("Etapa Proceso")

        self.guardar_btn = wx.Button(contenedor, label="&Guardar cambios")
        self.guardar_btn.Bind(wx.EVT_BUTTON, self._on_guardar)
        self.guardar_btn.Disable()
        activar_con_enter(self.guardar_btn)

        # Borra SOLO este caso (cliente y demás casos intactos) — mismo
        # botón/acción que "Eliminar caso" del menú contextual (ver
        # _eliminar_caso_seleccionado). Borrar el cliente completo con todo su
        # historial es una operación más rara/peligrosa que se dejó solo en
        # el menú contextual ("Eliminar cliente y todo su historial"), para
        # que no sea la opción a mano en el flujo normal de trabajo —
        # confirmado con el usuario tras un susto real probando esto: pensó
        # que borraba solo el caso seleccionado y el mensaje le avisó que iba
        # a borrar también el resto del historial del cliente.
        self.eliminar_btn = wx.Button(contenedor, label="Elimina&r caso")
        self.eliminar_btn.Bind(wx.EVT_BUTTON, self._on_eliminar_caso)
        self.eliminar_btn.Disable()
        activar_con_enter(self.eliminar_btn)

        for control in (
            estado_label, self.estado_choice, etapa_label, self.etapa_choice,
            self.guardar_btn, self.eliminar_btn,
        ):
            fila.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        box.Add(fila, 0)

        self.mensaje_texto = wx.StaticText(contenedor, label="")
        box.Add(self.mensaje_texto, 0, wx.TOP, 8)

        return box

    def _on_limpiar_busqueda(self, event):
        self.limpiar_busqueda()

    def limpiar_busqueda(self):
        """Vacía la búsqueda y el filtro de alerta. Reproduce un sonido de
        confirmación (borrar.wav) porque limpiar no deja ningún cambio visual
        obvio con foco en el botón — pedido explícito del usuario para
        confirmar que sí se borró todo sin tener que leer la barra de estado
        a mano. Público (no "_on_...") porque también lo dispara el atajo
        Alt+L (ver gestor_credito/ui/atajos.py y MainFrame._crear_atajos)."""
        self.busqueda_texto.SetValue("")
        self.filtro_alerta_choice.SetSelection(0)
        self._cargar_casos(avisar_sin_resultados=False)
        reproducir_sonido(SONIDO_BORRAR)

    def enfocar_busqueda(self):
        """Atajo Ctrl+F: lleva el foco directo al cuadro de búsqueda sin
        importar qué control tenga el foco en ese momento."""
        self.busqueda_texto.SetFocus()
        self.busqueda_texto.SelectAll()

    def enfocar_resultados(self):
        """Atajo Ctrl+R: lleva el foco a la lista de resultados de Casos. Si
        no hay ningún ítem seleccionado todavía, selecciona el primero para
        que las flechas funcionen de inmediato al llegar con el atajo."""
        if self.lista.GetItemCount() == 0:
            self.lista.SetFocus()
            return

        if self.lista.GetFirstSelected() == -1:
            estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
            self.lista.SetItemState(0, estado, estado)

        self.lista.SetFocus()

    def _on_menu_contextual(self, event):
        """Menú contextual (click derecho o tecla de menú del teclado) con
        todas las acciones posibles sobre el caso/cliente bajo el cursor (o el
        ya seleccionado, si se invoca desde el teclado). La navegación por
        flechas/Enter/Esc dentro del menú y sus submenús es el comportamiento
        nativo de wx.Menu en Windows — no hace falta cablearla a mano."""
        posicion_pantalla = event.GetPosition()

        if posicion_pantalla != wx.DefaultPosition:
            # Click derecho sobre una fila distinta a la seleccionada: la
            # selecciona primero (dispara _on_seleccionar_caso), igual que el
            # comportamiento estándar de un wx.ListCtrl/Explorador de Windows.
            posicion_lista = self.lista.ScreenToClient(posicion_pantalla)
            indice, _bandera = self.lista.HitTest(posicion_lista)
            if indice != wx.NOT_FOUND:
                estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
                self.lista.SetItemState(indice, estado, estado)

        if self._caso_seleccionado_id is None:
            self.GetTopLevelParent().SetStatusText("Seleccioná un caso para ver sus acciones.")
            return

        if posicion_pantalla == wx.DefaultPosition:
            # Invocado con la tecla de menú del teclado, sin coordenadas de
            # mouse: mostrar el menú junto a la fila seleccionada.
            rect = self.lista.GetItemRect(self.lista.GetFirstSelected())
            posicion = (rect.x, rect.y + rect.height)
        else:
            posicion = self.lista.ScreenToClient(posicion_pantalla)

        menu = self._construir_menu_contextual()
        self.lista.PopupMenu(menu, posicion)
        menu.Destroy()

    def _construir_menu_contextual(self):
        menu = wx.Menu()

        submenu_estado = wx.Menu()
        for valor in ESTADOS_SOLICITUD:
            item = submenu_estado.Append(wx.ID_ANY, valor)
            self.Bind(wx.EVT_MENU, self._crear_manejador_cambiar_estado(valor), item)
        menu.AppendSubMenu(submenu_estado, "Cambiar estatus de solicitud")

        item_desembolso = menu.Append(wx.ID_ANY, "Cambiar estado a desembolso")
        self.Bind(wx.EVT_MENU, self._on_cambiar_a_desembolso, item_desembolso)

        submenu_responsable = wx.Menu()
        for valor in RESPONSABLES_ACTUALES:
            item = submenu_responsable.Append(wx.ID_ANY, valor)
            self.Bind(wx.EVT_MENU, self._crear_manejador_cambiar_responsable(valor), item)
        menu.AppendSubMenu(submenu_responsable, "Cambiar quién tiene el caso en su poder")

        menu.AppendSeparator()

        # Vía alternativa al checkbox "Documentos completados (cliente)" del
        # panel de edición: un ítem de menú requiere navegar el menú y
        # confirmar con Enter, mientras que el checkbox se dispara con un solo
        # Tab+Espacio durante la navegación normal — eso causó un bug real en
        # producción (varios clientes marcados como completados por accidente,
        # sin querer, simplemente al tabular por la lista). El checkbox se deja
        # como está para quien prefiera usarlo viendo la pantalla; esta opción
        # de menú es la vía segura pedida explícitamente por el usuario tras
        # ese incidente. Junto con "Marcar como pendiente" (ya existía) para
        # poder ir en ambos sentidos desde acá.
        item_completo = menu.Append(wx.ID_ANY, "Marcar documentos completados (cliente)")
        self.Bind(wx.EVT_MENU, self._on_marcar_documentos_completos_menu, item_completo)

        item_pendiente = menu.Append(wx.ID_ANY, "Marcar como pendiente de completar documentos")
        self.Bind(wx.EVT_MENU, self._on_marcar_documentos_pendientes, item_pendiente)

        menu.AppendSeparator()

        # Dos acciones distintas y deliberadamente separadas: "Eliminar caso"
        # (la común, borra solo este caso) y "Eliminar cliente y todo su
        # historial" (rara/peligrosa, borra el cliente y TODOS sus casos) —
        # ver _eliminar_caso_seleccionado() y _eliminar_cliente_seleccionado().
        item_eliminar_caso = menu.Append(wx.ID_ANY, "Eliminar caso")
        self.Bind(wx.EVT_MENU, self._on_eliminar_caso, item_eliminar_caso)

        item_eliminar_cliente = menu.Append(wx.ID_ANY, "Eliminar cliente y todo su historial")
        self.Bind(wx.EVT_MENU, self._on_eliminar_cliente_completo, item_eliminar_cliente)

        return menu

    def _crear_manejador_cambiar_estado(self, valor):
        return lambda event: self._cambiar_estado_solicitud(valor)

    def _crear_manejador_cambiar_responsable(self, valor):
        return lambda event: self._cambiar_responsable_actual(valor)

    def _cambiar_estado_solicitud(self, nuevo_estado):
        """Cambia solo Estado Solicitud, sin tocar Etapa Proceso — misma
        lógica que "Guardar cambios" (actualizar_edicion_manual), reutilizando
        la Etapa Proceso ya cargada en el panel de edición para el caso
        seleccionado."""
        if self._caso_seleccionado_id is None:
            return

        etapa_actual = self.etapa_choice.GetStringSelection() or None
        conn = get_connection()
        try:
            actualizar_edicion_manual(conn, self._caso_seleccionado_id, nuevo_estado, etapa_actual)
        finally:
            conn.close()

        self.GetTopLevelParent().SetStatusText(f"Estado Solicitud cambiado a «{nuevo_estado}».")
        self._cargar_casos()

    def _on_cambiar_a_desembolso(self, event):
        if self._caso_seleccionado_id is None:
            return

        conn = get_connection()
        try:
            actualizar_edicion_manual(
                conn, self._caso_seleccionado_id, ESTADO_DESEMBOLSADA, ETAPA_DESEMBOLSO
            )
        finally:
            conn.close()

        self.GetTopLevelParent().SetStatusText("Caso marcado como Desembolsada / Desembolso.")
        self._cargar_casos()

    def _cambiar_responsable_actual(self, valor):
        if self._caso_seleccionado_id is None:
            return

        conn = get_connection()
        try:
            actualizar_responsable_actual(conn, self._caso_seleccionado_id, valor)
        finally:
            conn.close()

        self.GetTopLevelParent().SetStatusText(f"Responsable Actual cambiado a «{valor}».")
        self._cargar_casos()

    def _on_marcar_documentos_completos_menu(self, event):
        """Vía "segura" para marcar documentos completados (ver comentario en
        _construir_menu_contextual): a diferencia del checkbox del panel de
        edición (que se deja como está, a propósito, sin confirmación — ver
        CLAUDE.md), esta sí pide confirmar el nombre exacto antes de guardar,
        mismo patrón que _eliminar_caso_seleccionado(). Se agregó tras un
        reporte real del usuario (semana de uso en producción, 2026-07-11): en
        ocasiones el cliente marcado no era el que tenía activo. No se pudo
        reproducir la causa de fondo a nivel de código (la selección de la
        lista y la escritura en base de datos son correctas y sincrónicas en
        todos los casos revisados), así que esta confirmación es la red de
        seguridad: si el nombre leído acá no coincide con el cliente que el
        usuario cree tener activo, puede cancelar antes de que se guarde nada."""
        if self._cliente_seleccionado_id is None:
            return

        nombre = self._cliente_seleccionado_nombre or "(sin nombre)"
        cedula = self._cliente_seleccionado_cedula or "(sin cédula)"
        mensaje = f"¿Marcar a {nombre} (Cédula {cedula}) como documentos completados?"
        confirmacion = wx.MessageBox(
            mensaje, "Marcar documentos completados", wx.YES_NO | wx.ICON_QUESTION, self
        )
        if confirmacion != wx.YES:
            return

        conn = get_connection()
        try:
            marcar_documentos_completos(conn, self._cliente_seleccionado_id)
        finally:
            conn.close()

        self.GetTopLevelParent().SetStatusText(f"Documentos marcados como completados para {nombre}.")
        self._cargar_casos()

    def _on_marcar_documentos_pendientes(self, event):
        if self._cliente_seleccionado_id is None:
            return

        conn = get_connection()
        try:
            marcar_documentos_pendientes(conn, self._cliente_seleccionado_id)
        finally:
            conn.close()

        self.GetTopLevelParent().SetStatusText("Documentos marcados como pendientes nuevamente.")
        self._cargar_casos()

    def _on_eliminar_caso(self, event):
        self._eliminar_caso_seleccionado()

    def _eliminar_caso_seleccionado(self):
        """Handler compartido por el botón "Elimina&r caso" del panel de
        edición y el ítem "Eliminar caso" del menú contextual. Borra SOLO el
        caso seleccionado (eliminar_caso() en db/casos.py) — el cliente y sus
        demás casos quedan intactos, por eso el mensaje de confirmación lo
        aclara explícitamente (ver _eliminar_cliente_seleccionado() más abajo
        para la operación en cascada, que sí borra todo el historial)."""
        if self._caso_seleccionado_id is None:
            return

        no_presolicitud = self._caso_seleccionado_no_presolicitud or "(sin número)"
        mensaje = (
            f"¿Eliminar el caso No. Presolicitud {no_presolicitud}?\n\n"
            "El cliente y sus demás casos no se ven afectados. "
            "Esta acción no se puede deshacer."
        )
        confirmacion = wx.MessageBox(
            mensaje, "Eliminar caso", wx.YES_NO | wx.ICON_WARNING, self
        )
        if confirmacion != wx.YES:
            return

        conn = get_connection()
        try:
            eliminar_caso(conn, self._caso_seleccionado_id)
        finally:
            conn.close()

        reproducir_sonido(SONIDO_BORRAR)
        self.GetTopLevelParent().SetStatusText(f"Caso {no_presolicitud} eliminado.")
        self._cargar_casos()

    def _on_eliminar_cliente_completo(self, event):
        self._eliminar_cliente_seleccionado()

    def _eliminar_cliente_seleccionado(self):
        """Solo disponible desde "Eliminar cliente y todo su historial" del
        menú contextual (no hay botón equivalente en el panel principal —
        confirmado con el usuario tras un susto real: pensó que "Eliminar
        caso" iba a borrar todo el historial y no era así). Borra el CLIENTE
        completo y TODOS sus casos (no solo el seleccionado, ver
        eliminar_cliente() en db/clientes.py); el mensaje de confirmación
        muestra cuántos casos se van a perder para que quede claro el
        alcance antes de confirmar."""
        if self._cliente_seleccionado_id is None:
            return

        nombre = self._cliente_seleccionado_nombre or "(sin nombre)"
        cedula = self._cliente_seleccionado_cedula or "(sin cédula)"

        conn = get_connection()
        try:
            total_casos = contar_casos(conn, self._cliente_seleccionado_id)
        finally:
            conn.close()

        mensaje = (
            f"¿Eliminar a {nombre} (Cédula {cedula}) y TODO su historial "
            f"({total_casos} caso(s))?\n\n"
            "Esta acción no se puede deshacer."
        )
        confirmacion = wx.MessageBox(
            mensaje, "Eliminar cliente y todo su historial", wx.YES_NO | wx.ICON_WARNING, self
        )
        if confirmacion != wx.YES:
            return

        conn = get_connection()
        try:
            eliminar_cliente(conn, self._cliente_seleccionado_id)
        finally:
            conn.close()

        reproducir_sonido(SONIDO_BORRAR)
        self.GetTopLevelParent().SetStatusText(f"Cliente {nombre} y todo su historial eliminados.")
        self._cargar_casos()

    def recargar(self):
        """Vuelve a consultar la base de datos con la búsqueda/agente actuales.

        Se llama al entrar a esta pestaña (ver MainFrame) para que un cambio de
        ejecutivo_actual hecho en Configuración se refleje sin que el usuario
        tenga que volver a apretar "Buscar" a mano.
        """
        self._cargar_casos(avisar_sin_resultados=False)

    def _cargar_casos(self, avisar_sin_resultados=True):
        """avisar_sin_resultados controla el wx.MessageBox de "Sin resultados":
        solo debe dispararse ante una búsqueda EXPLÍCITA (Enter/"Buscar"), no
        ante un refresco silencioso (carga inicial, recargar(), "Limpiar
        búsqueda") ni, sobre todo, ante cada cambio del combobox "Filtrar por
        alerta" — este último se dispara con cada flecha arriba/abajo mientras
        se navega el combobox, y abrir un diálogo modal en cada tecla dejaba
        el filtro inusable (reporte real del usuario). El estado siempre
        queda igual reflejado en la barra de estado, con o sin el popup.
        """
        termino = self.busqueda_texto.GetValue().strip() or None
        _texto, filtro_alerta = FILTRO_ALERTA_OPCIONES[self.filtro_alerta_choice.GetSelection()]

        conn = get_connection()
        try:
            ejecutivo_actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            try:
                self._filas = buscar_casos(
                    conn, ejecutivo_actual=ejecutivo_actual, termino=termino, filtro_alerta=filtro_alerta
                )
            except ValueError as exc:
                self._filas = []
                self._refrescar_lista()
                self.GetTopLevelParent().SetStatusText(str(exc))
                wx.MessageBox(str(exc), "Búsqueda inválida", wx.OK | wx.ICON_ERROR, self)
                return
        finally:
            conn.close()

        self._refrescar_lista()

        if self._filas:
            self.GetTopLevelParent().SetStatusText(f"{len(self._filas)} caso(s) encontrados")
        else:
            mensaje = "No se encontraron resultados."
            self.GetTopLevelParent().SetStatusText(mensaje)
            if avisar_sin_resultados:
                wx.MessageBox(mensaje, "Sin resultados", wx.OK | wx.ICON_INFORMATION, self)

    def _refrescar_lista(self):
        self.lista.DeleteAllItems()
        for fila in self._filas:
            valores = self._fila_a_columnas(fila)
            indice = self.lista.InsertItem(self.lista.GetItemCount(), valores[0])
            for columna, valor in enumerate(valores[1:], start=1):
                self.lista.SetItem(indice, columna, valor)

            estado = fila[_INDICE_ESTADO_SOLICITUD_FILA]
            documentos_completos_fecha = fila[_INDICE_DOCUMENTOS_COMPLETOS_FECHA_FILA]
            if self._documentos_pendientes(estado, documentos_completos_fecha):
                self.lista.SetItemBackgroundColour(indice, self._COLOR_FONDO_DOCUMENTOS_PENDIENTES)
                self.lista.SetItemTextColour(indice, self._COLOR_TEXTO_DOCUMENTOS_PENDIENTES)

        for columna in range(len(COLUMNAS)):
            self.lista.SetColumnWidth(columna, wx.LIST_AUTOSIZE_USEHEADER)

        self._caso_seleccionado_id = None
        self._caso_seleccionado_no_presolicitud = None
        self._cliente_seleccionado_id = None
        self._cliente_seleccionado_nombre = None
        self._cliente_seleccionado_cedula = None
        self.guardar_btn.Disable()
        self.eliminar_btn.Disable()
        self.documentos_completos_check.SetValue(False)
        self.documentos_completos_check.Disable()
        self.documentos_completos_check.Show(True)
        self.Layout()
        self.caso_seleccionado_texto.SetLabel("Ningún caso seleccionado")

    @classmethod
    def _fila_a_columnas(cls, fila):
        (
            _caso_id, fecha_registro, no_presolicitud, ejecutivo, empresa_convenio,
            nombre, cedula, telefono, monto_solicitado, destino_credito, microseguro,
            estado, etapa, responsable_actual, decision, motivo_no_aplica, observaciones,
            _cliente_id, _documentos_completos_fecha, _constancia_recibida_fecha,
        ) = fila

        monto_texto = f"{monto_solicitado:,.2f}" if monto_solicitado is not None else ""

        valores = [
            formatear_fecha(fecha_registro), no_presolicitud or "", ejecutivo or "", empresa_convenio or "",
            nombre or "", cedula or "", telefono or "", monto_texto, destino_credito or "",
            formatear_microseguro(microseguro), estado or "", etapa or "", responsable_actual or "",
            decision or "", motivo_no_aplica or "", observaciones or "",
        ]
        # Celda vacía en vez de texto en blanco: para NVDA, una celda vacía en un
        # wx.ListCtrl se lee repitiendo solo el nombre de columna sin ningún valor,
        # lo cual sonaba igual en fila tras fila. Con este texto queda claro que
        # el dato no aplica a ese caso, en vez de sonar como si algo faltara.
        return [valor if valor else cls.CELDA_VACIA for valor in valores]

    @staticmethod
    def _documentos_pendientes(estado, documentos_completos_fecha):
        """Mismo criterio que FILTRO_ALERTA_DOCUMENTOS_PENDIENTES en
        db/casos.py: un caso ya cerrado (Desembolsada/No aplica/Cliente
        desistió) no cuenta como pendiente aunque documentos_completos_fecha
        siga NULL. Usado tanto para el resaltado en rojo de la fila como para
        el sonido de navegación (ver _refrescar_lista y _on_seleccionar_caso)."""
        return documentos_completos_fecha is None and estado not in ESTADOS_CERRADOS

    def _on_seleccionar_caso(self, event):
        indice = event.GetIndex()
        fila = self._filas[indice]
        (
            caso_id, _fecha_registro, no_presolicitud, _ejecutivo, _empresa_convenio,
            nombre, cedula, _telefono, _monto_solicitado, _destino_credito, _microseguro,
            estado, etapa, _responsable_actual, _decision, _motivo_no_aplica, _observaciones,
            cliente_id, documentos_completos_fecha, _constancia_recibida_fecha,
        ) = fila

        self._caso_seleccionado_id = caso_id
        self._caso_seleccionado_no_presolicitud = no_presolicitud
        self._cliente_seleccionado_id = cliente_id
        self._cliente_seleccionado_nombre = nombre
        self._cliente_seleccionado_cedula = cedula
        self.caso_seleccionado_texto.SetLabel(
            f"Editando: {nombre} — Cédula {cedula} — No. Presolicitud {no_presolicitud or '(sin número)'}"
        )
        self._seleccionar_en_choice(self.estado_choice, estado)
        self._seleccionar_en_choice(self.etapa_choice, etapa)
        self.guardar_btn.Enable()
        self.eliminar_btn.Enable()

        # Un caso ya Desembolsada está cerrado: no tiene sentido seguir
        # pidiendo/permitiendo marcar documentos para él (confirmado por el
        # usuario). Se oculta el control entero, no solo se deshabilita, para
        # no dejar un checkbox "muerto" en pantalla en un caso ya cerrado.
        caso_cerrado = estado == ESTADO_DESEMBOLSADA
        self.documentos_completos_check.Show(not caso_cerrado)
        if not caso_cerrado:
            ya_completos = documentos_completos_fecha is not None
            self.documentos_completos_check.SetValue(ya_completos)
            self.documentos_completos_check.Enable(not ya_completos)
        self.Layout()

        self.mensaje_texto.SetLabel("")

        # Equivalente auditivo, para el usuario ciego, del resaltado en rojo
        # que ve un vidente en esta misma fila (ver _refrescar_lista): suena
        # cada vez que la selección llega a un caso con documentos pendientes,
        # sea por flechas, Tab o clic — EVT_LIST_ITEM_SELECTED cubre los tres.
        if self._documentos_pendientes(estado, documentos_completos_fecha):
            reproducir_sonido(SONIDO_FILA_DOCUMENTOS_PENDIENTES)

    def _on_documentos_completos_check(self, event):
        if not event.IsChecked() or self._cliente_seleccionado_id is None:
            return

        conn = get_connection()
        try:
            marcar_documentos_completos(conn, self._cliente_seleccionado_id)
        finally:
            conn.close()

        # Refresca la lista de inmediato (bug real en producción: sin este
        # refresco, un Tab+Espacio accidental sobre este checkbox quedaba
        # grabado en la base de datos sin ninguna señal visible, y el caso
        # seguía apareciendo en el filtro "Documentos pendientes" como si nada
        # — varios clientes terminaron marcados por accidente sin que el
        # usuario lo notara hasta mucho después). _cargar_casos() ya limpia y
        # deshabilita este checkbox como parte de resetear el panel de edición
        # tras la recarga, igual que "Guardar cambios"/"Eliminar caso".
        self.mensaje_texto.SetLabel("Documentos completados marcados. Se apagó la alerta para este cliente.")
        self._cargar_casos()

    @staticmethod
    def _seleccionar_en_choice(choice_ctrl, valor):
        indice = choice_ctrl.FindString(valor or "")
        choice_ctrl.SetSelection(indice)

    def _on_guardar(self, event):
        if self._caso_seleccionado_id is None:
            return

        estado = self.estado_choice.GetStringSelection()
        etapa = self.etapa_choice.GetStringSelection()

        if not estado or not etapa:
            self.mensaje_texto.SetLabel("Seleccioná un Estado Solicitud y una Etapa Proceso.")
            return

        conn = get_connection()
        try:
            actualizar_edicion_manual(conn, self._caso_seleccionado_id, estado, etapa)
        finally:
            conn.close()

        self.mensaje_texto.SetLabel("Cambios guardados.")
        self._cargar_casos()
