import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from gestor_credito.version import VERSION

# URL ESTABLE de GitHub Releases: cuando exista el repositorio definitivo,
# esto debe apuntar a .../releases/latest/download/version.json — ese alias
# siempre resuelve al asset "version.json" del release marcado "latest", así
# que NO hace falta editar este link en cada release nuevo (requisito: cada
# release real debe incluir un asset con el nombre EXACTO "version.json" y no
# publicarse con --prerelease). Mecanismo ya verificado de punta a punta
# contra un repositorio de prueba real el 2026-08-19 — ver
# "recursos/actualización por franklin accesible.txt". Ese repositorio de
# prueba (javyx21/gestor-de-credito) se BORRÓ el mismo día, a pedido del
# usuario, porque falta validar qué licencia se le va a poner al contenido
# antes de volver a publicar nada — dejar VACÍO hasta que se cree el
# repositorio definitivo con la licencia ya decidida.
URL_VERSION_JSON = ""

NOMBRE_UPDATER = "GestorDeCredito_Updater.exe"


@dataclass
class ActualizacionDisponible:
    version: str
    url_descarga: str
    sha256: str


def _partes_version(texto):
    return tuple(int(parte) for parte in texto.strip().split("."))


def verificar_actualizacion(url_version_json=None):
    """Consulta el version.json remoto y devuelve un ActualizacionDisponible
    si su versión es más nueva que VERSION, o None si ya está actualizado.

    Lanza RuntimeError (nunca la excepción cruda de red/JSON) con un mensaje
    en español apto para mostrar directo en un wx.MessageBox — mismo criterio
    que el resto de los importadores de este proyecto (excel_importer.py,
    reporte_creditos_importer.py), que tampoco dejan escapar excepciones
    técnicas sin traducir hacia la UI."""
    url = url_version_json or URL_VERSION_JSON
    if not url:
        raise RuntimeError(
            "No hay una URL de actualizaciones configurada (URL_VERSION_JSON "
            "en gestor_credito/actualizador/actualizador.py)."
        )

    try:
        with urllib.request.urlopen(url, timeout=10) as respuesta:
            contenido = respuesta.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"No se pudo conectar para buscar actualizaciones: {exc}") from exc

    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"El archivo de versión remoto no es válido: {exc}") from exc

    version_remota = datos.get("version")
    url_descarga = datos.get("url")
    sha256 = datos.get("sha256")
    if not version_remota or not url_descarga or not sha256:
        raise RuntimeError(
            "El archivo de versión remoto está incompleto (falta version, url o sha256)."
        )

    try:
        es_mas_nueva = _partes_version(version_remota) > _partes_version(VERSION)
    except ValueError as exc:
        raise RuntimeError(f"Número de versión remoto inválido: {version_remota!r}") from exc

    if not es_mas_nueva:
        return None
    return ActualizacionDisponible(version=version_remota, url_descarga=url_descarga, sha256=sha256)


def _calcular_sha256(ruta):
    hash_sha256 = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            hash_sha256.update(bloque)
    return hash_sha256.hexdigest()


def descargar_actualizacion(url_descarga, sha256_esperado, destino):
    """Descarga el .zip de la actualización a `destino` (Path) y verifica su
    SHA256 contra `sha256_esperado`. Si no coincide, borra el archivo
    descargado y lanza RuntimeError — mejor no dejar un .zip corrupto/
    interrumpido a medio camino tirado en el disco, que además nunca debe
    llegar a aplicarse."""
    try:
        urllib.request.urlretrieve(url_descarga, destino)
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"No se pudo descargar la actualización: {exc}") from exc

    sha256_real = _calcular_sha256(destino)
    if sha256_real.lower() != sha256_esperado.lower():
        Path(destino).unlink(missing_ok=True)
        raise RuntimeError(
            "El archivo descargado no coincide con el checksum esperado "
            "(posible descarga incompleta o corrupta). Probá de nuevo."
        )


def aplicar_actualizacion(ruta_zip):
    """Lanza el proceso actualizador externo (GestorDeCredito_Updater.exe,
    ver updater/actualizar_app.py) pasándole el PID de este proceso, el .zip
    ya descargado y verificado, la carpeta de la app y la ruta del .exe
    principal para relanzar — y devuelve, sin cerrar nada acá. Quien llama
    (ayuda_panel.py) es responsable de cerrar la aplicación después: este
    módulo es UI-agnóstico (mismo criterio que calculo/ y export/, sin wx),
    así que no puede ser quien decide cómo se cierra la ventana.

    El .exe principal en ejecución no puede sobrescribirse a sí mismo en
    Windows — de ahí que haga falta un proceso aparte que espere a que este
    termine antes de tocar los archivos.

    Solo tiene efecto real en la versión empaquetada (sys.frozen): en
    desarrollo (python main.py) no existe un .exe que relanzar, así que se
    informa con un error claro en vez de fallar de forma confusa."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError(
            "Actualizar solo está disponible en la versión empaquetada (.exe) de la app, "
            "no corriendo desde el código fuente."
        )

    carpeta_app = Path(sys.executable).resolve().parent
    ruta_updater = carpeta_app / NOMBRE_UPDATER
    if not ruta_updater.exists():
        raise RuntimeError(f"No se encontró el actualizador ({ruta_updater}).")

    subprocess.Popen([
        str(ruta_updater),
        str(os.getpid()),
        str(ruta_zip),
        str(carpeta_app),
        str(Path(sys.executable).resolve()),
    ])
