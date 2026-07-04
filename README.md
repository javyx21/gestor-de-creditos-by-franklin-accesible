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
