import ctypes
import sys
import threading
from ctypes import wintypes
from pathlib import Path

import wx

# EVENT_OBJECT_LIVEREGIONCHANGED: mismo evento MSAA que usan los navegadores
# para implementar aria-live="polite" — NVDA lo escucha globalmente en
# cualquier ventana, no solo en navegadores, y anuncia el nombre accesible
# del objeto/child indicado sin robar el foco ni abrir nada. OBJID_CLIENT y
# CHILDID_SELF son las constantes MSAA estándar (ver winuser.h/oleacc.h).
_EVENT_OBJECT_LIVEREGIONCHANGED = 0x8021
_OBJID_CLIENT = 0xFFFFFFFC
_CHILDID_SELF = 0

# argtypes explícitos: sin esto, ctypes asume c_int de 32 bits para el HWND
# en la firma por defecto, lo que puede truncarlo en Windows de 64 bits.
_NotifyWinEvent = ctypes.windll.user32.NotifyWinEvent
_NotifyWinEvent.argtypes = [wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG]
_NotifyWinEvent.restype = None


class _SoloNombreAccesible(wx.Accessible):
    """Override de GetName por MSAA/UIA — nada más. GetRole/GetState quedan
    sin sobreescribir a propósito, para que el control siga reportando su rol
    y estado NATIVOS (lista, combo, árbol, casilla, etc.); si se los pisara
    acá también, como hay que hacer con un control puramente decorativo (ver
    logo.py), se rompería esa parte en vez de arreglar solo el nombre."""

    def __init__(self, win, nombre):
        super().__init__(win)
        self._nombre = nombre

    def GetName(self, childId):
        return (wx.ACC_OK, self._nombre)


def nombre_accesible(control, nombre):
    """Fija el nombre accesible real (el que lee NVDA) de `control`.

    wx.Window.SetName() NO alcanza: se verificó empíricamente, con IAccessible
    crudo vía COM (la interfaz que NVDA usa para esta app, no solo UI
    Automation), que SetName() no llega al nombre accesible real de NINGÚN
    control probado — ni estáticos (wx.StaticBitmap/wx.StaticText, ver
    logo.py) ni interactivos (wx.ListCtrl, wx.TextCtrl, wx.Choice). Windows
    completa el nombre con su propio mecanismo de "etiqueta automática por
    cercanía" (el STATIC más próximo en orden de creación/z-order), que a
    veces da un resultado razonable por coincidencia (un wx.Choice justo
    después de su wx.StaticText) y a veces da un resultado completamente
    equivocado — reporte real del usuario, 2026-07-11: la lista principal de
    Casos (`self.lista`, código dice SetName("Lista de casos")) se anunciaba
    como "Buscar", el nombre del GroupBox de búsqueda más cercano en
    z-order, nada que ver. Todo `.SetName(...)` de este proyecto debe pasar
    por esta función en su lugar — ver auditoría completa en CLAUDE.md.

    Sigue llamando a SetName() además (no hace daño, y es lo que un cliente
    MSAA hipotético que sí lo respete leería), pero SetAccessible() con
    _SoloNombreAccesible es lo que realmente hace que NVDA lo escuche."""
    control.SetName(nombre)
    control.SetAccessible(_SoloNombreAccesible(control, nombre))


def anunciar_texto_estado(status_bar):
    """Notifica a NVDA que el texto de `status_bar` (una wx.StatusBar) acaba
    de cambiar, para que lo lea solo — sin robar el foco ni abrir un diálogo.
    Llamar SIEMPRE inmediatamente después de status_bar.SetStatusText(texto).

    Verificado empíricamente con IAccessible crudo: el texto de una
    wx.StatusBar no vive en el objeto barra en sí (su accName da siempre
    None) sino en su primer "campo" — child id 1 en términos MSAA — que sí
    refleja el texto actual con normalidad. El evento hay que dispararlo ahí.

    Agregado tras un reporte real del usuario (2026-07-11): filtrar por
    alerta (Documentos pendientes, En espera de constancia) en Casos
    actualiza cuántos casos se encontraron en la barra de estado, pero NVDA
    nunca lo anunciaba — el usuario solo se enteraba si volvía a leer el foco
    a mano. Un wx.MessageBox en cada cambio de filtro ya se había descartado
    antes por una razón concreta (ver _cargar_casos en casos_panel.py):
    el combobox "Filtrar por alerta" dispara EVT_CHOICE en cada flecha
    arriba/abajo mientras se navega, así que un diálogo modal por tecla lo
    dejaba inusable. EVENT_OBJECT_LIVEREGIONCHANGED no tiene ese problema:
    no es modal, no mueve el foco, así que es seguro dispararlo en cualquier
    cambio de estado, no solo búsquedas explícitas."""
    hwnd = status_bar.GetHandle()
    _NotifyWinEvent(_EVENT_OBJECT_LIVEREGIONCHANGED, hwnd, _OBJID_CLIENT, _CHILDID_SELF + 1)


def ejecutar_en_segundo_plano(trabajo, callback):
    """Corre `trabajo()` (sin argumentos, normalmente una consulta a la base
    de datos) en un hilo aparte y entrega su valor de retorno a `callback`
    de vuelta en el hilo principal de wx (vía wx.CallAfter).

    Agregado 2026-08-16 tras un reporte real del usuario en Historial de
    Créditos: recargar la lista de créditos y de empresas (`buscar_creditos`/
    `obtener_empresas_convenio`) corre en el hilo principal por defecto, y
    mientras esa consulta a SQLite está en curso, Windows no bombea el bucle
    de mensajes de la ventana — con NVDA activo, esto se percibe como que "la
    lectura o salida por voz se congela" al abrir la pestaña o mover el
    selector de filtros, porque cualquier evento de accesibilidad pendiente
    (incluido el habla de NVDA, que depende de que Windows siga entregando
    mensajes) queda en cola hasta que el hilo principal se libera. Moverlo a
    un hilo aparte deja el bucle de mensajes libre todo el tiempo.

    `callback` SIEMPRE se llama en el hilo principal (nunca directo desde el
    hilo en segundo plano) — así puede tocar controles de wx sin problema,
    algo que NO es seguro hacer desde otro hilo. Si `trabajo()` necesita
    reportar un error (p. ej. un ValueError de una búsqueda inválida), debe
    atraparlo y devolverlo como parte del resultado en vez de dejarlo
    propagarse — una excepción sin atrapar dentro del hilo en segundo plano
    no llega a ningún lado, se pierde en silencio.

    Aislado como función de módulo (no un método) para que las pruebas
    puedan reemplazarlo por una versión síncrona vía monkeypatch (ver
    tests/test_creditos_panel.py) sin depender de threading real ni de
    bombear el bucle de eventos de wx en una prueba headless sin MainLoop."""

    def _en_hilo():
        resultado = trabajo()
        wx.CallAfter(callback, resultado)

    threading.Thread(target=_en_hilo, daemon=True).start()


def activar_con_enter(boton):
    """Un wx.Button ya responde a Barra Espaciadora al estar enfocado, pero en
    una wx.Frame (a diferencia de un wx.Dialog) Enter no dispara el click por
    defecto: Windows solo traduce Enter en click para el "botón por defecto"
    de un diálogo, mecanismo que un Frame simple no usa. Sin este bind, Enter
    no hace nada aunque el botón tenga el foco — rompe la navegación estándar
    por teclado. Aplicar a todo wx.Button de la app, no solo a uno puntual."""

    def _on_key_down(event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            boton.Command(wx.CommandEvent(wx.EVT_BUTTON.typeId, boton.GetId()))
        else:
            event.Skip()

    boton.Bind(wx.EVT_KEY_DOWN, _on_key_down)


# nvdaControllerClient(32|64).dll: la biblioteca cliente-servidor que NVDA
# publica específicamente para aplicaciones EXTERNAS a su propio proceso
# (juegos, apps compiladas aparte, etc. — no complementos/add-ons, que
# corren dentro del proceso de NVDA y usarían ui.message() en su lugar). Es
# el mecanismo oficial para pedirle a NVDA que hable un texto de forma
# directa, documentado en el manual de complementos que dejó el usuario en
# la raíz del proyecto ("manual creación de complementos.docx"). Los .dll no
# vienen con la instalación de NVDA (se comprobó a mano: no existen en
# C:\Program Files\NVDA en esta máquina) — son un binario redistribuible
# aparte, pensado para que cada aplicación de terceros lo empaquete consigo
# misma; acá se tomaron del paquete accessible_output2 de PyPI (que los
# redistribuye tal cual) y quedaron en gestor_credito/assets/nvda/, sin
# agregar esa librería completa como dependencia — de ahí solo hacía falta
# este único llamado (nvdaController_speakText), no toda su capa de
# abstracción multi-lector.
_NVDA_LIB_DIR = Path(__file__).resolve().parent.parent / "assets" / "nvda"
_nvda_controller_lib = None
_nvda_controller_cargado = False


def _cargar_nvda_controller():
    """Carga perezosamente (una sola vez por proceso) la dll de
    nvdaControllerClient que corresponda a la arquitectura de este Python
    (32 o 64 bits) y le fija el argtype correcto a
    nvdaController_speakText (LPCWSTR — sin esto ctypes puede mandar bytes
    mal codificados con tildes/ñ). Si NVDA no está corriendo, si el usuario
    está en una máquina sin estos .dll, o si la carga falla por cualquier
    otro motivo, devuelve None en vez de propagar la excepción: un anuncio
    de voz que falla no debe tumbar la app ni bloquear el resto de la UI,
    mismo criterio que reproducir_sonido() en ui/sonido.py."""
    global _nvda_controller_lib, _nvda_controller_cargado
    if _nvda_controller_cargado:
        return _nvda_controller_lib
    _nvda_controller_cargado = True

    nombre_dll = "nvdaControllerClient64.dll" if sys.maxsize > 2**32 else "nvdaControllerClient32.dll"
    ruta = _NVDA_LIB_DIR / nombre_dll
    try:
        lib = ctypes.windll.LoadLibrary(str(ruta))
        lib.nvdaController_speakText.argtypes = [wintypes.LPCWSTR]
        lib.nvdaController_speakText.restype = wintypes.LONG
    except OSError:
        return None

    _nvda_controller_lib = lib
    return lib


def anunciar_voz_nvda(texto):
    """Le pide a NVDA que hable `texto` YA, de forma directa — a diferencia
    de anunciar_texto_estado() (que depende de que NVDA detecte un evento
    MSAA de "región viva" sobre la barra de estado, algo que resultó no
    escucharse de forma confiable en el uso real, según reporte del usuario
    2026-07-11: ni el cambio de opción con flechas ni el anuncio del
    resultado al confirmar con Enter se oían en el combo "Filtrar por
    alerta" de Casos), esta función no depende de ningún control ni de que
    NVDA vigile un objeto en particular: es una llamada directa a la API
    pública de NVDA para aplicaciones externas (ver comentario sobre
    nvdaControllerClient arriba). No roba el foco ni abre nada.

    Pensada para usarse en respuesta a una acción puntual del usuario (p.
    ej. Enter sobre el combo de filtro) que necesita un anuncio confiable e
    inmediato — no para dispararla en cada tecla de flecha, que interrumpiría
    el anuncio nativo del nombre de la opción que NVDA ya hace solo al
    navegar un combobox."""
    lib = _cargar_nvda_controller()
    if lib is None:
        return
    try:
        lib.nvdaController_speakText(texto)
    except OSError:
        pass
