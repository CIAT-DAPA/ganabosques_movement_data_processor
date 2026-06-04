import sys
import pathlib
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tools.log_print import log_print


def test_log_print_levels(capsys):
    mock_logger = Mock()
    log_print(mock_logger, "info msg", level="info")
    mock_logger.info.assert_called_with("info msg")
    captured = capsys.readouterr()
    assert "info msg" in captured.out

    log_print(mock_logger, "dbg", level="debug")
    mock_logger.debug.assert_called_with("dbg")

    log_print(mock_logger, "warn", level="warning")
    mock_logger.warning.assert_called_with("warn")

    log_print(mock_logger, "err", level="error")
    mock_logger.error.assert_called_with("err")

    log_print(mock_logger, "crit", level="critical")
    mock_logger.critical.assert_called_with("crit")
