import hashlib
import json
import urllib.error

import pytest

from gestor_credito.actualizador import actualizador


class _RespuestaFalsa:
    def __init__(self, contenido_bytes):
        self._contenido = contenido_bytes

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._contenido


def _version_json(version="1.5.0", url="https://ejemplo.invalido/app.zip", sha256="abc123"):
    return json.dumps({"version": version, "url": url, "sha256": sha256}).encode("utf-8")


# ---- verificar_actualizacion ----------------------------------------------


def test_verificar_actualizacion_encuentra_version_mas_nueva(monkeypatch):
    monkeypatch.setattr(
        actualizador.urllib.request, "urlopen",
        lambda url, timeout=10: _RespuestaFalsa(_version_json(version="9.9.9")),
    )

    resultado = actualizador.verificar_actualizacion("https://ejemplo.invalido/version.json")

    assert resultado is not None
    assert resultado.version == "9.9.9"
    assert resultado.url_descarga == "https://ejemplo.invalido/app.zip"
    assert resultado.sha256 == "abc123"


def test_verificar_actualizacion_ya_esta_actualizado(monkeypatch):
    monkeypatch.setattr(
        actualizador.urllib.request, "urlopen",
        lambda url, timeout=10: _RespuestaFalsa(_version_json(version=actualizador.VERSION)),
    )

    resultado = actualizador.verificar_actualizacion("https://ejemplo.invalido/version.json")

    assert resultado is None


def test_verificar_actualizacion_version_remota_mas_vieja(monkeypatch):
    monkeypatch.setattr(
        actualizador.urllib.request, "urlopen",
        lambda url, timeout=10: _RespuestaFalsa(_version_json(version="0.0.1")),
    )

    resultado = actualizador.verificar_actualizacion("https://ejemplo.invalido/version.json")

    assert resultado is None


def test_verificar_actualizacion_sin_url_configurada(monkeypatch):
    monkeypatch.setattr(actualizador, "URL_VERSION_JSON", "")
    with pytest.raises(RuntimeError, match="URL de actualizaciones"):
        actualizador.verificar_actualizacion("")


def test_verificar_actualizacion_error_de_red(monkeypatch):
    def _urlopen_falla(url, timeout=10):
        raise urllib.error.URLError("sin conexión")

    monkeypatch.setattr(actualizador.urllib.request, "urlopen", _urlopen_falla)

    with pytest.raises(RuntimeError, match="No se pudo conectar"):
        actualizador.verificar_actualizacion("https://ejemplo.invalido/version.json")


def test_verificar_actualizacion_json_invalido(monkeypatch):
    monkeypatch.setattr(
        actualizador.urllib.request, "urlopen",
        lambda url, timeout=10: _RespuestaFalsa(b"esto no es json"),
    )

    with pytest.raises(RuntimeError, match="no es válido"):
        actualizador.verificar_actualizacion("https://ejemplo.invalido/version.json")


def test_verificar_actualizacion_campos_incompletos(monkeypatch):
    contenido = json.dumps({"version": "9.9.9"}).encode("utf-8")
    monkeypatch.setattr(
        actualizador.urllib.request, "urlopen",
        lambda url, timeout=10: _RespuestaFalsa(contenido),
    )

    with pytest.raises(RuntimeError, match="incompleto"):
        actualizador.verificar_actualizacion("https://ejemplo.invalido/version.json")


def test_verificar_actualizacion_version_remota_no_numerica(monkeypatch):
    monkeypatch.setattr(
        actualizador.urllib.request, "urlopen",
        lambda url, timeout=10: _RespuestaFalsa(_version_json(version="no-es-version")),
    )

    with pytest.raises(RuntimeError, match="inválido"):
        actualizador.verificar_actualizacion("https://ejemplo.invalido/version.json")


# ---- descargar_actualizacion -----------------------------------------------


def test_descargar_actualizacion_checksum_correcto(monkeypatch, tmp_path):
    contenido = b"contenido de prueba del zip"
    sha256_esperado = hashlib.sha256(contenido).hexdigest()

    def _urlretrieve_falso(url, destino):
        with open(destino, "wb") as archivo:
            archivo.write(contenido)

    monkeypatch.setattr(actualizador.urllib.request, "urlretrieve", _urlretrieve_falso)

    destino = tmp_path / "actualizacion.zip"
    actualizador.descargar_actualizacion("https://ejemplo.invalido/app.zip", sha256_esperado, destino)

    assert destino.exists()
    assert destino.read_bytes() == contenido


def test_descargar_actualizacion_checksum_no_coincide(monkeypatch, tmp_path):
    def _urlretrieve_falso(url, destino):
        with open(destino, "wb") as archivo:
            archivo.write(b"contenido distinto al esperado")

    monkeypatch.setattr(actualizador.urllib.request, "urlretrieve", _urlretrieve_falso)

    destino = tmp_path / "actualizacion.zip"
    with pytest.raises(RuntimeError, match="checksum"):
        actualizador.descargar_actualizacion("https://ejemplo.invalido/app.zip", "0" * 64, destino)

    assert not destino.exists()


def test_descargar_actualizacion_error_de_red(monkeypatch, tmp_path):
    def _urlretrieve_falla(url, destino):
        raise urllib.error.URLError("sin conexión")

    monkeypatch.setattr(actualizador.urllib.request, "urlretrieve", _urlretrieve_falla)

    destino = tmp_path / "actualizacion.zip"
    with pytest.raises(RuntimeError, match="No se pudo descargar"):
        actualizador.descargar_actualizacion("https://ejemplo.invalido/app.zip", "0" * 64, destino)


# ---- aplicar_actualizacion --------------------------------------------------


def test_aplicar_actualizacion_fuera_de_version_empaquetada(monkeypatch, tmp_path):
    monkeypatch.delattr(actualizador.sys, "frozen", raising=False)

    with pytest.raises(RuntimeError, match="versión empaquetada"):
        actualizador.aplicar_actualizacion(tmp_path / "actualizacion.zip")


def test_aplicar_actualizacion_sin_updater_presente(monkeypatch, tmp_path):
    monkeypatch.setattr(actualizador.sys, "frozen", True, raising=False)
    monkeypatch.setattr(actualizador.sys, "executable", str(tmp_path / "GestorDeCredito.exe"), raising=False)

    with pytest.raises(RuntimeError, match="No se encontró el actualizador"):
        actualizador.aplicar_actualizacion(tmp_path / "actualizacion.zip")


def test_aplicar_actualizacion_lanza_el_updater(monkeypatch, tmp_path):
    ruta_exe_principal = tmp_path / "GestorDeCredito.exe"
    ruta_exe_principal.touch()
    (tmp_path / actualizador.NOMBRE_UPDATER).touch()

    monkeypatch.setattr(actualizador.sys, "frozen", True, raising=False)
    monkeypatch.setattr(actualizador.sys, "executable", str(ruta_exe_principal), raising=False)

    llamadas = []
    monkeypatch.setattr(actualizador.subprocess, "Popen", lambda args: llamadas.append(args))

    ruta_zip = tmp_path / "actualizacion.zip"
    actualizador.aplicar_actualizacion(ruta_zip)

    assert len(llamadas) == 1
    argumentos = llamadas[0]
    assert argumentos[0] == str(tmp_path / actualizador.NOMBRE_UPDATER)
    assert argumentos[2] == str(ruta_zip)
    assert argumentos[3] == str(tmp_path)
    assert argumentos[4] == str(ruta_exe_principal)
