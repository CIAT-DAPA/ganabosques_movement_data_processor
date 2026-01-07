# -*- coding: utf-8 -*-
"""
Utilidades compartidas para normalización y conversión de datos.
Usadas por check_farms_enterprise.py y save_movement.py
"""
import pandas as pd


def to_clean_str(val) -> str:
    """Normaliza IDs a string comparable (quita espacios, .0, notación científica, NaNs)."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null"):
        return ""
    if s.endswith(".0"):
        try:
            s = str(int(float(s)))
        except Exception:
            pass
    try:
        if "e" in s.lower():
            n = float(s)
            s = str(int(n)) if n.is_integer() else str(n)
    except Exception:
        pass
    return s


def to_float_series(col: pd.Series) -> pd.Series:
    """
    Convierte una serie a float de forma tolerante:
    - Trim, elimina NBSP y separadores comunes
    - Soporta coma decimal y miles mezclados ('.' y ',')
    - Convierte '', '-', 'nan', 'none', 'null' a NaN
    """
    s = col.astype(str).str.strip().str.replace("\u00A0", "", regex=False)  # NBSP
    s = s.replace(
        {"": pd.NA, "-": pd.NA, "—": pd.NA, "--": pd.NA,
         "nan": pd.NA, "NaN": pd.NA, "NONE": pd.NA, "None": pd.NA, "null": pd.NA, "NULL": pd.NA}
    )

    def _norm(x: str) -> str:
        if x is pd.NA or x is None:
            return x
        x = str(x)
        x = x.replace(" ", "").replace("'", "")  # miles como espacio/apóstrofo
        # Solo comas -> coma decimal
        if ("," in x) and ("." not in x):
            x = x.replace(",", ".")
        # Ambos separadores: decide por última aparición
        elif ("," in x) and ("." in x):
            if x.rfind(",") > x.rfind("."):
                x = x.replace(".", "").replace(",", ".")  # punto miles, coma decimal
            else:
                x = x.replace(",", "")  # coma miles, punto decimal
        return x

    s = s.map(_norm)
    return pd.to_numeric(s, errors="coerce")
