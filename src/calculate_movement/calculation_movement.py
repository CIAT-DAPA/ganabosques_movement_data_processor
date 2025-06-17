import os
import re
import pandas as pd
import logging
from tools.log_print import log_print 
from ganabosques_orm.enums.species import Species
from ganabosques_orm.enums.typemovement import TypeMovement
from config import config
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.label import Label

TypeMovement.FARM.value

logger = logging.getLogger("Calculate movement")

def extract_year_from_filename(filename):
    match = re.search(r"(20\d{2})", filename)
    return match.group(1) if match else "unknown"

def calc_mov(path_input, path_output, source="SIGMA"):
    os.makedirs(path_output, exist_ok=True)

    # Crear subcarpetas
    farms_dir = os.path.join(path_output, "farms")
    enterprise_dir = os.path.join(path_output, "enterprise")
    movement_dir = os.path.join(path_output, "movement")

    os.makedirs(farms_dir, exist_ok=True)
    os.makedirs(enterprise_dir, exist_ok=True)
    os.makedirs(movement_dir, exist_ok=True)

    log_print(logger, "Iniciando el proceso de calcular movilización...")

    especie_mapping = config.get("especie_mapping", {})

    for file in os.listdir(path_input):
        if file.endswith(".csv"):
            log_lines = []
            log_print(logger, f"Procesando archivo: {file}")
            file_path = os.path.join(path_input, file)

            year_used = extract_year_from_filename(file)

            try:
                df = pd.read_csv(file_path, sep=",", engine="python", encoding="utf-8")
                log_print(logger, "Archivo leído correctamente.")

                # Limpiar columnas y valores
                df.columns = df.columns.str.strip()
                if 'ESPECIE' in df.columns:
                    df['ESPECIE'] = df['ESPECIE'].astype(str).str.strip().str.lower()
                    df['ESPECIE'] = df['ESPECIE'].map(lambda x: especie_mapping.get(x, x))
                    df = df[df['ESPECIE'].isin([Species.BOVINOS.value, Species.BUFALINOS.value])]
                    log_print(logger, "Filtrado de especies completado.")
                else:
                    log_print(logger, f"Columna ESPECIE no encontrada en {file}", "error")
                    continue

                # Guardar movilización en subcarpeta movement
                movilizacion_output_file = os.path.join(movement_dir, f"movement_data_base_{year_used}.csv")
                df.to_csv(movilizacion_output_file, index=False, encoding='utf-8-sig')
                log_print(logger, f"Archivo unificado guardado: {movilizacion_output_file}")
                log_lines.append(f"Archivo procesado: {file} (Registros: {len(df)})")
                
                type_origin_col = config["origen_destino"][source]["type_origin"]
                type_dest_col = config["origen_destino"][source]["type_destination"]


                # --- Generar predios ---
                predios_origen = df[df[type_origin_col] == TypeMovement.FARM.value][[ 
                    type_origin_col, f"{Source.SIT_CODE.value}_ORIGEN", f"{Source.PRODUCER_ID.value}_ORIGEN", "ADM3_ORIGEN"
                ]].rename(columns={
                    type_origin_col: "TIPO",
                    f"{Source.SIT_CODE.value}_ORIGEN": Source.SIT_CODE.value,
                    f"{Source.PRODUCER_ID.value}_ORIGEN": Source.PRODUCER_ID.value,
                    "ADM3_ORIGEN": "ADM3"
                })

                predios_destino = df[df[type_dest_col] ==  TypeMovement.FARM.value][[ 
                    type_dest_col, f"{Source.SIT_CODE.value}_DESTINO", f"{Source.PRODUCER_ID.value}_DESTINO", "ADM3_DESTINO"
                ]].rename(columns={
                    type_dest_col: "TIPO",
                    f"{Source.SIT_CODE.value}_DESTINO": Source.SIT_CODE.value,
                    f"{Source.PRODUCER_ID.value}_DESTINO": Source.PRODUCER_ID.value,
                    "ADM3_DESTINO": "ADM3"
                })

                predios = pd.concat([predios_origen, predios_destino], ignore_index=True)
                predios = predios.drop_duplicates(subset=[Source.SIT_CODE.value])

                farms_output_file = os.path.join(farms_dir, f"farms_data_base_{year_used}.csv")
                predios.to_csv(farms_output_file, index=False, encoding='utf-8-sig')
                log_print(logger, f"Archivo de predios guardado: {farms_output_file}")
                log_lines.append(f"Archivo farms_data_base_{year_used}.csv guardado (Registros únicos: {len(predios)})")

                # --- Generar empresas ---
                empresas_origen = df[df[type_origin_col] !=  TypeMovement.FARM.value][[ 
                    type_origin_col, f"{Source.PRODUCER_ID.value}_ORIGEN", "ADM2_ORIGEN"
                ]].rename(columns={
                    type_origin_col: "TIPO",
                    f"{Source.PRODUCER_ID.value}_ORIGEN": Label.PRODUCTIONUNIT_ID.value,
                    "ADM2_ORIGEN": "ADM2"
                })

                empresas_destino = df[df[type_dest_col] != TypeMovement.FARM.value][[ 
                    type_dest_col, f"{Source.PRODUCER_ID.value}_DESTINO", "ADM2_DESTINO"
                ]].rename(columns={
                    type_dest_col: "TIPO",
                    f"{Source.PRODUCER_ID.value}_DESTINO": Label.PRODUCTIONUNIT_ID.value,
                    "ADM2_DESTINO": "ADM2"
                })

                empresas = pd.concat([empresas_origen, empresas_destino], ignore_index=True)
                empresas = empresas.drop_duplicates(subset=[Label.PRODUCTIONUNIT_ID.value])

                enterprise_output_file = os.path.join(enterprise_dir, f"enterprise_data_base_{year_used}.csv")
                empresas.to_csv(enterprise_output_file, index=False, encoding='utf-8-sig')
                log_print(logger, f"Archivo de empresas guardado: {enterprise_output_file}")
                log_lines.append(f"Archivo enterprise_data_base_{year_used}.csv guardado (Registros únicos: {len(empresas)})")

                # --- Guardar log por archivo ---
                log_path = os.path.join(path_output, f"log_calc_mov_{year_used}.txt")
                with open(log_path, "w", encoding="utf-8") as log_file:
                    log_file.write("\n".join(log_lines))
                log_print(logger, f"Log guardado en: {log_path}")

            except Exception as e:
                log_print(logger, f"Error procesando {file}: {e}", "error")
                continue
