# -*- coding: utf-8 -*-
"""
Tests de _process_farm_identifiers y _process_enterprise_identifiers.

Se centran en los caminos de actualización, "sin cambios" y error
(incluido el volcado del CSV de errores), que el test de integración
existente no recorre.
"""
import os
import sys
import glob
import pathlib

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from save_movement.save_movement import (
    _process_farm_identifiers,
    _process_enterprise_identifiers,
    _build_farms_dict,
    _build_enterprises_dict,
)

from ganabosques_orm.collections.farm import Farm
from ganabosques_orm.collections.enterprise import Enterprise
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.label import Label
from ganabosques_orm.enums.typeenterprise import TypeEnterprise

SIT = Source.SIT_CODE.value
PROD = Source.PRODUCER_ID.value
UNIT = Label.PRODUCTIONUNIT_ID.value


def _write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def _error_files(output_dir):
    return glob.glob(os.path.join(str(output_dir), "*_errores_*.csv"))


# =========================================================
# FARMS
# =========================================================

def test_farm_identifiers_crea_columnas_faltantes_y_reporta_error(tmp_path):
    """Sin ADM3 en el CSV la columna se crea vacía y cada fila falla."""
    csv = _write_csv(tmp_path / "farms.csv", [{PROD: "P1"}])
    out = tmp_path / "out"

    _process_farm_identifiers(csv, str(out), "SIGMA", {})

    assert Farm.objects.count() == 0
    errores = _error_files(out)
    assert len(errores) == 1
    df_err = pd.read_csv(errores[0])
    assert "No se encontró Adm3" in df_err.iloc[0]["error"]
    assert df_err.iloc[0]["fila"] == 2


def test_farm_identifiers_farm_source_invalido(tmp_path):
    """Un source desconocido no rompe el proceso: el farm se crea sin farm_source."""
    csv = _write_csv(tmp_path / "farms.csv", [{SIT: "S1", PROD: "P1", "ADM3": "010101"}])
    out = tmp_path / "out"

    _process_farm_identifiers(csv, str(out), "FUENTE_INEXISTENTE", {})

    # farm_source es obligatorio en el ORM, así que la fila termina en errores
    assert Farm.objects.count() == 0
    assert len(_error_files(out)) == 1


def test_farm_identifiers_fila_sin_identificadores(tmp_path):
    csv = _write_csv(tmp_path / "farms.csv", [{SIT: "", PROD: "", "ADM3": "010101"}])
    out = tmp_path / "out"

    _process_farm_identifiers(csv, str(out), "SIGMA", {})

    errores = _error_files(out)
    assert len(errores) == 1
    assert "sin identificadores" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_farm_identifiers_actualiza_adm3_existente(tmp_path):
    """Un farm ya creado cambia de vereda cuando el CSV trae otro ADM3."""
    csv = _write_csv(tmp_path / "farms.csv", [{SIT: "S1", PROD: "P1", "ADM3": "010101"}])
    out = tmp_path / "out"
    _process_farm_identifiers(csv, str(out), "SIGMA", {})

    farm = Farm.objects.first()
    assert farm.adm3_id.ext_id == "010101"

    csv2 = _write_csv(tmp_path / "farms2.csv", [{SIT: "S1", PROD: "P1", "ADM3": "020202"}])
    _process_farm_identifiers(csv2, str(out), "SIGMA", _build_farms_dict())

    assert Farm.objects.count() == 1
    assert Farm.objects.first().adm3_id.ext_id == "020202"


def test_farm_identifiers_agrega_nuevo_ext_id(tmp_path):
    """Si el CSV aporta un identificador extra se añade al farm existente."""
    csv = _write_csv(tmp_path / "farms.csv", [{SIT: "S1", "ADM3": "010101"}])
    out = tmp_path / "out"
    _process_farm_identifiers(csv, str(out), "SIGMA", {})
    assert len(Farm.objects.first().ext_id) == 1

    csv2 = _write_csv(tmp_path / "farms2.csv", [{SIT: "S1", PROD: "P1", "ADM3": "010101"}])
    _process_farm_identifiers(csv2, str(out), "SIGMA", _build_farms_dict())

    farm = Farm.objects.first()
    assert Farm.objects.count() == 1
    assert {e.ext_code for e in farm.ext_id} == {"S1", "P1"}


def test_farm_identifiers_sin_cambios_no_reescribe(tmp_path):
    """Reprocesar el mismo CSV deja el farm intacto."""
    rows = [{SIT: "S1", PROD: "P1", "ADM3": "010101"}]
    csv = _write_csv(tmp_path / "farms.csv", rows)
    out = tmp_path / "out"
    _process_farm_identifiers(csv, str(out), "SIGMA", {})

    farm = Farm.objects.first()
    updated_antes = farm.log.updated

    _process_farm_identifiers(csv, str(out), "SIGMA", _build_farms_dict())

    farm = Farm.objects.first()
    assert Farm.objects.count() == 1
    assert farm.log.updated == updated_antes
    assert not _error_files(out)


# =========================================================
# ENTERPRISES
# =========================================================

def test_enterprise_identifiers_crea_columnas_faltantes_y_reporta_error(tmp_path):
    """Sin ADM2 la columna se crea vacía y la fila va al CSV de errores."""
    csv = _write_csv(tmp_path / "ent.csv", [{UNIT: "E1"}])
    out = tmp_path / "out"

    _process_enterprise_identifiers(csv, str(out), {})

    assert Enterprise.objects.count() == 0
    errores = _error_files(out)
    assert len(errores) == 1
    assert "No se encontró Adm2" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_enterprise_identifiers_fila_sin_identificadores(tmp_path):
    csv = _write_csv(tmp_path / "ent.csv", [{
        "TIPO": "COLLECTION_CENTER", UNIT: "", "ADM2": "0101",
        "NOMBRE": "CC", "LATITUD": 1.0, "LONGITUD": 2.0,
    }])
    out = tmp_path / "out"

    _process_enterprise_identifiers(csv, str(out), {})

    errores = _error_files(out)
    assert len(errores) == 1
    assert "sin identificadores" in pd.read_csv(errores[0]).iloc[0]["error"]


def test_enterprise_identifiers_tipo_desconocido_usa_enterprise(tmp_path):
    csv = _write_csv(tmp_path / "ent.csv", [{
        "TIPO": "ALGO_RARO", UNIT: "E9", "ADM2": "0101",
        "NOMBRE": "Generica", "LATITUD": 1.0, "LONGITUD": 2.0,
    }])
    out = tmp_path / "out"

    _process_enterprise_identifiers(csv, str(out), {})

    ent = Enterprise.objects.first()
    assert ent.type_enterprise == TypeEnterprise.ENTERPRISE


def test_enterprise_identifiers_actualiza_datos(tmp_path):
    rows = [{
        "TIPO": "COLLECTION_CENTER", UNIT: "E1", "ADM2": "0101",
        "NOMBRE": "Centro Viejo", "LATITUD": 1.0, "LONGITUD": 2.0,
    }]
    csv = _write_csv(tmp_path / "ent.csv", rows)
    out = tmp_path / "out"
    _process_enterprise_identifiers(csv, str(out), {})

    rows2 = [{
        "TIPO": "COLLECTION_CENTER", UNIT: "E1", "ADM2": "0202",
        "NOMBRE": "Centro Nuevo", "LATITUD": 9.5, "LONGITUD": -70.5,
    }]
    csv2 = _write_csv(tmp_path / "ent2.csv", rows2)
    _process_enterprise_identifiers(csv2, str(out), _build_enterprises_dict())

    ent = Enterprise.objects.first()
    assert Enterprise.objects.count() == 1
    assert ent.name == "Centro Nuevo"
    assert ent.latitude == 9.5
    assert ent.adm2_id.ext_id == "0202"


def test_enterprise_identifiers_sin_cambios(tmp_path):
    rows = [{
        "TIPO": "COLLECTION_CENTER", UNIT: "E1", "ADM2": "0101",
        "NOMBRE": "Centro", "LATITUD": 1.0, "LONGITUD": 2.0,
    }]
    csv = _write_csv(tmp_path / "ent.csv", rows)
    out = tmp_path / "out"
    _process_enterprise_identifiers(csv, str(out), {})

    updated_antes = Enterprise.objects.first().log.updated

    _process_enterprise_identifiers(csv, str(out), _build_enterprises_dict())

    ent = Enterprise.objects.first()
    assert Enterprise.objects.count() == 1
    assert ent.log.updated == updated_antes
    assert not _error_files(out)


def test_enterprise_identifiers_sin_nombre_va_a_errores(tmp_path):
    """El ORM exige nombre: la fila se registra como error, no rompe el lote."""
    csv = _write_csv(tmp_path / "ent.csv", [
        {"TIPO": "COLLECTION_CENTER", UNIT: "E1", "ADM2": "0101",
         "NOMBRE": "", "LATITUD": 1.0, "LONGITUD": 2.0},
        {"TIPO": "COLLECTION_CENTER", UNIT: "E2", "ADM2": "0101",
         "NOMBRE": "Valido", "LATITUD": 1.0, "LONGITUD": 2.0},
    ])
    out = tmp_path / "out"

    _process_enterprise_identifiers(csv, str(out), {})

    assert Enterprise.objects.count() == 1
    assert len(_error_files(out)) == 1
