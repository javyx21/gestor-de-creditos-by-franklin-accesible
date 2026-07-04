from openpyxl import Workbook


def export_to_excel(rows, headers, output_path):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(output_path)
