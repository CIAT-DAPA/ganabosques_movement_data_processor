# -*- coding: utf-8 -*-
"""
Casos límite sueltos: conversiones tolerantes de tools.data_utils,
normalización de ESPECIE en get_data_sigma y ejecución directa de config.py.
"""
import sys
import runpy
import pathlib

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tools.data_utils import to_clean_str, to_float_series
from get_data_sigma.get_data_sigma import get_sigma
from config import config


# =========================================================
# to_clean_str: los try/except tolerantes
# =========================================================

def test_to_clean_str_texto_terminado_en_punto_cero():
    """'.0' no convertible a número se devuelve tal cual, sin romper."""
    assert to_clean_str("ABC.0") == "ABC.0"


def test_to_clean_str_texto_con_letra_e():
    """Una 'e' que no forma notación científica no debe alterar el valor."""
    assert to_clean_str("PREDIO") == "PREDIO"
    assert to_clean_str("SIT-ESTE-01") == "SIT-ESTE-01"


def test_to_clean_str_notacion_cientifica_no_entera():
    assert to_clean_str("1.5e2") == "150"
    assert to_clean_str("1.234e2") == "123.4"


def test_to_float_series_mantiene_coherencia_con_to_clean_str():
    serie = pd.Series(["1.234,56", "1,234.56", "1 234", "", "-"])
    out = to_float_series(serie)
    assert out.tolist()[:3] == [1234.56, 1234.56, 1234.0]
    assert out.isna().sum() == 2


# =========================================================
# get_sigma: normalización de ESPECIE
# =========================================================

def _fila_sigma(**overrides):
    fila = {col: "1" for col in config["columnas_requeridas_sigma"]}
    fila.update({
        "ANIO": "2024", "MES": "01", "DIA": "15",
        "NUMERO_GUIA": "G1", "ESPECIE": "bovina",
    })
    fila.update(overrides)
    return fila


def test_get_sigma_especie_desconocida_se_conserva(tmp_path):
    """Una especie fuera del mapa queda igual en vez de perderse."""
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    pd.DataFrame([
        _fila_sigma(NUMERO_GUIA="G1", ESPECIE="equina"),
        _fila_sigma(NUMERO_GUIA="G2", ESPECIE="bovina"),
    ]).to_csv(inp / "sigma_2024.txt", index=False, sep="|", encoding="utf-8")

    get_sigma(str(inp), str(out))

    df = pd.read_csv(out / "sigma_2024_filtrado_limpio.csv")
    especies = df["ESPECIE"].tolist()
    assert "equina" in especies
    assert config["especie_map"]["bovina"] in especies


def test_get_sigma_especie_nula_se_conserva(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    filas = [_fila_sigma(NUMERO_GUIA="G1"), _fila_sigma(NUMERO_GUIA="G2")]
    df_in = pd.DataFrame(filas)
    df_in.loc[0, "ESPECIE"] = None
    df_in.to_csv(inp / "sigma_2024.txt", index=False, sep="|", encoding="utf-8")

    get_sigma(str(inp), str(out))

    df = pd.read_csv(out / "sigma_2024_filtrado_limpio.csv")
    assert df["ESPECIE"].isna().sum() == 1


# =========================================================
# config.py como script
# =========================================================

def test_config_ejecutado_como_script(capsys):
    runpy.run_module("config", run_name="__main__")
    assert "columnas_requeridas_sigma" in capsys.readouterr().out
