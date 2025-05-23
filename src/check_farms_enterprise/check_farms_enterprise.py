import os
import pandas as pd


def check(path_predio, path_mov, path_output):
    # ---------- 1. Predios --------------------------------------------------
    predio_file = next((f for f in os.listdir(path_predio) if f.endswith(".csv")), None)
    if predio_file is None:
        print("❌ No se encontró archivo CSV en el directorio de predios.")
        return

    predio_path = os.path.join(path_predio, predio_file)
    predio = pd.read_csv(predio_path, dtype=str)
    print(f"✅ Predios cargados: {predio_file}  ({predio.shape[0]} filas)")

    predio["CODIGO_SIT"] = pd.to_numeric(predio["CODIGO_SIT"], errors="coerce")
    codigos_predio = set(predio["CODIGO_SIT"].dropna().astype(int).unique())

    # ---------- 2. Movimientos ---------------------------------------------
    mov_files = [f for f in os.listdir(path_mov) if f.endswith(".csv")]
    if not mov_files:
        print("❌ No se encontraron archivos CSV en el directorio de movimientos.")
        return

    log_coinc = []          # coincidencias por año
    log_no_match = []       # no-coincidencias por año
    no_match_acumulado = [] # lista de dataframes por año

    for file in mov_files:
        anio = "".join(filter(str.isdigit, file))[:4]
        mov_path = os.path.join(path_mov, file)

        try:
            mov = pd.read_csv(mov_path, dtype=str)
            print(f"  ▸ {file}  ({mov.shape[0]} filas)")
        except Exception as e:
            print(f"    ⚠️  Error leyendo {file}: {e}")
            continue

        if "TIPO_MOVIMIENTO" not in mov.columns:
            print(f"    ⚠️  {file} omitido: falta columna 'TIPO_MOVIMIENTO'")
            continue

        mov_predio = mov[mov["TIPO_MOVIMIENTO"].str.contains("predio", case=False, na=False)].copy()
        mov_predio["CODIGO_SIT_ORIGEN"] = pd.to_numeric(mov_predio["CODIGO_SIT_ORIGEN"], errors="coerce")
        mov_predio["CODIGO_SIT_DESTINO"] = pd.to_numeric(mov_predio["CODIGO_SIT_DESTINO"], errors="coerce")

        origen  = set(mov_predio["CODIGO_SIT_ORIGEN"].dropna().astype(int).unique())
        destino = set(mov_predio["CODIGO_SIT_DESTINO"].dropna().astype(int).unique())

        origen_ok   = origen  & codigos_predio
        destino_ok  = destino & codigos_predio

        # ---------- 2a. log de coincidencias --------------------------------
        log_coinc.append({
            "AÑO": anio,
            "TOTAL_ORIGEN":           len(origen),
            "COINCIDENCIAS_ORIGEN":   len(origen_ok),
            "PORCENTAJE_ORIGEN":      round(len(origen_ok)/len(origen)*100, 2) if origen else 0,
            "TOTAL_DESTINO":          len(destino),
            "COINCIDENCIAS_DESTINO":  len(destino_ok),
            "PORCENTAJE_DESTINO":     round(len(destino_ok)/len(destino)*100, 2) if destino else 0
        })

        # ---------- 2b. registros NO coincidentes ---------------------------
        sin_origen   = mov_predio[~mov_predio["CODIGO_SIT_ORIGEN"].isin(codigos_predio)].copy()
        sin_destino  = mov_predio[~mov_predio["CODIGO_SIT_DESTINO"].isin(codigos_predio)].copy()

        sin_origen["CODIGO_SIT"]  = sin_origen["CODIGO_SIT_ORIGEN"]
        sin_destino["CODIGO_SIT"] = sin_destino["CODIGO_SIT_DESTINO"]

        cols_origen  = {
            "ID_DEPARTAMENTO_ORIGEN": "ID_DEPARTAMENTO",
            "DEPARTAMENTO_ORIGEN":    "DEPARTAMENTO",
            "ID_MUNICIPIO_ORIGEN":    "ID_MUNICIPIO",
            "MUNICIPIO_ORIGEN":       "MUNICIPIO",
            "ID_VEREDA_ORIGEN":       "ID_VEREDA",
            "VEREDA_ORIGEN":          "VEREDA",
            "CODIGO_SIT":             "CODIGO_SIT"
        }
        cols_destino = {
            "ID_DEPARTAMENTO_DESTINO": "ID_DEPARTAMENTO",
            "DEPARTAMENTO_DESTINO":    "DEPARTAMENTO",
            "ID_MUNICIPIO_DESTINO":    "ID_MUNICIPIO",
            "MUNICIPIO_DESTINO":       "MUNICIPIO",
            "ID_VEREDA_DESTINO":       "ID_VEREDA",
            "VEREDA_DESTINO":          "VEREDA",
            "CODIGO_SIT":              "CODIGO_SIT"
        }

        df_origen  = sin_origen[list(cols_origen.keys())].rename(columns=cols_origen)
        df_destino = sin_destino[list(cols_destino.keys())].rename(columns=cols_destino)

        df_anio = pd.concat([df_origen, df_destino], ignore_index=True).drop_duplicates()
        if not df_anio.empty:
            df_anio["ANIO"] = anio          # nueva columna ANIO
            no_match_acumulado.append(df_anio)
            log_no_match.append({"AÑO": anio, "REGISTROS_NO_COINCIDEN": df_anio.shape[0]})

    # ---------- 3. Guardar resultados --------------------------------------
    os.makedirs(path_output, exist_ok=True)

    # 3a. log de coincidencias
    if log_coinc:
        pd.DataFrame(log_coinc).to_csv(
            os.path.join(path_output, "log_coincidencias.csv"),
            index=False,
            encoding="utf-8-sig"
        )
        print("✅ log_coincidencias.csv guardado")

    # 3b. base general de no coincidencias + log
    if no_match_acumulado:
        df_total = pd.concat(no_match_acumulado, ignore_index=True).drop_duplicates()
        df_total.to_csv(
            os.path.join(path_output, "new_farms.csv"),
            index=False,
            encoding="utf-8-sig"
        )
        # añadir línea TOTAL al log de no coincidencias
        log_no_match.append({"AÑO": "TOTAL", "REGISTROS_NO_COINCIDEN": df_total.shape[0]})
        pd.DataFrame(log_no_match).to_csv(
            os.path.join(path_output, "log_no_coincidencias.csv"),
            index=False,
            encoding="utf-8-sig"
        )
        print(f"✅ no_match_total.csv guardado ({df_total.shape[0]} registros)")
        print("✅ log_no_coincidencias.csv guardado")


