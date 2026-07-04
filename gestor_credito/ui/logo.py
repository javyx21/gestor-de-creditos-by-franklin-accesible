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


class AppLogo(wx.Panel):
    """Logo no invasivo que debe aparecer en toda pestaña. Hasta que exista un
    archivo de imagen real en LOGO_PATH, se muestra un texto de respaldo — en
    ambos casos el nombre accesible que lee NVDA es el mismo (ALT_TEXT).

    El alt text SOLO debe ser audible para lectores de pantalla, nunca visible:
    se expone con SetName (nombre accesible vía MSAA/UIA), nunca con
    SetToolTip, que dibuja un globo de texto visible en pantalla.
    """

    def __init__(self, parent):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        if LOGO_PATH.exists():
            imagen = wx.Image(str(LOGO_PATH))
            imagen = imagen.Scale(DISPLAY_SIZE, DISPLAY_SIZE, wx.IMAGE_QUALITY_HIGH)
            control = wx.StaticBitmap(self, bitmap=wx.Bitmap(imagen))
        else:
            control = wx.StaticText(self, label="Franklin Accesible")

        control.SetName(ALT_TEXT)

        sizer.Add(control, 0, wx.ALL, 4)
        self.SetSizer(sizer)
