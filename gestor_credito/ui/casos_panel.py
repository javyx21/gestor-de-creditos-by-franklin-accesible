import wx

from gestor_credito.catalogos import (
    ESTADO_DESEMBOLSADA,
    ETAPAS_PROCESO,
    ESTADOS_SOLICITUD,
    formatear_microseguro,
)
from gestor_credito.db.alertas import marcar_documentos_completos
from gestor_credito.db.casos import (
    FILTRO_ALERTA_CONSTANCIA_EN_MANO,
    FILTRO_ALERTA_CONSTANCIA_PENDIENTE,
    FILTRO_ALERTA_DOCUMENTOS_PENDIENTES,
    FILTRO_ALERTA_TODOS,
    actualizar_edicion_manual,
    buscar_casos,
)
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, obtener_valor
from gestor_credito.db.database import get_connection
from gestor_credito.ui.accesibilidad import activar_con_enter
from gestor_credito.ui.fechas import formatear_fecha
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import SONIDO_LIMPIAR_BUSQUEDA, reproducir_sonido

# Orden y set de columnas pedido por el usuario para la lista de Casos. Debe
# coincidir en orden con el SELECT interno de buscar_casos() en gestor_credito/db/casos.py.
COLUMNAS = [
    "Fecha Registro", "No. Presolicitud", "Ejecutivo", "Empresa Convenio",
    "Nombre del Cliente", "Identificación", "Teléfono", "Monto Solicitado",
    "Destino del Crédito", "Microseguro", "Estado Solicitud", "Etapa Proceso",
    "Responsable Actual", "Decisión", "Motivo No Aplica / Desistimiento", "Observaciones",
]

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

    def __init__(self, parent):
        super().__init__(parent)

        self._filas = []
        self._caso_seleccionado_id = None
        self._cliente_seleccionado_id = None

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

        for control in (estado_label, self.estado_choice, etapa_label, self.etapa_choice, self.guardar_btn):
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
        reproducir_sonido(SONIDO_LIMPIAR_BUSQUEDA)

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

        for columna in range(len(COLUMNAS)):
            self.lista.SetColumnWidth(columna, wx.LIST_AUTOSIZE_USEHEADER)

        self._caso_seleccionado_id = None
        self._cliente_seleccionado_id = None
        self.guardar_btn.Disable()
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
        self._cliente_seleccionado_id = cliente_id
        self.caso_seleccionado_texto.SetLabel(
            f"Editando: {nombre} — Cédula {cedula} — No. Presolicitud {no_presolicitud or '(sin número)'}"
        )
        self._seleccionar_en_choice(self.estado_choice, estado)
        self._seleccionar_en_choice(self.etapa_choice, etapa)
        self.guardar_btn.Enable()

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

    def _on_documentos_completos_check(self, event):
        if not event.IsChecked() or self._cliente_seleccionado_id is None:
            return

        conn = get_connection()
        try:
            marcar_documentos_completos(conn, self._cliente_seleccionado_id)
        finally:
            conn.close()

        self.documentos_completos_check.Disable()
        self.mensaje_texto.SetLabel("Documentos completados marcados. Se apagó la alerta para este cliente.")

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
