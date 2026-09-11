# -*- coding: utf-8 -*-
"""
Tests unitarios de los helpers internos de save_movement.

Cubren los caminos que el flujo de integración no alcanza:
resolución de Farm/Enterprise por alias, mapeo de enums, conversión de
cantidades y el manejo de errores de la inserción por lotes.
"""
import sys
import pathlib

import pandas as pd
import pytest
from unittest.mock import Mock
from pymongo.errors import BulkWriteError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from save_movement.save_movement import (
    _safe_int_amount,
    _map_enum,
    iguales_con_nan,
    _get_farm_from_row,
    _get_enterprise_from_row,
    _detect_ganado_columns,
    _flush_batch_movements,
)

from ganabosques_orm.enums.label import Label
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.species import Species
from ganabosques_orm.enums.typeenterprise import TypeEnterprise
from ganabosques_orm.enums.typemovement import TypeMovement


# =========================================================
# _safe_int_amount
# =========================================================

def test_safe_int_amount_valores_validos():
    assert _safe_int_amount(5) == 5
    assert _safe_int_amount("7") == 7
    assert _safe_int_amount("3.0") == 3
    assert _safe_int_amount(0) == 0


@pytest.mark.parametrize("valor", [None, float("nan"), "", "   ", "nan", "None", "null"])
def test_safe_int_amount_vacios_levantan_error(valor):
    with pytest.raises(ValueError):
        _safe_int_amount(valor)


def test_safe_int_amount_negativo_levanta_error():
    with pytest.raises(ValueError):
        _safe_int_amount(-3)


# =========================================================
# _map_enum
# =========================================================

def test_map_enum_por_nombre():
    assert _map_enum(TypeMovement, "farm", "TIPO_ORIGEN") == TypeMovement.FARM
    assert _map_enum(TypeMovement, "  FARM  ", "TIPO_ORIGEN") == TypeMovement.FARM


def test_map_enum_por_valor():
    """Species usa valores en minúscula, así que cae en el fallback enum_cls(s)."""
    assert _map_enum(Species, "BOVINOS", "ESPECIE") == Species.BOVINOS


def test_map_enum_vacio_levanta_error():
    with pytest.raises(ValueError, match="ESPECIE vacío"):
        _map_enum(Species, float("nan"), "ESPECIE")


def test_map_enum_invalido_levanta_error():
    with pytest.raises(ValueError, match="inválido"):
        _map_enum(TypeMovement, "NO_EXISTE", "TIPO_ORIGEN")


# =========================================================
# iguales_con_nan
# =========================================================

def test_iguales_con_nan_ambos_none():
    assert iguales_con_nan(None, None) is True


def test_iguales_con_nan_ambos_nan():
    assert iguales_con_nan(float("nan"), float("nan")) is True


def test_iguales_con_nan_valores_iguales():
    assert iguales_con_nan(1.5, 1.5) is True


def test_iguales_con_nan_valores_distintos():
    assert iguales_con_nan(1.5, 2.5) is False
    assert iguales_con_nan(None, 1.0) is False
    assert iguales_con_nan(float("nan"), 1.0) is False


# =========================================================
# _get_farm_from_row
# =========================================================

def test_get_farm_from_row_por_sit_code():
    farm = object()
    farms_dict = {f"{Source.SIT_CODE.value}:SIT1": farm}
    row = {f"{Source.SIT_CODE.value}_ORIGEN": "SIT1"}
    assert _get_farm_from_row(row, farms_dict, True) is farm


def test_get_farm_from_row_fallback_por_producer_id():
    """Sin SIT_CODE debe resolver por PRODUCER_ID."""
    farm = object()
    farms_dict = {f"{Source.PRODUCER_ID.value}:PROD9": farm}
    row = {
        f"{Source.SIT_CODE.value}_DESTINO": "",
        f"{Source.PRODUCER_ID.value}_DESTINO": "PROD9",
    }
    assert _get_farm_from_row(row, farms_dict, False) is farm


def test_get_farm_from_row_sit_presente_pero_no_registrado():
    """SIT_CODE existe en la fila pero no en el cache: cae al fallback."""
    farm = object()
    farms_dict = {f"{Source.PRODUCER_ID.value}:PROD9": farm}
    row = {
        f"{Source.SIT_CODE.value}_ORIGEN": "DESCONOCIDO",
        f"{Source.PRODUCER_ID.value}_ORIGEN": "PROD9",
    }
    assert _get_farm_from_row(row, farms_dict, True) is farm


def test_get_farm_from_row_no_encontrado():
    assert _get_farm_from_row({}, {}, True) is None


# =========================================================
# _get_enterprise_from_row
# =========================================================

PROD_COL = Label.PRODUCTIONUNIT_ID.value


def test_get_enterprise_con_tipo_conocido():
    ent = object()
    d = {f"{TypeEnterprise.COLLECTION_CENTER.value}:{PROD_COL}:E1": ent}
    row = {f"{PROD_COL}_ORIGEN": "E1"}
    assert _get_enterprise_from_row(row, d, True, TypeMovement.COLLECTION_CENTER) is ent


def test_get_enterprise_sin_tipo_busca_en_todos_los_tipos():
    """Sin tipo_movement recorre todos los TypeEnterprise hasta encontrar."""
    ent = object()
    d = {f"{TypeEnterprise.SLAUGHTERHOUSE.value}:{PROD_COL}:E2": ent}
    row = {f"{PROD_COL}_ORIGEN": "E2"}
    assert _get_enterprise_from_row(row, d, True, None) is ent


def test_get_enterprise_tipo_movement_sin_equivalente_busca_en_todos():
    """TypeMovement.ENTERPRISE no mapea a un TypeEnterprise concreto."""
    ent = object()
    d = {f"{TypeEnterprise.ENTERPRISE.value}:{PROD_COL}:E3": ent}
    row = {f"{PROD_COL}_DESTINO": "E3"}
    assert _get_enterprise_from_row(row, d, False, TypeMovement.ENTERPRISE) is ent


def test_get_enterprise_tipo_slaughterhouse():
    ent = object()
    d = {f"{TypeEnterprise.SLAUGHTERHOUSE.value}:{PROD_COL}:E4": ent}
    row = {f"{PROD_COL}_DESTINO": "E4"}
    assert _get_enterprise_from_row(row, d, False, TypeMovement.SLAUGHTERHOUSE) is ent


def test_get_enterprise_tipo_cattle_fair():
    ent = object()
    d = {f"{TypeEnterprise.CATTLE_FAIR.value}:{PROD_COL}:E5": ent}
    row = {f"{PROD_COL}_ORIGEN": "E5"}
    assert _get_enterprise_from_row(row, d, True, TypeMovement.CATTLE_FAIR) is ent


def test_get_enterprise_alias_producer_id_con_tipo():
    """La fila trae PRODUCER_ID_* en vez de PRODUCTIONUNIT_ID_*."""
    ent = object()
    d = {f"{TypeEnterprise.SLAUGHTERHOUSE.value}:{PROD_COL}:P1": ent}
    row = {"PRODUCER_ID_DESTINO": "P1"}
    assert _get_enterprise_from_row(row, d, False, TypeMovement.SLAUGHTERHOUSE) is ent


def test_get_enterprise_alias_producer_id_sin_tipo():
    ent = object()
    d = {f"{TypeEnterprise.CATTLE_FAIR.value}:{PROD_COL}:P2": ent}
    row = {"PRODUCER_ID_ORIGEN": "P2"}
    assert _get_enterprise_from_row(row, d, True, None) is ent


def test_get_enterprise_ignora_columna_nan():
    """Una columna presente pero NaN no debe frenar el alias."""
    ent = object()
    d = {f"{TypeEnterprise.COLLECTION_CENTER.value}:{PROD_COL}:P3": ent}
    row = {f"{PROD_COL}_ORIGEN": float("nan"), "PRODUCER_ID_ORIGEN": "P3"}
    assert _get_enterprise_from_row(row, d, True, TypeMovement.COLLECTION_CENTER) is ent


def test_get_enterprise_ignora_columna_vacia():
    row = {f"{PROD_COL}_ORIGEN": "   ", "PRODUCER_ID_ORIGEN": "  "}
    assert _get_enterprise_from_row(row, {}, True, None) is None


def test_get_enterprise_alias_sin_coincidencia_con_tipo():
    """Recorre el fallback final por labels y termina devolviendo None."""
    row = {"PRODUCER_ID_DESTINO": "NOPE"}
    assert _get_enterprise_from_row(row, {}, False, TypeMovement.CATTLE_FAIR) is None


def test_get_enterprise_alias_sin_coincidencia_sin_tipo():
    row = {"PRODUCER_ID_ORIGEN": "NOPE"}
    assert _get_enterprise_from_row(row, {}, True, None) is None


def test_get_enterprise_fila_vacia():
    assert _get_enterprise_from_row({}, {}, True, None) is None


# =========================================================
# _detect_ganado_columns
# =========================================================

def test_detect_ganado_columns_excluye_metadatos():
    df = pd.DataFrame([{
        "EXT_ID": "M1",
        "TIPO_ORIGEN": "FARM",
        "TIPO_DESTINO": "FARM",
        "ESPECIE": "bovinos",
        "DATE": "2024-01-01",
        f"{Source.SIT_CODE.value}_ORIGEN": "1",
        "ADM1_ORIGEN": "01",
        "TERNEROS": 4,
        "NOVILLAS": "7",
        "OBSERVACION": "texto libre",
    }])

    cols = _detect_ganado_columns(df)

    assert "TERNEROS" in cols
    assert "NOVILLAS" in cols
    assert "OBSERVACION" not in cols
    assert "EXT_ID" not in cols
    assert "ADM1_ORIGEN" not in cols


# =========================================================
# _flush_batch_movements
# =========================================================

def _counters():
    return {"buenos": 0, "malos": 0, "existentes": 0}


def test_flush_batch_vacio():
    counters = _counters()
    assert _flush_batch_movements([], set(), counters, Mock()) == 0
    assert counters == {"buenos": 0, "malos": 0, "existentes": 0}


def test_flush_batch_exitoso():
    collection = Mock()
    collection.insert_many.return_value = Mock(inserted_ids=["a", "b"])

    counters = _counters()
    ext_ids = set()
    docs = [{"ext_id": "A"}, {"ext_id": "B"}]

    assert _flush_batch_movements(docs, ext_ids, counters, collection) == 2
    assert ext_ids == {"A", "B"}
    assert counters["buenos"] == 2
    collection.insert_many.assert_called_once_with(docs, ordered=False)


def test_flush_batch_sin_inserted_ids():
    collection = Mock()
    collection.insert_many.return_value = Mock(inserted_ids=None)

    counters = _counters()
    ext_ids = set()

    assert _flush_batch_movements([{"ext_id": "A"}], ext_ids, counters, collection) == 0
    assert ext_ids == {"A"}
    assert counters["buenos"] == 0


def test_flush_batch_bulk_write_error_parcial():
    """Los duplicados reportados por Mongo cuentan como malos; el resto se da por bueno."""
    collection = Mock()
    collection.insert_many.side_effect = BulkWriteError({
        "writeErrors": [
            {"op": {"ext_id": "B"}, "code": 11000},
            {"op": {}, "code": 11000},
        ]
    })

    counters = _counters()
    ext_ids = set()
    docs = [{"ext_id": "A"}, {"ext_id": "B"}, {"ext_id": "C"}]

    assert _flush_batch_movements(docs, ext_ids, counters, collection) == 2
    assert ext_ids == {"A", "C"}
    assert counters["buenos"] == 2
    assert counters["malos"] == 1


def test_flush_batch_bulk_write_error_sin_detalles():
    collection = Mock()
    collection.insert_many.side_effect = BulkWriteError({})

    counters = _counters()
    ext_ids = set()
    docs = [{"ext_id": "A"}]

    assert _flush_batch_movements(docs, ext_ids, counters, collection) == 1
    assert counters["buenos"] == 1
    assert counters["malos"] == 0


def test_flush_batch_error_inesperado():
    collection = Mock()
    collection.insert_many.side_effect = RuntimeError("conexión caída")

    counters = _counters()
    ext_ids = set()
    docs = [{"ext_id": "A"}, {"ext_id": "B"}]

    assert _flush_batch_movements(docs, ext_ids, counters, collection) == 0
    assert ext_ids == set()
    assert counters["malos"] == 2


# =========================================================
# Alias públicos (compatibilidad con llamadores antiguos)
# =========================================================

def test_alias_get_farm_from_row():
    from save_movement.save_movement import get_farm_from_row

    farm = object()
    farms_dict = {f"{Source.SIT_CODE.value}:SIT1": farm}
    assert get_farm_from_row({f"{Source.SIT_CODE.value}_ORIGEN": "SIT1"},
                             farms_dict, True) is farm


def test_alias_get_enterprise_from_row():
    from save_movement.save_movement import get_enterprise_from_row

    ent = object()
    d = {f"{TypeEnterprise.COLLECTION_CENTER.value}:{PROD_COL}:E1": ent}
    assert get_enterprise_from_row({f"{PROD_COL}_ORIGEN": "E1"}, d, True,
                                   TypeMovement.COLLECTION_CENTER) is ent
