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


def main():
    if len(sys.argv) != 5:
        return 1

    pid_principal = int(sys.argv[1])
    ruta_zip = Path(sys.argv[2])
    carpeta_app = Path(sys.argv[3])
    ruta_exe_principal = Path(sys.argv[4])

    # Windows no deja sobrescribir un .exe/.dll mientras el proceso que lo
    # tiene abierto sigue vivo — hay que confirmar la salida real del
    # proceso principal, no solo confiar en que ya se pidió el cierre.
    limite = time.time() + _TIMEOUT_ESPERA_CIERRE_SEGUNDOS
    while _proceso_sigue_vivo(pid_principal) and time.time() < limite:
        time.sleep(0.5)

    with zipfile.ZipFile(ruta_zip, "r") as zip_actualizacion:
        zip_actualizacion.extractall(carpeta_app)

    ruta_zip.unlink(missing_ok=True)

    subprocess.Popen([str(ruta_exe_principal)], cwd=str(carpeta_app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
