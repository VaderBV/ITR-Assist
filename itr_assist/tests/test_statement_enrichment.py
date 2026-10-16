"""Statement parsing against the page layout of real Morgan Stanley / E*TRADE statements.

The cover page holds only the period totals; cash, holdings and the activity table sit on later
pages. The earlier fixture put "Cash" on the cover page, so a parser that only read the cover page
passed its tests while returning $0 cash for every real statement. These fixtures keep the real
layout (fictional name, company and amounts).
"""
from datetime import date
from unittest.mock import MagicMock, patch

from itr_assist.parsers.etrade import ETradeStatementParser

COVER = (
    "Beginning Total Value (as of 12/1/25) $7,000.00\n"
    "Ending Total Value (as of 12/31/25) $7,525.02\n"
    "Includes Accrued Interest\n"
    "CLIENT STATEMENT     For the Period December 1-31, 2025\n"
    "STATEMENT FOR:\nJOHN DOE\n"
)
ACCOUNT_SUMMARY = (
    "Account Summary\nCLIENT STATEMENT     For the Period December 1-31, 2025\n"
    "ASSET ALLOCATION (includes accrued interest)\nCash\nEquities\n"
    "Market Value Percentage\nCash $1,525.02 20.27\nEquities 6,000.00 79.73\nTOTAL VALUE $7,525.02 100.00%\n"
    "CASH FLOW\nThis Period\nOPENING CASH, BDP, MMFs $1,000.00 $400.00\n"
    "Sales and Redemptions 495.00 495.00\n"
    "CLOSING CASH, BDP, MMFs $1,525.02 $1,525.02\n"
)
HOLDINGS = (
    "Account Detail\nCLIENT STATEMENT     For the Period December 1-31, 2025\n"
    "STOCKS\nCOMMON STOCKS\n"
    "Security Description Quantity Share Price Total Cost Market Value\n"
    "ACME CORP (ACME) 40.000 $150.000 $5,000.00 $6,000.00 $1,000.00 $80.00 1.33\n"
    "Rating: Morningstar: 2; Asset Class: Equities\n"
    "STOCK PLAN DETAILS\n08/20/23 RU000001 RSU ACME 24.263 $0.00 $150.00 $3,639.45\n"
)
ACTIVITY = (
    "ACTIVITY\nCASH FLOW ACTIVITY BY DATE\nActivity\nDate\nSettlement\n"
    "Date Activity Type Description Comments Quantity Price Credits/(Debits)\n"
    "12/10 Qualified Dividend ACME CORP $40.00\n"
    "12/10 Tax Withholding ACME CORP (10.00)\n"
    "12/18 12/19 Sold ACME CORP ACTED AS AGENT\nUNSOLICITED TRADE\n5.000 $100.0000 $495.00\n"
    "12/31 Interest Income BANK NA (Period 12/01-12/31) 0.02\n"
    "NET CREDITS/(DEBITS) $525.02\n"
    "MONEY MARKET FUND (MMF) AND BANK DEPOSIT PROGRAM ACTIVITY\nActivity\nDate Activity Type Description Credits/(Debits)\n"
    "12/10 Automatic Investment BANK DEPOSIT PROGRAM $30.00\n"
    "12/19 Automatic Investment BANK DEPOSIT PROGRAM 495.00\n"
    "NET ACTIVITY FOR PERIOD $525.02\n"
)


def _parse(pages, **kwargs):
    reader_pages = []
    for text in pages:
        page = MagicMock()
        page.extract_text.return_value = text
        reader_pages.append(page)
    with patch("itr_assist.parsers.etrade.statements.PdfReader") as reader:
        reader.return_value.pages = reader_pages
        return ETradeStatementParser().parse(["stmt.pdf"], calendar_year_hint=2025, **kwargs)


def test_cash_holdings_and_shares_come_from_later_pages():
    summaries, _, _ = _parse([COVER, ACCOUNT_SUMMARY, HOLDINGS, ACTIVITY])
    s = summaries[0]
    assert s.ending_value_usd == 7525.02
    assert s.cash_balance_usd == 1525.02          # not on the cover page
    assert s.opening_cash_usd == 1000.00
    assert s.equities_value_usd == 6000.00
    assert s.holdings_qty == {"ACME": 40.0}
    assert s.holdings_price == {"ACME": 150.0}
    assert s.holdings_name == {"ACME": "ACME CORP"}
    assert s.shares_held == 40.0


def test_activity_rows_roll_cash_forward_without_double_counting_the_sweep_table():
    summaries, _, _ = _parse([COVER, ACCOUNT_SUMMARY, HOLDINGS, ACTIVITY])
    s = summaries[0]
    by_label = {label: (d, amount) for d, amount, label in s.cash_events}
    assert by_label["Qualified Dividend ACME CORP"] == (date(2025, 12, 10), 40.00)
    assert by_label["Tax Withholding ACME CORP"] == (date(2025, 12, 10), -10.00)
    # The trade row carries two dates; cash moves on the settlement date, not the trade date.
    sold = [(d, a) for d, a, label in s.cash_events if label.startswith("Sold ACME CORP")]
    assert sold == [(date(2025, 12, 19), 495.00)]
    assert len(s.cash_events) == 4                # the MMF/BDP sweep rows below are not counted
    assert round(s.opening_cash_usd + sum(a for _, a, _ in s.cash_events), 2) == s.cash_balance_usd


def test_interest_is_collected_with_its_date():
    summaries, _, _ = _parse([COVER, ACCOUNT_SUMMARY, HOLDINGS, ACTIVITY])
    s = summaries[0]
    assert s.interest_events == [(date(2025, 12, 31), 0.02)]
    assert s.interest_usd == 0.02


def test_quantities_and_prices_are_not_mistaken_for_cash_amounts():
    # "5.000 $100.0000 $495.00": only the last token is money (two decimals, nothing after).
    summaries, _, sales = _parse([COVER, ACCOUNT_SUMMARY, HOLDINGS, ACTIVITY])
    assert 5.0 not in [a for _, a, _ in summaries[0].cash_events]
    assert 100.0 not in [a for _, a, _ in summaries[0].cash_events]
    assert [(s.quantity, s.gross_proceeds_usd, s.net_credit_usd) for s in sales] == [(5.0, 500.0, 495.0)]


def test_trade_settling_next_year_is_dated_in_the_new_year():
    activity = ACTIVITY.replace("12/18 12/19 Sold", "12/30 01/02 Sold")
    summaries, _, _ = _parse([COVER, ACCOUNT_SUMMARY, HOLDINGS, activity])
    dated = {d for d, a, _ in summaries[0].cash_events if a == 495.00}
    assert dated == {date(2026, 1, 2)}


def test_empty_balances_printed_as_dashes_are_zero():
    cover = COVER.replace("$7,000.00", "—").replace("$7,525.02", "—")
    summary = (
        "CLIENT STATEMENT     For the Period December 1-31, 2025\n"
        "CASH FLOW\nOPENING CASH, BDP, MMFs — —\nCLOSING CASH, BDP, MMFs — —\n"
    )
    summaries, _, _ = _parse([cover, summary])
    assert summaries[0].opening_cash_usd == 0.0
    assert summaries[0].cash_balance_usd == 0.0


def test_statement_without_activity_table_has_no_events_and_keeps_cash():
    summaries, _, _ = _parse([COVER, ACCOUNT_SUMMARY.replace("$1,525.02 $1,525.02", "$1,000.00 $1,000.00"), HOLDINGS])
    s = summaries[0]
    assert s.cash_events == [] and s.interest_events == []
    assert s.cash_balance_usd == 1000.00


def test_two_statements_in_one_file_each_get_their_own_details():
    nov = (COVER.replace("December 1-31", "November 1-30").replace("12/1/25", "11/1/25").replace("12/31/25", "11/30/25"))
    nov_summary = (
        "CLIENT STATEMENT     For the Period November 1-30, 2025\n"
        "OPENING CASH, BDP, MMFs $900.00 $400.00\nCLOSING CASH, BDP, MMFs $1,000.00 $1,000.00\n"
    )
    summaries, _, _ = _parse([nov, nov_summary, COVER, ACCOUNT_SUMMARY, HOLDINGS, ACTIVITY])
    by_end = {s.end_date: s for s in summaries}
    assert by_end[date(2025, 11, 30)].cash_balance_usd == 1000.00
    assert by_end[date(2025, 12, 31)].cash_balance_usd == 1525.02
    assert by_end[date(2025, 11, 30)].holdings_qty == {}      # not borrowed from the December pages
