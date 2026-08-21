import wx

from gestor_credito.db.database import get_connection
from gestor_credito.db.reporte_creditos import (
    ESTADO_CREDITO_ACTIVO,
    ESTADO_CREDITO_FINALIZADO,
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
    SONIDO_FILA_CREDITO_VENCIDO_SANEADO,
    reproducir_sonido,
)

# Orden de columnas de la lista — similar al diseño de CasosPanel (pedido
# explícito del usuario), y en el mismo orden en que se mapean los campos del
# Excel (ver sección 1 del pedido / gestor_credito/importer/reporte_creditos_importer.py).
# Debe coincidir con el orden del SELECT de buscar_creditos() en
# gestor_credito/db/reporte_creditos.py.
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

# Opciones del selector "Estado" — pedido explícito del usuario (2026-08-16):
# una vista dedicada a créditos ya finalizados (pagados en su totalidad) para
# campañas de reenganche, además de la vista de activos ya existente. Este
# selector explícito reemplaza el comportamiento anterior, en el que un
# término de búsqueda ignoraba automáticamente el filtro de estado para
# mostrar todo el historial del cliente — ahora hay que elegir "Todos los
# estados" a propósito para eso (ver buscar_creditos() en db/reporte_creditos.py).
#
# No hay una opción de menú separada para "Próximos a finalizar" (pedido
# explícito del usuario, segunda ronda 2026-08-16): ese filtro ES la
# combinación de "Activos" + el campo "Cuotas pendientes (máximo)" de acá
# abajo — no un control aparte — para no sumar otro control más a la
# tabulación (mismo criterio ya aplicado en Calculadora de Crédito: "evitar
# que el flujo de tabulación se vuelva lento o invasivo con demasiados
# campos"). El rótulo del campo lo deja explícito.
ESTADO_OPCIONES = [
    ("Activos (Corriente)", ESTADO_CREDITO_ACTIVO),
    ("Finalizados (para reenganche)", ESTADO_CREDITO_FINALIZADO),
    ("Todos los estados", ESTADO_TODOS),
]

# Texto de la opción "sin filtro" del selector "Empresa" — nunca es un nombre
# real de empresa, así que _empresa_seleccionada() lo distingue por índice 0.
_EMPRESA_TODAS = "Todas las empresas"

# Posición de estado_credito dentro de las tuplas que devuelve
# buscar_creditos() (ver _SELECT_BASE en db/reporte_creditos.py) — usada por
# la alerta visual/sonora de créditos Vencido/Saneado (ver
# _refrescar_lista/_on_seleccionar_credito), mismo criterio que
# _INDICE_ESTADO_SOLICITUD_FILA en casos_panel.py.
_INDICE_ESTADO_CREDITO_FILA = 7


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
        """Estado/Empresa/Cuotas pendientes — pedido explícito del usuario
        (2026-08-16), los tres combinables entre sí y con la búsqueda por
        cédula/nombre (AND). Ver buscar_creditos() en db/reporte_creditos.py
        para el detalle de cada filtro."""
        box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Filtros")
        contenedor = box.GetStaticBox()

        estado_label = wx.StaticText(contenedor, label="Estado:")
        self.estado_choice = wx.Choice(
            contenedor, choices=[texto for texto, _valor in ESTADO_OPCIONES]
        )
        nombre_accesible(self.estado_choice, "Estado")
        self.estado_choice.SetSelection(0)
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

        # Rótulo explícito (ejemplos incluidos) para que este campo sea, por
        # sí solo, descubrible como el filtro "Próximos a finalizar" que
        # pidió el usuario — combinado con Estado="Activos" (el valor por
        # defecto) sin necesidad de un control aparte. "<=", no "=": pedido
        # explícito del usuario, 2026-08-16 segunda ronda ("cuotas pendientes
        # sean menores o iguales a un valor seleccionado, por ejemplo <= 2").
        cuotas_label = wx.StaticText(
            contenedor, label="Cuotas pendientes (máximo, ej. 2 o 3 — 'Próximos a finalizar'):"
        )
        self.cuotas_pendientes_texto = wx.TextCtrl(contenedor, style=wx.TE_PROCESS_ENTER)
        nombre_accesible(
            self.cuotas_pendientes_texto,
            "Cuotas pendientes máximo, para ver próximos a finalizar",
        )
        self.cuotas_pendientes_texto.Bind(wx.EVT_TEXT_ENTER, lambda event: self._buscar())

        for control in (estado_label, self.estado_choice, empresa_label, self.empresa_choice,
                         cuotas_label, self.cuotas_pendientes_texto):
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

    def _leer_cuotas_pendientes_maximo(self):
        """Devuelve (valor, es_valido). Vacío es válido (sin filtro); solo un
        entero no negativo es aceptado — mismo criterio de validación que
        clasificar_termino_busqueda() en db/casos.py: rechazar en vez de
        adivinar qué quiso decir el usuario."""
        texto = self.cuotas_pendientes_texto.GetValue().strip()
        if not texto:
            return None, True
        if not texto.isdigit():
            return None, False
        return int(texto), True

    def _buscar(self):
        """Búsqueda explícita (botón "Buscar", Enter en cédula/nombre, o
        Enter en cuotas pendientes): manda el foco a la lista de resultados
        si hay alguno, mismo criterio ya usado en CasosPanel._buscar() — una
        vez que la consulta en segundo plano efectivamente trae resultados
        (ver _cargar_creditos)."""
        self._cargar_creditos(mover_foco_a_resultados=True)

    def limpiar_busqueda(self):
        """Vacía la búsqueda Y los tres filtros, y vuelve a la vista por
        defecto (créditos en estado Corriente, todas las empresas, sin
        filtro de cuotas pendientes). Público (no "_on_...") porque también
        lo dispara el atajo GLOBAL Ctrl+D (antes Alt+L) cuando esta pestaña
        está activa (pedido explícito del usuario — ver
        MainFrame._limpiar_segun_pestana_activa). Reproduce el sonido de
        confirmación (borrar.wav) — pedido explícito del usuario: "la acción
        de borrar siempre tiene que hacer llamado al sonido", mismo criterio
        que ya usan limpiar_busqueda()/eliminar_caso()/eliminar_cliente() en
        CasosPanel."""
        self.busqueda_texto.SetValue("")
        self.estado_choice.SetSelection(0)
        self.empresa_choice.SetSelection(0)
        self.cuotas_pendientes_texto.SetValue("")
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
        reporte real que motivó esto. La validación de "cuotas pendientes"
        SÍ es síncrona (no toca la base de datos, es instantánea) — solo la
        consulta real se manda al hilo en segundo plano."""
        termino = self.busqueda_texto.GetValue().strip() or None
        _texto_estado, estado = ESTADO_OPCIONES[self.estado_choice.GetSelection()]
        empresa = self._empresa_seleccionada()

        cuotas_pendientes_maximo, cuotas_validas = self._leer_cuotas_pendientes_maximo()
        if not cuotas_validas:
            mensaje = "Cuotas pendientes inválidas: ingresá un número entero de 0 en adelante."
            self._filas = []
            self._refrescar_lista()
            self.GetTopLevelParent().SetStatusText(mensaje)
            wx.MessageBox(mensaje, "Filtro inválido", wx.OK | wx.ICON_ERROR, self)
            return

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
                        cuotas_pendientes_maximo=cuotas_pendientes_maximo,
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

                estado_credito = fila[_INDICE_ESTADO_CREDITO_FILA]
                if self._es_credito_en_alerta(estado_credito):
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
    def _es_credito_en_alerta(estado_credito):
        """Vencido/Saneado — pedido explícito del usuario (2026-08-21): mismo
        equivalente visual/auditivo que ya tiene Casos para "Documentos
        pendientes" (ver casos_panel.py). Usado tanto para el resaltado en
        rojo de la fila (_refrescar_lista) como para el sonido de navegación
        (_on_seleccionar_credito)."""
        return estado_credito in ESTADOS_CREDITO_ALERTA

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
            _monto_desembolsado, estado_credito, _empresa_convenio, _plazo_credito, numero_cuotas,
            cuotas_pagadas, _estado_credito_fecha_cambio, _saldo_principal, _saldo_intereses,
        ) = fila
        pendientes_texto = self._formatear_cuotas_pendientes(numero_cuotas, cuotas_pagadas) or (
            CreditosPanel.CELDA_VACIA
        )
        self.credito_seleccionado_texto.SetLabel(
            f"{nombre_cliente} — Cédula {cedula} — Crédito No. {no_credito} — "
            f"Estado: {estado_credito or CreditosPanel.CELDA_VACIA} — "
            f"Cuotas pendientes: {pendientes_texto}"
        )

        # Equivalente auditivo, para el usuario ciego, del resaltado en rojo
        # que ve un vidente en esta misma fila (ver _refrescar_lista): suena
        # cada vez que la selección llega a un crédito Vencido o Saneado, sea
        # por flechas, Tab o clic — EVT_LIST_ITEM_SELECTED cubre los tres.
        # Mismo patrón que CasosPanel._on_seleccionar_caso.
        if self._es_credito_en_alerta(estado_credito):
            reproducir_sonido(SONIDO_FILA_CREDITO_VENCIDO_SANEADO)
