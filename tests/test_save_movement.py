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
from ganabosques_orm.enums.species import Species
from ganabosques_orm.enums.ugg import UGG

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
        # Crear estructuras administrativas necesarias
        Adm2(ext_id="0101").save()
        Adm2(ext_id="0202").save()
        Adm3(ext_id="010101").save()
        Adm3(ext_id="020202").save()
        

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