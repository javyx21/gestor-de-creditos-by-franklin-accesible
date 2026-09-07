import wx

from gestor_credito.ui.accesibilidad import anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.logo import AppLogo
from gestor_credito.ui.sonido import SONIDO_BORRAR, reproducir_sonido

# Mismo valor que TIPO_CAMBIO_FIJO en calculadora_panel.py (Calculadora de
# Crédito) — pedido explícito del usuario (2026-09-07): esta calculadora
# genérica necesita el mismo tipo de cambio para su atajo de multiplicar por
# el dólar (Ctrl+Shift+Q). Constante propia, no importada de ese módulo, para
# no crear una dependencia entre dos paneles por lo demás completamente
# independientes (mismo criterio de independencia entre Calculadora de
# Crédito e Historial de Créditos).
TIPO_CAMBIO_FIJO = 36.6243


def _formatear_numero(valor):
    """Sin decimales si el resultado es un entero exacto (54+25=79, no
    79.00), con 2 decimales si no — mismo criterio ya usado en el resto de
    la app para no mostrar/anunciar ceros de más."""
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.2f}"


class CalculadoraSimplePanel(wx.Panel):
    """Calculadora aritmética genérica — pedido explícito del usuario
    (2026-09-07), CUARTA pestaña del notebook (Ctrl+4), completamente
    independiente de "Calculadora de Crédito" (esa sigue siendo la Ctrl+2,
    sin cambios). No calcula nada del dominio de créditos: solo suma, resta,
    multiplica, divide, y multiplica por el tipo de cambio fijo.

    Flujo descrito por el usuario, confirmado explícitamente antes de
    implementar: un solo cuadro de edición. Se escribe un número y se
    presiona Enter (se guarda como operando y el cuadro se limpia); se
    escribe el segundo número (presionar Enter ahí es indiferente — el
    usuario confirmó explícitamente que funciona igual si se ejecuta el
    atajo de operación directo sobre el cuadro sin confirmar con Enter, ver
    _operandos_binarios); luego se presiona el atajo de la operación
    deseada, que calcula y anuncia el resultado por voz.

    Atajos (todos Ctrl+Shift+<letra>, para no chocar con Ctrl+D — el atajo
    GLOBAL único de "limpiar" de toda la app, ver MainFrame):
    - Ctrl+Shift+S: suma
    - Ctrl+Shift+R: resta
    - Ctrl+Shift+M: multiplica
    - Ctrl+Shift+D: divide
    - Ctrl+Shift+Q: multiplica el operando actual (UNARIO, uno solo) por el
      tipo de cambio fijo (36.6243) — a diferencia de las cuatro anteriores,
      que son binarias
    """

    def __init__(self, parent):
        super().__init__(parent)

        # Primer/segundo operando confirmados con Enter — ver _on_enter. Un
        # atajo de operación binaria puede completar el segundo operando
        # leyendo directo el cuadro sin que se haya confirmado con Enter,
        # ver _operandos_binarios.
        self._primer_operando = None
        self._segundo_operando = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Calculadora")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        entrada_label = wx.StaticText(self, label="Número:")
        self.entrada = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        nombre_accesible(self.entrada, "Número")
        self.entrada.Bind(wx.EVT_TEXT_ENTER, self._on_enter)
        entrada_sizer = wx.BoxSizer(wx.HORIZONTAL)
        entrada_sizer.Add(entrada_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        entrada_sizer.Add(self.entrada, 1, wx.EXPAND)
        sizer.Add(entrada_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.resultado_label = wx.StaticText(self, label="Resultado: —")
        sizer.Add(self.resultado_label, 0, wx.ALL, 8)

        # Mismo mecanismo EVT_CHAR_HOOK a nivel de panel que ya usa
        # CalculadoraPanel (Calculadora de Crédito) para sus atajos
        # Ctrl+Shift+Q/W/E/R/T — sin chequeo de FindFocus() a propósito:
        # debe funcionar sin importar qué control del panel tenga el foco.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_atajo)

        self.SetSizer(sizer)

    def recargar(self):
        """Sin estado que dependa de la base de datos ni de otra pestaña —
        no hace falta recargar nada. Existe solo para que
        MainFrame._on_cambiar_pestana/_abrir_dialogo puedan llamarla sin
        chequear de qué tipo es cada página, mismo patrón que el resto de
        las pestañas del notebook."""
        pass

    def limpiar_formulario(self):
        """Atajo GLOBAL Ctrl+D (ver MainFrame._limpiar_segun_pestana_activa)
        cuando esta es la pestaña activa — mismo nombre de método que
        CalculadoraPanel.limpiar_formulario(), mismo criterio de "único
        gesto global para limpiar" documentado en CLAUDE.md. Reproduce
        borrar.wav, mismo criterio que el resto de la app."""
        self.entrada.SetValue("")
        self._primer_operando = None
        self._segundo_operando = None
        self.resultado_label.SetLabel("Resultado: —")
        reproducir_sonido(SONIDO_BORRAR)
        self.entrada.SetFocus()

    # ---- Captura del operando actual del cuadro ---------------------------

    def _leer_operando_del_cuadro(self):
        """None si el cuadro está vacío (nada tipeado todavía) o si el texto
        no es un número válido (en ese caso ya avisó con wx.MessageBox —
        error de validación que de otra forma NVDA no se enteraría, mismo
        criterio que el resto de la app); el valor numérico si es válido."""
        texto = self.entrada.GetValue().strip()
        if not texto:
            return None
        try:
            return float(texto.replace(",", ""))
        except ValueError:
            wx.MessageBox(
                f"«{texto}» no es un número válido.", "Valor inválido",
                wx.OK | wx.ICON_ERROR, self,
            )
            return None

    def _on_enter(self, event):
        """Enter confirma el número tipeado como operando y limpia el
        cuadro para el siguiente — ver docstring de la clase. Si ya hay dos
        operandos confirmados y se presiona Enter de nuevo, el número más
        reciente reemplaza al segundo operando."""
        valor = self._leer_operando_del_cuadro()
        if valor is None:
            return
        if self._primer_operando is None:
            self._primer_operando = valor
        else:
            self._segundo_operando = valor
        self.entrada.SetValue("")

    # ---- Operaciones --------------------------------------------------

    def _operandos_binarios(self):
        """Devuelve (a, b) para una operación de dos operandos, o None si
        todavía no hay suficientes datos (y ya avisó el error por
        wx.MessageBox). Prioriza el par primer/segundo operando ya
        confirmado por Enter; si el segundo todavía no se confirmó, usa lo
        que haya sin confirmar en el cuadro como segundo operando — pedido
        explícito del usuario: "es indiferente si le doy enter o no al
        final"."""
        if self._primer_operando is None:
            wx.MessageBox(
                "Escribí el primer número y presioná Enter antes de operar.",
                "Faltan datos", wx.OK | wx.ICON_ERROR, self,
            )
            return None
        if self._segundo_operando is not None:
            return self._primer_operando, self._segundo_operando
        segundo = self._leer_operando_del_cuadro()
        if segundo is None:
            if self.entrada.GetValue().strip():
                # Ya avisó por wx.MessageBox en _leer_operando_del_cuadro
                # (texto inválido) — no repetir el aviso.
                return None
            wx.MessageBox(
                "Escribí el segundo número antes de operar.",
                "Faltan datos", wx.OK | wx.ICON_ERROR, self,
            )
            return None
        return self._primer_operando, segundo

    def _operar(self, operacion):
        operandos = self._operandos_binarios()
        if operandos is None:
            return
        a, b = operandos
        self._mostrar_resultado(operacion(a, b))

    def _dividir(self):
        operandos = self._operandos_binarios()
        if operandos is None:
            return
        a, b = operandos
        if b == 0:
            wx.MessageBox("No se puede dividir entre cero.", "Error", wx.OK | wx.ICON_ERROR, self)
            return
        self._mostrar_resultado(a / b)

    def _multiplicar_por_dolar(self):
        """Ctrl+Shift+Q: UNARIO — un solo operando (el del cuadro, o el
        primer operando ya confirmado si el cuadro está vacío) × el tipo de
        cambio fijo, a diferencia de suma/resta/multiplica/divide, que son
        binarias. Pedido explícito del usuario, confirmado antes de
        implementar."""
        operando = self._leer_operando_del_cuadro()
        if operando is None:
            if self.entrada.GetValue().strip():
                return  # ya avisó el error de número inválido
            if self._primer_operando is None:
                wx.MessageBox(
                    "Escribí un número antes de multiplicar por el dólar.",
                    "Faltan datos", wx.OK | wx.ICON_ERROR, self,
                )
                return
            operando = self._primer_operando
        self._mostrar_resultado(operando * TIPO_CAMBIO_FIJO)

    def _mostrar_resultado(self, valor):
        """Único punto de salida de cualquier operación: muestra el
        resultado en pantalla, lo anuncia por voz (pedido explícito del
        usuario: "...tiene que sumar y darme el resultado"), y reinicia el
        estado (cuadro y operandos) para la siguiente operación."""
        texto = _formatear_numero(valor)
        self.resultado_label.SetLabel(f"Resultado: {texto}")
        anunciar_voz_nvda(f"Resultado: {texto}.")
        self.entrada.SetValue("")
        self._primer_operando = None
        self._segundo_operando = None

    # ---- Atajos de teclado (Ctrl+Shift+Q/S/R/D/M) --------------------------

    def _on_atajo(self, event):
        if event.ControlDown() and event.ShiftDown() and not event.AltDown():
            codigo = event.GetKeyCode()
            if codigo == ord("Q"):
                self._multiplicar_por_dolar()
                return
            if codigo == ord("S"):
                self._operar(lambda a, b: a + b)
                return
            if codigo == ord("R"):
                self._operar(lambda a, b: a - b)
                return
            if codigo == ord("D"):
                self._dividir()
                return
            if codigo == ord("M"):
                self._operar(lambda a, b: a * b)
                return
        event.Skip()
