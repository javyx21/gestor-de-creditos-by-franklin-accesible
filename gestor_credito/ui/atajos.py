import wx

# Registro central de TODOS los atajos de teclado documentados de la app, no
# solo los globales de Casos. Hay dos clases mezcladas a propósito en una
# sola lista (única fuente de verdad para MainFrame y para la pestaña
# "Ayuda > Atajos de teclado" en ayuda_panel.py):
#
# 1. Atajos GLOBALES (modificador/tecla/acción completos): combinaciones tipo
#    Ctrl+F que saltan directo a un control específico sin importar qué tenga
#    el foco en ese momento. Estos sí necesitan que MainFrame._crear_atajos()
#    arme un wx.AcceleratorEntry a mano.
# 2. Mnemónicos de un solo botón/menú (p. ej. "&Importar") y atajos "de
#    sistema" ya provistos por wx (Esc cierra el diálogo modal, Enter en el
#    wx.Choice de agente) — esos YA funcionan solos, sin ningún binding
#    adicional; se documentan acá solo para que aparezcan en Ayuda. Sus filas
#    llevan modificador=tecla=acción=None, y MainFrame se las salta al armar
#    el wx.AcceleratorTable.
#
# "sección" identifica en qué pantalla vive cada atajo (Casos, Notificaciones,
# Configuración, Ayuda, o "General" para algo válido en cualquier diálogo
# modal) — es lo que se muestra como columna aparte en Ayuda para poder
# ubicar, por ejemplo, cuál es el atajo para importar el Excel sin tener que
# adivinar que vive en Configuración.
#
# A medida que se sumen más funciones a la app y hagan falta más atajos,
# alcanza con sumar una fila acá en vez de mantener listas sincronizadas a
# mano en dos lugares.
#
# "accion" es una clave de texto, no una referencia directa a un método de
# CasosPanel, para no crear un import circular entre este módulo (importado
# por ayuda_panel.py) y main_frame.py; MainFrame._crear_atajos() resuelve esa
# clave contra los métodos reales del panel al armar la tabla.
ATAJOS = [
    # (modificador wx.ACCEL_* o None, tecla o None, texto, sección, descripción, acción o None)
    (
        wx.ACCEL_CTRL, ord("F"), "Ctrl+F", "Casos",
        "Ir al cuadro de búsqueda de Casos (Cédula o nombre)",
        "enfocar_busqueda",
    ),
    (
        wx.ACCEL_CTRL, ord("R"), "Ctrl+R", "Casos",
        "Ir a la lista de resultados de Casos",
        "enfocar_resultados",
    ),
    (
        wx.ACCEL_ALT, ord("L"), "Alt+L", "Casos",
        "Limpiar la búsqueda y el filtro por alerta de Casos",
        "limpiar_busqueda",
    ),
    (
        None, None, "Alt+B", "Casos",
        "Ejecutar la búsqueda con el término escrito (botón Buscar)",
        None,
    ),
    (
        None, None, "Alt+G", "Casos",
        "Guardar el Estado Solicitud/Etapa Proceso del caso seleccionado",
        None,
    ),
    (
        None, None, "Enter (con foco en el cuadro de búsqueda)", "Casos",
        "Ejecutar la búsqueda, igual que el botón Buscar",
        None,
    ),
    (
        None, None, "Alt+H, N", "Notificaciones",
        "Abrir el diálogo de Notificaciones (menú Herramientas)",
        None,
    ),
    (
        None, None, "Alt+A", "Notificaciones",
        "Recalcular la lista de alertas activas (botón Actualizar)",
        None,
    ),
    (
        None, None, "Alt+M", "Notificaciones",
        "Marcar completados los documentos de la alerta seleccionada",
        None,
    ),
    (
        None, None, "Alt+C, C", "Configuración",
        "Abrir el diálogo de Configuración (menú Configuración)",
        None,
    ),
    (
        None, None, "Alt+G", "Configuración",
        "Guardar y usar el agente seleccionado (botón Guardar y usar este agente)",
        None,
    ),
    (
        None, None, "Enter (con foco en 'Escoge un agente')", "Configuración",
        "Guardar y usar el agente seleccionado, igual que el botón",
        None,
    ),
    (
        None, None, "Alt+S", "Configuración",
        "Elegir el archivo Excel de la bitácora a importar",
        None,
    ),
    (
        None, None, "Alt+I", "Configuración",
        "Importar la bitácora del archivo Excel seleccionado",
        None,
    ),
    (
        None, None, "Alt+Y, A", "Ayuda",
        "Abrir esta pantalla de Ayuda con la lista de atajos de teclado",
        None,
    ),
    (
        None, None, "Ctrl+Tab / Ctrl+Shift+Tab", "Calculadora",
        "Alternar entre las pestañas Casos y Calculadora de Crédito — la Calculadora es "
        "una pestaña de primer nivel, no un diálogo de menú (pedido explícito del "
        "usuario, 2026-07-11: \"esto es una función no una configuración\")",
        None,
    ),
    (
        None, None, "Alt+C", "Calculadora",
        "Calcular pasivo laboral, salario neto, cuota y endeudamiento con los datos ingresados",
        None,
    ),
    (
        None, None, "Ctrl+Shift+Q", "Calculadora",
        "Anunciar por voz el pasivo laboral ya calculado (dólares y córdobas), sin mover "
        "el foco ni tabular hasta el cuadro de Resultados",
        None,
    ),
    (
        None, None, "Ctrl+Shift+W", "Calculadora",
        "Anunciar por voz el salario con deducciones ya calculado (dólares y córdobas), "
        "sin mover el foco ni tabular hasta el cuadro de Resultados",
        None,
    ),
    (
        None, None, "Esc", "General",
        "Cerrar el diálogo abierto (Notificaciones/Configuración/Ayuda) y volver a Casos",
        None,
    ),
]
