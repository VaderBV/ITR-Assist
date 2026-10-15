"""Unit tests for the ITR Assist GUI."""
from datetime import date
import gc
import os
import tkinter as tk
from unittest.mock import MagicMock, patch
import pytest

from itr_assist.gui import ITRAssistGUI
from itr_assist.services.valuation import (
    DividendTaxResult,
    FTCResult,
    ScheduleFATableA2Result,
    ScheduleFATableA3LotResult,
    ScheduleOSResult,
)


@pytest.fixture(scope="module")
def tk_root():
    """Module-level Tk root to avoid multiple Tcl interpreter initializations."""
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.update_idletasks()
        root.destroy()
    except Exception:
        pass
    gc.collect()


@pytest.fixture
def gui_app(tk_root):
    """Fixture providing a hidden Toplevel window and ITRAssistGUI instance."""
    win = tk.Toplevel(tk_root)
    win.withdraw()
    app = ITRAssistGUI(win, auto_discover_years=False)
    yield app
    try:
        # Disassociate Tkinter variables so their __del__ doesn't attempt
        # to invoke Tcl calls after the widget/interpreter is destroyed
        for attr_name in dir(app):
            attr = getattr(app, attr_name, None)
            if isinstance(attr, tk.Variable):
                attr._tk = None
        win.destroy()
    except Exception:
        pass


def test_gui_initial_state(gui_app: ITRAssistGUI):
    """Test initial state of inputs and widgets."""
    assert gui_app.var_ay.get() == "2026-27"
    assert gui_app.var_fy.get() == "2025-26"
    assert gui_app.var_pan.get() == ""
    assert gui_app.var_benefit_history.get() == ""
    assert gui_app.var_holdings.get() == ""
    assert gui_app.var_stmt_cy.get() == ""
    assert gui_app.var_stmt_fy.get() == ""
    assert gui_app.var_tax_doc.get() == ""
    assert str(gui_app.btn_generate["state"]) == "normal"
    assert str(gui_app.btn_open_excel["state"]) == "disabled"
    assert len(gui_app.kpi_tree.get_children()) == 0
    assert len(gui_app.a3_tree.get_children()) == 0
    assert len(gui_app.os_tree.get_children()) == 0


def test_gui_descending_open_years(gui_app: ITRAssistGUI):
    """Test that open FYs and AYs are in strictly descending order."""
    fys = list(gui_app.fy_combo["values"])
    ays = list(gui_app.ay_combo["values"])

    assert len(fys) >= 3
    assert len(ays) >= 3
    assert fys == sorted(fys, reverse=True), f"FY options not in descending order: {fys}"
    assert ays == sorted(ays, reverse=True), f"AY options not in descending order: {ays}"


def test_gui_individual_file_inputs(gui_app: ITRAssistGUI):
    """Test that all 5 required file paths are managed individually."""
    gui_app.var_benefit_history.set("BenefitHistory.xlsx")
    gui_app.var_holdings.set("ByStatus_expanded.xlsx")
    gui_app.var_stmt_cy.set("ClientStatements_2025.pdf")
    gui_app.var_stmt_fy.set("ClientStatements_Jan-March26.pdf")
    gui_app.var_tax_doc.set("TaxDocuments_7420_022626.pdf")

    assert "BenefitHistory" in gui_app.var_benefit_history.get()
    assert "ByStatus_expanded" in gui_app.var_holdings.get()
    assert "ClientStatements_2025" in gui_app.var_stmt_cy.get()
    assert "ClientStatements_Jan-March26" in gui_app.var_stmt_fy.get()
    assert "TaxDocuments_7420" in gui_app.var_tax_doc.get()


def test_gui_fy_ay_auto_sync(gui_app: ITRAssistGUI):
    """Test selecting an FY automatically updates AY and vice-versa."""
    gui_app.var_fy.set("2024-25")
    gui_app._on_fy_selected()
    assert gui_app.var_ay.get() == "2025-26"
    assert "AY2025-26" in gui_app.var_output.get()

    gui_app.var_ay.set("2023-24")
    gui_app._on_ay_selected()
    assert gui_app.var_fy.get() == "2022-23"
    assert "AY2023-24" in gui_app.var_output.get()

    # Reset
    gui_app.var_fy.set("2025-26")
    gui_app._on_fy_selected()


def test_gui_logging(gui_app: ITRAssistGUI):
    """Test log appending."""
    gui_app._log("Test message line 1")
    gui_app._log("Test message line 2")
    log_content = gui_app.log_text.get("1.0", tk.END)
    assert "Test message line 1" in log_content
    assert "Test message line 2" in log_content


def test_gui_generation_success_callback(gui_app: ITRAssistGUI):
    """Test GUI updates correctly when generation finishes successfully."""
    a2_dummy = ScheduleFATableA2Result(
        country_name="United States",
        country_code="2",
        financial_inst_name="E*TRADE",
        financial_inst_address="PO BOX 484, Jersey City, NJ 07303",
        zip_code="07303",
        account_number="7420",
        status="Beneficial Owner",
        account_open_date="2023-01-01",
        peak_balance_usd=4376.16,
        peak_balance_inr=396463,
        peak_date=date(2025, 12, 16),
        peak_rate_inr=90.596,
        closing_balance_usd=4033.00,
        closing_balance_inr=360844,
        closing_date=date(2025, 12, 31),
        closing_rate_inr=89.473,
        gross_amount_paid_credited_inr=6174,
        nature_of_amount="Gross Dividends",
    )

    a3_dummy = [
        ScheduleFATableA3LotResult(
            lot_id="ACME-ESPP-20240603",
            country_name="United States",
            country_code="2",
            name_of_entity="Acme Technologies Inc.",
            address_of_entity="100 Innovation Way, San Jose, CA 95110",
            zip_code="95110",
            nature_of_entity="Listed Company",
            acquisition_date=date(2024, 6, 3),
            gross_shares=6.0,
            net_shares=6.0,
            vest_fmv_usd=98.37,
            acq_sbi_rate_inr=83.10,
            initial_value_inr=49046,
            peak_balance_inr=49284,
            peak_date=date(2025, 12, 16),
            peak_price_usd=90.68,
            peak_rate_inr=90.596,
            closing_balance_inr=39780,
            closing_date=date(2025, 12, 31),
            closing_price_usd=74.12,
            closing_rate_inr=89.473,
            gross_dividends_usd=10.92,
            gross_dividends_inr=956,
            gross_proceeds_inr=0,
            is_sold_lot=True,
            initial_cost_usd=590.22,
            peak_balance_usd=544.08,
            closing_balance_usd=444.72,
        )
    ]

    div_item = DividendTaxResult(
        pay_date=date(2025, 6, 6),
        symbol="ACME",
        gross_usd=13.0,
        tax_usd=3.25,
        preceding_month_end=date(2025, 5, 30),
        rule_115_rate=85.00,
        gross_inr=1105,
        rule_128_rate=85.20,
        tax_inr=277,
        advance_tax_bucket="Upto 15-Jun",
        source_document="sample_client_statements.pdf",
    )

    os_dummy = ScheduleOSResult(
        total_dividend_inr=1105,
        upto_15_jun_inr=1105,
        upto_15_sep_inr=0,
        upto_15_dec_inr=0,
        upto_15_mar_inr=0,
        upto_31_mar_inr=0,
        items=[div_item],
    )

    ftc_dummy = FTCResult(
        country_name="United States",
        country_code="2",
        head_of_income="Income from Other Sources",
        source_of_income="Dividends",
        dtaa_article="Article 10",
        gross_foreign_income_inr=1105,
        foreign_tax_paid_inr=277,
        estimated_indian_tax_inr=277,
        tax_relief_claimed_inr=277,
        gross_foreign_income_usd=13.0,
        foreign_tax_paid_usd=3.25,
        tax_relief_claimed_usd=3.25,
    )

    gui_app.last_generated_file = "test_output.xlsx"

    with patch("tkinter.messagebox.showinfo") as mock_info:
        gui_app._on_generation_success(a2_dummy, a3_dummy, os_dummy, ftc_dummy)
        mock_info.assert_called_once()

    # Verify buttons and status
    assert str(gui_app.btn_open_excel["state"]) == "normal"
    assert "Completed successfully" in gui_app.var_status.get()

    # Verify populated rows
    assert len(gui_app.kpi_tree.get_children()) == 6
    assert len(gui_app.a3_tree.get_children()) == 1
    assert len(gui_app.os_tree.get_children()) == 1

    # Check sold lot label in A3 Tree (last column 15)
    a3_values = gui_app.a3_tree.item(gui_app.a3_tree.get_children()[0])["values"]
    assert "ACME-ESPP-20240603" in str(a3_values[0])
    assert "YES (Sold 2026)" in str(a3_values[15])


def test_gui_generation_error_callback(gui_app: ITRAssistGUI):
    """Test GUI updates correctly when generation encounters an error."""
    with patch("tkinter.messagebox.showerror") as mock_err:
        gui_app._on_generation_error("File not found")
        mock_err.assert_called_once()

    assert str(gui_app.btn_generate["state"]) == "normal"
    assert "Error occurred" in gui_app.var_status.get()
