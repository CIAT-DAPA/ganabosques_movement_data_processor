import logging
import os
import argparse
from tqdm import tqdm
from get_data_sigma import get_sigma
from quality_control_movement import mov_quality_control
from calculate_movement import calc_mov
from tools.log_print import log_print
from save_movement.save_movement import save_movements
from config import config
from check_farms_enterprise.check_farms_enterprise import check_farms_enterprise


logging.basicConfig(
    filename='main_pipeline.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("main")

def main():
    try:
        log_print(logger, "Iniciando pipeline Movement Data Processor...")

        # Definir rutas base y de salida
        base_path = config['WORKSPACE']
        raw_input_path = config['DATA']

        output_path_get_data = os.path.join(base_path, "movilizacion", "1_tmp_get_sigma")
        output_path_quality = os.path.join(base_path, "movilizacion", "2_tmp_mov_quality_control")
        output_path_calc_mov = os.path.join(base_path, "movilizacion", "3_tmp_calc_mov")
        output_path_check = os.path.join(base_path, "movilizacion", "4_new_farms")
        output_path_save = os.path.join(base_path, "movilizacion", "5_save_movement")
        info = r"D:\OneDrive - CGIAR\Desktop\ganabosques\test\input"
        # Lista de pasos con funciones y nombres
        pasos = [
            ("Paso 1: Obtener datos", lambda: get_sigma(path_input=raw_input_path, path_output=output_path_get_data)),
            ("Paso 2: Validación de calidad", lambda: mov_quality_control(path_input=output_path_get_data, path_output=output_path_quality)),
            ("Paso 3: Calcular movimientos", lambda: calc_mov(path_input=output_path_quality, path_output=output_path_calc_mov)),
            ("Paso 4: Chequear resultados", lambda: check_farms_enterprise(info= info, input_data=output_path_calc_mov, output_data=output_path_check)),
            ("Paso 5: Guardar movimientos", lambda: save_movements(output_path_calc_mov, output_path_save))
        ]

        # Ejecutar pasos con barra de progreso
        for nombre, funcion in tqdm(pasos, desc="Ejecución pipeline", unit="paso"):
            log_print(logger, nombre)
            funcion()

        log_print(logger, "Proceso finalizado correctamente.")

    except Exception as e:
        log_print(logger, f"Error general en el proceso: {e}", level="error")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de procesamiento de datos de movilización.")
    main()