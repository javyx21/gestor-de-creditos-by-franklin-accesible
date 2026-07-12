import pytest

from gestor_credito.db import database
from gestor_credito.db.calculo_credito import guardar_simulacion, obtener_simulacion


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    connection = database.get_connection()
    yield connection
    connection.close()


@pytest.fixture
def caso_id(conn):
    conn.execute("INSERT INTO cliente (cedula, nombre) VALUES ('001-000000-0000A', 'Cliente Prueba')")
    cliente_id = conn.execute("SELECT id FROM cliente WHERE cedula = '001-000000-0000A'").fetchone()[0]
    conn.execute(
        "INSERT INTO caso (cliente_id, clave_caso, empresa_convenio) VALUES (?, 'CASO-1', 'IMMSA')",
        (cliente_id,),
    )
    conn.commit()
    return conn.execute("SELECT id FROM caso WHERE clave_caso = 'CASO-1'").fetchone()[0]


def _datos_simulacion(**overrides):
    datos = dict(
        empresa_convenio="IMMSA",
        tasa_interes=0.36,
        fecha_ingreso_empresa="2020-03-15",
        salario_bruto_cordobas=15000,
        ingresos_extra_cordobas=0,
        monto_credito_usd=1500,
        plazo_meses=12,
        periodicidad="Mensual",
        tipo_cambio=36.6243,
        deuda_activa_cordobas=0,
        pasivo_laboral_cordobas=75000,
        salario_neto_cordobas=13107.5,
        cuota_usd=153.04,
        cobertura_pasivo_laboral=0.732486,
        nivel_endeudamiento=0.427623,
    )
    datos.update(overrides)
    return datos


def test_sin_simulacion_guardada_devuelve_none(conn, caso_id):
    assert obtener_simulacion(conn, caso_id) is None


def test_guardar_y_obtener_simulacion(conn, caso_id):
    guardar_simulacion(conn, caso_id, _datos_simulacion())

    resultado = obtener_simulacion(conn, caso_id)
    assert resultado["empresa_convenio"] == "IMMSA"
    assert resultado["cuota_usd"] == 153.04
    assert resultado["nivel_endeudamiento"] == pytest.approx(0.427623)


def test_guardar_de_nuevo_pisa_la_anterior_sin_dejar_historial(conn, caso_id):
    guardar_simulacion(conn, caso_id, _datos_simulacion(monto_credito_usd=1500, cuota_usd=153.04))
    guardar_simulacion(conn, caso_id, _datos_simulacion(monto_credito_usd=2000, cuota_usd=204.05))

    resultado = obtener_simulacion(conn, caso_id)
    assert resultado["monto_credito_usd"] == 2000
    assert resultado["cuota_usd"] == 204.05

    total = conn.execute("SELECT COUNT(*) FROM calculo_credito WHERE caso_id = ?", (caso_id,)).fetchone()[0]
    assert total == 1
