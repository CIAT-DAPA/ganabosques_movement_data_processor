import os
import pandas as pd
import tempfile
from datetime import datetime
from ganabosques_orm.collections.farm import Farm
from ganabosques_orm.collections.enterprise import Enterprise
from ganabosques_orm.collections.movement import Movement
from ganabosques_orm.collections.adm1 import Adm1
from ganabosques_orm.collections.adm2 import Adm2
from ganabosques_orm.collections.adm3 import Adm3
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.label import Label
from ganabosques_orm.enums.typeenterprise import TypeEnterprise
from ganabosques_orm.enums.farmsource import FarmSource
from ganabosques_orm.enums.species import Species
from ganabosques_orm.auxiliaries.log import Log

from save_movement.save_movement import procesar_csv_movimientos, process_farm_identifiers, process_enterprise_identifiers, get_enterprise_from_row, get_farm_from_row, iguales_con_nan, save_movements, save_enterprise_identifiers, save_farm_identifiers

def create_mock_movement_files(base_dir):
    # Crear archivo de movimientos
    movements = pd.DataFrame([{
        "TIPO_ORIGEN": "FARM",
        "SIT_CODE_ORIGEN": "SIT001",
        "PRODUCER_ID_ORIGEN": "PROD001",
        "ADM1_ORIGEN": "01",
        "ADM2_ORIGEN": "0101",
        "ADM3_ORIGEN": "010101",
        "TIPO_DESTINO": "COLLECTION_CENTER",
        "SIT_CODE_DESTINO": "",
        "PRODUCER_ID_DESTINO": "PROD002",
        "ADM1_DESTINO": "02",
        "ADM2_DESTINO": "0202",
        "ADM3_DESTINO": "020202",
        "ESPECIE": "bovinos",
        "TERNEROS_MENORES_1_ANIO": 5,
        "EXT_ID": "MOV001",
        "DATE": "2024-06-01"
    }])
    movements_path = os.path.join(base_dir, "movements.csv")
    movements.to_csv(movements_path, index=False)

    # Crear archivo de farms
    farms = pd.DataFrame([{
        "TIPO": "FARM",
        "SIT_CODE": "SIT001",
        "PRODUCER_ID": "PROD001",
        "ADM3": "010101"
    }])
    farms_path = os.path.join(base_dir, "farms.csv")
    farms.to_csv(farms_path, index=False)

    # Crear archivo de enterprises
    enterprises = pd.DataFrame([{
        "TIPO": "COLLECTION_CENTER",
        "PRODUCTIONUNIT_ID": "PROD002",
        "ADM2": "0202",
        "NOMBRE": "Centro Acopio 1",
        "LATITUD": 4.5,
        "LONGITUD": -75.0
    }])
    enterprises_path = os.path.join(base_dir, "enterprises.csv")
    enterprises.to_csv(enterprises_path, index=False)

    return movements_path, farms_path, enterprises_path

def test_procesar_csv_movimientos_success():
    with tempfile.TemporaryDirectory() as tmpdir:

        # Crear archivos temporales de entrada
        movement_path, farm_path, enterprise_path = create_mock_movement_files(tmpdir)
        output_path = os.path.join(tmpdir, "errores")
        os.makedirs(output_path, exist_ok=True)

        # Crear entidades base
        process_farm_identifiers(farm_path, output_path, source="SIGMA")
        process_enterprise_identifiers(enterprise_path, output_path)

        # Ejecutar la función principal
        procesar_csv_movimientos(movement_path, output_path, source_pro="SIGMA")

        # Validaciones
        movimiento = Movement.objects(ext_id="MOV001").first()
        assert movimiento is not None
        assert movimiento.species == Species.BOVINOS
        assert movimiento.ext_id == "MOV001"
        assert movimiento.type_origin.name == "FARM"
        assert movimiento.type_destination.name == "COLLECTION_CENTER"
        assert movimiento.movement[0].amount == 5
        
def test_procesar_csv_farm_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        
        # Crear archivos temporales de entrada
        movement_path, farm_path, enterprise_path = create_mock_movement_files(tmpdir)
        output_path = os.path.join(tmpdir, "errores")
        os.makedirs(output_path, exist_ok=True)

        # Ejecutar la función principal
        process_farm_identifiers(farm_path, output_path, source="SIGMA")

        # Validaciones
        farm = Farm.objects().first()
        
        sit_entry = next((e for e in farm.ext_id if e["source"] == Source.SIT_CODE), None)
        producer_entry = next((e for e in farm.ext_id if e["source"] == Source.PRODUCER_ID), None)

        assert sit_entry is not None
        assert sit_entry["ext_code"] == "SIT001"
        assert producer_entry is not None
        assert producer_entry["ext_code"] == "PROD001"
        assert farm is not None
        assert farm.farm_source == FarmSource.SIGMA
        assert farm.adm3_id.ext_id == "010101"
        
def test_procesar_csv_enterprise_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear archivos de entrada simulados
        movement_path, farm_path, enterprise_path = create_mock_movement_files(tmpdir)
        output_path = os.path.join(tmpdir, "errores")
        os.makedirs(output_path, exist_ok=True)

        # Ejecutar la función de procesamiento
        process_enterprise_identifiers(enterprise_path, output_path)

        # Validaciones
        enterprise = Enterprise.objects().first()
        assert enterprise is not None
        assert enterprise.name == "Centro Acopio 1"
        assert enterprise.adm2_id.ext_id == "0202"
        assert enterprise.type_enterprise == TypeEnterprise.COLLECTION_CENTER

        # Verificamos que los identificadores externos estén correctamente asignados
        ids = {e.label: e.ext_code for e in enterprise.ext_id}
        assert Label.PRODUCTIONUNIT_ID in ids
        assert ids[Label.PRODUCTIONUNIT_ID] == "PROD002"

def test_update_existing_entities():
    with tempfile.TemporaryDirectory() as tmpdir:

        # Crear archivos de prueba
        movement_path, farm_path, enterprise_path = create_mock_movement_files(tmpdir)        
        output_path = os.path.join(tmpdir, "errores")

        # Crear Farm y Enterprise existentes con los mismos códigos que en los CSV
        farm = Farm(
            adm3_id=Adm3.objects(ext_id="010101").first(),
            ext_id=[{"source": Source.SIT_CODE, "ext_code": "SIT001"}],
            farm_source=FarmSource.SAGARI,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        farm.save()

        enterprise = Enterprise(
            name="Centro Antiguo",
            adm2_id=Adm2.objects(ext_id="0202").first(),
            ext_id=[{"label": Label.PRODUCTIONUNIT_ID, "ext_code": "PROD002"}],
            type_enterprise = TypeEnterprise.SLAUGHTERHOUSE,
            latitude = 7.3,
            longitud = 75,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        enterprise.save()
        
        # Crear entidades base
        process_farm_identifiers(farm_path, output_path, source="SIGMA")
        process_enterprise_identifiers(enterprise_path, output_path)

        # Validaciones: no se duplicaron, pero sí se actualizaron fuentes
        assert Farm.objects.count() == 1
        assert Enterprise.objects.count() == 1

        updated_farm = Farm.objects.first()
        updated_enterprise = Enterprise.objects.first()

        # Debe tener ambos sources si se actualizaron correctamente
        farm_sources = {e["source"] for e in updated_farm.ext_id}
        enterprise_sources = {e["label"] for e in updated_enterprise.ext_id}

        assert Source.SIT_CODE in farm_sources
        assert Source.PRODUCER_ID in farm_sources  # se agregó nuevo source

        assert Label.PRODUCTIONUNIT_ID in enterprise_sources
        assert updated_enterprise.name == "Centro Acopio 1"
        assert updated_enterprise.latitude == 4.5 # cambio la latitud original
        assert updated_enterprise.longitud == -75.0 # cambio la longitud original
        assert updated_enterprise.type_enterprise ==  TypeEnterprise.COLLECTION_CENTER # cambio el tipo de empresa

def test_missing_destination_reference():
    """
    Verifica que se genere un archivo de errores si el origen del movimiento (finca o empresa) no se encuentra.

    En este caso, el archivo de movimientos contiene un SIT_CODE_ORIGEN que no está en la base de datos mock de farms.
    Se espera que la función identifique este error y lo registre en el archivo CSV de errores.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear datos con SIT_CODE_ORIGEN no registrado
        movements = pd.DataFrame([{
            "TIPO_ORIGEN": "FARM",
            "SIT_CODE_ORIGEN": "SIT999",  # No existe en farms
            "PRODUCER_ID_ORIGEN": "PROD001",
            "ADM1_ORIGEN": "01",
            "ADM2_ORIGEN": "0101",
            "ADM3_ORIGEN": "010101",
            "TIPO_DESTINO": "COLLECTION_CENTER",
            "SIT_CODE_DESTINO": "",
            "PRODUCER_ID_DESTINO": "PROD002",
            "ADM1_DESTINO": "02",
            "ADM2_DESTINO": "0202",
            "ADM3_DESTINO": "020202",
            "ESPECIE": "bovinos",
            "TERNEROS_MENORES_1_ANIO": 5,
            "EXT_ID": "MOV002",
            "DATE": "2024-06-01"
        }])
        movements_path = os.path.join(tmpdir, "movements.csv")
        movements.to_csv(movements_path, index=False)
        
        farm = Farm(
            adm3_id=Adm3.objects(ext_id="010101").first(),
            ext_id=[{"source": Source.SIT_CODE, "ext_code": "SIT001"}],
            farm_source=FarmSource.SAGARI,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        farm.save()

        enterprise = Enterprise(
            name="Centro Antiguo",
            adm2_id=Adm2.objects(ext_id="0202").first(),
            ext_id=[{"label": Label.PRODUCTIONUNIT_ID, "ext_code": "PROD002"}],
            type_enterprise = TypeEnterprise.COLLECTION_CENTER,
            latitude = 4.5,
            longitud = -75.0,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        enterprise.save()

        # Crear carpeta de salida
        output_path = os.path.join(tmpdir, "errores")
        os.makedirs(output_path, exist_ok=True)

        # Ejecutar función de procesamiento
        procesar_csv_movimientos(movements_path, output_path, source_pro="SIGMA")

        # Validar archivo de errores generado
        errores = [f for f in os.listdir(output_path) if f.startswith("movements")]
        assert len(errores) == 1, "No se generó archivo de errores."

        errores_df = pd.read_csv(os.path.join(output_path, errores[0]))
        assert not errores_df.empty, "El archivo de errores está vacío."
        assert "No se encontró Farm origen" in errores_df["error"].iloc[0]
        assert errores_df["SIT_CODE_ORIGEN"].iloc[0] == "SIT999"

def test_missing_origin_reference():
    """
    Verifica que se genere un archivo de errores si el destino del movimiento (finca o empresa) no se encuentra.

    En este caso, el archivo de movimientos contiene un PRODUCER_ID_DESTINO que no está en la base de datos mock de enterprises.
    Se espera que la función identifique este error y lo registre en el archivo CSV de errores.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear datos con PRODUCER_ID_DESTINO no registrado
        movements = pd.DataFrame([{
            "TIPO_ORIGEN": "FARM",
            "SIT_CODE_ORIGEN": "SIT001",  
            "PRODUCER_ID_ORIGEN": "PROD001",
            "ADM1_ORIGEN": "01",
            "ADM2_ORIGEN": "0101",
            "ADM3_ORIGEN": "010101",
            "TIPO_DESTINO": "COLLECTION_CENTER",
            "SIT_CODE_DESTINO": "",
            "PRODUCER_ID_DESTINO": "PROD999", # No existe en enterprise
            "ADM1_DESTINO": "02",
            "ADM2_DESTINO": "0202",
            "ADM3_DESTINO": "020202",
            "ESPECIE": "bovinos",
            "TERNEROS_MENORES_1_ANIO": 5,
            "EXT_ID": "MOV002",
            "DATE": "2024-06-01"
        }])
        movements_path = os.path.join(tmpdir, "movements.csv")
        movements.to_csv(movements_path, index=False)
        
        farm = Farm(
            adm3_id=Adm3.objects(ext_id="010101").first(),
            ext_id=[{"source": Source.SIT_CODE, "ext_code": "SIT001"}],
            farm_source=FarmSource.SAGARI,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        farm.save()

        enterprise = Enterprise(
            name="Centro Antiguo",
            adm2_id=Adm2.objects(ext_id="0202").first(),
            ext_id=[{"label": Label.PRODUCTIONUNIT_ID, "ext_code": "PROD002"}],
            type_enterprise = TypeEnterprise.COLLECTION_CENTER,
            latitude = 4.5,
            longitud = -75.0,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        enterprise.save()

        # Crear carpeta de salida
        output_path = os.path.join(tmpdir, "errores")
        os.makedirs(output_path, exist_ok=True)

        # Ejecutar función de procesamiento
        procesar_csv_movimientos(movements_path, output_path, source_pro="SIGMA")

        # Validar archivo de errores generado
        errores = [f for f in os.listdir(output_path) if f.startswith("movements")]
        assert len(errores) == 1, "No se generó archivo de errores."

        errores_df = pd.read_csv(os.path.join(output_path, errores[0]))
        assert not errores_df.empty, "El archivo de errores está vacío."
        assert "No se encontró Enterprise destino" in errores_df["error"].iloc[0]
        assert errores_df["PRODUCER_ID_DESTINO"].iloc[0] == "PROD999"
        
def test_invalid_column():
    """
    Verifica que se genere un archivo de errores si el destino del movimiento (finca o empresa) no se encuentra.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        movements = pd.DataFrame([{
            "TIPO_ORIGEN": "FARM",
            "SIT_CODE_ORIGEN": "SIT001",  
            "PRODUCER_ID_ORIGEN": "PROD001",
            "ADM1_ORIGEN": "01",
            "ADM2_ORIGEN": "0101",
            "ADM3_ORIGEN": "010101",
            "TIPO_DESTINO": "COLLECTION_CENTER",
            "SIT_CODE_DESTINO": "",
            "PRODUCER_ID_DESTINO": "PROD002",
            # "ESPECIE": "bovinos", se omite una columna necesaria
            "ADM1_DESTINO": "02",
            "ADM2_DESTINO": "0202",
            "ADM3_DESTINO": "020202",
            "TERNEROS_MENORES_1_ANIO": 5,
            "EXT_ID": "MOV002",
            "DATE": "2024-06-01"
        }])
        movements_path = os.path.join(tmpdir, "movements.csv")
        movements.to_csv(movements_path, index=False)
        
        farm = Farm(
            adm3_id=Adm3.objects(ext_id="010101").first(),
            ext_id=[{"source": Source.SIT_CODE, "ext_code": "SIT001"}],
            farm_source=FarmSource.SAGARI,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        farm.save()

        enterprise = Enterprise(
            name="Centro Antiguo",
            adm2_id=Adm2.objects(ext_id="0202").first(),
            ext_id=[{"label": Label.PRODUCTIONUNIT_ID, "ext_code": "PROD002"}],
            type_enterprise = TypeEnterprise.COLLECTION_CENTER,
            latitude = 4.5,
            longitud = -75.0,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        enterprise.save()

        # Crear carpeta de salida
        output_path = os.path.join(tmpdir, "errores")
        os.makedirs(output_path, exist_ok=True)

        # Ejecutar función de procesamiento
        procesar_csv_movimientos(movements_path, output_path, source_pro="SIGMA")

        # Validar archivo de errores generado
        errores = [f for f in os.listdir(output_path) if f.startswith("movements")]
        assert len(errores) == 1, "No se generó archivo de errores."

        errores_df = pd.read_csv(os.path.join(output_path, errores[0]))
        assert not errores_df.empty, "El archivo de errores está vacío."
        assert "ESPECIE" in errores_df["error"].iloc[0]