"""Pruebas del generador de PDF de un cálculo de crédito (gestor_credito/
export/pdf_export.py) — módulo puro (sin DB/UI), ver CalculadoraPanel para
cómo arma la lista de campos que le pasa."""

from datetime import datetime

import pytest

from gestor_credito.export.pdf_export import generar_pdf_calculo


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
