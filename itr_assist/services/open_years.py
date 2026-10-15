"""Service for discovering open Assessment Years and Financial Years for Indian ITR filing."""
from datetime import date
import re
from typing import List, Tuple
import requests


def ay_to_fy(ay_str: str) -> str:
    """Convert AY string (e.g. '2026-27') to corresponding FY string ('2025-26')."""
    parts = ay_str.split("-")
    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2:
        y1 = int(parts[0]) - 1
        y2 = int(parts[1]) - 1
        return f"{y1}-{y2:02d}"
    return ay_str


def fy_to_ay(fy_str: str) -> str:
    """Convert FY string (e.g. '2025-26') to corresponding AY string ('2026-27')."""
    parts = fy_str.split("-")
    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2:
        y1 = int(parts[0]) + 1
        y2 = int(parts[1]) + 1
        return f"{y1}-{y2:02d}"
    return fy_str


def get_statutory_open_years(ref_date: date = None, max_years: int = 5) -> Tuple[List[str], List[str]]:
    """Compute legally open AYs and FYs under Section 139 based on current date.
    
    In Indian tax law, returns can only be filed for completed financial years (ending March 31).
    Includes Current Assessment Year and up to 4 preceding AYs eligible for Updated Returns u/s 139(8A).
    """
    if ref_date is None:
        ref_date = date.today()

    # If date is between 1-Apr-YYYY and 31-Dec-YYYY, the latest completed FY is (YYYY-1)-(YY),
    # and the Assessment Year currently open for filing is YYYY-(YY+1).
    # If date is between 1-Jan-YYYY and 31-Mar-YYYY, the latest completed FY is (YYYY-2)-(YY-1),
    # and the Assessment Year currently open for filing is (YYYY-1)-(YY).
    if ref_date.month >= 4:
        latest_completed_fy_start = ref_date.year - 1
    else:
        latest_completed_fy_start = ref_date.year - 2

    latest_filing_ay_start = latest_completed_fy_start + 1

    ay_list = []
    fy_list = []
    for i in range(max_years):
        ay_y1 = latest_filing_ay_start - i
        ay_y2 = (ay_y1 + 1) % 100
        ay_str = f"{ay_y1}-{ay_y2:02d}"

        fy_y1 = latest_completed_fy_start - i
        fy_y2 = (fy_y1 + 1) % 100
        fy_str = f"{fy_y1}-{fy_y2:02d}"

        ay_list.append(ay_str)
        fy_list.append(fy_str)

    return fy_list, ay_list


def _extract_valid_ays_from_html(html_text: str) -> List[str]:
    """Parse HTML and extract valid Indian Assessment Year patterns ('YYYY-YY')."""
    candidates = set(re.findall(r"(\d{4})[-–](\d{2})", html_text))
    valid = []
    for y1, y2 in candidates:
        try:
            if int(y1[2:]) + 1 == int(y2):
                valid.append(f"{y1}-{y2}")
        except ValueError:
            continue
    valid.sort(reverse=True)
    return valid


def fetch_open_assessment_years(timeout_seconds: float = 4.0) -> Tuple[List[str], List[str], str]:
    """Fetch open Assessment Years and Financial Years in descending order.
    
    Multi-tier discovery with online fallbacks:
    1. Primary: Official Income Tax e-Filing Portal (incometax.gov.in)
    2. Fallback 1: Authorized Tax Filing Portal (tax2win.in)
    3. Fallback 2: ClearTax Tax Calendar (cleartax.in)
    4. Offline Fallback: Statutory IT Act formula based on current date.
    
    Returns:
        (descending_fys, descending_ays, source_description)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Tier 1: incometax.gov.in
    try:
        resp = requests.get(
            "https://www.incometax.gov.in/iec/foportal/downloads/income-tax-returns",
            headers=headers,
            timeout=timeout_seconds,
        )
        if resp.status_code == 200:
            ays = _extract_valid_ays_from_html(resp.text)
            if ays:
                open_ays = [ay for ay in ays if int(ay[:4]) >= 2022][:5]
                open_fys = [ay_to_fy(ay) for ay in open_ays]
                return open_fys, open_ays, "Income Tax Portal (incometax.gov.in)"
    except Exception:
        pass

    # Tier 2: tax2win.in fallback
    try:
        resp = requests.get(
            "https://tax2win.in/guide/income-tax-return",
            headers=headers,
            timeout=timeout_seconds,
        )
        if resp.status_code == 200:
            ays = _extract_valid_ays_from_html(resp.text)
            if ays:
                open_ays = [ay for ay in ays if int(ay[:4]) >= 2022][:5]
                open_fys = [ay_to_fy(ay) for ay in open_ays]
                return open_fys, open_ays, "Tax Portal Fallback (tax2win.in)"
    except Exception:
        pass

    # Tier 3: cleartax.in fallback
    try:
        resp = requests.get(
            "https://cleartax.in/s/income-tax-calendar",
            headers=headers,
            timeout=timeout_seconds,
        )
        if resp.status_code == 200:
            ays = _extract_valid_ays_from_html(resp.text)
            if ays:
                open_ays = [ay for ay in ays if int(ay[:4]) >= 2022][:5]
                open_fys = [ay_to_fy(ay) for ay in open_ays]
                return open_fys, open_ays, "ClearTax Fallback (cleartax.in)"
    except Exception:
        pass

    # Tier 4: Statutory fallback based on current calendar date
    fys, ays = get_statutory_open_years()
    return fys, ays, "Statutory IT Act Rule 139 Calendar Formula"
