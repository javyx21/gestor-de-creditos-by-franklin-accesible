import wx

from gestor_credito.db.database import init_db
from gestor_credito.ui.casos_panel import CasosPanel
from gestor_credito.ui.configuracion_panel import ConfiguracionPanel
from gestor_credito.ui.notificaciones_panel import NotificacionesPanel


class MainFrame(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(900, 650))

        init_db()

        self.CreateStatusBar()
        self.SetStatusText("Listo")

        notebook = wx.Notebook(self)
        casos_panel = CasosPanel(notebook)
        notificaciones_panel = NotificacionesPanel(notebook)
        notebook.AddPage(casos_panel, "Casos")
        notebook.AddPage(notificaciones_panel, "Notificaciones")
        notebook.AddPage(ConfiguracionPanel(notebook), "Configuración")

        # Recargar cada pestaña con datos en vivo al entrar a ella, para que un
        # cambio hecho en otra (agente en Configuración, marcar documentos
        # completados en Notificaciones) se refleje sin depender de que el
        # usuario recuerde volver a apretar "Buscar"/"Actualizar" a mano.
        def _on_cambiar_pestana(event):
            pagina = notebook.GetPage(event.GetSelection())
            if pagina is casos_panel:
                casos_panel.recargar()
            elif pagina is notificaciones_panel:
                notificaciones_panel.recargar()
            event.Skip()

        notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, _on_cambiar_pestana)
