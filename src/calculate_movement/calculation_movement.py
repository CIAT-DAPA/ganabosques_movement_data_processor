import os
import pandas as pd

def calc_mov(path_input, path_output):
    os.makedirs(path_output, exist_ok=True)
    log_lines = []

    for file in os.listdir(path_input):
        if file.endswith(".csv"):
            file_path = os.path.join(path_input, file)
            try:
                df = pd.read_csv(file_path, sep=",", engine="python", encoding="utf-8")

                # Filtrar especies
                df = df[df['ESPECIE'].str.lower().isin(['bovina', 'bufalina'])]

                # Crear TIPO_MOVIMIENTO
                def limpiar(tipo):
                    if pd.isna(tipo):
                        return "desconocido"
                    return tipo.lower().split()[0]

                df['TIPO_MOVIMIENTO'] = df['TIPO_ORIGEN'].apply(limpiar) + "-" + df['TIPO_DESTINO'].apply(limpiar)

                # Guardar archivo procesado
                output_file = os.path.join(path_output, file)
                df.to_csv(output_file, index=False, encoding='utf-8-sig')

                # Generar líneas de log
                log_lines.append(f"Archivo: {file}")
                conteo = df['TIPO_MOVIMIENTO'].value_counts()
                for movimiento, count in conteo.items():
                    log_lines.append(f"  {movimiento}: {count}")
                log_lines.append("")  # línea en blanco entre archivos

            except Exception as e:
                log_lines.append(f"Error procesando {file}: {e}")
                log_lines.append("")

    # Guardar log
    log_path = os.path.join(path_output, "log_calc_mov.txt")
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("\n".join(log_lines))
