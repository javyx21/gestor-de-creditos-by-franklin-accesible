import openpyxl

from gestor_credito.export.excel_export import exportar_reporte_mensual


def _resultado_de_ejemplo():
    return {
        "desembolsados": [
            {
                "nombre": "Juan Perez", "cedula": "001", "empresa_convenio": "MIDESA",
                "microseguro": "Sí", "motivo_no_aplica": None, "fecha": "2026-08-20",
            },
        ],
        "con_microseguro": 1,
        "sin_microseguro": 0,
        "no_aplica": [
            {
                "nombre": "Ana Lopez", "cedula": "002", "empresa_convenio": "MIDESA",
                "microseguro": "No", "motivo_no_aplica": "Ingresos insuficientes",
                "fecha": "2026-08-05",
            },
        ],
        "cliente_desistio": [],
        "pendientes": [
            {
                "nombre": "Beto Cruz", "cedula": "003", "empresa_convenio": "MIDESA",
                "microseguro": "No", "motivo_no_aplica": None, "fecha": None,
            },
        ],
    }


def test_exportar_reporte_mensual_crea_hoja_resumen_y_detalle(tmp_path):
    ruta = tmp_path / "reporte.xlsx"
    exportar_reporte_mensual(_resultado_de_ejemplo(), "Agosto", 2026, "Maria Gomez", str(ruta))

    wb = openpyxl.load_workbook(ruta)
    assert wb.sheetnames == ["Resumen", "Desembolsados", "No aplica", "Cliente desistio", "Pendientes"]

    resumen = wb["Resumen"]
    valores_resumen = [fila[0].value for fila in resumen.iter_rows()]
    assert "Reporte Mensual de Casos" in valores_resumen

    desembolsados = wb["Desembolsados"]
    assert desembolsados["A1"].value == "Nombre"
    assert desembolsados["A2"].value == "Juan Perez"
    assert desembolsados["F2"].value == "2026-08-20"

    pendientes = wb["Pendientes"]
    assert pendientes["A2"].value == "Beto Cruz"
    assert pendientes["F2"].value is None
