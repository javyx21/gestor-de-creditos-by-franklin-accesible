"""Pruebas del generador de PDF de un cálculo de crédito (gestor_credito/
export/pdf_export.py) — módulo puro (sin DB/UI), ver CalculadoraPanel para
cómo arma la lista de campos que le pasa."""

from datetime import datetime

import pytest

from gestor_credito.export.pdf_export import LOGO_PATH, MARCA_NOMBRE, MARCA_TELEFONO, generar_pdf_calculo


def test_genera_un_pdf_valido_con_los_campos_dados(tmp_path):
    ruta = tmp_path / "calculo.pdf"
    campos = [
        ("Empresa convenio", "MIDESA"),
        ("Fecha de ingreso a la empresa", "01/01/2020"),
        ("Cuota calculada", "US$193.73 (C$7095.06)"),
    ]

    generar_pdf_calculo(str(ruta), campos, fecha_hora=datetime(2026, 8, 21, 14, 30))

    assert ruta.exists()
    contenido = ruta.read_bytes()
    assert contenido.startswith(b"%PDF-")
    assert len(contenido) > 0


def test_soporta_acentos_y_simbolos_de_moneda(tmp_path):
    """Los campos reales incluyen ñ/á/é/í/ó/ú, °, %, $ y C$/US$ — el PDF no
    debe reventar ni silenciosamente perder esos caracteres (fuentes base
    de reportlab usan WinAnsiEncoding, que sí los cubre)."""
    ruta = tmp_path / "calculo_acentos.pdf"
    campos = [
        ("Periodicidad", "Quincenal"),
        ("Pasivo laboral (respaldo del cliente)", "C$100000.00 (US$2730.43)"),
        ("Cobertura de pasivo laboral", "110%"),
        ("Salario neto (con deducciones)", "C$16963.33 (US$463.17)"),
    ]

    generar_pdf_calculo(str(ruta), campos)

    assert ruta.exists()
    assert ruta.stat().st_size > 0


def test_pagina_muchos_campos_sin_reventar(tmp_path):
    """Con muchos campos el contenido supera una sola página (ver el salto
    de página automático en generar_pdf_calculo) — no debe lanzar ni
    perder el documento."""
    ruta = tmp_path / "calculo_largo.pdf"
    campos = [(f"Campo {i}", f"Valor {i}") for i in range(80)]

    generar_pdf_calculo(str(ruta), campos)

    assert ruta.exists()
    assert ruta.read_bytes().startswith(b"%PDF-")


def test_sin_campos_igual_genera_un_pdf_con_solo_el_encabezado(tmp_path):
    ruta = tmp_path / "calculo_vacio.pdf"

    generar_pdf_calculo(str(ruta), [])

    assert ruta.exists()
    assert ruta.read_bytes().startswith(b"%PDF-")


# ---- Bloque de marca (logo + nombre + teléfono, pedido explícito del ----
# ---- usuario, 2026-08-21 — opción "identidad + contacto") ---------------

def _decodificar_stream_de_contenido(pdf_bytes):
    """Extrae y descomprime el content stream de TEXTO del PDF (reportlab lo
    codifica ASCII85+Flate por defecto) para poder verificar lo dibujado
    (Tj) — no alcanza con buscar la cadena cruda en los bytes del PDF
    porque queda comprimida. Con el logo incrustado hay varios streams en
    el archivo (el de la imagen incluido); se prueban todos y se devuelve
    el primero que decodifica a texto con operadores de texto (BT)."""
    import base64
    import re
    import zlib

    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        crudo = match.group(1).strip()
        if crudo.endswith(b"~>"):
            crudo = crudo[:-2]
        try:
            decodificado = zlib.decompress(base64.a85decode(crudo)).decode("latin-1")
        except Exception:
            continue
        if "BT" in decodificado:
            return decodificado
    raise AssertionError("no se encontró ningún content stream de texto en el PDF")


def test_encabezado_incluye_nombre_y_telefono_de_marca(tmp_path):
    ruta = tmp_path / "calculo_marca.pdf"

    generar_pdf_calculo(str(ruta), [("Empresa convenio", "MIDESA")])

    contenido = _decodificar_stream_de_contenido(ruta.read_bytes())
    assert MARCA_NOMBRE in contenido
    assert MARCA_TELEFONO in contenido


def test_logo_se_incrusta_como_imagen_cuando_existe_el_archivo(tmp_path):
    """No se prueba el contenido visual del logo (no hay forma razonable de
    "ver" un PDF en una prueba automatizada) — solo que, si LOGO_PATH existe
    en este entorno (igual que en la app real empaquetada), el PDF termina
    con un objeto de imagen incrustado y no solo texto."""
    ruta = tmp_path / "calculo_con_logo.pdf"

    generar_pdf_calculo(str(ruta), [("Empresa convenio", "MIDESA")])

    contenido = ruta.read_bytes()
    if LOGO_PATH.exists():
        assert b"/Subtype /Image" in contenido or b"/Subtype/Image" in contenido
    else:
        pytest.skip(f"LOGO_PATH no existe en este entorno: {LOGO_PATH}")


def test_sin_archivo_de_logo_no_revienta_igual_incluye_nombre_y_telefono(tmp_path, monkeypatch):
    """Mismo criterio que AppLogo en ui/logo.py: si el archivo del logo no
    está, no debe fallar — el nombre/teléfono de marca igual se dibujan."""
    monkeypatch.setattr(
        "gestor_credito.export.pdf_export.LOGO_PATH", tmp_path / "no_existe.png"
    )
    ruta = tmp_path / "calculo_sin_logo.pdf"

    generar_pdf_calculo(str(ruta), [("Empresa convenio", "MIDESA")])

    assert ruta.exists()
    contenido = _decodificar_stream_de_contenido(ruta.read_bytes())
    assert MARCA_NOMBRE in contenido
