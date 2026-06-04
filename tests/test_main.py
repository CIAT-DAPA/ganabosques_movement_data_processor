import sys
import pathlib
from unittest.mock import patch
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import main

@pytest.fixture(autouse=True)
def mock_config():
    with patch("main.config", {
        "WORKSPACE": "/tmp/workspace",
        "DATA": "/tmp/data"
    }):
        yield


def test_main_function_exists():
    assert callable(main.main)


def test_main_with_all_steps():
    with patch("main.get_sigma") as mock_get_sigma, patch(
        "main.mov_quality_control"
    ) as mock_qc, patch("main.calc_mov") as mock_calc, patch(
        "main.check"
    ) as mock_check, patch(
        "main.save_movements"
    ) as mock_save:

        main.main(selected_steps=[1, 2, 3, 4, 5], source="SIGMA")

        assert mock_get_sigma.called
        assert mock_qc.called
        assert mock_calc.called
        assert mock_check.called
        assert mock_save.called


def test_main_with_specific_steps():
    with patch("main.get_sigma") as mock_get_sigma, patch(
        "main.mov_quality_control"
    ) as mock_qc, patch("main.calc_mov") as mock_calc, patch(
        "main.check"
    ) as mock_check, patch(
        "main.save_movements"
    ) as mock_save:

        main.main(selected_steps=[2, 3], source="SIGMA")

        assert not mock_get_sigma.called
        assert mock_qc.called
        assert mock_calc.called
        assert not mock_check.called
        assert not mock_save.called


def test_main_with_none_selected_steps():
    with patch("main.get_sigma") as mock_get_sigma, patch(
        "main.mov_quality_control"
    ) as mock_qc, patch("main.calc_mov") as mock_calc, patch(
        "main.check"
    ) as mock_check, patch(
        "main.save_movements"
    ) as mock_save:

        main.main(selected_steps=None, source="SIGMA")

        assert mock_get_sigma.called
        assert mock_qc.called
        assert mock_calc.called
        assert mock_check.called
        assert mock_save.called


def test_main_passes_correct_paths():
    with patch("main.get_sigma") as mock_get_sigma:

        main.main(selected_steps=[1], source="SIGMA")

        args, kwargs = mock_get_sigma.call_args

        assert "path_input" in kwargs
        assert "path_output" in kwargs


def test_main_error_handling():
    with patch("main.get_sigma", side_effect=Exception("Test error")), patch(
        "main.log_print"
    ):

        with pytest.raises(Exception, match="Test error"):
            main.main(selected_steps=[1], source="SIGMA")


def test_main_with_different_sources():
    for source in ["SIGMA", "SINIGAN"]:

        with patch("main.get_sigma"), patch("main.mov_quality_control"), patch(
            "main.calc_mov"
        ), patch("main.check"), patch("main.save_movements") as mock_save:

            main.main(selected_steps=[5], source=source)

            assert mock_save.called


def test_main_step_order():
    execution_order = []

    def step1(*args, **kwargs):
        execution_order.append(1)

    def step2(*args, **kwargs):
        execution_order.append(2)

    def step3(*args, **kwargs):
        execution_order.append(3)

    with patch("main.get_sigma", side_effect=step1), patch(
        "main.mov_quality_control", side_effect=step2
    ), patch("main.calc_mov", side_effect=step3):

        main.main(selected_steps=[1, 2, 3], source="SIGMA")

        assert execution_order == [1, 2, 3]


def test_mov_quality_control_receives_correct_args():
    paths = main.build_paths()

    with patch("main.mov_quality_control") as mock_qc:

        main.main(selected_steps=[2], source="SIGMA")

        mock_qc.assert_called_once_with(
            path_input=paths["output_path_get_data"],
            path_output=paths["output_path_quality"],
            source="SIGMA",
        )


def test_calc_mov_receives_correct_args():
    paths = main.build_paths()

    with patch("main.calc_mov") as mock_calc:

        main.main(selected_steps=[3], source="SIGMA")

        mock_calc.assert_called_once_with(
            path_input=paths["output_path_quality"],
            path_output=paths["output_path_calc_mov"],
            source="SIGMA",
        )


def test_check_receives_correct_args():
    paths = main.build_paths()

    with patch("main.check") as mock_check:

        main.main(selected_steps=[4], source="SIGMA")

        mock_check.assert_called_once_with(
            info=paths["info"],
            input_data=paths["output_path_calc_mov"],
            output_data=paths["output_path_check"],
        )


def test_save_movements_receives_correct_args():
    paths = main.build_paths()

    with patch("main.save_movements") as mock_save:

        main.main(selected_steps=[5], source="SIGMA")

        mock_save.assert_called_once_with(
            paths["output_path_calc_mov"],
            paths["output_path_save"],
            paths["output_path_check"],
            "SIGMA",
        )


def test_logs_start_and_finish():
    with patch("main.log_print") as mock_log:

        main.main(selected_steps=[])

        messages = [
            str(call.args[1]) for call in mock_log.call_args_list if len(call.args) > 1
        ]

        assert any("Iniciando pipeline" in m for m in messages)
        assert any("Proceso finalizado correctamente" in m for m in messages)


def test_logs_each_step():
    with patch("main.log_print") as mock_log, patch("main.get_sigma"), patch(
        "main.mov_quality_control"
    ), patch("main.calc_mov"):

        main.main(selected_steps=[1, 2, 3], source="SIGMA")

        messages = [str(c.args[1]) for c in mock_log.call_args_list if len(c.args) > 1]

        assert any("Paso 1" in m for m in messages)
        assert any("Paso 2" in m for m in messages)
        assert any("Paso 3" in m for m in messages)


def test_pipeline_stops_after_error():
    with patch("main.get_sigma"), patch("main.mov_quality_control") as mock_qc, patch(
        "main.calc_mov"
    ) as mock_calc:

        mock_qc.side_effect = Exception("boom")

        with pytest.raises(Exception):
            main.main(selected_steps=[1, 2, 3], source="SIGMA")

        assert not mock_calc.called


def test_error_is_logged():
    with patch("main.get_sigma", side_effect=Exception("boom")), patch(
        "main.log_print"
    ) as mock_log:

        with pytest.raises(Exception):
            main.main(selected_steps=[1], source="SIGMA")

        messages = [str(c.args[1]) for c in mock_log.call_args_list if len(c.args) > 1]

        assert any("Error general en el proceso" in m for m in messages)


def test_empty_selected_steps_runs_no_process():
    with patch("main.get_sigma") as mock_get_sigma, patch(
        "main.mov_quality_control"
    ) as mock_qc, patch("main.calc_mov") as mock_calc, patch(
        "main.check"
    ) as mock_check, patch(
        "main.save_movements"
    ) as mock_save:

        main.main(selected_steps=[], source="SIGMA")

        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert not mock_check.called
        assert not mock_save.called


def test_invalid_selected_step_runs_nothing():
    with patch("main.get_sigma") as mock_get_sigma, patch(
        "main.mov_quality_control"
    ) as mock_qc, patch("main.calc_mov") as mock_calc, patch(
        "main.check"
    ) as mock_check, patch(
        "main.save_movements"
    ) as mock_save:

        main.main(selected_steps=[99], source="SIGMA")

        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert not mock_check.called
        assert not mock_save.called


def test_duplicate_steps_execute_only_once():
    with patch("main.get_sigma") as mock_get_sigma:

        main.main(selected_steps=[1, 1, 1], source="SIGMA")

        assert mock_get_sigma.call_count == 1


def test_only_step_4_runs():
    with patch("main.get_sigma") as mock_get_sigma, patch(
        "main.mov_quality_control"
    ) as mock_qc, patch("main.calc_mov") as mock_calc, patch(
        "main.check"
    ) as mock_check, patch(
        "main.save_movements"
    ) as mock_save:

        main.main(selected_steps=[4], source="SIGMA")

        assert mock_check.called
        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert not mock_save.called


def test_only_step_5_runs():
    with patch("main.get_sigma") as mock_get_sigma, patch(
        "main.mov_quality_control"
    ) as mock_qc, patch("main.calc_mov") as mock_calc, patch(
        "main.check"
    ) as mock_check, patch(
        "main.save_movements"
    ) as mock_save:

        main.main(selected_steps=[5], source="SIGMA")

        assert mock_save.called
        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert not mock_check.called
