"""Proceso actualizador externo, empaquetado APARTE de la app principal
(pyinstaller --onefile, ver CLAUDE.md sección Actualizaciones) — deliberadamente
sin ningún import de gestor_credito: el .exe principal en ejecución no puede
sobrescribirse a sí mismo en Windows, así que este script existe solo para
correr desde un proceso totalmente distinto mientras el principal ya cerró.

Se invoca como:
    GestorDeCredito_Updater.exe <pid_app_principal> <ruta_zip> <carpeta_app> <ruta_exe_principal>

(ver aplicar_actualizacion() en gestor_credito/actualizador/actualizador.py,
que arma exactamente esta lista de argumentos).

--onefile a propósito, no --onedir como la app principal: si este updater
tuviera su propia carpeta _internal/ conviviendo con la de GestorDeCredito.exe
dentro de la misma carpeta, empaquetarlas juntas sin colisión de archivos
compartidos por PyInstaller es innecesariamente frágil para un ejecutable que
casi nunca cambia. Como solo usa la librería estándar (zipfile/subprocess/
sys/time/pathlib), el costo de arranque de --onefile (autoextracción a una
carpeta temporal) no importa acá: se ejecuta una vez, de forma esporádica, no
en el flujo de uso diario de la app.

Importante para quien arme el .zip de cada actualización: el .zip debe
contener el contenido de dist/GestorDeCredito/ SIN este mismo
GestorDeCredito_Updater.exe (ver CLAUDE.md) — extraerlo se sobrescribiría a
sí mismo mientras está corriendo, el mismo problema que este script existe
para evitarle a GestorDeCredito.exe.
"""

import subprocess
import sys
import time
import zipfile
from pathlib import Path

_TIMEOUT_ESPERA_CIERRE_SEGUNDOS = 30


def _proceso_sigue_vivo(pid):
    """Sondea tasklist en vez de un handle de proceso (evita depender de
    psutil, que no es una dependencia de este proyecto) — funciona igual de
    bien para un chequeo puntual de "¿ya cerró?", no algo que se llame en un
    bucle ajustado."""
    try:
        resultado = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return str(pid) in resultado.stdout


_INTENTOS_EXTRACCION = 5
_ESPERA_ENTRE_INTENTOS_SEGUNDOS = 1.0


def _registrar(ruta_log, mensaje):
    """Este proceso corre sin consola (--onefile, invocado con Popen desde
    la app principal) — si algo falla acá, antes no quedaba ningún rastro en
    ningún lado, ni para el usuario ni para investigar después. Un log de
    texto plano junto a la app es la forma más simple de que un fallo silente
    dejara de ser completamente invisible. No lanza si no puede escribir
    (por ejemplo, carpeta_app sin permisos de escritura) — un log que falla
    no debe tumbar el proceso de actualización en sí."""
    try:
        with open(ruta_log, "a", encoding="utf-8") as archivo:
            archivo.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {mensaje}\n")
    except OSError:
        pass


def main():
    if len(sys.argv) != 5:
        return 1

    pid_principal = int(sys.argv[1])
    ruta_zip = Path(sys.argv[2])
    carpeta_app = Path(sys.argv[3])
    ruta_exe_principal = Path(sys.argv[4])
    ruta_log = carpeta_app / "GestorDeCredito_Updater.log"

    # Windows no deja sobrescribir un .exe/.dll mientras el proceso que lo
    # tiene abierto sigue vivo — hay que confirmar la salida real del
    # proceso principal, no solo confiar en que ya se pidió el cierre.
    limite = time.time() + _TIMEOUT_ESPERA_CIERRE_SEGUNDOS
    while _proceso_sigue_vivo(pid_principal) and time.time() < limite:
        time.sleep(0.5)

    # Real reporte de usuario (2026-08-20): tras "Actualizar ahora", la app
    # quedó en un estado peor que antes — ni actualizada ni el .zip
    # descargado, sin ningún rastro de qué pasó. Causas reales identificadas
    # acá, ambas corregidas:
    if _proceso_sigue_vivo(pid_principal):
        # 1. Si el proceso principal nunca llegó a cerrar del todo (podía
        #    pasar sin que nada lo avisara), la versión anterior intentaba
        #    extraer igual — sobre un .exe todavía abierto, eso revienta con
        #    PermissionError sin capturar, dejando la extracción a medias y
        #    sin relanzar nada. Ahora se aborta ANTES de tocar archivos y se
        #    relanza la app vieja tal cual estaba, en vez de arriesgar una
        #    carpeta a medio actualizar.
        _registrar(
            ruta_log,
            f"El proceso principal (PID {pid_principal}) seguía vivo tras "
            f"{_TIMEOUT_ESPERA_CIERRE_SEGUNDOS}s de espera. Se aborta la "
            "actualización sin modificar archivos.",
        )
        subprocess.Popen([str(ruta_exe_principal)], cwd=str(carpeta_app))
        return 1

    # 2. Aunque tasklist ya no liste el proceso, Windows puede tardar un
    #    instante extra en soltar el handle del archivo (una condición de
    #    carrera real, no solo teórica) — extraer inmediatamente después
    #    podía toparse con el mismo PermissionError sin capturar. Ahora se
    #    reintenta unas pocas veces con una pequeña espera entre intentos
    #    antes de rendirse.
    ultimo_error = None
    for intento in range(1, _INTENTOS_EXTRACCION + 1):
        try:
            with zipfile.ZipFile(ruta_zip, "r") as zip_actualizacion:
                zip_actualizacion.extractall(carpeta_app)
            ultimo_error = None
            break
        except (PermissionError, OSError) as exc:
            ultimo_error = exc
            _registrar(ruta_log, f"Intento {intento}/{_INTENTOS_EXTRACCION} de extracción falló: {exc}")
            if intento < _INTENTOS_EXTRACCION:
                time.sleep(_ESPERA_ENTRE_INTENTOS_SEGUNDOS)

    if ultimo_error is not None:
        # Se agotaron los reintentos: no se borra el .zip (permite reintentar
        # más adelante sin volver a descargar) y se relanza la app vieja para
        # que el usuario nunca se quede sin ninguna versión funcionando.
        _registrar(
            ruta_log,
            f"Se agotaron los {_INTENTOS_EXTRACCION} intentos de extracción "
            f"({ultimo_error}). Se relanza la app sin aplicar la actualización.",
        )
        subprocess.Popen([str(ruta_exe_principal)], cwd=str(carpeta_app))
        return 1

    ruta_zip.unlink(missing_ok=True)
    _registrar(ruta_log, "Actualización aplicada correctamente.")

    subprocess.Popen([str(ruta_exe_principal)], cwd=str(carpeta_app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
