import wx


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
