from pathlib import Path

import wx
import wx.adv

SONIDOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "sonidos"

# Nombres de archivo acordados con el usuario, uno por tipo de alerta.
SONIDO_DOCUMENTOS_PENDIENTES = "datosPendientes.wav"
SONIDO_CONSTANCIA_PENDIENTE = "alerta.wav"
SONIDO_CONSTANCIA_EN_MANO = "alertaMaxima.wav"

# Confirmación audible de cualquier acción de borrado en Casos: "Limpiar
# búsqueda" (vaciar el cuadro de búsqueda/filtro) y "Eliminar cliente" (borrar
# un cliente y sus casos) comparten este mismo sonido — el usuario pidió un
# aviso audible para saber que sí se borró, sin depender de leer la barra de
# estado a mano.
SONIDO_BORRAR = "borrar.wav"

# Distinto de SONIDO_DOCUMENTOS_PENDIENTES (datosPendientes.wav, que suena una
# sola vez al abrir/actualizar Notificaciones si hay alguna alerta activa).
# Este suena en Casos cada vez que el usuario navega con el lector de pantalla
# hasta una fila cuyo cliente todavía tiene documentos pendientes — pedido
# explícito del usuario (ciego, navega con NVDA) como equivalente auditivo del
# resaltado en rojo que ve un vidente en esa misma fila, para no depender de
# que alguien le lea la lista de Notificaciones para enterarse.
SONIDO_FILA_DOCUMENTOS_PENDIENTES = "documentoPendiente.wav"


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
