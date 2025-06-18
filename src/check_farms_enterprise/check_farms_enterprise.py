import os
import io
import zipfile
import requests
import pandas as pd
import geopandas as gpd
from mongoengine import connect
from ganabosques_orm.collections.adm3 import Adm3
from config import config

workspace= config["GEO_WORKSPACE"]
store= config['GEO_STORE'] 
url_geoserver= config['URL_GEO']
user=config['GEO_USER']
password=config['GEO_PWD']

def completar_coordenadas_con_shapefile(new_enterprise, output_data, workspace, store, url_geoserver, user, password):
    print("\n🌐 Descargando shapefile ADM2 desde GeoServer...")

    shp_output = os.path.join(output_data, "shapefile_adm2")
    os.makedirs(shp_output, exist_ok=True)

    url_shp = f"{url_geoserver}/{workspace}/wfs?service=WFS&version=1.0.0&request=GetFeature&typeName={workspace}:{store}&outputFormat=shape-zip"
    print("🌐 Solicitando shapefile desde:", url_shp)

    response = requests.get(url_shp, auth=(user, password))
    if not response.ok:
        print("❌ Error al descargar shapefile:", response.status_code)
        return new_enterprise

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        z.extractall(shp_output)
    print("✅ Shapefile descargado y extraído en:", shp_output)

    shp_files = [f for f in os.listdir(shp_output) if f.endswith(".shp")]
    if not shp_files:
        print("❌ No se encontró shapefile extraído.")
        return new_enterprise

    ruta_shp = os.path.join(shp_output, shp_files[0])
    adm2_gdf = gpd.read_file(ruta_shp)
    print("📋 Columnas disponibles en el shapefile:")
    print(adm2_gdf.columns.tolist())

    # Identificar columna ADM2
    posibles_adm2 = ["adm2", "cod_mpio", "codigo_municipio", "municipio", "nom_mun"]
    adm2_col = next((col for col in adm2_gdf.columns if col.lower() in posibles_adm2), None)

    if not adm2_col:
        print("❌ No se encontró columna compatible con ADM2 en el shapefile.")
        return new_enterprise

    print(f"🔄 Usando la columna '{adm2_col}' como ADM2.")
    adm2_gdf = adm2_gdf.rename(columns={adm2_col: "ADM2"})
    adm2_gdf["ADM2"] = adm2_gdf["ADM2"].astype(str).str.strip().str.upper()

    # Validar geometrías válidas
    adm2_gdf = adm2_gdf[adm2_gdf.geometry.notnull() & adm2_gdf.is_valid]

    # Calcular centroides
    adm2_proj = adm2_gdf.to_crs("EPSG:3116")
    centroids_proj = adm2_proj.geometry.centroid
    centroids_latlon = gpd.GeoSeries(centroids_proj, crs="EPSG:3116").to_crs("EPSG:4326")
    adm2_gdf["LATITUD"] = centroids_latlon.y
    adm2_gdf["LONGITUD"] = centroids_latlon.x

    adm2_coords = adm2_gdf[["ADM2", "LATITUD", "LONGITUD"]].dropna().copy()
    print("📌 ADM2 únicos en shapefile:", adm2_coords["ADM2"].unique()[:5])

    # Preparar new_enterprise
    new_enterprise["ADM2"] = new_enterprise["ADM2"].astype(str).str.strip().str.upper()
    new_enterprise["LATITUD"] = pd.to_numeric(new_enterprise["LATITUD"], errors="coerce")
    new_enterprise["LONGITUD"] = pd.to_numeric(new_enterprise["LONGITUD"], errors="coerce")
    new_enterprise["PRODUCTIONUNIT_ID"] = new_enterprise["PRODUCTIONUNIT_ID"].astype(str)

    missing_mask = new_enterprise["LATITUD"].isna() | new_enterprise["LONGITUD"].isna()
    print(f"🔍 Registros con coordenadas faltantes: {missing_mask.sum()}")

    # Merge con shapefile para completar coordenadas
    new_enterprise = pd.merge(
        new_enterprise,
        adm2_coords,
        on="ADM2",
        how="left",
        suffixes=("", "_shp")
    )

    # Rellenar LAT y LON faltantes
    new_enterprise["LATITUD"] = new_enterprise["LATITUD"].combine_first(new_enterprise["LATITUD_shp"])
    new_enterprise["LONGITUD"] = new_enterprise["LONGITUD"].combine_first(new_enterprise["LONGITUD_shp"])
    new_enterprise.drop(columns=["LATITUD_shp", "LONGITUD_shp"], inplace=True)

    still_missing = new_enterprise["LATITUD"].isna() | new_enterprise["LONGITUD"].isna()
    print(f"🧭 Coordenadas completadas. Aún faltantes: {still_missing.sum()}")

    # 🔄 Reintento: buscar coordenadas dentro del mismo ADM2 ya completo
    if still_missing.any():
        print("🔁 Buscando coordenadas dentro del mismo ADM2...")
        completed_coords = new_enterprise[~still_missing][["ADM2", "LATITUD", "LONGITUD"]].drop_duplicates()

        def rellenar_coord(row):
            if pd.isna(row["LATITUD"]) or pd.isna(row["LONGITUD"]):
                match = completed_coords[completed_coords["ADM2"] == row["ADM2"]]
                if not match.empty:
                    return pd.Series({"LATITUD": match["LATITUD"].values[0], "LONGITUD": match["LONGITUD"].values[0]})
            return pd.Series({"LATITUD": row["LATITUD"], "LONGITUD": row["LONGITUD"]})

        new_enterprise[["LATITUD", "LONGITUD"]] = new_enterprise.apply(rellenar_coord, axis=1)

    # 🚮 Eliminar filas que aún no tienen coordenadas
    final_missing = new_enterprise["LATITUD"].isna() | new_enterprise["LONGITUD"].isna()
    if final_missing.any():
        print(f"🗑️ Eliminando {final_missing.sum()} filas sin coordenadas.")
        new_enterprise = new_enterprise[~final_missing]

    print("✅ Coordenadas completadas y filas inválidas eliminadas.")

    return new_enterprise



def check(input_data, output_data, info):
    os.makedirs(output_data, exist_ok=True)

    # FARMS
    farms_dir = os.path.join(input_data, "farms")
    farms_files = [os.path.join(farms_dir, f) for f in os.listdir(farms_dir) if f.endswith(".csv")]
    farms_df = pd.concat([pd.read_csv(f) for f in farms_files], ignore_index=True)

    connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])
    sit_codes = [d.ext_id for d in Adm3.objects() if d.ext_id]

    new_farms = farms_df[~farms_df["SIT_CODE"].isin(sit_codes)]
    total_farms = len(farms_df)
    not_found = len(new_farms)
    found = total_farms - not_found
    found_pct = (found / total_farms) * 100 if total_farms > 0 else 0

    print(f"Total SIT_CODEs en farms: {total_farms}")
    print(f"Coincidencias encontradas: {found} ({found_pct:.2f}%)")

    farms_output_path = os.path.join(output_data, "farms")
    os.makedirs(farms_output_path, exist_ok=True)
    new_farms.to_csv(os.path.join(farms_output_path, "new_farms.csv"), index=False, encoding="utf-8-sig")

    # ENTERPRISE
    enterprise_dir = os.path.join(input_data, "enterprise")
    enterprise_files = [os.path.join(enterprise_dir, f) for f in os.listdir(enterprise_dir) if f.endswith(".csv")]
    enterprise_df = pd.concat([pd.read_csv(f) for f in enterprise_files], ignore_index=True)

    # Leer archivos de texto
    cc_txt = pd.read_csv(os.path.join(info, "COLLECTION_CENTER.txt"), sep="|", encoding="latin1")
    cc_txt.columns = cc_txt.columns.str.strip().str.upper()
    if "LATITUD" in cc_txt.columns and "LONGITUD" in cc_txt.columns:
        cc_txt["LATITUD"] = cc_txt["LATITUD"].astype(str).str.replace(",", ".").astype(float)
        cc_txt["LONGITUD"] = cc_txt["LONGITUD"].astype(str).str.replace(",", ".").astype(float)

    sh_txt = pd.read_csv(os.path.join(info, "SLAUGHTERHOUSE.txt"), sep="|", encoding="latin1")
    sh_txt.columns = sh_txt.columns.str.strip().str.upper()

    cc_filter = enterprise_df["TIPO"].str.upper() == "COLLECTION_CENTER"
    merged_cc = pd.merge(
        enterprise_df[cc_filter], cc_txt,
        left_on="PRODUCTIONUNIT_ID", right_on="ID_CONCENTRACION", how="left"
    )
    merged_cc = merged_cc.rename(columns={"NOMBRE_CONCENTRACION": "NOMBRE"})
    merged_cc = merged_cc[["TIPO", "PRODUCTIONUNIT_ID", "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]]

    sh_filter = enterprise_df["TIPO"].str.upper() == "SLAUGHTERHOUSE"
    merged_sh = pd.merge(
        enterprise_df[sh_filter], sh_txt,
        left_on="PRODUCTIONUNIT_ID", right_on="ID_PLANTA_BENEFICIO", how="left"
    )
    merged_sh = merged_sh.rename(columns={"NOMBRE_PLANTA_BENEFICIO": "NOMBRE"})
    merged_sh = merged_sh[["TIPO", "PRODUCTIONUNIT_ID", "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]]

    others = enterprise_df[~(cc_filter | sh_filter)].copy()
    others["NOMBRE"] = None
    others["LATITUD"] = None
    others["LONGITUD"] = None
    others = others[["TIPO", "PRODUCTIONUNIT_ID", "ADM2", "NOMBRE", "LATITUD", "LONGITUD"]]

    new_enterprise = pd.concat([merged_cc, merged_sh, others], ignore_index=True)
    new_enterprise["NOMBRE"] = new_enterprise["NOMBRE"].astype(str).str.strip()
    new_enterprise = new_enterprise[~new_enterprise["NOMBRE"].isin(["", "nan", "None"])]
    new_enterprise = new_enterprise[~new_enterprise["NOMBRE"].str.contains("---INACTIVA---", case=False, na=False)]
    new_enterprise = new_enterprise[~new_enterprise["NOMBRE"].str.contains("^-+$", na=False)]

    # Completar coordenadas faltantes con shapefile ADM2
    new_enterprise = completar_coordenadas_con_shapefile(
        new_enterprise, output_data, workspace, store, url_geoserver, user, password
    )

    enterprise_output_path = os.path.join(output_data, "enterprise")
    os.makedirs(enterprise_output_path, exist_ok=True)
    new_enterprise.to_csv(os.path.join(enterprise_output_path, "new_enterprise.csv"), index=False, encoding="utf-8-sig")

    print("✅ Archivo new_enterprise.csv generado correctamente con coordenadas completadas.")
