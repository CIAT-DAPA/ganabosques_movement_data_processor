# -*- coding: utf-8 -*-
"""
Tests del punto de entrada por línea de comandos de main.py.

El bloque `if __name__ == "__main__"` se ejecuta con runpy para que la
resolución de argumentos (-p / -f / -s) quede cubierta. Los pasos del
pipeline se parchean en sus módulos de origen, porque runpy crea un
espacio de nombres nuevo que vuelve a importarlos.
"""
import sys
import runpy
import pathlib

import pytest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import main
from config import config as app_config


@pytest.fixture
def pipeline_mockeado(tmp_path, monkeypatch):
    """Aísla el pipeline: rutas en tmp y todos los pasos parcheados."""
    monkeypatch.setitem(app_config, "WORKSPACE", str(tmp_path))
    monkeypatch.setitem(app_config, "DATA", str(tmp_path / "data"))

    with patch("get_data_sigma.get_sigma") as get_sigma, \
         patch("quality_control_movement.mov_quality_control") as qc, \
         patch("calculate_movement.calc_mov") as calc, \
         patch("check_farms_enterprise.check") as check, \
         patch("save_movement.save_movement.save_movements") as save:
        yield {
            "get_sigma": get_sigma,
            "mov_quality_control": qc,
            "calc_mov": calc,
            "check": check,
            "save_movements": save,
        }


def _ejecutar_cli(argv):
    with patch.object(sys, "argv", ["main.py"] + argv):
        runpy.run_module("main", run_name="__main__")


def _pasos_ejecutados(mocks):
    return [nombre for nombre, mock in mocks.items() if mock.called]


# =========================================================
# build_paths
# =========================================================

def test_build_paths_sin_workspace(monkeypatch):
    monkeypatch.setitem(app_config, "WORKSPACE", None)
    with pytest.raises(ValueError, match="WORKSPACE"):
        main.build_paths()


def test_build_paths_sin_data(monkeypatch, tmp_path):
    monkeypatch.setitem(app_config, "WORKSPACE", str(tmp_path))
    monkeypatch.setitem(app_config, "DATA", None)
    with pytest.raises(ValueError, match="DATA"):
        main.build_paths()


def test_build_paths_crea_base_y_rutas(monkeypatch, tmp_path):
    monkeypatch.setitem(app_config, "WORKSPACE", str(tmp_path))
    monkeypatch.setitem(app_config, "DATA", str(tmp_path / "data"))

    paths = main.build_paths()

    assert (tmp_path / "movilizacion").is_dir()
    assert paths["base_path"].endswith("movilizacion")
    assert paths["info"].endswith("info")
    assert paths["output_path_save"].endswith("5_save_movement")


# =========================================================
# CLI
# =========================================================

def test_cli_sin_flags_ejecuta_todos_los_pasos(pipeline_mockeado):
    _ejecutar_cli(["-s", "SIGMA"])

    assert len(_pasos_ejecutados(pipeline_mockeado)) == 5


def test_cli_process_ejecuta_solo_los_pasos_pedidos(pipeline_mockeado):
    _ejecutar_cli(["-s", "SIGMA", "-p", "1", "3"])

    assert _pasos_ejecutados(pipeline_mockeado) == ["get_sigma", "calc_mov"]


def test_cli_process_deduplica_y_ordena(pipeline_mockeado):
    _ejecutar_cli(["-s", "SIGMA", "-p", "3", "1", "3"])

    assert pipeline_mockeado["get_sigma"].call_count == 1
    assert pipeline_mockeado["calc_mov"].call_count == 1
    assert not pipeline_mockeado["mov_quality_control"].called


def test_cli_process_descarta_pasos_fuera_de_rango(pipeline_mockeado):
    _ejecutar_cli(["-s", "SIGMA", "-p", "0", "2", "9"])

    assert _pasos_ejecutados(pipeline_mockeado) == ["mov_quality_control"]


def test_cli_from_step_ejecuta_de_ahi_en_adelante(pipeline_mockeado):
    _ejecutar_cli(["-s", "SIGMA", "-f", "4"])

    assert _pasos_ejecutados(pipeline_mockeado) == ["check", "save_movements"]


def test_cli_process_y_from_step_son_excluyentes(pipeline_mockeado):
    with pytest.raises(ValueError, match="al mismo tiempo"):
        _ejecutar_cli(["-s", "SIGMA", "-p", "1", "-f", "2"])


def test_cli_sin_pasos_validos_falla(pipeline_mockeado):
    with pytest.raises(ValueError, match="pasos válidos"):
        _ejecutar_cli(["-s", "SIGMA", "-p", "7", "8"])


def test_cli_source_sinigan(pipeline_mockeado):
    _ejecutar_cli(["-s", "SINIGAN", "-p", "2"])

    assert pipeline_mockeado["mov_quality_control"].call_args[1]["source"] == "SINIGAN"


def test_cli_source_invalido_aborta(pipeline_mockeado):
    with pytest.raises(SystemExit):
        _ejecutar_cli(["-s", "OTRA_FUENTE"])


def test_cli_source_obligatorio(pipeline_mockeado):
    with pytest.raises(SystemExit):
        _ejecutar_cli([])
