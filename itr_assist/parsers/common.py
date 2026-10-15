"""Common parser utilities for date and currency parsing."""
from datetime import date, datetime
from typing import Any, Optional
import pandas as pd


def parse_date(date_val: Any) -> Optional[date]:
    """Parse various date formats commonly used in financial exports."""
    if pd.isna(date_val) or date_val is None:
        return None
    if isinstance(date_val, (pd.Timestamp, datetime)):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val

    date_str = str(date_val).strip()
    if not date_str or date_str.lower() in ("nan", "none", "null", ""):
        return None

    formats = (
        "%d-%b-%Y",  # 15-AUG-2024
        "%d-%b-%y",  # 15-AUG-24
        "%m/%d/%Y",  # 08/15/2024
        "%m/%d/%y",  # 08/15/24
        "%Y-%m-%d",  # 2024-08-15
        "%d/%m/%Y",  # 15/08/2024
    )
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    return None


def clean_currency(val: Any) -> float:
    """Clean currency string or numeric value to float."""
    if pd.isna(val) or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0
