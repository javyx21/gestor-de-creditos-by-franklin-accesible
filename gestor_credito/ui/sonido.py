from pathlib import Path

import wx
import wx.adv

SONIDOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "sonidos"

# Nombres de archivo acordados con el usuario, uno por tipo de alerta.
SONIDO_DOCUMENTOS_PENDIENTES = "datosPendientes.wav"
SONIDO_CONSTANCIA_PENDIENTE = "alerta.wav"
SONIDO_CONSTANCIA_EN_MANO = "alertaMaxima.wav"

# Confirmación audible de "Limpiar búsqueda" en Casos: el usuario pidió un
# sonido al vaciar el cuadro de búsqueda/filtro para saber que sí se borró,
# sin depender de leer la barra de estado a mano.
SONIDO_LIMPIAR_BUSQUEDA = "borrar.wav"


def reproducir_sonido(nombre_archivo):
    """Reproduce un .wav de gestor_credito/assets/sonidos/ en forma asíncrona.

    Si el archivo todavía no existe en disco (p. ej. no se colocó el .wav
    real), no hace nada: una alerta sin sonido no debe interrumpir el flujo de
    la app ni bloquear la lectura con NVDA.
    """
    ruta = SONIDOS_DIR / nombre_archivo
    if not ruta.exists():
        return

    sonido = wx.adv.Sound(str(ruta))
    if sonido.IsOk():
        sonido.Play(wx.adv.SOUND_ASYNC)
