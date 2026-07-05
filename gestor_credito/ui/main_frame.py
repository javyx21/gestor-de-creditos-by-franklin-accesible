import wx

from gestor_credito.db.database import init_db
from gestor_credito.ui.casos_panel import CasosPanel
from gestor_credito.ui.configuracion_panel import ConfiguracionPanel
from gestor_credito.ui.notificaciones_panel import NotificacionesPanel


class _PanelDialog(wx.Dialog):
    """Diálogo modal genérico que aloja un panel existente (Notificaciones,
    Configuración) — se abre desde el menú en vez de vivir como pestaña. Igual
    que un wx.Frame, pero modal: bloquea Casos hasta que se cierra, como
    "Herramientas > Opciones" en cualquier app de Windows (pedido explícito
    del usuario, acostumbrado a navegar así con NVDA).

    wx.Dialog no trae CreateStatusBar()/SetStatusText() como wx.Frame (eso es
    específico de wx.Frame), pero los paneles alojados llaman
    self.GetTopLevelParent().SetStatusText(...) — acá GetTopLevelParent()
    devuelve este diálogo, no MainFrame. Se agrega un wx.StatusBar manual y se
    expone SetStatusText() para que ese código no necesite cambiar.
    """

    def __init__(self, parent, titulo, panel_cls):
        super().__init__(
            parent, title=titulo, size=(760, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        # El status bar se crea ANTES que el panel a propósito: el panel
        # (NotificacionesPanel, ConfiguracionPanel) llama a
        # self.GetTopLevelParent().SetStatusText(...) desde su propio
        # __init__, y ese __init__ corre durante panel_cls(self) más abajo —
        # si _status_bar no existe todavía en ese momento, SetStatusText()
        # revienta con AttributeError (bug real encontrado al validar esto).
        self._status_bar = wx.StatusBar(self)
        panel = panel_cls(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        sizer.Add(self._status_bar, 0, wx.EXPAND)
        self.SetSizer(sizer)

        # Un wx.Dialog modal normalmente cierra con Escape "gratis", pero acá
        # adentro hay controles nativos (wx.Choice, wx.TreeCtrl) que pueden
        # quedarse con la tecla antes de que llegue al cierre por defecto —
        # mismo tipo de problema ya visto con Enter en el combobox de agente
        # (ver configuracion_panel.py). Se engancha EVT_CHAR_HOOK acá para
        # garantizar que Escape SIEMPRE cierre el diálogo y devuelva el foco a
        # Casos, sin importar qué control tenga el foco en ese momento
        # (reporte real del usuario: no había forma de cerrar Configuración
        # sin cerrar todo el programa).
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def SetStatusText(self, texto):
        self._status_bar.SetStatusText(texto)


class MainFrame(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(900, 650))

        init_db()

        self.CreateStatusBar()
        self.SetStatusText("Listo")

        # Ventana principal = directamente Casos, sin pestañas: Notificaciones
        # y Configuración pasan a ser diálogos que se abren desde un menú
        # clásico de Windows (Alt + flechas), en vez de wx.Notebook — pedido
        # explícito del usuario por cómo navega con NVDA.
        self.casos_panel = CasosPanel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.casos_panel, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self._crear_menu()

    def _crear_menu(self):
        menu_bar = wx.MenuBar()

        menu_herramientas = wx.Menu()
        item_notificaciones = menu_herramientas.Append(wx.ID_ANY, "&Notificaciones...")
        self.Bind(wx.EVT_MENU, self._on_abrir_notificaciones, item_notificaciones)
        menu_bar.Append(menu_herramientas, "&Herramientas")

        menu_configuracion = wx.Menu()
        item_configuracion = menu_configuracion.Append(wx.ID_ANY, "&Configuración...")
        self.Bind(wx.EVT_MENU, self._on_abrir_configuracion, item_configuracion)
        menu_bar.Append(menu_configuracion, "&Configuración")

        self.SetMenuBar(menu_bar)

    def _on_abrir_notificaciones(self, event):
        self._abrir_dialogo("Notificaciones", NotificacionesPanel)

    def _on_abrir_configuracion(self, event):
        self._abrir_dialogo("Configuración", ConfiguracionPanel)

    def _abrir_dialogo(self, titulo, panel_cls):
        with _PanelDialog(self, titulo, panel_cls) as dialogo:
            dialogo.ShowModal()

        # Al cerrar, Casos se recarga siempre: un cambio de agente en
        # Configuración o una alerta marcada en Notificaciones debe reflejarse
        # sin que el usuario tenga que volver a apretar "Buscar" a mano (mismo
        # criterio que antes aplicaba EVT_NOTEBOOK_PAGE_CHANGED con pestañas).
        self.casos_panel.recargar()
        self.SetStatusText("Listo")
