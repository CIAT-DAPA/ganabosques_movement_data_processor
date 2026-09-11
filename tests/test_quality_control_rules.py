# -*- coding: utf-8 -*-
"""
Tests de las reglas de negocio de mov_quality_control.

Cada combinación origen/destino exige identificadores distintos:
  FARM → FARM        : (SIT o PRODUCER) en ambos extremos
  FARM → no FARM     : (SIT o PRODUCER) solo en origen
  no FARM → FARM     : (SIT o PRODUCER) solo en destino
  no FARM → no FARM  : PRODUCER en ambos extremos
"""
import sys
import pathlib

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from quality_control_movement.quality_control_movement import (
    _normalize_types,
    mov_quality_control,
)
from config import config
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.enums.source import Source

SIT_O = f"{Source.SIT_CODE.value}_ORIGEN"
SIT_D = f"{Source.SIT_CODE.value}_DESTINO"
PROD_O = f"{Source.PRODUCER_ID.value}_ORIGEN"
PROD_D = f"{Source.PRODUCER_ID.value}_DESTINO"

PREDIO = "PREDIO"
PLANTA = "PLANTA DE BENEFICIO"
FERIA = "FERIA GANADERA"


@pytest.fixture
def carpetas(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    out.mkdir()
    return inp, out


def _escribir(inp, filas, nombre="sample.csv"):
    pd.DataFrame(filas).to_csv(inp / nombre, index=False, encoding="utf-8")
    return inp / nombre


def _leer_depurado(out, nombre="sample_depurado.csv"):
    ruta = out / nombre
    if not ruta.exists():
        return None
    return pd.read_csv(ruta, encoding="latin1")


def _fila(origen, destino, sit_o="", sit_d="", prod_o="", prod_d=""):
    return {
        "TIPO_ORIGEN": origen,
        "TIPO_DESTINO": destino,
        SIT_O: sit_o,
        SIT_D: sit_d,
        PROD_O: prod_o,
        PROD_D: prod_d,
    }


# =========================================================
# _normalize_types
# =========================================================

def test_normalize_types_convierte_faltantes_en_na():
    out = _normalize_types(pd.Series(["", "nan", "NULL", None, " predio "]), config["MOV"])
    assert out.isna().sum() == 4
    assert out.iloc[4] == str(TypeMovement.FARM.value)


def test_normalize_types_mapea_todos_los_literales():
    out = _normalize_types(
        pd.Series([PREDIO, "CONCENTRACION GANADERA", PLANTA, FERIA, "EMPRESA"]),
        config["MOV"],
    )
    assert out.tolist() == [
        TypeMovement.FARM.value,
        TypeMovement.COLLECTION_CENTER.value,
        TypeMovement.SLAUGHTERHOUSE.value,
        TypeMovement.CATTLE_FAIR.value,
        TypeMovement.ENTERPRISE.value,
    ]


# =========================================================
# Reglas por combinación
# =========================================================

def test_regla_farm_a_farm_exige_ambos_extremos(carpetas):
    inp, out = carpetas
    _escribir(inp, [
        _fila(PREDIO, PREDIO, sit_o="1", sit_d="2"),      # válida
        _fila(PREDIO, PREDIO, sit_o="3", prod_d="9"),     # válida (fallback producer)
        _fila(PREDIO, PREDIO, sit_o="4"),                 # inválida: destino sin ids
    ])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    assert len(_leer_depurado(out)) == 2


def test_regla_farm_a_no_farm_solo_exige_origen(carpetas):
    inp, out = carpetas
    _escribir(inp, [
        _fila(PREDIO, PLANTA, sit_o="1"),          # válida
        _fila(PREDIO, PLANTA, prod_o="2"),         # válida
        _fila(PREDIO, PLANTA, prod_d="3"),         # inválida: origen sin ids
    ])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    assert len(_leer_depurado(out)) == 2


def test_regla_no_farm_a_farm_solo_exige_destino(carpetas):
    inp, out = carpetas
    _escribir(inp, [
        _fila(PLANTA, PREDIO, sit_d="1"),          # válida
        _fila(PLANTA, PREDIO, prod_d="2"),         # válida
        _fila(PLANTA, PREDIO, prod_o="3"),         # inválida: destino sin ids
    ])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    assert len(_leer_depurado(out)) == 2


def test_regla_no_farm_a_no_farm_exige_producer_en_ambos(carpetas):
    inp, out = carpetas
    _escribir(inp, [
        _fila(PLANTA, FERIA, prod_o="1", prod_d="2"),   # válida
        _fila(PLANTA, FERIA, sit_o="1", sit_d="2"),     # inválida: SIT no basta
        _fila(PLANTA, FERIA, prod_o="3"),               # inválida
    ])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    assert len(_leer_depurado(out)) == 1


def test_combinaciones_cruzadas_sin_filas_se_omiten(carpetas):
    """El producto cartesiano de tipos genera combos vacíos que deben saltarse."""
    inp, out = carpetas
    _escribir(inp, [
        _fila(PREDIO, PREDIO, sit_o="1", sit_d="2"),
        _fila(PLANTA, FERIA, prod_o="3", prod_d="4"),
    ])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    log = pd.read_csv(out / "log_mov_quality_control.txt", sep="|")
    # Solo se registran las 2 combinaciones que realmente tienen filas
    assert len(log) == 2
    assert len(_leer_depurado(out)) == 2


# =========================================================
# Casos de archivo / columnas
# =========================================================

def test_ignora_archivos_que_no_son_csv(carpetas):
    inp, out = carpetas
    (inp / "notas.txt").write_text("nada que procesar", encoding="utf-8")

    mov_quality_control(str(inp), str(out), source="SIGMA")

    # El log se genera igual, pero sin ninguna combinación registrada
    assert (out / "log_mov_quality_control.txt").exists()
    assert list(out.iterdir()) == [out / "log_mov_quality_control.txt"]


def test_archivo_sin_columnas_de_tipo_se_omite(carpetas):
    inp, out = carpetas
    _escribir(inp, [{"OTRA": 1}])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    assert _leer_depurado(out) is None


def test_descarta_filas_sin_tipo(carpetas):
    inp, out = carpetas
    _escribir(inp, [
        _fila(PREDIO, PREDIO, sit_o="1", sit_d="2"),
        _fila(None, PREDIO, sit_o="3", sit_d="4"),
        _fila(PREDIO, "", sit_o="5", sit_d="6"),
    ])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    assert len(_leer_depurado(out)) == 1


def test_archivo_sin_tipos_validos_se_omite(carpetas):
    inp, out = carpetas
    _escribir(inp, [_fila(None, None, sit_o="1", sit_d="2")])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    assert _leer_depurado(out) is None


def test_crea_columnas_de_codigo_ausentes(carpetas):
    """Sin columnas SIT/PRODUCER el proceso no falla: se crean vacías."""
    inp, out = carpetas
    pd.DataFrame([{"TIPO_ORIGEN": PREDIO, "TIPO_DESTINO": PREDIO}]).to_csv(
        inp / "sample.csv", index=False, encoding="utf-8")

    mov_quality_control(str(inp), str(out), source="SIGMA")

    # Ninguna fila supera la validación, así que no se guarda depurado
    assert _leer_depurado(out) is None
    log = pd.read_csv(out / "log_mov_quality_control.txt", sep="|")
    assert log.iloc[0]["records_used"] == 0
    assert log.iloc[0]["percent_removed"] == 100.0


def test_archivo_ilegible_queda_registrado_sin_romper(carpetas):
    inp, out = carpetas
    (inp / "roto.csv").write_bytes(b"TIPO_ORIGEN,TIPO_DESTINO\n\xff\xfe\xfa,\xff")
    _escribir(inp, [_fila(PREDIO, PREDIO, sit_o="1", sit_d="2")])

    mov_quality_control(str(inp), str(out), source="SIGMA")

    # El archivo válido se procesa igual
    assert len(_leer_depurado(out)) == 1


def test_source_alternativo_usa_otras_columnas(carpetas):
    """La fuente 'otro' apunta a las columnas origen/destino en minúscula."""
    inp, out = carpetas
    pd.DataFrame([{
        "origen": PREDIO, "destino": PREDIO,
        SIT_O: "1", SIT_D: "2", PROD_O: "", PROD_D: "",
    }]).to_csv(inp / "sample.csv", index=False, encoding="utf-8")

    mov_quality_control(str(inp), str(out), source="otro")

    assert len(_leer_depurado(out)) == 1
