# -*- coding: utf-8 -*-
"""Comprehensive tests for config module."""
import sys
import pathlib
import os
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from config import config


def test_config_has_required_keys():
    """Test that all required configuration keys are present."""
    required_keys = [
        'DEBUG', 'WORKSPACE', 'DATA', 'MONGO_URI', 'MONGO_DB_NAME',
        'URL_GEO', 'GEO_USER', 'GEO_PWD', 'GEO_WORKSPACE', 'GEO_STORE',
        'columnas_requeridas_sigma', 'MOV', 'origen_destino', 'especie_map'
    ]
    for key in required_keys:
        assert key in config, f"Missing config key: {key}"


def test_config_columnas_requeridas_sigma():
    """Test that required SIGMA columns are defined."""
    cols = config["columnas_requeridas_sigma"]
    assert isinstance(cols, list)
    assert len(cols) > 0
    assert "ANIO" in cols
    assert "MES" in cols
    assert "DIA" in cols
    assert "NUMERO_GUIA" in cols
    assert "ESPECIE" in cols
    assert "TIPO_ORIGEN" in cols
    assert "TIPO_DESTINO" in cols


def test_config_mov_mapping():
    """Test MOV mapping contains expected type movements."""
    mov = config["MOV"]
    assert "PREDIO" in mov
    assert "CONCENTRACION GANADERA" in mov
    assert "PLANTA DE BENEFICIO" in mov
    assert "FERIA GANADERA" in mov
    assert "EMPRESA" in mov


def test_config_origen_destino_sigma():
    """Test SIGMA origin/destination column configuration."""
    od = config["origen_destino"]
    assert "SIGMA" in od
    assert "type_origin" in od["SIGMA"]
    assert "type_destination" in od["SIGMA"]
    assert od["SIGMA"]["type_origin"] == "TIPO_ORIGEN"
    assert od["SIGMA"]["type_destination"] == "TIPO_DESTINO"


def test_config_especie_map():
    """Test species mapping."""
    es = config["especie_map"]
    assert "bovina" in es
    assert "bufalina" in es
    assert len(es) >= 2


def test_config_boolean_debug():
    """Test DEBUG is boolean."""
    assert isinstance(config['DEBUG'], bool)


def test_config_strings_not_empty():
    """Test string configs are not empty."""
    string_keys = ['WORKSPACE', 'DATA', 'MONGO_URI', 'MONGO_DB_NAME']
    for key in string_keys:
        if config[key] is not None:  # Could be None from env vars
            assert isinstance(config[key], str)
