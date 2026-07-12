from datetime import date

import pytest

from gestor_credito.calculo.dias360 import dias360

# Cada caso se generó llamando a =DAYS360(A,B) en un Excel real vía COM
# (no se confió solo en la documentación de Microsoft) — ver el docstring de
# dias360() para el porqué. Cubren: el caso real del workbook de referencia,
# fin de mes en 31, fin de febrero (año no bisiesto y bisiesto), doble 31,
# encadenamiento de meses de 30/31 días, mitad de mes y un año calendario
# completo.
CASOS = [
    (date(2025, 7, 3), date(2026, 7, 11), 368),
    (date(2025, 1, 31), date(2025, 2, 28), 28),
    (date(2025, 1, 30), date(2025, 2, 28), 28),
    (date(2025, 2, 28), date(2025, 3, 31), 30),
    (date(2024, 2, 29), date(2025, 2, 28), 358),
    (date(2025, 1, 31), date(2025, 3, 31), 60),
    (date(2025, 3, 31), date(2025, 4, 30), 30),
    (date(2025, 4, 30), date(2025, 5, 31), 30),
    (date(2025, 1, 15), date(2025, 2, 15), 30),
    (date(2025, 1, 1), date(2026, 1, 1), 360),
    (date(2025, 6, 30), date(2025, 7, 31), 30),
]


@pytest.mark.parametrize("inicio,fin,esperado", CASOS)
def test_dias360_contra_excel_real(inicio, fin, esperado):
    assert dias360(inicio, fin) == esperado
