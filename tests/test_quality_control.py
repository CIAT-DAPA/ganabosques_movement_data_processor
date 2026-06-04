import sys
import pathlib
import pandas as pd
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from quality_control_movement.quality_control_movement import _normalize_types, mov_quality_control
from config import config
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.enums.source import Source


def test_normalize_types_mapping():
    mapping = config["MOV"]
    s = pd.Series([" predio ", "PLANTA DE BENEFICIO", "FERIA GANADERA", "", None])
    out = _normalize_types(s, mapping)
    assert out.iloc[0] == str(TypeMovement.FARM.value)


def test_mov_quality_control_minimal(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    out.mkdir()

    # create a CSV that will pass the farm-farm validation
    df = pd.DataFrame([
        {
            "TIPO_ORIGEN": "PREDIO",
            "TIPO_DESTINO": "PREDIO",
            f"{Source.SIT_CODE.value}_ORIGEN": "123",
            f"{Source.SIT_CODE.value}_DESTINO": "456",
            f"{Source.PRODUCER_ID.value}_ORIGEN": "",
            f"{Source.PRODUCER_ID.value}_DESTINO": "",
        }
    ])
    file_path = inp / "sample.csv"
    df.to_csv(file_path, index=False, encoding='utf-8')

    mov_quality_control(str(inp), str(out), source="SIGMA")

    # Expect a log file to be created
    log_file = out / "log_mov_quality_control.txt"
    assert log_file.exists()
