import sys
import pathlib
from unittest.mock import patch

import pandas as pd

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[1] / "src")
)

from calculate_movement.calculation_movement import (
    extract_year_from_filename,
    safe_convert_int,
    calc_mov,
)

from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.species import Species
from ganabosques_orm.enums.typemovement import TypeMovement


# ==========================================================
# Helpers
# ==========================================================

def build_movement_row(**overrides):
    row = {
        "ESPECIE": Species.BOVINOS.value,
        "EXT_ID": "EXT001",

        f"{Source.SIT_CODE.value}_ORIGEN": "100",
        f"{Source.SIT_CODE.value}_DESTINO": "200",

        f"{Source.PRODUCER_ID.value}_ORIGEN": "1000",
        f"{Source.PRODUCER_ID.value}_DESTINO": "2000",

        "ADM1_ORIGEN": "01",
        "ADM2_ORIGEN": "0101",
        "ADM3_ORIGEN": "010101",

        "ADM1_DESTINO": "01",
        "ADM2_DESTINO": "0101",
        "ADM3_DESTINO": "010101",

        "TIPO_ORIGEN": TypeMovement.FARM.value,
        "TIPO_DESTINO": TypeMovement.FARM.value,
    }

    row.update(overrides)
    return row


# ==========================================================
# extract_year_from_filename
# ==========================================================

def test_extract_year_from_filename():
    assert extract_year_from_filename("mov_2021_file.csv") == "2021"
    assert extract_year_from_filename("no_year.csv") == "unknown"


def test_extract_year_multiple_years():
    assert (
        extract_year_from_filename(
            "mov_2023_backup_2024.csv"
        )
        == "2023"
    )


# ==========================================================
# safe_convert_int
# ==========================================================

def test_safe_convert_int():
    df = pd.DataFrame(
        {
            "A": ["1", "2"],
            "B": ["10", "20"]
        }
    )

    result = safe_convert_int(
        df.copy(),
        ["B"]
    )

    assert str(result["B"].dtype).startswith("int")


def test_safe_convert_int_missing_column():
    df = pd.DataFrame({"A": ["1"]})

    result = safe_convert_int(
        df.copy(),
        ["NO_EXISTE"]
    )

    assert "A" in result.columns


# ==========================================================
# calc_mov
# ==========================================================

def test_calc_mov_creates_directories(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    pd.DataFrame(
        [build_movement_row()]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    assert (output_dir / "farms").exists()
    assert (output_dir / "enterprise").exists()
    assert (output_dir / "movement").exists()


def test_calc_mov_generates_log_file(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    pd.DataFrame(
        [build_movement_row()]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    assert (
        output_dir / "log_calc_mov_2023.txt"
    ).exists()


def test_calc_mov_ignores_non_csv(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    (input_dir / "archivo.txt").write_text(
        "dummy"
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    movement_dir = output_dir / "movement"

    assert not list(
        movement_dir.glob("*.csv")
    )


def test_calc_mov_filters_invalid_species(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    pd.DataFrame(
        [
            build_movement_row(
                ESPECIE="caballos"
            )
        ]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    movement_file = (
        output_dir
        / "movement"
        / "movement_data_base_2023.csv"
    )

    result = pd.read_csv(movement_file)

    assert len(result) == 0


def test_calc_mov_missing_species_column(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    row = build_movement_row()
    row.pop("ESPECIE")

    pd.DataFrame([row]).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    movement_file = (
        output_dir
        / "movement"
        / "movement_data_base_2023.csv"
    )

    assert not movement_file.exists()


def test_calc_mov_exact_duplicate_removed(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    row = build_movement_row()

    pd.DataFrame(
        [row, row]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    movement_file = (
        output_dir
        / "movement"
        / "movement_data_base_2023.csv"
    )

    result = pd.read_csv(movement_file)

    assert len(result) == 1


def test_calc_mov_conflicting_extid_generates_error_file(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    row1 = build_movement_row(
        EXT_ID="A"
    )

    row2 = build_movement_row(
        EXT_ID="A",
        ADM2_DESTINO="9999"
    )

    pd.DataFrame(
        [row1, row2]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    assert (
        output_dir
        / "movement"
        / "movement_errors_extid_2023.csv"
    ).exists()


def test_calc_mov_conflicting_extid_removed_from_main_file(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    row1 = build_movement_row(
        EXT_ID="A"
    )

    row2 = build_movement_row(
        EXT_ID="A",
        ADM2_DESTINO="9999"
    )

    pd.DataFrame(
        [row1, row2]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    movement_file = (
        output_dir
        / "movement"
        / "movement_data_base_2023.csv"
    )

    result = pd.read_csv(movement_file)

    assert len(result) == 0


def test_calc_mov_without_extid(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    row = build_movement_row()
    row.pop("EXT_ID")

    pd.DataFrame([row]).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    movement_file = (
        output_dir
        / "movement"
        / "movement_data_base_2023.csv"
    )

    assert movement_file.exists()


def test_calc_mov_replaces_null_adm3(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    pd.DataFrame(
        [
            build_movement_row(
                ADM3_ORIGEN=None,
                ADM3_DESTINO=None
            )
        ]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    movement_file = (
        output_dir
        / "movement"
        / "movement_data_base_2023.csv"
    )

    result = pd.read_csv(movement_file)

    assert (
        result["ADM3_ORIGEN"].iloc[0]
        == 999999999999
    )

    assert (
        result["ADM3_DESTINO"].iloc[0]
        == 999999999999
    )


def test_calc_mov_generates_farms_file(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    pd.DataFrame(
        [build_movement_row()]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    farms_file = (
        output_dir
        / "farms"
        / "farms_data_base_2023.csv"
    )

    assert farms_file.exists()

    farms = pd.read_csv(farms_file)

    assert len(farms) > 0

    assert "TIPO" in farms.columns
    assert "ADM3" in farms.columns


def test_calc_mov_generates_enterprise_file(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    pd.DataFrame(
        [
            build_movement_row(
                TIPO_ORIGEN=TypeMovement.ENTERPRISE.value,
                TIPO_DESTINO=TypeMovement.ENTERPRISE.value
            )
        ]
    ).to_csv(
        input_dir / "mov_2023.csv",
        index=False
    )

    calc_mov(
        str(input_dir),
        str(output_dir)
    )

    enterprise_file = (
        output_dir
        / "enterprise"
        / "enterprise_data_base_2023.csv"
    )

    assert enterprise_file.exists()

    enterprise = pd.read_csv(
        enterprise_file
    )

    assert len(enterprise) > 0


def test_calc_mov_handles_read_error(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    input_dir.mkdir()

    (input_dir / "mov_2023.csv").write_text(
        "dummy"
    )

    with patch(
        "calculate_movement.calculation_movement.pd.read_csv"
    ) as mock_read:

        mock_read.side_effect = Exception(
            "error lectura"
        )

        calc_mov(
            str(input_dir),
            str(output_dir)
        )

    assert (
        output_dir / "movement"
    ).exists()