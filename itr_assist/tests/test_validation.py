"""Unit tests for Statutory Rules & Schema Validation Engine."""
from datetime import date, timedelta
import pytest

from itr_assist.models import (
    Form1042SData,
    LotStatus,
    PlanType,
    ReconciliationReport,
    ShareLot,
)
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import (
    A2GrossAmount,
    DividendTaxResult,
    FTCResult,
    ScheduleFATableA2Result,
    ScheduleFATableA3LotResult,
    ScheduleOSResult,
)
from itr_assist.validation import (
    CBDTSchemaValidator,
    InvariantValidator,
    RuleCategory,
    RuleStatus,
    Severity,
    StatutoryRuleValidator,
    ValidationEngine,
)
from itr_assist.validation.cbdt_pdf_rules import CBDTPDFRuleValidator


@pytest.fixture
def sbi_service():
    return SBIRateService(auto_download=False)


@pytest.fixture
def sample_a2():
    return ScheduleFATableA2Result(
        country_name="UNITED STATES OF AMERICA",
        country_code="2",
        financial_inst_name="Morgan Stanley Smith Barney LLC (E*TRADE)",
        financial_inst_address="1 New York Plaza, 7th Floor, New York, NY",
        zip_code="10004",
        account_number="ACC-1234567",
        status="OWNER",
        account_open_date="2021-04-15",
        peak_balance_usd=4352.67,
        peak_balance_inr=391523,
        peak_date=date(2025, 12, 11),
        peak_rate_inr=89.95,
        closing_balance_usd=4011.61,
        closing_balance_inr=358919,
        closing_date=date(2025, 12, 31),
        closing_rate_inr=89.47,
        gross_amounts=[
            A2GrossAmount(
                nature="D",
                amount_usd=70.54,
                amount_inr=6193,
                rate_inr=87.80,
                rate_date=date(2025, 12, 31),
                source="Synthetic statement fixture",
            )
        ],
        # (statement end, value the model computes, value the statement prints)
        model_checks=[(date(2025, 12, 31), 4011.61, 4011.61)],
    )


@pytest.fixture
def sample_a3_lot():
    return ScheduleFATableA3LotResult(
        lot_id="ACME-ESPP-20241202",
        country_name="UNITED STATES OF AMERICA",
        country_code="2",
        name_of_entity="Acme Technologies Inc.",
        address_of_entity="100 Innovation Way, San Jose, CA",
        zip_code="95110",
        nature_of_entity="Company",
        acquisition_date=date(2024, 12, 2),
        gross_shares=8.0,
        net_shares=8.0,
        vest_fmv_usd=66.86,
        acq_sbi_rate_inr=84.16,
        initial_value_inr=45016,
        peak_balance_inr=54078,
        peak_date=date(2025, 7, 22),
        peak_price_usd=78.74,
        peak_rate_inr=85.85,
        closing_balance_inr=44799,
        closing_date=date(2025, 12, 31),
        closing_price_usd=62.59,
        closing_rate_inr=89.47,
        gross_dividends_usd=70.54,
        gross_dividends_inr=6193,
        gross_proceeds_inr=0,
        is_sold_lot=False,
        initial_cost_usd=534.88,
        peak_balance_usd=629.92,
        closing_balance_usd=500.72,
    )


@pytest.fixture
def sample_os_and_ftc():
    items = [
        DividendTaxResult(
            pay_date=date(2025, 6, 5),
            symbol="ACME",
            gross_usd=17.635,
            tax_usd=4.40875,
            tax_deduction_date=date(2025, 6, 5),
            preceding_month_end=date(2025, 5, 31),
            rule_115_rate=85.10,
            gross_inr=1501,
            # Rule 128(5)(ii) uses the same "last day of preceding month" date as Rule 115 when
            # the dividend is paid and the tax is deducted on the same date, so this equals
            # rule_115_rate here (previously a different, incorrect exact-pay-date rate).
            rule_128_rate=85.10,
            tax_inr=375,
            advance_tax_bucket="Upto 15-Jun-2025",
        ),
        DividendTaxResult(
            pay_date=date(2025, 9, 5),
            symbol="ACME",
            gross_usd=17.635,
            tax_usd=4.40875,
            tax_deduction_date=date(2025, 9, 5),
            preceding_month_end=date(2025, 8, 31),
            rule_115_rate=87.70,
            gross_inr=1547,
            rule_128_rate=87.70,
            tax_inr=387,
            advance_tax_bucket="16-Jun to 15-Sep-2025",
        ),
    ]
    os_res = ScheduleOSResult(
        total_dividend_inr=3048,
        upto_15_jun_inr=1501,
        upto_15_sep_inr=1547,
        upto_15_dec_inr=0,
        upto_15_mar_inr=0,
        upto_31_mar_inr=0,
        items=items,
    )
    ftc_res = FTCResult(
        country_name="UNITED STATES OF AMERICA",
        country_code="2",
        head_of_income="Other Sources",
        source_of_income="Dividends",
        dtaa_article="10",
        gross_foreign_income_inr=3048,
        foreign_tax_paid_inr=762,
        estimated_indian_tax_inr=951,
        tax_relief_claimed_inr=762,
    )
    return os_res, ftc_res


# ==============================================================================
# 1. Schema Validator Tests
# ==============================================================================

def test_schema_validator_table_a2_success(sample_a2):
    validator = CBDTSchemaValidator()
    results = validator.validate_table_a2(sample_a2)
    assert len(results) == 1
    assert results[0].status == RuleStatus.PASSED
    assert results[0].severity == Severity.FATAL_SCHEMA


def test_schema_validator_table_a2_fatal_error(sample_a2):
    validator = CBDTSchemaValidator()
    # Mutate with invalid country code and non-integer peak balance
    sample_a2.country_code = "INVALID_999"
    sample_a2.peak_balance_inr = 391523.50  # type: ignore
    results = validator.validate_table_a2(sample_a2)
    failures = [r for r in results if r.status == RuleStatus.FAILED]
    assert len(failures) >= 1
    assert any("CountryCodeExcludingIndia" in r.field_name for r in failures)


def test_schema_validator_table_a3_success(sample_a3_lot):
    validator = CBDTSchemaValidator()
    results = validator.validate_table_a3([sample_a3_lot])
    assert len(results) == 1
    assert results[0].status == RuleStatus.PASSED


def test_schema_validator_schedule_fsi_and_tr_success(sample_os_and_ftc):
    os_res, ftc_res = sample_os_and_ftc
    validator = CBDTSchemaValidator()
    fsi_results = validator.validate_schedule_fsi(ftc_res, os_res)
    assert len(fsi_results) == 1
    assert fsi_results[0].status == RuleStatus.PASSED

    tr_results = validator.validate_schedule_tr(ftc_res)
    assert len(tr_results) == 1
    assert tr_results[0].status == RuleStatus.PASSED


# ==============================================================================
# 2. Statutory Rule Validator Tests
# ==============================================================================

def test_statutory_rule_115_rate_date(sbi_service, sample_os_and_ftc):
    os_res, _ = sample_os_and_ftc
    stat_val = StatutoryRuleValidator(sbi_service)
    results = stat_val.validate_rule_115_dividends(os_res)
    assert all(r.status == RuleStatus.PASSED for r in results)

    # Induce statutory breach: set preceding month end to payment date
    os_res.items[0].preceding_month_end = os_res.items[0].pay_date
    breach_results = stat_val.validate_rule_115_dividends(os_res)
    failures = [r for r in breach_results if r.status == RuleStatus.FAILED]
    assert len(failures) >= 1
    assert failures[0].rule_id == "STAT-115-DATE-01"
    assert failures[0].severity == Severity.STATUTORY_ERROR


def test_statutory_dtaa_cap(sbi_service, sample_os_and_ftc):
    os_res, ftc_res = sample_os_and_ftc
    stat_val = StatutoryRuleValidator(sbi_service)
    results = stat_val.validate_rule_128_ftc(os_res, ftc_res)
    assert any(r.rule_id == "STAT-DTAA-CAP-01" and r.status == RuleStatus.PASSED for r in results)

    # Exceed DTAA cap
    ftc_res.tax_relief_claimed_inr = ftc_res.foreign_tax_paid_inr + 500
    breach_results = stat_val.validate_rule_128_ftc(os_res, ftc_res)
    cap_failure = next(r for r in breach_results if r.rule_id == "STAT-DTAA-CAP-01")
    assert cap_failure.status == RuleStatus.FAILED


# ==============================================================================
# 3. CBDT Systems PDF Validation Rules Tests
# ==============================================================================

def test_cbdt_pdf_rules_parity(sample_a2, sample_a3_lot, sample_os_and_ftc):
    os_res, ftc_res = sample_os_and_ftc
    pdf_val = CBDTPDFRuleValidator()
    results = pdf_val.validate_rules(
        a2=sample_a2,
        a3_lots=[sample_a3_lot],
        os_result=os_res,
        ftc=ftc_res,
        is_resident=True,
        part_b_tti_sl19_yes=True,
    )
    assert all(r.status == RuleStatus.PASSED for r in results)
    assert any(r.rule_id == "CBDT-PDF-R746" for r in results)
    assert any(r.rule_id == "CBDT-PDF-R451" for r in results)
    assert any(r.rule_id == "CBDT-PDF-R526" for r in results)


def test_cbdt_pdf_rule_448_fsi_exceeds_os(sample_a2, sample_a3_lot, sample_os_and_ftc):
    os_res, ftc_res = sample_os_and_ftc
    # FSI foreign income exceeds Schedule OS total income
    ftc_res.gross_foreign_income_inr = os_res.total_dividend_inr + 1000
    pdf_val = CBDTPDFRuleValidator()
    results = pdf_val.validate_rules(
        a2=sample_a2,
        a3_lots=[sample_a3_lot],
        os_result=os_res,
        ftc=ftc_res,
        is_resident=True,
        part_b_tti_sl19_yes=True,
    )
    r448 = next(r for r in results if r.rule_id == "CBDT-PDF-R448")
    assert r448.status == RuleStatus.FAILED
    assert r448.severity == Severity.DEFECTIVE_139_9


# ==============================================================================
# 4. Invariant Tests
# ==============================================================================

def test_invariant_peak_closing(sample_a2, sample_a3_lot):
    inv_val = InvariantValidator()
    results = inv_val.validate_peak_closing_invariants(sample_a2, [sample_a3_lot])
    assert all(r.status == RuleStatus.PASSED for r in results)

    # Invert Table A2 peak and closing
    sample_a2.peak_balance_inr = sample_a2.closing_balance_inr - 1000
    inv_results = inv_val.validate_peak_closing_invariants(sample_a2, [sample_a3_lot])
    fail = next(r for r in inv_results if r.rule_id == "INV-PEAK-CLOSE-A2")
    assert fail.status == RuleStatus.FAILED


def test_invariant_1042s_reconciliation():
    inv_val = InvariantValidator()
    form_1042s = Form1042SData(
        calendar_year=2025,
        recipient_name="JOHN DOE",
        recipient_tin="ABCDE1234F",
        gross_dividend_usd=71.0,
        tax_withheld_usd=18.0,
        withholding_rate=0.25,
        withholding_agent="E*TRADE",
        account_number="ACC-1234567",
    )
    # Statement gross $70.54 rounds to $71.00 (diff $0.46 <= $1.00) -> PASS
    results = inv_val.validate_cross_document_reconciliation(
        form_1042s=form_1042s,
        cy_dividends_usd=70.54,
        cy_tax_withheld_usd=17.64,
    )
    assert all(r.status == RuleStatus.PASSED for r in results)

    # Statement gross differs by more than $1.00 -> FAIL
    fail_results = inv_val.validate_cross_document_reconciliation(
        form_1042s=form_1042s,
        cy_dividends_usd=65.00,
        cy_tax_withheld_usd=17.64,
    )
    fail_r = next(r for r in fail_results if r.rule_id == "INV-1042S-DIV-RECON")
    assert fail_r.status == RuleStatus.FAILED


# ==============================================================================
# 5. Full Validation Engine Pipeline Test
# ==============================================================================

def test_validation_engine_pipeline(sbi_service, sample_a2, sample_a3_lot, sample_os_and_ftc):
    os_res, ftc_res = sample_os_and_ftc
    engine = ValidationEngine(sbi_service=sbi_service)
    report = engine.validate(
        a2=sample_a2,
        a3_lots=[sample_a3_lot],
        os_result=os_res,
        ftc=ftc_res,
        cy_dividends_usd=35.27,
        cy_tax_withheld_usd=8.82,
    )
    assert report.scorecard.total_rules > 10
    assert report.scorecard.is_filing_ready is True
    assert report.scorecard.fatal_errors == 0
    assert report.scorecard.defective_errors == 0
    assert report.scorecard.statutory_errors == 0
    assert report.scorecard.compute_status() == "100%_STATUTORILY_COMPLIANT"


def _period(start, end):
    from itr_assist.models import StatementPeriodSummary
    return StatementPeriodSummary(
        period_label=f"{start}..{end}", start_date=start, end_date=end,
        beginning_value_usd=0.0, ending_value_usd=0.0,
        cash_balance_usd=0.0, equities_value_usd=0.0, shares_held=0.0,
    )


def _rsu_lot(acq):
    return ShareLot(
        lot_id=f"X-{acq}", symbol="X", plan_type=PlanType.RSU, acquisition_date=acq,
        gross_shares=10, withheld_shares=0, net_shares=10, vest_fmv_usd=10.0,
        cost_basis_per_share_usd=10.0, remaining_shares=10, status=LotStatus.ACTIVE,
    )


def test_coverage_gaps_bundled_and_duplicate_periods_have_no_gap():
    from itr_assist.validation.invariants import find_coverage_gaps
    periods = [
        _period(date(2024, 1, 1), date(2024, 2, 29)),   # E*TRADE folds a quiet month into the next statement
        _period(date(2024, 3, 1), date(2024, 3, 31)),
        _period(date(2024, 3, 1), date(2024, 3, 31)),   # same statement uploaded twice (two FY folders)
        _period(date(2024, 4, 1), date(2024, 6, 30)),   # quarterly statement
    ]
    assert find_coverage_gaps(periods, date(2024, 1, 15), date(2024, 6, 30)) == []


def test_coverage_gaps_reports_leading_middle_and_trailing_gaps_exactly():
    from itr_assist.validation.invariants import find_coverage_gaps
    periods = [
        _period(date(2024, 3, 1), date(2024, 4, 30)),
        _period(date(2024, 7, 1), date(2024, 7, 31)),
    ]
    assert find_coverage_gaps(periods, date(2024, 1, 1), date(2024, 9, 30)) == [
        (date(2024, 1, 1), date(2024, 2, 29)),
        (date(2024, 5, 1), date(2024, 6, 30)),
        (date(2024, 8, 1), date(2024, 9, 30)),
    ]
    assert find_coverage_gaps([], date(2024, 1, 1), date(2024, 1, 31)) == [(date(2024, 1, 1), date(2024, 1, 31))]


def test_statement_coverage_rule_spans_first_vest_through_fy_end():
    inv_val = InvariantValidator()
    lots = [_rsu_lot(date(2023, 11, 20)), _rsu_lot(date(2026, 2, 20))]  # 2026 vest is after CY2025 - ignored
    full = [_period(date(2023, 11, 1), date(2026, 3, 31))]
    (passed,) = inv_val.validate_statement_coverage(full, lots, 2025)
    assert passed.status == RuleStatus.PASSED

    # Only the filing year's own statements: a 2024 sale of the 2023 lot would be invisible.
    filing_year_only = [_period(date(2025, 1, 1), date(2026, 3, 31))]
    (failed,) = inv_val.validate_statement_coverage(filing_year_only, lots, 2025)
    assert failed.status == RuleStatus.FAILED
    assert failed.severity == Severity.STATUTORY_ERROR
    assert "2023-11-20 to 2024-12-31" in failed.details


def test_failed_audit_warning_rule_is_not_reported_as_fully_compliant(sbi_service, sample_a2, sample_a3_lot, sample_os_and_ftc):
    from itr_assist.models import SaleEvent
    os_res, ftc_res = sample_os_and_ftc
    engine = ValidationEngine(sbi_service=sbi_service)
    # An unmatched sale yields a FAILED rule of severity AUDIT_WARNING; the verdict must reflect it.
    unmatched = SaleEvent(sale_date=date(2025, 6, 1), symbol="X", quantity=5, price_usd=10.0,
                          gross_proceeds_usd=50.0, unmatched_quantity=5)
    report = engine.validate(a2=sample_a2, a3_lots=[sample_a3_lot], os_result=os_res, ftc=ftc_res,
                             cy_dividends_usd=35.27, cy_tax_withheld_usd=8.82, sales=[unmatched])
    assert report.scorecard.failed >= 1
    assert report.scorecard.compute_status() != "100%_STATUTORILY_COMPLIANT"
