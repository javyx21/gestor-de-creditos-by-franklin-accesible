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
from gestor_credito.ui.sonido import SONIDO_ACTUALIZACION_REPORTE, reproducir_sonido

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Primera opción del selector de agente — reporte de todos los agentes juntos,
# distinto de dejar el filtro vacío por accidente (ver _agente_seleccionado()).
OPCION_TODOS_LOS_AGENTES = "Todos los agentes"


def _texto_entrada(entrada):
    """Línea legible por NVDA para una fila del árbol de detalle — mismo
    criterio que _texto_alerta() en notificaciones_panel.py."""
    partes = [
        entrada["nombre"] or "(sin nombre)",
        f"Cédula {entrada['cedula'] or '(sin cédula)'}",
        f"Empresa {entrada['empresa_convenio'] or '(sin empresa)'}",
    ]
    if entrada["fecha"]:
        partes.append(f"Fecha {formatear_fecha(entrada['fecha'])}")
    if entrada["motivo_no_aplica"]:
        partes.append(f"Motivo: {entrada['motivo_no_aplica']}")
    return " — ".join(partes)


class ReporteMensualPanel(wx.Panel):
    """"Herramientas ▸ Reporte Mensual de Casos": Desembolsados (con/sin
    microseguro), No aplica, Cliente desistió y Pendientes — para
    seguimiento de comisiones (ver CLAUDE.md). Puramente de consulta y
    exportación: nada acá es editable, ver db/reporte_mensual.py para la
    lógica de cruce con Historial de Créditos que decide cada categoría.

    Pendientes NO se filtra por el mes elegido a propósito (pedido
    explícito del usuario): es la lista viva de todo lo que sigue abierto
    ahora mismo, para que nada se pierda de vista entre un mes y el
    siguiente."""

    def __init__(self, parent):
        super().__init__(parent)

        self._resultado_actual = None
        self._conteos_anteriores = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Reporte Mensual de Casos")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_seccion_filtros(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(self._crear_seccion_resumen(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.detalle_check = wx.CheckBox(self, label="Ver casos &detallados")
        self.detalle_check.Bind(wx.EVT_CHECKBOX, self._on_toggle_detalle)
        sizer.Add(self.detalle_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Mismo control (wx.TreeCtrl) y mismo criterio de agrupación por
        # categoría que el árbol de alertas de Notificaciones — ver
        # notificaciones_panel.py.
        self.arbol = wx.TreeCtrl(self, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT)
        nombre_accesible(self.arbol, "Árbol de casos del reporte")
        self.arbol.Hide()
        sizer.Add(self.arbol, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.guardar_btn = wx.Button(self, label="&Guardar reporte...")
        self.guardar_btn.Bind(wx.EVT_BUTTON, self._on_guardar_reporte)
        activar_con_enter(self.guardar_btn)
        sizer.Add(self.guardar_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)
        self._cargar_agentes()
        self.recargar()

    # ---- Filtros -----------------------------------------------------

    def _crear_seccion_filtros(self, panel):
        box = wx.StaticBoxSizer(wx.HORIZONTAL, panel, "Mes a consultar")
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

        for control in (
            mes_label, self.mes_choice, anio_label, self.anio_spin,
            agente_label, self.agente_choice,
        ):
            box.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        return box

    def _crear_seccion_resumen(self, panel):
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Resumen")
        contenedor = box.GetStaticBox()

        self.desembolsados_label = wx.StaticText(contenedor, label="")
        self.no_aplica_label = wx.StaticText(contenedor, label="")
        self.cliente_desistio_label = wx.StaticText(contenedor, label="")
        self.pendientes_label = wx.StaticText(contenedor, label="")

        for control in (
            self.desembolsados_label, self.no_aplica_label,
            self.cliente_desistio_label, self.pendientes_label,
        ):
            box.Add(control, 0, wx.BOTTOM, 4)

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

    def _on_cambiar_filtro(self, event):
        self.recargar()

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

        conteos = (
            len(resultado["desembolsados"]), resultado["con_microseguro"],
            resultado["sin_microseguro"], len(resultado["no_aplica"]),
            len(resultado["cliente_desistio"]), len(resultado["pendientes"]),
        )
        if self._conteos_anteriores is not None and conteos != self._conteos_anteriores:
            reproducir_sonido(SONIDO_ACTUALIZACION_REPORTE)
        self._conteos_anteriores = conteos

        self._resultado_actual = resultado
        self._mostrar_resumen(resultado)
        if self.detalle_check.GetValue():
            self._mostrar_detalle(resultado)

        mensaje = (
            f"{MESES[mes - 1]} {anio}: {len(resultado['desembolsados'])} desembolsados, "
            f"{len(resultado['no_aplica'])} no aplica, "
            f"{len(resultado['cliente_desistio'])} cliente desistió, "
            f"{len(resultado['pendientes'])} pendientes."
        )
        self.GetTopLevelParent().SetStatusText(mensaje)

    def _mostrar_resumen(self, resultado):
        self.desembolsados_label.SetLabel(
            f"Desembolsados: {len(resultado['desembolsados'])} "
            f"(con microseguro: {resultado['con_microseguro']} / "
            f"sin microseguro: {resultado['sin_microseguro']})"
        )
        self.no_aplica_label.SetLabel(f"No aplica: {len(resultado['no_aplica'])}")
        self.cliente_desistio_label.SetLabel(
            f"Cliente desistió: {len(resultado['cliente_desistio'])}"
        )
        self.pendientes_label.SetLabel(
            f"Pendientes (no depende del mes elegido): {len(resultado['pendientes'])}"
        )

    def _on_toggle_detalle(self, event):
        mostrar = self.detalle_check.GetValue()
        self.arbol.Show(mostrar)
        if mostrar and self._resultado_actual is not None:
            self._mostrar_detalle(self._resultado_actual)
        self.Layout()

    def _mostrar_detalle(self, resultado):
        self.arbol.DeleteAllItems()
        raiz = self.arbol.AddRoot("Reporte")

        grupos = (
            ("Desembolsados", resultado["desembolsados"]),
            ("No aplica", resultado["no_aplica"]),
            ("Cliente desistió", resultado["cliente_desistio"]),
            ("Pendientes", resultado["pendientes"]),
        )
        for nombre_categoria, entradas in grupos:
            nodo = self.arbol.AppendItem(raiz, f"{nombre_categoria} ({len(entradas)})")
            for entrada in entradas:
                self.arbol.AppendItem(nodo, _texto_entrada(entrada))

        self.arbol.ExpandAll()

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
