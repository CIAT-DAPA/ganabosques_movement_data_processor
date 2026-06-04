import sys
import pathlib
from unittest.mock import patch

import pandas as pd

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[1] / "src")
)

from get_data_sigma.get_data_sigma import get_sigma
from config import config


def create_input_file(path, filename, data):
    df = pd.DataFrame(data)
    file_path = path / filename
    df.to_csv(
        file_path,
        index=False,
        sep="|",
        encoding="utf-8"
    )
    return file_path


def build_complete_sigma_row(**overrides):
    row = {}

    for col in config["columnas_requeridas_sigma"]:
        row[col] = "1"

    row.update(
        {
            "ANIO": "2024",
            "MES": "01",
            "DIA": "15",
            "NUMERO_GUIA": "GUIA001",
            "CODIGO_SIT_ORIGEN": "SIT001",
            "CODIGO_SIT_DESTINO": "SIT002",
            "ID_UNIDAD_PRODUCTORA_ORIGEN": "UP001",
            "ID_UNIDAD_PRODUCTORA_DESTINO": "UP002",
            "ID_DEPARTAMENTO_ORIGEN": "01",
            "ID_MUNICIPIO_ORIGEN": "0101",
            "ID_VEREDA_ORIGEN": "010101",
            "ID_DEPARTAMENTO_DESTINO": "01",
            "ID_MUNICIPIO_DESTINO": "0101",
            "ID_VEREDA_DESTINO": "010101",
            "ESPECIE": "bovina",
        }
    )

    row.update(overrides)

    return row


def test_get_sigma_minimal(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()
    out.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [build_complete_sigma_row()]
    )

    get_sigma(str(inp), str(out))

    out_files = list(out.iterdir())

    assert any(
        f.name.endswith("_filtrado_limpio.csv")
        for f in out_files
    )

    assert any(
        f.name == "log_columnas.txt"
        for f in out_files
    )


def test_get_sigma_renames_columns(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [build_complete_sigma_row()]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert "EXT_ID" in result.columns

    assert "ADM1_ORIGEN" in result.columns
    assert "ADM2_ORIGEN" in result.columns
    assert "ADM3_ORIGEN" in result.columns

    assert "ADM1_DESTINO" in result.columns
    assert "ADM2_DESTINO" in result.columns
    assert "ADM3_DESTINO" in result.columns

    assert "NUMERO_GUIA" not in result.columns


def test_get_sigma_creates_date_column(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [build_complete_sigma_row()]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert "DATE" in result.columns

    assert "ANIO" not in result.columns
    assert "MES" not in result.columns
    assert "DIA" not in result.columns


def test_get_sigma_date_value(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [
            build_complete_sigma_row(
                ANIO="2024",
                MES="03",
                DIA="20"
            )
        ]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert str(
        result["DATE"].iloc[0]
    ).startswith("2024-03-20")


def test_get_sigma_invalid_date_becomes_null(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [
            build_complete_sigma_row(
                MES="13",
                DIA="99"
            )
        ]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert pd.isna(
        result["DATE"].iloc[0]
    )


def test_get_sigma_logs_missing_columns(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [{"ANIO": "2024"}]
    )

    get_sigma(str(inp), str(out))

    content = (
        out / "log_columnas.txt"
    ).read_text(encoding="utf-8")

    assert "FALTAN columnas" in content


def test_get_sigma_logs_all_columns_present(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [build_complete_sigma_row()]
    )

    get_sigma(str(inp), str(out))

    content = (
        out / "log_columnas.txt"
    ).read_text(encoding="utf-8")

    assert (
        "Todas las columnas requeridas están presentes"
        in content
    )


def test_get_sigma_processes_multiple_files(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2023.txt",
        [build_complete_sigma_row(ANIO="2023")]
    )

    create_input_file(
        inp,
        "mov_2024.txt",
        [build_complete_sigma_row(ANIO="2024")]
    )

    get_sigma(str(inp), str(out))

    csv_files = list(
        out.glob("*_filtrado_limpio.csv")
    )

    assert len(csv_files) == 2


def test_get_sigma_ignores_files_without_year(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov.txt",
        [build_complete_sigma_row()]
    )

    get_sigma(str(inp), str(out))

    csv_files = list(
        out.glob("*_filtrado_limpio.csv")
    )

    assert len(csv_files) == 0


def test_get_sigma_ignores_non_txt_files(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    pd.DataFrame(
        [build_complete_sigma_row()]
    ).to_csv(
        inp / "mov_2024.csv",
        index=False
    )

    get_sigma(str(inp), str(out))

    csv_files = list(
        out.glob("*_filtrado_limpio.csv")
    )

    assert len(csv_files) == 0


def test_get_sigma_handles_read_error(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    (inp / "mov_2024.txt").write_text("dummy")

    with patch(
        "get_data_sigma.get_data_sigma.pd.read_csv"
    ) as mock_read:

        mock_read.side_effect = Exception(
            "archivo corrupto"
        )

        get_sigma(str(inp), str(out))

    content = (
        out / "log_columnas.txt"
    ).read_text(encoding="utf-8")

    assert "ERROR al procesar" in content


def test_get_sigma_creates_output_directory(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [build_complete_sigma_row()]
    )

    assert not out.exists()

    get_sigma(str(inp), str(out))

    assert out.exists()


def test_get_sigma_filters_unexpected_columns(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    row = build_complete_sigma_row()
    row["COLUMNA_BASURA"] = "XYZ"

    create_input_file(
        inp,
        "mov_2024.txt",
        [row]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert "COLUMNA_BASURA" not in result.columns


def test_get_sigma_without_species_column(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    row = build_complete_sigma_row()
    row.pop("ESPECIE")

    create_input_file(
        inp,
        "mov_2024.txt",
        [row]
    )

    get_sigma(str(inp), str(out))

    csv_files = list(
        out.glob("*_filtrado_limpio.csv")
    )

    assert len(csv_files) == 1


def test_get_sigma_maps_bovina_species(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [
            build_complete_sigma_row(
                ESPECIE="bovina"
            )
        ]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert (
        result["ESPECIE"].iloc[0]
        == config["especie_map"]["bovina"]
    )


def test_get_sigma_maps_bufalina_species(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [
            build_complete_sigma_row(
                ESPECIE="bufalina"
            )
        ]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert (
        result["ESPECIE"].iloc[0]
        == config["especie_map"]["bufalina"]
    )


def test_get_sigma_normalizes_text_and_species_mapping(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"

    inp.mkdir()

    create_input_file(
        inp,
        "mov_2024.txt",
        [
            build_complete_sigma_row(
                ESPECIE="BÚFALINA"
            )
        ]
    )

    get_sigma(str(inp), str(out))

    output_file = next(
        out.glob("*_filtrado_limpio.csv")
    )

    result = pd.read_csv(output_file)

    assert (
        result["ESPECIE"].iloc[0]
        == config["especie_map"]["bufalina"]
    )