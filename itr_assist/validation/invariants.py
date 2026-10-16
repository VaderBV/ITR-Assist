"""Accounting, Valuation, and Cross-Document Invariant Validators."""
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from itr_assist.models import (
    Form1042SData,
    SaleEvent,
    ShareLot,
    StatementPeriodSummary,
    is_placeholder,
)
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

    def validate_placeholders(
        self,
        a2: ScheduleFATableA2Result,
        a3_lots: List[ScheduleFATableA3LotResult],
        taxpayer_fields: Optional[Dict[str, str]] = None,
    ) -> List[ValidationRuleResult]:
        """No statutory field may still hold a "TO BE FILLED" stand-in.

        Company/broker addresses, ZIP codes and the account opening date are not on any broker
        document. They used to be filled with invented values ("00000", "2021-01-01") that passed
        every check; now they are placeholders and this rule fails until the taxpayer supplies them.
        """
        missing: List[str] = []
        a2_fields = [
            ("broker name", a2.financial_inst_name),
            ("broker address", a2.financial_inst_address),
            ("broker ZIP", a2.zip_code),
            ("account number", a2.account_number),
            ("account opening date", a2.account_open_date),
        ]
        a2_missing = [label for label, value in a2_fields if is_placeholder(value)]
        if a2_missing:
            missing.append("Table A2: " + ", ".join(a2_missing))

        a3_missing: List[str] = []
        for label, attr in (("company name", "name_of_entity"), ("company address", "address_of_entity"), ("company ZIP", "zip_code")):
            if any(is_placeholder(getattr(lot, attr)) for lot in a3_lots):
                a3_missing.append(label)
        if a3_missing:
            missing.append("Table A3: " + ", ".join(a3_missing))

        tp_missing = [label for label, value in (taxpayer_fields or {}).items() if is_placeholder(value)]
        if tp_missing:
            missing.append("Taxpayer: " + ", ".join(tp_missing))

        common = dict(
            rule_id="INV-NO-PLACEHOLDERS",
            category=RuleCategory.CBDT_SCHEMA,
            authority="CBDT e-Filing mandatory fields (Schedule FA Tables A2/A3)",
            title="Mandatory Details Supplied (no stand-in values)",
            description=(
                "Details no broker document contains (addresses, ZIP codes, account opening date) "
                "must be supplied by the taxpayer, never invented."
            ),
            severity=Severity.DEFECTIVE_139_9,
        )
        if missing:
            return [ValidationRuleResult(
                **common,
                status=RuleStatus.FAILED,
                details=(
                    "Still to be filled in: " + "; ".join(missing) + ". Enter them under 'Details your "
                    "documents don't contain' (or the matching command-line options) and regenerate."
                ),
            )]
        return [ValidationRuleResult(
            **common,
            status=RuleStatus.PASSED,
            details="Every mandatory Table A2/A3 detail holds a value supplied from the documents or by the taxpayer.",
        )]

    def validate_a2_integrity(
        self, a2: ScheduleFATableA2Result, a3_lots: List[ScheduleFATableA3LotResult]
    ) -> List[ValidationRuleResult]:
        """Cross-checks that make a wrong Table A2 visible instead of "100% compliant".

        1. The peak is only trusted if cash + shares x close reproduces the total the broker
           prints on every statement date of the year (catches missing cash, wrong share counts,
           bad prices - the peak itself cannot be checked against any document).
        2. A2's dividend and sale-proceeds rows must equal what Table A3 reports for the same
           lots (catches an income row that is missing or wrongly converted).
        """
        results: List[ValidationRuleResult] = []

        peak_common = dict(
            rule_id="INV-A2-PEAK-VERIFIED",
            category=RuleCategory.DOCUMENT_RECONCILIATION,
            authority="Statement reconciliation (cash + shares x close vs printed account total)",
            title="Table A2 Peak Reproduces Broker Statement Totals",
            description=(
                "The valuation behind the peak balance must reproduce the account total printed on "
                "every statement of the calendar year."
            ),
            severity=Severity.AUDIT_WARNING,
            field_name="PeakBalanceDuringPeriod",
        )
        if a2.peak_notes:
            results.append(ValidationRuleResult(
                **peak_common, status=RuleStatus.FAILED,
                details="Peak not verified: " + " ".join(a2.peak_notes),
            ))
        elif not a2.model_checks:
            results.append(ValidationRuleResult(
                **peak_common, status=RuleStatus.WARNING,
                details="No statement ending in the calendar year could be checked against the valuation.",
            ))
        else:
            first, last = a2.model_checks[0][0], a2.model_checks[-1][0]
            results.append(ValidationRuleResult(
                **peak_common, status=RuleStatus.PASSED,
                details=(
                    f"Cash + shares x close equals the printed account total on all "
                    f"{len(a2.model_checks)} statement dates ({first} to {last}); peak "
                    f"₹{a2.peak_balance_inr:,} on {a2.peak_date}."
                ),
            ))

        by_nature = {g.nature: g.amount_inr for g in a2.gross_amounts}
        tolerance = max(5, len(a3_lots))  # each lot rounds on its own; a few rupees of drift is rounding
        problems: List[str] = []
        for nature, label, a3_total in (
            ("D", "dividends", sum(l.gross_dividends_inr for l in a3_lots)),
            ("S", "sale proceeds", sum(l.gross_proceeds_inr for l in a3_lots)),
        ):
            a2_total = by_nature.get(nature, 0)
            if abs(a2_total - a3_total) > tolerance:
                problems.append(f"{label}: Table A2 reports ₹{a2_total:,} but Table A3 lots add up to ₹{a3_total:,}")
        income_common = dict(
            rule_id="INV-A2-A3-INCOME",
            category=RuleCategory.DOCUMENT_RECONCILIATION,
            authority="Cross-schedule consistency (Table A2 gross amounts vs Table A3 lot totals)",
            title="Table A2 Income Rows Agree With Table A3",
            description="Dividends and sale proceeds credited to the account must match the lot-level totals.",
            severity=Severity.AUDIT_WARNING,
        )
        if problems:
            results.append(ValidationRuleResult(
                **income_common, status=RuleStatus.FAILED,
                details="; ".join(problems) + ". A row may be missing or shares may be unmatched to lots.",
            ))
        else:
            results.append(ValidationRuleResult(
                **income_common, status=RuleStatus.PASSED,
                details=f"Table A2 dividend and sale-proceeds rows agree with Table A3 within ₹{tolerance}.",
            ))
        return results

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
