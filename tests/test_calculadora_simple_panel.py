"""Pruebas de CalculadoraSimplePanel — calculadora aritmética genérica,
cuarta pestaña del notebook (Ctrl+4), pedido explícito del usuario
(2026-09-07). Sin base de datos ni dependencia de otra pestaña, así que estas
pruebas construyen el panel solo (sin fixture `conn`), a diferencia de
test_calculadora_panel.py."""

import wx
import pytest

from gestor_credito.ui.calculadora_simple_panel import TIPO_CAMBIO_FIJO, CalculadoraSimplePanel


@pytest.fixture(scope="module")
def app():
    return wx.App()


@pytest.fixture
def calc(app):
    frame = wx.Frame(None)
    notebook = wx.Notebook(frame)
    panel = CalculadoraSimplePanel(notebook)
    notebook.AddPage(panel, "Calculadora")
    yield panel
    frame.Destroy()


def _escribir_y_enter(panel, texto):
    panel.entrada.SetValue(texto)
    panel._on_enter(None)


# ---- Flujo con Enter en ambos números --------------------------------------

def test_suma_con_enter_en_ambos_numeros(calc, monkeypatch):
    voces = []
    monkeypatch.setattr(
        "gestor_credito.ui.calculadora_simple_panel.anunciar_voz_nvda",
        lambda texto: voces.append(texto),
    )
    _escribir_y_enter(calc, "54")
    _escribir_y_enter(calc, "25")

    calc._operar(lambda a, b: a + b)

    assert calc.resultado_label.GetLabel() == "Resultado: 79"
    assert voces == ["Resultado: 79."]
    # Reinicia el estado para la siguiente operación.
    assert calc._primer_operando is None
    assert calc._segundo_operando is None
    assert calc.entrada.GetValue() == ""


# ---- Flujo sin Enter en el segundo número (pedido explícito del usuario:
# "es indiferente si le doy enter o no al final") -----------------------------

def test_suma_sin_enter_en_el_segundo_numero(calc, monkeypatch):
    voces = []
    monkeypatch.setattr(
        "gestor_credito.ui.calculadora_simple_panel.anunciar_voz_nvda",
        lambda texto: voces.append(texto),
    )
    _escribir_y_enter(calc, "54")
    calc.entrada.SetValue("25")  # sin Enter

    calc._operar(lambda a, b: a + b)

    assert calc.resultado_label.GetLabel() == "Resultado: 79"
    assert voces == ["Resultado: 79."]


def test_resta_sin_enter_en_el_segundo_numero(calc):
    _escribir_y_enter(calc, "54")
    calc.entrada.SetValue("25")

    calc._operar(lambda a, b: a - b)

    assert calc.resultado_label.GetLabel() == "Resultado: 29"


def test_multiplica_sin_enter_en_el_segundo_numero(calc):
    _escribir_y_enter(calc, "6")
    calc.entrada.SetValue("7")

    calc._operar(lambda a, b: a * b)

    assert calc.resultado_label.GetLabel() == "Resultado: 42"


def test_divide_sin_enter_en_el_segundo_numero(calc):
    _escribir_y_enter(calc, "10")
    calc.entrada.SetValue("4")

    calc._dividir()

    assert calc.resultado_label.GetLabel() == "Resultado: 2.50"


def test_dividir_entre_cero_avisa_con_messagebox_y_no_calcula(calc, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: llamadas.append(a) or wx.OK)
    _escribir_y_enter(calc, "10")
    calc.entrada.SetValue("0")

    calc._dividir()

    assert len(llamadas) == 1
    assert calc.resultado_label.GetLabel() == "Resultado: —"


# ---- Ctrl+Shift+Q: multiplicar por el dólar, UNARIO ------------------------

def test_multiplicar_por_dolar_usa_el_cuadro_sin_necesitar_enter(calc, monkeypatch):
    voces = []
    monkeypatch.setattr(
        "gestor_credito.ui.calculadora_simple_panel.anunciar_voz_nvda",
        lambda texto: voces.append(texto),
    )
    calc.entrada.SetValue("10")  # sin Enter, sin segundo operando

    calc._multiplicar_por_dolar()

    esperado = f"{10 * TIPO_CAMBIO_FIJO:.2f}"
    assert calc.resultado_label.GetLabel() == f"Resultado: {esperado}"
    assert voces == [f"Resultado: {esperado}."]


def test_multiplicar_por_dolar_usa_el_primer_operando_confirmado_si_el_cuadro_esta_vacio(calc):
    _escribir_y_enter(calc, "10")  # cuadro queda vacío tras el Enter

    calc._multiplicar_por_dolar()

    esperado = f"{10 * TIPO_CAMBIO_FIJO:.2f}"
    assert calc.resultado_label.GetLabel() == f"Resultado: {esperado}"


def test_multiplicar_por_dolar_sin_ningun_numero_avisa_con_messagebox(calc, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: llamadas.append(a) or wx.OK)

    calc._multiplicar_por_dolar()

    assert len(llamadas) == 1
    assert calc.resultado_label.GetLabel() == "Resultado: —"


# ---- Datos insuficientes / inválidos ---------------------------------------

def test_operar_sin_ningun_numero_avisa_con_messagebox(calc, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: llamadas.append(a) or wx.OK)

    calc._operar(lambda a, b: a + b)

    assert len(llamadas) == 1
    assert calc.resultado_label.GetLabel() == "Resultado: —"


def test_operar_con_solo_el_primer_numero_avisa_con_messagebox(calc, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: llamadas.append(a) or wx.OK)
    _escribir_y_enter(calc, "54")

    calc._operar(lambda a, b: a + b)

    assert len(llamadas) == 1
    assert calc.resultado_label.GetLabel() == "Resultado: —"


def test_enter_con_texto_invalido_avisa_con_messagebox_y_no_confirma_operando(calc, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: llamadas.append(a) or wx.OK)

    _escribir_y_enter(calc, "abc")

    assert len(llamadas) == 1
    assert calc._primer_operando is None
    # El texto inválido no se borra, para que se pueda corregir.
    assert calc.entrada.GetValue() == "abc"


# ---- Ctrl+D (limpiar, atajo global dispatchado desde MainFrame) -----------

def test_limpiar_formulario_reinicia_todo(calc):
    _escribir_y_enter(calc, "54")
    calc.entrada.SetValue("25")
    calc._operar(lambda a, b: a + b)

    _escribir_y_enter(calc, "1")
    calc.entrada.SetValue("2")

    calc.limpiar_formulario()

    assert calc.entrada.GetValue() == ""
    assert calc._primer_operando is None
    assert calc._segundo_operando is None
    assert calc.resultado_label.GetLabel() == "Resultado: —"


# ---- Atajos de teclado (EVT_CHAR_HOOK) -------------------------------------

def _evento_char_hook(codigo, ctrl=True, shift=True, alt=False):
    evento = wx.KeyEvent(wx.EVT_CHAR_HOOK.typeId)
    evento.SetControlDown(ctrl)
    evento.SetShiftDown(shift)
    evento.SetAltDown(alt)
    evento.SetKeyCode(codigo)
    return evento


def test_atajo_ctrl_shift_s_suma(calc):
    _escribir_y_enter(calc, "3")
    _escribir_y_enter(calc, "4")

    calc._on_atajo(_evento_char_hook(ord("S")))

    assert calc.resultado_label.GetLabel() == "Resultado: 7"


def test_atajo_ctrl_shift_m_multiplica(calc):
    _escribir_y_enter(calc, "3")
    _escribir_y_enter(calc, "4")

    calc._on_atajo(_evento_char_hook(ord("M")))

    assert calc.resultado_label.GetLabel() == "Resultado: 12"


def test_atajo_ctrl_shift_d_divide(calc):
    _escribir_y_enter(calc, "8")
    _escribir_y_enter(calc, "4")

    calc._on_atajo(_evento_char_hook(ord("D")))

    assert calc.resultado_label.GetLabel() == "Resultado: 2"


def test_atajo_ctrl_shift_q_multiplica_por_dolar(calc):
    _escribir_y_enter(calc, "2")

    calc._on_atajo(_evento_char_hook(ord("Q")))

    esperado = f"{2 * TIPO_CAMBIO_FIJO:.2f}"
    assert calc.resultado_label.GetLabel() == f"Resultado: {esperado}"
