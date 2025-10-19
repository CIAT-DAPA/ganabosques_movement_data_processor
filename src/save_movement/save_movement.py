# SAVE
# -*- coding: utf-8 -*-
import os
import pandas as pd
from datetime import datetime
from collections import defaultdict
from tqdm import tqdm
from mongoengine import connect

from tools.log_print import log_print
import logging
from config import config

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

# >>> añadidos para enterprise
from ganabosques_orm.auxiliaries.extidenterprise import ExtIdEnterprise
from ganabosques_orm.enums.typeenterprise import TypeEnterprise
from ganabosques_orm.collections.adm2 import Adm2

# Logger
logger = logging.getLogger("Save Movement")


# ---------------------------
# Utilidades de normalización
# ---------------------------
def _to_clean_str(val) -> str:
    """Normaliza IDs a string comparable (quita espacios, .0, notación científica, NaNs)."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null"):
        return ""
    if s.endswith(".0"):
        try:
            s = str(int(float(s)))
        except Exception:
            pass
    try:
        if "e" in s.lower():
            n = float(s)
            s = str(int(n)) if n.is_integer() else str(n)
    except Exception:
        pass
    return s


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


def _to_float_series(col: pd.Series) -> pd.Series:
    """Convierte una serie a float (acepta coma/punto, miles, vacíos)."""
    s = col.astype(str).str.strip().str.replace("\u00A0", "", regex=False)
    s = s.replace({"": pd.NA, "-": pd.NA, "—": pd.NA, "--": pd.NA,
                   "nan": pd.NA, "NaN": pd.NA, "NONE": pd.NA, "None": pd.NA, "null": pd.NA, "NULL": pd.NA})

    def _norm(x: str) -> str:
        if x is pd.NA or x is None:
            return x
        x = str(x).replace(" ", "").replace("'", "")
        if ("," in x) and ("." not in x):
            x = x.replace(",", ".")
        elif ("," in x) and ("." in x):
            if x.rfind(",") > x.rfind("."):
                x = x.replace(".", "").replace(",", ".")
            else:
                x = x.replace(",", "")
        return x

    return pd.to_numeric(s.map(_norm), errors="coerce")


# --------------------------------
# Columnas a excluir (no ganado)
# --------------------------------
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


# -----------------------------
# Diccionarios precargados
# -----------------------------
def _build_farms_dict():
    """
    Construye dict tolerante: clave 'SIT_CODE:<code>' o 'PRODUCER_ID:<code>' (ambos normalizados).
    Soporta que ext_id venga como objeto o dict; source como enum o string.
    """
    d = {}
    for farm in Farm.objects.only("id", "ext_id"):
        for ext in farm.ext_id:
            try:
                src = getattr(ext, "source", None)
                code = getattr(ext, "ext_code", None)
                if code is None and isinstance(ext, dict):
                    src = ext.get("source")
                    code = ext.get("ext_code")
                src_val = src.value if hasattr(src, "value") else str(src)
                key = f"{src_val}:{_to_clean_str(code)}"
                if key.split(":", 1)[1]:
                    d[key] = farm
            except Exception:
                continue
    return d


def _build_enterprises_dict():
    """
    Construye dict: clave '<LABEL.value>:<ext_code>' (ambos normalizados).
    """
    d = {}
    for ent in Enterprise.objects.only("id", "ext_id"):
        for ext in ent.ext_id:
            label = getattr(ext, "label", None)
            code = getattr(ext, "ext_code", None)
            if code is None and isinstance(ext, dict):
                label = ext.get("label")
                code = ext.get("ext_code")
            label_val = label.value if hasattr(label, "value") else str(label)
            key = f"{label_val}:{_to_clean_str(code)}"
            if key.split(":", 1)[1]:
                d[key] = ent
    return d


# -----------------------------
# Resolución y creación de FARM
# -----------------------------
def _get_adm3_for_side(row, is_origin: bool):
    col = "ADM3_ORIGEN" if is_origin else "ADM3_DESTINO"
    code = _to_clean_str(row.get(col))
    if not code:
        return None
    adm = Adm3.objects(ext_id=code).only("id").first()
    return adm


def _get_or_create_farm_from_row(row, farms_dict, is_origin: bool, farm_source_from_param: str):
    """
    Busca FARM por SIT_CODE_* y si no, PRODUCER_ID_*.
    Si no existe, lo crea usando ADM3_* del mismo lado.
    Devuelve el objeto Farm (o lanza ValueError si no se pudo crear/buscar).
    """
    suffix = "ORIGEN" if is_origin else "DESTINO"

    # 1) Intento por SIT_CODE
    sit_col = f"{Source.SIT_CODE.value}_{suffix}"
    sit_val = _to_clean_str(row.get(sit_col))
    if sit_val:
        farm = farms_dict.get(f"{Source.SIT_CODE.value}:{sit_val}")
        if farm:
            return farm

    # 2) Fallback por PRODUCER_ID
    prod_col = f"{Source.PRODUCER_ID.value}_{suffix}"
    prod_val = _to_clean_str(row.get(prod_col))
    if prod_val:
        farm = farms_dict.get(f"{Source.PRODUCER_ID.value}:{prod_val}")
        if farm:
            return farm

    # 3) Si no existe → crear (requiere ADM3 válido)
    adm3 = _get_adm3_for_side(row, is_origin)
    if adm3 is None:
        raise ValueError(f"No se encontró Adm3 para {'ORIGEN' if is_origin else 'DESTINO'}")

    try:
        farm_source = FarmSource(farm_source_from_param)
    except Exception:
        farm_source = None

    ext_ids = []
    if sit_val:
        ext_ids.append(ExtIdFarm(source=Source.SIT_CODE, ext_code=sit_val))
    if prod_val:
        ext_ids.append(ExtIdFarm(source=Source.PRODUCER_ID, ext_code=prod_val))
    if not ext_ids:
        raise ValueError(f"No hay SIT_CODE/PRODUCER_ID para crear Farm en {'ORIGEN' if is_origin else 'DESTINO'}")

    farm = Farm(
        adm3_id=adm3,
        ext_id=ext_ids,
        log=Log(enable=True, created=datetime.now(), updated=datetime.now()),
        farm_source=farm_source
    )
    farm.save()

    # Actualizar cache en memoria
    for ext in ext_ids:
        farms_dict[f"{ext.source.value}:{_to_clean_str(ext.ext_code)}"] = farm

    return farm


# -----------------------------
# Resolución de ENTERPRISE
# -----------------------------
def _get_enterprise_from_row(row, enterprises_dict, is_origin=True):
    """
    Busca ENTERPRISE probando:
      - Todos los labels exactos: f'{label.value}_ORIGEN/DESTINO'
      - Alias PRODUCER_ID_* -> PRODUCTIONUNIT_ID (compat. CSV)
      - Fallback: si hay PRODUCER_ID_* y no encontró con PRODUCTIONUNIT_ID,
                  probar el mismo código contra todos los labels.
    """
    suffix = "ORIGEN" if is_origin else "DESTINO"

    # 1) Match exacto por todos los labels
    for label in Label:
        col_name = f"{label.value}_{suffix}"
        if col_name in row:
            ext_code_raw = row.get(col_name)
            if pd.notna(ext_code_raw):
                ext_code = _to_clean_str(ext_code_raw)
                if ext_code:
                    key = f"{label.value}:{ext_code}"
                    ent = enterprises_dict.get(key)
                    if ent:
                        return ent

    # 2) Alias: PRODUCER_ID_* -> PRODUCTIONUNIT_ID
    alias_col = f"PRODUCER_ID_{suffix}"
    alias_code = None
    if alias_col in row:
        ext_code_raw = row.get(alias_col)
        if pd.notna(ext_code_raw):
            alias_code = _to_clean_str(ext_code_raw)
            if alias_code:
                key = f"{Label.PRODUCTIONUNIT_ID.value}:{alias_code}"
                ent = enterprises_dict.get(key)
                if ent:
                    return ent

    # 3) Fallback adicional: probar PRODUCER_ID_* contra TODOS los labels
    if alias_code:
        for label in Label:
            key = f"{label.value}:{alias_code}"
            ent = enterprises_dict.get(key)
            if ent:
                return ent

    return None


# ------------------------------------------
# Guardar/actualizar: FARMS (new_farms*.csv)
# ------------------------------------------
def _process_farm_identifiers(csv_path: str, output_path_save: str, farm_source: str):
    df = pd.read_csv(csv_path, dtype=str)

    needed = [Source.SIT_CODE.value, Source.PRODUCER_ID.value, "ADM3", "TIPO"]
    for col in needed:
        if col not in df.columns:
            df[col] = None

    for col in [src.value for src in Source] + ["ADM3"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('.0', '', regex=False).map(_to_clean_str)

    adm3_dict = {adm.ext_id: adm for adm in Adm3.objects.only("id", "ext_id")}

    farm_index = {}
    for farm in Farm.objects():
        for ext in farm.ext_id:
            farm_index[(getattr(ext, "source", None), getattr(ext, "ext_code", None))] = farm

    try:
        farm_source_enum = FarmSource(farm_source)
    except Exception:
        farm_source_enum = None

    creados = actualizados = sin_cambios = errores = 0
    error_rows = []

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="🧭 Guardando Farms (pre)"):
        try:
            adm3_code = _to_clean_str(row.get("ADM3"))
            adm3_id = adm3_dict.get(adm3_code)
            if not adm3_id:
                raise ValueError(f"No se encontró Adm3 con ID {adm3_code}")

            ext_ids = []
            for src in Source:
                col = src.value
                ext_code = _to_clean_str(row.get(col))
                if ext_code:
                    ext_ids.append(ExtIdFarm(source=src, ext_code=ext_code))

            if not ext_ids:
                raise ValueError("Fila sin identificadores externos (SIT/PRODUCER)")

            farm = None
            for ext in ext_ids:
                farm = farm_index.get((ext.source, ext.ext_code))
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
                for ext in ext_ids:
                    farm_index[(ext.source, ext.ext_code)] = farm
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


def _save_farm_identifiers(csv_folder_path: str, output_path_save: str, farm_source: str):
    if not os.path.isdir(csv_folder_path):
        return
    for file in os.listdir(csv_folder_path):
        if file.endswith(".csv") and "new_farms" in file:
            csv_path = os.path.join(csv_folder_path, file)
            log_print(logger, f"📄 Procesando Farms CSV: {csv_path}")
            _process_farm_identifiers(csv_path, output_path_save, farm_source)


# ------------------------------------------------
# Guardar/actualizar: ENTERPRISE (new_enterprise)
# ------------------------------------------------
def _process_enterprise_identifiers(csv_path: str, output_path_save: str):
    df = pd.read_csv(csv_path, dtype=str)

    needed = ["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]
    for col in needed:
        if col not in df.columns:
            df[col] = None

    for col in [lab.value for lab in Label] + ["ADM2"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('.0', '', regex=False).map(_to_clean_str)

    for c in ("LATITUD", "LONGITUD"):
        if c in df.columns:
            df[c] = _to_float_series(df[c])

    adm2_dict = {adm.ext_id: adm for adm in Adm2.objects.only("id", "ext_id")}

    enterprise_index = {}
    for ent in Enterprise.objects():
        for ext in ent.ext_id:
            enterprise_index[(getattr(ext, "label", None), getattr(ext, "ext_code", None))] = ent

    creados = actualizados = sin_cambios = errores = 0
    error_rows = []

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="🏢 Guardando Enterprises (pre)"):
        try:
            adm2_code = _to_clean_str(row.get("ADM2"))
            adm2_id = adm2_dict.get(adm2_code)
            if not adm2_id:
                raise ValueError(f"No se encontró Adm2 con ID {adm2_code}")

            ext_ids = []
            for label in Label:
                col = label.value
                ext_code = _to_clean_str(row.get(col))
                if ext_code:
                    ext_ids.append(ExtIdEnterprise(label=label, ext_code=ext_code))
            if not ext_ids:
                base = _to_clean_str(row.get(Label.PRODUCTIONUNIT_ID.value))
                if base:
                    ext_ids.append(ExtIdEnterprise(label=Label.PRODUCTIONUNIT_ID, ext_code=base))
                else:
                    raise ValueError("Fila sin identificadores de enterprise")

            name = (row.get("NOMBRE") or "").strip()
            tipo = (row.get("TIPO") or "").strip().upper()
            lat = row.get("LATITUD")
            lon = row.get("LONGITUD")
            type_enterprise = TypeEnterprise[tipo] if tipo in TypeEnterprise.__members__ else TypeEnterprise.ENTERPRISE

            enterprise = None
            for ext in ext_ids:
                enterprise = enterprise_index.get((ext.label, ext.ext_code))
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
                for ext in ext_ids:
                    enterprise_index[(ext.label, ext.ext_code)] = enterprise
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


def _save_enterprise_identifiers(csv_folder_path: str, output_path_save: str):
    if not os.path.isdir(csv_folder_path):
        return
    for file in os.listdir(csv_folder_path):
        if file.endswith(".csv"):
            csv_path = os.path.join(csv_folder_path, file)
            log_print(logger, f"📄 Procesando Enterprise CSV: {csv_path}")
            _process_enterprise_identifiers(csv_path, output_path_save)


# -----------------------------
# Núcleo: guardar movimientos
# -----------------------------
def _detect_ganado_columns(df: pd.DataFrame):
    candidatas = [c for c in df.columns if c not in EXCLUDE_COLUMNS]
    def _is_numeric_like(series: pd.Series) -> bool:
        try:
            return pd.to_numeric(series, errors="coerce").notna().any()
        except Exception:
            return False
    return [c for c in candidatas if _is_numeric_like(df[c])]


def procesar_csv_movimientos(csv_path, output_path_save, source_pro):
    """
    Procesa un archivo CSV de movimientos:
    - Crea FARM on-the-fly si no existe (usando ADM3 del lado correspondiente).
    - Guarda movimientos idempotentes por EXT_ID.
    - Emite resumen por año y CSV de errores.
    """
    df = pd.read_csv(csv_path, parse_dates=["DATE"], dayfirst=True)
    df.columns = (df.columns
                  .str.strip()
                  .str.replace("'", "", regex=False)
                  .str.replace('"', '', regex=False))

    ganado_columns = _detect_ganado_columns(df)

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

    # caches
    farms_dict = _build_farms_dict()
    enterprises_dict = _build_enterprises_dict()
    movements_ext_ids = set(Movement.objects.only("ext_id").scalar("ext_id"))

    # resumen por año
    total_rows_by_year = defaultdict(int)
    matched_rows_by_year = defaultdict(int)
    inserted_rows_by_year = defaultdict(int)
    existing_rows_by_year = defaultdict(int)
    error_rows_by_year = defaultdict(int)

    errores = []
    buenos, malos, existentes = 0, 0, 0

    for index, row in tqdm(df.iterrows(), total=len(df), desc=f"Procesando {os.path.basename(csv_path)}"):
        try:
            try:
                year_key = int(row["DATE"].year)
            except Exception:
                year_key = "sin_fecha"
            total_rows_by_year[year_key] += 1

            ext_id = _to_clean_str(row.get("EXT_ID"))
            if not ext_id:
                raise ValueError("EXT_ID vacío")

            type_origin = _map_enum(TypeMovement, row.get("TIPO_ORIGEN"), "TIPO_ORIGEN")
            type_destination = _map_enum(TypeMovement, row.get("TIPO_DESTINO"), "TIPO_DESTINO")
            species = _map_enum(Species, row.get("ESPECIE"), "ESPECIE")

            farm_id_origin = farm_id_destination = None
            enterprise_id_origin = enterprise_id_destination = None

            if type_origin == TypeMovement.FARM:
                farm_id_origin = _get_or_create_farm_from_row(row, farms_dict, True, source_pro)
            else:
                enterprise_id_origin = _get_enterprise_from_row(row, enterprises_dict, True)
                if not enterprise_id_origin:
                    raise ValueError("No se encontró Enterprise origen")

            if type_destination == TypeMovement.FARM:
                farm_id_destination = _get_or_create_farm_from_row(row, farms_dict, False, source_pro)
            else:
                enterprise_id_destination = _get_enterprise_from_row(row, enterprises_dict, False)
                if not enterprise_id_destination:
                    raise ValueError("No se encontró Enterprise destino")

            movement_list = []
            for col in ganado_columns:
                val = row[col]
                try:
                    amount = _safe_int_amount(val)
                except ValueError:
                    continue
                movement_list.append(Classification(label=col, amount=amount))

            if not movement_list:
                raise ValueError("Fila sin cantidades de ganado válidas")

            matched_rows_by_year[year_key] += 1

            if ext_id in movements_ext_ids:
                existentes += 1
                existing_rows_by_year[year_key] += 1
                continue

            movimiento = Movement(
                date=row["DATE"],
                ext_id=ext_id,
                type_origin=type_origin,
                type_destination=type_destination,
                source_movement=sourcemovement,
                species=species,
                farm_id_origin=farm_id_origin,
                farm_id_destination=farm_id_destination,
                enterprise_id_origin=enterprise_id_origin,
                enterprise_id_destination=enterprise_id_destination,
                movement=movement_list
            )
            movimiento.save()
            buenos += 1
            inserted_rows_by_year[year_key] += 1
            movements_ext_ids.add(ext_id)

        except Exception as e:
            errores.append({**row.to_dict(), "fila_original": index, "error": str(e)})
            malos += 1
            error_rows_by_year[year_key] += 1

    log_print(logger, f"Completado: {buenos} guardados, {existentes} ya existentes, {malos} con error.")

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
            "year": y,
            "total_rows": total_rows_by_year.get(y, 0),
            "matched_rows": matched_rows_by_year.get(y, 0),    # “deberían guardarse”
            "inserted_rows": inserted_rows_by_year.get(y, 0),  # guardados nuevos
            "existing_rows": existing_rows_by_year.get(y, 0),  # coincidían pero ya existían
            "error_rows": error_rows_by_year.get(y, 0)
        })

    summary_df = pd.DataFrame(summary_rows)
    os.makedirs(output_path_save, exist_ok=True)
    summary_name = f"movements_save_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    summary_path = os.path.join(output_path_save, summary_name)
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    log_print(logger, f"📊 Resumen por año guardado en: {summary_path}")


# ----------------------------------------
# Orquestador público (NO CAMBIA EL NOMBRE)
# ----------------------------------------
def save_movements(input_path_root, output_path_save, input_path_farm_enterprise, source_pro):
    """
    Orquesta el guardado en este orden:
      1) Guarda/actualiza FARMS desde input_path_farm_enterprise/farms/*new_farms*.csv
      2) Guarda/actualiza ENTERPRISES desde input_path_farm_enterprise/enterprise/*.csv
      3) Procesa y guarda MOVEMENTS desde input_path_root/movement/*.csv
    """
    connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])

    # 1) FARMS
    farms_dir = os.path.join(input_path_farm_enterprise, "farms")
    if os.path.isdir(farms_dir):
        files = [f for f in os.listdir(farms_dir) if f.endswith(".csv") and "new_farms" in f]
        if files:
            log_print(logger, f"Guardando Farms (pre): {farms_dir} → {len(files)} archivo(s)")
            _save_farm_identifiers(farms_dir, output_path_save, source_pro)
        else:
            log_print(logger, "No hay CSV de 'new_farms' — se continúa.")
    else:
        log_print(logger, f"Carpeta de farms no existe: {farms_dir}")

    # 2) ENTERPRISES
    enterprise_dir = os.path.join(input_path_farm_enterprise, "enterprise")
    if os.path.isdir(enterprise_dir):
        files = [f for f in os.listdir(enterprise_dir) if f.endswith(".csv")]
        if files:
            log_print(logger, f"Guardando Enterprises (pre): {enterprise_dir} → {len(files)} archivo(s)")
            _save_enterprise_identifiers(enterprise_dir, output_path_save)
        else:
            log_print(logger, "No hay CSV en 'enterprise' — se continúa.")
    else:
        log_print(logger, f"Carpeta de enterprise no existe: {enterprise_dir}")

    # 3) MOVEMENTS
    path_movements = os.path.join(input_path_root, "movement")
    if not os.path.isdir(path_movements):
        log_print(logger, f"No existe carpeta movement: {path_movements}")
        return

    archivos = [f for f in os.listdir(path_movements) if f.lower().endswith(".csv")]
    if not archivos:
        log_print(logger, "No se encontraron CSV de movimientos.")
        return

    for archivo in archivos:
        ruta_completa = os.path.join(path_movements, archivo)
        log_print(logger, f"Procesando archivo de movimientos: {archivo}")
        procesar_csv_movimientos(ruta_completa, output_path_save, source_pro)
