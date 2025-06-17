import os
import pandas as pd
from mongoengine import connect
from ganabosques_orm.collections.adm3 import Adm3
from config import config


def check_farms_enterprise(input_data, output_data, info):
    os.makedirs(output_data, exist_ok=True)

    # ===================== FARMS =====================
    farms_dir = os.path.join(input_data, "farms")
    farms_files = [os.path.join(farms_dir, f) for f in os.listdir(farms_dir) if f.endswith(".csv")]

    farms_df = pd.concat([pd.read_csv(f) for f in farms_files], ignore_index=True)
    connect(db=config['MONGO_DB_NAME'], host=config['MONGO_URI'])

    sit_codes = [d.ext_id for d in Adm3.objects() if d.ext_id]
    print("Head de sit_codes:", sit_codes[:5])

    new_farms = farms_df[~farms_df["SIT_CODE"].isin(sit_codes)]

    total_farms = len(farms_df)
    not_found = len(new_farms)
    found = total_farms - not_found
    found_pct = (found / total_farms) * 100 if total_farms > 0 else 0

    print(f"Total SIT_CODEs en farms: {total_farms}")
    print(f"Coincidencias encontradas en base de datos: {found}")
    print(f"No encontradas (nuevas): {not_found}")
    print(f"Porcentaje encontrado: {found_pct:.2f}%")


    farms_output_path = os.path.join(output_data, "farms")
    os.makedirs(farms_output_path, exist_ok=True)
    new_farms.to_csv(os.path.join(farms_output_path, "new_farms.csv"), index=False, encoding="utf-8-sig")

    # ===================== ENTERPRISE =====================
    enterprise_dir = os.path.join(input_data, "enterprise")
    enterprise_files = [os.path.join(enterprise_dir, f) for f in os.listdir(enterprise_dir) if f.endswith(".csv")]

    enterprise_df = pd.concat([pd.read_csv(f) for f in enterprise_files], ignore_index=True)

    # Leer COLLECTION_CENTER.txt y SLAUGHTERHOUSE.txt
    cc_txt = pd.read_csv(os.path.join(info, "COLLECTION_CENTER.txt"), sep="|", encoding="latin1")
    cc_txt.columns = cc_txt.columns.str.strip().str.upper()

    # Reemplazar coma por punto en columnas de latitud/longitud y convertir a float
    if "LATITUD" in cc_txt.columns and "LONGITUD" in cc_txt.columns:
        cc_txt["LATITUD"] = cc_txt["LATITUD"].astype(str).str.replace(",", ".").astype(float)
        cc_txt["LONGITUD"] = cc_txt["LONGITUD"].astype(str).str.replace(",", ".").astype(float)

    sh_txt = pd.read_csv(os.path.join(info, "SLAUGHTERHOUSE.txt"), sep="|", encoding="latin1")
    sh_txt.columns = sh_txt.columns.str.strip().str.upper()

    print("Columnas en cc_txt:", cc_txt.columns.tolist())

    # Merge para COLLECTION_CENTER
    cc_filter = enterprise_df["TIPO"].str.upper() == "COLLECTION_CENTER"
    merged_cc = pd.merge(
        enterprise_df[cc_filter],
        cc_txt,
        how="left",
        left_on="PRODUCTIONUNIT_ID",
        right_on="ID_CONCENTRACION"
    )[
        enterprise_df.columns.tolist() + ["NOMBRE_CONCENTRACION", "LATITUD", "LONGITUD"]
    ]

    # Merge para SLAUGHTERHOUSE
    sh_filter = enterprise_df["TIPO"].str.upper() == "SLAUGHTERHOUSE"
    merged_sh = pd.merge(
        enterprise_df[sh_filter],
        sh_txt,
        how="left",
        left_on="PRODUCTIONUNIT_ID",
        right_on="ID_PLANTA_BENEFICIO"
    )[
        enterprise_df.columns.tolist() + ["NOMBRE_PLANTA_BENEFICIO", "LATITUD", "LONGITUD"]
    ]

    others = enterprise_df[~(cc_filter | sh_filter)]
    new_enterprise = pd.concat([merged_cc, merged_sh, others], ignore_index=True)

    enterprise_output_path = os.path.join(output_data, "enterprise")
    os.makedirs(enterprise_output_path, exist_ok=True)

    # Guardar todo
    new_enterprise.to_csv(os.path.join(enterprise_output_path, "new_enterprise.csv"), index=False, encoding="utf-8-sig")

    # Guardar CC y SH por separado
    merged_cc.to_csv(os.path.join(enterprise_output_path, "new_collection_center.csv"), index=False, encoding="utf-8-sig")
    merged_sh.to_csv(os.path.join(enterprise_output_path, "new_slaughterhouse.csv"), index=False, encoding="utf-8-sig")
    print("Archivos separados guardados por tipo de empresa.")


#input_data = r"D:\OneDrive - CGIAR\Desktop\ganabosques\test\test_mov\movilizacion\3_tmp_calc_mov"
#output_data = r"D:\OneDrive - CGIAR\Desktop\ganabosques\test\test_mov\movilizacion\4_tmp_check_farms_enterprice"
#info = r"D:\OneDrive - CGIAR\Desktop\ganabosques\test\input"
#check_farms_enterprise(input_data, output_data, info)
