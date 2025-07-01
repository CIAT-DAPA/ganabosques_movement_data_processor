from mongoengine import connect
import os
from tqdm import tqdm
from datetime import datetime

from tools.log_print import log_print
import logging
from config import config

import pandas as pd
from ganabosques_orm.collections.movement import Movement
from ganabosques_orm.auxiliaries.classification import Classification
from ganabosques_orm.collections.sourcemovement import SourceMovement
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.enums.species import Species
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.label import Label
from ganabosques_orm.collections.farm import Farm
from ganabosques_orm.collections.enterprise import Enterprise
from ganabosques_orm.auxiliaries.extidfarm import ExtIdFarm
from ganabosques_orm.enums.farmsource import FarmSource
from ganabosques_orm.auxiliaries.extidenterprise import ExtIdEnterprise
from ganabosques_orm.enums.typeenterprise import TypeEnterprise
from ganabosques_orm.auxiliaries.log import Log
from ganabosques_orm.collections.adm3 import Adm3
from ganabosques_orm.collections.adm2 import Adm2


# Configuración del logger de este script
logger = logging.getLogger("Save Movement")

# Columnas que no son tipos de ganado

EXCLUDE_COLUMNS = []

# 1. Campos compuestos con source
for source in Source:
    for sufijo in ["ORIGEN", "DESTINO"]:
        EXCLUDE_COLUMNS.append(f"{source.value}_{sufijo}")

# 2. Campos administrativos
for nivel in ["ADM1", "ADM2", "ADM3"]:
    for sufijo in ["ORIGEN", "DESTINO"]:
        EXCLUDE_COLUMNS.append(f"{nivel}_{sufijo}")

# 3. Otros campos fijos
EXCLUDE_COLUMNS += ["EXT_ID", "TIPO_ORIGEN", "TIPO_DESTINO", "ESPECIE", "DATE"]

def save_movements(input_path_root, output_path_save, input_path_farm_enterprise, source_pro ):
    """
    Carga y guarda los movimientos de ganado, predios y empresas a partir de archivos CSV.
    
    Entradas:
        input_path_root (str): Ruta al directorio raíz donde están los archivos de movimiento.
        output_path_save (str): Ruta donde se guardarán los archivos de error si los hay.
        input_path_farm_enterprise (str): Ruta a las carpetas con archivos CSV de predios y empresas.

    Salida:
        None
    """
    # Conexión a MongoDB (ajusta los valores a tu entorno)
    connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])
    path_farm = os.path.join(input_path_farm_enterprise, "farms")
    path_enterprise = os.path.join(input_path_farm_enterprise, "enterprise")
    # Procesar farms
    path_farm = os.path.join(input_path_farm_enterprise, "farms")
    if os.path.exists(path_farm):
        archivos_farm = [f for f in os.listdir(path_farm) if f.endswith(".csv") and "new_farms" in f]
        if archivos_farm:
            log_print(logger, f"Guardando farms desde archivos CSV...")
            save_farm_identifiers(path_farm, output_path_save, source_pro)
        else:
            log_print(logger, f"Carpeta de farms vacía, se omite procesamiento.")
    else:
        log_print(logger, f"Carpeta de farms no existe, se omite procesamiento.")

    # Procesar enterprises
    path_enterprise = os.path.join(input_path_farm_enterprise, "enterprise")
    if os.path.exists(path_enterprise):
        archivos_enterprise = [f for f in os.listdir(path_enterprise) if f.endswith(".csv")]
        if archivos_enterprise:
            log_print(logger, f"Guardando enterprise desde archivos CSV...")
            save_enterprise_identifiers(path_enterprise, output_path_save)
        else:
            log_print(logger, f"Carpeta de enterprise vacía, se omite procesamiento.")
    else:
        log_print(logger, f"Carpeta de enterprise no existe, se omite procesamiento.")

    path_movements = os.path.join(input_path_root, "movement")
    archivos = [f for f in os.listdir(path_movements) if f.endswith(".csv")]
    for archivo in archivos:
        ruta_completa = os.path.join(path_movements, archivo)
        log_print(logger, f"Procesando archivo: {archivo}")
        procesar_csv_movimientos(ruta_completa, output_path_save, source_pro)

def procesar_csv_movimientos(csv_path, output_path_save, source_pro):
    """
    Procesa un archivo CSV de movimientos y los guarda en la base de datos si son válidos.

    Entradas:
        csv_path (str): Ruta al archivo CSV.
        output_path_save (str): Ruta donde se guardarán los errores si ocurren.

    Salida:
        None
    """
    # Ruta del CSV
    df = pd.read_csv(csv_path, parse_dates=["DATE"], dayfirst=True)

    # Limpieza de nombres de columnas
    df.columns = df.columns.str.strip().str.replace("'", "").str.replace('"', '')

    # Columnas excluidas para detectar tipos de ganado
    ganado_columns = [col for col in df.columns if col not in EXCLUDE_COLUMNS]

    errores = []
    buenos, malos, existentes  = 0, 0, 0
    
    # cargar sourcemovement
    
    # Buscar o crear el SourceMovement correspondiente
    sourcemovement = SourceMovement.objects(name=source_pro).first()

    if not sourcemovement:
        sourcemovement = SourceMovement(name=source_pro, 
                    log=Log(enable=True, created=datetime.now(), updated=datetime.now()))
        sourcemovement.save()
        log_print(logger, f"SourceMovement creado: {source_pro}")
    else:
        log_print(logger, f"SourceMovement existente encontrado: {source_pro}")

    # Precargar Farms
    farms_dict = {}
    for farm in Farm.objects.only("id", "ext_id"):
        for ext in farm.ext_id:
            clave = f"{ext.source.value}:{ext.ext_code}"
            farms_dict[clave] = farm

    # Precargar Enterprises
    enterprises_dict = {}
    for ent in Enterprise.objects.only("id", "ext_id"):
        for ext in ent.ext_id:
            key = f"{ext.label.value}:{ext.ext_code}"
            enterprises_dict[key] = ent

    # Precargar Movements
    movements_ext_ids = set(Movement.objects.only("ext_id").scalar("ext_id"))
    
    # Procesar cada fila
    for index, row in tqdm(df.iterrows(), total=len(df), desc=f"Procesando {os.path.basename(csv_path)}"):
        try:

            ext_id = row["EXT_ID"]
            if ext_id in movements_ext_ids:
                existentes  += 1
                continue

            # Tipo origen y destino como enums
            type_origin = TypeMovement[row["TIPO_ORIGEN"]]
            type_destination = TypeMovement[row["TIPO_DESTINO"]]

            farm_id_origin, farm_id_destination = None, None
            enterprise_id_origin, enterprise_id_destination = None, None

             # Buscar origen
            if type_origin == TypeMovement.FARM:
                farm_id_origin = get_farm_from_row(row, farms_dict, is_origin=True)
                if not farm_id_origin:
                    raise ValueError("No se encontró Farm origen")
            else:
                enterprise_id_origin = get_enterprise_from_row(row, enterprises_dict, is_origin=True)
                if not enterprise_id_origin:
                    raise ValueError("No se encontró Enterprise origen")

            # Buscar destino
            if type_destination == TypeMovement.FARM:
                farm_id_destination = get_farm_from_row(row, farms_dict, is_origin=False)
                if not farm_id_destination:
                    raise ValueError("No se encontró Farm destino")
            else:
                enterprise_id_destination = get_enterprise_from_row(row, enterprises_dict, is_origin=False)
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
                ext_id=row["EXT_ID"],
                type_origin=type_origin,
                type_destination=type_destination,
                source_movement=sourcemovement,
                species=Species(row["ESPECIE"]),
                farm_id_origin=farm_id_origin,
                farm_id_destination=farm_id_destination,
                enterprise_id_origin=enterprise_id_origin,
                enterprise_id_destination=enterprise_id_destination,
                movement=movement_list
            )

            movimiento.save()
            #print(f"[OK] Movimiento guardado para guía {row['NUMERO_GUIA']}")
            buenos += 1

        except Exception as e:
            error_msg = str(e)
            errores.append({**row.to_dict(), "fila_original": index, "error": error_msg})
            malos += 1

    log_print(logger, f"Completado: {buenos} guardados, {existentes} sin cambios, {malos} con error.")

    if errores:
        os.makedirs(output_path_save, exist_ok=True)
        
        base_name = os.path.splitext(os.path.basename(csv_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{base_name}_{timestamp}.csv"
        print(f"Guardando errores en {file_name}")
        error_file_path = os.path.join(output_path_save, file_name)
        pd.DataFrame(errores).to_csv(error_file_path, index=False)
        log_print(logger, f"Errores guardados en: {error_file_path}")

def get_farm_from_row(row, farms_dict, is_origin=True):
    """
    Retorna el objeto Farm correspondiente a un origen o destino dado.

    Entradas:
        row (pd.Series): Fila del CSV.
        farms_dict (dict): Diccionario precargado de predios con claves en formato "source:ext_code".
        is_origin (bool): Indica si se está buscando el origen o el destino.

    Salida:
        Farm o None
    """
    suffix = "ORIGEN" if is_origin else "DESTINO"
    for source in Source:
        col_name = f"{source.value}_{suffix}"
        ext_code = row.get(col_name)
        if pd.notna(ext_code):
            farm = farms_dict.get(f"{source.value}:{ext_code}")
            if farm:
                return farm
    return None

def get_enterprise_from_row(row, enterprises_dict, is_origin=True):
    """
    Retorna el objeto Enterprise correspondiente a un origen o destino dado.

    Entradas:
        row (pd.Series): Fila del CSV.
        enterprises_dict (dict): Diccionario precargado de empresas con claves en formato "label:ext_code".
        is_origin (bool): Indica si se está buscando el origen o el destino.

    Salida:
        Enterprise o None
    """
    suffix = "ORIGEN" if is_origin else "DESTINO"
    for label in Label:
        # Aqui hay un problema desde antes viene con el PRODUCER_ID en vez del label 
        # col_name = f"{label.value}_{suffix}"
        col_name = f"PRODUCER_ID_{suffix}"
        ext_code = row.get(col_name)
        if pd.notna(ext_code):
            enterprise = enterprises_dict.get(f"{label.value}:{ext_code}")
            if enterprise:
                return enterprise
    return None

def process_farm_identifiers(csv_path, output_path_save, source):
    """
    Procesa un archivo CSV de predios y actualiza o crea las entradas en MongoDB.

    Entradas:
        csv_path (str): Ruta al archivo CSV.
        output_path_save (str): Ruta donde se guardarán los errores.

    Salida:
        None
    """
    df = pd.read_csv(csv_path, dtype=str)

    # Limpiar códigos externos y adm3
    for col in [src.value for src in Source] + ["ADM3"]:
        if col in df.columns:
            df[col] = df[col].str.replace('.0', '', regex=False)

    adm3_dict = {adm.ext_id: adm for adm in Adm3.objects.only("id", "ext_id")}

    farm_index = {}
    for farm in Farm.objects():
        for ext in farm.ext_id:
            farm_index[(ext.source, ext.ext_code)] = farm

    farm_creados, farm_actualizados, farm_sin_cambios, farm_errores = 0, 0, 0, 0
    errores = []
    
    farm_source = FarmSource(source)

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="🧭 Procesando Farms"):
        try:
            adm3_id = adm3_dict.get(row.get("ADM3"))
            if not adm3_id:
                raise ValueError(f"No se encontró Adm3 con ID {row.get('ADM3')}")

            ext_ids = []
            for src in Source:
                col = src.value
                ext_code = row.get(col)
                if ext_code:
                    ext_ids.append(ExtIdFarm(source=src, ext_code=ext_code.strip()))

            farm = None
            for ext in ext_ids:
                farm = farm_index.get((ext.source, ext.ext_code))
                if farm:
                    break

            if farm:
                codigos_actuales = {(e.source, e.ext_code) for e in farm.ext_id}
                nuevos_codigos = {(e.source, e.ext_code) for e in ext_ids}
                nuevos = nuevos_codigos - codigos_actuales

                if nuevos:
                    for s, code in nuevos:
                        farm.ext_id.append(ExtIdFarm(source=s, ext_code=code))
                    farm.log.updated = datetime.now()
                    farm.save()
                    farm_actualizados += 1
                else:
                    farm_sin_cambios += 1
            else:
                farm = Farm(
                    adm3_id=adm3_id,
                    ext_id=ext_ids,
                    log=Log(enable=True, created=datetime.now(), updated=datetime.now()),
                    farm_source = farm_source
                )
                farm.save()
                for ext in ext_ids:
                    farm_index[(ext.source, ext.ext_code)] = farm
                farm_creados += 1

        except Exception as e:
            errores.append({**row.to_dict(), "fila": idx + 2, "error": str(e)})
            farm_errores += 1

    # Guardar errores si los hay
    if errores:
        os.makedirs(output_path_save, exist_ok=True)
        name = os.path.splitext(os.path.basename(csv_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{name}_errores_{timestamp}.csv"
        print(f"Guardando errores en {file_name}")
        error_path = os.path.join(output_path_save, file_name)
        pd.DataFrame(errores).to_csv(error_path, index=False)
        log_print(logger, f"Errores guardados en: {error_path}")

    # Log final
    log_print(logger, f"  Finalizado: {farm_creados} creados, {farm_actualizados} actualizados, {farm_sin_cambios} sin cambios, {farm_errores} con error.")

def save_farm_identifiers(csv_folder_path, output_path_save, farm_source):
    """
    Procesa todos los archivos CSV en una carpeta para registrar predios.

    Entradas:
        csv_folder_path (str): Ruta a la carpeta con archivos CSV.
        output_path_save (str): Ruta donde se guardarán errores si ocurren.

    Salida:
        None
    """
    for file in os.listdir(csv_folder_path):
        if file.endswith(".csv") and "new_farms" in file:
            csv_path = os.path.join(csv_folder_path, file)
            log_print(logger, f"📄 Procesando archivo: {csv_path}")
            process_farm_identifiers(csv_path, output_path_save, farm_source)

def process_enterprise_identifiers(csv_path, output_path_save):
    """
    Procesa un archivo CSV de empresas y actualiza o crea las entradas en MongoDB.

    Entradas:
        csv_path (str): Ruta al archivo CSV.
        output_path_save (str): Ruta donde se guardarán los errores.

    Salida:
        None
    """
    
    df = pd.read_csv(csv_path, dtype=str)

    # Limpiar columnas numéricas
    for col in [src.value for src in Label] + ["ADM2"]:
        if col in df.columns:
            df[col] = df[col].str.replace('.0', '', regex=False)

    # Precargar ADM2
    adm2_dict = {adm.ext_id: adm for adm in Adm2.objects.only("id", "ext_id")}

    # Precargar empresas indexadas por (label, ext_code)
    enterprise_index = {}
    for ent in Enterprise.objects():
        for ext in ent.ext_id:
            key = (ext.label, ext.ext_code)
            enterprise_index[key] = ent

    creados, actualizados, sin_cambios, errores_count = 0, 0, 0, 0
    errores = []

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="🏢 Procesando Enterprises"):
        try:
            adm2_id = adm2_dict.get(row.get("ADM2"))
            if not adm2_id:
                raise ValueError(f"No se encontró Adm2 con ID {row.get('ADM2')}")

            ext_ids = []
            for label in Label:
                col = f"{label.value}"
                ext_code = row.get(col)
                if pd.notna(ext_code) and ext_code.strip():
                    ext_ids.append(ExtIdEnterprise(label=label, ext_code=ext_code.strip()))

            name = row.get("NOMBRE", "").strip()
            tipo = row.get("TIPO", "").strip().upper()
            lat = limpiar_coord(row.get("LATITUD"), "LATITUD")
            lon = limpiar_coord(row.get("LONGITUD"), "LONGITUD")
            type_enterprise = TypeEnterprise[tipo] if tipo in TypeEnterprise.__members__ else TypeEnterprise.ENTERPRISE

            # Buscar empresa existente
            enterprise = None
            for ext in ext_ids:
                enterprise = enterprise_index.get((ext.label, ext.ext_code))
                if enterprise:
                    break

            if enterprise:
                cambios = False

                # Verificar nuevos códigos externos
                codigos_actuales = {(e.label, e.ext_code) for e in enterprise.ext_id}
                nuevos_codigos = {(e.label, e.ext_code) for e in ext_ids}
                nuevos = nuevos_codigos - codigos_actuales

                if nuevos:
                    for l, code in nuevos:
                        enterprise.ext_id.append(ExtIdEnterprise(label=l, ext_code=code))
                    cambios = True

                # Verificar cambios en otros campos
                if enterprise.name != name or not iguales_con_nan(enterprise.latitude, lat) or not iguales_con_nan(enterprise.longitud, lon) or enterprise.adm2_id != adm2_id or enterprise.type_enterprise != type_enterprise:
                    enterprise.name = name
                    enterprise.latitude = lat
                    enterprise.longitud = lon
                    enterprise.adm2_id = adm2_id
                    enterprise.type_enterprise = type_enterprise
                    cambios = True

                if cambios:
                    enterprise.log.updated = datetime.now()
                    enterprise.save()
                    actualizados += 1
                else:
                    sin_cambios += 1

            else:
                enterprise = Enterprise(
                    name=name,
                    latitude=lat,
                    longitud=lon,
                    adm2_id=adm2_id,
                    type_enterprise=type_enterprise,
                    ext_id=ext_ids,
                    log=Log(enable=True, created=datetime.now(), updated=datetime.now())
                )
                enterprise.save()
                for ext in ext_ids:
                    enterprise_index[(ext.label, ext.ext_code)] = enterprise
                creados += 1

        except Exception as e:
            errores.append({**row.to_dict(), "fila": idx + 2, "error": str(e)})
            errores_count += 1

    # Guardar errores
    if errores:
        os.makedirs(output_path_save, exist_ok=True)
        name = os.path.splitext(os.path.basename(csv_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{name}_errores_{timestamp}.csv"
        print(f"Guardando errores en {file_name}")
        error_path = os.path.join(output_path_save, file_name)
        pd.DataFrame(errores).to_csv(error_path, index=False)
        log_print(logger, f"❌ Errores guardados en: {error_path}")

    # Log resumen
    log_print(logger, f"✅ Finalizado: {creados} creados, {actualizados} actualizados, {sin_cambios} sin cambios, {errores_count} con error.")

def save_enterprise_identifiers(csv_folder_path, output_path_save):
    """
    Procesa todos los archivos CSV en una carpeta para registrar empresas.

    Entradas:
        csv_folder_path (str): Ruta a la carpeta con archivos CSV.
        output_path_save (str): Ruta donde se guardarán errores si ocurren.

    Salida:
        None
    """
    
    for file in os.listdir(csv_folder_path):
        if file.endswith(".csv"):
            csv_path = os.path.join(csv_folder_path, file)
            log_print(logger, f"📄 Procesando archivo: {csv_path}")
            process_enterprise_identifiers(csv_path, output_path_save)

def iguales_con_nan(a, b):
    """
    Compara dos valores teniendo en cuenta que ambos pueden ser NaN o None.

    Entradas:
        a (float|None): Primer valor a comparar.
        b (float|None): Segundo valor a comparar.

    Salida:
        bool: True si son iguales (incluyendo NaN/None), False si no.
    """
    if a is None and b is None:
        return True
    if isinstance(a, float) and pd.isna(a) and isinstance(b, float) and pd.isna(b):
        return True
    return a == b

def limpiar_coord(valor, campo="LATITUD/LONGITUD"):
    """
    Limpia y convierte un valor a float si es válido, de lo contrario lanza un error.

    Entradas:
        valor (str|float|None): Valor a convertir.
        campo (str): Nombre del campo para usar en el mensaje de error.

    Salida:
        float o None si está vacío.

    Excepciones:
        ValueError: Si el valor no puede convertirse a float.
    """
    if valor is None:
        return None
    valor = str(valor).strip()
    if valor == "":
        return None
    try:
        return float(valor)
    except ValueError:
        raise ValueError(f"Valor inválido para {campo}: '{valor}'")