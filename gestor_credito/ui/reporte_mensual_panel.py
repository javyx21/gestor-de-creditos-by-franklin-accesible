from datetime import datetime

import wx

from gestor_credito.db.casos import obtener_ejecutivos
from gestor_credito.db.configuracion import CLAVE_EJECUTIVO_ACTUAL, obtener_valor
from gestor_credito.db.database import get_connection
from gestor_credito.db.reporte_mensual import generar_reporte_mensual
from gestor_credito.export.excel_export import exportar_reporte_mensual
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.fechas import formatear_fecha
from gestor_credito.ui.logo import AppLogo

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Primera opción del selector de agente — reporte de todos los agentes juntos,
# distinto de dejar el filtro vacío por accidente (ver _agente_seleccionado()).
OPCION_TODOS_LOS_AGENTES = "Todos los agentes"

# Celda vacía en vez de texto en blanco — mismo criterio que CasosPanel.CELDA_VACIA
# y CreditosPanel: una celda vacía en un wx.ListCtrl hace que NVDA lea solo el
# nombre de columna sin ningún valor, repetido fila tras fila; con este texto
# queda claro que el dato no aplica a esa fila.
CELDA_VACIA = "Celda vacía"

COLUMNAS_RESUMEN = ["Categoría", "Cantidad"]
COLUMNAS_DETALLE = [
    "Categoría", "Nombre", "Identificación", "Empresa Convenio",
    "Microseguro", "Motivo No Aplica", "Fecha",
]

# Selector "Microseguro" (pedido explícito del usuario): quién llevó
# microseguro y quién no, para poder verlos por nombre en la tabla detallada
# — no solo el conteo del resumen. None = sin filtrar.
MICROSEGURO_OPCIONES = [
    ("Todos", None),
    ("Con microseguro", "Sí"),
    ("Sin microseguro", "No"),
]

# Orden en que se combinan las 4 categorías en la tabla de detalle.
_CATEGORIAS_DETALLE = ("Desembolsados", "No aplica", "Cliente desistió", "Pendientes")


class ReporteMensualPanel(wx.Panel):
    """"Herramientas ▸ Reporte Mensual de Casos": Desembolsados (con/sin
    microseguro), No aplica, Cliente desistió y Pendientes — para
    seguimiento de comisiones (ver CLAUDE.md). Puramente de consulta y
    exportación: nada acá es editable, ver db/reporte_mensual.py para la
    lógica de cruce con Historial de Créditos que decide cada categoría.

    Dos tablas SIEMPRE VISIBLES (wx.ListCtrl), mismo patrón que Casos e
    Historial de Créditos — no un wx.TreeCtrl escondido detrás de una
    casilla como la primera versión: eso dejaba el detalle sin foco y sin
    ninguna forma de que NVDA lo encontrara al mostrarse (reporte real del
    usuario). Al estar siempre presentes y en el orden normal de tabulación,
    no hace falta ningún manejo especial de foco para llegar a ellas.

    Pendientes NO se filtra por el mes elegido a propósito (pedido
    explícito del usuario): es la lista viva de todo lo que sigue abierto
    ahora mismo, para que nada se pierda de vista entre un mes y el
    siguiente."""

    def __init__(self, parent):
        super().__init__(parent)

        self._resultado_actual = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Reporte Mensual de Casos")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_seccion_filtros(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        resumen_label = wx.StaticText(self, label="Resumen general:")
        sizer.Add(resumen_label, 0, wx.LEFT | wx.RIGHT, 8)

        self.resumen_lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 150))
        nombre_accesible(self.resumen_lista, "Tabla resumen del reporte mensual")
        for indice, columna in enumerate(COLUMNAS_RESUMEN):
            self.resumen_lista.InsertColumn(indice, columna)
            self.resumen_lista.SetColumnWidth(indice, wx.LIST_AUTOSIZE_USEHEADER)
        sizer.Add(self.resumen_lista, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        detalle_label = wx.StaticText(self, label="Casos detallados:")
        sizer.Add(detalle_label, 0, wx.LEFT | wx.RIGHT, 8)

        self.detalle_lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        nombre_accesible(self.detalle_lista, "Tabla detallada de casos del reporte mensual")
        for indice, columna in enumerate(COLUMNAS_DETALLE):
            self.detalle_lista.InsertColumn(indice, columna)
            self.detalle_lista.SetColumnWidth(indice, wx.LIST_AUTOSIZE_USEHEADER)
        sizer.Add(self.detalle_lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.guardar_btn = wx.Button(self, label="&Guardar reporte...")
        self.guardar_btn.Bind(wx.EVT_BUTTON, self._on_guardar_reporte)
        activar_con_enter(self.guardar_btn)
        sizer.Add(self.guardar_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)
        self._cargar_agentes()
        self.recargar()

    # ---- Filtros -----------------------------------------------------

    def _crear_seccion_filtros(self, panel):
        box = wx.StaticBoxSizer(wx.HORIZONTAL, panel, "Filtros")
        contenedor = box.GetStaticBox()

        ahora = datetime.now()

        mes_label = wx.StaticText(contenedor, label="Mes:")
        self.mes_choice = wx.Choice(contenedor, choices=MESES)
        self.mes_choice.SetSelection(ahora.month - 1)
        nombre_accesible(self.mes_choice, "Mes del reporte")
        self.mes_choice.Bind(wx.EVT_CHOICE, self._on_cambiar_filtro)

        anio_label = wx.StaticText(contenedor, label="Año:")
        self.anio_spin = wx.SpinCtrl(contenedor, min=2020, max=2100, initial=ahora.year)
        nombre_accesible(self.anio_spin, "Año del reporte")
        self.anio_spin.Bind(wx.EVT_SPINCTRL, self._on_cambiar_filtro)
        # wx.SpinCtrl también acepta escribir el número directo (no solo las
        # flechas) — EVT_TEXT cubre ese caso, igual que EVT_SPINCTRL cubre
        # las flechas/rueda del mouse.
        self.anio_spin.Bind(wx.EVT_TEXT, self._on_cambiar_filtro)

        agente_label = wx.StaticText(contenedor, label="Agente:")
        self.agente_choice = wx.Choice(contenedor, choices=[])
        nombre_accesible(self.agente_choice, "Agente del reporte")
        self.agente_choice.Bind(wx.EVT_CHOICE, self._on_cambiar_filtro)

        microseguro_label = wx.StaticText(contenedor, label="Microseguro:")
        self.microseguro_choice = wx.Choice(
            contenedor, choices=[texto for texto, _valor in MICROSEGURO_OPCIONES]
        )
        self.microseguro_choice.SetSelection(0)
        nombre_accesible(self.microseguro_choice, "Filtrar tabla detallada por microseguro")
        # Filtro puramente de VISTA sobre el mismo resultado ya calculado —
        # no vuelve a consultar la base de datos (ver _on_cambiar_filtro_microseguro).
        self.microseguro_choice.Bind(wx.EVT_CHOICE, self._on_cambiar_filtro_microseguro)

        for control in (
            mes_label, self.mes_choice, anio_label, self.anio_spin,
            agente_label, self.agente_choice, microseguro_label, self.microseguro_choice,
        ):
            box.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        return box

    def _cargar_agentes(self):
        conn = get_connection()
        try:
            ejecutivo_actual = obtener_valor(conn, CLAVE_EJECUTIVO_ACTUAL)
            ejecutivos = obtener_ejecutivos(conn)
        finally:
            conn.close()

        opciones = [OPCION_TODOS_LOS_AGENTES, *ejecutivos]
        self.agente_choice.Set(opciones)
        # Por defecto, el agente configurado en Configuración de Casos (si
        # existe y ya tiene casos) — mismo criterio que el resto de la app
        # (ver ejecutivo_actual en CLAUDE.md). Si no, "Todos los agentes".
        if ejecutivo_actual and ejecutivo_actual in ejecutivos:
            self.agente_choice.SetSelection(opciones.index(ejecutivo_actual))
        else:
            self.agente_choice.SetSelection(0)

    def _agente_seleccionado(self):
        valor = self.agente_choice.GetStringSelection()
        if not valor or valor == OPCION_TODOS_LOS_AGENTES:
            return None
        return valor

    def _microseguro_seleccionado(self):
        _texto, valor = MICROSEGURO_OPCIONES[self.microseguro_choice.GetSelection()]
        return valor

    def _on_cambiar_filtro(self, event):
        self.recargar()

    def _on_cambiar_filtro_microseguro(self, event):
        if self._resultado_actual is not None:
            self._refrescar_detalle(self._resultado_actual)

    # ---- Cálculo y presentación ---------------------------------------

    def recargar(self):
        anio = self.anio_spin.GetValue()
        mes = self.mes_choice.GetSelection() + 1
        agente = self._agente_seleccionado()

        conn = get_connection()
        try:
            resultado = generar_reporte_mensual(conn, anio, mes, ejecutivo=agente)
        finally:
            conn.close()

        self._resultado_actual = resultado
        self._refrescar_resumen(resultado)
        self._refrescar_detalle(resultado)

        mensaje = (
            f"{MESES[mes - 1]} {anio}: {len(resultado['desembolsados'])} desembolsados, "
            f"{len(resultado['no_aplica'])} no aplica, "
            f"{len(resultado['cliente_desistio'])} cliente desistió, "
            f"{len(resultado['pendientes'])} pendientes."
        )
        self.GetTopLevelParent().SetStatusText(mensaje)

    def _refrescar_resumen(self, resultado):
        filas = [
            ("Desembolsados", len(resultado["desembolsados"])),
            ("  Con microseguro", resultado["con_microseguro"]),
            ("  Sin microseguro", resultado["sin_microseguro"]),
            ("No aplica", len(resultado["no_aplica"])),
            ("Cliente desistió", len(resultado["cliente_desistio"])),
            ("Pendientes (no depende del mes elegido)", len(resultado["pendientes"])),
        ]
        self.resumen_lista.Freeze()
        try:
            self.resumen_lista.DeleteAllItems()
            for fila, (categoria, cantidad) in enumerate(filas):
                indice = self.resumen_lista.InsertItem(fila, categoria)
                self.resumen_lista.SetItem(indice, 1, str(cantidad))
        finally:
            self.resumen_lista.Thaw()

    def _entradas_combinadas(self, resultado):
        claves = {
            "Desembolsados": "desembolsados",
            "No aplica": "no_aplica",
            "Cliente desistió": "cliente_desistio",
            "Pendientes": "pendientes",
        }
        for categoria in _CATEGORIAS_DETALLE:
            for entrada in resultado[claves[categoria]]:
                yield categoria, entrada

    def _refrescar_detalle(self, resultado):
        microseguro_filtro = self._microseguro_seleccionado()

        self.detalle_lista.Freeze()
        try:
            self.detalle_lista.DeleteAllItems()
            fila = 0
            for categoria, entrada in self._entradas_combinadas(resultado):
                if microseguro_filtro is not None and entrada["microseguro"] != microseguro_filtro:
                    continue

                valores = [
                    categoria,
                    entrada["nombre"] or "",
                    entrada["cedula"] or "",
                    entrada["empresa_convenio"] or "",
                    entrada["microseguro"] or "",
                    entrada["motivo_no_aplica"] or "",
                    formatear_fecha(entrada["fecha"]) if entrada["fecha"] else "",
                ]
                valores = [valor if valor else CELDA_VACIA for valor in valores]

                indice = self.detalle_lista.InsertItem(fila, valores[0])
                for columna, valor in enumerate(valores[1:], start=1):
                    self.detalle_lista.SetItem(indice, columna, valor)
                fila += 1
        finally:
            self.detalle_lista.Thaw()

    # ---- Exportar -------------------------------------------------------

    def _on_guardar_reporte(self, event):
        """Botón "Guardar reporte...": pregunta dónde guardar con
        wx.FileDialog nativo (excepción ya aceptada a "sin popups", igual
        que la importación de Excel) con un nombre sugerido por mes/año. El
        trabajo real vive en _guardar_reporte_en_ruta, separado a propósito
        para poder probarlo sin el diálogo real (modal e interactivo, no
        invocable en una prueba automatizada) — mismo patrón que
        _guardar_pdf_en_ruta en calculadora_panel.py."""
        if self._resultado_actual is None:
            return

        anio = self.anio_spin.GetValue()
        mes = self.mes_choice.GetSelection() + 1
        nombre_mes = MESES[mes - 1]
        nombre_sugerido = f"ReporteMensual_{nombre_mes}_{anio}.xlsx"

        with wx.FileDialog(
            self, "Guardar reporte mensual", defaultFile=nombre_sugerido,
            wildcard="Archivos Excel (*.xlsx)|*.xlsx",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            ruta = dialogo.GetPath()

        self._guardar_reporte_en_ruta(ruta, nombre_mes, anio)

    def _guardar_reporte_en_ruta(self, ruta, nombre_mes, anio):
        agente = self._agente_seleccionado() or OPCION_TODOS_LOS_AGENTES
        try:
            exportar_reporte_mensual(self._resultado_actual, nombre_mes, anio, agente, ruta)
        except OSError as exc:
            mensaje = f"Error al guardar el reporte: {exc}"
            self.GetTopLevelParent().SetStatusText(mensaje)
            wx.MessageBox(mensaje, "Error al guardar", wx.OK | wx.ICON_ERROR, self)
            return

        mensaje = f"Reporte guardado en {ruta}"
        self.GetTopLevelParent().SetStatusText(mensaje)
        anunciar_voz_nvda("Reporte guardado.")
