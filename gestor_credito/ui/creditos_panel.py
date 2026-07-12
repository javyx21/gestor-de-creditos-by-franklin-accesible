import wx

from gestor_credito.db.database import get_connection
from gestor_credito.db.reporte_creditos import buscar_creditos
from gestor_credito.ui.accesibilidad import activar_con_enter, nombre_accesible
from gestor_credito.ui.fechas import formatear_fecha
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import SONIDO_BORRAR, reproducir_sonido

# Orden de columnas de la lista — similar al diseño de CasosPanel (pedido
# explícito del usuario), y en el mismo orden en que se mapean los campos del
# Excel (ver sección 1 del pedido / gestor_credito/importer/reporte_creditos_importer.py).
# Debe coincidir con el orden del SELECT de buscar_creditos() en
# gestor_credito/db/reporte_creditos.py.
COLUMNAS = [
    "Fecha Desembolso", "Fecha Vencimiento", "No. Crédito", "Monto Desembolsado",
    "Nombre del Cliente", "Identificación", "Empresa Convenio", "Estado del Crédito",
    "Plazo del Crédito", "Número de Cuotas",
]


class CreditosPanel(wx.Panel):
    """Pestaña "Historial de Créditos" — módulo nuevo e independiente (ver
    CLAUDE.md) que consulta reporte_credito, poblada por
    gestor_credito/importer/reporte_creditos_importer.py (importado desde
    Configuración > Configuración de Reporte de Créditos, no desde acá — mismo
    criterio ya usado para la bitácora de MIDESA/Casos: importar es una acción
    de configuración puntual, consultar es el uso diario).

    Puramente de consulta (sin edición): el pedido del usuario es buscar un
    cliente y ver el estatus de su crédito / su historial, no modificar datos
    del reporte desde acá."""

    CELDA_VACIA = "Celda vacía"

    def __init__(self, parent):
        super().__init__(parent)

        self._filas = []

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Historial de Créditos")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_busqueda(), 0, wx.EXPAND | wx.ALL, 8)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        nombre_accesible(self.lista, "Lista de créditos")
        for indice, columna in enumerate(COLUMNAS):
            self.lista.InsertColumn(indice, columna)
            # Una sola vez acá, no en cada refresco — mismo motivo/mismo
            # ahorro medido que CasosPanel (ver ese comentario): USEHEADER
            # solo depende del ancho del encabezado, nunca cambia.
            self.lista.SetColumnWidth(indice, wx.LIST_AUTOSIZE_USEHEADER)
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_seleccionar_credito)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        self.credito_seleccionado_texto = wx.StaticText(self, label="Ningún crédito seleccionado")
        sizer.Add(self.credito_seleccionado_texto, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self._cargar_creditos(avisar_sin_resultados=False)

    def _crear_busqueda(self):
        box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Buscar")
        contenedor = box.GetStaticBox()

        label = wx.StaticText(contenedor, label="Cédula o nombre del cliente:")
        self.busqueda_texto = wx.TextCtrl(contenedor, style=wx.TE_PROCESS_ENTER)
        nombre_accesible(self.busqueda_texto, "Buscar por cédula o nombre")
        self.busqueda_texto.Bind(wx.EVT_TEXT_ENTER, lambda event: self._buscar())

        buscar_btn = wx.Button(contenedor, label="&Buscar")
        buscar_btn.Bind(wx.EVT_BUTTON, lambda event: self._buscar())
        activar_con_enter(buscar_btn)

        # "&Vaciar búsqueda", no "Limpiar búsqueda": Alt+L es un atajo
        # GLOBAL cuyo efecto depende de la pestaña activa (pedido explícito
        # del usuario, 2026-07-12; ver MainFrame._limpiar_segun_pestana_activa)
        # y ese atajo global intercepta Alt+L antes de que llegara al
        # mnemónico local de este botón — mismo tipo de choque ya evitado
        # antes al elegir Alt+A en vez de Alt+L para el botón Calcular de la
        # Calculadora (ver calculadora_panel.py). El atajo global también
        # llama a limpiar_busqueda() (ver más abajo) cuando esta pestaña
        # está activa, así que Alt+L y Alt+V terminan haciendo lo mismo acá.
        limpiar_btn = wx.Button(contenedor, label="&Vaciar búsqueda")
        limpiar_btn.Bind(wx.EVT_BUTTON, lambda event: self.limpiar_busqueda())
        activar_con_enter(limpiar_btn)

        for control in (label, self.busqueda_texto, buscar_btn, limpiar_btn):
            box.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        return box

    def _buscar(self):
        """Búsqueda explícita (botón "Buscar" o Enter en el cuadro de texto):
        manda el foco a la lista de resultados si hay alguno, mismo criterio
        ya usado en CasosPanel._buscar()."""
        self._cargar_creditos()
        if self._filas:
            estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
            self.lista.SetItemState(0, estado, estado)
            self.lista.SetFocus()

    def limpiar_busqueda(self):
        """Vacía la búsqueda y vuelve a la vista por defecto (créditos en
        estado Corriente). Público (no "_on_...") porque también lo dispara
        el atajo GLOBAL Alt+L cuando esta pestaña está activa (pedido
        explícito del usuario, 2026-07-12 — ver
        MainFrame._limpiar_segun_pestana_activa). Reproduce el sonido de
        confirmación (borrar.wav) — pedido explícito del usuario: "la acción
        de borrar siempre tiene que hacer llamado al sonido", mismo criterio
        que ya usan limpiar_busqueda()/eliminar_caso()/eliminar_cliente() en
        CasosPanel."""
        self.busqueda_texto.SetValue("")
        self._cargar_creditos(avisar_sin_resultados=False)
        reproducir_sonido(SONIDO_BORRAR)

    def enfocar_busqueda(self):
        """Atajo GLOBAL Ctrl+F cuando esta pestaña está activa (pedido
        explícito del usuario, 2026-07-12: "si el usuario se encuentra en
        el apartado del Historial de Créditos, el atajo debe mover el foco
        del cursor directamente al cuadro de edición de búsqueda") — ver
        MainFrame._enfocar_busqueda_segun_pestana_activa. Antes Ctrl+F
        apuntaba siempre a CasosPanel.enfocar_busqueda() sin importar la
        pestaña activa, así que no tenía ningún efecto visible acá."""
        self.busqueda_texto.SetFocus()
        self.busqueda_texto.SelectAll()

    def enfocar_resultados(self):
        """Atajo GLOBAL Ctrl+R cuando esta pestaña está activa (pedido
        explícito del usuario, 2026-07-12: "el comando Ctrl+R que lleva a la
        lista igual tiene que funcionar con el apartado del historial de
        créditos") — ver MainFrame._enfocar_resultados_segun_pestana_activa.
        Idéntico a CasosPanel.enfocar_resultados(): si no hay ningún ítem
        seleccionado todavía, selecciona el primero para que las flechas
        funcionen de inmediato al llegar con el atajo."""
        if self.lista.GetItemCount() == 0:
            self.lista.SetFocus()
            return

        if self.lista.GetFirstSelected() == -1:
            estado = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
            self.lista.SetItemState(0, estado, estado)

        self.lista.SetFocus()

    def recargar(self):
        """Se llama al entrar a esta pestaña (ver MainFrame._on_cambiar_pestana)
        y al cerrar cualquier diálogo modal (ver MainFrame._abrir_dialogo), para
        que una reimportación hecha desde Configuración se refleje sin que el
        usuario tenga que volver a buscar a mano."""
        self._cargar_creditos(avisar_sin_resultados=False)

    def _cargar_creditos(self, avisar_sin_resultados=True):
        termino = self.busqueda_texto.GetValue().strip() or None

        conn = get_connection()
        try:
            try:
                self._filas = buscar_creditos(conn, termino=termino)
            except ValueError as exc:
                self._filas = []
                self._refrescar_lista()
                self.GetTopLevelParent().SetStatusText(str(exc))
                wx.MessageBox(str(exc), "Búsqueda inválida", wx.OK | wx.ICON_ERROR, self)
                return
        finally:
            conn.close()

        self._refrescar_lista()

        cantidad = len(self._filas)
        if cantidad:
            mensaje = f"{cantidad} crédito(s) encontrados"
        else:
            mensaje = "No se encontraron resultados." if termino else "0 crédito(s) encontrados"
            if avisar_sin_resultados:
                wx.MessageBox(mensaje, "Sin resultados", wx.OK | wx.ICON_INFORMATION, self)

        self.GetTopLevelParent().SetStatusText(mensaje)

    def _refrescar_lista(self):
        # Freeze/Thaw: mismo motivo que CasosPanel._refrescar_lista() — evita
        # redibujar la lista en cada InsertItem/SetItem individual, notable
        # con el volumen real de este reporte (~4800 filas).
        self.lista.Freeze()
        try:
            self.lista.DeleteAllItems()
            for fila in self._filas:
                valores = self._fila_a_columnas(fila)
                indice = self.lista.InsertItem(self.lista.GetItemCount(), valores[0])
                for columna, valor in enumerate(valores[1:], start=1):
                    self.lista.SetItem(indice, columna, valor)
            # El ancho de columnas ya se fija una sola vez en __init__.
        finally:
            self.lista.Thaw()

        self.credito_seleccionado_texto.SetLabel("Ningún crédito seleccionado")

    @classmethod
    def _fila_a_columnas(cls, fila):
        (
            _id, no_credito, cedula, nombre_cliente, fecha_desembolso, fecha_vencimiento,
            monto_desembolsado, estado_credito, empresa_convenio, plazo_credito, cuotas_pagadas,
        ) = fila

        monto_texto = f"{monto_desembolsado:.2f}" if monto_desembolsado is not None else ""
        plazo_texto = str(plazo_credito) if plazo_credito is not None else ""
        cuotas_texto = str(cuotas_pagadas) if cuotas_pagadas is not None else ""

        valores = [
            formatear_fecha(fecha_desembolso), formatear_fecha(fecha_vencimiento), no_credito or "",
            monto_texto, nombre_cliente or "", cedula or "", empresa_convenio or "",
            estado_credito or "", plazo_texto, cuotas_texto,
        ]
        # Celda vacía en vez de texto en blanco: mismo motivo que
        # CasosPanel._fila_a_columnas — NVDA lee una celda realmente vacía
        # repitiendo solo el nombre de columna, sin ningún valor después.
        return [valor if valor else cls.CELDA_VACIA for valor in valores]

    def _on_seleccionar_credito(self, event):
        indice = event.GetIndex()
        fila = self._filas[indice]
        (
            _id, no_credito, cedula, nombre_cliente, _fecha_desembolso, _fecha_vencimiento,
            _monto_desembolsado, estado_credito, _empresa_convenio, _plazo_credito, _cuotas_pagadas,
        ) = fila
        self.credito_seleccionado_texto.SetLabel(
            f"{nombre_cliente} — Cédula {cedula} — Crédito No. {no_credito} — "
            f"Estado: {estado_credito or CreditosPanel.CELDA_VACIA}"
        )
