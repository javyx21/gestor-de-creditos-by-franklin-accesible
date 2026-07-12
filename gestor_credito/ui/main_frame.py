import wx

from gestor_credito.db.database import init_db
from gestor_credito.ui.accesibilidad import anunciar_texto_estado, anunciar_voz_nvda, nombre_accesible
from gestor_credito.ui.atajos import ATAJOS
from gestor_credito.ui.ayuda_panel import AyudaPanel
from gestor_credito.ui.calculadora_panel import CalculadoraPanel
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

    def __init__(self, parent, titulo, panel_cls, size=(760, 560)):
        super().__init__(
            parent, title=titulo, size=size,
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
        anunciar_texto_estado(self._status_bar)


class MainFrame(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(900, 650))

        init_db()

        self.CreateStatusBar()
        self.SetStatusText("Listo")

        # Notificaciones/Configuración/Ayuda siguen como diálogos modales
        # desde el menú (pedido explícito del usuario por cómo navega con
        # NVDA, ver CLAUDE.md) — son herramientas de configuración/consulta
        # puntual, no algo que se use en el flujo de trabajo día a día.
        #
        # La Calculadora es distinta: pedido explícito del usuario
        # (2026-07-11), después de probar la primera versión como diálogo de
        # menú: "esto es una función no una configuración", tiene que ser un
        # módulo de primer nivel igual que Casos, no algo escondido en un
        # menú. Por eso acá SÍ vuelve un wx.Notebook con dos pestañas
        # (Casos, Calculadora) — la única pestaña real de la app, todo lo
        # demás sigue siendo diálogo modal.
        self.notebook = wx.Notebook(self)
        nombre_accesible(self.notebook, "Módulos")

        # wx.Notebook exige que cada página tenga al notebook como parent
        # directo (AssertionError real si no: "notebook pages must have
        # notebook as parent") — por eso CasosPanel/CalculadoraPanel se
        # construyen con self.notebook, no con self (MainFrame), a pesar de
        # que casos_panel.py sigue llamando self.GetTopLevelParent() para la
        # barra de estado: eso sube toda la cadena de parents hasta el
        # Frame real sin importar cuántos niveles de Notebook haya en el medio.
        self.casos_panel = CasosPanel(self.notebook)
        self.notebook.AddPage(self.casos_panel, "Casos")
        self.calculadora_panel = CalculadoraPanel(self.notebook)
        self.notebook.AddPage(self.calculadora_panel, "Calculadora de Crédito")
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_cambiar_pestana)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.notebook, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self._crear_menu()
        self._crear_atajos()

    def _on_cambiar_pestana(self, event):
        """Igual que el patrón documentado que tenía la app cuando todo era
        wx.Notebook: cada pestaña recarga sus datos en vivo al entrar, para
        que un cambio hecho en la otra pestaña o en un diálogo (agente
        configurado, tasa de convenio actualizada) se vea sin tener que
        recargar a mano.

        Anuncia además el módulo al que se acaba de entrar — reporte real
        del usuario (2026-07-12): parado en el selector de pestañas NVDA
        solo decía "módulo" sin el nombre concreto, y Ctrl+Tab no anunciaba
        nada en absoluto. Causa: nombre_accesible(self.notebook, "Módulos")
        fija ese nombre fijo para el control de pestañas completo —
        GetName() en _SoloNombreAccesible (accesibilidad.py) ignora el
        childId, así que también pisa el nombre de cada pestaña individual
        en vez de dejar pasar "Casos"/"Calculadora de Crédito" al control
        nativo. Ctrl+Tab, además, cambia de página sin mover el foco al
        control de pestañas, así que ni siquiera ese anuncio nativo (mal)
        llegaba a dispararse. Se usa anunciar_voz_nvda() en vez de intentar
        arreglar el nombre nativo del control: EVT_NOTEBOOK_PAGE_CHANGED
        dispara para cualquier forma de cambiar de página (clic, flechas en
        el selector, o Ctrl+Tab), así que un único anuncio explícito acá
        cubre los tres casos por igual, sin depender de en qué control haya
        quedado el foco — mismo criterio que ya se usa en el resto de la
        app para anuncios que resultaron no ser confiables por la vía
        nativa (ver docstring de anunciar_voz_nvda).

        Confirmado con el usuario y su NVDA real: solo el nombre de la
        pestaña ("Casos", "Calculadora de Crédito"), sin anteponer la
        palabra "Módulo" — la primera versión sí funcionaba pero sonaba
        redundante repetida en cada cambio."""
        indice = event.GetSelection()
        pagina = self.notebook.GetPage(indice)
        if pagina is self.casos_panel:
            self.casos_panel.recargar()
        elif pagina is self.calculadora_panel:
            self.calculadora_panel.recargar()
        anunciar_voz_nvda(self.notebook.GetPageText(indice))
        event.Skip()

    def SetStatusText(self, texto):
        """Override sobre wx.Frame.SetStatusText: además de mostrar el texto,
        dispara el anuncio accesible (ver anunciar_texto_estado) — sin esto,
        cada self.GetTopLevelParent().SetStatusText(...) de los paneles hijos
        seguía siendo mudo para NVDA, igual que en _PanelDialog más arriba."""
        super().SetStatusText(texto)
        anunciar_texto_estado(self.GetStatusBar())

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

        menu_ayuda = wx.Menu()
        item_atajos = menu_ayuda.Append(wx.ID_ANY, "&Atajos de teclado...")
        self.Bind(wx.EVT_MENU, self._on_abrir_ayuda, item_atajos)
        menu_bar.Append(menu_ayuda, "A&yuda")

        self.SetMenuBar(menu_bar)

    def _crear_atajos(self):
        """Arma el wx.AcceleratorTable de la ventana a partir del registro
        central de gestor_credito/ui/atajos.py (única fuente de verdad,
        compartida con la pestaña Ayuda). Cada entrada apunta a un método
        público de CasosPanel — ver ese diccionario más abajo — para no
        necesitar un import circular entre atajos.py y este módulo.

        ATAJOS también documenta mnemónicos de botón/menú y atajos "de
        sistema" que ya funcionan solos (ver atajos.py): esas filas traen
        accion=None y se saltan acá, no necesitan un binding.

        Solo tiene efecto con foco dentro de MainFrame: mientras un diálogo
        modal (Notificaciones/Configuración) está abierto, Windows enruta el
        teclado ahí primero, así que estos atajos quedan inactivos sin
        necesidad de deshabilitarlos a mano.
        """
        acciones = {
            "enfocar_busqueda": self.casos_panel.enfocar_busqueda,
            "enfocar_resultados": self.casos_panel.enfocar_resultados,
            "limpiar_busqueda": self.casos_panel.limpiar_busqueda,
        }

        entradas = []
        for modificador, tecla, _texto, _seccion, _descripcion, accion in ATAJOS:
            if accion is None:
                continue
            id_atajo = wx.NewIdRef()
            self.Bind(wx.EVT_MENU, self._crear_manejador_atajo(acciones[accion]), id=id_atajo)
            entradas.append(wx.AcceleratorEntry(modificador, tecla, id_atajo))

        self.SetAcceleratorTable(wx.AcceleratorTable(entradas))

    @staticmethod
    def _crear_manejador_atajo(metodo):
        return lambda event: metodo()

    def _on_abrir_notificaciones(self, event):
        self._abrir_dialogo("Notificaciones", NotificacionesPanel)

    def _on_abrir_configuracion(self, event):
        self._abrir_dialogo("Configuración", ConfiguracionPanel)

    def _on_abrir_ayuda(self, event):
        self._abrir_dialogo("Ayuda", AyudaPanel)

    def _abrir_dialogo(self, titulo, panel_cls, size=(760, 560)):
        with _PanelDialog(self, titulo, panel_cls, size=size) as dialogo:
            dialogo.ShowModal()

        # Al cerrar, Casos se recarga siempre: un cambio de agente en
        # Configuración o una alerta marcada en Notificaciones debe reflejarse
        # sin que el usuario tenga que volver a apretar "Buscar" a mano (mismo
        # criterio que antes aplicaba EVT_NOTEBOOK_PAGE_CHANGED con pestañas).
        self.casos_panel.recargar()
        self.SetStatusText("Listo")
