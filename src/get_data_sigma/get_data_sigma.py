import os
import re
import pandas as pd
import unidecode
import logging
from tools.log_print import log_print
from config import config
from ganabosques_orm.enums.source import Source

logger = logging.getLogger("Get Data")

def get_sigma(path_input, path_output):
    log_print(logger, 'Inicio del proceso get_data_sigma...')

    columnas_requeridas = config["columnas_requeridas_sigma"]
    log_resultados = []

    os.makedirs(path_output, exist_ok=True)
    archivos = [f for f in os.listdir(path_input) if f.endswith('.txt') and re.search(r'\d{4}', f)]
    log_print(logger, f"Número de archivos de movilización disponibles: {len(archivos)}")

    for i, archivo in enumerate(archivos, start=1):
        ruta_archivo = os.path.join(path_input, archivo)
        anio = re.search(r'\d{4}', archivo).group()

        try:
            df = pd.read_csv(ruta_archivo, sep='|', encoding='latin1', dtype=str)
            columnas_disponibles = df.columns.tolist()
            columnas_faltantes = [col for col in columnas_requeridas if col not in columnas_disponibles]

            if columnas_faltantes:
                log_resultados.append(f"{archivo} ({anio}): FALTAN columnas -> {columnas_faltantes}")
            else:
                log_resultados.append(f"{archivo} ({anio}): Todas las columnas requeridas están presentes.")

            columnas_filtradas = [col for col in columnas_requeridas if col in columnas_disponibles]
            df_filtrado = df[columnas_filtradas].copy()

            def limpiar_texto(texto):
                if isinstance(texto, str):
                    texto = texto.lower()
                    texto = unidecode.unidecode(texto)
                    texto = texto.replace('ñ', 'n')
                return texto

            for col in df_filtrado.columns:
                if df_filtrado[col].dtype == 'object':
                    df_filtrado[col] = df_filtrado[col].map(limpiar_texto)

            if {'ANIO', 'MES', 'DIA'}.issubset(df_filtrado.columns):
                df_filtrado['DATE'] = pd.to_datetime(
                    df_filtrado['ANIO'] + '-' + df_filtrado['MES'] + '-' + df_filtrado['DIA'],
                    errors='coerce'
                )
                df_filtrado = df_filtrado.drop(columns=['ANIO', 'MES', 'DIA'])

            df_filtrado = df_filtrado.rename(columns={
                'NUMERO_GUIA': "EXT_ID",
                'ID_DEPARTAMENTO_ORIGEN': "ADM1_ORIGEN",
                'ID_MUNICIPIO_ORIGEN': "ADM2_ORIGEN",
                'ID_VEREDA_ORIGEN': "ADM3_ORIGEN",
                'ID_DEPARTAMENTO_DESTINO': "ADM1_DESTINO",
                'ID_MUNICIPIO_DESTINO': "ADM2_DESTINO",
                'ID_VEREDA_DESTINO': "ADM3_DESTINO",
                'CODIGO_SIT_ORIGEN': f"{Source.SIT_CODE.value}_ORIGEN",
                'CODIGO_SIT_DESTINO': f"{Source.SIT_CODE.value}_DESTINO",
                'ID_UNIDAD_PRODUCTORA_ORIGEN': f"{Source.PRODUCER_ID.value}_ORIGEN",
                'ID_UNIDAD_PRODUCTORA_DESTINO': f"{Source.PRODUCER_ID.value}_DESTINO"
            })

            # 💡 Normalizar columna ESPECIE
            if "ESPECIE" in df_filtrado.columns:
                especie_map = config.get("especie_map", {})

                def corregir_especie(val):
                    if pd.isna(val):
                        return val
                    val = val.lower()
                    for key, value in especie_map.items():
                        if key in val:
                            return value
                    return val

                df_filtrado["ESPECIE"] = df_filtrado["ESPECIE"].apply(corregir_especie)

            # Guardar archivo procesado
            output_filename = f"{os.path.splitext(archivo)[0]}_filtrado_limpio.csv"
            output_path = os.path.join(path_output, output_filename)
            df_filtrado.to_csv(output_path, index=False, encoding='utf-8')
            log_print(logger, f"""Archivo {i}, cargado y procesado: {archivo}""")

        except Exception as e:
            log_resultados.append(f"{archivo} ({anio}): ERROR al procesar -> {e}")

    log_print(logger, 'Proceso finalizado.')

    # Guardar log
    log_path = os.path.join(path_output, "log_columnas.txt")
    with open(log_path, "w", encoding='utf-8') as f:
        for linea in log_resultados:
            f.write(linea + "\n")
