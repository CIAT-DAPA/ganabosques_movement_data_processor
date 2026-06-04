# -*- coding: utf-8 -*-
"""Comprehensive tests for data_utils module."""
import sys
import pathlib
import pandas as pd
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tools.data_utils import to_clean_str, to_float_series


# ==================== TEST: to_clean_str ====================

def test_to_clean_str_none():
    """Test None values."""
    assert to_clean_str(None) == ""


def test_to_clean_str_decimal_notation():
    """Test .0 truncation."""
    assert to_clean_str(" 123.0 ") == "123"
    assert to_clean_str("999.0") == "999"
    assert to_clean_str("0.0") == "0"
    assert to_clean_str("1.0") == "1"


def test_to_clean_str_scientific():
    """Test scientific notation conversion."""
    assert to_clean_str("1.23e3") == "1230"
    assert to_clean_str("1e2") == "100"
    assert to_clean_str("5.5e1") == "55"
    assert to_clean_str("1e0") == "1"


def test_to_clean_str_missing_literals():
    """Test missing value literals."""
    assert to_clean_str("nan") == ""
    assert to_clean_str("NaN") == ""
    assert to_clean_str("none") == ""
    assert to_clean_str("None") == ""
    assert to_clean_str("null") == ""
    assert to_clean_str("NULL") == ""


def test_to_clean_str_whitespace():
    """Test whitespace handling."""
    assert to_clean_str("  123  ") == "123"
    assert to_clean_str("\t456\n") == "456"
    assert to_clean_str("   ") == ""


def test_to_clean_str_normal_numbers():
    """Test normal string numbers."""
    assert to_clean_str("123") == "123"
    assert to_clean_str("456.789") == "456.789"
    assert to_clean_str("-100") == "-100"


def test_to_clean_str_alphanumeric():
    """Test mixed alphanumeric strings."""
    assert to_clean_str("ABC123") == "ABC123"
    assert to_clean_str("prod_001") == "prod_001"


def test_to_clean_str_float_non_zero():
    """Test floats with non-zero decimals."""
    assert to_clean_str("123.5") == "123.5"
    assert to_clean_str("999.99") == "999.99"


def test_to_clean_str_large_numbers():
    """Test large numbers."""
    assert to_clean_str("1000000") == "1000000"
    assert to_clean_str("999999999.0") == "999999999"


# ==================== TEST: to_float_series ====================

def test_to_float_series_basic():
    """Test basic decimal conversion with comma/dot separators."""
    s = pd.Series(["1,23", "1.234,56", "1,234.56", "", None, "nan", "123.0"])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 1.23)
    assert np.isclose(res.iloc[1], 1234.56)
    assert np.isclose(res.iloc[2], 1234.56)
    assert pd.isna(res.iloc[3])
    assert pd.isna(res.iloc[4])
    assert pd.isna(res.iloc[5])
    assert np.isclose(res.iloc[6], 123.0)


def test_to_float_series_missing_values():
    """Test various missing value representations."""
    s = pd.Series(["", "-", "—", "--", "nan", "NaN", "NONE", "None", "null", "NULL"])
    res = to_float_series(s)
    for val in res:
        assert pd.isna(val)


def test_to_float_series_whitespace():
    """Test whitespace handling."""
    s = pd.Series(["  1.5  ", "\t2.3\n", "  3.7  "])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 1.5)
    assert np.isclose(res.iloc[1], 2.3)
    assert np.isclose(res.iloc[2], 3.7)


def test_to_float_series_thousands_separator_space():
    """Test space as thousands separator."""
    s = pd.Series(["1 234,56", "1 000.5"])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 1234.56)
    assert np.isclose(res.iloc[1], 1000.5)


def test_to_float_series_thousands_separator_apostrophe():
    """Test apostrophe as thousands separator."""
    s = pd.Series(["1'234.56", "10'000.5"])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 1234.56)
    assert np.isclose(res.iloc[1], 10000.5)


def test_to_float_series_nbsp():
    """Test non-breaking space handling."""
    s = pd.Series(["1\u00A01,5"])  # NBSP + comma
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 11.5)


def test_to_float_series_negative():
    """Test negative numbers."""
    s = pd.Series(["-1,5", "-100.25", "-0.5"])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], -1.5)
    assert np.isclose(res.iloc[1], -100.25)
    assert np.isclose(res.iloc[2], -0.5)


def test_to_float_series_zero():
    """Test zero values."""
    s = pd.Series(["0", "0.0", "0,0"])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 0.0)
    assert np.isclose(res.iloc[1], 0.0)
    assert np.isclose(res.iloc[2], 0.0)


def test_to_float_series_large_values():
    """Test large numeric values."""
    s = pd.Series(["1000000,5", "999999.99"])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 1000000.5)
    assert np.isclose(res.iloc[1], 999999.99)


def test_to_float_series_scientific_notation():
    """Test scientific notation in series."""
    s = pd.Series(["1e3", "1.5e2", "2E-1"])
    res = to_float_series(s)
    assert np.isclose(res.iloc[0], 1000)
    assert np.isclose(res.iloc[1], 150)
    assert np.isclose(res.iloc[2], 0.2)
