import wx

from gestor_credito.ui.main_frame import MainFrame


class GestorCreditoApp(wx.App):
    def OnInit(self):
        frame = MainFrame(None, title="Gestor de Crédito")
        frame.Show()
        return True


def main():
    app = GestorCreditoApp()
    app.MainLoop()
