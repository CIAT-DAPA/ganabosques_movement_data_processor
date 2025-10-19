# -*- coding: utf-8 -*-
import os
import io
import zipfile
import requests
import pandas as pd
import geopandas as gpd
from mongoengine import connect

# ORM
from ganabosques_orm.collections.farm import Farm
from ganabosques_orm.auxiliaries.extidfarm import ExtIdFarm
from ganabosques_orm.enums.source import Source
from ganabosques_orm.enums.label import Label
from ganabosques_orm.enums.typemovement import TypeMovement
from ganabosques_orm.collections.adm3 import Adm3  # <-- para validar catálogo ADM3

# Config (.env ya lo carga tu config.py)
from config import config


# =========================
# Utilidades y normalización
# =========================
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


def _to_float_series(col: pd.Series) -> pd.Series:
    """
    Convierte una serie a float de forma tolerante:
    - Trim, elimina NBSP y separadores comunes
    - Soporta coma decimal y miles mezclados ('.' y ',')
    - Convierte '', '-', 'nan', 'none', 'null' a NaN
    """
    s = col.astype(str).str.strip().str.replace("\u00A0", "", regex=False)  # NBSP
    s = s.replace(
        {"": pd.NA, "-": pd.NA, "—": pd.NA, "--": pd.NA,
         "nan": pd.NA, "NaN": pd.NA, "NONE": pd.NA, "None": pd.NA, "null": pd.NA, "NULL": pd.NA}
    )

    def _norm(x: str) -> str:
        if x is pd.NA or x is None:
            return x
        x = str(x)
        x = x.replace(" ", "").replace("'", "")  # miles como espacio/apóstrofo
        # Solo comas -> coma decimal
        if ("," in x) and ("." not in x):
            x = x.replace(",", ".")
        # Ambos separadores: decide por última aparición
        elif ("," in x) and ("." in x):
            if x.rfind(",") > x.rfind("."):
                x = x.replace(".", "").replace(",", ".")  # punto miles, coma decimal
            else:
                x = x.replace(",", "")  # coma miles, punto decimal
        return x

    s = s.map(_norm)
    return pd.to_numeric(s, errors="coerce")


def _load_all_csv(folder: str) -> pd.DataFrame:
    if not os.path.isdir(folder):
        return pd.DataFrame()
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".csv")]
    if not files:
        return pd.DataFrame()
    # Mantén tipos por defecto; en caso de necesitar dtype=str, cámbialo aquí
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


# =========================
# FARMS: detectar nuevos
# =========================
def _cargar_existentes_en_mongo():
    """Devuelve dos sets con códigos existentes en Farm: SIT_CODE y PRODUCER_ID."""
    connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])
    existing_sit, existing_prod = set(), set()

    for farm in Farm.objects.only("ext_id"):
        if not farm.ext_id:
            continue
        for ext in farm.ext_id:
            # tolera objeto/dict/atributos
            if isinstance(ext, ExtIdFarm):
                src, code = ext.source, ext.ext_code
            elif isinstance(ext, dict):
                src, code = ext.get("source"), ext.get("ext_code")
            else:
                src, code = getattr(ext, "source", None), getattr(ext, "ext_code", None)

            code_s = _to_clean_str(code)
            if not code_s:
                continue

            if src == Source.SIT_CODE or (isinstance(src, str) and src == Source.SIT_CODE.value):
                existing_sit.add(code_s)
            elif src == Source.PRODUCER_ID or (isinstance(src, str) and src == Source.PRODUCER_ID.value):
                existing_prod.add(code_s)

    return existing_sit, existing_prod


def _marcar_nuevos_farms(farms_df: pd.DataFrame) -> pd.DataFrame:
    """Marca 'nuevos' por ausencia en Mongo (SIT -> fallback PRODUCER)."""
    for c in (Source.SIT_CODE.value, Source.PRODUCER_ID.value, "ADM3", "TIPO"):
        if c not in farms_df.columns:
            farms_df[c] = pd.NA

    farms_df[Source.SIT_CODE.value] = farms_df[Source.SIT_CODE.value].map(_to_clean_str)
    farms_df[Source.PRODUCER_ID.value] = farms_df[Source.PRODUCER_ID.value].map(_to_clean_str)
    farms_df["ADM3"] = farms_df["ADM3"].map(_to_clean_str)
    farms_df["TIPO"] = farms_df["TIPO"].astype(str).str.strip().str.upper()

    existing_sit, existing_prod = _cargar_existentes_en_mongo()

    def _row_is_new(row):
        sit = row[Source.SIT_CODE.value]
        prod = row[Source.PRODUCER_ID.value]
        if sit and sit in existing_sit:
            return False
        if prod and prod in existing_prod:
            return False
        return True

    mask_new = farms_df.apply(_row_is_new, axis=1)
    return farms_df[mask_new].copy()


def _validar_adm3_catalogo(farms_df: pd.DataFrame) -> pd.DataFrame:
    """
    Devuelve las filas cuyo ADM3 no existe en el catálogo Adm3 (por ext_id).
    Solo inspecciona filas con ADM3 no vacío.
    """
    # catálogo de Adm3
    adm3_catalog = set()
    for adm in Adm3.objects.only("ext_id"):
        adm3_catalog.add(_to_clean_str(getattr(adm, "ext_id", None)))

    df = farms_df.copy()
    df["ADM3"] = df["ADM3"].map(_to_clean_str)
    mask_check = df["ADM3"].astype(str).str.len() > 0
    missing = df[mask_check & (~df["ADM3"].isin(adm3_catalog))].copy()
    return missing


# ==========================================
# ENTERPRISE: centroides ADM2 desde shapefile ADM3
# ==========================================
def _descargar_adm3_wfs(output_dir: str) -> str:
    URL_GS = config["URL_GEO"].rstrip("/")
    WORKSPACE = config["GEO_WORKSPACE"]
    STORE = config["GEO_STORE"]
    USER = config["GEO_USER"]
    PWD = config["GEO_PWD"]

    print("\n🌐 Descargando ADM3 (WFS) para derivar centroides por municipio (ADM2)...")
    wfs_url = (
        f"{URL_GS}/{WORKSPACE}/wfs?"
        f"service=WFS&version=1.0.0&request=GetFeature&"
        f"typeName={WORKSPACE}:{STORE}&outputFormat=shape-zip"
    )
    shp_dir = os.path.join(output_dir, "shapefile_adm3")
    os.makedirs(shp_dir, exist_ok=True)

    r = requests.get(wfs_url, auth=(USER, PWD))
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(shp_dir)

    shp_files = [f for f in os.listdir(shp_dir) if f.lower().endswith(".shp")]
    if not shp_files:
        raise RuntimeError("No se encontró .shp tras extraer ADM3.")
    return os.path.join(shp_dir, shp_files[0])


def _centroides_adm2_desde_adm3(output_dir: str) -> pd.DataFrame:
    """Disuelve por cod_mpio y devuelve centroides por municipio en WGS84."""
    shp_path = _descargar_adm3_wfs(output_dir)
    gdf = gpd.read_file(shp_path)
    print("📋 Columnas ADM3:", list(gdf.columns))

    prefer_code = "cod_mpio"
    prefer_name = "nom_mpio"
    cols_lower = {c.lower(): c for c in gdf.columns}

    if prefer_code in cols_lower:
        col_adm2_code = cols_lower[prefer_code]
    else:
        raise RuntimeError("No se encontró columna 'cod_mpio' dentro de ADM3.")
    col_adm2_name = cols_lower.get(prefer_name, None)

    gdf["ADM2_CODE"] = gdf[col_adm2_code].astype(str).str.strip()
    if col_adm2_name:
        gdf["ADM2_NAME"] = gdf[col_adm2_name].astype(str).str.strip()

    gdf = gdf[gdf.geometry.notna() & gdf.is_valid]

    gdf_3116 = gdf.to_crs(3116)
    dis = gdf_3116.dissolve(by="ADM2_CODE", as_index=False)
    cents_3116 = dis.geometry.centroid
    cents_wgs = gpd.GeoSeries(cents_3116, crs=3116).to_crs(4326)

    out = pd.DataFrame({
        "ADM2_CODE": dis["ADM2_CODE"].astype(str),
        "LATITUD": cents_wgs.y,
        "LONGITUD": cents_wgs.x,
    })
    print(f"🧭 Centroides generados para {len(out)} municipios (ADM2_CODE = cod_mpio).")
    return out


def _completar_coords_enterprise(new_enterprise: pd.DataFrame, output_dir: str) -> pd.DataFrame:
    """Completa LAT/LON con centroides ADM2 y duplica coords dentro del mismo ADM2 si faltan."""
    if new_enterprise.empty:
        return new_enterprise

    centroids = _centroides_adm2_desde_adm3(output_dir)

    df = new_enterprise.copy()
    df["ADM2"] = df["ADM2"].map(_to_clean_str)
    df["LATITUD"] = pd.to_numeric(df["LATITUD"], errors="coerce")
    df["LONGITUD"] = pd.to_numeric(df["LONGITUD"], errors="coerce")

    df = pd.merge(df, centroids, left_on="ADM2", right_on="ADM2_CODE", how="left", suffixes=("", "_cent"))
    df["LATITUD"] = df["LATITUD"].combine_first(df["LATITUD_cent"])
    df["LONGITUD"] = df["LONGITUD"].combine_first(df["LONGITUD_cent"])
    df.drop(columns=["ADM2_CODE", "LATITUD_cent", "LONGITUD_cent"], inplace=True)

    missing = df["LATITUD"].isna() | df["LONGITUD"].isna()
    if missing.any():
        filled = df[~missing][["ADM2", "LATITUD", "LONGITUD"]].drop_duplicates()

        def _fill_row(row):
            if pd.isna(row["LATITUD"]) or pd.isna(row["LONGITUD"]):
                m = filled[filled["ADM2"] == row["ADM2"]]
                if not m.empty:
                    row["LATITUD"] = m.iloc[0]["LATITUD"]
                    row["LONGITUD"] = m.iloc[0]["LONGITUD"]
            return row

        df = df.apply(_fill_row, axis=1)

    final_missing = df["LATITUD"].isna() | df["LONGITUD"].isna()
    if final_missing.any():
        print(f"🗑️ Eliminando {final_missing.sum()} enterprise sin coordenadas tras centroides ADM3.")
        df = df[~final_missing].copy()

    return df


# =========================
# CHECK principal
# =========================
def check(input_data: str, output_data: str, info: str):
    """
    - FARMS: Une CSVs, detecta nuevos comparando contra Mongo (SIT → PRODUCER fallback),
      valida ADM3 contra catálogo, y genera outputs listos para crear nuevos farms.
    - ENTERPRISE: Conforma empresas desde CSV + TXT (CC, SH, CF), completa coordenadas, dedup por PRODUCTIONUNIT_ID.
    """
    os.makedirs(output_data, exist_ok=True)

    # ---------- FARMS ----------
    farms_dir = os.path.join(input_data, "farms")
    farms_df = _load_all_csv(farms_dir)
    if farms_df.empty:
        farms_df = pd.DataFrame(columns=[Source.SIT_CODE.value, Source.PRODUCER_ID.value, "ADM3", "TIPO"])

    new_farms = _marcar_nuevos_farms(farms_df)

    total_farms = len(farms_df)
    not_found = len(new_farms)
    found = total_farms - not_found
    found_pct = (found / total_farms * 100) if total_farms else 0.0

    print(f"Total farms (filas): {total_farms}")
    print(f"Coincidencias encontradas en Mongo: {found} ({found_pct:.2f}%)")
    print(f"Nuevos (SIT/PRODUCER no presentes): {not_found}")

    farms_output_path = os.path.join(output_data, "farms")
    os.makedirs(farms_output_path, exist_ok=True)

    # Deduplicación y export mínimo para crear farms
    if not new_farms.empty:
        new_farms = new_farms.drop_duplicates(subset=[Source.SIT_CODE.value])
        new_farms = new_farms.drop_duplicates(subset=[Source.PRODUCER_ID.value])

    # Export para trazabilidad completa
    new_farms.to_csv(os.path.join(farms_output_path, "new_farms.csv"),
                     index=False, encoding="utf-8-sig")

    # Export mínimo para crear (solo columnas clave)
    new_farms_min = new_farms[[Source.SIT_CODE.value, Source.PRODUCER_ID.value, "ADM3", "TIPO"]].copy()
    new_farms_min.to_csv(os.path.join(farms_output_path, "new_farms_to_create.csv"),
                         index=False, encoding="utf-8-sig")

    # Validación de ADM3 contra catálogo
    farms_adm3_missing_catalog = _validar_adm3_catalogo(new_farms_min)
    if not farms_adm3_missing_catalog.empty:
        p = os.path.join(farms_output_path, "farms_adm3_not_in_catalog.csv")
        farms_adm3_missing_catalog.to_csv(p, index=False, encoding="utf-8-sig")
        print(f"⚠️ ADM3 no encontrados en catálogo: {len(farms_adm3_missing_catalog)} → {p}")

    # Log ADM3 problemático literal (valor especial)
    problem_value = "999999999999"
    farms_df["ADM3"] = farms_df["ADM3"].map(_to_clean_str)
    farms_with_problem = farms_df[farms_df["ADM3"] == problem_value].copy()

    log_csv_path = os.path.join(farms_output_path, "farms_adm3_issues.csv")
    farms_with_problem.to_csv(log_csv_path, index=False, encoding="utf-8-sig")

    summary_txt = (
        f"Resumen de ADM3 en farms:\n"
        f"Total de registros: {total_farms}\n"
        f"Registros con ADM3 == {problem_value}: {len(farms_with_problem)}\n"
        f"Posibles nuevos farms: {len(new_farms)} (ver new_farms.csv / new_farms_to_create.csv)\n"
    )
    summary_txt_path = os.path.join(farms_output_path, "farms_adm3_summary.txt")
    with open(summary_txt_path, "w", encoding="utf-8") as f:
        f.write(summary_txt)

    print("🧾 Logs generados (farms):")
    print(f"- CSV de registros problemáticos: {log_csv_path}")
    print(f"- Resumen en TXT: {summary_txt_path}")
    print(f"- CSV mínimo para crear nuevos farms: {os.path.join(farms_output_path, 'new_farms_to_create.csv')}")

    # ---------- ENTERPRISE ----------
    enterprise_dir = os.path.join(input_data, "enterprise")
    enterprise_df = _load_all_csv(enterprise_dir)
    if enterprise_df.empty:
        enterprise_df = pd.DataFrame(columns=["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2", "NOMBRE", "LATITUD", "LONGITUD"])

    # TXT esperados en `info/`
    cc_path = os.path.join(info, f"{TypeMovement.COLLECTION_CENTER.value}.txt")
    sh_path = os.path.join(info, f"{TypeMovement.SLAUGHTERHOUSE.value}.txt")
    cf_path = os.path.join(info, f"{TypeMovement.CATTLE_FAIR.value}.txt")

    # Normaliza base
    enterprise_df["TIPO"] = enterprise_df["TIPO"].astype(str).str.strip().str.upper()
    enterprise_df[Label.PRODUCTIONUNIT_ID.value] = enterprise_df[Label.PRODUCTIONUNIT_ID.value].map(_to_clean_str)
    enterprise_df["ADM2"] = enterprise_df["ADM2"].map(_to_clean_str)

    CC_VAL = str(TypeMovement.COLLECTION_CENTER.value).upper()
    SH_VAL = str(TypeMovement.SLAUGHTERHOUSE.value).upper()
    CF_VAL = str(TypeMovement.CATTLE_FAIR.value).upper()

    # Helper lectura TXT con detección de columnas y conversión robusta de LAT/LON
    def _leer_txt_emp(path, key_candidates, name_candidates):
        if not os.path.isfile(path):
            return None, None, None
        df = pd.read_csv(path, sep="|", encoding="latin1")
        df.columns = df.columns.str.strip().str.upper()
        key_col = next((c for c in key_candidates if c in df.columns), None)
        name_col = next((c for c in name_candidates if c in df.columns), None)
        if key_col is None:
            raise RuntimeError(
                f"No encontré columna llave en {os.path.basename(path)}. "
                f"Probé {key_candidates}. Encabezados: {list(df.columns)}"
            )
        df[key_col] = df[key_col].map(_to_clean_str)
        for c in ("LATITUD", "LONGITUD"):
            if c in df.columns:
                df[c] = _to_float_series(df[c])
        return df, key_col, name_col

    # COLLECTION CENTER
    cc_txt, cc_key_col, cc_name_col = _leer_txt_emp(
        cc_path,
        key_candidates=["ID_CONCENTRACION", "ID_CC", "ID_CENTRO_ACOPIO", "ID_CONCENTRATION"],
        name_candidates=["NOMBRE_CONCENTRACION", "NOMBRE_CC", "NOMBRE", "NOMBRE_CENTRO_ACOPIO"]
    )
    if cc_txt is not None:
        cc_filter = enterprise_df["TIPO"] == CC_VAL
        merged_cc = pd.merge(
            enterprise_df[cc_filter], cc_txt,
            left_on=Label.PRODUCTIONUNIT_ID.value, right_on=cc_key_col, how="left"
        )
        if cc_name_col and cc_name_col in merged_cc.columns:
            merged_cc = merged_cc.rename(columns={cc_name_col: "NOMBRE"})
        else:
            if "NOMBRE" not in merged_cc.columns:
                merged_cc["NOMBRE"] = None
        for col in ("LATITUD", "LONGITUD"):
            if col not in merged_cc.columns:
                merged_cc[col] = None
        merged_cc = merged_cc[["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]]
    else:
        cc_filter = enterprise_df["TIPO"] == CC_VAL
        merged_cc = enterprise_df[cc_filter][["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2"]].copy()
        merged_cc["NOMBRE"] = None; merged_cc["LATITUD"] = None; merged_cc["LONGITUD"] = None

    # SLAUGHTERHOUSE
    sh_txt, sh_key_col, sh_name_col = _leer_txt_emp(
        sh_path,
        key_candidates=["ID_PLANTA_BENEFICIO", "ID_PB", "ID_PLANTA"],
        name_candidates=["NOMBRE_PLANTA_BENEFICIO", "NOMBRE_PB", "NOMBRE"]
    )
    if sh_txt is not None:
        sh_filter = enterprise_df["TIPO"] == SH_VAL
        merged_sh = pd.merge(
            enterprise_df[sh_filter], sh_txt,
            left_on=Label.PRODUCTIONUNIT_ID.value, right_on=sh_key_col, how="left"
        )
        if sh_name_col and sh_name_col in merged_sh.columns:
            merged_sh = merged_sh.rename(columns={sh_name_col: "NOMBRE"})
        else:
            if "NOMBRE" not in merged_sh.columns:
                merged_sh["NOMBRE"] = None
        for col in ("LATITUD", "LONGITUD"):
            if col not in merged_sh.columns:
                merged_sh[col] = None
        merged_sh = merged_sh[["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]]
    else:
        sh_filter = enterprise_df["TIPO"] == SH_VAL
        merged_sh = enterprise_df[sh_filter][["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2"]].copy()
        merged_sh["NOMBRE"] = None; merged_sh["LATITUD"] = None; merged_sh["LONGITUD"] = None

    # CATTLE FAIR
    cf_txt, cf_key_col, cf_name_col = _leer_txt_emp(
        cf_path,
        key_candidates=["ID_FERIA", "ID_CATTLE_FAIR", "ID_CF", "ID_CONCENTRACION", "ID_CC"],
        name_candidates=["NOMBRE_FERIA", "NOMBRE_CATTLE_FAIR", "NOMBRE", "NOMBRE_CONCENTRACION", "NOMBRE_CC"]
    )
    if cf_txt is not None:
        cf_filter = enterprise_df["TIPO"] == CF_VAL
        merged_cf = pd.merge(
            enterprise_df[cf_filter], cf_txt,
            left_on=Label.PRODUCTIONUNIT_ID.value, right_on=cf_key_col, how="left"
        )
        if cf_name_col and cf_name_col in merged_cf.columns:
            merged_cf = merged_cf.rename(columns={cf_name_col: "NOMBRE"})
        else:
            if "NOMBRE" not in merged_cf.columns:
                merged_cf["NOMBRE"] = None
        for col in ("LATITUD", "LONGITUD"):
            if col not in merged_cf.columns:
                merged_cf[col] = None
        merged_cf = merged_cf[["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]]
    else:
        cf_filter = enterprise_df["TIPO"] == CF_VAL
        merged_cf = enterprise_df[cf_filter][["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2"]].copy()
        merged_cf["NOMBRE"] = None; merged_cf["LATITUD"] = None; merged_cf["LONGITUD"] = None

    # Otros tipos
    others = enterprise_df[~(enterprise_df["TIPO"].isin([CC_VAL, SH_VAL, CF_VAL]))][
        ["TIPO", Label.PRODUCTIONUNIT_ID.value, "ADM2"]
    ].copy()
    others["NOMBRE"] = None; others["LATITUD"] = None; others["LONGITUD"] = None

    # Unión final y limpieza
    new_enterprise = pd.concat([merged_cc, merged_sh, merged_cf, others], ignore_index=True)
    new_enterprise["NOMBRE"] = new_enterprise["NOMBRE"].astype(str).str.strip()
    new_enterprise = new_enterprise[~new_enterprise["NOMBRE"].isin(["", "nan", "None"])]
    new_enterprise = new_enterprise[~new_enterprise["NOMBRE"].str.contains("---INACTIVA---", case=False, na=False)]
    new_enterprise = new_enterprise[~new_enterprise["NOMBRE"].str.contains("^-+$", na=False)]

    # Completar coordenadas con centroides de ADM2
    new_enterprise = _completar_coords_enterprise(new_enterprise, output_data)

    # Guardar enterprise
    enterprise_output_path = os.path.join(output_data, "enterprise")
    os.makedirs(enterprise_output_path, exist_ok=True)
    if not new_enterprise.empty:
        new_enterprise = new_enterprise.drop_duplicates(subset=[Label.PRODUCTIONUNIT_ID.value])

    final_csv = os.path.join(enterprise_output_path, "new_enterprise.csv")
    new_enterprise.to_csv(final_csv, index=False, encoding="utf-8-sig")
    print(f"✅ Archivo new_enterprise.csv generado correctamente con coordenadas completadas → {final_csv}")

    # (Opcional) exporta por tipo
    for val, fname in [
        (CC_VAL, "enterprise_collection_center.csv"),
        (SH_VAL, "enterprise_slaughterhouse.csv"),
        (CF_VAL, "enterprise_cattle_fair.csv")
    ]:
        subdf = new_enterprise[new_enterprise["TIPO"] == val]
        if not subdf.empty:
            sub_path = os.path.join(enterprise_output_path, fname)
            subdf.to_csv(sub_path, index=False, encoding="utf-8-sig")
            print(f"   ↳ guardado {fname}: {len(subdf)} filas → {sub_path}")
