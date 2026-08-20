import os
import subprocess
import tempfile
from pathlib import Path

import wx

from gestor_credito.actualizador.actualizador import (
    aplicar_actualizacion,
    descargar_actualizacion,
    verificar_actualizacion,
)
from gestor_credito.ui.accesibilidad import activar_con_enter, anunciar_voz_nvda, ejecutar_en_segundo_plano, nombre_accesible
from gestor_credito.version import VERSION

# Todo lo de actualizaciones vivía como una sección/árbol dentro de la
# pantalla de Ayuda (ver ayuda_panel.py, historia completa en su docstring).
# Pedido explícito del usuario (2026-08-20), aclarado paso a paso con la
# navegación real de teclado (Alt, flecha derecha hasta Ayuda, flecha abajo,
# flecha derecha para desplegar el submenú...): esto tenía que vivir en un
# SUBMENÚ NATIVO "Ayuda > Actualizaciones ▶" con dos ítems ("Buscar
# actualizaciones" / "Información sobre la versión"), no en un panel o árbol
# dentro de un diálogo. Este módulo no tiene estado propio ni conoce a
# MainFrame — expone funciones que main_frame.py llama directo desde los
# EVT_MENU de esos dos ítems, mismo criterio de separación que calculo/ o
# export/ (sin acoplarse al llamador salvo por el `parent` para diálogos).


class ActualizacionDisponibleDialog(wx.Dialog):
    """"Esa pantalla" que el usuario pidió explícitamente: NO aparece al
    entrar a Ayuda ni tiene un lugar fijo en ningún menú — se abre solo como
    consecuencia de que "Buscar actualizaciones" haya encontrado, en efecto,
    una versión más nueva. Ahí, y solo ahí, es donde va el botón que
    realmente instala ("por eso no te lo mencionaba, porque es lógico que
    tiene que ir en esa pantalla", palabras del usuario)."""

    def __init__(self, parent, actualizacion):
        super().__init__(
            parent, title="Actualización disponible", size=(480, 420),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._actualizacion = actualizacion

        sizer = wx.BoxSizer(wx.VERTICAL)

        version_label = wx.StaticText(
            self,
            label=f"Versión instalada: {VERSION}\nVersión disponible: {actualizacion.version}",
        )
        sizer.Add(version_label, 0, wx.ALL, 12)

        notas_label = wx.StaticText(self, label="Novedades de esta versión:")
        sizer.Add(notas_label, 0, wx.LEFT | wx.RIGHT, 12)

        self.notas_texto = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY,
            value=actualizacion.notas or "La nueva versión no incluyó una descripción de cambios.",
        )
        nombre_accesible(self.notas_texto, "Novedades de la versión disponible")
        sizer.Add(self.notas_texto, 1, wx.EXPAND | wx.ALL, 12)

        self.mensaje = wx.StaticText(self, label="")
        sizer.Add(self.mensaje, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        botones = wx.BoxSizer(wx.HORIZONTAL)
        self.instalar_btn = wx.Button(self, label="&Instalar actualización")
        self.instalar_btn.Bind(wx.EVT_BUTTON, self._on_instalar)
        activar_con_enter(self.instalar_btn)
        botones.Add(self.instalar_btn, 0, wx.RIGHT, 8)

        cerrar_btn = wx.Button(self, id=wx.ID_CANCEL, label="&Cerrar")
        activar_con_enter(cerrar_btn)
        botones.Add(cerrar_btn, 0)
        sizer.Add(botones, 0, wx.ALL, 12)

        self.SetSizer(sizer)

    def _fijar_mensaje(self, texto):
        self.mensaje.SetLabel(texto)
        anunciar_voz_nvda(texto)

    def _on_instalar(self, event):
        self.instalar_btn.Disable()
        self._fijar_mensaje(f"Descargando versión {self._actualizacion.version}...")

        def trabajo():
            destino = Path(tempfile.gettempdir()) / f"GestorDeCredito_{self._actualizacion.version}.zip"
            try:
                descargar_actualizacion(self._actualizacion.url_descarga, self._actualizacion.sha256, destino)
                return True, destino
            except RuntimeError as exc:
                return False, str(exc)

        ejecutar_en_segundo_plano(trabajo, self._on_descarga_completa)

    def _on_descarga_completa(self, resultado):
        exito, valor = resultado

        if not exito:
            self.instalar_btn.Enable()
            self._fijar_mensaje(f"No se pudo descargar la actualización: {valor}")
            wx.MessageBox(valor, "No se pudo descargar la actualización", wx.OK | wx.ICON_ERROR, self)
            return

        try:
            aplicar_actualizacion(valor)
        except RuntimeError as exc:
            self.instalar_btn.Enable()
            self._fijar_mensaje(f"No se pudo aplicar la actualización: {exc}")
            wx.MessageBox(str(exc), "No se pudo aplicar la actualización", wx.OK | wx.ICON_ERROR, self)
            return

        # Mismo motivo que tenía ayuda_panel.py: el anuncio sale ANTES de
        # cerrar la app porque, una vez cerrada, no queda nada corriendo que
        # pueda seguir hablando.
        anunciar_voz_nvda("Actualización descargada. Cerrando la aplicación para aplicarla.")

        # Bug real reportado por el usuario (2026-08-20), reproducido en vivo
        # CUATRO VECES, cada intento descartando la teoría del anterior:
        # 1. wx.Exit() directo — no cerraba.
        # 2. EndModal() + wx.Exit() diferido con wx.CallAfter (teoría: bucle
        #    modal anidado que nunca entrega el CallAfter) — tampoco cerraba.
        # 3. os._exit(0) (teoría: ExitProcess() esperando DLL_PROCESS_DETACH
        #    de alguna de las muchas DLLs nativas empaquetadas) — TAMPOCO
        #    cerraba.
        # 4. ctypes.windll.kernel32.TerminateProcess(GetCurrentProcess(), 0)
        #    directo — TAMPOCO cerraba, a pesar de ser en teoría la llamada
        #    más contundente disponible. Sospecha (no confirmada): en un
        #    ctypes de 64 bits, sin declarar argtypes/restype, tanto el
        #    valor que devuelve GetCurrentProcess() como el que recibe
        #    TerminateProcess() se marshalan por defecto como un entero C de
        #    32 bits — un handle de 64 bits mal truncado ahí puede volver
        #    TerminateProcess() una llamada que falla en silencio.
        #
        # Fix definitivo: en vez de seguir afinando la llamada directa a la
        # API de Win32 (cada intento anterior parecía sólido en el papel y
        # no funcionó en la práctica), se reutiliza el ÚNICO mecanismo que
        # de verdad cerró estos procesos colgados durante todo este
        # diagnóstico en vivo: `taskkill /F /PID <pid>` — lanzado como
        # subproceso contra el propio PID. Verificado empíricamente muchas
        # veces esta misma sesión (siempre cerró lo que ningún otro método
        # lograba cerrar), así que en vez de confiar en una cuarta teoría
        # sin poder probarla antes de publicar, se usa directamente la
        # herramienta que ya demostró funcionar de verdad.
        subprocess.Popen(["taskkill", "/F", "/PID", str(os.getpid())])


def buscar_actualizaciones(parent, al_completar):
    """"Ayuda > Actualizaciones > Buscar actualizaciones". Busca en segundo
    plano para no congelar la barra de mensajes de Windows (y con ella la
    voz de NVDA) mientras la red responde — mismo mecanismo que el resto de
    la app (ejecutar_en_segundo_plano, ver accesibilidad.py).

    `al_completar(valor)` se llama SOLO si la búsqueda terminó con éxito
    (valor=None si ya está actualizado, o el ActualizacionDisponible
    encontrado) — nunca ante un error de red, porque ahí no hay nada nuevo
    que registrar. MainFrame usa esto para que "Información sobre la
    versión" pueda responder sin volver a golpear la red."""
    anunciar_voz_nvda("Buscando actualizaciones...")

    def trabajo():
        try:
            return True, verificar_actualizacion()
        except RuntimeError as exc:
            return False, str(exc)

    def al_terminar(resultado):
        exito, valor = resultado

        if not exito:
            wx.MessageBox(valor, "No se pudo buscar actualizaciones", wx.OK | wx.ICON_ERROR, parent)
            return

        if valor is None:
            al_completar(None)
            wx.MessageBox(
                f"Ya tenés la versión más reciente ({VERSION}).",
                "Sin actualizaciones disponibles", wx.OK | wx.ICON_INFORMATION, parent,
            )
            return

        al_completar(valor)
        # "esa pantalla" — pedido explícito del usuario: el botón que
        # instala solo aparece acá, cuando de verdad hay algo para instalar.
        dialogo = ActualizacionDisponibleDialog(parent, valor)
        dialogo.ShowModal()
        dialogo.Destroy()

    ejecutar_en_segundo_plano(trabajo, al_terminar)


def mostrar_informacion_version(parent, ultima_busqueda_realizada, ultima_actualizacion_encontrada):
    """"Ayuda > Actualizaciones > Información sobre la versión". Consulta
    puntual, sin tocar la red: versión instalada, y si ya se hizo una
    búsqueda antes en esta misma sesión, qué se encontró la última vez
    (incluidas las novedades, si las había) — sin obligar a repetir la
    búsqueda solo para volver a leerlas."""
    lineas = [f"Versión instalada: {VERSION}"]

    if not ultima_busqueda_realizada:
        lineas.append("Todavía no se buscaron actualizaciones en esta sesión.")
    elif ultima_actualizacion_encontrada is None:
        lineas.append("Última búsqueda: ya estabas en la versión más reciente.")
    else:
        lineas.append(f"Última búsqueda: versión {ultima_actualizacion_encontrada.version} disponible.")
        if ultima_actualizacion_encontrada.notas:
            lineas.append("")
            lineas.append("Novedades:")
            lineas.append(ultima_actualizacion_encontrada.notas)

    wx.MessageBox("\n".join(lineas), "Información de la versión", wx.OK | wx.ICON_INFORMATION, parent)
