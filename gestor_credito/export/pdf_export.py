"""Exportación a PDF de un cálculo de crédito ya realizado en la Calculadora
(gestor_credito/ui/calculadora_panel.py) — pedido explícito del usuario
(2026-08-21): un archivo imprimible para adjuntar al expediente físico/
digital del cliente, ya que la Calculadora en sí es deliberadamente
independiente y no guarda nada (ver CalculadoraPanel).

Sin acceso a DB/UI, igual que excel_export.py/word_export.py: recibe los
datos ya armados (lista de etiqueta/valor) y una ruta de archivo — el
llamador decide qué campos incluir y en qué orden."""

from datetime import datetime
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

TITULO = "Cálculo de Crédito"

# Bloque de marca en el encabezado — pedido explícito del usuario
# (2026-08-21), opción "identidad + contacto" de las 5 presentadas: que el
# PDF quede autosuficiente si se encuentra suelto en un expediente, sin
# depender de estar archivado junto a otros papeles. Mismo logo que
# ui/logo.py (misma resolución de ruta relativa al paquete, funciona igual
# en fuente y empaquetado con PyInstaller — ver LOGO_PATH ahí).
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
MARCA_NOMBRE = "Franklin Accesible"
MARCA_TELEFONO = "+505 5771 4938"

# El archivo real de LOGO_PATH es de 2048x2048px (~2 MB) — de sobra para
# imprimirlo a 1.6cm de lado, pero incrustarlo así de grande infla cada PDF
# a varios MB sin ninguna ganancia de calidad visible en ese tamaño. Se
# reduce con PIL antes de incrustarlo (mismo criterio que AppLogo en
# ui/logo.py, que también lo escala antes de mostrarlo) — 300px alcanza
# sobrado incluso para impresión a buena resolución en 1.6cm.
_LOGO_MAX_PX = 300


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

    # Encabezado de marca: logo a la izquierda, nombre y teléfono a su
    # derecha en la misma franja — si el archivo del logo no existe (mismo
    # criterio que AppLogo en ui/logo.py) se omite la imagen sin fallar,
    # el nombre y el teléfono igual quedan.
    logo_lado = 1.6 * cm
    texto_x = margen
    if LOGO_PATH.exists():
        logo_reducido = Image.open(LOGO_PATH)
        logo_reducido.thumbnail((_LOGO_MAX_PX, _LOGO_MAX_PX))
        c.drawImage(
            ImageReader(logo_reducido), margen, y - logo_lado, width=logo_lado, height=logo_lado,
            preserveAspectRatio=True, mask="auto",
        )
        texto_x = margen + logo_lado + 0.4 * cm

    c.setFont("Helvetica-Bold", 13)
    c.drawString(texto_x, y - 0.5 * cm, MARCA_NOMBRE)
    c.setFont("Helvetica", 9)
    c.drawString(texto_x, y - 1.05 * cm, MARCA_TELEFONO)
    y -= logo_lado + 0.5 * cm

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
