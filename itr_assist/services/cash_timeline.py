"""Daily cash balance of a broker account, rebuilt from the statements' own cash roll-forward."""
from datetime import date, timedelta
from typing import List, Optional, Tuple

from itr_assist.models import StatementPeriodSummary

# One cent of rounding per printed amount, a few amounts per period.
CASH_TOLERANCE_USD = 0.02


class CashTimeline:
    """Cash on any day, as opening cash plus every dated cash movement printed on the statements.

    Brokers show cash on a settlement-date basis, so a sale traded on the last day of a month
    can settle in the next one: its row sits in the first statement's activity table but its
    cash only reaches the account in the second. Events are therefore pooled across all
    statements and applied on the day the cash moves, not within the statement that lists them.

    A period is trusted only if the running balance at its end equals the closing cash the
    statement itself prints. A period that does not reconcile (unparsed row, missing statement,
    unknown activity type) is reported in `issues` and `cash_on` returns None for its days; the
    chain then restarts from that statement's printed closing cash.
    """

    def __init__(self, summaries: List[StatementPeriodSummary]):
        self.issues: List[str] = []
        # (first day, last day, message) for each unreconciled period, to filter by filing year.
        self.issue_ranges: List[Tuple[date, date, str]] = []
        ordered = sorted(summaries, key=lambda s: s.start_date)
        self._events: List[Tuple[date, float]] = sorted(
            (d, amount) for s in ordered for d, amount, _ in s.cash_events
        )
        # (start, end, anchor_date, anchor_balance, verified)
        self._periods: List[Tuple[date, date, Optional[date], Optional[float], bool]] = []

        anchor_date: Optional[date] = None
        anchor_balance: Optional[float] = None
        for s in ordered:
            if anchor_date is None:
                if s.opening_cash_usd is None:
                    self._periods.append((s.start_date, s.end_date, None, None, False))
                    self._issue(s, f"{s.period_label}: opening cash is not printed on the statement, so "
                                   f"cash for {s.start_date} to {s.end_date} cannot be verified.")
                    continue
                anchor_date, anchor_balance = s.start_date, s.opening_cash_usd

            running = anchor_balance + sum(a for d, a in self._events if anchor_date <= d <= s.end_date)
            verified = abs(running - s.cash_balance_usd) <= CASH_TOLERANCE_USD
            self._periods.append((s.start_date, s.end_date, anchor_date, anchor_balance, verified))
            if not verified:
                self._issue(s, f"{s.period_label}: opening cash plus the activity rows gives ${running:,.2f} "
                               f"but the statement prints closing cash of ${s.cash_balance_usd:,.2f}; cash for "
                               f"{s.start_date} to {s.end_date} cannot be verified.")
                anchor_date, anchor_balance = s.end_date + timedelta(days=1), s.cash_balance_usd

    def _issue(self, summary: StatementPeriodSummary, message: str) -> None:
        self.issues.append(message)
        self.issue_ranges.append((summary.start_date, summary.end_date, message))

    def issues_between(self, start: date, end: date) -> List[str]:
        """Messages for unreconciled periods that overlap [start, end]."""
        return [m for s, e, m in self.issue_ranges if s <= end and e >= start]

    def cash_on(self, day: date) -> Optional[float]:
        """Cash at the end of `day`, or None when no reconciled statement covers that day."""
        for start, end, anchor_date, anchor_balance, verified in self._periods:
            if start <= day <= end:
                if not verified or anchor_date is None:
                    return None
                return round(anchor_balance + sum(a for d, a in self._events if anchor_date <= d <= day), 2)
        return None

    def unverified_ranges(self, start: date, end: date) -> List[Tuple[date, date]]:
        """Ranges inside [start, end] with no reconciled statement (uncovered or not reconciled)."""
        covered = sorted(
            (max(p_start, start), min(p_end, end))
            for p_start, p_end, _, _, verified in self._periods
            if verified and p_start <= end and p_end >= start
        )
        gaps: List[Tuple[date, date]] = []
        cursor = start
        for c_start, c_end in covered:
            if c_start > cursor:
                gaps.append((cursor, c_start - timedelta(days=1)))
            cursor = max(cursor, c_end + timedelta(days=1))
        if cursor <= end:
            gaps.append((cursor, end))
        return gaps
