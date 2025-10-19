#####################################################################
######################    Brayan Mora   #############################
###################### quality control  #############################
#####################################################################

import os
import pandas as pd
import logging
from tools.log_print import log_print
from config import config
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.enums.source import Source

logger = logging.getLogger("Quality control movement")

# Conjunto de literales que deben tratarse como faltantes
_MISSING_LITERALS = {"", "NAN", "NONE", "NULL"}

def _normalize_types(series: pd.Series, mapping: dict) -> pd.Series:
    """
    Normaliza columna de tipo:
      - Convierte a StringDtype (admite pd.NA),
      - Aplica strip y upper,
      - Convierte literales vacíos a NA,
      - Aplica mapeo (PREDIO -> FARM, etc.).
    """
    s = series.astype("string")  # permite pd.NA
    s = s.str.strip().str.upper()
    s = s.replace({lit: pd.NA for lit in _MISSING_LITERALS})
    s = s.replace(mapping)
    return s

def mov_quality_control(path_input, path_output, source="SIGMA"):
    os.makedirs(path_output, exist_ok=True)
    log_data = []

    log_print(logger, "🔷 Iniciando proceso de control de calidad...")

    # Diccionario de reclasificación (PREDIO→FARM, etc.)
    mapping = config["MOV"]

    # Columnas de tipo según la fuente
    type_origin_col = config["origen_destino"][source]["type_origin"]
    type_dest_col   = config["origen_destino"][source]["type_destination"]

    for file in os.listdir(path_input):
        if not file.lower().endswith(".csv"):
            continue

        file_path = os.path.join(path_input, file)
        base_filename = os.path.splitext(file)[0]

        log_print(logger, f"\n📂 Procesando archivo: {file}")

        try:
            df = pd.read_csv(file_path, sep=",", engine="python", encoding="utf-8")
            log_print(logger, f"✅ Archivo leído correctamente: {file}")

            # Validación de columnas requeridas de tipo
            if type_origin_col not in df.columns or type_dest_col not in df.columns:
                log_print(logger, f"⚠️ Columnas {type_origin_col} o {type_dest_col} no encontradas en {file}", "warning")
                continue

            # === Normalizar y reclasificar tipo origen/destino ===
            df[type_origin_col] = _normalize_types(df[type_origin_col], mapping)
            df[type_dest_col]   = _normalize_types(df[type_dest_col], mapping)

            # === Eliminar filas sin TIPO_ORIGEN o sin TIPO_DESTINO ===
            before_rows = len(df)
            df = df[df[type_origin_col].notna() & df[type_dest_col].notna()].copy()
            dropped_missing_types = before_rows - len(df)
            if dropped_missing_types > 0:
                log_print(logger, f"🧹 Filas descartadas por TIPO faltante: {dropped_missing_types}")

            if df.empty:
                log_print(logger, "⚠️ No quedan registros con tipos válidos tras limpieza; se omite archivo.", "warning")
                continue

            # === Asegurar columnas de códigos para evitar KeyError ===
            col_sit_o  = f"{Source.SIT_CODE.value}_ORIGEN"       # SIT_CODE_ORIGEN
            col_sit_d  = f"{Source.SIT_CODE.value}_DESTINO"      # SIT_CODE_DESTINO
            col_prod_o = f"{Source.PRODUCER_ID.value}_ORIGEN"    # PRODUCER_ID_ORIGEN
            col_prod_d = f"{Source.PRODUCER_ID.value}_DESTINO"   # PRODUCER_ID_DESTINO

            for c in (col_sit_o, col_sit_d, col_prod_o, col_prod_d):
                if c not in df.columns:
                    df[c] = pd.NA

            # === Valores únicos de tipos (ya sin NA) ===
            tipos_origen  = df[type_origin_col].unique()
            tipos_destino = df[type_dest_col].unique()

            df_final = []  # buffers de subconjuntos válidos
            FARM = TypeMovement.FARM.value

            for origen in tipos_origen:
                for destino in tipos_destino:
                    combo = f"{origen} - {destino}"
                    df_combo = df[(df[type_origin_col] == origen) & (df[type_dest_col] == destino)]
                    total_rows = len(df_combo)
                    if total_rows == 0:
                        continue

                    # Helpers por fila
                    has_sit_o   = df_combo[col_sit_o].notna() & (df_combo[col_sit_o].astype("string").str.strip() != "")
                    has_sit_d   = df_combo[col_sit_d].notna() & (df_combo[col_sit_d].astype("string").str.strip() != "")
                    has_prod_o  = df_combo[col_prod_o].notna() & (df_combo[col_prod_o].astype("string").str.strip() != "")
                    has_prod_d  = df_combo[col_prod_d].notna() & (df_combo[col_prod_d].astype("string").str.strip() != "")

                    # Reglas (originales + respaldo)
                    if origen == FARM and destino == FARM:
                        mask_valida = ((has_sit_o | has_prod_o) & (has_sit_d | has_prod_d))
                    elif origen == FARM and destino != FARM:
                        mask_valida = (has_sit_o | has_prod_o)
                    elif origen != FARM and destino == FARM:
                        mask_valida = (has_sit_d | has_prod_d)
                    else:
                        mask_valida = (has_prod_o & has_prod_d)

                    df_valid = df_combo[mask_valida]
                    valid_rows   = len(df_valid)
                    removed_rows = total_rows - valid_rows
                    removal_pct  = (removed_rows / total_rows * 100) if total_rows else 0.0

                    log_print(
                        logger,
                        f" Combinación: {combo} | Total: {total_rows} | Usados: {valid_rows} | "
                        f"Removidos: {removed_rows} ({removal_pct:.2f}%)"
                    )

                    if not df_valid.empty:
                        df_final.append(df_valid)

                    log_data.append({
                        'file': file,
                        'combination': combo,
                        'total_records': total_rows,
                        'records_removed': removed_rows,
                        'records_used': valid_rows,
                        'percent_removed': round(removal_pct, 2)
                    })

            # === Guardar depurado por archivo ===
            if df_final:
                df_concat = pd.concat(df_final, ignore_index=True)
                output_filename = f"{base_filename}_depurado.csv"
                df_concat.to_csv(os.path.join(path_output, output_filename), index=False, encoding='latin1')
                log_print(logger, f"💾 Archivo depurado guardado como: {output_filename}")
            else:
                log_print(logger, "⚠️ No hubo combinaciones válidas para guardar.", "warning")

        except Exception as e:
            log_print(logger, f"❌ Error leyendo {file}: {e}", "error")

    # === Log consolidado ===
    df_log = pd.DataFrame(log_data)
    df_log.to_csv(os.path.join(path_output, "log_mov_quality_control.csv"), index=False, encoding='utf-8-sig')
    log_print(logger, "📄 Log guardado como: log_mov_quality_control.csv")
    log_print(logger, "✅ Proceso finalizado.")
