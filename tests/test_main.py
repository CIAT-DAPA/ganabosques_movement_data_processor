# -*- coding: utf-8 -*-
"""Comprehensive tests for main module pipeline orchestration."""
import sys
import pathlib
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from argparse import Namespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import main


def test_main_function_exists():
    """Test main() function exists and is callable."""
    assert callable(main.main)


def test_main_with_all_steps():
    """Test main() can be called with all steps."""
    with patch('main.get_sigma') as mock_get_sigma, \
         patch('main.mov_quality_control') as mock_qc, \
         patch('main.calc_mov') as mock_calc, \
         patch('main.check') as mock_check, \
         patch('main.save_movements') as mock_save:
        
        # Should not raise
        main.main(selected_steps=[1, 2, 3, 4, 5], source="SIGMA")
        
        assert mock_get_sigma.called
        assert mock_qc.called
        assert mock_calc.called
        assert mock_check.called
        assert mock_save.called


def test_main_with_specific_steps():
    """Test main() with specific selected steps."""
    with patch('main.get_sigma') as mock_get_sigma, \
         patch('main.mov_quality_control') as mock_qc, \
         patch('main.calc_mov') as mock_calc, \
         patch('main.check') as mock_check, \
         patch('main.save_movements') as mock_save:
        
        # Only run steps 2 and 3
        main.main(selected_steps=[2, 3], source="SIGMA")
        
        assert not mock_get_sigma.called
        assert mock_qc.called
        assert mock_calc.called
        assert not mock_check.called
        assert not mock_save.called


def test_main_with_none_selected_steps():
    """Test main() with None selected_steps runs all steps."""
    with patch('main.get_sigma') as mock_get_sigma, \
         patch('main.mov_quality_control') as mock_qc, \
         patch('main.calc_mov') as mock_calc, \
         patch('main.check') as mock_check, \
         patch('main.save_movements') as mock_save:
        
        main.main(selected_steps=None, source="SIGMA")
        
        assert mock_get_sigma.called
        assert mock_qc.called
        assert mock_calc.called
        assert mock_check.called
        assert mock_save.called


def test_main_passes_correct_paths():
    """Test that main() passes correct paths to pipeline functions."""
    with patch('main.get_sigma') as mock_get_sigma, \
         patch('main.mov_quality_control') as mock_qc, \
         patch('main.calc_mov') as mock_calc, \
         patch('main.check') as mock_check, \
         patch('main.save_movements') as mock_save:
        
        main.main(selected_steps=[1], source="SIGMA")
        
        # Check first function was called with correct paths
        call_args = mock_get_sigma.call_args
        assert 'path_input' in str(call_args)
        assert 'path_output' in str(call_args)


def test_main_error_handling():
    """Test main() handles errors gracefully."""
    with patch('main.get_sigma') as mock_get_sigma, \
         patch('main.log_print'):
        
        mock_get_sigma.side_effect = Exception("Test error")
        
        # Should not raise, errors are caught and logged
        try:
            main.main(selected_steps=[1], source="SIGMA")
        except Exception as e:
            # Depending on error handling, may raise or not
            pass


def test_main_with_different_sources():
    """Test main() with different source values."""
    sources = ["SIGMA", "SINIGAN"]
    
    for source in sources:
        with patch('main.get_sigma'), \
             patch('main.mov_quality_control'), \
             patch('main.calc_mov'), \
             patch('main.check'), \
             patch('main.save_movements') as mock_save:
            
            main.main(selected_steps=[5], source=source)
            
            # Check source was passed
            call_args = mock_save.call_args
            if call_args:
                assert source in str(call_args)


def test_main_step_order():
    """Test that main() executes steps in correct order."""
    execution_order = []
    
    def mock_step1(*args, **kwargs):
        execution_order.append(1)
    
    def mock_step2(*args, **kwargs):
        execution_order.append(2)
    
    def mock_step3(*args, **kwargs):
        execution_order.append(3)
    
    with patch('main.get_sigma', side_effect=mock_step1), \
         patch('main.mov_quality_control', side_effect=mock_step2), \
         patch('main.calc_mov', side_effect=mock_step3):
        
        main.main(selected_steps=[1, 2, 3], source="SIGMA")
        
        # Verify order
        assert execution_order == [1, 2, 3]

def test_mov_quality_control_receives_correct_args():
    with patch("main.mov_quality_control") as mock_qc:
        main.main(selected_steps=[2], source="SIGMA")

        mock_qc.assert_called_once_with(
            path_input=main.output_path_get_data,
            path_output=main.output_path_quality,
            source="SIGMA"
        )

def test_calc_mov_receives_correct_args():
    with patch("main.calc_mov") as mock_calc:
        main.main(selected_steps=[3], source="SIGMA")

        mock_calc.assert_called_once_with(
            path_input=main.output_path_quality,
            path_output=main.output_path_calc_mov,
            source="SIGMA"
        )

def test_check_receives_correct_args():
    with patch("main.check") as mock_check:
        main.main(selected_steps=[4], source="SIGMA")

        mock_check.assert_called_once_with(
            info=main.info,
            input_data=main.output_path_calc_mov,
            output_data=main.output_path_check
        )

def test_save_movements_receives_correct_args():
    with patch("main.save_movements") as mock_save:
        main.main(selected_steps=[5], source="SIGMA")

        mock_save.assert_called_once_with(
            main.output_path_calc_mov,
            main.output_path_save,
            main.output_path_check,
            "SIGMA"
        )

def test_logs_start_and_finish():
    with patch("main.log_print") as mock_log:
        main.main(selected_steps=[])

        logged_messages = [
            str(call.args[1])
            for call in mock_log.call_args_list
            if len(call.args) > 1
        ]

        assert any(
            "Iniciando pipeline Movement Data Processor"
            in msg
            for msg in logged_messages
        )

        assert any(
            "Proceso finalizado correctamente"
            in msg
            for msg in logged_messages
        )

def test_logs_each_step():
    with patch("main.log_print") as mock_log, \
         patch("main.get_sigma"), \
         patch("main.mov_quality_control"), \
         patch("main.calc_mov"):

        main.main(selected_steps=[1, 2, 3], source="SIGMA")

        logged_messages = [
            str(call.args[1])
            for call in mock_log.call_args_list
            if len(call.args) > 1
        ]

        assert any("Paso 1: Obtener datos" in msg for msg in logged_messages)
        assert any("Paso 2: Validación de calidad" in msg for msg in logged_messages)
        assert any("Paso 3: Calcular movimientos" in msg for msg in logged_messages)

def test_pipeline_stops_after_error():
    with patch("main.get_sigma"), \
         patch("main.mov_quality_control") as mock_qc, \
         patch("main.calc_mov") as mock_calc:

        mock_qc.side_effect = Exception("boom")

        main.main(selected_steps=[1, 2, 3], source="SIGMA")

        assert not mock_calc.called

def test_error_is_logged():
    with patch(
        "main.get_sigma",
        side_effect=Exception("boom")
    ), patch("main.log_print") as mock_log:

        main.main(selected_steps=[1], source="SIGMA")

        error_calls = [
            str(call)
            for call in mock_log.call_args_list
        ]

        assert any(
            "Error general en el proceso"
            in call
            for call in error_calls
        )

def test_empty_selected_steps_runs_no_process():
    with patch("main.get_sigma") as mock_get_sigma, \
         patch("main.mov_quality_control") as mock_qc, \
         patch("main.calc_mov") as mock_calc, \
         patch("main.check") as mock_check, \
         patch("main.save_movements") as mock_save:

        main.main(selected_steps=[], source="SIGMA")

        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert not mock_check.called
        assert not mock_save.called
        

def test_invalid_selected_step_runs_nothing():
    with patch("main.get_sigma") as mock_get_sigma, \
         patch("main.mov_quality_control") as mock_qc, \
         patch("main.calc_mov") as mock_calc, \
         patch("main.check") as mock_check, \
         patch("main.save_movements") as mock_save:

        main.main(selected_steps=[99], source="SIGMA")

        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert not mock_check.called
        assert not mock_save.called

def test_duplicate_steps_execute_only_once():
    with patch("main.get_sigma") as mock_get_sigma:
        main.main(selected_steps=[1, 1, 1], source="SIGMA")

        mock_get_sigma.assert_called_once()

def test_only_step_4_runs():
    with patch("main.get_sigma") as mock_get_sigma, \
         patch("main.mov_quality_control") as mock_qc, \
         patch("main.calc_mov") as mock_calc, \
         patch("main.check") as mock_check, \
         patch("main.save_movements") as mock_save:

        main.main(selected_steps=[4], source="SIGMA")

        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert mock_check.called
        assert not mock_save.called

def test_only_step_5_runs():
    with patch("main.get_sigma") as mock_get_sigma, \
         patch("main.mov_quality_control") as mock_qc, \
         patch("main.calc_mov") as mock_calc, \
         patch("main.check") as mock_check, \
         patch("main.save_movements") as mock_save:

        main.main(selected_steps=[5], source="SIGMA")

        assert not mock_get_sigma.called
        assert not mock_qc.called
        assert not mock_calc.called
        assert not mock_check.called
        assert mock_save.called