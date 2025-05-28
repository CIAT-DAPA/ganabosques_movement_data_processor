#####################################################################
######################    Brayan Mora   #############################
###################### quality control  #############################
#####################################################################

import os
import pandas as pd
import logging
from tools.log_print import log_print

logger = logging.getLogger("Quality control movement")

def mov_quality_control(path_input, path_output):
    os.makedirs(path_output, exist_ok=True)
    log_data = []

    log_print(logger, "🔷 Iniciando proceso de control de calidad...")

    for file in os.listdir(path_input):
        if file.endswith(".csv"):
            year = ''.join(filter(str.isdigit, file))
            file_path = os.path.join(path_input, file)
            base_filename = os.path.splitext(file)[0]

            log_print(logger, f"\n📂 Procesando archivo: {file}")

            try:
                df = pd.read_csv(file_path, sep=",", engine="python", encoding="utf-8")
                log_print(logger, f"✅ Archivo leído correctamente: {file}")

                # Validar existencia de columnas requeridas
                if 'TIPO_ORIGEN' not in df.columns or 'TIPO_DESTINO' not in df.columns:
                    log_print(logger, f"⚠️ Columnas TIPO_ORIGEN o TIPO_DESTINO no encontradas en {file}", "warning")
                    continue

                tipos_origen = df['TIPO_ORIGEN'].dropna().unique()
                tipos_destino = df['TIPO_DESTINO'].dropna().unique()
                
                df_final = []  # Lista para almacenar los dataframes válidos

                for origen in tipos_origen:
                    for destino in tipos_destino:
                        combo = f"{origen.strip()} - {destino.strip()}"
                        df_combo = df[(df['TIPO_ORIGEN'] == origen) & (df['TIPO_DESTINO'] == destino)]

                        total_rows = len(df_combo)

                        if origen.strip().upper() == 'PREDIO' and destino.strip().upper() == 'PREDIO':
                            df_valid = df_combo[
                                df_combo['CODIGO_SIT_ORIGEN'].notna() & df_combo['CODIGO_SIT_DESTINO'].notna()
                            ]
                        elif origen.strip().upper() == 'PREDIO':
                            df_valid = df_combo[df_combo['CODIGO_SIT_ORIGEN'].notna()]
                        elif destino.strip().upper() == 'PREDIO':
                            df_valid = df_combo[df_combo['CODIGO_SIT_DESTINO'].notna()]
                        else:
                            df_valid = df_combo.copy()

                        valid_rows = len(df_valid)
                        removed_rows = total_rows - valid_rows
                        removal_pct = (removed_rows / total_rows * 100) if total_rows else 0

                        log_print(logger, f" Combinación: {combo} | Total: {total_rows} | Usados: {valid_rows} | Removidos: {removed_rows} ({removal_pct:.2f}%)")

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

                if df_final:
                    df_concat = pd.concat(df_final, ignore_index=True)
                    output_filename = f"{base_filename}_depurado.csv"
                    df_concat.to_csv(os.path.join(path_output, output_filename), index=False, encoding='utf-8-sig')
                    log_print(logger, f"💾 Archivo depurado guardado como: {output_filename}")

            except Exception as e:
                log_print(logger, f" Error leyendo {file}: {e}", "error")

    df_log = pd.DataFrame(log_data)
    df_log.to_csv(os.path.join(path_output, "log_mov_quality_control.csv"), index=False, encoding='utf-8-sig')
    log_print(logger, " Log guardado como: log_mov_quality_control.csv")
    log_print(logger, " Proceso finalizado.")
