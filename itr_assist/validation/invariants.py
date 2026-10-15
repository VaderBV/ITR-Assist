"""Accounting, Valuation, and Cross-Document Invariant Validators."""
from typing import List, Optional

from itr_assist.models import Form1042SData, ReconciliationReport
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


class InvariantValidator:
    """Validates accounting invariants and cross-document reconciliation integrity."""

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
        recon: Optional[ReconciliationReport],
        form_1042s: Optional[Form1042SData],
        cy_dividends_usd: float,
        cy_tax_withheld_usd: float,
    ) -> List[ValidationRuleResult]:
        """Validate cross-document reconciliation against Form 1042-S and share holdings ledger."""
        results: List[ValidationRuleResult] = []

        # 1. Share holdings reconciliation
        if recon:
            if recon.status == "MATCH":
                results.append(
                    ValidationRuleResult(
                        rule_id="INV-HOLDINGS-MATCH",
                        category=RuleCategory.DOCUMENT_RECONCILIATION,
                        authority="Cross-Document Reconciliation (Benefit History vs Current Holdings)",
                        title="Share Ledger Reconstruction vs Holdings Export Parity",
                        description="Reconstructed active share count must reconcile exactly with broker holdings export.",
                        severity=Severity.AUDIT_WARNING,
                        status=RuleStatus.PASSED,
                        details=f"Total active shares ({recon.total_reconstructed_shares:.2f}) match broker holdings ({recon.total_holdings_shares:.2f}) across {recon.reconstructed_lots_count} lots.",
                    )
                )
            else:
                results.append(
                    ValidationRuleResult(
                        rule_id="INV-HOLDINGS-MATCH",
                        category=RuleCategory.DOCUMENT_RECONCILIATION,
                        authority="Cross-Document Reconciliation (Benefit History vs Current Holdings)",
                        title="Share Ledger Reconstruction vs Holdings Export Parity",
                        description="Reconstructed active share count must reconcile exactly with broker holdings export.",
                        severity=Severity.AUDIT_WARNING,
                        status=RuleStatus.FAILED,
                        details=f"Discrepancies found: {'; '.join(recon.discrepancies)}.",
                    )
                )

        # 2. Form 1042-S Dividend Reconciliation (tolerance <= $1.00)
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
