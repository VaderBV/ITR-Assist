"""Fully synthetic end-to-end integration test verifying the entire pipeline without local private data."""
import calendar
from datetime import date
import os
import tempfile
import openpyxl
import pytest

from itr_assist.models import (
    DividendEvent,
    Form1042SData,
    LotStatus,
    PlanType,
    ShareLot,
    StatementPeriodSummary,
)
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.reconciliation.verifier import DocumentVerifier
from itr_assist.reports.excel_generator import ITRWorkbookGenerator
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import ValuationEngine
from itr_assist.validation import RuleStatus, ValidationEngine


@pytest.fixture
def synthetic_data():
    """Create a completely self-contained, synthetic dataset."""
    # 1. Historical Lots: 2 Active lots + 1 Sold lot (sold in CY 2025)
    lot1 = ShareLot(
        lot_id="ACME-RSU-G100-T1-20240515",
        symbol="ACME",
        plan_type=PlanType.RSU,
        acquisition_date=date(2024, 5, 15),
        gross_shares=15.0,
        withheld_shares=5.0,
        net_shares=10.0,
        vest_fmv_usd=100.0,
        cost_basis_per_share_usd=100.0,
        remaining_shares=10.0,
        status=LotStatus.ACTIVE,
        grant_number="G100",
    )
    lot2 = ShareLot(
        lot_id="ACME-ESPP-20240603",
        symbol="ACME",
        plan_type=PlanType.ESPP,
        acquisition_date=date(2024, 6, 3),
        gross_shares=5.0,
        withheld_shares=0.0,
        net_shares=5.0,
        vest_fmv_usd=80.0,
        cost_basis_per_share_usd=80.0,
        remaining_shares=5.0,
        status=LotStatus.ACTIVE,
    )
    sold_lot = ShareLot(
        lot_id="ACME-ESPP-20231201",
        symbol="ACME",
        plan_type=PlanType.ESPP,
        acquisition_date=date(2023, 12, 1),
        gross_shares=6.0,
        withheld_shares=0.0,
        net_shares=6.0,
        vest_fmv_usd=70.0,
        cost_basis_per_share_usd=70.0,
        remaining_shares=0.0,
        status=LotStatus.FULLY_SOLD,
        disposal_date=date(2025, 6, 15),
        disposal_qty=6.0,
    )
    all_lots = [sold_lot, lot1, lot2]

    # 2. Broker Holdings Snapshot (15 shares total)
    h_lot1 = ShareLot(
        lot_id="ACME-G100-20240515",
        symbol="ACME",
        plan_type=PlanType.RSU,
        acquisition_date=date(2024, 5, 15),
        gross_shares=10.0,
        withheld_shares=0.0,
        net_shares=10.0,
        vest_fmv_usd=100.0,
        cost_basis_per_share_usd=100.0,
        remaining_shares=10.0,
        status=LotStatus.ACTIVE,
    )
    h_lot2 = ShareLot(
        lot_id="ACME-ESPP-20240603",
        symbol="ACME",
        plan_type=PlanType.ESPP,
        acquisition_date=date(2024, 6, 3),
        gross_shares=5.0,
        withheld_shares=0.0,
        net_shares=5.0,
        vest_fmv_usd=80.0,
        cost_basis_per_share_usd=80.0,
        remaining_shares=5.0,
        status=LotStatus.ACTIVE,
    )
    holdings = [h_lot1, h_lot2]

    # 3. Monthly Statement Summaries. History starts at the earliest lot's acquisition month
    # (Dec 2023) so a sale in any month would be visible - the statement-coverage rule checks
    # exactly this - then all 12 months of CY 2025, then Q4 of FY 2025-26.
    summaries = []
    for year, month in [(2023, 12)] + [(2024, m) for m in range(1, 13)]:
        summaries.append(
            StatementPeriodSummary(
                period_label=f"Period {month}/{year}",
                start_date=date(year, month, 1),
                end_date=date(year, month, calendar.monthrange(year, month)[1]),
                beginning_value_usd=1400.0,
                ending_value_usd=1500.0,
                cash_balance_usd=40.0,
                equities_value_usd=1460.0,
                shares_held=15.0,
            )
        )
    for month in range(1, 13):
        start_d = date(2025, month, 1)
        end_d = date(2025, month, 28 if month == 2 else (30 if month in (4, 6, 9, 11) else 31))
        summaries.append(
            StatementPeriodSummary(
                period_label=f"Period {month}/2025",
                start_date=start_d,
                end_date=end_d,
                beginning_value_usd=1500.0,
                ending_value_usd=1600.0 if month < 12 else 1700.0,
                cash_balance_usd=50.0,
                equities_value_usd=1550.0,
                shares_held=15.0,
            )
        )
    # Add Jan-Mar 2026 for complete FY
    for month in range(1, 4):
        start_d = date(2026, month, 1)
        end_d = date(2026, month, 28 if month == 2 else 31)
        summaries.append(
            StatementPeriodSummary(
                period_label=f"Period {month}/2026",
                start_date=start_d,
                end_date=end_d,
                beginning_value_usd=1700.0,
                ending_value_usd=1750.0,
                cash_balance_usd=60.0,
                equities_value_usd=1690.0,
                shares_held=15.0,
            )
        )

    # 4. Dividends (4 CY 2025 quarterly payments + 1 Q4 payment)
    dividends = [
        DividendEvent(pay_date=date(2025, 3, 10), symbol="ACME", gross_amount_usd=15.0, tax_withheld_usd=3.75),
        DividendEvent(pay_date=date(2025, 6, 10), symbol="ACME", gross_amount_usd=15.0, tax_withheld_usd=3.75),
        DividendEvent(pay_date=date(2025, 9, 10), symbol="ACME", gross_amount_usd=15.0, tax_withheld_usd=3.75),
        DividendEvent(pay_date=date(2025, 12, 10), symbol="ACME", gross_amount_usd=15.0, tax_withheld_usd=3.75),
        DividendEvent(pay_date=date(2026, 3, 10), symbol="ACME", gross_amount_usd=15.0, tax_withheld_usd=3.75),
    ]

    # 5. Form 1042-S ($60.00 gross dividend, $15.00 tax withheld)
    form_1042s = Form1042SData(
        calendar_year=2025,
        recipient_name="JOHN DOE",
        recipient_tin="ABCDE1234F",
        gross_dividend_usd=60.0,
        tax_withheld_usd=15.0,
        withholding_rate=0.25,
        withholding_agent="Sample Custodial Broker LLC",
        account_number="ACC-9876543",
    )

    return {
        "all_lots": all_lots,
        "holdings": holdings,
        "summaries": summaries,
        "dividends": dividends,
        "form_1042s": form_1042s,
    }


def test_synthetic_reconciliation_and_sold_lots(synthetic_data):
    """Test reconciliation engine, active share matching, and sold lot detection."""
    ledger = LotLedger(synthetic_data["all_lots"])
    verifier = DocumentVerifier(ledger, synthetic_data["holdings"])
    report = verifier.verify_holdings()

    assert report.status in ("MATCH", "CONSISTENT")
    assert report.total_holdings_shares == 15.0
    assert report.total_reconstructed_shares == 15.0
    assert report.sold_lots_count == 1
    assert report.sold_lots[0].lot_id == "ACME-ESPP-20231201"

    # FA lots for CY 2025 includes 2 active lots + 1 sold lot = 3 lots
    fa_lots = ledger.get_schedule_fa_lots(2025)
    assert len(fa_lots) == 3


def test_synthetic_valuation_and_workbook_generation(synthetic_data):
    """Test full valuation, statutory rule validation, and multi-sheet Excel generation."""
    sbi_service = SBIRateService(auto_download=False)
    mkt_service = MarketDataService(auto_download=False)

    # Populate mock prices for ACME in market data service
    mock_acme_prices = {
        date(2025, 6, 13): {"open": 105.0, "high": 108.0, "low": 103.0, "close": 106.0},
        date(2025, 12, 31): {"open": 110.0, "high": 115.0, "low": 109.0, "close": 112.0},
        date(2025, 12, 10): {"open": 120.0, "high": 125.0, "low": 118.0, "close": 122.0},
    }
    mkt_service._price_cache["ACME"] = mock_acme_prices

    ledger = LotLedger(synthetic_data["all_lots"])
    engine = ValuationEngine(
        ledger=ledger,
        sbi_service=sbi_service,
        market_service=mkt_service,
        employer_entity_name="Acme Corporation",
        employer_entity_address="100 Silicon Way, San Jose, CA",
        employer_zip="95110",
        broker_name="Sample Custodial Broker LLC",
        broker_address="100 Wall Street, New York, NY",
        broker_zip="10005",
        account_number="ACC-9876543",
    )

    # 1. Table A2
    dec_stmt = next(s for s in synthetic_data["summaries"] if s.end_date == date(2025, 12, 31))
    a2_res = engine.compute_table_a2(2025, dec_stmt, synthetic_data["dividends"])
    assert a2_res.peak_balance_inr > 0
    assert a2_res.closing_balance_inr > 0
    assert a2_res.account_number == "ACC-9876543"

    # 2. Table A3
    a3_lots = engine.compute_table_a3(2025, synthetic_data["dividends"])
    assert len(a3_lots) == 3  # 2 active + 1 sold lot

    # 3. Schedule OS & FTC
    fy_divs = [d for d in synthetic_data["dividends"] if date(2025, 4, 1) <= d.pay_date <= date(2026, 3, 31)]
    os_res, ftc_res = engine.compute_schedule_os_and_ftc(fy_divs)
    assert os_res.total_dividend_inr > 0
    assert ftc_res.foreign_tax_paid_inr > 0

    # 4. Statutory & Schema Validation
    val_engine = ValidationEngine(sbi_service=sbi_service)
    cy_div_usd = sum(d.gross_amount_usd for d in synthetic_data["dividends"] if d.pay_date.year == 2025)
    cy_tax_usd = sum(d.tax_withheld_usd for d in synthetic_data["dividends"] if d.pay_date.year == 2025)
    val_report = val_engine.validate(
        a2=a2_res,
        a3_lots=a3_lots,
        os_result=os_res,
        ftc=ftc_res,
        form_1042s=synthetic_data["form_1042s"],
        cy_dividends_usd=cy_div_usd,
        cy_tax_withheld_usd=cy_tax_usd,
        statement_summaries=synthetic_data["summaries"],
        lots=ledger.lots,
        calendar_year=2025,
    )
    coverage = next(r for r in val_report.results if r.rule_id == "INV-STATEMENT-COVERAGE")
    assert coverage.status == RuleStatus.PASSED
    failures = [(r.rule_id, r.details) for r in val_report.results if r.status != RuleStatus.PASSED]
    assert val_report.scorecard.compute_status() == "100%_STATUTORILY_COMPLIANT", failures

    # 5. Excel Generation
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "Synthetic_ITR2_Working.xlsx")
        gen = ITRWorkbookGenerator(out_path)
        gen.generate(
            a2_result=a2_res,
            a3_lots=a3_lots,
            os_result=os_res,
            ftc_result=ftc_res,
            form_1042s=synthetic_data["form_1042s"],
            reconciliation_report=DocumentVerifier(ledger, synthetic_data["holdings"]).verify_holdings(),
            dividends=synthetic_data["dividends"],
            statement_summaries=synthetic_data["summaries"],
            taxpayer_name="JOHN DOE",
            pan="ABCDE1234F",
            ay="2026-27",
            fy="2025-26",
            sbi_service=sbi_service,
            val_report=val_report,
        )

        assert os.path.exists(out_path)
        wb = openpyxl.load_workbook(out_path, data_only=True)
        assert len(wb.sheetnames) == 12
        assert "Schedule_FA_Table_A2" in wb.sheetnames
        assert "Schedule_FA_Table_A3" in wb.sheetnames
        assert "Audit_Validation_Report" in wb.sheetnames
        assert wb["Schedule_FA_Table_A2"]["F5"].value == "ACC-9876543"
