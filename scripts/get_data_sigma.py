import os
import re
import pandas as pd
import unidecode

def get_sigma(path_input, path_output):
    # Lista de columnas requeridas
    #columnas_requeridas = ['ANIO', 'CODIGO_SIT_ORIGEN', 'CODIGO_SIT_DESTINO','NUMERO_GUIA','ID_UNIDAD_PRODUCTORA_ORIGEN', 
    #    'DEPARTAMENTO_ORIGEN', 'MUNICIPIO_ORIGEN','VEREDA_ORIGEN', 'TIPO_ORIGEN', 'ID_UNIDAD_PRODUCTORA_DESTINO', 'DEPARTAMENTO_DESTINO', 
    #    'MUNICIPIO_DESTINO', 'VEREDA_DESTINO', 'TIPO_DESTINO','ESPECIE', 'TOTAL_ANIMALES', "'HEMBRAS MENOR DE 3 MESES'", "'HEMBRAS ENTRE 3 A 8 MESES'", "'HEMBRAS DE 8 A 12 MESES'", "'HEMBRAS 1 A 2 AÑOS'", 
    #    "'HEMBRAS 2 A 3 AÑOS'", "'HEMBRAS DE 3 A 5 AÑOS'", "'HEMBRAS MAYORES DE 5 AÑOS'", "'MACHOS MENOR DE 3 MESES'", "'MACHOS ENTRE 3 A 8 MESES'", "'MACHOS DE 8 A 12 MESES'", 
    #    "'MACHOS DE 1 A 2 AÑOS'", "'MACHOS DE 2 A 3 AÑOS'", "'MACHOS MAYORES A 3 AÑOS'", "'HEMBRA BUFALINA MENOR DE 3 ME", "'HEMBRA BUFALINA DE 3 A 8 MESE", 
    #    "'HEMBRA BUFALINA ENTRE 8 Y 12 ", "'HEMBRA BUFALINA DE 1 A 2 AÑO", "'HEMBRA BUFALINA DE 2 A 3 AÑO", "'HEMBRA BUFALINA DE 3 A 5 AÑO", "'HEMBRA BUFALINA MAYOR DE 5 A", 
    #    "'MACHOS BUFALINO MENOR DE 3 ME", "'MACHOS BUFALINO DE 3 A 8 MESE", "'MACHOS BUFALINO DE 8 A 12 MES", "'MACHOS BUFALINO DE 1 A 2 AÑO", "'MACHOS BUFALINO DE 2 A 3 AÑO", 
    #    "'MACHOS BUFALINO MAYORES A 3 A", "'LACTANTES HASTA 30 DIAS'", "'PRECEBO 31 A 60 DIAS'", "'LEVANTE CEBA 61 A 180 DIAS'", "'HEMBRA REEMPLAZO MENOR DE 8 M", 
    #    "'HEMBRA CRIA MAYOR A 8 MESES'", "'MACHO REPRODUCTOR MAYOR DE 6 "] 





    columnas_requeridas = ['ANIO', 'CODIGO_SIT_ORIGEN', 'CODIGO_SIT_DESTINO','NUMERO_GUIA','ID_UNIDAD_PRODUCTORA_ORIGEN', 
        'TIPO_ORIGEN', 'ID_UNIDAD_PRODUCTORA_DESTINO','TIPO_DESTINO','ESPECIE', 'TOTAL_ANIMALES', "'HEMBRAS MENOR DE 3 MESES'", "'HEMBRAS ENTRE 3 A 8 MESES'", "'HEMBRAS DE 8 A 12 MESES'", "'HEMBRAS 1 A 2 AÑOS'", 
        "'HEMBRAS 2 A 3 AÑOS'", "'HEMBRAS DE 3 A 5 AÑOS'", "'HEMBRAS MAYORES DE 5 AÑOS'", "'MACHOS MENOR DE 3 MESES'", "'MACHOS ENTRE 3 A 8 MESES'", "'MACHOS DE 8 A 12 MESES'", 
        "'MACHOS DE 1 A 2 AÑOS'", "'MACHOS DE 2 A 3 AÑOS'", "'MACHOS MAYORES A 3 AÑOS'", "'HEMBRA BUFALINA MENOR DE 3 ME", "'HEMBRA BUFALINA DE 3 A 8 MESE", 
        "'HEMBRA BUFALINA ENTRE 8 Y 12 ", "'HEMBRA BUFALINA DE 1 A 2 AÑO", "'HEMBRA BUFALINA DE 2 A 3 AÑO", "'HEMBRA BUFALINA DE 3 A 5 AÑO", "'HEMBRA BUFALINA MAYOR DE 5 A", 
        "'MACHOS BUFALINO MENOR DE 3 ME", "'MACHOS BUFALINO DE 3 A 8 MESE", "'MACHOS BUFALINO DE 8 A 12 MES", "'MACHOS BUFALINO DE 1 A 2 AÑO", "'MACHOS BUFALINO DE 2 A 3 AÑO", 
        "'MACHOS BUFALINO MAYORES A 3 A", "'LACTANTES HASTA 30 DIAS'", "'PRECEBO 31 A 60 DIAS'", "'LEVANTE CEBA 61 A 180 DIAS'", "'HEMBRA REEMPLAZO MENOR DE 8 M", 
        "'HEMBRA CRIA MAYOR A 8 MESES'", "'MACHO REPRODUCTOR MAYOR DE 6 "] 

    log_resultados = []

    # Crear carpeta de salida si no existe
    os.makedirs(path_output, exist_ok=True)

    # Listar archivos .txt con año en el nombre (4 dígitos seguidos)
    archivos = [f for f in os.listdir(path_input) if f.endswith('.txt') and re.search(r'\d{4}', f)]

    for archivo in archivos:
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

            # Seleccionar solo las columnas que existen
            columnas_filtradas = [col for col in columnas_requeridas if col in columnas_disponibles]
            df_filtrado = df[columnas_filtradas]

            # Limpiar los datos: convertir a minúsculas, eliminar tildes y reemplazar 'ñ' por 'n'
            def limpiar_texto(texto):
                if isinstance(texto, str):
                    # Convertir a minúsculas
                    texto = texto.lower()
                    # Eliminar tildes y caracteres especiales
                    texto = unidecode.unidecode(texto)
                    # Reemplazar 'ñ' por 'n'
                    texto = texto.replace('ñ', 'n')
                return texto

            # Aplicar la función de limpieza a todo el dataframe
            df_filtrado = df_filtrado.applymap(limpiar_texto)

            # Guardar el dataframe procesado
            output_filename = f"{os.path.splitext(archivo)[0]}_filtrado_limpio.csv"
            output_path = os.path.join(path_output, output_filename)
            df_filtrado.to_csv(output_path, index=False, encoding='utf-8')

        except Exception as e:
            log_resultados.append(f"{archivo} ({anio}): ERROR al procesar -> {e}")

    # Guardar log
    log_path = os.path.join(path_output, "log_columnas.txt")
    with open(log_path, "w", encoding='utf-8') as f:
        for linea in log_resultados:
            f.write(linea + "\n")


get_sigma(
    path_input=r"D:\OneDrive - CGIAR\Desktop\ganabosques\movilizacion\data\brutos\content",
    path_output=r"D:\OneDrive - CGIAR\Desktop\ganabosques\movilizacion\data\tmp_get_sigma"
)