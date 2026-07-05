import wx

from gestor_credito.ui.atajos import ATAJOS
from gestor_credito.ui.logo import AppLogo


class AyudaPanel(wx.Panel):
    """Lista de referencia de TODOS los atajos de teclado documentados de la
    app (ver gestor_credito/ui/atajos.py — única fuente de verdad: globales
    de Casos, mnemónicos de botón/menú de cualquier pantalla, y atajos de
    sistema como Esc). Un wx.ListCtrl de 3 columnas (Atajo, Sección, Acción),
    igual de estilo que la lista de Casos, para que NVDA pueda recorrerla
    celda por celda con Ctrl+Alt+flechas como ya hace en esa pantalla — mismo
    patrón, no una tabla nueva con reglas distintas. La columna Sección deja
    ubicar de un vistazo en qué pantalla vive cada atajo (p. ej. "Importar"
    está en Configuración, no en Casos)."""

    def __init__(self, parent):
        super().__init__(parent)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(AppLogo(self), 0, wx.ALIGN_LEFT | wx.ALL, 4)

        titulo = wx.StaticText(self, label="Ayuda — Atajos de teclado")
        titulo.SetFont(titulo.GetFont().Bold())
        sizer.Add(titulo, 0, wx.ALL, 8)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.lista.SetName("Lista de atajos de teclado")
        self.lista.InsertColumn(0, "Atajo")
        self.lista.InsertColumn(1, "Sección")
        self.lista.InsertColumn(2, "Acción")
        for _modificador, _tecla, texto, seccion, descripcion, _accion in ATAJOS:
            indice = self.lista.InsertItem(self.lista.GetItemCount(), texto)
            self.lista.SetItem(indice, 1, seccion)
            self.lista.SetItem(indice, 2, descripcion)
        self.lista.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self.lista.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
        self.lista.SetColumnWidth(2, wx.LIST_AUTOSIZE_USEHEADER)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
