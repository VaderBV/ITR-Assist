"""Table A2: peak from the account's real daily cash, income rows, placeholders and the checks
that make a wrong A2 visible.

Each test here pins a defect that once shipped as "100% compliant": cash read as $0 so the peak
silently fell back to the closing value, interest and sale-proceeds rows never written, and
invented addresses / ZIP / opening date accepted as real.
"""
from datetime import date

from itr_assist.models import (
    PLACEHOLDER_PREFIX,
    DividendEvent,
    LotStatus,
    PlanType,
    SaleEvent,
    ShareLot,
    StatementPeriodSummary,
    is_placeholder,
)
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import ValuationEngine
from itr_assist.validation.invariants import InvariantValidator
from itr_assist.validation.models import RuleStatus, Severity
from itr_assist.validation.schema_validator import CBDTSchemaValidator

DETAILS = dict(
    broker_name="Test Broker LLC", broker_address="1 Test Plaza, New York, NY", broker_zip="10004",
    account_number="123-456789", account_open_date="2023-09-01",
    employer_entity_name="ACME CORP", employer_entity_address="1 Acme Way, Springfield", employer_zip="12345",
)


def _lot(shares=10.0):
    return ShareLot(
        lot_id="ACME-RSU-20240515", symbol="ACME", plan_type=PlanType.RSU,
        acquisition_date=date(2024, 5, 15), gross_shares=shares, withheld_shares=0.0, net_shares=shares,
        vest_fmv_usd=100.0, cost_basis_per_share_usd=100.0, remaining_shares=shares, status=LotStatus.ACTIVE,
    )


def _market(prices):
    mkt = MarketDataService(auto_download=False)
    mkt._price_cache["ACME"] = {d: {"open": p, "high": p, "low": p, "close": p} for d, p in prices.items()}
    return mkt


def _statement(start, end, opening, closing, ending_value, events=(), interest=()):
    return StatementPeriodSummary(
        period_label=f"{start}..{end}", start_date=start, end_date=end,
        beginning_value_usd=0.0, ending_value_usd=ending_value,
        cash_balance_usd=closing, equities_value_usd=ending_value - closing, shares_held=10.0,
        opening_cash_usd=opening, cash_events=list(events), interest_events=list(interest),
        interest_usd=round(sum(a for _, a in interest), 2),
    )


PRICES = {
    date(2025, 2, 3): 100.0, date(2025, 4, 7): 100.0, date(2025, 6, 30): 100.0,
    date(2025, 10, 6): 100.0, date(2025, 12, 31): 100.0,
}


def _two_halves():
    """10 shares at $100 all year. Cash: $0, +$300 deposited 10-Mar, -$300 withdrawn 1-Sep."""
    h1 = _statement(date(2025, 1, 1), date(2025, 6, 30), 0.0, 300.0, 1300.0,
                    events=[(date(2025, 3, 10), 300.0, "Funds Received")])
    h2 = _statement(date(2025, 7, 1), date(2025, 12, 31), 300.0, 0.0, 1000.0,
                    events=[(date(2025, 9, 1), -300.0, "Funds Transferred")])
    return h1, h2


def _engine(ledger=None, prices=PRICES, **overrides):
    return ValuationEngine(
        ledger=ledger or LotLedger([_lot()]), sbi_service=SBIRateService(auto_download=False),
        market_service=_market(prices), **{**DETAILS, **overrides},
    )


# ---------------------------------------------------------------- the peak
def test_peak_uses_the_cash_held_on_each_day_not_the_year_end_cash():
    h1, h2 = _two_halves()
    a2 = _engine().compute_table_a2(2025, h2, [], statement_summaries=[h1, h2])
    # $300 of cash sat in the account from March to August, so the account peaked at $1,300 then;
    # on 31-Dec (no cash) it is only $1,000. A flat 31-Dec cash cannot see this.
    assert a2.peak_balance_usd == 1300.00
    assert a2.peak_date in (date(2025, 4, 7), date(2025, 6, 30))
    assert a2.closing_balance_usd == 1000.00
    assert a2.peak_balance_inr > a2.closing_balance_inr
    assert not a2.peak_degraded and a2.peak_notes == []
    assert [(d, m, p) for d, m, p in a2.model_checks] == [
        (date(2025, 6, 30), 1300.0, 1300.0), (date(2025, 12, 31), 1000.0, 1000.0)]


def test_without_statement_history_the_peak_is_flagged_unverified():
    _, h2 = _two_halves()
    a2 = _engine().compute_table_a2(2025, h2, [])
    assert a2.peak_degraded
    assert any("No statement history" in n for n in a2.peak_notes)


def test_cash_parsed_as_zero_is_caught_not_hidden_by_the_closing_floor():
    """The original bug: cash/opening never parsed, so peak fell back to the closing value."""
    h1 = _statement(date(2025, 1, 1), date(2025, 6, 30), None, 0.0, 1300.0)
    h2 = _statement(date(2025, 7, 1), date(2025, 12, 31), None, 0.0, 1000.0)
    a2 = _engine().compute_table_a2(2025, h2, [], statement_summaries=[h1, h2])
    assert a2.peak_degraded
    joined = " ".join(a2.peak_notes)
    assert "cannot be verified" in joined and "valuation model gives $1,000.00" in joined
    result = InvariantValidator().validate_a2_integrity(a2, [])[0]
    assert result.rule_id == "INV-A2-PEAK-VERIFIED"
    assert result.status == RuleStatus.FAILED


def test_valuation_model_catches_a_wrong_share_count():
    h1, h2 = _two_halves()
    a2 = _engine(ledger=LotLedger([_lot(shares=12.0)])).compute_table_a2(
        2025, h2, [], statement_summaries=[h1, h2])
    assert a2.peak_degraded
    assert any("valuation model gives $1,200.00" in n and "prints $1,000.00" in n for n in a2.peak_notes)


def test_a_verified_peak_passes_the_rule_and_says_what_it_checked():
    h1, h2 = _two_halves()
    a2 = _engine().compute_table_a2(2025, h2, [], statement_summaries=[h1, h2])
    result = InvariantValidator().validate_a2_integrity(a2, [])[0]
    assert result.status == RuleStatus.PASSED
    assert "2 statement dates" in result.details


# ---------------------------------------------------------------- income rows
def test_dividend_interest_and_sale_proceeds_each_get_their_own_row():
    h1 = _statement(date(2025, 1, 1), date(2025, 6, 30), 0.0, 0.0, 1000.0,
                    interest=[(date(2025, 3, 31), 0.03), (date(2025, 6, 30), 0.02)])
    h2 = _statement(date(2025, 7, 1), date(2025, 12, 31), 0.0, 0.0, 1000.0, interest=[(date(2025, 9, 30), 0.01)])
    divs = [DividendEvent(date(2025, 3, 10), "ACME", 20.0, 5.0), DividendEvent(date(2025, 9, 10), "ACME", 20.0, 5.0)]
    sales = [SaleEvent(date(2025, 5, 12), "ACME", 2.0, 110.0, 220.0)]
    engine = _engine()
    a2 = engine.compute_table_a2(2025, h2, divs, statement_summaries=[h1, h2], cy_sales=sales)

    rows = {g.nature: g for g in a2.gross_amounts}
    assert list(rows) == ["D", "I", "S"]
    assert (rows["D"].amount_usd, rows["I"].amount_usd, rows["S"].amount_usd) == (40.0, 0.06, 220.0)
    sbi = engine.sbi
    assert rows["D"].amount_inr == sum(round(20.0 * sbi.get_rule_115_dividend_rate(d.pay_date)[1]) for d in divs)
    assert rows["I"].amount_inr == sum(
        round(a * sbi.get_rule_115_dividend_rate(d)[1])
        for d, a in [(date(2025, 3, 31), 0.03), (date(2025, 6, 30), 0.02), (date(2025, 9, 30), 0.01)])
    assert rows["S"].amount_inr == round(220.0 * sbi.get_rule_115_capital_gains_rate(date(2025, 5, 12))[1])
    assert all(g.rate_inr > 0 for g in rows.values())       # effective rate, not a 0.0 stand-in


def test_sales_and_interest_in_other_years_are_not_reported():
    h1, h2 = _two_halves()
    h1.interest_events = [(date(2024, 12, 31), 5.0)]          # belongs to another year
    sales = [SaleEvent(date(2024, 5, 12), "ACME", 2.0, 110.0, 220.0)]
    a2 = _engine().compute_table_a2(2025, h2, [], statement_summaries=[h1, h2], cy_sales=sales)
    assert [g.nature for g in a2.gross_amounts] == ["N"]


def test_a2_income_must_agree_with_a3_or_the_rule_fails():
    divs = [DividendEvent(date(2025, 3, 10), "ACME", 20.0, 5.0), DividendEvent(date(2025, 9, 10), "ACME", 20.0, 5.0)]
    ledger = LotLedger([_lot()])
    sales = ledger.allocate_sales([SaleEvent(date(2025, 5, 12), "ACME", 2.0, 110.0, 220.0)])
    engine = _engine(ledger=ledger)
    h1 = _statement(date(2025, 1, 1), date(2025, 12, 31), 0.0, 0.0, 800.0)
    a2 = engine.compute_table_a2(2025, h1, divs, statement_summaries=[h1], cy_sales=sales)
    a3 = engine.compute_table_a3(2025, divs, sales)
    validator = InvariantValidator()
    income = [r for r in validator.validate_a2_integrity(a2, a3) if r.rule_id == "INV-A2-A3-INCOME"][0]
    assert income.status == RuleStatus.PASSED, income.details

    # The original defect: the sale-proceeds row is simply absent from A2.
    a2.gross_amounts = [g for g in a2.gross_amounts if g.nature != "S"]
    income = [r for r in validator.validate_a2_integrity(a2, a3) if r.rule_id == "INV-A2-A3-INCOME"][0]
    assert income.status == RuleStatus.FAILED and "sale proceeds" in income.details


# ---------------------------------------------------------------- placeholders
def test_details_the_documents_cannot_supply_are_placeholders_never_invented():
    engine = ValuationEngine(
        ledger=LotLedger([_lot()]), sbi_service=SBIRateService(auto_download=False),
        market_service=_market(PRICES))
    for value in (engine.broker_address, engine.broker_zip, engine.account_open_date, engine.account_number,
                  engine.employer_entity_address, engine.employer_zip, engine.employer_entity_name, engine.broker_name):
        assert value.startswith(PLACEHOLDER_PREFIX), value
    for fake in ("00000", "2021-01-01", "Broker Operating Address", "Corporate Headquarters Address"):
        assert fake not in (engine.broker_address, engine.broker_zip, engine.account_open_date,
                            engine.employer_entity_address, engine.employer_zip)


def test_supplied_details_are_used_and_whitespace_only_counts_as_missing():
    engine = _engine(broker_zip="  10004  ", account_open_date="   ")
    assert engine.broker_zip == "10004"
    assert is_placeholder(engine.account_open_date)


def test_placeholders_fail_one_rule_naming_every_missing_field():
    h1, h2 = _two_halves()
    engine = _engine(broker_address="", account_open_date="", employer_entity_address="", employer_zip="")
    a2 = engine.compute_table_a2(2025, h2, [], statement_summaries=[h1, h2])
    a3 = engine.compute_table_a3(2025, [])
    result = InvariantValidator().validate_placeholders(
        a2, a3, {"taxpayer name": "JOHN DOE", "PAN": f"{PLACEHOLDER_PREFIX}: PAN"})[0]
    assert result.rule_id == "INV-NO-PLACEHOLDERS"
    assert result.status == RuleStatus.FAILED and result.severity == Severity.DEFECTIVE_139_9
    for text in ("broker address", "account opening date", "company address", "company ZIP", "PAN"):
        assert text in result.details
    assert "taxpayer name" not in result.details.replace("Taxpayer:", "")  # the name WAS supplied


def test_nothing_missing_passes_the_placeholder_rule():
    h1, h2 = _two_halves()
    engine = _engine()
    a2 = engine.compute_table_a2(2025, h2, [], statement_summaries=[h1, h2])
    a3 = engine.compute_table_a3(2025, [])
    result = InvariantValidator().validate_placeholders(a2, a3, {"PAN": "ABCDE1234F"})[0]
    assert result.status == RuleStatus.PASSED


def test_placeholders_are_reported_once_not_as_schema_noise_on_every_row():
    h1, h2 = _two_halves()
    a2 = _engine(broker_address="", broker_zip="", account_open_date="").compute_table_a2(
        2025, h2, [], statement_summaries=[h1, h2])
    results = CBDTSchemaValidator().validate_table_a2(a2)
    assert results and all(r.status == RuleStatus.PASSED for r in results)


def test_a_real_schema_violation_is_still_reported():
    h1, h2 = _two_halves()
    a2 = _engine(broker_zip="TOO-LONG-ZIP").compute_table_a2(2025, h2, [], statement_summaries=[h1, h2])
    results = CBDTSchemaValidator().validate_table_a2(a2)
    assert any(r.status == RuleStatus.FAILED and r.field_name == "ZipCode" for r in results)
