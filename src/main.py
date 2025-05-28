import logging
import os
import argparse

from get_data_sigma import get_sigma
from quality_control_movement import mov_quality_control
from calculate_movement import calc_mov
from check_farms_enterprise import check
from tools.log_print import log_print
from save_movement.save_movement import save_movements
from config import config


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

        # Paso 1: Obtener datos
        log_print(logger, "Paso 1: Obtener datos...")
        get_sigma(
            path_input=raw_input_path,
            path_output=output_path_get_data
        )

        # Paso 2: Validación de calidad
        log_print(logger, "Paso 2: Validación de calidad...")
        mov_quality_control( path_input=output_path_get_data, path_output=output_path_quality)

        # Paso 3: Calcular movimientos
        log_print(logger, "Paso 3: Calcular movimientos...")
        calc_mov(
            path_input=output_path_quality,
            path_output=output_path_calc_mov
        )

        # Paso 4: Chequear resultados
        log_print(logger, "Paso 4: chequear resultados...")
        check(
            path_predio=raw_input_path,
            path_mov=output_path_calc_mov,
            path_output=output_path_check
        )

        # Paso 5: Chequear resultados
        log_print(logger, "Paso 5: Guardar movimientos...")
        save_movements(output_path_calc_mov, output_path_save )
        
        log_print(logger, "Proceso finalizado correctamente.")

    except Exception as e:
        log_print(logger, f"Error general en el proceso: {e}", level="error")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de procesamiento de datos de movilización.")
    
    main() 