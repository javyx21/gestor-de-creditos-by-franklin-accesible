from pathlib import Path

import wx

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"

# Tamaño de despliegue en pantalla: pequeño y no invasivo, sin importar la
# resolución del archivo de origen (el actual es de 2048x2048 px).
DISPLAY_SIZE = 32

ALT_TEXT = (
    "Logo de Franklin Accesible: figura humana azul en movimiento, atravesando una "
    "barrera fragmentada de color naranja y amarillo."
)


class _NombreAccesible(wx.Accessible):
    """GetName/GetRole/GetState por MSAA/UIA para un control estático.

    wx.Window.SetName() NO alcanza para esto: se verificó empíricamente (con
    UI Automation Y directamente contra IAccessible crudo vía COM, que es la
    interfaz que NVDA realmente consulta para una app wx/Win32 clásica como
    esta) que ni wx.StaticBitmap ni wx.StaticText propagan SetName() al
    nombre accesible real — wx.StaticBitmap queda con nombre vacío (NVDA solo
    anuncia el rol, "gráfico", sin texto) y wx.StaticText cae de vuelta al
    texto VISIBLE (GetLabel()), lo que además violaría la regla de que el alt
    text no debe ser visible para un vidente. La única forma confirmada de
    exponer un nombre accesible distinto del texto/bitmap visible es
    sobreescribir wx.Accessible.GetName() a mano y asignarlo con
    SetAccessible().

    GetState agrega ACC_STATE_SYSTEM_FOCUSABLE: el nombre correcto por sí
    solo no bastó (reporte real del usuario, 2026-07-11, confirmado con NVDA
    real): un control sin foco no entra en el recorrido normal con Tab que el
    usuario usa para todo lo demás en esta app, así que NVDA nunca llegaba a
    leerlo aunque el nombre ya estuviera bien expuesto a nivel de API — ver
    _LogoBitmap/_LogoTexto más abajo, que además habilitan AcceptsFocus para
    que el control realmente entre en el ciclo de Tab de wx, no solo declare
    el estado."""

    def __init__(self, win, nombre):
        super().__init__(win)
        self._nombre = nombre

    def GetName(self, childId):
        return (wx.ACC_OK, self._nombre)

    def GetRole(self, childId):
        return (wx.ACC_OK, wx.ROLE_SYSTEM_GRAPHIC)

    def GetState(self, childId):
        estado = wx.ACC_STATE_SYSTEM_FOCUSABLE
        if self.GetWindow() and self.GetWindow().HasFocus():
            estado |= wx.ACC_STATE_SYSTEM_FOCUSED
        return (wx.ACC_OK, estado)


class _LogoBitmap(wx.StaticBitmap):
    """wx.StaticBitmap no acepta foco por teclado por defecto — estos dos
    overrides son lo que efectivamente lo mete en el ciclo de Tab de wx
    (wxControlContainer los consulta para decidir qué hijos incluye al
    tabular dentro de un panel), independientemente de lo que declare
    GetState() por MSAA."""

    def AcceptsFocus(self):
        return True

    def AcceptsFocusFromKeyboard(self):
        return True


class _LogoTexto(wx.StaticText):
    """Mismo motivo que _LogoBitmap — ver ahí."""

    def AcceptsFocus(self):
        return True

    def AcceptsFocusFromKeyboard(self):
        return True


class AppLogo(wx.Panel):
    """Logo no invasivo que debe aparecer en toda pestaña. Hasta que exista un
    archivo de imagen real en LOGO_PATH, se muestra un texto de respaldo — en
    ambos casos el nombre accesible que lee NVDA es el mismo (ALT_TEXT).

    El alt text SOLO debe ser audible para lectores de pantalla, nunca visible:
    se expone vía wx.Accessible.GetName (ver _NombreAccesible más arriba),
    nunca con SetToolTip, que dibuja un globo de texto visible en pantalla.
    El control SÍ es alcanzable con Tab (ver _LogoBitmap/_LogoTexto) — es la
    única forma confirmada de que NVDA llegue a leerlo durante la navegación
    normal de esta app; un vidente tabulando hasta acá solo va a ver el
    rectángulo de foco estándar alrededor del logo, ningún texto nuevo.
    """

    def __init__(self, parent):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        if LOGO_PATH.exists():
            imagen = wx.Image(str(LOGO_PATH))
            imagen = imagen.Scale(DISPLAY_SIZE, DISPLAY_SIZE, wx.IMAGE_QUALITY_HIGH)
            control = _LogoBitmap(self, bitmap=wx.Bitmap(imagen))
        else:
            control = _LogoTexto(self, label="Franklin Accesible")

        control.SetName(ALT_TEXT)
        control.SetAccessible(_NombreAccesible(control, ALT_TEXT))

        sizer.Add(control, 0, wx.ALL, 4)
        self.SetSizer(sizer)
