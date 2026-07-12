from datetime import date

import wx
import wx.lib.scrolledpanel as scrolledpanel

from gestor_credito.calculo.amortizacion import PERIODICIDADES_VALIDAS
from gestor_credito.calculo.capacidad import evaluar_capacidad
from gestor_credito.db.convenios import guardar_tasa, listar_convenios
from gestor_credito.db.database import get_connection
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.fechas import parsear_fecha_ui
from gestor_credito.ui.logo import AppLogo


class CalculadoraPanel(scrolledpanel.ScrolledPanel):
    """Calculadora de crédito completamente independiente y autocontenida —
    pedido explícito del usuario (2026-07-12): "por el momento, este módulo
    debe ser estrictamente una calculadora de crédito independiente y nada
    más; solo debe permitirle al usuario digitar los datos en el momento
    para hacer los cálculos". No busca ni referencia casos/clientes/cédulas
    de ningún tipo — ni siquiera para prellenar campos. Todo lo que necesita
    lo tipea el oficial ahí mismo, cada vez.

    (Versión anterior, revertida: llegó a tener una sección "Buscar caso"
    que reutilizaba buscar_casos() de Casos para prellenar Empresa/Monto y
    un botón "Guardar simulación en este caso" que persistía contra un
    caso_id — el usuario rechazó explícitamente esa vinculación: "no estoy
    de acuerdo con la vinculación que estás haciendo... yo nunca pedí que
    se añadiera nada de eso". Ver CLAUDE.md para el detalle completo. La
    tabla `calculo_credito` y `db/calculo_credito.py` (guardar/obtener
    simulación por caso) quedaron en el código sin usar — no se borraron
    porque no se pidió, pero este panel ya no los toca.)

    Vive como la segunda pestaña de un wx.Notebook en MainFrame (junto a
    Casos) — ver CLAUDE.md, "Navegación", para el historial de por qué es
    una pestaña y no un diálogo de menú.

    Hereda de ScrolledPanel (no wx.Panel liso) a propósito: el formulario
    completo supera fácilmente el alto de una sola pantalla — bug real
    reportado por el usuario (2026-07-11): sin scroll, las secciones de más
    abajo quedaban recortadas y no había forma de llegar a ellas ni con Tab.

    Replica el flujo de recursos/calculadora.xlsx (ver CLAUDE.md para el
    análisis completo de esa hoja, celda por celda): el oficial tipea la
    empresa (resuelve la tasa por convenio), la premisa del pasivo laboral
    (fecha de ingreso + salario), los ingresos extra, y las condiciones del
    crédito (monto, plazo, periodicidad, tipo de cambio, deudas activas) —
    Calcular (gestor_credito/calculo/) muestra pasivo laboral, salario neto,
    cuota, cobertura de pasivo laboral y nivel de endeudamiento. Nada se
    guarda: es una herramienta de cálculo del momento, para explorar
    escenarios, no un registro persistente."""

    def __init__(self, parent):
        super().__init__(parent)

        self._convenios = {}

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Calculadora de Crédito")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_entradas(), 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self._crear_resultados(), 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self._crear_seccion_tasas(), 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self.SetupScrolling(scroll_x=False, scroll_y=True)
        self._cargar_empresas()

    # ---- Datos de entrada -------------------------------------------------
    # Nombres de campo/comentarios citan la celda de recursos/calculadora.xlsx
    # que replican (ver CLAUDE.md, sección Calculadora de Crédito) para poder
    # rastrear cada control hasta su origen en el Excel.

    def _crear_entradas(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Datos para calcular")
        contenedor = box.GetStaticBox()

        grilla = wx.FlexGridSizer(cols=4, gap=(8, 6))

        # B5: empresa convenio (tipeada/elegida a mano, nunca prellenada) ->
        # resuelve B12 (tasa) por VLOOKUP contra convenio_tasa.
        empresa_label = wx.StaticText(contenedor, label="Empresa convenio:")
        self.empresa_choice = wx.Choice(contenedor, choices=[])
        nombre_accesible(self.empresa_choice, "Empresa convenio")
        self.empresa_choice.Bind(wx.EVT_CHOICE, lambda event: self._actualizar_tasa_mostrada())
        self.tasa_texto = wx.StaticText(contenedor, label="Tasa: —")
        grilla.Add(empresa_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.empresa_choice, 0, wx.EXPAND)
        grilla.Add(self.tasa_texto, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(wx.StaticText(contenedor, label=""))

        # B6/B7: premisa del pasivo laboral (fecha de ingreso + salario bruto).
        fecha_ingreso_label = wx.StaticText(contenedor, label="Fecha de ingreso a la empresa (DD/MM/AAAA):")
        self.fecha_ingreso_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.fecha_ingreso_texto, "Fecha de ingreso a la empresa")
        salario_label = wx.StaticText(contenedor, label="Salario bruto mensual (C$):")
        self.salario_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.salario_texto, "Salario bruto mensual en Córdobas")
        grilla.Add(fecha_ingreso_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.fecha_ingreso_texto, 0, wx.EXPAND)
        grilla.Add(salario_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.salario_texto, 0, wx.EXPAND)

        # D9/B10: ingresos extra (suman al salario neto) y monto del crédito
        # (siempre en Dólares, se tipea directo — nunca viene de un caso).
        extra_label = wx.StaticText(contenedor, label="Ingresos extra (C$, opcional):")
        self.extra_texto = wx.TextCtrl(contenedor, value="0")
        nombre_accesible(self.extra_texto, "Ingresos extra en Córdobas")
        monto_label = wx.StaticText(contenedor, label="Monto del crédito (US$):")
        self.monto_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.monto_texto, "Monto del crédito en Dólares")
        grilla.Add(extra_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.extra_texto, 0, wx.EXPAND)
        grilla.Add(monto_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.monto_texto, 0, wx.EXPAND)

        # B11/B13: plazo (siempre en meses, ver capacidad.py) y periodicidad.
        plazo_label = wx.StaticText(contenedor, label="Plazo (meses):")
        self.plazo_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.plazo_texto, "Plazo en meses")
        periodicidad_label = wx.StaticText(contenedor, label="Periodicidad:")
        self.periodicidad_choice = wx.Choice(contenedor, choices=list(PERIODICIDADES_VALIDAS))
        nombre_accesible(self.periodicidad_choice, "Periodicidad")
        self.periodicidad_choice.SetSelection(0)
        grilla.Add(plazo_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.plazo_texto, 0, wx.EXPAND)
        grilla.Add(periodicidad_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.periodicidad_choice, 0, wx.EXPAND)

        # Tipo de cambio: no es una celda propia del Excel (ahí vivía junto a
        # la consulta de cédula que este panel ya no usa) — queda como campo
        # manual, se tipea cada vez (ver CLAUDE.md, pregunta abierta sobre si
        # debería vivir en Configuración en su lugar). C15: cuotas de deudas
        # activas externas (la etiqueta "Cuotas de Deudas Activas" es B15).
        tipo_cambio_label = wx.StaticText(contenedor, label="Tipo de cambio (C$ por US$):")
        self.tipo_cambio_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.tipo_cambio_texto, "Tipo de cambio, Córdobas por Dólar")
        deuda_label = wx.StaticText(contenedor, label="Cuotas de deudas activas externas (C$, opcional):")
        self.deuda_texto = wx.TextCtrl(contenedor, value="0")
        nombre_accesible(self.deuda_texto, "Cuotas de deudas activas externas en Córdobas")
        grilla.Add(tipo_cambio_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.tipo_cambio_texto, 0, wx.EXPAND)
        grilla.Add(deuda_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.deuda_texto, 0, wx.EXPAND)

        box.Add(grilla, 0, wx.EXPAND | wx.BOTTOM, 8)

        # Único botón de acción de esta sección — siempre habilitado (no hay
        # ningún estado previo, como un caso seleccionado, del que dependa).
        self.calcular_btn = wx.Button(contenedor, label="&Calcular")
        self.calcular_btn.Bind(wx.EVT_BUTTON, self._on_calcular)
        activar_con_enter(self.calcular_btn)
        box.Add(self.calcular_btn, 0)

        return box

    def _actualizar_tasa_mostrada(self):
        empresa = self.empresa_choice.GetStringSelection()
        tasa = self._convenios.get(empresa)
        self.tasa_texto.SetLabel("Tasa: sin configurar" if tasa is None else f"Tasa: {tasa:.0%}")

    # ---- Resultados ---------------------------------------------------
    # Orden y contenido calcan Calculadora!B7:B19 del Excel de referencia.

    def _crear_resultados(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Resultados")
        contenedor = box.GetStaticBox()

        self.resultado_salario_bruto = wx.StaticText(contenedor, label="Salario bruto: —")
        self.resultado_pasivo_laboral = wx.StaticText(contenedor, label="Pasivo laboral: —")
        self.resultado_salario_neto = wx.StaticText(contenedor, label="Salario neto mensual: —")
        self.resultado_cuota = wx.StaticText(contenedor, label="Cuota calculada: —")
        self.resultado_cobertura = wx.StaticText(contenedor, label="Cobertura de pasivo laboral: —")
        self.resultado_endeudamiento = wx.StaticText(contenedor, label="Nivel de endeudamiento: —")

        for control in (
            self.resultado_salario_bruto, self.resultado_pasivo_laboral, self.resultado_salario_neto,
            self.resultado_cuota, self.resultado_cobertura, self.resultado_endeudamiento,
        ):
            box.Add(control, 0, wx.BOTTOM, 4)

        return box

    def _limpiar_resultados(self):
        self.resultado_salario_bruto.SetLabel("Salario bruto: —")
        self.resultado_pasivo_laboral.SetLabel("Pasivo laboral: —")
        self.resultado_salario_neto.SetLabel("Salario neto mensual: —")
        self.resultado_cuota.SetLabel("Cuota calculada: —")
        self.resultado_cobertura.SetLabel("Cobertura de pasivo laboral: —")
        self.resultado_endeudamiento.SetLabel("Nivel de endeudamiento: —")

    def _leer_entradas(self):
        """Valida y convierte todos los campos de entrada. Devuelve
        (entradas_dict, None) si todo es válido, o (None, mensaje_error) si
        no — nunca lanza, para que el llamador decida cómo avisar (acá
        siempre wx.MessageBox, ver _on_calcular: es una validación que de
        otra forma NVDA no se enteraría, mismo criterio que el resto de la
        app para este tipo de error)."""
        empresa = self.empresa_choice.GetStringSelection()
        if not empresa:
            return None, "Elegí una empresa convenio."
        tasa = self._convenios.get(empresa)
        if tasa is None:
            return None, (
                f"«{empresa}» no tiene una tasa de interés configurada. "
                "Asignale una tasa en la sección \"Tasas por convenio\" antes de calcular."
            )

        fecha_ingreso_iso = parsear_fecha_ui(self.fecha_ingreso_texto.GetValue())
        if fecha_ingreso_iso is None:
            return None, "La fecha de ingreso debe tener el formato DD/MM/AAAA."

        try:
            salario = float(self.salario_texto.GetValue().replace(",", ""))
            extra = float(self.extra_texto.GetValue().replace(",", "") or 0)
            monto = float(self.monto_texto.GetValue().replace(",", ""))
            plazo = int(self.plazo_texto.GetValue())
            tipo_cambio = float(self.tipo_cambio_texto.GetValue().replace(",", ""))
            deuda = float(self.deuda_texto.GetValue().replace(",", "") or 0)
        except ValueError:
            return None, "Revisá los campos numéricos: salario, ingresos extra, monto, plazo, tipo de cambio y deuda deben ser números."

        if salario <= 0 or monto <= 0 or plazo <= 0 or tipo_cambio <= 0:
            return None, "Salario, monto, plazo y tipo de cambio deben ser mayores que cero."

        periodicidad = self.periodicidad_choice.GetStringSelection()

        return {
            "empresa_convenio": empresa,
            "tasa_interes": tasa,
            "fecha_ingreso": date.fromisoformat(fecha_ingreso_iso),
            "salario_bruto_cordobas": salario,
            "ingresos_extra_cordobas": extra,
            "monto_credito_usd": monto,
            "plazo_meses": plazo,
            "periodicidad": periodicidad,
            "tipo_cambio": tipo_cambio,
            "deuda_activa_cordobas": deuda,
        }, None

    def _on_calcular(self, event):
        entradas, error = self._leer_entradas()
        if error:
            wx.MessageBox(error, "Datos incompletos", wx.OK | wx.ICON_ERROR, self)
            return

        resultado = evaluar_capacidad(
            fecha_ingreso=entradas["fecha_ingreso"],
            salario_bruto_mensual_cordobas=entradas["salario_bruto_cordobas"],
            ingresos_extra_cordobas=entradas["ingresos_extra_cordobas"],
            monto_credito_usd=entradas["monto_credito_usd"],
            plazo_meses=entradas["plazo_meses"],
            periodicidad=entradas["periodicidad"],
            tasa_anual=entradas["tasa_interes"],
            tipo_cambio=entradas["tipo_cambio"],
            deuda_activa_cordobas=entradas["deuda_activa_cordobas"],
        )

        # Calculadora!C7 = B7/C2 — conversión trivial, no vive en
        # evaluar_capacidad() porque es solo informativa (nada más la usa),
        # pero el usuario pidió explícitamente que el salario bruto en
        # dólares también quede visible en el panel.
        salario_bruto_usd = entradas["salario_bruto_cordobas"] / entradas["tipo_cambio"]

        self.resultado_salario_bruto.SetLabel(
            f"Salario bruto: C${entradas['salario_bruto_cordobas']:,.2f} (US${salario_bruto_usd:,.2f})"
        )
        self.resultado_pasivo_laboral.SetLabel(
            f"Pasivo laboral: C${resultado.pasivo_laboral_cordobas:,.2f} "
            f"(US${resultado.pasivo_laboral_usd:,.2f})"
        )
        self.resultado_salario_neto.SetLabel(
            f"Salario neto mensual: C${resultado.salario_neto_cordobas:,.2f} "
            f"(US${resultado.salario_neto_usd:,.2f})"
        )
        self.resultado_cuota.SetLabel(
            f"Cuota calculada: US${resultado.cuota_usd:,.2f} (C${resultado.cuota_cordobas:,.2f})"
        )
        self.resultado_cobertura.SetLabel(
            f"Cobertura de pasivo laboral: {resultado.cobertura_pasivo_laboral:.0%}"
        )
        self.resultado_endeudamiento.SetLabel(
            f"Nivel de endeudamiento: {resultado.nivel_endeudamiento:.0%}"
        )

        mensaje = (
            f"Pasivo laboral: {resultado.pasivo_laboral_cordobas:,.2f} córdobas. "
            f"Cuota calculada: {resultado.cuota_usd:.2f} dólares. "
            f"Nivel de endeudamiento: {resultado.nivel_endeudamiento:.0%}."
        )
        self.GetTopLevelParent().SetStatusText(mensaje)
        # El anuncio por región viva de la barra de estado no se escucha de
        # forma confiable (ver anunciar_voz_nvda en accesibilidad.py — mismo
        # hallazgo real que motivó agregarla para el combo "Filtrar por
        # alerta" de Casos). Acá el resultado del cálculo es exactamente el
        # tipo de anuncio puntual, disparado por una acción explícita del
        # usuario, para el que se construyó esa función.
        anunciar_voz_nvda(mensaje)

    # ---- Tasas por convenio --------------------------------------------

    def _crear_seccion_tasas(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Tasas por convenio")
        contenedor = box.GetStaticBox()

        self.tasas_lista = wx.ListCtrl(contenedor, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 150))
        nombre_accesible(self.tasas_lista, "Tasas por convenio")
        self.tasas_lista.InsertColumn(0, "Empresa")
        self.tasas_lista.InsertColumn(1, "Tasa")
        self.tasas_lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_seleccionar_tasa)
        box.Add(self.tasas_lista, 0, wx.EXPAND | wx.BOTTOM, 8)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(contenedor, label="Nueva tasa para la empresa seleccionada (%, ej. 36):")
        self.nueva_tasa_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.nueva_tasa_texto, "Nueva tasa para la empresa seleccionada, en porcentaje")
        actualizar_btn = wx.Button(contenedor, label="&Actualizar tasa")
        actualizar_btn.Bind(wx.EVT_BUTTON, self._on_actualizar_tasa)
        activar_con_enter(actualizar_btn)

        for control in (label, self.nueva_tasa_texto, actualizar_btn):
            fila.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        box.Add(fila, 0)

        return box

    def recargar(self):
        """Se llama al entrar a esta pestaña (ver MainFrame._on_cambiar_pestana)
        para que una tasa actualizada en otra sesión/pestaña se refleje sin
        recargar a mano. A propósito NO toca los datos ya escritos en el
        formulario — solo refresca la lista de empresas/tasas (ver
        _cargar_empresas, que preserva la empresa elegida si sigue
        existiendo)."""
        self._cargar_empresas()

    def _cargar_empresas(self):
        conn = get_connection()
        try:
            convenios = listar_convenios(conn)
        finally:
            conn.close()

        empresa_previa = self.empresa_choice.GetStringSelection()

        self._convenios = dict(convenios)
        self.empresa_choice.Set([empresa for empresa, _tasa in convenios])

        if empresa_previa:
            indice = self.empresa_choice.FindString(empresa_previa)
            if indice != wx.NOT_FOUND:
                self.empresa_choice.SetSelection(indice)
                self._actualizar_tasa_mostrada()

        self.tasas_lista.DeleteAllItems()
        for indice, (empresa, tasa) in enumerate(convenios):
            self.tasas_lista.InsertItem(indice, empresa)
            self.tasas_lista.SetItem(indice, 1, "sin configurar" if tasa is None else f"{tasa:.0%}")
        for columna in range(2):
            self.tasas_lista.SetColumnWidth(columna, wx.LIST_AUTOSIZE_USEHEADER)

    def _on_seleccionar_tasa(self, event):
        empresa, tasa = self._filas_tasas()[event.GetIndex()]
        self.nueva_tasa_texto.SetValue("" if tasa is None else f"{tasa * 100:.0f}")

    def _filas_tasas(self):
        return sorted(self._convenios.items())

    def _on_actualizar_tasa(self, event):
        indice = self.tasas_lista.GetFirstSelected()
        if indice == wx.NOT_FOUND:
            wx.MessageBox(
                "Seleccioná una empresa de la lista antes de actualizar su tasa.",
                "Ninguna empresa seleccionada", wx.OK | wx.ICON_ERROR, self,
            )
            return

        empresa, _tasa_actual = self._filas_tasas()[indice]
        try:
            porcentaje = float(self.nueva_tasa_texto.GetValue().replace(",", "."))
        except ValueError:
            wx.MessageBox(
                "La tasa debe ser un número (por ejemplo 36 para 36%).",
                "Tasa inválida", wx.OK | wx.ICON_ERROR, self,
            )
            return

        conn = get_connection()
        try:
            guardar_tasa(conn, empresa, porcentaje / 100)
        finally:
            conn.close()

        self._cargar_empresas()
        mensaje = f"Tasa de «{empresa}» actualizada a {porcentaje:.0f}%."
        self.GetTopLevelParent().SetStatusText(mensaje)
