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
                # dict fallback
                if code is None and isinstance(ext, dict):
                    src = ext.get("source")
                    code = ext.get("ext_code")
                # source como enum o string
                src_val = src.value if hasattr(src, "value") else str(src)
                key = f"{src_val}:{_to_clean_str(code)}"
                if key.split(":", 1)[1]:  # no guardar claves vacías
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
            # dict fallback (por si acaso)
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

    # Determinar FarmSource si es válido; si no, omitir
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

    # Actualizar diccionario en memoria para próximas filas
    for ext in ext_ids:
        farms_dict[f"{ext.source.value}:{_to_clean_str(ext.ext_code)}"] = farm

    return farm


# -----------------------------
# Resolución de ENTERPRISE
# -----------------------------
def _get_enterprise_from_row(row, enterprises_dict, is_origin=True):
    """
    Busca ENTERPRISE probando todas las columnas posibles por Label:
    f'{label.value}_ORIGEN/DESTINO', normalizando ext_code.
    """
    suffix = "ORIGEN" if is_origin else "DESTINO"
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
    return None


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
    # Lee CSV
    df = pd.read_csv(csv_path, parse_dates=["DATE"], dayfirst=True)
    df.columns = (df.columns
                  .str.strip()
                  .str.replace("'", "", regex=False)
                  .str.replace('"', '', regex=False))

    # Detección de columnas de ganado (numéricas)
    ganado_columns = _detect_ganado_columns(df)

    # Conexión y SourceMovement
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

    # Precarga de FARM y ENTERPRISE
    farms_dict = _build_farms_dict()
    enterprises_dict = _build_enterprises_dict()

    # Idempotencia: EXT_ID ya guardados
    movements_ext_ids = set(Movement.objects.only("ext_id").scalar("ext_id"))

    # Acumuladores por año
    total_rows_by_year = defaultdict(int)
    matched_rows_by_year = defaultdict(int)
    inserted_rows_by_year = defaultdict(int)
    existing_rows_by_year = defaultdict(int)
    error_rows_by_year = defaultdict(int)

    errores = []
    buenos, malos, existentes = 0, 0, 0

    # Iteración principal
    for index, row in tqdm(df.iterrows(), total=len(df), desc=f"Procesando {os.path.basename(csv_path)}"):
        # Año (si falla fecha, lo clasificamos como 'sin_fecha')
        try:
            year_key = int(row["DATE"].year)
        except Exception:
            year_key = "sin_fecha"
        total_rows_by_year[year_key] += 1

        try:
            # EXT_ID normalizado
            ext_id_raw = row["EXT_ID"]
            ext_id = _to_clean_str(ext_id_raw)
            if not ext_id:
                raise ValueError("EXT_ID vacío")

            # Enums robustos
            type_origin = _map_enum(TypeMovement, row.get("TIPO_ORIGEN"), "TIPO_ORIGEN")
            type_destination = _map_enum(TypeMovement, row.get("TIPO_DESTINO"), "TIPO_DESTINO")
            species = _map_enum(Species, row.get("ESPECIE"), "ESPECIE")

            # Resolver origen/destino (creando FARM on-the-fly si falta)
            farm_id_origin = farm_id_destination = None
            enterprise_id_origin = enterprise_id_destination = None

            if type_origin == TypeMovement.FARM:
                farm_id_origin = _get_or_create_farm_from_row(row, farms_dict, is_origin=True, farm_source_from_param=source_pro)
            else:
                enterprise_id_origin = _get_enterprise_from_row(row, enterprises_dict, is_origin=True)
                if not enterprise_id_origin:
                    raise ValueError("No se encontró Enterprise origen")

            if type_destination == TypeMovement.FARM:
                farm_id_destination = _get_or_create_farm_from_row(row, farms_dict, is_origin=False, farm_source_from_param=source_pro)
            else:
                enterprise_id_destination = _get_enterprise_from_row(row, enterprises_dict, is_origin=False)
                if not enterprise_id_destination:
                    raise ValueError("No se encontró Enterprise destino")

            # Clasificaciones (solo columnas numéricas candidatas)
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

            # Si llegamos aquí, hubo “coincidencia válida”
            matched_rows_by_year[year_key] += 1

            # Idempotencia por EXT_ID
            if ext_id in movements_ext_ids:
                existentes += 1
                existing_rows_by_year[year_key] += 1
                continue

            # Construir y guardar
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

    # Log resumen en consola
    log_print(logger, f"Completado: {buenos} guardados, {existentes} ya existentes, {malos} con error.")

    # Guardar errores detallados (si hay)
    if errores:
        os.makedirs(output_path_save, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(csv_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = f"{base_name}_errores_{timestamp}.csv"
        error_path = os.path.join(output_path_save, error_file)
        pd.DataFrame(errores).to_csv(error_path, index=False)
        log_print(logger, f"Errores guardados en: {error_path}")

    # Guardar resumen por año
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
# Orquestador: detecta archivos y procesa
# ----------------------------------------
def save_movements(input_path_root, output_path_save, input_path_farm_enterprise, source_pro):
    """
    Orquesta el guardado de movimientos:
    - Crea FARM al vuelo cuando falten (usando ADM3 del lado correspondiente).
    - Procesa todos los CSV en input_path_root/movement.
    - Genera resumen por año y CSV de errores.
    """
    connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])

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
