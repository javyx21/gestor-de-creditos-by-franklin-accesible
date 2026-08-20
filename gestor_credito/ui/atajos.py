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
        "Ir al cuadro de búsqueda de Casos (Cédula o nombre) — atajo GLOBAL cuyo "
        "efecto depende de la pestaña activa (pedido explícito del usuario, "
        "2026-07-12), ver también la fila de Historial de Créditos",
        "enfocar_busqueda",
    ),
    (
        None, None, "Ctrl+F", "Historial de Créditos",
        "Ir al cuadro de búsqueda de Historial de Créditos (Cédula o nombre) — "
        "mismo atajo físico que en Casos, cada pestaña define su propio efecto "
        "(en Calculadora no hace nada, no hay un cuadro de búsqueda ahí)",
        None,
    ),
    (
        wx.ACCEL_CTRL, ord("R"), "Ctrl+R", "Casos",
        "Ir a la lista de resultados de Casos — atajo GLOBAL cuyo efecto depende de "
        "la pestaña activa (pedido explícito del usuario, 2026-07-12), ver también la "
        "fila de Historial de Créditos",
        "enfocar_resultados",
    ),
    (
        None, None, "Ctrl+R", "Historial de Créditos",
        "Ir a la lista de resultados de Historial de Créditos — mismo atajo físico "
        "que en Casos, cada pestaña define su propio efecto (en Calculadora no hace "
        "nada, no hay una lista de resultados ahí)",
        None,
    ),
    (
        wx.ACCEL_CTRL, ord("D"), "Ctrl+D", "General",
        "Limpiar/vaciar los campos del módulo activo — atajo GLOBAL, ÚNICO y "
        "congruente en toda la app (pedido explícito del usuario, 2026-08-16: "
        "\"unifica el comando para limpiar formularios o campos en todos los "
        "módulos... que funcione como el único gesto global para limpiar de "
        "forma congruente\"; reemplaza los atajos previos Alt+L, global pero "
        "distinto por pestaña, y Alt+V, mnemónico local del botón \"Vaciar "
        "búsqueda\" en Casos/Historial de Créditos — ninguno de los dos sigue "
        "activo). En Casos vacía la búsqueda, el filtro por alerta Y el cuadro "
        "de edición del caso seleccionado juntos (antes eran dos acciones "
        "separadas); en Calculadora limpia todos los campos de entrada "
        "conservando la última empresa convenio elegida; en Historial de "
        "Créditos vacía la búsqueda y los tres filtros y vuelve a la vista por "
        "defecto (créditos en estado Corriente)",
        "limpiar_busqueda",
    ),
    (
        wx.ACCEL_CTRL, ord("1"), "Ctrl+1", "General",
        "Ir directo a la pestaña Casos, sin importar cuál esté activa (pedido "
        "explícito del usuario, 2026-08-16, navegación rápida entre pestañas "
        "distinta de Ctrl+Tab, que solo avanza/retrocede en orden)",
        "ir_a_casos",
    ),
    (
        wx.ACCEL_CTRL, ord("2"), "Ctrl+2", "General",
        "Ir directo a la pestaña Calculadora de Crédito, sin importar cuál "
        "esté activa",
        "ir_a_calculadora",
    ),
    (
        wx.ACCEL_CTRL, ord("3"), "Ctrl+3", "General",
        "Ir directo a la pestaña Historial de Créditos, sin importar cuál "
        "esté activa",
        "ir_a_creditos",
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
        None, None, "Flecha arriba / abajo (en árbol de categorías)", "Configuración",
        "Moverse entre las categorías Configuración de Casos / Configuración de la "
        "Calculadora — navegación nativa del árbol, no cambia todavía la sección "
        "mostrada",
        None,
    ),
    (
        None, None, "Enter (en árbol de categorías)", "Configuración",
        "Activar (mostrar) la sección de la categoría seleccionada, sin mover el foco",
        None,
    ),
    (
        None, None, "Tab (en árbol de categorías)", "Configuración",
        "Activar la sección seleccionada y pasar el foco directo a su primer campo "
        "editable",
        None,
    ),
    (
        None, None, "Alt+G (en Configuración de la Calculadora)", "Configuración",
        "Guardar (crear o actualizar) la empresa convenio y tasa de los campos, y "
        "anunciar por voz la confirmación",
        None,
    ),
    (
        None, None, "Enter (en el cuadro de Tasa de interés)", "Configuración",
        "Guardar la tasa directamente sin tener que ir hasta el botón, y anunciar por "
        "voz \"Tasa actualizada\"",
        None,
    ),
    (
        None, None, "Alt+N (en Configuración de la Calculadora)", "Configuración",
        "Limpiar los campos para dar de alta una empresa convenio nueva",
        None,
    ),
    (
        None, None, "Alt+R (en Configuración de la Calculadora)", "Configuración",
        "Eliminar la empresa convenio seleccionada (pide confirmación)",
        None,
    ),
    (
        None, None, "Alt+S (en Configuración de Reporte de Créditos)", "Configuración",
        "Elegir el archivo Excel del reporte de créditos a importar",
        None,
    ),
    (
        None, None, "Alt+I (en Configuración de Reporte de Créditos)", "Configuración",
        "Importar el reporte de créditos del archivo Excel seleccionado",
        None,
    ),
    (
        None, None, "Alt+Y, A", "Ayuda",
        "Abrir esta pantalla de Ayuda con la lista de atajos de teclado",
        None,
    ),
    (
        None, None, "Alt+Y, C", "Ayuda",
        "Desplegar el submenú Actualizaciones (Buscar actualizaciones / "
        "Información sobre la versión) — no abre ninguna pantalla por sí solo, "
        "es un submenú nativo, se navega con flechas igual que cualquier menú "
        "de Windows",
        None,
    ),
    (
        None, None, "Alt+Y, C, B", "Ayuda",
        "Buscar actualizaciones disponibles (compara la versión instalada contra "
        "la publicada en el link de descarga configurado). Si encuentra una "
        "versión más nueva, abre una pantalla aparte (\"Actualización "
        "disponible\") con las novedades y el botón para instalarla",
        None,
    ),
    (
        None, None, "Alt+Y, C, I", "Ayuda",
        "Información sobre la versión: muestra la versión instalada y, si ya se "
        "buscaron actualizaciones antes en esta sesión, qué se encontró la "
        "última vez — sin volver a consultar la red",
        None,
    ),
    (
        None, None, "Alt+I (en \"Actualización disponible\")", "Ayuda",
        "Descargar, verificar y aplicar la actualización encontrada — cierra la "
        "aplicación para instalarla y la vuelve a abrir sola. Solo aparece en la "
        "pantalla \"Actualización disponible\", que a su vez solo se abre cuando "
        "\"Buscar actualizaciones\" encuentra algo más nuevo",
        None,
    ),
    (
        None, None, "Ctrl+Tab / Ctrl+Shift+Tab", "Calculadora",
        "Alternar entre las pestañas Casos, Calculadora de Crédito e Historial de "
        "Créditos, en orden (adelante/atrás) — todas son pestañas de primer nivel, "
        "no diálogos de menú (pedido explícito del usuario, 2026-07-11: \"esto es "
        "una función no una configuración\", mismo criterio aplicado a Historial de "
        "Créditos el 2026-07-12). Al llegar a cada una, se anuncia por voz su "
        "nombre. Para ir directo a una pestaña específica sin importar el orden, "
        "ver Ctrl+1/Ctrl+2/Ctrl+3 más arriba (sección General)",
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
        None, None, "Ctrl+Shift+E", "Calculadora",
        "Anunciar por voz únicamente el nombre de la empresa convenio elegida (sin la "
        "tasa), sin mover el foco",
        None,
    ),
    (
        None, None, "Ctrl+Shift+R", "Calculadora",
        "Calcular (pasivo laboral, salario neto, cuota y endeudamiento con los datos "
        "ingresados) y anunciar por voz el resultado — único atajo de teclado para "
        "calcular; el botón \"Calcular\" ya no tiene mnemónico (antes Alt+A, retirado "
        "2026-07-12 para no duplicar la misma acción, pedido explícito del usuario: "
        "\"no dupliques funciones\")",
        None,
    ),
    (
        None, None, "Enter / Espacio (en Empresa convenio)", "Calculadora",
        "Confirmar la empresa resaltada y anunciar por voz \"Seleccionada {empresa}\", sin "
        "repetir la tasa — al navegar con las flechas, NVDA ya anuncia nombre y tasa de "
        "cada opción por su cuenta",
        None,
    ),
    (
        None, None, "Ctrl+T", "Calculadora",
        "Copiar al portapapeles el resumen de la operación calculada (monto, plazo y "
        "cuota QUINCENAL aproximada) y anunciar por voz que se copió — la cuota se "
        "calcula siempre con periodicidad Quincenal para este resumen, sin importar qué "
        "esté elegido en el combo Periodicidad del formulario; exige los mismos datos "
        "completos que \"Calcular\" (empresa con tasa, fecha de ingreso, salario, monto, "
        "plazo)",
        None,
    ),
    (
        None, None, "Ctrl+Shift+T", "Calculadora",
        "Igual que Ctrl+T, pero con la cuota MENSUAL aproximada en vez de la quincenal",
        None,
    ),
    (
        None, None, "Alt+B (en Historial de Créditos)", "Historial de Créditos",
        "Ejecutar la búsqueda con el término escrito (botón Buscar)",
        None,
    ),
    (
        None, None, "Enter (con foco en el cuadro de búsqueda)", "Historial de Créditos",
        "Ejecutar la búsqueda, igual que el botón Buscar",
        None,
    ),
    (
        None, None, "Esc", "General",
        "Cerrar el diálogo abierto (Notificaciones/Configuración/Ayuda) y volver a Casos",
        None,
    ),
]
