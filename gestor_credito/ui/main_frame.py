import wx

from gestor_credito.db.database import init_db
from gestor_credito.ui.casos_panel import CasosPanel
from gestor_credito.ui.configuracion_panel import ConfiguracionPanel


class MainFrame(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(900, 650))

        init_db()

        self.CreateStatusBar()
        self.SetStatusText("Listo")

        notebook = wx.Notebook(self)
        casos_panel = CasosPanel(notebook)
        notebook.AddPage(casos_panel, "Casos")
        notebook.AddPage(ConfiguracionPanel(notebook), "Configuración")

        def _on_cambiar_pestana(event):
            if notebook.GetPage(event.GetSelection()) is casos_panel:
                casos_panel.recargar()
            event.Skip()

        notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, _on_cambiar_pestana)
