"""Accounting, Valuation, and Cross-Document Invariant Validators."""
from datetime import date, timedelta
from typing import List, Optional, Tuple

from itr_assist.models import Form1042SData, SaleEvent, ShareLot, StatementPeriodSummary
from itr_assist.services.valuation import (
    ScheduleFATableA2Result,
    ScheduleFATableA3LotResult,
)
from itr_assist.validation.models import (
    RuleCategory,
    RuleStatus,
    Severity,
    ValidationRuleResult,
)


def find_coverage_gaps(
    summaries: List[StatementPeriodSummary], required_start: date, required_end: date
) -> List[Tuple[date, date]]:
    """Return the sub-ranges of [required_start, required_end] covered by no statement period."""
    gaps: List[Tuple[date, date]] = []
    cursor = required_start  # first day not yet known to be covered
    for start, end in sorted((s.start_date, s.end_date) for s in summaries):
        if cursor > required_end:
            break
        if start > cursor:
            gaps.append((cursor, min(start - timedelta(days=1), required_end)))
        cursor = max(cursor, end + timedelta(days=1))
    if cursor <= required_end:
        gaps.append((cursor, required_end))
    return gaps


class InvariantValidator:
    """Validates accounting invariants and cross-document reconciliation integrity."""

    def validate_statement_coverage(
        self,
        summaries: List[StatementPeriodSummary],
        lots: List[ShareLot],
        calendar_year: int,
    ) -> List[ValidationRuleResult]:
        """Statements must continuously cover every day a sale or dividend could affect this
        filing: from the earliest lot's acquisition through the end of the Indian FY.

        A sale only reaches the lot ledger if a supplied statement shows it, so a lot sold
        during an uncovered stretch is never marked disposed and stays in Schedule FA Table A3
        as if still held (and dividends in that stretch go missing). This rule turns that
        silent overstatement into a hard, visible failure naming the exact missing periods.
        """
        cy_end = date(calendar_year, 12, 31)
        relevant_acquisitions = [l.acquisition_date for l in lots if l.acquisition_date <= cy_end]
        required_start = min(relevant_acquisitions) if relevant_acquisitions else date(calendar_year, 1, 1)
        required_end = date(calendar_year + 1, 3, 31)
        gaps = find_coverage_gaps(summaries, required_start, required_end)

        common = dict(
            rule_id="INV-STATEMENT-COVERAGE",
            category=RuleCategory.DOCUMENT_RECONCILIATION,
            authority="Cross-Document Reconciliation (Statement Coverage vs Lot History)",
            title="Broker Statements Cover Full Holding History",
            description=(
                "Statements must cover every day from the first vest/purchase through 31 March "
                "after the calendar year, or sales/dividends in the gaps go undetected."
            ),
        )
        if gaps:
            gap_text = "; ".join(f"{s.isoformat()} to {e.isoformat()}" for s, e in gaps)
            return [ValidationRuleResult(
                **common,
                severity=Severity.STATUTORY_ERROR,
                status=RuleStatus.FAILED,
                details=(
                    f"No statement covers: {gap_text}. Any shares sold in these periods are still "
                    f"reported as held in Table A3 (overstating foreign assets), and dividends in "
                    f"them are missing. Upload the statements for these periods and regenerate."
                ),
            )]
        return [ValidationRuleResult(
            **common,
            severity=Severity.STATUTORY_ERROR,
            status=RuleStatus.PASSED,
            details=f"Statements continuously cover {required_start.isoformat()} to {required_end.isoformat()}.",
        )]

    def validate_peak_closing_invariants(
        self, a2: ScheduleFATableA2Result, a3_lots: List[ScheduleFATableA3LotResult]
    ) -> List[ValidationRuleResult]:
        """Validate that peak balance is mathematically greater than or equal to closing balance."""
        results: List[ValidationRuleResult] = []

        # 1. Table A2 Peak >= Closing Invariant
        if a2.peak_balance_inr < a2.closing_balance_inr:
            results.append(
                ValidationRuleResult(
                    rule_id="INV-PEAK-CLOSE-A2",
                    category=RuleCategory.DOCUMENT_RECONCILIATION,
                    authority="CBDT Schedule FA Principles & Inherent Valuation Logic",
                    title="Table A2 Peak Balance >= Closing Balance Invariant",
                    description="The peak balance during the calendar year cannot be lower than the closing balance.",
                    severity=Severity.AUDIT_WARNING,
                    status=RuleStatus.FAILED,
                    details=f"Table A2 peak balance (₹{a2.peak_balance_inr}) is less than closing balance (₹{a2.closing_balance_inr}).",
                    field_name="PeakBalanceDuringPeriod",
                    expected=f">= {a2.closing_balance_inr}",
                    actual=str(a2.peak_balance_inr),
                )
            )
        else:
            results.append(
                ValidationRuleResult(
                    rule_id="INV-PEAK-CLOSE-A2",
                    category=RuleCategory.DOCUMENT_RECONCILIATION,
                    authority="CBDT Schedule FA Principles & Inherent Valuation Logic",
                    title="Table A2 Peak Balance >= Closing Balance Invariant",
                    description="The peak balance during the calendar year cannot be lower than the closing balance.",
                    severity=Severity.AUDIT_WARNING,
                    status=RuleStatus.PASSED,
                    details=f"Table A2 peak balance (₹{a2.peak_balance_inr} on {a2.peak_date}) is >= closing balance (₹{a2.closing_balance_inr}).",
                    field_name="PeakBalanceDuringPeriod",
                    expected=f">= {a2.closing_balance_inr}",
                    actual=str(a2.peak_balance_inr),
                )
            )

        # 2. Table A3 Peak >= Closing Invariant per lot
        lot_failures = []
        for lot in a3_lots:
            if lot.peak_balance_inr < lot.closing_balance_inr:
                lot_failures.append(f"Lot {lot.lot_id} (Peak ₹{lot.peak_balance_inr} < Close ₹{lot.closing_balance_inr})")

        if lot_failures:
            results.append(
                ValidationRuleResult(
                    rule_id="INV-PEAK-CLOSE-A3",
                    category=RuleCategory.DOCUMENT_RECONCILIATION,
                    authority="CBDT Schedule FA Principles & Inherent Valuation Logic",
                    title="Table A3 Peak Balance >= Closing Balance Invariant",
                    description="Every active lot's peak balance during the calendar year must be >= its closing balance.",
                    severity=Severity.AUDIT_WARNING,
                    status=RuleStatus.FAILED,
                    details=f"Violations detected in: {'; '.join(lot_failures)}.",
                )
            )
        else:
            results.append(
                ValidationRuleResult(
                    rule_id="INV-PEAK-CLOSE-A3",
                    category=RuleCategory.DOCUMENT_RECONCILIATION,
                    authority="CBDT Schedule FA Principles & Inherent Valuation Logic",
                    title="Table A3 Peak Balance >= Closing Balance Invariant",
                    description="Every active lot's peak balance during the calendar year must be >= its closing balance.",
                    severity=Severity.AUDIT_WARNING,
                    status=RuleStatus.PASSED,
                    details=f"All {len(a3_lots)} Table A3 lots satisfy Peak Balance >= Closing Balance.",
                )
            )

        return results

    def validate_cross_document_reconciliation(
        self,
        form_1042s: Optional[Form1042SData],
        cy_dividends_usd: float,
        cy_tax_withheld_usd: float,
        sales: Optional[List[SaleEvent]] = None,
    ) -> List[ValidationRuleResult]:
        """Validate cross-document reconciliation against Form 1042-S and sale-to-lot allocation."""
        results: List[ValidationRuleResult] = []

        # 0. Fully-matched sale allocation (LotLedger.allocate_sales() silently under-allocates
        # when fewer shares remain across candidate lots than a sale needs - e.g. the lot that
        # was actually sold vested/was disposed in a year whose statements weren't supplied).
        # Flag it instead of letting Table A3 gross proceeds quietly understate the real figure.
        unmatched_sales = [s for s in (sales or []) if s.unmatched_quantity > 1e-6]
        if unmatched_sales:
            details = "; ".join(
                f"{s.sale_date.isoformat()}: {s.unmatched_quantity:.2f} of {s.quantity:.2f} shares "
                f"sold could not be matched to any active lot (likely sold/disposed in a year "
                f"whose statements weren't supplied) - gross proceeds for this sale are understated"
                for s in unmatched_sales
            )
            results.append(
                ValidationRuleResult(
                    rule_id="INV-SALE-ALLOCATION-COMPLETE",
                    category=RuleCategory.DOCUMENT_RECONCILIATION,
                    authority="Cross-Document Reconciliation (Sale Events vs Benefit History Lots)",
                    title="Sale Quantity Fully Matched to Active Lots",
                    description="Every parsed sale must FIFO-match in full against lots with enough remaining shares.",
                    severity=Severity.AUDIT_WARNING,
                    status=RuleStatus.FAILED,
                    details=details,
                )
            )
        elif sales:
            results.append(
                ValidationRuleResult(
                    rule_id="INV-SALE-ALLOCATION-COMPLETE",
                    category=RuleCategory.DOCUMENT_RECONCILIATION,
                    authority="Cross-Document Reconciliation (Sale Events vs Benefit History Lots)",
                    title="Sale Quantity Fully Matched to Active Lots",
                    description="Every parsed sale must FIFO-match in full against lots with enough remaining shares.",
                    severity=Severity.AUDIT_WARNING,
                    status=RuleStatus.PASSED,
                    details=f"All {len(sales)} parsed sale(s) fully matched to active lots.",
                )
            )

        # (No "reconstructed shares vs Current Holdings export" parity rule: the holdings export
        # is a live as-of-today snapshot while the reconstruction stops at the filing year's
        # last statement, so for anyone who sold after that year it always fails - a timing
        # artifact, not an error in the return. Removed rather than shown as a misleading red.)

        # Form 1042-S Dividend Reconciliation (tolerance <= $1.00)
        if form_1042s:
            div_diff = abs(cy_dividends_usd - form_1042s.gross_dividend_usd)
            if div_diff <= 1.0:
                results.append(
                    ValidationRuleResult(
                        rule_id="INV-1042S-DIV-RECON",
                        category=RuleCategory.DOCUMENT_RECONCILIATION,
                        authority="IRS Form 1042-S Box 2 vs Monthly Broker Statements",
                        title="CY Statement Gross Dividend Reconciled with Form 1042-S",
                        description="Statement gross dividend must match IRS Form 1042-S Box 2 within $1.00 IRS roundoff tolerance.",
                        severity=Severity.AUDIT_WARNING,
                        status=RuleStatus.PASSED,
                        details=f"Statement gross dividend (${cy_dividends_usd:.2f}) reconciles with Form 1042-S Box 2 (${form_1042s.gross_dividend_usd:.2f}) within ${div_diff:.2f}.",
                        field_name="gross_dividend_usd",
                        expected=f"${form_1042s.gross_dividend_usd:.2f} +/- $1.00",
                        actual=f"${cy_dividends_usd:.2f}",
                    )
                )
            else:
                results.append(
                    ValidationRuleResult(
                        rule_id="INV-1042S-DIV-RECON",
                        category=RuleCategory.DOCUMENT_RECONCILIATION,
                        authority="IRS Form 1042-S Box 2 vs Monthly Broker Statements",
                        title="CY Statement Gross Dividend Reconciled with Form 1042-S",
                        description="Statement gross dividend must match IRS Form 1042-S Box 2 within $1.00 IRS roundoff tolerance.",
                        severity=Severity.AUDIT_WARNING,
                        status=RuleStatus.FAILED,
                        details=f"Discrepancy of ${div_diff:.2f} between Statement (${cy_dividends_usd:.2f}) and Form 1042-S Box 2 (${form_1042s.gross_dividend_usd:.2f}).",
                        field_name="gross_dividend_usd",
                        expected=f"${form_1042s.gross_dividend_usd:.2f}",
                        actual=f"${cy_dividends_usd:.2f}",
                    )
                )

            # 3. Form 1042-S Tax Withheld Reconciliation (tolerance <= $1.00)
            tax_diff = abs(cy_tax_withheld_usd - form_1042s.tax_withheld_usd)
            if tax_diff <= 1.0:
                results.append(
                    ValidationRuleResult(
                        rule_id="INV-1042S-TAX-RECON",
                        category=RuleCategory.DOCUMENT_RECONCILIATION,
                        authority="IRS Form 1042-S Box 7a vs Monthly Broker Statements",
                        title="CY Statement Tax Withheld Reconciled with Form 1042-S",
                        description="Statement tax withheld must match IRS Form 1042-S Box 7a within $1.00 IRS roundoff tolerance.",
                        severity=Severity.AUDIT_WARNING,
                        status=RuleStatus.PASSED,
                        details=f"Statement tax withheld (${cy_tax_withheld_usd:.2f}) reconciles with Form 1042-S Box 7a (${form_1042s.tax_withheld_usd:.2f}) within ${tax_diff:.2f}.",
                        field_name="tax_withheld_usd",
                        expected=f"${form_1042s.tax_withheld_usd:.2f} +/- $1.00",
                        actual=f"${cy_tax_withheld_usd:.2f}",
                    )
                )
            else:
                results.append(
                    ValidationRuleResult(
                        rule_id="INV-1042S-TAX-RECON",
                        category=RuleCategory.DOCUMENT_RECONCILIATION,
                        authority="IRS Form 1042-S Box 7a vs Monthly Broker Statements",
                        title="CY Statement Tax Withheld Reconciled with Form 1042-S",
                        description="Statement tax withheld must match IRS Form 1042-S Box 7a within $1.00 IRS roundoff tolerance.",
                        severity=Severity.AUDIT_WARNING,
                        status=RuleStatus.FAILED,
                        details=f"Discrepancy of ${tax_diff:.2f} between Statement (${cy_tax_withheld_usd:.2f}) and Form 1042-S Box 7a (${form_1042s.tax_withheld_usd:.2f}).",
                        field_name="tax_withheld_usd",
                        expected=f"${form_1042s.tax_withheld_usd:.2f}",
                        actual=f"${cy_tax_withheld_usd:.2f}",
                    )
                )

        return results
