"""Unit tests for Open Years Discovery Service."""
from datetime import date
import pytest

from itr_assist.services.open_years import (
    _extract_valid_ays_from_html,
    ay_to_fy,
    fetch_open_assessment_years,
    fy_to_ay,
    get_statutory_open_years,
)


def test_ay_to_fy_conversion():
    assert ay_to_fy("2026-27") == "2025-26"
    assert ay_to_fy("2025-26") == "2024-25"
    assert ay_to_fy("2024-25") == "2023-24"
    assert ay_to_fy("invalid") == "invalid"


def test_fy_to_ay_conversion():
    assert fy_to_ay("2025-26") == "2026-27"
    assert fy_to_ay("2024-25") == "2025-26"
    assert fy_to_ay("2023-24") == "2024-25"
    assert fy_to_ay("invalid") == "invalid"


def test_get_statutory_open_years_descending():
    ref_date = date(2026, 7, 15)  # In FY 2026-27 / AY 2027-28 or FY 2025-26 / AY 2026-27
    fys, ays = get_statutory_open_years(ref_date=ref_date, max_years=5)

    assert len(fys) == 5
    assert len(ays) == 5
    # Verify strictly descending order
    assert fys == sorted(fys, reverse=True)
    assert ays == sorted(ays, reverse=True)


def test_extract_valid_ays_from_html():
    html_sample = """
    <div>Downloads for AY 2026-27 and AY 2025-26</div>
    <div>Circular 2026-09 is not an AY</div>
    <div>Prior year AY 2024-25 and 2023-24</div>
    """
    extracted = _extract_valid_ays_from_html(html_sample)
    assert "2026-27" in extracted
    assert "2025-26" in extracted
    assert "2024-25" in extracted
    assert "2023-24" in extracted
    assert "2026-09" not in extracted


def test_fetch_open_assessment_years():
    fys, ays, src = fetch_open_assessment_years(timeout_seconds=4.0)
    assert len(fys) >= 3
    assert len(ays) >= 3
    assert fys == sorted(fys, reverse=True)
    assert ays == sorted(ays, reverse=True)
    assert src != ""
