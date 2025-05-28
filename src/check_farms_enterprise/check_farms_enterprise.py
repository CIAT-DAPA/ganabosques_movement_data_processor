import os
import pandas as pd
import logging
from tools.log_print import log_print 

logger = logging.getLogger("Check farms and enterprise")

def check(path_predio, path_mov, path_output):
    log_print(logger, "🚀 Iniciando proceso de verificación de movimientos contra predios...")
    
    # ---------- 1. Predios --------------------------------------------------S
    log_print(logger, "🔍 Buscando archivo de predios...")
    predio_file = next((f for f in os.listdir(path_predio) if f.endswith(".csv")), None)
    if predio_file is None:
        log_print(logger, "❌ No se encontró archivo CSV en el directorio de predios.")
        return

    predio_path = os.path.join(path_predio, predio_file)
    log_print(logger, f"📂 Leyendo archivo de predios: {predio_file}")
    predio = pd.read_csv(predio_path, dtype=str)
    log_print(logger, f"✅ Predios cargados: {predio_file}  ({predio.shape[0]} filas)")

    predio["CODIGO_SIT"] = pd.to_numeric(predio["CODIGO_SIT"], errors="coerce")
    codigos_predio = set(predio["CODIGO_SIT"].dropna().astype(int).unique())
    log_print(logger, f"📌 Códigos de predio únicos cargados: {len(codigos_predio)}")

    # ---------- 2. Movimientos ---------------------------------------------
    log_print(logger, "🔍 Buscando archivos de movimientos...")
    mov_files = [f for f in os.listdir(path_mov) if f.endswith(".csv")]
    if not mov_files:
        log_print(logger, "❌ No se encontraron archivos CSV en el directorio de movimientos.", "warning")
        return
    log_print(logger, f"📁 Archivos de movimientos encontrados: {len(mov_files)}")

    log_coinc = []
    log_no_match = []
    no_match_acumulado = []

    for file in mov_files:
        anio = "".join(filter(str.isdigit, file))[:4]
        mov_path = os.path.join(path_mov, file)
        log_print(logger, f"\n📄 Procesando archivo de movimientos: {file} (Año detectado: {anio})")

        try:
            mov = pd.read_csv(mov_path, dtype=str)
            log_print(logger, f"   ✅ Archivo cargado ({mov.shape[0]} filas)")
        except Exception as e:
            log_print(logger, f"   ⚠️  Error leyendo {file}: {e}", "error")
            continue

        if "TIPO_MOVIMIENTO" not in mov.columns:
            log_print(logger, f"   ⚠️  {file} omitido: falta columna 'TIPO_MOVIMIENTO'", "warning")
            continue

        mov_predio = mov[mov["TIPO_MOVIMIENTO"].str.contains("farm", case=False, na=False)].copy()
        log_print(logger, f"   🔢 Registros con 'predio' en TIPO_MOVIMIENTO: {mov_predio.shape[0]}")

        mov_predio["CODIGO_SIT_ORIGEN"] = pd.to_numeric(mov_predio["CODIGO_SIT_ORIGEN"], errors="coerce")
        mov_predio["CODIGO_SIT_DESTINO"] = pd.to_numeric(mov_predio["CODIGO_SIT_DESTINO"], errors="coerce")

        origen  = set(mov_predio["CODIGO_SIT_ORIGEN"].dropna().astype(int).unique())
        destino = set(mov_predio["CODIGO_SIT_DESTINO"].dropna().astype(int).unique())

        origen_ok   = origen  & codigos_predio
        destino_ok  = destino & codigos_predio

        log_coinc.append({
            "AÑO": anio,
            "TOTAL_ORIGEN":           len(origen),
            "COINCIDENCIAS_ORIGEN":   len(origen_ok),
            "PORCENTAJE_ORIGEN":      round(len(origen_ok)/len(origen)*100, 2) if origen else 0,
            "TOTAL_DESTINO":          len(destino),
            "COINCIDENCIAS_DESTINO":  len(destino_ok),
            "PORCENTAJE_DESTINO":     round(len(destino_ok)/len(destino)*100, 2) if destino else 0
        })

        log_print(logger, f"   ✅ Coincidencias ORIGEN: {len(origen_ok)} de {len(origen)}")
        log_print(logger, f"   ✅ Coincidencias DESTINO: {len(destino_ok)} de {len(destino)}")

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
            df_anio["ANIO"] = anio
            no_match_acumulado.append(df_anio)
            log_no_match.append({"AÑO": anio, "REGISTROS_NO_COINCIDEN": df_anio.shape[0]})
            log_print(logger, f"   ⚠️  Registros no coincidentes agregados: {df_anio.shape[0]}")

    # ---------- 3. Guardar resultados --------------------------------------
    os.makedirs(path_output, exist_ok=True)

    if log_coinc:
        pd.DataFrame(log_coinc).to_csv(
            os.path.join(path_output, "log_coincidencias.csv"),
            index=False,
            encoding="utf-8-sig"
        )
        log_print(logger, "📄 Archivo log_coincidencias.csv guardado")

    if no_match_acumulado:
        df_total = pd.concat(no_match_acumulado, ignore_index=True).drop_duplicates()
        df_total.to_csv(
            os.path.join(path_output, "new_farms.csv"),
            index=False,
            encoding="utf-8-sig"
        )
        log_no_match.append({"AÑO": "TOTAL", "REGISTROS_NO_COINCIDEN": df_total.shape[0]})
        pd.DataFrame(log_no_match).to_csv(
            os.path.join(path_output, "log_no_coincidencias.csv"),
            index=False,
            encoding="utf-8-sig"
        )
        log_print(logger, f"📄 Archivo new_farms.csv guardado ({df_total.shape[0]} registros)")
        log_print(logger, "📄 Archivo log_no_coincidencias.csv guardado")

    log_print(logger, "✅ Proceso completado.")

