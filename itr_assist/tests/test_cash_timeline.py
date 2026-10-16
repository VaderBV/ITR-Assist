"""CashTimeline: daily cash rebuilt from statements and checked against each printed closing."""
from datetime import date

from itr_assist.models import StatementPeriodSummary
from itr_assist.services.cash_timeline import CashTimeline


def _period(start, end, opening, closing, events=()):
    return StatementPeriodSummary(
        period_label=f"{start}..{end}", start_date=start, end_date=end,
        beginning_value_usd=0.0, ending_value_usd=0.0,
        cash_balance_usd=closing, equities_value_usd=0.0, shares_held=0.0,
        opening_cash_usd=opening, cash_events=list(events),
    )


def test_cash_changes_on_the_day_it_moves():
    tl = CashTimeline([_period(
        date(2025, 1, 1), date(2025, 1, 31), 100.0, 130.0,
        [(date(2025, 1, 10), 50.0, "Funds Received"), (date(2025, 1, 20), -20.0, "Funds Transferred")],
    )])
    assert tl.issues == []
    assert tl.cash_on(date(2025, 1, 9)) == 100.0
    assert tl.cash_on(date(2025, 1, 10)) == 150.0
    assert tl.cash_on(date(2025, 1, 19)) == 150.0
    assert tl.cash_on(date(2025, 1, 31)) == 130.0
    assert tl.cash_on(date(2025, 2, 1)) is None   # no statement covers it


def test_cash_settling_after_month_end_belongs_to_the_next_period():
    # A sale traded 30 Jan settles 2 Feb: listed in January's table, cash arrives in February.
    jan = _period(date(2025, 1, 1), date(2025, 1, 31), 100.0, 100.0, [(date(2025, 2, 2), 500.0, "Sold")])
    feb = _period(date(2025, 2, 1), date(2025, 2, 28), 100.0, 600.0)
    tl = CashTimeline([jan, feb])
    assert tl.issues == []
    assert tl.cash_on(date(2025, 1, 31)) == 100.0
    assert tl.cash_on(date(2025, 2, 1)) == 100.0
    assert tl.cash_on(date(2025, 2, 2)) == 600.0


def test_period_that_does_not_reconcile_is_unverified_and_the_chain_restarts():
    jan = _period(date(2025, 1, 1), date(2025, 1, 31), 100.0, 100.0)
    feb = _period(date(2025, 2, 1), date(2025, 2, 28), 100.0, 250.0)   # +150 not explained by any row
    mar = _period(date(2025, 3, 1), date(2025, 3, 31), 250.0, 260.0, [(date(2025, 3, 5), 10.0, "Dividend")])
    tl = CashTimeline([jan, feb, mar])
    assert len(tl.issues) == 1
    assert "$100.00" in tl.issues[0] and "$250.00" in tl.issues[0]   # computed vs printed
    assert tl.cash_on(date(2025, 1, 15)) == 100.0
    assert tl.cash_on(date(2025, 2, 15)) is None
    assert tl.cash_on(date(2025, 3, 10)) == 260.0                       # verified again from Feb's printed close
    assert tl.unverified_ranges(date(2025, 1, 1), date(2025, 3, 31)) == [(date(2025, 2, 1), date(2025, 2, 28))]
    assert tl.issues_between(date(2025, 3, 1), date(2025, 3, 31)) == []
    assert len(tl.issues_between(date(2025, 2, 1), date(2025, 2, 28))) == 1


def test_missing_opening_cash_means_unverified_not_zero():
    tl = CashTimeline([_period(date(2025, 1, 1), date(2025, 1, 31), None, 100.0)])
    assert tl.cash_on(date(2025, 1, 15)) is None
    assert tl.unverified_ranges(date(2025, 1, 1), date(2025, 1, 31)) == [(date(2025, 1, 1), date(2025, 1, 31))]


def test_missing_statement_leaves_its_days_unverified():
    jan = _period(date(2025, 1, 1), date(2025, 1, 31), 100.0, 100.0)
    mar = _period(date(2025, 3, 1), date(2025, 3, 31), 100.0, 100.0)
    tl = CashTimeline([jan, mar])
    assert tl.unverified_ranges(date(2025, 1, 1), date(2025, 3, 31)) == [(date(2025, 2, 1), date(2025, 2, 28))]
    assert tl.cash_on(date(2025, 2, 10)) is None
    assert tl.cash_on(date(2025, 3, 10)) == 100.0


def test_cent_rounding_in_printed_amounts_is_tolerated():
    tl = CashTimeline([_period(date(2025, 1, 1), date(2025, 1, 31), 100.00, 110.01, [(date(2025, 1, 5), 10.0, "x")])])
    assert tl.issues == []
