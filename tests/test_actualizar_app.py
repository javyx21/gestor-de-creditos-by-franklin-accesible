"""Pruebas de updater/actualizar_app.py — el proceso actualizador externo,
stdlib puro (ver su propio docstring). Reescrito 2026-08-20 tras un reporte
real: después de "Actualizar ahora", la app quedó peor que antes (ni
actualizada ni el .zip descargado, sin rastro de qué pasó). Dos causas reales
identificadas y corregidas acá, ambas cubiertas por pruebas:

1. Si el proceso principal nunca terminaba de cerrar, la versión anterior
   igual intentaba extraer sobre un .exe todavía abierto — PermissionError
   sin capturar, extracción a medias, nada relanzado.
2. Aunque tasklist ya no listara el proceso, Windows podía tardar un
   instante extra en soltar el handle del archivo — la extracción inmediata
   podía toparse con el mismo error.

Estas pruebas llaman main() directo (no el .exe compilado — eso ya se probó
por separado con builds reales de PyInstaller, ver CLAUDE.md) contra archivos
y carpetas reales en tmp_path, monkeypatcheando solo _proceso_sigue_vivo (no
hay ningún proceso real que esperar) y subprocess.Popen (no hay ningún .exe
real que relanzar)."""

import zipfile

import pytest

from updater import actualizar_app


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    # Ninguna prueba necesita esperar de verdad los timeouts/reintentos reales.
    monkeypatch.setattr(actualizar_app, "_TIMEOUT_ESPERA_CIERRE_SEGUNDOS", 0)
    monkeypatch.setattr(actualizar_app, "_ESPERA_ENTRE_INTENTOS_SEGUNDOS", 0)


def _crear_zip_de_prueba(tmp_path, nombre_archivo="app.txt", contenido=b"version nueva"):
    ruta_zip = tmp_path / "actualizacion.zip"
    with zipfile.ZipFile(ruta_zip, "w") as z:
        z.writestr(nombre_archivo, contenido)
    return ruta_zip


def _argv(monkeypatch, pid, ruta_zip, carpeta_app, ruta_exe):
    monkeypatch.setattr(
        actualizar_app.sys, "argv",
        ["GestorDeCredito_Updater.exe", str(pid), str(ruta_zip), str(carpeta_app), str(ruta_exe)],
    )


def test_main_extrae_y_relanza_cuando_el_proceso_ya_cerro(tmp_path, monkeypatch):
    monkeypatch.setattr(actualizar_app, "_proceso_sigue_vivo", lambda pid: False)
    carpeta_app = tmp_path / "GestorDeCredito"
    carpeta_app.mkdir()
    ruta_exe = carpeta_app / "GestorDeCredito.exe"
    ruta_exe.write_bytes(b"exe viejo")
    ruta_zip = _crear_zip_de_prueba(tmp_path)

    llamadas_popen = []
    monkeypatch.setattr(actualizar_app.subprocess, "Popen", lambda args, **kw: llamadas_popen.append((args, kw)))

    _argv(monkeypatch, 1234, ruta_zip, carpeta_app, ruta_exe)
    codigo = actualizar_app.main()

    assert codigo == 0
    assert (carpeta_app / "app.txt").read_bytes() == b"version nueva"
    assert not ruta_zip.exists()
    assert len(llamadas_popen) == 1
    assert llamadas_popen[0][0] == [str(ruta_exe)]


def test_main_aborta_sin_tocar_archivos_si_el_proceso_principal_sigue_vivo(tmp_path, monkeypatch):
    monkeypatch.setattr(actualizar_app, "_proceso_sigue_vivo", lambda pid: True)
    carpeta_app = tmp_path / "GestorDeCredito"
    carpeta_app.mkdir()
    ruta_exe = carpeta_app / "GestorDeCredito.exe"
    ruta_exe.write_bytes(b"exe viejo")
    ruta_zip = _crear_zip_de_prueba(tmp_path)

    llamadas_popen = []
    monkeypatch.setattr(actualizar_app.subprocess, "Popen", lambda args, **kw: llamadas_popen.append((args, kw)))

    _argv(monkeypatch, 1234, ruta_zip, carpeta_app, ruta_exe)
    codigo = actualizar_app.main()

    assert codigo == 1
    # No se tocó nada: ni se extrajo el zip, ni se borró.
    assert not (carpeta_app / "app.txt").exists()
    assert ruta_zip.exists()
    # Igual se relanza la app (la vieja, sin actualizar) para no dejar al
    # usuario sin nada funcionando.
    assert len(llamadas_popen) == 1
    assert llamadas_popen[0][0] == [str(ruta_exe)]
    # Queda un rastro de por qué no se aplicó.
    log = (carpeta_app / "GestorDeCredito_Updater.log").read_text(encoding="utf-8")
    assert "seguía vivo" in log


def test_main_reintenta_extraccion_si_el_archivo_sigue_bloqueado_un_instante(tmp_path, monkeypatch):
    # Simula la condición de carrera real: tasklist ya no ve el proceso,
    # pero el primer intento de extraer igual falla (Windows no soltó el
    # handle todavía) — el segundo intento sí tiene que funcionar.
    monkeypatch.setattr(actualizar_app, "_proceso_sigue_vivo", lambda pid: False)
    carpeta_app = tmp_path / "GestorDeCredito"
    carpeta_app.mkdir()
    ruta_exe = carpeta_app / "GestorDeCredito.exe"
    ruta_exe.write_bytes(b"exe viejo")
    ruta_zip = _crear_zip_de_prueba(tmp_path)

    intentos_realizados = []
    extractall_original = zipfile.ZipFile.extractall

    def _extractall_falla_una_vez(self, path):
        intentos_realizados.append(1)
        if len(intentos_realizados) == 1:
            raise PermissionError("archivo en uso")
        return extractall_original(self, path)

    monkeypatch.setattr(zipfile.ZipFile, "extractall", _extractall_falla_una_vez)
    monkeypatch.setattr(actualizar_app.subprocess, "Popen", lambda args, **kw: None)

    _argv(monkeypatch, 1234, ruta_zip, carpeta_app, ruta_exe)
    codigo = actualizar_app.main()

    assert codigo == 0
    assert len(intentos_realizados) == 2
    assert (carpeta_app / "app.txt").read_bytes() == b"version nueva"
    assert not ruta_zip.exists()


def test_main_se_rinde_tras_agotar_los_reintentos_y_relanza_la_app_vieja(tmp_path, monkeypatch):
    monkeypatch.setattr(actualizar_app, "_proceso_sigue_vivo", lambda pid: False)
    carpeta_app = tmp_path / "GestorDeCredito"
    carpeta_app.mkdir()
    ruta_exe = carpeta_app / "GestorDeCredito.exe"
    ruta_exe.write_bytes(b"exe viejo")
    ruta_zip = _crear_zip_de_prueba(tmp_path)

    monkeypatch.setattr(
        zipfile.ZipFile, "extractall",
        lambda self, path: (_ for _ in ()).throw(PermissionError("bloqueado para siempre")),
    )
    llamadas_popen = []
    monkeypatch.setattr(actualizar_app.subprocess, "Popen", lambda args, **kw: llamadas_popen.append(args))

    _argv(monkeypatch, 1234, ruta_zip, carpeta_app, ruta_exe)
    codigo = actualizar_app.main()

    assert codigo == 1
    # El .zip NO se borra: permite reintentar más tarde sin volver a
    # descargar — perderlo acá sería el mismo "queda peor que antes" que
    # reportó el usuario.
    assert ruta_zip.exists()
    assert not (carpeta_app / "app.txt").exists()
    assert len(llamadas_popen) == 1
    assert llamadas_popen[0] == [str(ruta_exe)]
    log = (carpeta_app / "GestorDeCredito_Updater.log").read_text(encoding="utf-8")
    assert "Se agotaron los" in log
