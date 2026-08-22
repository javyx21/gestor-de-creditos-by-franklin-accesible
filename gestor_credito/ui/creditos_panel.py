import wx

from gestor_credito.calculo.avance_credito import calcular_avance_pago
from gestor_credito.db.database import get_connection
from gestor_credito.db.reporte_creditos import (
    ESTADO_CREDITO_ACTIVO,
    ESTADO_CREDITO_CANCELADO,
    ESTADO_ELEGIBLES_REFINANCIAMIENTO,
    ESTADOS_CREDITO_ALERTA,
    ESTADO_TODOS,
    buscar_creditos,
    obtener_empresas_convenio,
)
from gestor_credito.ui.accesibilidad import (
    activar_con_enter,
    anunciar_voz_nvda,
    ejecutar_en_segundo_plano,
    nombre_accesible,
)
from gestor_credito.ui.fechas import formatear_fecha
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import (
    SONIDO_BORRAR,
    SONIDO_FILA_CASO_ESPECIAL_CUOTAS_COMPLETAS,
    SONIDO_FILA_CREDITO_VENCIDO_SANEADO,
    SONIDO_FILA_REVISAR_MANUALMENTE,
    reproducir_sonido,
)

# Orden de columnas de la lista — similar al diseño de CasosPanel (pedido
# explícito del usuario). Independiente del orden del SELECT de
# buscar_creditos() en gestor_credito/db/reporte_creditos.py —
# _fila_a_columnas() hace el mapeo entre ambos.
#
# "Número de Cuotas"/"Cuotas Pagadas"/"Cuotas Pendientes" agregadas 2026-08-16
# junto con el filtro de cuotas pendientes — antes esta lista solo tenía una
# columna "Número de Cuotas" que en realidad mostraba cuotas_pagadas (no el
# total de cuotas), un error de rótulo que quedó corregido de paso al separar
# ambos valores.
#
# "Saldo a la fecha" agregada 2026-08-21, pedido explícito del usuario: se
# calcula sumando saldo_principal + saldo_intereses (columnas nuevas del
# reporte real, ver database.py/reporte_creditos_importer.py) — esas dos NO
# tienen columna propia acá, el usuario pidió explícitamente que queden
# ocultas ("son relleno... solo se muestra el saldo a la fecha"), mismo
# criterio ya usado para "Cuotas Pendientes" (calculada, no importada tal
# cual). Ubicada junto a "Monto Desembolsado" porque ambas son cifras de
# dinero del crédito.
COLUMNAS = [
    "Fecha Desembolso", "Fecha Vencimiento", "No. Crédito", "Monto Desembolsado",
    "Saldo a la fecha", "Nombre del Cliente", "Identificación", "Empresa Convenio",
    "Estado del Crédito", "Plazo del Crédito", "Número de Cuotas", "Cuotas Pagadas",
    "Cuotas Pendientes",
]

# Opciones del selector "Estado" — reducidas a estas 3 (pedido explícito del
# usuario, 2026-08-22: "es más lógico que solo tengamos tres"). Reemplaza al
# esquema anterior de 4 opciones (Activos/Finalizados/Todos/Elegibles):
# "Activos (Corriente)" y "Finalizados (para reenganche)" se retiraron del
# selector — ESTADO_CREDITO_ACTIVO sigue siendo un valor válido para pasarle
# a buscar_creditos() directamente si hiciera falta, solo dejó de tener su
# propia entrada acá.
#
# "Cancelados" (nueva) reemplaza a "Finalizados (para reenganche)" — a
# propósito NO es la misma condición compuesta de antes: solo
# estado_credito = "Cancelado" literal (ver ESTADO_CREDITO_CANCELADO en
# db/reporte_creditos.py). Un crédito con cuotas completas pero
# estado_credito todavía en "Corriente" NO entra acá — confirmado
# explícitamente por el usuario ("si el sistema dice que está activo, eso
# está prohibido" tratarlo como cancelado) — ese caso vive aparte, ver
# _es_caso_especial_activo_con_cuotas_completas más abajo.
#
# "Elegibles para refinanciar" (2026-08-21): créditos que pasan el cruce de
# avance de pago (ver gestor_credito/calculo/avance_credito.py).
ESTADO_OPCIONES = [
    ("Todos los estados", ESTADO_TODOS),
    ("Elegibles para refinanciar", ESTADO_ELEGIBLES_REFINANCIAMIENTO),
    ("Cancelados", ESTADO_CREDITO_CANCELADO),
]

# Selección por defecto de estado_choice — pedido explícito del usuario
# (2026-08-21): "cuando borremos filtro queden... en general... todos", así
# que al entrar a la pestaña o al limpiar (Ctrl+D) el filtro de Estado
# arranca en "Todos los estados". Constante para no repetir el número mágico
# en los dos lugares que la usan (__init__ vía _crear_filtros, y
# limpiar_busqueda()).
_INDICE_ESTADO_POR_DEFECTO = 0  # "Todos los estados"

# Texto de la opción "sin filtro" del selector "Empresa" — nunca es un nombre
# real de empresa, así que _empresa_seleccionada() lo distingue por índice 0.
_EMPRESA_TODAS = "Todas las empresas"


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

    # Alerta visual para créditos Vencido/Saneado (pedido explícito del
    # usuario, 2026-08-21) — mismos colores exactos que ya usa Casos para
    # "Documentos pendientes" (casos_panel.py), ya verificados con buen
    # contraste (~7.5:1); no se inventan colores nuevos acá.
    _COLOR_FONDO_CREDITO_ALERTA = wx.Colour(255, 214, 214)
    _COLOR_TEXTO_CREDITO_ALERTA = wx.Colour(139, 0, 0)

    # Color distinto para el "caso especial" (Corriente con cuotas ya
    # completas) — pedido explícito del usuario, 2026-08-22: "le tienes que
    # poner un color en amarillo para que el vidente también lo pueda
    # identificar". Amarillo claro + texto negro: contraste ~19:1 (muy por
    # encima del mínimo WCAG), se distingue a simple vista del rojo de la
    # otra alerta sin confundirse con ella.
    _COLOR_FONDO_CASO_ESPECIAL = wx.Colour(255, 241, 118)
    _COLOR_TEXTO_CASO_ESPECIAL = wx.Colour(0, 0, 0)

    def __init__(self, parent):
        super().__init__(parent)

        self._filas = []
        self._empresas = []
        # Contadores de "versión" para descartar resultados de una consulta
        # en segundo plano que ya quedó obsoleta (2026-08-16, ver
        # _cargar_creditos/_cargar_empresas): con la carga asíncrona, una
        # segunda consulta disparada mientras la primera todavía está en
        # curso (p. ej. dos flechas rápidas en el selector "Estado") podría
        # devolver su resultado DESPUÉS de la más nueva y pisarla con datos
        # viejos si no se descarta explícitamente.
        self._version_creditos = 0
        self._version_empresas = 0

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Historial de Créditos")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_busqueda(), 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self._crear_filtros(), 0, wx.EXPAND | wx.ALL, 8)

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

        # Enter en estado_choice/empresa_choice: mismo problema/mismo arreglo
        # que filtro_alerta_choice en casos_panel.py y agentes_choice en
        # configuracion_panel.py — el wx.Choice nativo se queda con la tecla
        # Enter antes de que un EVT_KEY_DOWN normal la vea, así que hace
        # falta interceptarla acá arriba con EVT_CHAR_HOOK. Solo al confirmar
        # con Enter se anuncia en voz la cantidad resultante (ver
        # anunciar_voz_nvda) — arrastrar con las flechas sigue silencioso del
        # lado de la app, NVDA ya anuncia el texto de cada opción solo.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self._cargar_empresas()
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

        # "Vaciar búsqueda" SIN mnemónico: tenía Alt+V hasta 2026-08-16,
        # cuando el usuario pidió unificar todo comando de limpiar en un
        # solo atajo GLOBAL congruente, Ctrl+D (ver MainFrame.
        # _limpiar_segun_pestana_activa, que llama a limpiar_busqueda() —
        # más abajo — cuando esta pestaña está activa). El botón sigue
        # existiendo y accionable con mouse/Tab+Enter, solo perdió su
        # mnemónico de teclado propio.
        limpiar_btn = wx.Button(contenedor, label="Vaciar búsqueda")
        limpiar_btn.Bind(wx.EVT_BUTTON, lambda event: self.limpiar_busqueda())
        activar_con_enter(limpiar_btn)

        for control in (label, self.busqueda_texto, buscar_btn, limpiar_btn):
            box.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        return box

    def _crear_filtros(self):
        """Estado/Empresa — pedido explícito del usuario (2026-08-16), ambos
        combinables entre sí y con la búsqueda por cédula/nombre (AND). Ver
        buscar_creditos() en db/reporte_creditos.py para el detalle de cada
        filtro.

        El campo "Cuotas pendientes (máximo)" que vivía acá se eliminó
        (pedido explícito del usuario, 2026-08-22: "ya no vale la pena
        tenerla") — el filtro de % de avance de pago ("Elegibles para
        refinanciar") lo reemplaza por completo."""
        box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Filtros")
        contenedor = box.GetStaticBox()

        estado_label = wx.StaticText(contenedor, label="Estado:")
        self.estado_choice = wx.Choice(
            contenedor, choices=[texto for texto, _valor in ESTADO_OPCIONES]
        )
        nombre_accesible(self.estado_choice, "Estado")
        self.estado_choice.SetSelection(_INDICE_ESTADO_POR_DEFECTO)
        self.estado_choice.Bind(
            wx.EVT_CHOICE, lambda event: self._cargar_creditos(avisar_sin_resultados=False)
        )

        empresa_label = wx.StaticText(contenedor, label="Empresa:")
        self.empresa_choice = wx.Choice(contenedor, choices=[_EMPRESA_TODAS])
        nombre_accesible(self.empresa_choice, "Empresa")
        self.empresa_choice.SetSelection(0)
        self.empresa_choice.Bind(
            wx.EVT_CHOICE, lambda event: self._cargar_creditos(avisar_sin_resultados=False)
        )

        for control in (estado_label, self.estado_choice, empresa_label, self.empresa_choice):
            box.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        return box

    def _on_char_hook(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            foco = wx.Window.FindFocus()
            if foco in (self.estado_choice, self.empresa_choice):
                self._cargar_creditos(avisar_sin_resultados=False, anunciar_voz=True)
                return
        event.Skip()

    def _cargar_empresas(self):
        """Lista de empresas realmente presentes en reporte_credito, no el
        catálogo global de convenio_tasa (pedido explícito del usuario,
        2026-08-16: "evitando listar todas las empresas globalmente"). Se
        recarga también desde recargar() por si una reimportación trajo una
        empresa nueva.

        Corre en segundo plano (ver ejecutar_en_segundo_plano en
        accesibilidad.py) — reporte real del usuario, 2026-08-16 segunda
        ronda: con la consulta corriendo en el hilo principal, abrir esta
        pestaña o navegar el selector "Estado"/"Empresa" se sentía como que
        "la lectura o salida por voz se congela", porque mientras la
        consulta a SQLite corre, Windows no bombea el bucle de mensajes de
        la ventana y NVDA queda sin poder hablar hasta que termina."""
        self._version_empresas += 1
        version = self._version_empresas
        seleccion_previa = self._empresa_seleccionada()

        def _trabajo():
            conn = get_connection()
            try:
                return obtener_empresas_convenio(conn)
            finally:
                conn.close()

        def _al_terminar(empresas):
            if not self or version != self._version_empresas:
                return  # pestaña ya cerrada, o esta carga quedó obsoleta
            self._empresas = empresas
            self.empresa_choice.Set([_EMPRESA_TODAS, *self._empresas])
            if seleccion_previa and seleccion_previa in self._empresas:
                self.empresa_choice.SetSelection(self._empresas.index(seleccion_previa) + 1)
            else:
                self.empresa_choice.SetSelection(0)

        ejecutar_en_segundo_plano(_trabajo, _al_terminar)

    def _empresa_seleccionada(self):
        indice = self.empresa_choice.GetSelection()
        if indice <= 0 or indice == wx.NOT_FOUND:
            return None
        return self._empresas[indice - 1]

    def _buscar(self):
        """Búsqueda explícita (botón "Buscar" o Enter en cédula/nombre):
        manda el foco a la lista de resultados si hay alguno, mismo criterio
        ya usado en CasosPanel._buscar() — una vez que la consulta en
        segundo plano efectivamente trae resultados (ver _cargar_creditos)."""
        self._cargar_creditos(mover_foco_a_resultados=True)

    def limpiar_busqueda(self):
        """Vacía la búsqueda Y los filtros, y vuelve a la vista por defecto
        — "Todos los estados" (ver _INDICE_ESTADO_POR_DEFECTO; pedido
        explícito del usuario, 2026-08-21: "cuando borremos filtro queden...
        en general... todos", para que buscar un cliente sin crédito activo
        no dependa de cambiar el filtro a mano primero), todas las empresas.
        Público (no "_on_...") porque también lo dispara el atajo GLOBAL
        Ctrl+D (antes Alt+L) cuando esta pestaña está activa (pedido
        explícito del usuario — ver MainFrame._limpiar_segun_pestana_activa).
        Reproduce el sonido de confirmación (borrar.wav) — pedido explícito
        del usuario: "la acción de borrar siempre tiene que hacer llamado al
        sonido", mismo criterio que ya usan limpiar_busqueda()/
        eliminar_caso()/eliminar_cliente() en CasosPanel."""
        self.busqueda_texto.SetValue("")
        self.estado_choice.SetSelection(_INDICE_ESTADO_POR_DEFECTO)
        self.empresa_choice.SetSelection(0)
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
        usuario tenga que volver a buscar a mano — incluida una empresa nueva
        en el selector "Empresa"."""
        self._cargar_empresas()
        self._cargar_creditos(avisar_sin_resultados=False)

    def _cargar_creditos(self, avisar_sin_resultados=True, anunciar_voz=False,
                          mover_foco_a_resultados=False):
        """Dispara la consulta de créditos en segundo plano (ver
        ejecutar_en_segundo_plano en accesibilidad.py) para no bloquear el
        hilo principal de la interfaz ni la respuesta de NVDA mientras
        corre — ver el comentario largo en _cargar_empresas() para el
        reporte real que motivó esto."""
        termino = self.busqueda_texto.GetValue().strip() or None
        _texto_estado, estado = ESTADO_OPCIONES[self.estado_choice.GetSelection()]
        empresa = self._empresa_seleccionada()

        self._version_creditos += 1
        version = self._version_creditos
        # Feedback inmediato y síncrono: sin esto, la barra de estado queda
        # en silencio durante toda la consulta en segundo plano, que es
        # justo la sensación de "se congeló" que reportó el usuario incluso
        # sin bloquear nada de verdad.
        self.GetTopLevelParent().SetStatusText("Buscando…")

        def _trabajo():
            conn = get_connection()
            try:
                try:
                    return (True, buscar_creditos(
                        conn, termino=termino, estado=estado, empresa=empresa,
                    ))
                except ValueError as exc:
                    return (False, str(exc))
            finally:
                conn.close()

        def _al_terminar(resultado):
            if not self or version != self._version_creditos:
                return  # pestaña ya cerrada, o esta búsqueda quedó obsoleta
            ok, valor = resultado
            if not ok:
                self._filas = []
                self._refrescar_lista()
                self.GetTopLevelParent().SetStatusText(valor)
                wx.MessageBox(valor, "Búsqueda inválida", wx.OK | wx.ICON_ERROR, self)
                return

            self._filas = valor
            self._refrescar_lista()

            cantidad = len(self._filas)
            if cantidad:
                mensaje = f"{cantidad} crédito(s) encontrados"
            else:
                mensaje = "No se encontraron resultados." if termino else "0 crédito(s) encontrados"
                if avisar_sin_resultados:
                    wx.MessageBox(mensaje, "Sin resultados", wx.OK | wx.ICON_INFORMATION, self)

            self.GetTopLevelParent().SetStatusText(mensaje)
            if anunciar_voz:
                anunciar_voz_nvda(mensaje)

            if mover_foco_a_resultados and self._filas:
                estado_item = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
                self.lista.SetItemState(0, estado_item, estado_item)
                self.lista.SetFocus()

        ejecutar_en_segundo_plano(_trabajo, _al_terminar)

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

                (
                    _id, _no_credito, _cedula, _nombre_cliente, _fecha_desembolso, _fecha_vencimiento,
                    monto_desembolsado, estado_credito, _empresa_convenio, plazo_credito, numero_cuotas,
                    cuotas_pagadas, _estado_credito_fecha_cambio, saldo_principal, saldo_intereses,
                    dias_en_mora, _es_convenio, _fecha_ultimo_pago_principal,
                ) = fila

                # Tres condiciones mutuamente excluyentes, en orden de
                # prioridad (ver _on_seleccionar_credito para el mismo
                # orden aplicado al sonido): la alerta de estado/mora real
                # es la más urgente; el "caso especial" (Corriente con
                # cuotas ya completas, pedido explícito del usuario,
                # 2026-08-22) es más específico que "revisar manualmente" y
                # se revisa antes — con cuotas completas, el % por dinero y
                # por cuotas casi siempre van a diferir, así que sin este
                # orden ese caso caería en el cajón genérico de "revisar
                # manualmente" en vez de su propio aviso.
                if self._es_credito_en_alerta(estado_credito, dias_en_mora):
                    self.lista.SetItemBackgroundColour(indice, self._COLOR_FONDO_CREDITO_ALERTA)
                    self.lista.SetItemTextColour(indice, self._COLOR_TEXTO_CREDITO_ALERTA)
                elif self._es_caso_especial_activo_con_cuotas_completas(
                    estado_credito, numero_cuotas, cuotas_pagadas,
                ):
                    self.lista.SetItemBackgroundColour(indice, self._COLOR_FONDO_CASO_ESPECIAL)
                    self.lista.SetItemTextColour(indice, self._COLOR_TEXTO_CASO_ESPECIAL)
                elif self._requiere_revision_manual(
                    saldo_principal, saldo_intereses, monto_desembolsado,
                    cuotas_pagadas, numero_cuotas, plazo_credito,
                ):
                    self.lista.SetItemBackgroundColour(indice, self._COLOR_FONDO_CREDITO_ALERTA)
                    self.lista.SetItemTextColour(indice, self._COLOR_TEXTO_CREDITO_ALERTA)
            # El ancho de columnas ya se fija una sola vez en __init__.
        finally:
            self.lista.Thaw()

        self.credito_seleccionado_texto.SetLabel("Ningún crédito seleccionado")

    @classmethod
    def _fila_a_columnas(cls, fila):
        (
            _id, no_credito, cedula, nombre_cliente, fecha_desembolso, fecha_vencimiento,
            monto_desembolsado, estado_credito, empresa_convenio, plazo_credito, numero_cuotas,
            cuotas_pagadas, _estado_credito_fecha_cambio, saldo_principal, saldo_intereses,
            _dias_en_mora, _es_convenio, _fecha_ultimo_pago_principal,
        ) = fila

        monto_texto = f"{monto_desembolsado:.2f}" if monto_desembolsado is not None else ""
        plazo_texto = str(plazo_credito) if plazo_credito is not None else ""
        numero_cuotas_texto = str(numero_cuotas) if numero_cuotas is not None else ""
        cuotas_pagadas_texto = str(cuotas_pagadas) if cuotas_pagadas is not None else ""
        cuotas_pendientes_texto = cls._formatear_cuotas_pendientes(numero_cuotas, cuotas_pagadas)
        saldo_a_la_fecha_texto = cls._formatear_saldo_a_la_fecha(saldo_principal, saldo_intereses)

        valores = [
            formatear_fecha(fecha_desembolso), formatear_fecha(fecha_vencimiento), no_credito or "",
            monto_texto, saldo_a_la_fecha_texto, nombre_cliente or "", cedula or "",
            empresa_convenio or "", estado_credito or "", plazo_texto, numero_cuotas_texto,
            cuotas_pagadas_texto, cuotas_pendientes_texto,
        ]
        # Celda vacía en vez de texto en blanco: mismo motivo que
        # CasosPanel._fila_a_columnas — NVDA lee una celda realmente vacía
        # repitiendo solo el nombre de columna, sin ningún valor después.
        return [valor if valor else cls.CELDA_VACIA for valor in valores]

    @staticmethod
    def _es_credito_en_alerta(estado_credito, dias_en_mora):
        """Vencido/Saneado/Prorrogado, O en mora real (dias_en_mora > 0)
        aunque estado_credito todavía diga Corriente — pedido explícito del
        usuario (2026-08-21), confirmado con datos reales: 98 de 1,777
        créditos "Corriente" ya tenían dias_en_mora > 0 (el sistema de
        origen no había actualizado el estado todavía — mismo tipo de
        desfase que motiva también _es_caso_especial_activo_con_cuotas_
        completas más abajo). Mismo equivalente visual/auditivo que ya
        tiene Casos para "Documentos pendientes" (ver casos_panel.py). Usado
        tanto para el resaltado en rojo de la fila (_refrescar_lista) como
        para el sonido de navegación (_on_seleccionar_credito)."""
        return estado_credito in ESTADOS_CREDITO_ALERTA or (
            dias_en_mora is not None and dias_en_mora > 0
        )

    @staticmethod
    def _es_caso_especial_activo_con_cuotas_completas(estado_credito, numero_cuotas, cuotas_pagadas):
        """Corriente (activo) pero cuotas_pagadas ya alcanzó o superó
        numero_cuotas — pedido explícito del usuario (2026-08-22). A
        propósito NO se trata como Cancelado en ningún filtro ("si el
        sistema dice que está activo, eso está prohibido" tratarlo distinto)
        — sigue contando como Corriente para todo lo demás, incluida
        "Elegibles para refinanciar" si corresponde, pero se marca aparte
        (amarillo + sonido propio) para que el oficial decida con criterio
        antes de ofrecer algo, en vez de tratarlo como un caso limpio más."""
        if estado_credito != ESTADO_CREDITO_ACTIVO:
            return False
        if numero_cuotas is None or cuotas_pagadas is None:
            return False
        return cuotas_pagadas >= numero_cuotas

    @staticmethod
    def _requiere_revision_manual(saldo_principal, saldo_intereses, monto_desembolsado,
                                   cuotas_pagadas, numero_cuotas, plazo_credito):
        """True si el % de avance de pago no es confiable (el cálculo por
        dinero y por cuotas no coinciden, o el chequeo estructural de plazo
        vs. número de cuotas falla — ver
        gestor_credito/calculo/avance_credito.py) — pedido explícito del
        usuario (2026-08-21): en vez de adivinar cuál número creerle, se
        marca para que alguien lo revise a mano. Un crédito sin datos
        suficientes para calcular nada ("sin_datos") NO cuenta como esto —
        eso es simplemente falta de dato, no una inconsistencia real."""
        _avance, estado_avance = calcular_avance_pago(
            saldo_principal, saldo_intereses, monto_desembolsado,
            cuotas_pagadas, numero_cuotas, plazo_credito,
        )
        return estado_avance == "inconsistente"

    @staticmethod
    def _formatear_cuotas_pendientes(numero_cuotas, cuotas_pagadas):
        if numero_cuotas is None or cuotas_pagadas is None:
            return ""
        return str(max(numero_cuotas - cuotas_pagadas, 0))

    @staticmethod
    def _formatear_saldo_a_la_fecha(saldo_principal, saldo_intereses):
        """Saldo a la fecha = saldo_principal + saldo_intereses — pedido
        explícito del usuario (2026-08-21): "el saldo a la fecha es la suma
        de saldo principal más el saldo de intereses". Sin ambos valores no
        hay suma confiable que mostrar (mismo criterio que
        _formatear_cuotas_pendientes): mejor celda vacía que un total parcial
        que parezca completo sin serlo."""
        if saldo_principal is None or saldo_intereses is None:
            return ""
        return f"{saldo_principal + saldo_intereses:.2f}"

    def _on_seleccionar_credito(self, event):
        indice = event.GetIndex()
        fila = self._filas[indice]
        (
            _id, no_credito, cedula, nombre_cliente, _fecha_desembolso, _fecha_vencimiento,
            monto_desembolsado, estado_credito, _empresa_convenio, plazo_credito, numero_cuotas,
            cuotas_pagadas, _estado_credito_fecha_cambio, saldo_principal, saldo_intereses,
            dias_en_mora, _es_convenio, _fecha_ultimo_pago_principal,
        ) = fila
        pendientes_texto = self._formatear_cuotas_pendientes(numero_cuotas, cuotas_pagadas) or (
            CreditosPanel.CELDA_VACIA
        )
        self.credito_seleccionado_texto.SetLabel(
            f"{nombre_cliente} — Cédula {cedula} — Crédito No. {no_credito} — "
            f"Estado: {estado_credito or CreditosPanel.CELDA_VACIA} — "
            f"Cuotas pendientes: {pendientes_texto}"
        )

        # Equivalente auditivo, para el usuario ciego, del resaltado en rojo/
        # amarillo que ve un vidente en esta misma fila (ver
        # _refrescar_lista): suena cada vez que la selección llega a una
        # fila marcada, sea por flechas, Tab o clic — EVT_LIST_ITEM_SELECTED
        # cubre los tres. Mismo patrón que CasosPanel._on_seleccionar_caso.
        # Mismo orden de prioridad que _refrescar_lista — ver ese comentario.
        if self._es_credito_en_alerta(estado_credito, dias_en_mora):
            reproducir_sonido(SONIDO_FILA_CREDITO_VENCIDO_SANEADO)
        elif self._es_caso_especial_activo_con_cuotas_completas(
            estado_credito, numero_cuotas, cuotas_pagadas,
        ):
            reproducir_sonido(SONIDO_FILA_CASO_ESPECIAL_CUOTAS_COMPLETAS)
        elif self._requiere_revision_manual(
            saldo_principal, saldo_intereses, monto_desembolsado,
            cuotas_pagadas, numero_cuotas, plazo_credito,
        ):
            reproducir_sonido(SONIDO_FILA_REVISAR_MANUALMENTE)
