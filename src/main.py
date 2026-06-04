import logging
import os
import argparse

from get_data_sigma import get_sigma
from quality_control_movement import mov_quality_control
from calculate_movement import calc_mov
from tools.log_print import log_print
from save_movement.save_movement import save_movements
from config import config
from check_farms_enterprise import check
from ganabosques_orm.enums.farmsource import FarmSource


logger = logging.getLogger("main")


def build_paths():
    """
    Construye todas las rutas necesarias para el pipeline.
    Se ejecuta únicamente cuando se llama main().
    """

    workspace = config.get("WORKSPACE")
    raw_input_path = config.get("DATA")

    if not workspace:
        raise ValueError("WORKSPACE no está configurado.")

    if not raw_input_path:
        raise ValueError("DATA no está configurado.")

    base_path = os.path.join(workspace, "movilizacion")

    os.makedirs(base_path, exist_ok=True)

    return {
        "base_path": base_path,
        "raw_input_path": raw_input_path,
        "output_path_get_data": os.path.join(base_path, "1_tmp_get_sigma"),
        "output_path_quality": os.path.join(base_path, "2_tmp_mov_quality_control"),
        "output_path_calc_mov": os.path.join(base_path, "3_tmp_calc_mov"),
        "output_path_check": os.path.join(base_path, "4_new_farms"),
        "output_path_save": os.path.join(base_path, "5_save_movement"),
        "info": os.path.join(raw_input_path, "info"),
    }


def configure_logging(base_path):
    """
    Configura logging únicamente cuando el pipeline se ejecuta.
    """

    logging.basicConfig(
        filename=os.path.join(base_path, "main_pipeline.log"),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(selected_steps=None, source=None):
    try:
        paths = build_paths()

        configure_logging(paths["base_path"])

        log_print(logger, "Iniciando pipeline Movement Data Processor...")

        pasos = [
            (
                "Paso 1: Obtener datos",
                lambda: get_sigma(
                    path_input=paths["raw_input_path"],
                    path_output=paths["output_path_get_data"],
                ),
            ),
            (
                "Paso 2: Validación de calidad",
                lambda: mov_quality_control(
                    path_input=paths["output_path_get_data"],
                    path_output=paths["output_path_quality"],
                    source=source,
                ),
            ),
            (
                "Paso 3: Calcular movimientos",
                lambda: calc_mov(
                    path_input=paths["output_path_quality"],
                    path_output=paths["output_path_calc_mov"],
                    source=source,
                ),
            ),
            (
                "Paso 4: Chequear resultados",
                lambda: check(
                    info=paths["info"],
                    input_data=paths["output_path_calc_mov"],
                    output_data=paths["output_path_check"],
                ),
            ),
            (
                "Paso 5: Guardar movimientos",
                lambda: save_movements(
                    paths["output_path_calc_mov"],
                    paths["output_path_save"],
                    paths["output_path_check"],
                    source,
                ),
            ),
        ]

        for idx, (nombre, funcion) in enumerate(pasos, start=1):
            if selected_steps is None or idx in selected_steps:
                log_print(logger, nombre)
                funcion()

        log_print(logger, "Proceso finalizado correctamente.")

    except Exception as e:
        log_print(
            logger,
            f"Error general en el proceso: {e}",
            level="error",
        )
        raise


if __name__ == "__main__":

    source_valide = [
        FarmSource.SIGMA.value,
        FarmSource.SINIGAN.value,
    ]

    parser = argparse.ArgumentParser(
        description=(
            "Pipeline de procesamiento de datos de movilización ganadera.\n\n"
            "Pasos disponibles:\n"
            "  1: Obtener datos\n"
            "  2: Validación de calidad\n"
            "  3: Calcular movimientos\n"
            "  4: Chequear nuevos predios o empresas\n"
            "  5: Guardar movimientos en MongoDB\n\n"
            "Ejemplos:\n"
            "  python main.py             # Ejecuta todos los pasos\n"
            "  python main.py -p 1 3      # Ejecuta solo los pasos 1 y 3\n"
            "  python main.py -f 2        # Ejecuta desde el paso 2 en adelante\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "-p",
        "--process",
        nargs="*",
        type=int,
        help="Paso(s) específicos a ejecutar (1-5).",
    )

    parser.add_argument(
        "-f",
        "--from_step",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="Paso desde el cual ejecutar el pipeline.",
    )

    parser.add_argument(
        "-s",
        "--source",
        type=str,
        required=True,
        choices=source_valide,
        help="Código del source para procesar los movimientos.",
    )

    args = parser.parse_args()

    source = args.source

    if args.process and args.from_step:
        raise ValueError(
            "No se puede usar --process y --from_step al mismo tiempo."
        )

    if args.from_step:
        steps = list(range(args.from_step, 6))
        print(
            f"🔁 Ejecutando desde el paso {args.from_step} "
            f"en adelante: {steps}"
        )
        main(selected_steps=steps, source=source)

    elif args.process:
        steps = sorted(
            set(
                p for p in args.process
                if 1 <= p <= 5
            )
        )

        if not steps:
            raise ValueError(
                "No se especificaron pasos válidos (1-5)."
            )

        print(
            f"🔁 Ejecutando pasos seleccionados: {steps}"
        )

        main(selected_steps=steps, source=source)

    else:
        print("🔁 Ejecutando todos los pasos (1-5).")
        main(source=source)