"""Exportación a PDF de un cálculo de crédito ya realizado en la Calculadora
(gestor_credito/ui/calculadora_panel.py) — pedido explícito del usuario
(2026-08-21): un archivo imprimible para adjuntar al expediente físico/
digital del cliente, ya que la Calculadora en sí es deliberadamente
independiente y no guarda nada (ver CalculadoraPanel).

Sin acceso a DB/UI, igual que excel_export.py/word_export.py: recibe los
datos ya armados (lista de etiqueta/valor) y una ruta de archivo — el
llamador decide qué campos incluir y en qué orden."""

from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

TITULO = "Cálculo de Crédito"


def generar_pdf_calculo(ruta, campos, fecha_hora=None):
    """Genera un PDF de una sola sección (con salto de página automático si
    hace falta) con `campos`: una lista de tuplas (etiqueta, valor) en el
    orden exacto en que deben imprimirse. No valida ni interpreta los
    campos — esa decisión (qué incluir, qué excluir) es del llamador, ver
    CalculadoraPanel._construir_datos_calculo. En particular, ningún aviso
    transitorio de la UI (como "copiado al portapapeles") debe llegar
    nunca hasta acá."""
    fecha_hora = fecha_hora or datetime.now()

    c = canvas.Canvas(ruta, pagesize=letter)
    ancho, alto = letter
    margen = 2 * cm
    y = alto - margen

    c.setFont("Helvetica-Bold", 14)
    c.drawString(margen, y, TITULO)
    y -= 0.9 * cm

    c.setFont("Helvetica", 9)
    c.drawString(margen, y, f"Generado: {fecha_hora.strftime('%d/%m/%Y %H:%M')}")
    y -= 1.0 * cm

    c.setFont("Helvetica", 11)
    for etiqueta, valor in campos:
        if y < margen:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = alto - margen
        c.drawString(margen, y, f"{etiqueta}: {valor}")
        y -= 0.7 * cm

    c.showPage()
    c.save()
