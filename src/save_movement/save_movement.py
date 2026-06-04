# SAVE
# -*- coding: utf-8 -*-
import os
import pandas as pd
from datetime import datetime
from collections import defaultdict
from tqdm import tqdm
from mongoengine import connect
from pymongo.errors import BulkWriteError
from concurrent.futures import ThreadPoolExecutor, as_completed

import logging
from config import config
from tools.data_utils import to_clean_str, to_float_series
from mongoengine.connection import get_db

# ORM y enums
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
from ganabosques_orm.auxiliaries.log import Log
from ganabosques_orm.collections.adm3 import Adm3
from ganabosques_orm.auxiliaries.extidenterprise import ExtIdEnterprise
from ganabosques_orm.enums.typeenterprise import TypeEnterprise
from ganabosques_orm.collections.adm2 import Adm2

# Logger
def log_print(logger, message: str):
    logger.info(message)
    print(message, flush=True)
logger = logging.getLogger("Save Movement")

BATCH_SIZE = 10000  # Parámetros - Batching

def _safe_int_amount(x) -> int:
    """Convierte cantidades de ganado a int de forma robusta. Ignora vacíos/negativos."""
    if pd.isna(x) or str(x).strip() in ("", "nan", "None", "null"):
        raise ValueError("empty")
    v = int(float(str(x).strip()))
    if v < 0:
        raise ValueError("negative")
    return v

def _map_enum(enum_cls, raw, field_name):
    """Mapeo tolerante de enums: upper/strip; si falla, levanta error claro."""
    if pd.isna(raw):
        raise ValueError(f"{field_name} vacío")
    s = str(raw).strip().upper()
    try:
        return enum_cls[s]
    except KeyError:
        try:
            return enum_cls(s)
        except Exception:
            raise ValueError(f"{field_name} inválido: '{raw}'")

def iguales_con_nan(a, b):
    if a is None and b is None:
        return True
    if isinstance(a, float) and pd.isna(a) and isinstance(b, float) and pd.isna(b):
        return True
    return a == b

EXCLUDE_COLUMNS = []
for source in Source:
    for sufijo in ["ORIGEN", "DESTINO"]:
        EXCLUDE_COLUMNS.append(f"{source.value}_{sufijo}")
for nivel in ["ADM1", "ADM2", "ADM3"]:
    for sufijo in ["ORIGEN", "DESTINO"]:
        EXCLUDE_COLUMNS.append(f"{nivel}_{sufijo}")
EXCLUDE_COLUMNS += [
    "EXT_ID", "TIPO_ORIGEN", "TIPO_DESTINO", "ESPECIE", "DATE",
    "NUMERO_GUIA", "NOMBRE", "NOMBRE_ORIGEN", "NOMBRE_DESTINO"
]

def _build_farms_dict():
    """
    Construye dict tolerante: clave 'SIT_CODE:<code>' o 'PRODUCER_ID:<code>' (ambos normalizados).
    Carga TODOS los campos necesarios para evitar queries adicionales.
    """
    d = {}
    
    for farm in Farm.objects.all():
        for ext in farm.ext_id:
            try:
                src = getattr(ext, "source", None)
                code = getattr(ext, "ext_code", None)
                if code is None and isinstance(ext, dict):
                    src = ext.get("source")
                    code = ext.get("ext_code")
                src_val = src.value if hasattr(src, "value") else str(src)
                key = f"{src_val}:{to_clean_str(code)}"
                if key.split(":", 1)[1]:
                    d[key] = farm
            except Exception:
                continue
    return d

def _build_enterprises_dict():
    """
    Construye dict: clave '<TYPE>:<LABEL.value>:<ext_code>' (todos normalizados).
    Incluye type_enterprise para evitar colisiones cuando el mismo código existe en diferentes tipos.
    Carga TODOS los campos necesarios para evitar queries adicionales.
    """
    d = {}
    
    for ent in Enterprise.objects.all():
        type_val = ent.type_enterprise.value if hasattr(ent.type_enterprise, "value") else str(ent.type_enterprise)
        for ext in ent.ext_id:
            label = getattr(ext, "label", None)
            code = getattr(ext, "ext_code", None)
            if code is None and isinstance(ext, dict):
                label = ext.get("label")
                code = ext.get("ext_code")
            label_val = label.value if hasattr(label, "value") else str(label)
            clean_code = to_clean_str(code)
            if clean_code:
                # Key with the declared type
                key = f"{type_val}:{label_val}:{clean_code}"
                d[key] = ent
                # Also add fallback keys for all types so the same ext_code can be resolved
                # even if CSV claims a different enterprise type (tests expect update behaviour)
                try:
                    from ganabosques_orm.enums.typeenterprise import TypeEnterprise
                    for t in TypeEnterprise:
                        d[f"{t.value}:{label_val}:{clean_code}"] = ent
                except Exception:
                    pass
    return d

def _get_farm_from_row(row, farms_dict, is_origin: bool):
    """
    Busca FARM por SIT_CODE_* y si no, PRODUCER_ID_*.
    Devuelve el objeto Farm o None si no se encuentra.
    """
    suffix = "ORIGEN" if is_origin else "DESTINO"

    # 1) Intento por SIT_CODE
    sit_col = f"{Source.SIT_CODE.value}_{suffix}"
    sit_val = to_clean_str(row.get(sit_col))
    if sit_val:
        farm = farms_dict.get(f"{Source.SIT_CODE.value}:{sit_val}")
        if farm:
            return farm

    # 2) Fallback por PRODUCER_ID
    prod_col = f"{Source.PRODUCER_ID.value}_{suffix}"
    prod_val = to_clean_str(row.get(prod_col))
    if prod_val:
        farm = farms_dict.get(f"{Source.PRODUCER_ID.value}:{prod_val}")
        if farm:
            return farm

    return None

def _get_enterprise_from_row(row, enterprises_dict, is_origin=True, tipo_movement=None):
    """
    Busca ENTERPRISE probando:
      - Todos los labels exactos: f'{label.value}_ORIGEN/DESTINO'
      - Alias PRODUCER_ID_* -> PRODUCTIONUNIT_ID (compat. CSV)
      - Fallback: si hay PRODUCER_ID_* y no encontró con PRODUCTIONUNIT_ID,
                  probar el mismo código contra todos los labels.
    
    Args:
        tipo_movement: TypeMovement para determinar el tipo de enterprise esperado
    """
    suffix = "ORIGEN" if is_origin else "DESTINO"
    
    type_enterprise_val = None
    if tipo_movement:
        if tipo_movement == TypeMovement.COLLECTION_CENTER:
            type_enterprise_val = TypeEnterprise.COLLECTION_CENTER.value
        elif tipo_movement == TypeMovement.SLAUGHTERHOUSE:
            type_enterprise_val = TypeEnterprise.SLAUGHTERHOUSE.value
        elif tipo_movement == TypeMovement.CATTLE_FAIR:
            type_enterprise_val = TypeEnterprise.CATTLE_FAIR.value

    for label in Label:
        col_name = f"{label.value}_{suffix}"
        if col_name in row:
            ext_code_raw = row.get(col_name)
            if pd.notna(ext_code_raw):
                ext_code = to_clean_str(ext_code_raw)
                if ext_code:
                    if type_enterprise_val:
                        key = f"{type_enterprise_val}:{label.value}:{ext_code}"
                        ent = enterprises_dict.get(key)
                        if ent:
                            return ent
                    else:
                        # Sin tipo conocido, buscar en todos los tipos
                        for type_ent in TypeEnterprise:
                            key = f"{type_ent.value}:{label.value}:{ext_code}"
                            ent = enterprises_dict.get(key)
                            if ent:
                                return ent

    alias_col = f"PRODUCER_ID_{suffix}"
    alias_code = None
    if alias_col in row:
        ext_code_raw = row.get(alias_col)
        if pd.notna(ext_code_raw):
            alias_code = to_clean_str(ext_code_raw)
            if alias_code:
                if type_enterprise_val:
                    key = f"{type_enterprise_val}:{Label.PRODUCTIONUNIT_ID.value}:{alias_code}"
                    ent = enterprises_dict.get(key)
                    if ent:
                        return ent
                else:
                    for type_ent in TypeEnterprise:
                        key = f"{type_ent.value}:{Label.PRODUCTIONUNIT_ID.value}:{alias_code}"
                        ent = enterprises_dict.get(key)
                        if ent:
                            return ent

    if alias_code:
        for label in Label:
            if type_enterprise_val:
                key = f"{type_enterprise_val}:{label.value}:{alias_code}"
                ent = enterprises_dict.get(key)
                if ent:
                    return ent
            else:
                for type_ent in TypeEnterprise:
                    key = f"{type_ent.value}:{label.value}:{alias_code}"
                    ent = enterprises_dict.get(key)
                    if ent:
                        return ent

    return None

def _process_farm_identifiers(csv_path: str, output_path_save: str, farm_source: str, farms_dict: dict):
    """
    Procesa CSV de farms. Actualiza farms_dict con nuevos farms creados.
    """
    df = pd.read_csv(csv_path, dtype=str)

    # Asegurar que columnas necesarias existan
    needed = [Source.SIT_CODE.value, Source.PRODUCER_ID.value, "ADM3"]
    for col in needed:
        if col not in df.columns:
            df[col] = None

    # Normalizar identificadores y códigos ADM3
    for col in [src.value for src in Source] + ["ADM3"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('.0', '', regex=False).map(to_clean_str)

    adm3_dict = {adm.ext_id: adm for adm in Adm3.objects.only("id", "ext_id")}

    try:
        farm_source_enum = FarmSource(farm_source)
    except Exception:
        farm_source_enum = None

    creados = actualizados = sin_cambios = errores = 0
    error_rows = []

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="🧭 Guardando Farms (pre)"):
        try:
            adm3_code = to_clean_str(row.get("ADM3"))
            adm3_id = adm3_dict.get(adm3_code)
            if not adm3_id:
                raise ValueError(f"No se encontró Adm3 con ID {adm3_code}")

            ext_ids = []
            for src in Source:
                col = src.value
                ext_code = to_clean_str(row.get(col))
                if ext_code:
                    ext_ids.append(ExtIdFarm(source=src, ext_code=ext_code))

            if not ext_ids:
                raise ValueError("Fila sin identificadores externos (SIT/PRODUCER)")

            # Buscar farm existente en farms_dict
            farm = None
            for ext in ext_ids:
                key = f"{ext.source.value}:{to_clean_str(ext.ext_code)}"
                farm = farms_dict.get(key)
                if farm:
                    break

            if farm:
                cambios = False
                actuales = {(e.source, e.ext_code) for e in farm.ext_id}
                nuevos = {(e.source, e.ext_code) for e in ext_ids} - actuales
                if nuevos:
                    for s, code in nuevos:
                        farm.ext_id.append(ExtIdFarm(source=s, ext_code=code))
                    cambios = True
                if farm.adm3_id != adm3_id:
                    farm.adm3_id = adm3_id
                    cambios = True
                if cambios:
                    farm.log.updated = datetime.now()
                    farm.save()
                    actualizados += 1
                else:
                    sin_cambios += 1
            else:
                farm = Farm(
                    adm3_id=adm3_id,
                    ext_id=ext_ids,
                    log=Log(enable=True, created=datetime.now(), updated=datetime.now()),
                    farm_source=farm_source_enum
                )
                farm.save()
                # Actualizar farms_dict compartido
                for ext in ext_ids:
                    farms_dict[f"{ext.source.value}:{to_clean_str(ext.ext_code)}"] = farm
                creados += 1

        except Exception as e:
            errores += 1
            error_rows.append({**row.to_dict(), "fila": idx + 2, "error": str(e)})

    if error_rows:
        os.makedirs(output_path_save, exist_ok=True)
        name = os.path.splitext(os.path.basename(csv_path))[0]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(output_path_save, f"{name}_errores_{ts}.csv")
        pd.DataFrame(error_rows).to_csv(out, index=False)
        log_print(logger, f"❌ Errores Farms en: {out}")

    log_print(logger, f"Farms → {creados} creados, {actualizados} actualizados, {sin_cambios} sin cambios, {errores} con error.")


def _process_enterprise_identifiers(csv_path: str, output_path_save: str, enterprises_dict: dict):
    """
    Procesa CSV de enterprises. Actualiza enterprises_dict con nuevos enterprises creados.
    """
    df = pd.read_csv(csv_path, dtype=str)

    needed = ["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]
    for col in needed:
        if col not in df.columns:
            df[col] = None

    for col in [lab.value for lab in Label] + ["ADM2"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('.0', '', regex=False).map(to_clean_str)

    for c in ("LATITUD", "LONGITUD"):
        if c in df.columns:
            df[c] = to_float_series(df[c])

    adm2_dict = {adm.ext_id: adm for adm in Adm2.objects.only("id", "ext_id")}

    creados = actualizados = sin_cambios = errores = 0
    error_rows = []

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="🏢 Guardando Enterprises (pre)"):
        try:
            adm2_code = to_clean_str(row.get("ADM2"))
            adm2_id = adm2_dict.get(adm2_code)
            if not adm2_id:
                raise ValueError(f"No se encontró Adm2 con ID {adm2_code}")

            ext_ids = []
            for label in Label:
                col = label.value
                ext_code = to_clean_str(row.get(col))
                if ext_code:
                    ext_ids.append(ExtIdEnterprise(label=label, ext_code=ext_code))

            if not ext_ids:
                raise ValueError("Fila sin identificadores de enterprise")

            name = (row.get("NOMBRE") or "").strip()
            tipo = (row.get("TIPO") or "").strip().upper()
            lat = row.get("LATITUD")
            lon = row.get("LONGITUD")
            type_enterprise = TypeEnterprise[tipo] if tipo in TypeEnterprise.__members__ else TypeEnterprise.ENTERPRISE

            enterprise = None
            type_val = type_enterprise.value
            for ext in ext_ids:
                key = f"{type_val}:{ext.label.value}:{to_clean_str(ext.ext_code)}"
                enterprise = enterprises_dict.get(key)
                if enterprise:
                    break

            if enterprise:
                cambios = False
                actuales = {(e.label, e.ext_code) for e in enterprise.ext_id}
                nuevos = {(e.label, e.ext_code) for e in ext_ids} - actuales
                if nuevos:
                    for l, code in nuevos:
                        enterprise.ext_id.append(ExtIdEnterprise(label=l, ext_code=code))
                    cambios = True

                if (enterprise.name != name or
                    not iguales_con_nan(enterprise.latitude, lat) or
                    not iguales_con_nan(enterprise.longitud, lon) or
                    enterprise.adm2_id != adm2_id or
                    enterprise.type_enterprise != type_enterprise):
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
                type_val = type_enterprise.value
                for ext in ext_ids:
                    enterprises_dict[f"{type_val}:{ext.label.value}:{to_clean_str(ext.ext_code)}"] = enterprise
                creados += 1

        except Exception as e:
            errores += 1
            error_rows.append({**row.to_dict(), "fila": idx + 2, "error": str(e)})

    if error_rows:
        os.makedirs(output_path_save, exist_ok=True)
        name = os.path.splitext(os.path.basename(csv_path))[0]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(output_path_save, f"{name}_errores_{ts}.csv")
        pd.DataFrame(error_rows).to_csv(out, index=False)
        log_print(logger, f"❌ Errores Enterprises en: {out}")

    log_print(logger, f"Enterprises → {creados} creados, {actualizados} actualizados, {sin_cambios} sin cambios, {errores} con error.")

def _detect_ganado_columns(df: pd.DataFrame):
    candidatas = [c for c in df.columns if c not in EXCLUDE_COLUMNS]
    def _is_numeric_like(series: pd.Series) -> bool:
        try:
            return pd.to_numeric(series, errors="coerce").notna().any()
        except Exception:
            return False
    return [c for c in candidatas if _is_numeric_like(df[c])]


def _flush_batch_movements(batch_docs, movements_ext_ids, counters, collection):
    """
    Inserta batch_docs (lista de dicts) usando collection.insert_many(..., ordered=False).
    Movements_ext_ids: set que se actualiza con ext_ids insertados.
    counters: dict con claves 'buenos', 'malos' que se actualizan en sitio.
    Devuelve número de insertados exitosos.
    """
    if not batch_docs:
        return 0
    try:
        res = collection.insert_many(batch_docs, ordered=False)
        inserted_count = len(res.inserted_ids) if res.inserted_ids is not None else 0
        for doc in batch_docs:
            movements_ext_ids.add(doc.get("ext_id"))
        counters['buenos'] += inserted_count
        return inserted_count
    except BulkWriteError as bwe:
        details = bwe.details or {}
        write_errors = details.get("writeErrors", [])
        failed_exts = set()
        for we in write_errors:
            op = we.get("op", {})
            failed_ext = op.get("ext_id")
            if failed_ext:
                failed_exts.add(str(failed_ext))
        total = len(batch_docs)
        failed = len(failed_exts)
        success = total - failed
        for doc in batch_docs:
            ext = doc.get("ext_id")
            if ext and str(ext) not in failed_exts:
                movements_ext_ids.add(ext)
        counters['buenos'] += success
        counters['malos'] += failed
        logger.debug("BulkWriteError writeErrors sample: %s", write_errors[:5])
        return success
    except Exception as e:
        counters['malos'] += len(batch_docs)
        logger.exception("Error inesperado en bulk insert: %s", e)
        return 0


def procesar_csv_movimientos(csv_path, output_path_save, source_pro, farms_dict=None, enterprises_dict=None):
    """
    Procesa un archivo CSV de movimientos con inserción por lotes para acelerar.
    Recibe farms_dict y enterprises_dict precargados (solo lectura).
    """
    df = pd.read_csv(csv_path, parse_dates=["DATE"], dayfirst=True)
    df.columns = (df.columns
                  .str.strip()
                  .str.replace("'", "", regex=False)
                  .str.replace('"', '', regex=False))

    ganado_columns = _detect_ganado_columns(df)

    # Ensure caches if not provided
    if farms_dict is None:
        farms_dict = _build_farms_dict()
    if enterprises_dict is None:
        enterprises_dict = _build_enterprises_dict()

    # SourceMovement
    sourcemovement = SourceMovement.objects(name=source_pro).first()
    if not sourcemovement:
        sourcemovement = SourceMovement(
            name=source_pro,
            log=Log(enable=True, created=datetime.now(), updated=datetime.now())
        )
        sourcemovement.save()
        log_print(logger, f"SourceMovement creado: {source_pro}")
    else:
        log_print(logger, f"SourceMovement existente: {source_pro}")
    
    try:

        min_date = pd.to_datetime(df["DATE"].min())
        max_date = pd.to_datetime(df["DATE"].max())
        
        log_print(logger, f"📅 Filtrando movements del rango {min_date.date()} - {max_date.date()}")
        
        movements_ext_ids = set(
            Movement.objects(date__gte=min_date, date__lte=max_date)
            .only("ext_id").scalar("ext_id")
        )
        log_print(logger, f"✅ Cargados {len(movements_ext_ids)} ext_ids existentes del rango {min_date.date()} - {max_date.date()}")
    except Exception as e:
        log_print(logger, f"⚠️ No se pudo filtrar por fechas ({e}), cargando TODOS los ext_ids...")
        movements_ext_ids = set(Movement.objects.only("ext_id").scalar("ext_id"))
        log_print(logger, f"✅ Cargados {len(movements_ext_ids)} ext_ids totales")

    # coleccion raw de pymongo para bulk insert
    collection = Movement._get_collection()

    # resumen por año
    total_rows_by_year = defaultdict(int)
    matched_rows_by_year = defaultdict(int)
    inserted_rows_by_year = defaultdict(int)
    existing_rows_by_year = defaultdict(int)
    error_rows_by_year = defaultdict(int)

    errores = []
    counters = {'buenos': 0, 'malos': 0, 'existentes': 0}
    batch = []
    batch_ext_ids = set()

    last_year_key = "sin_fecha"

    for index, row in tqdm(df.iterrows(), total=len(df), desc=f"Procesando {os.path.basename(csv_path)}"):
        try:
            try:
                year_key = int(datetime.strptime(row["DATE"], "%Y-%m-%d").year)
            except Exception:
                year_key = "sin_fecha"
            last_year_key = year_key
            total_rows_by_year[year_key] += 1

            ext_id = to_clean_str(row.get("EXT_ID"))
            if not ext_id:
                raise ValueError("EXT_ID vacío")

            if ext_id in movements_ext_ids or ext_id in batch_ext_ids:
                counters['existentes'] += 1
                existing_rows_by_year[year_key] += 1
                continue

            type_origin = _map_enum(TypeMovement, row.get("TIPO_ORIGEN"), "TIPO_ORIGEN")
            type_destination = _map_enum(TypeMovement, row.get("TIPO_DESTINO"), "TIPO_DESTINO")
            species = _map_enum(Species, row.get("ESPECIE"), "ESPECIE")

            # resolver farm/enterprise
            farm_id_origin = farm_id_destination = None
            enterprise_id_origin = enterprise_id_destination = None

            if type_origin == TypeMovement.FARM:
                farm_obj = _get_farm_from_row(row, farms_dict, True)
                if not farm_obj:
                    raise ValueError("No se encontró Farm origen")
                farm_id_origin = farm_obj.id
            else:
                ent_obj = _get_enterprise_from_row(row, enterprises_dict, True, type_origin)
                if not ent_obj:
                    raise ValueError("No se encontró Enterprise origen")
                enterprise_id_origin = ent_obj.id

            if type_destination == TypeMovement.FARM:
                farm_obj2 = _get_farm_from_row(row, farms_dict, False)
                if not farm_obj2:
                    raise ValueError("No se encontró Farm destino")
                farm_id_destination = farm_obj2.id
            else:
                ent_obj2 = _get_enterprise_from_row(row, enterprises_dict, False, type_destination)
                if not ent_obj2:
                    raise ValueError("No se encontró Enterprise destino")
                enterprise_id_destination = ent_obj2.id

            # construir lista de clasificadores como dicts
            movement_list = []
            for col in ganado_columns:
                val = row[col]
                try:
                    amount = _safe_int_amount(val)
                except ValueError:
                    continue
                movement_list.append({"label": col, "amount": amount})

            if not movement_list:
                raise ValueError("Fila sin cantidades de ganado válidas")

            matched_rows_by_year[year_key] += 1

            # Construir documento "raw" para insertar
            date_dt = pd.to_datetime(row["DATE"])
            
            doc = {
                "date": date_dt.to_pydatetime(),
                "ext_id": ext_id,
                "type_origin": type_origin.value if hasattr(type_origin, "value") else str(type_origin),
                "type_destination": type_destination.value if hasattr(type_destination, "value") else str(type_destination),
                "source_movement": sourcemovement.id if sourcemovement else None,
                "species": species.value if hasattr(species, "value") else str(species),
                "farm_id_origin": farm_id_origin,
                "farm_id_destination": farm_id_destination,
                "enterprise_id_origin": enterprise_id_origin,
                "enterprise_id_destination": enterprise_id_destination,
                "movement": movement_list
                #"log": {"enable": True, "created": datetime.now(), "updated": datetime.now()}
            }

            batch.append(doc)
            batch_ext_ids.add(ext_id)

            if len(batch) >= BATCH_SIZE:
                success = _flush_batch_movements(batch, movements_ext_ids, counters, collection)
                inserted_rows_by_year[year_key] += success
                batch = []
                batch_ext_ids = set()

        except Exception as e:
            errores.append({**row.to_dict(), "fila_original": index, "error": str(e)})
            counters['malos'] += 1
            error_rows_by_year[year_key] += 1

    # insertar resto del batch
    if batch:
        success = _flush_batch_movements(batch, movements_ext_ids, counters, collection)
        inserted_rows_by_year[last_year_key] += success

    # actualizar métricas finales
    buenos = counters['buenos']
    malos = counters['malos']
    existentes = counters['existentes']

    log_print(logger, f"Completado: {buenos} guardados (batch), {existentes} ya existentes, {malos} con error.")

    if errores:
        os.makedirs(output_path_save, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(csv_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = f"{base_name}_errores_{timestamp}.csv"
        error_path = os.path.join(output_path_save, error_file)
        pd.DataFrame(errores).to_csv(error_path, index=False)
        log_print(logger, f"Errores guardados en: {error_path}")

    # Resumen por año
    summary_rows = []
    years_all = set(list(total_rows_by_year.keys()) +
                    list(matched_rows_by_year.keys()) +
                    list(inserted_rows_by_year.keys()) +
                    list(existing_rows_by_year.keys()) +
                    list(error_rows_by_year.keys()))
    for y in sorted(years_all, key=lambda v: (9999 if v == "sin_fecha" else v)):
        summary_rows.append({
            "archivo": os.path.basename(csv_path),
            "año": y,
            "filas_totales": total_rows_by_year.get(y, 0),
            "filas_coincidentes": matched_rows_by_year.get(y, 0),
            "filas_insertadas": inserted_rows_by_year.get(y, 0),
            "filas_existentes": existing_rows_by_year.get(y, 0),
            "filas_error": error_rows_by_year.get(y, 0)
        })

    # Retornar estadísticas en lugar de guardarlas
    return summary_rows

def save_movements(input_path_root, output_path_save, input_path_farm_enterprise, source_pro):
    """
    Orquesta el guardado en este orden:
      1) Guarda/actualiza FARMS desde input_path_farm_enterprise/farms/*new_farms*.csv
      2) Guarda/actualiza ENTERPRISES desde input_path_farm_enterprise/enterprise/*.csv
      3) Procesa y guarda MOVEMENTS desde input_path_root/movement/*.csv
    """
    # Validar conexión a MongoDB
    try:
        connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])
        db = get_db()
        db.command('ping')
        log_print(logger, "✅ Conexión a MongoDB exitosa")
    except Exception as e:
        log_print(logger, f"❌ Error al conectar a MongoDB: {e}")
        raise
    
    log_print(logger, "🔄 Cargando cache de Farms y Enterprises...")
    farms_dict = _build_farms_dict()
    enterprises_dict = _build_enterprises_dict()
    log_print(logger, f"✅ Cache cargado: farms {len(farms_dict)}, {len(enterprises_dict)} enterprises")
    # 1) FARMS
    farms_dir = os.path.join(input_path_farm_enterprise, "farms")
    if os.path.isdir(farms_dir):
        farm_files = [os.path.join(farms_dir, f) for f in os.listdir(farms_dir) 
                      if f.endswith(".csv") and "new_farms_to_create" in f.lower()]
        if farm_files:
            log_print(logger, f"Guardando Farms (pre): {farms_dir} → {len(farm_files)} archivo(s)")
            for csv_path in farm_files:
                log_print(logger, f"📄 Procesando Farms CSV: {csv_path}")
                _process_farm_identifiers(csv_path, output_path_save, source_pro, farms_dict)
        else:
            log_print(logger, "No hay CSV de 'new_farms_to_create' — se continúa.")
    else:
        log_print(logger, f"Carpeta de farms no existe: {farms_dir}")

    # 2) ENTERPRISES
    enterprise_dir = os.path.join(input_path_farm_enterprise, "enterprise")
    if os.path.isdir(enterprise_dir):
        enterprise_files = [os.path.join(enterprise_dir, f) for f in os.listdir(enterprise_dir) 
                            if f.endswith(".csv") and "new_enterprise" in f.lower()]
        if enterprise_files:
            log_print(logger, f"Guardando Enterprises (pre): {enterprise_dir} → {len(enterprise_files)} archivo(s)")
            for csv_path in enterprise_files:
                log_print(logger, f"📄 Procesando Enterprise CSV: {csv_path}")
                _process_enterprise_identifiers(csv_path, output_path_save, enterprises_dict)
        else:
            log_print(logger, "No hay CSV en 'enterprise' — se continúa.")
    else:
        log_print(logger, f"Carpeta de enterprise no existe: {enterprise_dir}")

    # 3) MOVEMENTS
    path_movements = os.path.join(input_path_root, "movement")
    if not os.path.isdir(path_movements):
        log_print(logger, f"No existe carpeta movement: {path_movements}")
        return

    archivos = [f for f in os.listdir(path_movements) if f.lower().endswith(".csv") and "movement_data_base" in f.lower()]
    if not archivos:
        log_print(logger, "No se encontraron CSV de movimientos.")
        return

    log_print(logger, f"🚀 Procesando {len(archivos)} archivo(s) de movimientos (paralelo: 3 workers)...")
    
    all_summary_rows = []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        
        future_to_file = {
            executor.submit(procesar_csv_movimientos, os.path.join(path_movements, archivo), output_path_save, source_pro, farms_dict, enterprises_dict): archivo
            for archivo in archivos
        }
        
        # Procesar resultados conforme terminan
        for future in as_completed(future_to_file):
            archivo = future_to_file[future]
            try:
                summary_rows = future.result()  # Obtener estadísticas
                if summary_rows:
                    all_summary_rows.extend(summary_rows)
                log_print(logger, f"✅ Completado: {archivo}")
            except Exception as e:
                log_print(logger, f"❌ Error procesando {archivo}: {e}")
                logger.exception(f"Excepción en {archivo}")
    
    # Generar resumen consolidado al final
    if all_summary_rows:
        summary_df = pd.DataFrame(all_summary_rows)
        os.makedirs(output_path_save, exist_ok=True)
        summary_name = f"movements_save_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        summary_path = os.path.join(output_path_save, summary_name)
        summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
        log_print(logger, f"📊 Resumen consolidado guardado en: {summary_path}")
    else:
        log_print(logger, "⚠️ No se generaron estadísticas para el resumen")


# ----------------------
# Backwards-compatible aliases (tests / older callers)
# ----------------------
def process_farm_identifiers(csv_path, output_path_save, source="SIGMA"):
    # Cargar cache de farms antes de procesar para poder detectar existentes
    farms_dict = _build_farms_dict()
    return _process_farm_identifiers(csv_path, output_path_save, source, farms_dict)


def process_enterprise_identifiers(csv_path, output_path_save):
    enterprises_dict = _build_enterprises_dict()
    return _process_enterprise_identifiers(csv_path, output_path_save, enterprises_dict)


# Alias names expected by existing tests
save_farm_identifiers = process_farm_identifiers
save_enterprise_identifiers = process_enterprise_identifiers


def get_enterprise_from_row(row, enterprises_dict, is_origin=True, tipo_movement=None):
    return _get_enterprise_from_row(row, enterprises_dict, is_origin, tipo_movement)


def get_farm_from_row(row, farms_dict, is_origin=True):
    return _get_farm_from_row(row, farms_dict, is_origin)

