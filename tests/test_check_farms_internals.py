# -*- coding: utf-8 -*-
"""
Tests de los internos de check_farms_enterprise que dependen de MongoDB
o de servicios externos (GeoServer WFS) y que por eso quedaban sin cubrir.

`connect` se parchea porque conftest ya dejó mongoengine apuntando a
mongomock; una segunda llamada con otros parámetros sería rechazada.
"""
import io
import os
import sys
import zipfile
import pathlib
from datetime import datetime

import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import Polygon
from unittest.mock import patch, Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import check_farms_enterprise.check_farms_enterprise as cfe
from check_farms_enterprise.check_farms_enterprise import (
    _cargar_existentes_en_mongo,
    _descargar_adm3_wfs,
    _centroides_adm2_desde_adm3,
    _completar_coords_enterprise,
    check,
)

from ganabosques_orm.collections.farm import Farm
from ganabosques_orm.collections.adm3 import Adm3
from ganabosques_orm.auxiliaries.log import Log
from ganabosques_orm.auxiliaries.extidfarm import ExtIdFarm
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.label import Label
from ganabosques_orm.enums.farmsource import FarmSource
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.enums.valuechain import ValueChain

UNIT = Label.PRODUCTIONUNIT_ID.value
CC_VAL = str(TypeMovement.COLLECTION_CENTER.value).upper()


@pytest.fixture
def mongo_connect_ok():
    with patch.object(cfe, "connect") as mock_connect:
        yield mock_connect


def _crear_farm(ext_ids):
    now = datetime.now()
    farm = Farm(
        adm3_id=Adm3.objects(ext_id="010101").first(),
        ext_id=ext_ids,
        farm_source=FarmSource.SIGMA,
        value_chain=ValueChain.LIVESTOCK.value,
        log=Log(enable=True, created=now, updated=now),
    )
    farm.save()
    return farm


# =========================================================
# _cargar_existentes_en_mongo
# =========================================================

def test_cargar_existentes_sin_farms(mongo_connect_ok):
    sit, prod = _cargar_existentes_en_mongo()
    assert sit == set()
    assert prod == set()


def test_cargar_existentes_separa_sit_y_producer(mongo_connect_ok):
    _crear_farm([
        ExtIdFarm(source=Source.SIT_CODE, ext_code="S1"),
        ExtIdFarm(source=Source.PRODUCER_ID, ext_code="P1"),
    ])
    _crear_farm([ExtIdFarm(source=Source.SIT_CODE, ext_code="S2")])

    sit, prod = _cargar_existentes_en_mongo()

    assert sit == {"S1", "S2"}
    assert prod == {"P1"}


def test_cargar_existentes_ignora_codigos_vacios_y_otras_fuentes(mongo_connect_ok):
    _crear_farm([
        ExtIdFarm(source=Source.SIT_CODE, ext_code="   "),
        ExtIdFarm(source=Source.GEOFARMER_ID, ext_code="G1"),
        ExtIdFarm(source=Source.PRODUCER_ID, ext_code="P9"),
    ])

    sit, prod = _cargar_existentes_en_mongo()

    assert sit == set()
    assert prod == {"P9"}


def test_cargar_existentes_ignora_farm_sin_ext_id(mongo_connect_ok):
    """Documento legado insertado sin ext_id: se salta sin romper."""
    Farm._get_collection().insert_one({"ext_id": []})
    _crear_farm([ExtIdFarm(source=Source.SIT_CODE, ext_code="S1")])

    sit, prod = _cargar_existentes_en_mongo()

    assert sit == {"S1"}


# =========================================================
# _descargar_adm3_wfs
# =========================================================

def _zip_bytes(nombres):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre in nombres:
            z.writestr(nombre, b"contenido")
    return buf.getvalue()


@pytest.fixture
def geo_config(monkeypatch):
    for clave, valor in {
        "URL_GEO": "https://geo.example.org/geoserver/",
        "GEO_WORKSPACE": "ws",
        "GEO_STORE": "adm3",
        "GEO_USER": "user",
        "GEO_PWD": "pwd",
    }.items():
        monkeypatch.setitem(cfe.config, clave, valor)


def test_descargar_adm3_wfs_extrae_shapefile(tmp_path, geo_config):
    respuesta = Mock(content=_zip_bytes(["adm3.shp", "adm3.dbf", "adm3.shx"]))
    respuesta.raise_for_status = Mock()

    with patch.object(cfe.requests, "get", return_value=respuesta) as mock_get:
        shp = _descargar_adm3_wfs(str(tmp_path))

    assert shp.endswith("adm3.shp")
    assert os.path.isfile(shp)

    url_llamada = mock_get.call_args[0][0]
    assert url_llamada.startswith("https://geo.example.org/geoserver/ws/wfs?")
    assert "typeName=ws:adm3" in url_llamada
    assert mock_get.call_args[1]["auth"] == ("user", "pwd")


def test_descargar_adm3_wfs_sin_shp_levanta_error(tmp_path, geo_config):
    respuesta = Mock(content=_zip_bytes(["adm3.dbf"]))
    respuesta.raise_for_status = Mock()

    with patch.object(cfe.requests, "get", return_value=respuesta):
        with pytest.raises(RuntimeError, match="No se encontró .shp"):
            _descargar_adm3_wfs(str(tmp_path))


def test_descargar_adm3_wfs_propaga_error_http(tmp_path, geo_config):
    respuesta = Mock()
    respuesta.raise_for_status.side_effect = RuntimeError("503")

    with patch.object(cfe.requests, "get", return_value=respuesta):
        with pytest.raises(RuntimeError, match="503"):
            _descargar_adm3_wfs(str(tmp_path))


# =========================================================
# _centroides_adm2_desde_adm3
# =========================================================

def _cuadrado(lon, lat, lado=0.1):
    return Polygon([
        (lon, lat), (lon + lado, lat),
        (lon + lado, lat + lado), (lon, lat + lado),
    ])


def _gdf_adm3(columnas_extra=True, con_geometria_nula=False):
    filas = {
        "cod_mpio": ["5001", "5001", "5002"],
        "geometry": [_cuadrado(-75.0, 4.0), _cuadrado(-75.1, 4.0), _cuadrado(-73.0, 5.0)],
    }
    if columnas_extra:
        filas["nom_mpio"] = ["Municipio A", "Municipio A", "Municipio B"]
    if con_geometria_nula:
        filas["cod_mpio"].append("5003")
        filas["geometry"].append(None)
        if columnas_extra:
            filas["nom_mpio"].append("Municipio C")
    return gpd.GeoDataFrame(filas, crs="EPSG:4326")


def test_centroides_adm2_agrupa_por_municipio(tmp_path):
    with patch.object(cfe, "_descargar_adm3_wfs", return_value="fake.shp"), \
         patch.object(cfe.gpd, "read_file", return_value=_gdf_adm3()):
        out = _centroides_adm2_desde_adm3(str(tmp_path))

    assert set(out["ADM2_CODE"]) == {"5001", "5002"}
    assert len(out) == 2

    fila = out[out["ADM2_CODE"] == "5002"].iloc[0]
    assert fila["LONGITUD"] == pytest.approx(-72.95, abs=0.1)
    assert fila["LATITUD"] == pytest.approx(5.05, abs=0.1)


def test_centroides_adm2_sin_columna_de_nombre(tmp_path):
    with patch.object(cfe, "_descargar_adm3_wfs", return_value="fake.shp"), \
         patch.object(cfe.gpd, "read_file", return_value=_gdf_adm3(columnas_extra=False)):
        out = _centroides_adm2_desde_adm3(str(tmp_path))

    assert len(out) == 2


def test_centroides_adm2_descarta_geometrias_nulas(tmp_path):
    gdf = _gdf_adm3(con_geometria_nula=True)
    with patch.object(cfe, "_descargar_adm3_wfs", return_value="fake.shp"), \
         patch.object(cfe.gpd, "read_file", return_value=gdf):
        out = _centroides_adm2_desde_adm3(str(tmp_path))

    assert "5003" not in set(out["ADM2_CODE"])


def test_centroides_adm2_sin_cod_mpio_levanta_error(tmp_path):
    gdf = gpd.GeoDataFrame(
        {"otro_codigo": ["1"], "geometry": [_cuadrado(-75.0, 4.0)]},
        crs="EPSG:4326",
    )
    with patch.object(cfe, "_descargar_adm3_wfs", return_value="fake.shp"), \
         patch.object(cfe.gpd, "read_file", return_value=gdf):
        with pytest.raises(RuntimeError, match="cod_mpio"):
            _centroides_adm2_desde_adm3(str(tmp_path))


# =========================================================
# _completar_coords_enterprise
# =========================================================

def test_completar_coords_dataframe_vacio():
    vacio = pd.DataFrame(columns=["ADM2", "LATITUD", "LONGITUD"])
    assert _completar_coords_enterprise(vacio, "dummy").empty


def test_completar_coords_copia_desde_otro_registro_del_mismo_adm2():
    """Sin centroide disponible, se reutilizan las coords de un vecino del mismo ADM2."""
    centroides = pd.DataFrame([{"ADM2_CODE": "9999", "LATITUD": 0.0, "LONGITUD": 0.0}])

    df = pd.DataFrame([
        {"ADM2": "0101", "LATITUD": 3.0, "LONGITUD": -76.0},
        {"ADM2": "0101", "LATITUD": None, "LONGITUD": None},
        {"ADM2": "0303", "LATITUD": None, "LONGITUD": None},
    ])

    with patch.object(cfe, "_centroides_adm2_desde_adm3", return_value=centroides):
        out = _completar_coords_enterprise(df, "dummy")

    # La fila sin par en su ADM2 se descarta
    assert len(out) == 2
    assert set(out["ADM2"]) == {"0101"}
    assert out["LATITUD"].tolist() == [3.0, 3.0]


# =========================================================
# check(): ramas de entrada vacía y export por tipo
# =========================================================

def test_check_sin_datos_de_entrada(tmp_path, mongo_connect_ok):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    info_dir = tmp_path / "info"
    input_dir.mkdir()
    info_dir.mkdir()

    centroides = pd.DataFrame(columns=["ADM2_CODE", "LATITUD", "LONGITUD"])
    with patch.object(cfe, "_centroides_adm2_desde_adm3", return_value=centroides):
        check(str(input_dir), str(output_dir), str(info_dir))

    assert (output_dir / "farms" / "new_farms.csv").exists()
    assert (output_dir / "enterprise" / "new_enterprise.csv").exists()
    assert pd.read_csv(output_dir / "enterprise" / "new_enterprise.csv").empty
    assert not (output_dir / "farms" / "new_farms_to_create.csv").exists()


def test_check_exporta_enterprise_por_tipo(tmp_path, mongo_connect_ok):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    info_dir = tmp_path / "info"
    (input_dir / "farms").mkdir(parents=True)
    (input_dir / "enterprise").mkdir(parents=True)
    info_dir.mkdir()

    pd.DataFrame([
        {Source.SIT_CODE.value: "100", Source.PRODUCER_ID.value: "200",
         "ADM3": "010101", "TIPO": "PREDIO"},
        {Source.SIT_CODE.value: "101", Source.PRODUCER_ID.value: "201",
         "ADM3": "999999999999", "TIPO": "PREDIO"},
    ]).to_csv(input_dir / "farms" / "f.csv", index=False)

    # Sin columna NOMBRE: el nombre proviene del TXT de información
    pd.DataFrame([
        {"TIPO": CC_VAL, UNIT: "1", "ADM2": "0101"},
        {"TIPO": "ENTERPRISE", UNIT: "2", "ADM2": "0101"},
    ]).to_csv(input_dir / "enterprise" / "e.csv", index=False)

    (info_dir / f"{TypeMovement.COLLECTION_CENTER.value}.txt").write_text(
        "ID_CC|NOMBRE_CC|LATITUD|LONGITUD\n1|Centro Uno|3,5|-76,5",
        encoding="latin1",
    )

    centroides = pd.DataFrame([{"ADM2_CODE": "0101", "LATITUD": 3.5, "LONGITUD": -76.5}])
    with patch.object(cfe, "_centroides_adm2_desde_adm3", return_value=centroides):
        check(str(input_dir), str(output_dir), str(info_dir))

    final = pd.read_csv(output_dir / "enterprise" / "new_enterprise.csv")
    assert "Centro Uno" in final["NOMBRE"].tolist()

    por_tipo = output_dir / "enterprise" / "enterprise_collection_center.csv"
    assert por_tipo.exists()
    assert len(pd.read_csv(por_tipo)) == 1

    # Los tipos sin nombre en el TXT no llegan al archivo final
    assert not (output_dir / "enterprise" / "enterprise_slaughterhouse.csv").exists()

    # Farms: se detectan los dos nuevos y se registra el ADM3 problemático
    assert (output_dir / "farms" / "new_farms_to_create.csv").exists()
    problemas = pd.read_csv(output_dir / "farms" / "farms_adm3_issues.csv")
    assert len(problemas) == 1
    assert (output_dir / "farms" / "farms_adm3_not_in_catalog.csv").exists()


def test_marcar_nuevos_farms_crea_columnas_ausentes(mongo_connect_ok):
    """Un CSV sin PRODUCER_ID ni TIPO no debe romper la detección de nuevos."""
    from check_farms_enterprise.check_farms_enterprise import _marcar_nuevos_farms

    _crear_farm([ExtIdFarm(source=Source.SIT_CODE, ext_code="S1")])

    df = pd.DataFrame([{Source.SIT_CODE.value: "S1"}, {Source.SIT_CODE.value: "S2"}])
    out = _marcar_nuevos_farms(df)

    assert out[Source.SIT_CODE.value].tolist() == ["S2"]
    assert Source.PRODUCER_ID.value in out.columns
    assert "ADM3" in out.columns
