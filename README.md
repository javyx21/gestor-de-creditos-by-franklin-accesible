# Gestor de Crédito

Aplicación de escritorio para la gestión de créditos, desarrollada en Python.

## Características

- Interfaz gráfica con wxPython, pensada para ser accesible con lectores de pantalla (NVDA).
- Almacenamiento local con SQLite.
- Exportación de reportes a Excel (openpyxl) y Word (python-docx).

## Requisitos

- Python 3.10+
- Windows (uso previsto con NVDA)

## Instalación

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecución

```
python main.py
```

## Pruebas

```
pytest
```

## Empaquetado portable (pendrive)

```
pip install pyinstaller
pyinstaller --name "GestorDeCredito" --windowed --noconfirm --add-data "gestor_credito/assets;gestor_credito/assets" main.py
```

Genera `dist/GestorDeCredito/` (el .exe + la carpeta `_internal/` de soporte).
Copiá la carpeta completa al pendrive — no muevas el .exe suelto fuera de
ella. `data/gestor_credito.db` se crea junto al .exe en el primer inicio y
queda ahí, persistiendo entre ejecuciones aunque se traslade la carpeta a otra
máquina.
