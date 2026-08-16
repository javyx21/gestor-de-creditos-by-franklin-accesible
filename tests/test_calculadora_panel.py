"""Batería de pruebas de estrés sobre CalculadoraPanel y su interacción con
ConfiguracionPanel — reporte real del usuario (2026-07-12), calificado como
"fallo crítico que impide el paso a producción":

1. "Falta de actualización en caliente": tras editar una tasa en
   Configuración, la Calculadora sigue mostrando la tasa anterior.
2. "Cálculos congelados e incorrectos": alternar entre empresas con datos
   precargados en el formulario siempre devuelve el mismo resultado, como si
   no se refrescaran las variables internas al cambiar de empresa.

Estas pruebas construyen paneles reales (no mocks) contra una base de datos
temporal, disparan los eventos nativos de wx tal cual los generaría un
usuario real (EVT_CHOICE al elegir una empresa, no solo SetSelection()), y
comparan el resultado contra evaluar_capacidad() calculado directamente con
la tasa esperada — para detectar cualquier desincronización entre lo que la
UI muestra y lo que debería calcular."""

import wx
import pytest

from gestor_credito.calculo.capacidad import evaluar_capacidad
from gestor_credito.db import database
from gestor_credito.db.convenios import guardar_tasa
from gestor_credito.ui.calculadora_panel import TIPO_CAMBIO_FIJO, CalculadoraPanel
from gestor_credito.ui.configuracion_panel import ConfiguracionPanel


@pytest.fixture(scope="module")
def app():
    return wx.App()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


def _frame_con_status_bar():
    frame = wx.Frame(None)
    frame.CreateStatusBar()
    return frame


@pytest.fixture
def notebook_frame(app, conn):
    """CalculadoraPanel exige que su parent sea un wx.Notebook real (ver
    main_frame.py: wx.Notebook.AddPage exige pPage->GetParent() == this) y
    llama self.GetTopLevelParent().SetStatusText(...), así que el frame que
    aloja el notebook necesita barra de estado, igual que en la app real.

    Depende explícitamente de `conn` (aunque no lo use directo) para
    garantizar que el monkeypatch de DB_PATH ya se aplicó ANTES de construir
    el panel — pytest no garantiza el orden entre fixtures sin relación de
    dependencia entre sí solo por el orden en que aparecen en la firma del
    test. Sin este `conn` acá, se comprobó empíricamente que el panel se
    construye contra la base de datos REAL de producción (data/gestor_credito.db)
    en vez de la temporal — un bug real de esta batería de pruebas, no de la
    app, pero que hubiera invalidado silenciosamente varias de estas pruebas."""
    frame = _frame_con_status_bar()
    notebook = wx.Notebook(frame)
    frame._notebook = notebook
    yield frame
    frame.Destroy()


@pytest.fixture
def calc(notebook_frame, conn):
    panel = CalculadoraPanel(notebook_frame._notebook)
    notebook_frame._notebook.AddPage(panel, "Calculadora")
    return panel


def _elegir_empresa(panel, empresa):
    """Simula la selección real de una empresa en empresa_choice: cambia la
    selección Y dispara el EVT_CHOICE nativo que un usuario real generaría
    (con flechas, tipeo o clic) — SetSelection() por sí solo NO dispara ese
    evento en wx, así que probar solo con SetSelection() no sería una
    simulación fiel de la interacción real."""
    indice = panel._empresas_por_indice.index(empresa)
    panel.empresa_choice.SetSelection(indice)
    evento = wx.CommandEvent(wx.EVT_CHOICE.typeId, panel.empresa_choice.GetId())
    evento.SetEventObject(panel.empresa_choice)
    panel.empresa_choice.GetEventHandler().ProcessEvent(evento)


def _llenar_formulario(panel, monto="1140", plazo="24", periodicidad_indice=0,
                        fecha_ingreso="01/01/2020", salario="15000"):
    panel.fecha_ingreso_texto.SetValue(fecha_ingreso)
    panel.salario_texto.SetValue(salario)
    panel.monto_texto.SetValue(monto)
    panel.plazo_texto.SetValue(plazo)
    panel.periodicidad_choice.SetSelection(periodicidad_indice)


def _cuota_esperada(panel, tasa, monto=1140.0, plazo=24, periodicidad="Mensual",
                     fecha_ingreso_iso="2020-01-01", salario=15000.0):
    from datetime import date
    resultado = evaluar_capacidad(
        fecha_ingreso=date.fromisoformat(fecha_ingreso_iso),
        salario_bruto_mensual_cordobas=salario,
        ingresos_extra_cordobas=0.0,
        monto_credito_usd=monto,
        plazo_meses=plazo,
        periodicidad=periodicidad,
        tasa_anual=tasa,
        tipo_cambio=TIPO_CAMBIO_FIJO,
        deuda_activa_cordobas=0.0,
    )
    return resultado.cuota_usd


# ---- 1. "Cálculos congelados": alternar empresas debe recalcular limpio ---

def test_alternar_dos_empresas_con_tasas_distintas_da_resultados_distintos(calc, conn):
    _llenar_formulario(calc)

    _elegir_empresa(calc, "MIDESA")  # 0.18
    calc._on_calcular(None)
    cuota_midesa = calc._ultimo_resultado.cuota_usd

    _elegir_empresa(calc, "NICAES")  # 0.60
    calc._on_calcular(None)
    cuota_nicaes = calc._ultimo_resultado.cuota_usd

    assert cuota_midesa != cuota_nicaes
    assert cuota_midesa == pytest.approx(_cuota_esperada(calc, 0.18))
    assert cuota_nicaes == pytest.approx(_cuota_esperada(calc, 0.60))


def test_volver_a_la_primera_empresa_recalcula_el_valor_original(calc, conn):
    """El escenario exacto reportado: A -> B -> A otra vez debe dar el mismo
    resultado que la primera vez con A, no arrastrar el de B."""
    _llenar_formulario(calc)

    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    primera = calc._ultimo_resultado.cuota_usd

    _elegir_empresa(calc, "NICAES")
    calc._on_calcular(None)

    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    tercera = calc._ultimo_resultado.cuota_usd

    assert tercera == pytest.approx(primera)


def test_alternancia_exhaustiva_todas_las_empresas_contra_todas(calc, conn):
    """Recorre TODAS las empresas de la lista real (29), en orden y en
    orden inverso, recalculando en cada una — cada resultado debe coincidir
    exactamente con evaluar_capacidad() usando la tasa real de esa empresa
    en ese momento, sin importar cuál fue la empresa anterior."""
    _llenar_formulario(calc)
    empresas = list(calc._empresas_por_indice)
    assert len(empresas) == 29

    for empresa in empresas + list(reversed(empresas)) + empresas:
        _elegir_empresa(calc, empresa)
        tasa = calc._convenios[empresa]
        if tasa is None:
            # _on_calcular() muestra un wx.MessageBox real para una empresa
            # sin tasa configurada (ver _leer_entradas) — no se llama acá,
            # abriría un modal real que colgaría la prueba en modo headless.
            continue
        calc._on_calcular(None)
        assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, tasa)), (
            f"cuota incorrecta tras elegir {empresa!r} (tasa {tasa})"
        )


def test_empresa_sin_tasa_configurada_bloquea_el_calculo_manual(calc, conn):
    _llenar_formulario(calc)
    _elegir_empresa(calc, "GRUPO TALSE")  # sembrada con tasa NULL
    entradas, error = calc._leer_entradas()
    assert entradas is None
    assert "tasa de interés configurada" in error


def test_alternar_empresa_despues_de_calcular_recalcula_solo_con_la_tasa_nueva(calc, conn):
    """Fix del reporte real (2026-07-12), calificado como fallo crítico:
    "el sistema siempre devuelve el mismo resultado... no recalcula al
    cambiar el foco de la empresa seleccionada". Antes, cambiar la empresa
    tras Calcular solo actualizaba tasa_texto y dejaba el cuadro de
    Resultados con el número de la empresa ANTERIOR, indistinguible de un
    cálculo válido. Ahora, si ya había un resultado, cambiar de empresa
    fuerza un recálculo limpio en silencio (sin wx.MessageBox ni voz)."""
    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, 0.18))

    _elegir_empresa(calc, "NICAES")
    assert calc.tasa_texto.GetLabel() == "Tasa: 60%"
    # Recalculado SOLO, sin volver a presionar Calcular.
    assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, 0.60))
    assert "60" not in calc.resultado_cuota.GetLabel()  # no queda texto de la tasa vieja
    assert calc.resultado_cuota.GetLabel() == (
        f"Cuota calculada: US${calc._ultimo_resultado.cuota_usd:.2f} "
        f"(C${calc._ultimo_resultado.cuota_cordobas:.2f})"
    )


def test_cambiar_a_empresa_sin_tasa_limpia_el_resultado_en_vez_de_dejar_uno_viejo(calc, conn):
    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    assert calc._ultimo_resultado is not None

    _elegir_empresa(calc, "GRUPO TALSE")  # sembrada con tasa NULL
    assert calc._ultimo_resultado is None
    assert calc.resultado_cuota.GetLabel() == "Cuota calculada: —"


def test_recalculo_silencioso_no_llama_a_voz_ni_status(calc, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.calculadora_panel.anunciar_voz_nvda",
        lambda texto: llamadas.append(texto),
    )
    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    assert len(llamadas) == 1  # el propio Calcular sí habla

    _elegir_empresa(calc, "NICAES")
    assert len(llamadas) == 1  # cambiar de empresa NO agrega un segundo anuncio


# ---- 2. "Falta de actualización en caliente" tras editar una tasa --------

def test_recargar_calculadora_ve_una_tasa_editada_directo_en_bd(calc, conn):
    guardar_tasa(conn, "MIDESA", 0.99)
    calc.recargar()

    assert calc._convenios["MIDESA"] == pytest.approx(0.99)
    _elegir_empresa(calc, "MIDESA")
    assert calc.tasa_texto.GetLabel() == "Tasa: 99%"


def test_recargar_solo_ya_recalcula_sin_volver_a_elegir_la_empresa_ni_presionar_calcular(calc, conn):
    """El corazón del fallo #1 reportado ("actualización en caliente"): con
    un resultado ya calculado y la MISMA empresa todavía seleccionada,
    editar su tasa en la base (como haría Configuración) y solo llamar
    recargar() — sin volver a elegir la empresa ni presionar Calcular — ya
    debe reflejar la tasa nueva."""
    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, 0.18))

    guardar_tasa(conn, "MIDESA", 0.50)
    calc.recargar()

    assert calc.tasa_texto.GetLabel() == "Tasa: 50%"
    assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, 0.50))


def test_recargar_tras_borrar_la_empresa_elegida_limpia_el_resultado(calc, conn):
    from gestor_credito.db.convenios import eliminar_convenio

    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    assert calc._ultimo_resultado is not None

    eliminar_convenio(conn, "MIDESA")
    calc.recargar()

    assert calc._ultimo_resultado is None
    assert calc.resultado_cuota.GetLabel() == "Cuota calculada: —"


def test_editar_tasa_en_configuracion_se_refleja_en_calculadora_tras_recargar(calc, conn):
    """Simula el flujo real MainFrame: ConfiguracionPanel (en su propio
    diálogo/frame) edita una tasa; al cerrar ese diálogo, MainFrame llama
    calculadora_panel.recargar() incondicionalmente (ver
    MainFrame._abrir_dialogo) — acá se reproduce ese mismo paso sin
    necesitar un wx.Dialog modal real (bloquearía la prueba)."""
    frame_config = _frame_con_status_bar()
    config = ConfiguracionPanel(frame_config)

    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    cuota_antes = calc._ultimo_resultado.cuota_usd

    # Editar MIDESA desde Configuración, igual que el usuario real.
    indice = next(i for i, (e, _t) in enumerate(config._convenios_cargados) if e == "MIDESA")
    config.convenios_lista.SetItemState(indice, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    evento = wx.ListEvent(wx.wxEVT_LIST_ITEM_SELECTED, config.convenios_lista.GetId())
    evento.SetIndex(indice)
    config._on_seleccionar_convenio(evento)
    config.convenio_tasa_texto.SetValue("5")
    config._on_guardar_convenio(None)
    frame_config.Destroy()

    # Recargar (paso que MainFrame hace SIEMPRE al cerrar cualquier diálogo).
    calc.recargar()
    assert calc._convenios["MIDESA"] == pytest.approx(0.05)

    _elegir_empresa(calc, "MIDESA")
    assert calc.tasa_texto.GetLabel() == "Tasa: 5%"

    calc._on_calcular(None)
    cuota_despues = calc._ultimo_resultado.cuota_usd
    assert cuota_despues != cuota_antes
    assert cuota_despues == pytest.approx(_cuota_esperada(calc, 0.05))


def test_ediciones_repetidas_de_tasa_interleaved_con_cambios_de_empresa(calc, conn):
    """Estrés combinado: cambios consecutivos de tasa en la base (como si
    vinieran de Configuración) intercalados con recargar()/cambio de
    empresa/Calcular en la Calculadora, muchas veces seguidas."""
    _llenar_formulario(calc)
    secuencia = [
        ("MIDESA", 0.10), ("MIDESA", 0.20), ("NICAES", 0.30), ("MIDESA", 0.40),
        ("NICAES", 0.50), ("NICAES", 0.60), ("MIDESA", 0.70),
    ]
    for empresa, tasa in secuencia:
        guardar_tasa(conn, empresa, tasa)
        calc.recargar()
        _elegir_empresa(calc, empresa)
        calc._on_calcular(None)
        assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, tasa)), (
            f"tras guardar {empresa}={tasa}, la calculadora no reflejó la tasa nueva"
        )

    # Estado final coherente: MIDESA=0.70, NICAES=0.60, sin mezclarse.
    assert calc._convenios["MIDESA"] == pytest.approx(0.70)
    assert calc._convenios["NICAES"] == pytest.approx(0.60)


def test_recargar_preserva_la_empresa_elegida_y_su_tasa_actualizada(calc, conn):
    _llenar_formulario(calc)
    _elegir_empresa(calc, "NICAES")
    guardar_tasa(conn, "NICAES", 0.77)
    calc.recargar()

    assert calc._empresa_seleccionada() == "NICAES"
    assert calc.tasa_texto.GetLabel() == "Tasa: 77%"
    calc._on_calcular(None)
    assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, 0.77))


def test_guardado_repetido_de_la_misma_tasa_no_desincroniza_nada(calc, conn):
    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    for _ in range(10):
        guardar_tasa(conn, "MIDESA", 0.33)
        calc.recargar()
    calc._on_calcular(None)
    assert calc._ultimo_resultado.cuota_usd == pytest.approx(_cuota_esperada(calc, 0.33))


# ---- limpiar_formulario() (atajo GLOBAL Ctrl+D en la Calculadora, antes Alt+L) ---------

def test_limpiar_formulario_vacia_los_campos_pero_conserva_la_empresa(calc, conn):
    _llenar_formulario(calc)
    _elegir_empresa(calc, "NICAES")
    calc._on_calcular(None)
    assert calc._ultimo_resultado is not None

    calc.limpiar_formulario()

    assert calc._empresa_seleccionada() == "NICAES"
    assert calc.fecha_ingreso_texto.GetValue() == ""
    assert calc.salario_texto.GetValue() == ""
    assert calc.extra_texto.GetValue() == "0"
    assert calc.monto_texto.GetValue() == ""
    assert calc.plazo_texto.GetValue() == ""
    assert calc.periodicidad_choice.GetSelection() == 0
    assert calc.deuda_texto.GetValue() == "0"


def test_limpiar_formulario_limpia_pasivo_laboral_y_resultados(calc, conn):
    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")
    calc._on_calcular(None)
    assert calc._pasivo_laboral_cordobas is not None
    assert calc._ultimo_resultado is not None

    calc.limpiar_formulario()

    assert calc._pasivo_laboral_cordobas is None
    assert calc.resultado_pasivo_laboral.GetLabel() == "Pasivo laboral: —"
    assert calc._ultimo_resultado is None
    assert calc.resultado_cuota.GetLabel() == "Cuota calculada: —"


def test_limpiar_formulario_sin_empresa_elegida_no_falla(calc, conn):
    calc.limpiar_formulario()  # no debe lanzar
    assert calc._empresa_seleccionada() is None


def test_limpiar_formulario_reproduce_el_sonido_de_borrado(calc, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.calculadora_panel.reproducir_sonido",
        lambda nombre: llamadas.append(nombre),
    )
    from gestor_credito.ui.sonido import SONIDO_BORRAR

    calc.limpiar_formulario()

    assert llamadas == [SONIDO_BORRAR]


def test_limpiar_formulario_deja_el_foco_en_fecha_de_ingreso(calc, conn):
    # Pedido explícito del usuario, 2026-08-16: tras Ctrl+D, el foco debe
    # quedar en "Fecha de ingreso" para poder seguir cargando el siguiente
    # cliente sin ir a buscar el primer campo a mano.
    _llenar_formulario(calc)
    calc.salario_texto.SetFocus()

    calc.limpiar_formulario()

    assert wx.Window.FindFocus() is calc.fecha_ingreso_texto


# ---- Salario con deducciones en vivo (pedido explícito del usuario, ------
# ---- 2026-08-16: "mismo comportamiento del cálculo de pasivos") ----------

def test_salario_neto_se_calcula_en_vivo_al_tipear_salario_sin_calcular(calc, conn):
    from gestor_credito.calculo.deducciones import calcular_salario_neto_mensual

    calc.salario_texto.SetValue("15000")

    esperado = calcular_salario_neto_mensual(15000.0, 0.0)
    assert calc._salario_neto_cordobas == pytest.approx(esperado)
    assert calc._salario_neto_usd == pytest.approx(esperado / TIPO_CAMBIO_FIJO)
    assert "Salario neto mensual: C$" in calc.resultado_salario_neto.GetLabel()


def test_salario_neto_en_vivo_no_requiere_empresa_ni_monto_ni_plazo(calc, conn):
    # A diferencia del resto de "Resultados" (cuota, cobertura,
    # endeudamiento), el salario neto no depende de empresa/tasa ni de
    # monto/plazo — calcular_salario_neto_mensual() solo usa salario bruto e
    # ingresos extra.
    assert calc._empresa_seleccionada() is None
    assert calc.monto_texto.GetValue() == ""
    assert calc.plazo_texto.GetValue() == ""

    calc.salario_texto.SetValue("15000")

    assert calc._salario_neto_cordobas is not None


def test_salario_neto_en_vivo_se_actualiza_al_cambiar_ingresos_extra(calc, conn):
    from gestor_credito.calculo.deducciones import calcular_salario_neto_mensual

    calc.salario_texto.SetValue("15000")
    sin_extra = calc._salario_neto_cordobas

    calc.extra_texto.SetValue("2000")

    con_extra = calc._salario_neto_cordobas
    assert con_extra == pytest.approx(calcular_salario_neto_mensual(15000.0, 2000.0))
    assert con_extra > sin_extra


def test_salario_neto_en_vivo_vuelve_a_guion_si_se_borra_el_salario(calc, conn):
    calc.salario_texto.SetValue("15000")
    assert calc._salario_neto_cordobas is not None

    calc.salario_texto.SetValue("")

    assert calc._salario_neto_cordobas is None
    assert calc.resultado_salario_neto.GetLabel() == "Salario neto mensual: —"


def test_pasivo_laboral_en_vivo_sigue_funcionando_junto_al_salario_neto(calc, conn):
    # Pedido explícito del usuario: que agregar el salario neto en vivo no
    # interfiera ni desactive el cálculo automático del pasivo laboral —
    # ambos deben quedar activos y correctos al mismo tiempo.
    calc.fecha_ingreso_texto.SetValue("01/01/2020")
    calc.salario_texto.SetValue("15000")

    assert calc._pasivo_laboral_cordobas is not None
    assert calc._salario_neto_cordobas is not None
    assert "Pasivo laboral: C$" in calc.resultado_pasivo_laboral.GetLabel()
    assert "Salario neto mensual: C$" in calc.resultado_salario_neto.GetLabel()


def test_cambiar_empresa_sin_tasa_no_borra_el_salario_neto_en_vivo(calc, conn):
    # Antes (hasta 2026-08-16), cambiar a una empresa sin tasa configurada
    # limpiaba TODO el cuadro de Resultados, incluido el salario neto — con
    # el cálculo en vivo, eso ya no debería pasar: el salario neto no
    # depende de la empresa/tasa en absoluto (mismo criterio ya aplicado al
    # pasivo laboral).
    from gestor_credito.db.convenios import guardar_tasa

    guardar_tasa(conn, "SIN TASA", None)
    calc.recargar()

    calc.salario_texto.SetValue("15000")
    assert calc._salario_neto_cordobas is not None

    _elegir_empresa(calc, "SIN TASA")

    assert calc._salario_neto_cordobas is not None
    assert "Salario neto mensual: C$" in calc.resultado_salario_neto.GetLabel()


def test_calcular_no_pisa_el_salario_neto_con_un_numero_distinto(calc, conn):
    _llenar_formulario(calc)
    _elegir_empresa(calc, "MIDESA")

    antes_de_calcular = calc._salario_neto_cordobas
    calc._on_calcular(None)

    assert calc._salario_neto_cordobas == pytest.approx(antes_de_calcular)
    assert f"C${calc._salario_neto_cordobas:.2f}" in calc.resultado_salario_neto.GetLabel()


def test_anunciar_salario_neto_lee_el_valor_en_vivo_sin_necesitar_calcular(calc, conn, monkeypatch):
    # Ctrl+Shift+W: hasta 2026-08-16 dependía de haber presionado
    # Ctrl+Shift+R al menos una vez (leía de _ultimo_resultado) — ahora debe
    # funcionar con solo tipear el salario, igual que Ctrl+Shift+Q.
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.calculadora_panel.anunciar_voz_nvda",
        lambda texto: llamadas.append(texto),
    )
    assert calc._ultimo_resultado is None

    calc.salario_texto.SetValue("15000")
    calc._anunciar_salario_neto()

    assert len(llamadas) == 1
    assert "Salario con deducciones" in llamadas[0]


def test_anunciar_salario_neto_sin_salario_avisa_que_falta_el_dato(calc, conn, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "gestor_credito.ui.calculadora_panel.anunciar_voz_nvda",
        lambda texto: llamadas.append(texto),
    )

    calc._anunciar_salario_neto()

    assert len(llamadas) == 1
    assert "Todavía no se puede calcular" in llamadas[0]


def test_limpiar_formulario_limpia_tambien_el_salario_neto_en_vivo(calc, conn):
    calc.salario_texto.SetValue("15000")
    assert calc._salario_neto_cordobas is not None

    calc.limpiar_formulario()

    assert calc._salario_neto_cordobas is None
    assert calc.resultado_salario_neto.GetLabel() == "Salario neto mensual: —"
