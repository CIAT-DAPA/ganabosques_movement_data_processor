# -*- coding: utf-8 -*-
"""
Tests del orquestador save_movements() y de las ramas de
procesar_csv_movimientos() que el camino feliz no recorre.

save_movements() abre su propia conexión a MongoDB, por eso se parchea
`connect` (conftest ya dejó mongoengine apuntando a mongomock y una segunda
llamada a connect con otros parámetros sería rechazada).
"""
import os
import sys
import glob
import pathlib
from datetime import datetime

import pandas as pd
import pytest
from unittest.mock import patch, Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import save_movement.save_movement as sm
from save_movement.save_movement import save_movements, procesar_csv_movimientos

from ganabosques_orm.collections.farm import Farm
from ganabosques_orm.collections.enterprise import Enterprise
from ganabosques_orm.collections.movement import Movement
from ganabosques_orm.collections.sourcemovement import SourceMovement
from ganabosques_orm.collections.adm2 import Adm2
from ganabosques_orm.collections.adm3 import Adm3
from ganabosques_orm.auxiliaries.log import Log
from ganabosques_orm.auxiliaries.extidfarm import ExtIdFarm
from ganabosques_orm.auxiliaries.extidenterprise import ExtIdEnterprise
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.label import Label
from ganabosques_orm.enums.farmsource import FarmSource
from ganabosques_orm.enums.typeenterprise import TypeEnterprise
from ganabosques_orm.enums.valuechain import ValueChain

SIT = Source.SIT_CODE.value
PROD = Source.PRODUCER_ID.value
UNIT = Label.PRODUCTIONUNIT_ID.value


@pytest.fixture
def mongo_connect_ok():
    """Neutraliza el connect() interno dejando viva la conexión de mongomock."""
    with patch.object(sm, "connect") as mock_connect:
        yield mock_connect


@pytest.fixture
def entidades_base():
    """Un Farm (SIT S1 / PRODUCER P1) y un Enterprise centro de acopio (E1)."""
    now = datetime.now()
    farm = Farm(
        adm3_id=Adm3.objects(ext_id="010101").first(),
        ext_id=[
            ExtIdFarm(source=Source.SIT_CODE, ext_code="S1"),
            ExtIdFarm(source=Source.PRODUCER_ID, ext_code="P1"),
        ],
        farm_source=FarmSource.SIGMA,
        value_chain=ValueChain.LIVESTOCK.value,
        log=Log(enable=True, created=now, updated=now),
    )
    farm.save()

    enterprise = Enterprise(
        name="Centro Acopio",
        latitude=4.5,
        longitud=-75.0,
        adm2_id=Adm2.objects(ext_id="0202").first(),
        type_enterprise=TypeEnterprise.COLLECTION_CENTER,
        ext_id=[ExtIdEnterprise(label=Label.PRODUCTIONUNIT_ID, ext_code="E1")],
        value_chain=ValueChain.LIVESTOCK.value,
        log=Log(enable=True, created=now, updated=now),
    )
    enterprise.save()
    return farm, enterprise


def _fila_movimiento(**overrides):
    fila = {
        "EXT_ID": "MOV1",
        "DATE": "2024-06-01",
        "TIPO_ORIGEN": "FARM",
        "TIPO_DESTINO": "COLLECTION_CENTER",
        "ESPECIE": "bovinos",
        f"{SIT}_ORIGEN": "S1",
        f"{PROD}_ORIGEN": "P1",
        f"{SIT}_DESTINO": "",
        f"{PROD}_DESTINO": "E1",
        "TERNEROS": 5,
    }
    fila.update(overrides)
    return fila


def _escribir_movimientos(path, filas):
    pd.DataFrame(filas).to_csv(path, index=False)
    return str(path)


def _armar_arbol(tmp_path, con_farms=True, con_enterprise=True, con_movement=True,
                 nombres_validos=True):
    root = tmp_path / "root"
    fe = tmp_path / "farm_ent"

    if con_farms:
        d = fe / "farms"
        d.mkdir(parents=True)
        nombre = "new_farms_to_create.csv" if nombres_validos else "otra_cosa.csv"
        pd.DataFrame([{SIT: "S1", PROD: "P1", "ADM3": "010101", "TIPO": "FARM"}]).to_csv(
            d / nombre, index=False)

    if con_enterprise:
        d = fe / "enterprise"
        d.mkdir(parents=True)
        nombre = "new_enterprise.csv" if nombres_validos else "otra_cosa.csv"
        pd.DataFrame([{
            "TIPO": "COLLECTION_CENTER", UNIT: "E1", "ADM2": "0202",
            "NOMBRE": "Centro Acopio", "LATITUD": 4.5, "LONGITUD": -75.0,
        }]).to_csv(d / nombre, index=False)

    if con_movement:
        d = root / "movement"
        d.mkdir(parents=True)
        nombre = "movement_data_base_2024.csv" if nombres_validos else "otra_cosa.csv"
        _escribir_movimientos(d / nombre, [_fila_movimiento()])

    return root, fe


# =========================================================
# save_movements: flujo completo
# =========================================================

def test_save_movements_flujo_completo(tmp_path, mongo_connect_ok):
    root, fe = _armar_arbol(tmp_path)
    out = tmp_path / "out"

    save_movements(str(root), str(out), str(fe), "SIGMA")

    assert Farm.objects.count() == 1
    assert Enterprise.objects.count() == 1

    mov = Movement.objects(ext_id="MOV1").first()
    assert mov is not None
    assert mov.farm_id_origin is not None
    assert mov.enterprise_id_destination is not None
    assert mov.movement[0].amount == 5

    resumen = glob.glob(os.path.join(str(out), "movements_save_summary_*.csv"))
    assert len(resumen) == 1
    df = pd.read_csv(resumen[0])
    assert df.iloc[0]["filas_insertadas"] == 1


def test_save_movements_error_de_conexion_propaga(tmp_path):
    root, fe = _armar_arbol(tmp_path)
    with patch.object(sm, "connect", side_effect=RuntimeError("sin red")):
        with pytest.raises(RuntimeError):
            save_movements(str(root), str(fe / "out"), str(fe), "SIGMA")


def test_save_movements_sin_carpetas_farms_ni_enterprise(tmp_path, mongo_connect_ok,
                                                         entidades_base):
    root, fe = _armar_arbol(tmp_path, con_farms=False, con_enterprise=False)
    out = tmp_path / "out"

    save_movements(str(root), str(out), str(fe), "SIGMA")

    assert Movement.objects(ext_id="MOV1").first() is not None


def test_save_movements_carpetas_sin_csv_esperados(tmp_path, mongo_connect_ok,
                                                   entidades_base):
    root, fe = _armar_arbol(tmp_path, nombres_validos=False)
    out = tmp_path / "out"

    save_movements(str(root), str(out), str(fe), "SIGMA")

    # Ningún archivo coincide con los patrones esperados: nada se procesa
    assert Movement.objects.count() == 0
    assert not glob.glob(os.path.join(str(out), "movements_save_summary_*.csv"))


def test_save_movements_sin_carpeta_movement(tmp_path, mongo_connect_ok):
    root, fe = _armar_arbol(tmp_path, con_movement=False)
    out = tmp_path / "out"

    save_movements(str(root), str(out), str(fe), "SIGMA")

    assert Farm.objects.count() == 1
    assert Movement.objects.count() == 0


def test_save_movements_captura_error_de_worker(tmp_path, mongo_connect_ok):
    root, fe = _armar_arbol(tmp_path)
    out = tmp_path / "out"

    with patch.object(sm, "procesar_csv_movimientos",
                      side_effect=RuntimeError("boom")) as mock_proc:
        save_movements(str(root), str(out), str(fe), "SIGMA")

    assert mock_proc.called
    assert not glob.glob(os.path.join(str(out), "movements_save_summary_*.csv"))


def test_save_movements_sin_estadisticas(tmp_path, mongo_connect_ok):
    root, fe = _armar_arbol(tmp_path)
    out = tmp_path / "out"

    with patch.object(sm, "procesar_csv_movimientos", return_value=[]):
        save_movements(str(root), str(out), str(fe), "SIGMA")

    assert not glob.glob(os.path.join(str(out), "movements_save_summary_*.csv"))


# =========================================================
# procesar_csv_movimientos: ramas de error
# =========================================================

def test_procesar_reutiliza_source_movement_existente(tmp_path, entidades_base):
    now = datetime.now()
    SourceMovement(name="SIGMA", log=Log(enable=True, created=now, updated=now)).save()

    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento()])
    procesar_csv_movimientos(csv, str(tmp_path / "out"), "SIGMA")

    assert SourceMovement.objects(name="SIGMA").count() == 1


def test_procesar_fecha_no_parseable_carga_todos_los_ext_ids(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv",
                                [_fila_movimiento(DATE="fecha-mala")])
    out = tmp_path / "out"

    resumen = procesar_csv_movimientos(csv, str(out), "SIGMA")

    assert Movement.objects.count() == 0
    assert resumen[0]["año"] == "sin_fecha"
    assert resumen[0]["filas_error"] == 1
    assert glob.glob(os.path.join(str(out), "*_errores_*.csv"))


def test_procesar_ext_id_vacio(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento(EXT_ID="")])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    errores = glob.glob(os.path.join(str(out), "*_errores_*.csv"))
    assert "EXT_ID vacío" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_procesar_movimiento_ya_existente(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento()])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")
    resumen = procesar_csv_movimientos(csv, str(out), "SIGMA")

    assert Movement.objects.count() == 1
    assert resumen[0]["filas_existentes"] == 1
    assert resumen[0]["filas_insertadas"] == 0


def test_procesar_duplicado_dentro_del_mismo_archivo(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv",
                                [_fila_movimiento(), _fila_movimiento()])
    out = tmp_path / "out"

    resumen = procesar_csv_movimientos(csv, str(out), "SIGMA")

    assert Movement.objects.count() == 1
    assert resumen[0]["filas_existentes"] == 1


def test_procesar_enterprise_origen_no_encontrado(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento(
        TIPO_ORIGEN="COLLECTION_CENTER",
        **{f"{PROD}_ORIGEN": "NO_EXISTE", f"{SIT}_ORIGEN": ""},
    )])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    errores = glob.glob(os.path.join(str(out), "*_errores_*.csv"))
    assert "Enterprise origen" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_procesar_farm_origen_no_encontrado(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento(
        **{f"{SIT}_ORIGEN": "NO_EXISTE", f"{PROD}_ORIGEN": ""},
    )])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    errores = glob.glob(os.path.join(str(out), "*_errores_*.csv"))
    assert "Farm origen" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_procesar_farm_destino_no_encontrado(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento(
        TIPO_DESTINO="FARM",
        **{f"{SIT}_DESTINO": "NO_EXISTE", f"{PROD}_DESTINO": ""},
    )])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    errores = glob.glob(os.path.join(str(out), "*_errores_*.csv"))
    assert "Farm destino" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_procesar_enterprise_destino_no_encontrado(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento(
        **{f"{PROD}_DESTINO": "NO_EXISTE"},
    )])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    errores = glob.glob(os.path.join(str(out), "*_errores_*.csv"))
    assert "Enterprise destino" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_procesar_ignora_cantidades_invalidas(tmp_path, entidades_base):
    """Una columna de ganado vacía se omite; la válida sigue contando."""
    csv = _escribir_movimientos(tmp_path / "mov.csv", [
        _fila_movimiento(TERNEROS=3, NOVILLAS=""),
        _fila_movimiento(EXT_ID="MOV2", TERNEROS=1, NOVILLAS=9),
    ])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    mov1 = Movement.objects(ext_id="MOV1").first()
    assert [c.label for c in mov1.movement] == ["TERNEROS"]
    assert Movement.objects(ext_id="MOV2").first().movement[1].amount == 9


def test_procesar_fila_sin_cantidades_validas(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv", [
        _fila_movimiento(TERNEROS=""),
        _fila_movimiento(EXT_ID="MOV2", TERNEROS=4),
    ])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    errores = glob.glob(os.path.join(str(out), "*_errores_*.csv"))
    assert "sin cantidades" in pd.read_csv(errores[0]).iloc[0]["error"]
    assert Movement.objects.count() == 1


def test_procesar_descarta_cantidades_negativas(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv",
                                [_fila_movimiento(TERNEROS=-2, NOVILLAS=6)])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    mov = Movement.objects(ext_id="MOV1").first()
    assert [c.label for c in mov.movement] == ["NOVILLAS"]


def test_procesar_inserta_por_lotes(tmp_path, entidades_base, monkeypatch):
    """Con BATCH_SIZE pequeño se vacía el lote dentro del bucle, no solo al final."""
    monkeypatch.setattr(sm, "BATCH_SIZE", 1)

    filas = [_fila_movimiento(EXT_ID=f"MOV{i}") for i in range(3)]
    csv = _escribir_movimientos(tmp_path / "mov.csv", filas)
    out = tmp_path / "out"

    resumen = procesar_csv_movimientos(csv, str(out), "SIGMA")

    assert Movement.objects.count() == 3
    assert resumen[0]["filas_insertadas"] == 3


def test_procesar_especie_invalida(tmp_path, entidades_base):
    csv = _escribir_movimientos(tmp_path / "mov.csv",
                                [_fila_movimiento(ESPECIE="equina")])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    errores = glob.glob(os.path.join(str(out), "*_errores_*.csv"))
    assert "ESPECIE" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_procesar_origen_empresa_y_destino_predio(tmp_path, entidades_base):
    """Movimiento inverso: sale de un centro de acopio y llega a un predio."""
    csv = _escribir_movimientos(tmp_path / "mov.csv", [_fila_movimiento(
        TIPO_ORIGEN="COLLECTION_CENTER",
        TIPO_DESTINO="FARM",
        **{f"{SIT}_ORIGEN": "", f"{PROD}_ORIGEN": "E1",
           f"{SIT}_DESTINO": "S1", f"{PROD}_DESTINO": ""},
    )])
    out = tmp_path / "out"

    procesar_csv_movimientos(csv, str(out), "SIGMA")

    mov = Movement.objects(ext_id="MOV1").first()
    assert mov is not None
    assert mov.enterprise_id_origin is not None
    assert mov.farm_id_destination is not None
    assert mov.farm_id_origin is None
    assert mov.enterprise_id_destination is None
