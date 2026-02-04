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

logger = logging.getLogger("Calculate movement")


def extract_year_from_filename(filename):
    match = re.search(r"(20\d{2})", filename)
    return match.group(1) if match else "unknown"


def safe_convert_int(df, columns):
    # Mantengo tu lógica tal cual (sin mejoras) porque así lo pediste.
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').dropna().astype(int)
    return df


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

    for file in os.listdir(path_input):
        if not file.endswith(".csv"):
            continue

        log_lines = []
        log_print(logger, f"Procesando archivo: {file}")
        file_path = os.path.join(path_input, file)

        year_used = extract_year_from_filename(file)

        try:
            df = pd.read_csv(file_path, sep=",", engine="python", encoding="utf-8")
            log_print(logger, "Archivo leído correctamente.")

            df.columns = df.columns.str.strip()

            # === Filtrado por especie ===
            if 'ESPECIE' in df.columns:
                df = df[df['ESPECIE'].isin([Species.BOVINOS.value, Species.BUFALINOS.value])]
                log_print(logger, "Filtrado de especies completado.")
            else:
                log_print(logger, f"Columna ESPECIE no encontrada en {file}", "error")
                continue

            # === Convertir columnas a enteros en movement ===
            movement_int_cols = [
                f"{Source.SIT_CODE.value}_ORIGEN", f"{Source.SIT_CODE.value}_DESTINO",
                f"{Source.PRODUCER_ID.value}_ORIGEN", f"{Source.PRODUCER_ID.value}_DESTINO",
                "ADM1_ORIGEN", "ADM2_ORIGEN", "ADM3_ORIGEN",
                "ADM1_DESTINO", "ADM2_DESTINO", "ADM3_DESTINO"
            ]

            df = safe_convert_int(df, movement_int_cols)

            # === ADM3: forzar faltantes a 999999999999 ===
            for adm_col in ["ADM3_ORIGEN", "ADM3_DESTINO"]:
                if adm_col in df.columns:
                    df[adm_col] = pd.to_numeric(df[adm_col], errors="coerce").fillna(999999999999).astype("int64")

            # ============================================================
            # Control de duplicados por EXT_ID (lo que pediste)
            #  Escenario 1: filas idénticas en todas las columnas -> dejar 1
            #  Escenario 2: mismo EXT_ID pero diferencias en otras columnas -> eliminar todas y reportar
            # ============================================================
            df_errors = pd.DataFrame()

            if "EXT_ID" in df.columns:
                # Normalizar EXT_ID (string)
                df["EXT_ID"] = df["EXT_ID"].astype(str).str.strip()
                df.loc[df["EXT_ID"].isin(["", "nan", "None", "NULL", "NAN"]), "EXT_ID"] = pd.NA

                # --- Escenario 1: duplicado exacto (toda la fila igual) ---
                before_exact = len(df)
                df = df.drop_duplicates(keep="first").copy()
                removed_exact = before_exact - len(df)
                if removed_exact > 0:
                    log_print(logger, f"🧹 Duplicados exactos eliminados (todas las columnas iguales): {removed_exact}")
                    log_lines.append(f"Duplicados exactos eliminados: {removed_exact}")

                # --- Escenario 2: EXT_ID duplicado con diferencias ---
                dup_ext_mask = df["EXT_ID"].notna() & df.duplicated(subset=["EXT_ID"], keep=False)
                dup_ext_ids = df.loc[dup_ext_mask, "EXT_ID"].unique()

                if len(dup_ext_ids) > 0:
                    df_conflict = df[df["EXT_ID"].isin(dup_ext_ids)].copy()
                    df_errors = df_conflict.copy()
                    df = df[~df["EXT_ID"].isin(dup_ext_ids)].copy()

                    log_print(logger, f"❌ EXT_ID duplicados con diferencias (escenario 2). Eliminados del df: {len(df_errors)}")
                    log_lines.append(
                        f"EXT_ID conflictivos eliminados (escenario 2): {len(df_errors)} | EXT_ID únicos: {len(dup_ext_ids)}"
                    )

                    # Guardar df_errors
                    errors_output_file = os.path.join(movement_dir, f"movement_errors_extid_{year_used}.csv")
                    df_errors.to_csv(errors_output_file, index=False, encoding="utf-8-sig")
                    log_print(logger, f"📄 Archivo df_errors guardado: {errors_output_file}")
                else:
                    log_print(logger, "✅ No se encontraron EXT_ID conflictivos (escenario 2).")
                    log_lines.append("No se encontraron EXT_ID conflictivos (escenario 2).")

            else:
                log_print(logger, f"⚠️ Columna EXT_ID no encontrada en {file}. No se aplica control de duplicados.", "warning")
                log_lines.append("Columna EXT_ID no encontrada. No se aplicó control de duplicados.")

            # === Guardar movement ===
            movement_output_file = os.path.join(movement_dir, f"movement_data_base_{year_used}.csv")
            df.to_csv(movement_output_file, index=False, encoding='utf-8-sig')
            log_print(logger, f"Archivo movement guardado: {movement_output_file}")
            log_lines.append(f"Archivo movement_data_base_{year_used}.csv guardado (Registros: {len(df)})")

            type_origin_col = config["origen_destino"][source]["type_origin"]
            type_dest_col = config["origen_destino"][source]["type_destination"]

            # --- Generar farms ---
            predios_origen = df[df[type_origin_col] == TypeMovement.FARM.value][[
                type_origin_col, f"{Source.SIT_CODE.value}_ORIGEN", f"{Source.PRODUCER_ID.value}_ORIGEN", "ADM3_ORIGEN"
            ]].rename(columns={
                type_origin_col: "TIPO",
                f"{Source.SIT_CODE.value}_ORIGEN": Source.SIT_CODE.value,
                f"{Source.PRODUCER_ID.value}_ORIGEN": Source.PRODUCER_ID.value,
                "ADM3_ORIGEN": "ADM3"
            })

            predios_destino = df[df[type_dest_col] == TypeMovement.FARM.value][[
                type_dest_col, f"{Source.SIT_CODE.value}_DESTINO", f"{Source.PRODUCER_ID.value}_DESTINO", "ADM3_DESTINO"
            ]].rename(columns={
                type_dest_col: "TIPO",
                f"{Source.SIT_CODE.value}_DESTINO": Source.SIT_CODE.value,
                f"{Source.PRODUCER_ID.value}_DESTINO": Source.PRODUCER_ID.value,
                "ADM3_DESTINO": "ADM3"
            })

            predios = pd.concat([predios_origen, predios_destino], ignore_index=True)
            predios = predios.drop_duplicates(subset=[Source.SIT_CODE.value])
            predios = safe_convert_int(predios, [Source.SIT_CODE.value, Source.PRODUCER_ID.value, "ADM3"])

            farms_output_file = os.path.join(farms_dir, f"farms_data_base_{year_used}.csv")
            predios.to_csv(farms_output_file, index=False, encoding='utf-8-sig')
            log_print(logger, f"Archivo farms guardado: {farms_output_file}")
            log_lines.append(f"Archivo farms_data_base_{year_used}.csv guardado (Registros únicos: {len(predios)})")

            # --- Generar enterprise ---
            empresas_origen = df[df[type_origin_col] != TypeMovement.FARM.value][[
                type_origin_col, "PRODUCER_ID_ORIGEN", "ADM2_ORIGEN"
            ]].rename(columns={
                type_origin_col: "TIPO",
                "PRODUCER_ID_ORIGEN": Label.PRODUCTIONUNIT_ID.value,
                "ADM2_ORIGEN": "ADM2"
            })

            empresas_destino = df[df[type_dest_col] != TypeMovement.FARM.value][[
                type_dest_col, "PRODUCER_ID_DESTINO", "ADM2_DESTINO"
            ]].rename(columns={
                type_dest_col: "TIPO",
                "PRODUCER_ID_DESTINO": Label.PRODUCTIONUNIT_ID.value,
                "ADM2_DESTINO": "ADM2"
            })

            empresas = pd.concat([empresas_origen, empresas_destino], ignore_index=True)
            empresas = safe_convert_int(empresas, [Label.PRODUCTIONUNIT_ID.value, "ADM2"])

            enterprise_output_file = os.path.join(enterprise_dir, f"enterprise_data_base_{year_used}.csv")
            empresas.to_csv(enterprise_output_file, index=False, encoding='utf-8-sig')
            log_print(logger, f"Archivo enterprise guardado: {enterprise_output_file}")
            log_lines.append(f"Archivo enterprise_data_base_{year_used}.csv guardado (Registros únicos: {len(empresas)})")

            # Guardar log
            log_path = os.path.join(path_output, f"log_calc_mov_{year_used}.txt")
            with open(log_path, "w", encoding="utf-8") as log_file:
                log_file.write("\n".join(log_lines))
            log_print(logger, f"Log guardado en: {log_path}")

        except Exception as e:
            log_print(logger, f"Error procesando {file}: {e}", "error")
            continue
