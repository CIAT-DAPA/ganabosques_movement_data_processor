import sys
import pathlib
import pandas as pd
from unittest.mock import patch
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from check_farms_enterprise.check_farms_enterprise import (
    _merge_enterprise_txt,
    _load_all_csv,
    _validar_adm3_catalogo,
    _marcar_nuevos_farms,
    check,
)

from ganabosques_orm.enums.label import Label
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.enums.source import Source


# =========================================================
# _merge_enterprise_txt
# =========================================================

def test_merge_enterprise_txt_minimal(tmp_path):
    prod_col = Label.PRODUCTIONUNIT_ID.value
    tipo_val = str(TypeMovement.COLLECTION_CENTER.value).upper()

    enterprise_df = pd.DataFrame([{
        "TIPO": tipo_val,
        prod_col: "ID1",
        "ADM2": "100"
    }])

    txt = tmp_path / "cc.txt"
    pd.DataFrame([{
        "ID_CC": "ID1",
        "NOMBRE_CC": "Centro 1",
        "LATITUD": "1.23",
        "LONGITUD": "-2.34"
    }]).to_csv(txt, index=False, sep="|", encoding="latin1")

    merged = _merge_enterprise_txt(
        enterprise_df,
        tipo_val,
        str(txt),
        key_candidates=["ID_CONCENTRACION", "ID_CC"],
        name_candidates=["NOMBRE_CONCENTRACION", "NOMBRE_CC"],
    )

    assert not merged.empty
    assert merged.iloc[0]["NOMBRE"] == "Centro 1"


def test_merge_enterprise_txt_missing_file():
    df = pd.DataFrame([{
        "TIPO": "CC",
        Label.PRODUCTIONUNIT_ID.value: "1",
        "ADM2": "100"
    }])

    result = _merge_enterprise_txt(
        df,
        "CC",
        "no_existe.txt",
        ["ID_CC"],
        ["NOMBRE_CC"]
    )

    assert not result.empty
    assert "NOMBRE" in result.columns


def test_merge_enterprise_txt_missing_key_column(tmp_path):
    df = pd.DataFrame([{
        "TIPO": "CC",
        Label.PRODUCTIONUNIT_ID.value: "1",
        "ADM2": "100"
    }])

    txt = tmp_path / "cc.txt"
    pd.DataFrame([{"OTRA": "1"}]).to_csv(txt, sep="|", index=False)

    with pytest.raises(RuntimeError):
        _merge_enterprise_txt(
            df,
            "CC",
            str(txt),
            ["ID_CC"],
            ["NOMBRE_CC"]
        )


# =========================================================
# _load_all_csv
# =========================================================

def test_load_all_csv_missing_folder():
    result = _load_all_csv("no_existe")
    assert result.empty


def test_load_all_csv_empty_folder(tmp_path):
    result = _load_all_csv(str(tmp_path))
    assert result.empty


def test_load_all_csv_multiple_files(tmp_path):
    pd.DataFrame([{"A": 1}]).to_csv(tmp_path / "a.csv", index=False)
    pd.DataFrame([{"A": 2}]).to_csv(tmp_path / "b.csv", index=False)

    result = _load_all_csv(str(tmp_path))
    assert len(result) == 2


# =========================================================
# _validar_adm3_catalogo
# =========================================================

def test_validar_adm3_catalogo_missing():
    df = pd.DataFrame([{"ADM3": "999999"}])
    result = _validar_adm3_catalogo(df)
    assert len(result) == 1


def test_validar_adm3_catalogo_existing():
    df = pd.DataFrame([{"ADM3": "010101"}])
    result = _validar_adm3_catalogo(df)
    assert result.empty


# =========================================================
# _marcar_nuevos_farms
# =========================================================

@patch("check_farms_enterprise.check_farms_enterprise._cargar_existentes_en_mongo")
def test_marcar_nuevos_farms_all_new(mock_existing):
    mock_existing.return_value = (set(), set())

    df = pd.DataFrame([{
        "SIT_CODE": "100",
        "PRODUCER_ID": "200",
        "ADM3": "010101",
        "TIPO": "PREDIO"
    }])

    result = _marcar_nuevos_farms(df)
    assert len(result) == 1


@patch("check_farms_enterprise.check_farms_enterprise._cargar_existentes_en_mongo")
def test_marcar_nuevos_farms_existing_sit(mock_existing):
    mock_existing.return_value = ({"100"}, set())

    df = pd.DataFrame([{
        "SIT_CODE": "100",
        "PRODUCER_ID": "999",
        "ADM3": "010101",
        "TIPO": "PREDIO"
    }])

    result = _marcar_nuevos_farms(df)
    assert result.empty


@patch("check_farms_enterprise.check_farms_enterprise._cargar_existentes_en_mongo")
def test_marcar_nuevos_farms_existing_producer(mock_existing):
    mock_existing.return_value = (set(), {"500"})

    df = pd.DataFrame([{
        "SIT_CODE": "111",
        "PRODUCER_ID": "500",
        "ADM3": "010101",
        "TIPO": "PREDIO"
    }])

    result = _marcar_nuevos_farms(df)
    assert result.empty


# =========================================================
# _completar_coords_enterprise
# =========================================================

@patch("check_farms_enterprise.check_farms_enterprise._centroides_adm2_desde_adm3")
def test_completar_coords_enterprise(mock_centroids):
    from check_farms_enterprise.check_farms_enterprise import _completar_coords_enterprise

    mock_centroids.return_value = pd.DataFrame([{
        "ADM2_CODE": "0101",
        "LATITUD": 3.5,
        "LONGITUD": -76.5
    }])

    df = pd.DataFrame([{
        "ADM2": "0101",
        "LATITUD": None,
        "LONGITUD": None
    }])

    result = _completar_coords_enterprise(df, "dummy")
    assert result.iloc[0]["LATITUD"] == 3.5


# =========================================================
# CHECK PRINCIPAL (FALTANTE IMPORTANTE)
# =========================================================

@patch("check_farms_enterprise.check_farms_enterprise._cargar_existentes_en_mongo")
@patch("check_farms_enterprise.check_farms_enterprise._centroides_adm2_desde_adm3")
def test_check_main_flow(mock_centroids, mock_mongo, tmp_path):
    """
    Test de integración básico del flujo principal.
    """

    mock_mongo.return_value = (set(), set())

    mock_centroids.return_value = pd.DataFrame([{
        "ADM2_CODE": "0101",
        "LATITUD": 3.5,
        "LONGITUD": -76.5
    }])

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    info_dir = tmp_path / "info"

    (input_dir / "farms").mkdir(parents=True)
    (input_dir / "enterprise").mkdir(parents=True)
    info_dir.mkdir()

    # farms input
    pd.DataFrame([{
        Source.SIT_CODE.value: "100",
        Source.PRODUCER_ID.value: "200",
        "ADM3": "010101",
        "TIPO": "PREDIO"
    }]).to_csv(input_dir / "farms" / "f.csv", index=False)

    # enterprise input
    prod = Label.PRODUCTIONUNIT_ID.value
    pd.DataFrame([{
        "TIPO": str(TypeMovement.COLLECTION_CENTER.value).upper(),
        prod: "1",
        "ADM2": "0101",
        "NOMBRE": "CC1"
    }]).to_csv(input_dir / "enterprise" / "e.csv", index=False)

    # txt info
    (info_dir / f"{TypeMovement.COLLECTION_CENTER.value}.txt").write_text(
        "ID_CC|NOMBRE\n1|Centro1",
        encoding="utf-8"
    )

    check(str(input_dir), str(output_dir), str(info_dir))

    assert (output_dir / "farms" / "new_farms.csv").exists()
    assert (output_dir / "enterprise" / "new_enterprise.csv").exists()