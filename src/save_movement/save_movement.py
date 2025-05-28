
from mongoengine import connect
#import mongomock
import os
from tqdm import tqdm
from datetime import datetime

from tools.log_print import log_print
import logging
from config import config

import pandas as pd
from bson import ObjectId
from ganabosques_orm.collections.movement import Movement
from ganabosques_orm.auxiliaries.classification import Classification
from ganabosques_orm.auxiliaries.sourcemovement import SourceMovement
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.collections.farm import Farm
from ganabosques_orm.collections.enterprise import Enterprise


# Configuración del logger de este script
logger = logging.getLogger("Save Movement")

# ObjectId fijo para "ICA"
ICA_SOURCE_ID = ObjectId("5f5e1c5f5c5a5b5c5d5e5f5f")

# Columnas que no son tipos de ganado
EXCLUDE_COLUMNS = [
    'CODIGO_SIT_ORIGEN', 'CODIGO_SIT_DESTINO', 'NUMERO_GUIA',
    'ID_UNIDAD_PRODUCTORA_ORIGEN', 'ID_UNIDAD_PRODUCTORA_DESTINO',
    'TIPO_ORIGEN', 'TIPO_DESTINO', 'DATE', 'ESPECIE', 'TIPO_MOVIMIENTO',
    'ID_DEPARTAMENTO_ORIGEN', 'DEPARTAMENTO_ORIGEN', 'ID_MUNICIPIO_ORIGEN', 
    'MUNICIPIO_ORIGEN', 'ID_VEREDA_ORIGEN', 'VEREDA_ORIGEN', 'ID_DEPARTAMENTO_DESTINO', 
    'DEPARTAMENTO_DESTINO', 'ID_MUNICIPIO_DESTINO', 'MUNICIPIO_DESTINO', 'ID_VEREDA_DESTINO', 
    'VEREDA_DESTINO', 'TOTAL_ANIMALES'
]

type_movement_mapping = {
    "predio": "FARM",
    "planta de beneficio": "SLAUGHTERHOUSE",
    "planta": "SLAUGHTERHOUSE",
    "feria ganadera": "CATTLE_FAIR",
    "concentracion ganadera": "CATTLE_FAIR",
    "municipio": "MUNICIPALITY",
    "centro de acopio": "COLLECTION_CENTER",
    "empresa": "ENTERPRISE"
}


def procesar_csv_movimientos(csv_path):

    # Conexión a MongoDB (ajusta los valores a tu entorno)
    connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])
    #connect(db=config['MONGO_DB_NAME'], host='mongodb://localhost', mongo_client_class=mongomock.MongoClient)

    # Ruta del CSV
    df = pd.read_csv(csv_path, parse_dates=["DATE"], dayfirst=True)

    # Limpieza de nombres de columnas
    df.columns = df.columns.str.strip().str.replace("'", "").str.replace('"', '')

    # Columnas excluidas para detectar tipos de ganado
    ganado_columns = [col for col in df.columns if col not in EXCLUDE_COLUMNS]

    errores = []
    buenos, malos = 0, 0

    # Procesar cada fila
    for index, row in tqdm(df.iterrows(), total=len(df), desc=f"Procesando {os.path.basename(csv_path)}"):
        try:
            # Tipo origen y destino como enums
            tipo_origen_raw = row["TIPO_ORIGEN"].strip().lower()
            tipo_destino_raw = row["TIPO_DESTINO"].strip().lower()

            if tipo_origen_raw not in type_movement_mapping or tipo_destino_raw not in type_movement_mapping:
                #print(f"[SALTO] Fila {index} tiene tipo origen o destino inválido: '{tipo_origen_raw}' → '{tipo_destino_raw}'")
                malos += 1
                continue

            type_origin = TypeMovement[type_movement_mapping[tipo_origen_raw]]
            type_destination = TypeMovement[type_movement_mapping[tipo_destino_raw]]

            farm_id_origin, farm_id_destination = None, None
            enterprise_id_origin, enterprise_id_destination = None, None

            # Buscar origen
            if type_origin == TypeMovement.FARM:
                farm_id_origin = Farm.objects(
                    __raw__={
                        "$or": [
                            {
                                "ext_id": {
                                    "$elemMatch": {
                                        "source": "SIT_CODE",
                                        "ext_code": str(row["CODIGO_SIT_ORIGEN"])
                                    }
                                }
                            },
                            {
                                "ext_id": {
                                    "$elemMatch": {
                                        "source": "PRODUCER_ID",
                                        "ext_code": str(row["ID_UNIDAD_PRODUCTORA_ORIGEN"])
                                    }
                                }
                            }
                        ]
                    }
                ).first()
                if not farm_id_origin:
                    raise ValueError("No se encontró Farm origen")
            else:
                enterprise_id_origin = Enterprise.objects(
                    __raw__={
                        "ext_id": {
                            "$elemMatch": {
                                "label": "PRODUCTIONUNIT_ID",
                                "ext_code": str(row["ID_UNIDAD_PRODUCTORA_ORIGEN"])
                            }
                        }
                    }
                ).first()
                if not enterprise_id_origin:
                    raise ValueError("No se encontró Enterprise origen")

            # Buscar Destino
            if type_destination == TypeMovement.FARM:
                farm_id_destination = Farm.objects(
                    __raw__={
                        "$or": [
                            {
                                "ext_id": {
                                    "$elemMatch": {
                                        "source": "SIT_CODE",
                                        "ext_code": str(row["CODIGO_SIT_DESTINO"])
                                    }
                                }
                            },
                            {
                                "ext_id": {
                                    "$elemMatch": {
                                        "source": "PRODUCER_ID",
                                        "ext_code": str(row["ID_UNIDAD_PRODUCTORA_DESTINO"])
                                    }
                                }
                            }
                        ]
                    }
                ).first()
                if not farm_id_destination:
                    raise ValueError("No se encontró Farm destino")
            else:
                enterprise_id_destination = Enterprise.objects(
                    __raw__={
                        "ext_id": {
                            "$elemMatch": {
                                "label": "PRODUCTIONUNIT_ID",
                                "ext_code": str(row["ID_UNIDAD_PRODUCTORA_DESTINO"])
                            }
                        }
                    }
                ).first()
                if not enterprise_id_destination:
                    raise ValueError("No se encontró Enterprise destino")

            # Clasificaciones de ganado
            movement_list = []
            for col in ganado_columns:
                value = row[col]
                if pd.notna(value) and str(value).strip() not in ('', 'nan'):
                    movement_list.append(Classification(label=col, amount=int(value)))

            # Construir movimiento
            movimiento = Movement(
                date=row["DATE"],
                ext_id=row["NUMERO_GUIA"],
                type_origin=type_origin,
                type_destination=type_destination,
                source=SourceMovement(id=ICA_SOURCE_ID, name="ICA"),
                species=row["ESPECIE"].strip().upper(),
                farm_id_origin=farm_id_origin,
                farm_id_destination=farm_id_destination,
                enterprise_id_origin=enterprise_id_origin,
                enterprise_id_destination=enterprise_id_destination,
                movement=movement_list
            )

            #print(movimiento.to_mongo().to_dict())

            movimiento.validate()
            #movimiento.save()
            #print(f"[OK] Movimiento guardado para guía {row['NUMERO_GUIA']}")
            buenos += 1

        except Exception as e:
            error_msg = str(e)
            errores.append({**row.to_dict(), "fila_original": index, "error": error_msg})
            malos += 1

    log_print(logger, f"Completado: {buenos} guardados, {malos} con error.")

    if errores:
        os.makedirs("log_save", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file_path = f"log_save/save_movement_{timestamp}.csv"
        pd.DataFrame(errores).to_csv(error_file_path, index=False)
        log_print(logger, f"Errores guardados en: {error_file_path}")

def save_movements(path_root):
    archivos = [f for f in os.listdir(path_root) if f.endswith(".csv")]
    for archivo in archivos:
        ruta_completa = os.path.join(path_root, archivo)
        log_print(logger, f"Procesando archivo: {archivo}")
        procesar_csv_movimientos(ruta_completa)
