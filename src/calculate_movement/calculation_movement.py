import os
import re
import pandas as pd
import logging
from tools.log_print import log_print 
from ganabosques_orm.enums.species import Species
from config import config

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

                # --- Generar predios ---
                predios_origen = df[df["TIPO_ORIGEN"] == "FARM"][[ 
                    "TIPO_ORIGEN", "SIT_CODE_ORIGEN", "PRODUCER_ID_ORIGEN", "ADM3_ORIGEN"
                ]].rename(columns={
                    "TIPO_ORIGEN": "TIPO",
                    "SIT_CODE_ORIGEN": "SIT_CODE",
                    "PRODUCER_ID_ORIGEN": "PRODUCER_ID",
                    "ADM3_ORIGEN": "ADM3"
                })

                predios_destino = df[df["TIPO_DESTINO"] == "FARM"][[ 
                    "TIPO_DESTINO", "SIT_CODE_DESTINO", "PRODUCER_ID_DESTINO", "ADM3_DESTINO"
                ]].rename(columns={
                    "TIPO_DESTINO": "TIPO",
                    "SIT_CODE_DESTINO": "SIT_CODE",
                    "PRODUCER_ID_DESTINO": "PRODUCER_ID",
                    "ADM3_DESTINO": "ADM3"
                })

                predios = pd.concat([predios_origen, predios_destino], ignore_index=True)
                predios = predios.drop_duplicates(subset=["SIT_CODE"])

                farms_output_file = os.path.join(farms_dir, f"farms_data_base_{year_used}.csv")
                predios.to_csv(farms_output_file, index=False, encoding='utf-8-sig')
                log_print(logger, f"Archivo de predios guardado: {farms_output_file}")
                log_lines.append(f"Archivo farms_data_base_{year_used}.csv guardado (Registros únicos: {len(predios)})")

                # --- Generar empresas ---
                empresas_origen = df[df["TIPO_ORIGEN"] != "FARM"][[ 
                    "TIPO_ORIGEN", "PRODUCER_ID_ORIGEN", "ADM2_ORIGEN"
                ]].rename(columns={
                    "TIPO_ORIGEN": "TIPO",
                    "PRODUCER_ID_ORIGEN": "PRODUCTIONUNIT_ID",
                    "ADM2_ORIGEN": "ADM2"
                })

                empresas_destino = df[df["TIPO_DESTINO"] != "FARM"][[ 
                    "TIPO_DESTINO", "PRODUCER_ID_DESTINO", "ADM2_DESTINO"
                ]].rename(columns={
                    "TIPO_DESTINO": "TIPO",
                    "PRODUCER_ID_DESTINO": "PRODUCTIONUNIT_ID",
                    "ADM2_DESTINO": "ADM2"
                })

                empresas = pd.concat([empresas_origen, empresas_destino], ignore_index=True)
                empresas = empresas.drop_duplicates(subset=["PRODUCTIONUNIT_ID"])

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
