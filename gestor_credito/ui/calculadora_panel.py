import math
from datetime import date, datetime

import wx
import wx.lib.scrolledpanel as scrolledpanel

from gestor_credito.calculo.amortizacion import (
    PERIODICIDAD_MENSUAL,
    PERIODICIDAD_QUINCENAL,
    PERIODICIDADES_VALIDAS,
)
from gestor_credito.calculo.capacidad import evaluar_capacidad
from gestor_credito.calculo.deducciones import calcular_salario_neto_mensual
from gestor_credito.calculo.pasivo_laboral import calcular_pasivo_laboral
from gestor_credito.db.convenios import listar_convenios
from gestor_credito.db.database import get_connection
from gestor_credito.export.pdf_export import generar_pdf_calculo
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.fechas import parsear_fecha_ui
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import SONIDO_BORRAR, reproducir_sonido

# Fijo a pedido explícito del usuario (2026-07-12): "por el momento es
# estrictamente fijo... no va a variar". Antes era un campo editable
# (tipo_cambio_texto) que el oficial tipeaba cada vez — se sacó de la
# interfaz por completo para no ocupar espacio de tabulación con un dato
# que ya no cambia. Cuando exista un módulo de Configuración para tasas de
# interés/empresas/tipo de cambio (mencionado por el usuario como trabajo
# futuro, todavía no pedido), este valor debería migrar ahí en vez de
# quedar hardcodeado — no hacerlo antes de que se pida explícitamente.
TIPO_CAMBIO_FIJO = 36.6243


def _texto_opcion_empresa(empresa, tasa):
    """Texto de cada ítem de empresa_choice — pedido explícito del usuario
    (2026-07-12), tras un reporte real de una tasa desactualizada que hizo
    que no confiara en cuál se estaba aplicando: "necesito que al navegar
    por la lista, cada opción muestre y verbalice el nombre de la empresa
    junto con su respectivo porcentaje de tasa". NVDA ya anuncia el texto
    de cada ítem al arrastrar flechas por un wx.Choice sin necesitar nada
    especial de accesibilidad acá — con la tasa DENTRO del texto del ítem,
    se escucha "Empresa: Tasa: X%" en cada opción sin un paso extra."""
    if tasa is None:
        return f"{empresa}: Tasa: sin configurar"
    return f"{empresa}: Tasa: {tasa:.0%}"


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
    empresa (resuelve la tasa por convenio, solo lectura acá — ver
    "Empresas / tasas por convenio" más abajo), la premisa del pasivo
    laboral (fecha de ingreso + salario, calculado en vivo), los ingresos
    extra, y las condiciones del crédito (monto, plazo, periodicidad,
    deudas activas — el tipo de cambio es fijo, TIPO_CAMBIO_FIJO arriba) —
    Calcular (gestor_credito/calculo/) muestra pasivo laboral, salario neto,
    cuota, cobertura de pasivo laboral y nivel de endeudamiento. Nada se
    guarda: es una herramienta de cálculo del momento, para explorar
    escenarios, no un registro persistente."""

    def __init__(self, parent):
        super().__init__(parent)

        self._convenios = {}
        # Empresas en el mismo orden que los ítems de empresa_choice — permite
        # recuperar el nombre real de la empresa a partir del índice
        # seleccionado, ya que el texto visible/anunciado de cada ítem ahora
        # incluye la tasa (ver _texto_opcion_empresa) y no es directamente la
        # empresa. Ver _empresa_seleccionada().
        self._empresas_por_indice = []
        self._ultimo_resultado = None
        # Pasivo laboral: se rastrea aparte del resto de "Resultados" porque
        # se actualiza en vivo (ver _actualizar_pasivo_laboral_en_vivo), sin
        # esperar a Calcular — pedido explícito del usuario (2026-07-12).
        self._pasivo_laboral_cordobas = None
        self._pasivo_laboral_usd = None
        # Salario con deducciones (salario neto): mismo criterio que el
        # pasivo laboral de arriba — se actualiza en vivo (ver
        # _actualizar_salario_neto_en_vivo), sin esperar a Calcular ni
        # depender de que haya una empresa elegida. Pedido explícito del
        # usuario (2026-08-16): "que se calcule y actualice en tiempo
        # real... siguiendo el mismo comportamiento del cálculo de
        # pasivos".
        self._salario_neto_cordobas = None
        self._salario_neto_usd = None
        # Cuota redondeada hacia arriba al entero (ej. 19.25 -> 20) x
        # TIPO_CAMBIO_FIJO, en córdobas — pedido explícito del usuario
        # (2026-08-20): a diferencia del pasivo laboral/salario neto, esta NO
        # se calcula en vivo, depende de que ya haya corrido un Calcular (ver
        # _calcular_y_mostrar), igual que resultado_cuota.
        self._cuota_redondeada_usd = None
        self._cuota_redondeada_cordobas = None
        # Snapshot de los datos de entrada que produjeron _ultimo_resultado —
        # pedido explícito del usuario (2026-08-21) para el PDF exportable
        # (ver _construir_datos_calculo/_on_guardar_pdf): el PDF tiene que
        # reflejar exactamente los datos del último Calcular, nunca lo que
        # haya quedado tipeado después sin recalcular. Mismo criterio que
        # _ultimo_resultado: se limpia junto con él en _limpiar_resultados.
        self._ultimas_entradas = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Calculadora de Crédito")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        sizer.Add(self._crear_entradas(), 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self._crear_resultados(), 0, wx.EXPAND | wx.ALL, 8)

        # Atajos de un solo tecleo (pedido explícito del usuario, 2026-07-12):
        # Ctrl+Shift+Q/W/E anuncian Pasivo laboral / Salario con deducciones /
        # Empresa por voz SIN mover el foco ni tabular hasta el cuadro de
        # Resultados — para no obligar a NVDA a recorrer todos los campos
        # informativos cada vez que solo hace falta un dato puntual.
        # Ctrl+Shift+R es distinto (ver _on_atajo_verbalizacion): no se limita
        # a anunciar, dispara el cálculo completo — es el ÚNICO atajo de
        # teclado para calcular, ver el botón "Calcular" (sin mnemónico desde
        # que se sacó Alt+A, pedido explícito del usuario: "no dupliques
        # funciones"). Ctrl+R, sin Shift (pedido explícito del usuario,
        # 2026-08-20, "lo más parecido" a Ctrl+Shift+R), solo anuncia la
        # cuota ya calculada redondeada al entero x TIPO_CAMBIO_FIJO — ver
        # _anunciar_cuota_redondeada; no recalcula nada por su cuenta.
        # Mismo mecanismo EVT_CHAR_HOOK a nivel de panel que ya
        # usa CasosPanel para el combo "Filtrar por alerta" (necesario
        # porque, a diferencia de un wx.Dialog, un wx.Panel dentro de un
        # wx.Notebook no recibe atajos de teclado "globales" por ningún otro
        # medio) — pero acá SIN el chequeo de FindFocus() de ese caso, a
        # propósito: el pedido es que funcione sin importar qué control del
        # panel tenga el foco en ese momento.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_atajo_verbalizacion)

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
        #
        # La tasa YA NO tiene una etiqueta visible aparte (pedido explícito
        # del usuario, 2026-08-21: "cosas que he realizado para ciegos que
        # no deberían de estarse mostrando") — no hace falta: el texto del
        # propio ítem elegido en empresa_choice ya incluye la tasa (ver
        # _texto_opcion_empresa, ej. "MIDESA: Tasa: 18%"), y NVDA lo anuncia
        # igual con el combo enfocado, esté abierto o cerrado. La etiqueta
        # separada era solo una ayuda visual para personas videntes, no
        # aportaba nada por voz que no se escuchara ya. Elegir una empresa
        # sigue forzando el mismo recálculo silencioso de siempre.
        empresa_label = wx.StaticText(contenedor, label="Empresa convenio:")
        self.empresa_choice = wx.Choice(contenedor, choices=[])
        nombre_accesible(self.empresa_choice, "Empresa convenio")
        self.empresa_choice.Bind(
            wx.EVT_CHOICE, lambda event: self._refrescar_resultado_tras_cambio_de_tasa()
        )
        grilla.Add(empresa_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.empresa_choice, 0, wx.EXPAND)
        grilla.Add(wx.StaticText(contenedor, label=""))
        grilla.Add(wx.StaticText(contenedor, label=""))

        # B6/B7: premisa del pasivo laboral (fecha de ingreso + salario bruto).
        # Se escuchan en vivo (EVT_TEXT) para actualizar el Pasivo laboral en
        # pantalla sin esperar a Calcular — ver
        # _actualizar_pasivo_laboral_en_vivo. salario_texto además dispara el
        # salario con deducciones en vivo (ver _actualizar_salario_neto_en_vivo
        # — dos handlers distintos atados al mismo EVT_TEXT, cada uno
        # actualiza su propio resultado sin interferir con el otro).
        fecha_ingreso_label = wx.StaticText(contenedor, label="Fecha de ingreso a la empresa (DD/MM/AAAA):")
        self.fecha_ingreso_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.fecha_ingreso_texto, "Fecha de ingreso a la empresa")
        self.fecha_ingreso_texto.Bind(wx.EVT_TEXT, self._actualizar_pasivo_laboral_en_vivo)
        salario_label = wx.StaticText(contenedor, label="Salario bruto mensual (C$):")
        self.salario_texto = wx.TextCtrl(contenedor)
        nombre_accesible(self.salario_texto, "Salario bruto mensual en Córdobas")
        self.salario_texto.Bind(wx.EVT_TEXT, self._actualizar_pasivo_laboral_en_vivo)
        self.salario_texto.Bind(wx.EVT_TEXT, self._actualizar_salario_neto_en_vivo)
        grilla.Add(fecha_ingreso_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.fecha_ingreso_texto, 0, wx.EXPAND)
        grilla.Add(salario_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.salario_texto, 0, wx.EXPAND)

        # D9/B10: ingresos extra (suman al salario neto) y monto del crédito
        # (siempre en Dólares, se tipea directo — nunca viene de un caso).
        # extra_texto también dispara el salario neto en vivo (pedido
        # explícito del usuario, 2026-08-16: recalcular al cambiar "salario
        # bruto y las deducciones" — junto con salario_texto arriba, son los
        # dos únicos campos de los que depende calcular_salario_neto_mensual()).
        extra_label = wx.StaticText(contenedor, label="Ingresos extra (C$, opcional):")
        self.extra_texto = wx.TextCtrl(contenedor, value="0")
        nombre_accesible(self.extra_texto, "Ingresos extra en Córdobas")
        self.extra_texto.Bind(wx.EVT_TEXT, self._actualizar_salario_neto_en_vivo)
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

        # Tipo de cambio: a pedido explícito del usuario (2026-07-12) ya NO
        # es un campo editable — ver TIPO_CAMBIO_FIJO al principio del
        # archivo. C15: cuotas de deudas activas externas (la etiqueta
        # "Cuotas de Deudas Activas" es B15).
        deuda_label = wx.StaticText(contenedor, label="Cuotas de deudas activas externas (C$, opcional):")
        self.deuda_texto = wx.TextCtrl(contenedor, value="0")
        nombre_accesible(self.deuda_texto, "Cuotas de deudas activas externas en Córdobas")
        grilla.Add(deuda_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grilla.Add(self.deuda_texto, 0, wx.EXPAND)
        grilla.Add(wx.StaticText(contenedor, label=""))
        grilla.Add(wx.StaticText(contenedor, label=""))

        box.Add(grilla, 0, wx.EXPAND | wx.BOTTOM, 8)

        # Único botón de acción de esta sección — siempre habilitado (no hay
        # ningún estado previo, como un caso seleccionado, del que dependa).
        #
        # SIN mnemónico (antes Alt+A, antes de eso Alt+C — ver historial en
        # git): pedido explícito del usuario (2026-07-12), "no dupliques
        # funciones... el único shortcut encargado de realizar el cálculo y
        # mostrar el resultado debe ser Control+Shift+R" — Alt+A quedaba
        # duplicando exactamente esa misma acción. El botón sigue existiendo
        # para un usuario vidente que prefiera hacer clic con el mouse (sigue
        # activándose con Enter una vez que tiene el foco, ver
        # activar_con_enter), pero ya no tiene un acelerador de teclado
        # global — ver _on_atajo_verbalizacion (codigo == ord("R")), que
        # ahora llama directo a _on_calcular.
        self.calcular_btn = wx.Button(contenedor, label="Calcular")
        self.calcular_btn.Bind(wx.EVT_BUTTON, self._on_calcular)
        activar_con_enter(self.calcular_btn)

        # Guardar PDF: pedido explícito del usuario (2026-08-21) para poder
        # adjuntar el cálculo al expediente físico/digital del cliente — ver
        # _on_guardar_pdf/_guardar_pdf_en_ruta/_construir_datos_calculo más
        # abajo. Requiere un Calcular previo (mismo criterio que Ctrl+R para
        # la cuota redondeada), así que vive al lado del botón Calcular, no
        # en Resultados. Atajo Ctrl+P (libre en toda la app, sin colisión —
        # ver _on_atajo_verbalizacion) además del botón, mismo patrón dual
        # botón+atajo que ya tiene Calcular.
        botones_sizer = wx.BoxSizer(wx.HORIZONTAL)
        botones_sizer.Add(self.calcular_btn, 0)
        self.guardar_pdf_btn = wx.Button(contenedor, label="Guardar PDF")
        self.guardar_pdf_btn.Bind(wx.EVT_BUTTON, self._on_guardar_pdf)
        activar_con_enter(self.guardar_pdf_btn)
        botones_sizer.Add(self.guardar_pdf_btn, 0, wx.LEFT, 8)
        box.Add(botones_sizer, 0)

        return box

    def _empresa_seleccionada(self):
        """Nombre real de la empresa elegida en empresa_choice — no
        GetStringSelection(), porque el texto visible de cada ítem ahora
        incluye la tasa (pedido explícito del usuario, 2026-07-12: quiere
        que NVDA anuncie "Empresa: Tasa: X%" al navegar la lista, ver
        _texto_opcion_empresa) y no coincide con la clave que usan
        `self._convenios`/`obtener_tasa`. Se recupera por índice contra
        `_empresas_por_indice`, que _cargar_empresas mantiene en el mismo
        orden que los ítems del wx.Choice."""
        indice = self.empresa_choice.GetSelection()
        if indice == wx.NOT_FOUND or indice >= len(self._empresas_por_indice):
            return None
        return self._empresas_por_indice[indice]

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

        # La cuota redondeada (Ctrl+R) YA NO tiene una etiqueta visible acá
        # — pedido explícito del usuario (2026-08-21): es un dato que solo
        # necesita en voz, calculado igual en _calcular_y_mostrar y guardado
        # en _cuota_redondeada_usd/_cordobas, pero sin ocupar espacio ni
        # texto en Resultados. Mismo criterio que ya se usaba para el
        # nombre de empresa (Ctrl+Shift+E: se anuncia por voz sin tener su
        # propia etiqueta separada en pantalla).
        for control in (
            self.resultado_salario_bruto, self.resultado_pasivo_laboral, self.resultado_salario_neto,
            self.resultado_cuota, self.resultado_cobertura, self.resultado_endeudamiento,
        ):
            box.Add(control, 0, wx.BOTTOM, 4)

        return box

    def _actualizar_pasivo_laboral_en_vivo(self, event=None):
        """Pedido explícito del usuario (2026-07-12): el pasivo laboral no
        puede esperar a que se llene el resto del formulario y se presione
        Calcular — en su flujo de trabajo es el primer dato que necesita
        para saber si el cliente tiene margen para un crédito. Se recalcula
        solo con Fecha de ingreso + Salario bruto (Calculadora!B6/B7, las
        únicas dos celdas de las que depende — ver pasivo_laboral.py), sin
        tocar ni exigir el resto de los campos (empresa, monto, plazo...).
        La conversión a Dólares usa TIPO_CAMBIO_FIJO (ya no hay campo de
        tipo de cambio que pueda faltar).

        Atado a EVT_TEXT de fecha_ingreso_texto/salario_texto, y llamado
        también desde _on_calcular para que "Calcular" no dependa de una
        segunda fórmula: esta función es la única fuente de verdad de
        resultado_pasivo_laboral y de los valores que anuncia Ctrl+Shift+Q
        (ver _anunciar_pasivo_laboral).

        event.Skip() es OBLIGATORIO acá (bug real encontrado 2026-08-16 al
        agregar el salario neto en vivo): salario_texto tiene DOS handlers
        atados al mismo EVT_TEXT (este y _actualizar_salario_neto_en_vivo).
        wx solo sigue llamando al resto de los handlers de un mismo evento
        en la misma ventana si cada uno llama a event.Skip() — sin esto,
        el handler bindeado más recientemente "se come" el evento y el otro
        directamente deja de ejecutarse al tipear, dejando el pasivo
        laboral congelado en su último valor sin ningún error visible.
        Verificado empíricamente el orden de ejecución (LIFO: el último
        Bind() es el primero en correr) y que Skip() en AMBOS handlers es lo
        que hace que los dos terminen ejecutándose siempre, sin importar el
        orden en que se hayan bindeado."""
        if event is not None:
            event.Skip()
        fecha_ingreso_iso = parsear_fecha_ui(self.fecha_ingreso_texto.GetValue())
        try:
            salario = float(self.salario_texto.GetValue().replace(",", ""))
        except ValueError:
            salario = None

        if fecha_ingreso_iso is None or salario is None or salario <= 0:
            self._pasivo_laboral_cordobas = None
            self._pasivo_laboral_usd = None
            self.resultado_pasivo_laboral.SetLabel("Pasivo laboral: —")
            return

        pasivo_cordobas = calcular_pasivo_laboral(
            date.fromisoformat(fecha_ingreso_iso), salario, date.today()
        )

        self._pasivo_laboral_cordobas = pasivo_cordobas
        self._pasivo_laboral_usd = pasivo_cordobas / TIPO_CAMBIO_FIJO
        self.resultado_pasivo_laboral.SetLabel(
            f"Pasivo laboral: C${pasivo_cordobas:.2f} (US${self._pasivo_laboral_usd:.2f})"
        )

    def _actualizar_salario_neto_en_vivo(self, event=None):
        """Pedido explícito del usuario (2026-08-16): "el salario neto se
        recalcule dinámicamente al cambiar sus valores, sin requerir
        presionar el botón de calcular ni depender de la selección de una
        empresa" — mismo criterio y misma forma que
        _actualizar_pasivo_laboral_en_vivo (independiente, atada a su
        propio EVT_TEXT, no reemplaza ni desactiva esa otra actualización),
        pero para calcular_salario_neto_mensual() (Calculadora!B9 =
        B7-B23-B25+D9), que depende únicamente de Salario bruto mensual
        (B7) e Ingresos extra (D9) — ni de la empresa/tasa, ni de
        monto/plazo/periodicidad, así que puede quedar al día sin esperar a
        que el resto del formulario esté completo.

        Atado a EVT_TEXT de salario_texto Y extra_texto, y llamado también
        desde _on_calcular/limpiar_formulario para que "Calcular" no
        dependa de una segunda fórmula: esta función es la única fuente de
        verdad de resultado_salario_neto y de los valores que anuncia
        Ctrl+Shift+W (ver _anunciar_salario_neto) — antes ese atajo leía de
        _ultimo_resultado (solo disponible después de un Calcular
        explícito); ahora lee de acá en vivo, igual que Ctrl+Shift+Q ya lee
        de _pasivo_laboral_cordobas/_usd en vez de _ultimo_resultado.

        event.Skip() es OBLIGATORIO acá, mismo motivo que en
        _actualizar_pasivo_laboral_en_vivo (ver ese docstring): salario_texto
        tiene dos handlers atados al mismo EVT_TEXT, y sin Skip() en ambos,
        solo el bindeado más recientemente corre — esta función haber sido
        agregada SIN Skip() fue justo lo que desactivó en silencio el
        pasivo laboral en vivo al escribir el salario, exactamente lo que
        el usuario pidió evitar explícitamente ("que esta actualización no
        interfiera ni desactive el cálculo automático del pasivo laboral")."""
        if event is not None:
            event.Skip()
        try:
            salario = float(self.salario_texto.GetValue().replace(",", ""))
        except ValueError:
            salario = None
        try:
            extra = float(self.extra_texto.GetValue().replace(",", "") or 0)
        except ValueError:
            extra = None

        if salario is None or salario <= 0 or extra is None:
            self._salario_neto_cordobas = None
            self._salario_neto_usd = None
            self.resultado_salario_neto.SetLabel("Salario neto mensual: —")
            return

        salario_neto_cordobas = calcular_salario_neto_mensual(salario, extra)
        self._salario_neto_cordobas = salario_neto_cordobas
        self._salario_neto_usd = salario_neto_cordobas / TIPO_CAMBIO_FIJO
        self.resultado_salario_neto.SetLabel(
            f"Salario neto mensual: C${salario_neto_cordobas:.2f} (US${self._salario_neto_usd:.2f})"
        )

    def _leer_entradas(self):
        """Valida y convierte todos los campos de entrada. Devuelve
        (entradas_dict, None) si todo es válido, o (None, mensaje_error) si
        no — nunca lanza, para que el llamador decida cómo avisar (acá
        siempre wx.MessageBox, ver _on_calcular: es una validación que de
        otra forma NVDA no se enteraría, mismo criterio que el resto de la
        app para este tipo de error)."""
        empresa = self._empresa_seleccionada()
        if not empresa:
            return None, "Elegí una empresa convenio."
        tasa = self._convenios.get(empresa)
        if tasa is None:
            return None, f"«{empresa}» no tiene una tasa de interés configurada todavía."

        fecha_ingreso_iso = parsear_fecha_ui(self.fecha_ingreso_texto.GetValue())
        if fecha_ingreso_iso is None:
            return None, "La fecha de ingreso debe tener el formato DD/MM/AAAA."

        try:
            salario = float(self.salario_texto.GetValue().replace(",", ""))
            extra = float(self.extra_texto.GetValue().replace(",", "") or 0)
            monto = float(self.monto_texto.GetValue().replace(",", ""))
            plazo = int(self.plazo_texto.GetValue())
            deuda = float(self.deuda_texto.GetValue().replace(",", "") or 0)
        except ValueError:
            return None, "Revisá los campos numéricos: salario, ingresos extra, monto, plazo y deuda deben ser números."

        if salario <= 0 or monto <= 0 or plazo <= 0:
            return None, "Salario, monto y plazo deben ser mayores que cero."

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
            "tipo_cambio": TIPO_CAMBIO_FIJO,
            "deuda_activa_cordobas": deuda,
        }, None

    def _on_calcular(self, event):
        entradas, error = self._leer_entradas()
        if error:
            wx.MessageBox(error, "Datos incompletos", wx.OK | wx.ICON_ERROR, self)
            return
        self._calcular_y_mostrar(entradas, hablar=True)

    def _calcular_y_mostrar(self, entradas, hablar):
        """Núcleo compartido entre Calcular (botón o Ctrl+Shift+R,
        `hablar=True`: valida antes vía _leer_entradas/wx.MessageBox, avisa
        por voz y estado al terminar)
        y el refresco silencioso al cambiar de empresa (`hablar=False`, ver
        _refrescar_resultado_tras_cambio_de_tasa) — antes este cálculo vivía
        solo dentro de _on_calcular, así que un cambio de empresa sin volver
        a presionar Calcular dejaba el cuadro de Resultados mostrando el
        número calculado con la tasa de la empresa ANTERIOR, indistinguible
        de un resultado válido. Reporte real del usuario (2026-07-12),
        calificado como fallo crítico: "el sistema siempre devuelve el mismo
        resultado... no recalcula al cambiar el foco de la empresa
        seleccionada". Confirmado con una batería de pruebas de estrés
        (tests/test_calculadora_panel.py) que la tasa SÍ se leía fresca en
        cada Calcular — lo que faltaba era forzar ese Calcular, no arreglar
        la lectura de la tasa en sí."""
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

        # Se guarda para el resumen hablado de más abajo (cuota/endeudamiento)
        # y para el atajo Ctrl+Shift+R en general — ver _on_atajo_verbalizacion.
        # Ni el pasivo laboral ni el salario neto se leen de acá para mostrarse
        # en pantalla: ambos se actualizan en vivo por separado (ver
        # _actualizar_pasivo_laboral_en_vivo/_actualizar_salario_neto_en_vivo),
        # y ninguno de los dos interfiere con el otro.
        self._ultimo_resultado = resultado
        self._ultimas_entradas = entradas

        # Ya deberían estar al día por los listeners EVT_TEXT de fecha/
        # salario/extra, pero se vuelven a llamar acá para que cada una siga
        # siendo la única fuente de verdad de su propia etiqueta — evita que
        # Calcular y la actualización en vivo puedan mostrar dos números
        # calculados por dos caminos de código distintos.
        self._actualizar_pasivo_laboral_en_vivo()
        self._actualizar_salario_neto_en_vivo()

        # Calculadora!C7 = B7/C2 — conversión trivial, no vive en
        # evaluar_capacidad() porque es solo informativa (nada más la usa),
        # pero el usuario pidió explícitamente que el salario bruto en
        # dólares también quede visible en el panel.
        salario_bruto_usd = entradas["salario_bruto_cordobas"] / entradas["tipo_cambio"]

        self.resultado_salario_bruto.SetLabel(
            f"Salario bruto: C${entradas['salario_bruto_cordobas']:.2f} (US${salario_bruto_usd:.2f})"
        )
        # resultado_salario_neto NO se pisa acá con resultado.salario_neto_*:
        # _actualizar_salario_neto_en_vivo(), ya llamada arriba, es la única
        # fuente de verdad de esa etiqueta (mismo criterio que pasivo
        # laboral) — evaluar_capacidad() calcula su propio salario neto
        # internamente (misma fórmula, calcular_salario_neto_mensual) solo
        # porque nivel_endeudamiento lo necesita, no porque haga falta un
        # segundo camino para mostrarlo en pantalla.
        self.resultado_cuota.SetLabel(
            f"Cuota calculada: US${resultado.cuota_usd:.2f} (C${resultado.cuota_cordobas:.2f})"
        )
        # Redondeo hacia arriba al entero (math.ceil, no round — 19.25 debe
        # subir a 20 igual que 19.99, mismo criterio ya usado en
        # _resumen_credito para Ctrl+T/Ctrl+Shift+T), multiplicado por
        # TIPO_CAMBIO_FIJO para su equivalente en córdobas. Pedido explícito
        # del usuario (2026-08-20): Ctrl+R lee estos dos valores en voz alta
        # (ver _anunciar_cuota_redondeada) sin recalcular nada por su cuenta.
        # Sin etiqueta visible propia (ver _crear_resultados) — solo voz.
        self._cuota_redondeada_usd = math.ceil(resultado.cuota_usd)
        self._cuota_redondeada_cordobas = self._cuota_redondeada_usd * TIPO_CAMBIO_FIJO
        self.resultado_cobertura.SetLabel(
            f"Cobertura de pasivo laboral: {resultado.cobertura_pasivo_laboral:.0%}"
        )
        self.resultado_endeudamiento.SetLabel(
            f"Nivel de endeudamiento: {resultado.nivel_endeudamiento:.0%}"
        )

        if not hablar:
            # Refresco silencioso (cambio de empresa/tasa, ver
            # _refrescar_resultado_tras_cambio_de_tasa) — anunciar acá
            # convertiría cada flecha sobre empresa_choice en un anuncio
            # hablado, exactamente el tipo de ruido que ya se evita a
            # propósito para ese combo (NVDA ya lee el texto del ítem solo).
            return

        # Pedido explícito del usuario (2026-07-12): sin el pasivo laboral
        # acá — para eso ya está Ctrl+Shift+Q, este resumen se quedaba
        # demasiado largo repitiendo un dato que ya se puede consultar aparte.
        mensaje = (
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

    def _limpiar_resultados(self):
        """Vuelve el cuadro de Resultados (salvo Pasivo laboral y Salario
        neto, que se rastrean aparte y siguen siendo válidos — ninguno de
        los dos depende de empresa/tasa/monto/plazo) a su estado "todavía no
        calculado" — usado cuando cambiar de empresa deja el formulario sin
        datos suficientes para recalcular limpio (ver
        _refrescar_resultado_tras_cambio_de_tasa): mostrar el resultado de la
        empresa ANTERIOR ahí sería indistinguible de un cálculo válido para
        la empresa recién elegida. Salario neto se sumó a esta excepción
        2026-08-16, mismo día que pasó a calcularse en vivo — antes SÍ se
        pisaba acá porque solo existía como parte de un Calcular completo."""
        self._ultimo_resultado = None
        self._ultimas_entradas = None
        self._cuota_redondeada_usd = None
        self._cuota_redondeada_cordobas = None
        self.resultado_salario_bruto.SetLabel("Salario bruto: —")
        self.resultado_cuota.SetLabel("Cuota calculada: —")
        self.resultado_cobertura.SetLabel("Cobertura de pasivo laboral: —")
        self.resultado_endeudamiento.SetLabel("Nivel de endeudamiento: —")

    def _refrescar_resultado_tras_cambio_de_tasa(self):
        """Se llama cada vez que la tasa aplicable puede haber cambiado: al
        elegir otra empresa en empresa_choice, y al recargar() (ver ese
        método) cuando la MISMA empresa elegida tiene ahora una tasa distinta
        porque se editó desde Configuración mientras esta pestaña seguía
        abierta. Pedido explícito del usuario (2026-07-12), fallo calificado
        como crítico: "asegurate de que cada cambio de empresa fuerce un
        recálculo limpio con su tasa correspondiente".

        Sin datos previos calculados (_ultimo_resultado is None) no hay nada
        que quede desactualizado, así que no hace nada — evita, por ejemplo,
        que construir el panel (recargar/_cargar_empresas corre en __init__)
        dispare un cálculo antes de que el oficial haya tipeado nada.

        Si ya había un resultado y el formulario sigue teniendo datos
        válidos, se recalcula en silencio con la tasa/empresa actuales (sin
        wx.MessageBox ni voz — esto no es una acción explícita del usuario).
        Si el formulario YA NO alcanza para
        calcular (p. ej. se cambió a una empresa sin tasa configurada), se
        limpia el cuadro en vez de dejar el número de la empresa anterior
        mostrado como si siguiera vigente — eso es exactamente lo que se
        reportó como "cálculos incorrectos"."""
        if self._ultimo_resultado is None:
            return
        entradas, error = self._leer_entradas()
        if error:
            self._limpiar_resultados()
            return
        self._calcular_y_mostrar(entradas, hablar=False)

    def limpiar_formulario(self):
        """Atajo GLOBAL Ctrl+D (antes Alt+L, unificado 2026-08-16 — ver
        MainFrame._limpiar_segun_pestana_activa) cuando la pestaña activa es
        la Calculadora (pedido explícito del usuario, 2026-07-12: "debe
        limpiar absolutamente todos los campos de entrada de datos,
        manteniendo únicamente seleccionada la última empresa que se
        utilizó").

        empresa_choice NO se toca a propósito: la empresa/tasa ya resuelta
        no es un dato que el oficial tipee a mano, así que no tiene sentido
        "olvidarla" cada vez que limpia el resto. El resto de los campos
        vuelve a su estado inicial en blanco (Periodicidad a su selección
        por defecto, índice 0 "Mensual", igual que al construir el panel).

        Al vaciar fecha/salario/extra, el pasivo laboral y el salario neto en
        vivo también se limpian solos (ver _actualizar_pasivo_laboral_en_vivo/
        _actualizar_salario_neto_en_vivo, ya atados a EVT_TEXT de esos
        campos) — se llaman una vez más acá de forma explícita, mismo
        criterio que _on_calcular, para no depender únicamente del evento.
        El cuadro de Resultados también se limpia (ver _limpiar_resultados):
        un cálculo anterior ya no corresponde a un formulario recién
        vaciado.

        Reproduce el sonido de confirmación (borrar.wav) — pedido explícito
        del usuario: "la acción de borrar siempre tiene que hacer llamado
        al sonido", mismo criterio que ya usan las acciones de limpiar/
        eliminar de CasosPanel.

        Deja el foco en "Fecha de ingreso" (el primer campo del formulario)
        — pedido explícito del usuario, 2026-08-16: "que el foco del
        teclado... quede colocado automáticamente en el campo de texto de
        la Fecha de Ingreso... para facilitar el ingreso continuo de
        datos". Antes, tras limpiar, el foco se quedaba donde ya estuviera
        (normalmente sobre el propio atajo o el último control tocado), así
        que había que ir a buscar el primer campo a mano (con Tab o mouse)
        para empezar a cargar el siguiente cliente."""
        self.fecha_ingreso_texto.SetValue("")
        self.salario_texto.SetValue("")
        self.extra_texto.SetValue("0")
        self.monto_texto.SetValue("")
        self.plazo_texto.SetValue("")
        self.periodicidad_choice.SetSelection(0)
        self.deuda_texto.SetValue("0")
        self._actualizar_pasivo_laboral_en_vivo()
        self._actualizar_salario_neto_en_vivo()
        self._limpiar_resultados()
        reproducir_sonido(SONIDO_BORRAR)
        self.fecha_ingreso_texto.SetFocus()

    # ---- Atajos de verbalización pura (Ctrl+Shift+Q/W/E/T, Ctrl+T/R/P) ----

    def _on_atajo_verbalizacion(self, event):
        if event.ControlDown() and event.ShiftDown() and not event.AltDown():
            codigo = event.GetKeyCode()
            if codigo == ord("Q"):
                self._anunciar_pasivo_laboral()
                return
            if codigo == ord("W"):
                self._anunciar_salario_neto()
                return
            if codigo == ord("E"):
                self._anunciar_empresa()
                return
            if codigo == ord("R"):
                # Único atajo que dispara el cálculo (pedido explícito del
                # usuario, 2026-07-12: "no dupliques funciones... el único
                # shortcut encargado de realizar el cálculo y mostrar el
                # resultado debe ser Control+Shift+R") — antes esta tecla
                # solo anunciaba por voz un resultado ya calculado con
                # Alt+A/el botón Calcular (ver _anunciar_cuota, eliminado);
                # ahora llama directo a la misma lógica que el botón, así
                # que ya no hace falta ningún otro atajo/mnemónico para
                # calcular.
                self._on_calcular(None)
                return
            if codigo == ord("T"):
                # Ctrl+Shift+T: copia el resumen con la cuota MENSUAL — ver
                # Ctrl+T (rama de abajo, sin Shift) para la quincenal.
                self._copiar_resumen_mensual()
                return
        elif event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            if event.GetKeyCode() == ord("T"):
                # Ctrl+T: copia el resumen con la cuota QUINCENAL — pedido
                # explícito del usuario (2026-08-16), ver
                # _copiar_resumen_quincenal/_resumen_credito.
                self._copiar_resumen_quincenal()
                return
            if event.GetKeyCode() == ord("R"):
                # Ctrl+R (sin Shift, "lo más parecido" a Ctrl+Shift+R —
                # pedido explícito del usuario, 2026-08-20): a nivel global
                # Ctrl+R no hace nada en esta pestaña (enfoca la lista de
                # resultados en Casos/Historial de Créditos, que acá no
                # existe — ver MainFrame._enfocar_resultados_segun_pestana_activa),
                # así que reutilizarlo acá no pisa ningún otro atajo.
                self._anunciar_cuota_redondeada()
                return
            if event.GetKeyCode() == ord("P"):
                # Ctrl+P: guardar el cálculo en PDF, mismo atajo dual
                # botón+teclado que el resto de las acciones de este panel —
                # ver _on_guardar_pdf. Libre en toda la app (ningún otro
                # panel/menú usa Ctrl+P), pedido explícito del usuario
                # (2026-08-21) para poder adjuntarlo al expediente del
                # cliente.
                self._on_guardar_pdf(None)
                return
        elif (
            not event.ControlDown() and not event.ShiftDown() and not event.AltDown()
            and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE)
            and wx.Window.FindFocus() is self.empresa_choice
        ):
            # Pedido explícito del usuario (2026-07-12): mientras se navega
            # empresa_choice con las flechas, NVDA ya anuncia el texto de
            # cada ítem solo (nombre + tasa, ver _texto_opcion_empresa) — no
            # se agrega ningún anuncio propio ahí, para no ser repetitivo.
            # "Seleccionada" se habla SOLO al confirmar con Enter/Espacio,
            # mismo mecanismo EVT_CHAR_HOOK que ya usan filtro_alerta_choice
            # (casos_panel.py) y agentes_choice (configuracion_panel.py) para
            # interceptar Enter antes de que el combo nativo se lo trague.
            self._anunciar_empresa_confirmada()
            return
        event.Skip()

    # ---- Copiado rápido de resumen (Ctrl+T / Ctrl+Shift+T) -----------------
    # Pedido explícito del usuario (2026-08-16): copiar al portapapeles un
    # resumen de la operación calculada, listo para pegar en un mensaje al
    # cliente, sin tener que armarlo a mano ni tabular hasta los resultados.

    def _resumen_credito(self, periodicidad, etiqueta_periodicidad):
        """Arma el texto de resumen para Ctrl+T/Ctrl+Shift+T. Reutiliza
        _leer_entradas() para exigir el mismo conjunto completo de datos que
        ya exige "Calcular" (empresa con tasa configurada, fecha de ingreso,
        salario, monto, plazo) — sin eso no hay cuota que copiar, mismo
        mensaje de error ("Datos incompletos") que ya usa _on_calcular.

        La cuota SIEMPRE se calcula acá con `periodicidad` forzada por el
        llamador, sin importar qué tenga elegido periodicidad_choice en ese
        momento — así Ctrl+T da la cuota quincenal y Ctrl+Shift+T la
        mensual sin que el oficial tenga que cambiar el combo y volver a
        calcular para conseguir la otra variante. Monto va con dos
        decimales y sin separador de miles, mismo criterio ya establecido
        para toda salida de texto de este panel (ver "No thousands
        separator..." en CLAUDE.md); plazo va tal cual, en meses enteros.

        **La cuota copiada, y SOLO ella, se redondea hacia arriba a un
        entero** (`math.ceil`, no `round`) — pedido explícito del usuario
        (2026-08-20): "de 21.01 pase a 22, de 21.30 pase a 22... no importa
        cual sea siempre tiene que pasarlo arriba", y aclaró que es
        exclusivo de este texto copiado — el cálculo real
        (`evaluar_capacidad()`), los labels de "Resultados" en pantalla y
        lo que anuncia Ctrl+Shift+R siguen mostrando `resultado.cuota_usd`
        exacto, con decimales, sin tocar. No usar `round()` acá: 21.01
        debe subir a 22 igual que 21.99, algo que un redondeo normal no
        haría.

        Devuelve None (sin armar ningún texto) si los datos no alcanzan —
        el llamador ya se encarga de avisar el error, acá no hace falta
        repetirlo."""
        entradas, error = self._leer_entradas()
        if error:
            wx.MessageBox(error, "Datos incompletos", wx.OK | wx.ICON_ERROR, self)
            return None

        resultado = evaluar_capacidad(
            fecha_ingreso=entradas["fecha_ingreso"],
            salario_bruto_mensual_cordobas=entradas["salario_bruto_cordobas"],
            ingresos_extra_cordobas=entradas["ingresos_extra_cordobas"],
            monto_credito_usd=entradas["monto_credito_usd"],
            plazo_meses=entradas["plazo_meses"],
            periodicidad=periodicidad,
            tasa_anual=entradas["tasa_interes"],
            tipo_cambio=entradas["tipo_cambio"],
            deuda_activa_cordobas=entradas["deuda_activa_cordobas"],
        )

        cuota_redondeada = math.ceil(resultado.cuota_usd)

        # Formato exacto pedido por el usuario, incluida la línea de plazo
        # con un espacio final antes del salto de línea — no es un error de
        # tipeo, se preserva tal cual se pidió.
        return (
            f"monto de USD ${entradas['monto_credito_usd']:.2f}\n"
            f"plazo de {entradas['plazo_meses']} meses \n"
            f"cuota {etiqueta_periodicidad} aproximada de USD ${cuota_redondeada}"
        )

    def _copiar_al_portapapeles(self, texto):
        """wx.TheClipboard.Open() puede fallar de forma transitoria en
        Windows si otro proceso (o incluso otra prueba automatizada) tiene
        el portapapeles abierto en ese instante exacto — comprobado
        empíricamente: la batería de pruebas de este panel falló de forma
        intermitente por esto mismo antes de agregar el reintento. Windows
        no da ninguna garantía de que un solo intento alcance; unos pocos
        reintentos cortos son la práctica estándar recomendada para
        OpenClipboard. Recién si los 5 intentos fallan se avisa el error de
        verdad — un fallo genuino y persistente (no uno transitorio)."""
        for _intento in range(5):
            if wx.TheClipboard.Open():
                break
            wx.MilliSleep(20)
        else:
            wx.MessageBox(
                "No se pudo acceder al portapapeles. Intentá de nuevo.",
                "Error al copiar", wx.OK | wx.ICON_ERROR, self,
            )
            return False
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(texto))
        finally:
            wx.TheClipboard.Close()
        return True

    def _copiar_resumen_quincenal(self):
        """Ctrl+T: copia al portapapeles el resumen de la operación
        calculada con la cuota QUINCENAL, y anuncia por voz que se copió
        (pedido explícito del usuario: "emite un anuncio por voz... del
        texto formateado que fue copiado al portapapeles") — mismo
        mecanismo anunciar_voz_nvda() que ya usan Ctrl+Shift+Q/W/E, no roba
        el foco ni tabula a ningún control."""
        texto = self._resumen_credito(PERIODICIDAD_QUINCENAL, "quincenal")
        if texto is None:
            return
        if not self._copiar_al_portapapeles(texto):
            return
        anunciar_voz_nvda("Resumen quincenal copiado al portapapeles.")

    def _copiar_resumen_mensual(self):
        """Ctrl+Shift+T: igual que _copiar_resumen_quincenal, pero con la
        cuota MENSUAL."""
        texto = self._resumen_credito(PERIODICIDAD_MENSUAL, "mensual")
        if texto is None:
            return
        if not self._copiar_al_portapapeles(texto):
            return
        anunciar_voz_nvda("Resumen mensual copiado al portapapeles.")

    def _anunciar_pasivo_laboral(self):
        """Ctrl+Shift+Q: habla el pasivo laboral (el mismo número que está en
        el cuadro "Resultados", actualizado en vivo — ver
        _actualizar_pasivo_laboral_en_vivo) sin mover el foco ni tabular
        hasta ahí — ver anunciar_voz_nvda, que llama directo a la API de
        NVDA para esto en vez de depender de que el usuario navegue hasta
        el control."""
        if self._pasivo_laboral_cordobas is None:
            anunciar_voz_nvda("Todavía no se puede calcular el pasivo laboral: falta la fecha de ingreso o el salario.")
            return
        anunciar_voz_nvda(
            f"Pasivo laboral: {self._pasivo_laboral_usd:.2f} dólares y "
            f"{self._pasivo_laboral_cordobas:.2f} córdobas."
        )

    def _anunciar_cuota_redondeada(self):
        """Ctrl+R: habla la cuota redondeada hacia arriba al entero (ej. de
        19.25 a 20 dólares) multiplicada por TIPO_CAMBIO_FIJO — el mismo
        número que está en "Cuota redondeada" dentro de Resultados,
        calculado junto con el resto en _calcular_y_mostrar. A diferencia de
        Ctrl+Shift+Q/W (pasivo laboral/salario neto, que se recalculan en
        vivo sin depender de Calcular), este valor depende de un Calcular
        previo (Ctrl+Shift+R o el botón), así que si todavía no hay uno
        avisa por voz en vez de fallar en silencio."""
        if self._cuota_redondeada_usd is None:
            anunciar_voz_nvda(
                "Todavía no se ha calculado ninguna cuota. "
                "Presioná Control, Shift, R primero."
            )
            return
        anunciar_voz_nvda(
            f"Cuota redondeada: {self._cuota_redondeada_usd} dólares, "
            f"equivalentes a {self._cuota_redondeada_cordobas:.2f} córdobas."
        )

    # ---- Guardar cálculo en PDF (Ctrl+P / botón "Guardar PDF") ------------
    # Pedido explícito del usuario (2026-08-21): poder adjuntar el cálculo
    # ya hecho al expediente físico/digital de un cliente. La Calculadora
    # sigue sin guardar nada en la base de datos (ver la clase) — esto es
    # exclusivamente un archivo que el oficial elige dónde guardar cada vez.

    def _construir_datos_calculo(self):
        """Arma la lista ordenada de 14 campos (8 de entrada + 6 de
        resultado) que va al PDF — exactamente los que el usuario pidió que
        quedaran visibles en pantalla (ver CLAUDE.md, sección Calculadora),
        ni uno más: nunca un aviso transitorio como "copiado al
        portapapeles" ni datos que solo existen por voz (Cuota redondeada,
        Tasa). Usa _ultimas_entradas/_ultimo_resultado (el snapshot del
        último Calcular, ver _calcular_y_mostrar) en vez de releer los
        controles en vivo — si el oficial tipeó algo después sin volver a
        calcular, el PDF debe seguir reflejando el cálculo real, no una
        mezcla de datos viejos y nuevos. Solo tiene sentido llamarla con un
        cálculo ya hecho (ver _on_guardar_pdf, que lo garantiza antes)."""
        entradas = self._ultimas_entradas
        resultado = self._ultimo_resultado
        salario_bruto_usd = entradas["salario_bruto_cordobas"] / entradas["tipo_cambio"]

        return [
            ("Empresa convenio", entradas["empresa_convenio"]),
            ("Fecha de ingreso a la empresa", entradas["fecha_ingreso"].strftime("%d/%m/%Y")),
            ("Salario bruto mensual", f"C${entradas['salario_bruto_cordobas']:.2f}"),
            ("Ingresos extra", f"C${entradas['ingresos_extra_cordobas']:.2f}"),
            ("Monto del crédito", f"US${entradas['monto_credito_usd']:.2f}"),
            ("Plazo", f"{entradas['plazo_meses']} meses"),
            ("Periodicidad", entradas["periodicidad"]),
            ("Cuotas de deudas activas externas", f"C${entradas['deuda_activa_cordobas']:.2f}"),
            (
                "Salario bruto (sin deducciones)",
                f"C${entradas['salario_bruto_cordobas']:.2f} (US${salario_bruto_usd:.2f})",
            ),
            (
                "Salario neto (con deducciones)",
                f"C${self._salario_neto_cordobas:.2f} (US${self._salario_neto_usd:.2f})",
            ),
            (
                "Pasivo laboral (respaldo del cliente)",
                f"C${self._pasivo_laboral_cordobas:.2f} (US${self._pasivo_laboral_usd:.2f})",
            ),
            ("Cuota calculada", f"US${resultado.cuota_usd:.2f} (C${resultado.cuota_cordobas:.2f})"),
            ("Cobertura de pasivo laboral", f"{resultado.cobertura_pasivo_laboral:.0%}"),
            ("Nivel de endeudamiento", f"{resultado.nivel_endeudamiento:.0%}"),
        ]

    def _on_guardar_pdf(self, event):
        """Ctrl+P / botón "Guardar PDF": exige un Calcular previo (mismo
        criterio que Ctrl+R para la cuota redondeada — sin eso no hay nada
        coherente que exportar), después pregunta dónde guardar con
        wx.FileDialog nativo (excepción ya aceptada a "sin popups", igual
        que la importación de Excel) con un nombre sugerido por fecha y
        hora del cálculo (pedido explícito del usuario, 2026-08-21) que el
        oficial puede sobrescribir ahí mismo. El trabajo real vive en
        _guardar_pdf_en_ruta, separado a propósito para poder probarlo sin
        el diálogo real (que es modal e interactivo, no se puede invocar en
        una prueba automatizada — mismo patrón que _seleccionar_archivo_
        simulado en tests/test_configuracion_creditos.py)."""
        if self._ultimo_resultado is None:
            wx.MessageBox(
                "Todavía no hay ningún cálculo para guardar. Presioná Calcular primero.",
                "Nada que guardar", wx.OK | wx.ICON_ERROR, self,
            )
            return

        ahora = datetime.now()
        nombre_sugerido = f"Calculo_credito_{ahora.strftime('%d-%m-%Y_%H%M')}.pdf"
        with wx.FileDialog(
            self, "Guardar cálculo como PDF",
            defaultFile=nombre_sugerido, wildcard="Archivos PDF (*.pdf)|*.pdf",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            ruta = dialogo.GetPath()

        self._guardar_pdf_en_ruta(ruta, fecha_hora=ahora)

    def _guardar_pdf_en_ruta(self, ruta, fecha_hora=None):
        try:
            generar_pdf_calculo(ruta, self._construir_datos_calculo(), fecha_hora=fecha_hora)
        except OSError as exc:
            wx.MessageBox(
                f"No se pudo guardar el PDF: {exc}", "Error al guardar", wx.OK | wx.ICON_ERROR, self,
            )
            return
        mensaje = f"PDF guardado en: {ruta}"
        self.GetTopLevelParent().SetStatusText(mensaje)
        anunciar_voz_nvda(mensaje)

    def _anunciar_salario_neto(self):
        """Ctrl+Shift+W: igual que _anunciar_pasivo_laboral (mismo patrón,
        misma fuente de datos en vivo) pero para el salario con deducciones
        aplicadas (INSS + IR + ingresos extra). Hasta 2026-08-16 leía de
        _ultimo_resultado (solo disponible después de Ctrl+Shift+R/Calcular)
        — pedido explícito del usuario ese día: "permite que la lectura del
        salario neto funcione directamente en vivo (similar a como ya opera
        Ctrl+Shift+Q para el pasivo laboral)" — ver
        _actualizar_salario_neto_en_vivo. Ahora lee de
        _salario_neto_cordobas/_usd, sin depender de que se haya calculado
        antes."""
        if self._salario_neto_cordobas is None:
            anunciar_voz_nvda("Todavía no se puede calcular el salario con deducciones: falta el salario bruto.")
            return
        anunciar_voz_nvda(
            f"Salario con deducciones: {self._salario_neto_usd:.2f} dólares y "
            f"{self._salario_neto_cordobas:.2f} córdobas."
        )

    def _anunciar_empresa(self):
        """Ctrl+Shift+E: habla SOLO el nombre de la empresa convenio
        actualmente elegida — sin la tasa, a propósito (pedido explícito del
        usuario, 2026-07-12: "ese dato ya lo revisé en la lista", ver
        _texto_opcion_empresa, que ya la anuncia al navegar el combo)."""
        empresa = self._empresa_seleccionada()
        if empresa is None:
            anunciar_voz_nvda("Todavía no se eligió ninguna empresa convenio.")
            return
        anunciar_voz_nvda(f"Empresa: {empresa}.")

    def _anunciar_empresa_confirmada(self):
        """Enter/Espacio sobre empresa_choice: confirmación mínima, a
        propósito — pedido explícito del usuario (2026-07-12) tras probar
        la versión anterior (que repetía la tasa) y encontrarla "demasiada
        información... mucho ruido". Ahora es solo "Seleccionada {empresa}",
        sin tasa — la tasa ya se escuchó al navegar la lista (ver
        _texto_opcion_empresa) y no hace falta repetirla acá."""
        empresa = self._empresa_seleccionada()
        if empresa is None:
            return
        anunciar_voz_nvda(f"Seleccionada {empresa}")

    # ---- Empresas / tasas por convenio ---------------------------------
    # Solo lectura acá — pedido explícito del usuario (2026-07-12): editar
    # tasas, agregar empresas o cambiar el tipo de cambio es trabajo futuro
    # de un módulo aparte en Configuración, todavía no construido. Este
    # panel solo consume `convenio_tasa` (vía listar_convenios) para poblar
    # el wx.Choice de Empresa; no la edita.

    def recargar(self):
        """Se llama al entrar a esta pestaña (ver MainFrame._on_cambiar_pestana)
        para que una tasa actualizada en otro lado (hoy: directo en la base;
        más adelante, desde el futuro módulo de Configuración) se refleje sin
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

        empresa_previa = self._empresa_seleccionada()

        self._convenios = dict(convenios)
        self._empresas_por_indice = [empresa for empresa, _tasa in convenios]
        self.empresa_choice.Set([_texto_opcion_empresa(empresa, tasa) for empresa, tasa in convenios])

        if empresa_previa and empresa_previa in self._empresas_por_indice:
            self.empresa_choice.SetSelection(self._empresas_por_indice.index(empresa_previa))
            self._refrescar_resultado_tras_cambio_de_tasa()
        elif empresa_previa:
            # La empresa que estaba elegida se borró (Configuración >
            # "Eliminar empresa") mientras esta pestaña seguía abierta con un
            # resultado ya calculado para ella — mismo criterio que un
            # cambio de tasa: no dejar ese número mostrado como si siguiera
            # vigente para una empresa que ya no existe.
            self._limpiar_resultados()
