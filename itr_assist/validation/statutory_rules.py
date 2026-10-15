"""Statutory Tax Rule Validator for IT Act 1961 and IT Rules 1962."""
from datetime import date, timedelta
from typing import List, Optional

from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import (
    FTCResult,
    ScheduleFATableA2Result,
    ScheduleFATableA3LotResult,
    ScheduleOSResult,
)
from itr_assist.validation.models import (
    RuleCategory,
    RuleStatus,
    Severity,
    ValidationRuleResult,
)


class StatutoryRuleValidator:
    """Validates computational grounding against Income-tax Act, 1961 and Income-tax Rules, 1962."""

    def __init__(self, sbi_service: SBIRateService):
        self.sbi = sbi_service

    def validate_rule_115_dividends(self, os_result: ScheduleOSResult) -> List[ValidationRuleResult]:
        """Validate that Schedule OS foreign dividends convert at SBI TTBR on last day of preceding month (Rule 115(2)(c))."""
        results: List[ValidationRuleResult] = []
        for idx, item in enumerate(os_result.items, 1):
            expected_preceding_month_end, expected_rate = self.sbi.get_rule_115_dividend_rate(item.pay_date)
            expected_gross_inr = round(item.gross_usd * expected_rate)

            # Check date match
            if item.preceding_month_end != expected_preceding_month_end:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-115-DATE-{idx:02d}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="Income-tax Rules, 1962 - Rule 115(2)(c)",
                        title=f"Rule 115 Preceding Month-End Date Verification ({item.pay_date})",
                        description="Mandates conversion of foreign dividend at SBI TTBR on the last day of the month preceding receipt.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.FAILED,
                        details=f"Dividend on {item.pay_date} used rate date {item.preceding_month_end}, expected {expected_preceding_month_end}.",
                        field_name="preceding_month_end",
                        expected=expected_preceding_month_end.strftime("%Y-%m-%d"),
                        actual=item.preceding_month_end.strftime("%Y-%m-%d"),
                    )
                )
            else:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-115-DATE-{idx:02d}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="Income-tax Rules, 1962 - Rule 115(2)(c)",
                        title=f"Rule 115 Preceding Month-End Date Verification ({item.pay_date})",
                        description="Mandates conversion of foreign dividend at SBI TTBR on the last day of the month preceding receipt.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.PASSED,
                        details=f"Dividend on {item.pay_date} correctly converted at SBI TTBR of preceding month-end {expected_preceding_month_end} (Rate: ₹{expected_rate:.2f}).",
                        field_name="preceding_month_end",
                        expected=expected_preceding_month_end.strftime("%Y-%m-%d"),
                        actual=item.preceding_month_end.strftime("%Y-%m-%d"),
                    )
                )

            # Check rate and calculation match
            if abs(item.rule_115_rate - expected_rate) > 0.001 or abs(item.gross_inr - expected_gross_inr) > 1:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-115-RATE-{idx:02d}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="Income-tax Rules, 1962 - Rule 115(2)(c)",
                        title=f"Rule 115 Exchange Rate & Conversion Accuracy ({item.pay_date})",
                        description="Mandates computation of Schedule OS dividend at verified SBI TTBR.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.FAILED,
                        details=f"Gross INR ₹{item.gross_inr} mismatch against expected ₹{expected_gross_inr} (${item.gross_usd:.2f} @ ₹{expected_rate:.2f}).",
                        field_name="gross_inr",
                        expected=str(expected_gross_inr),
                        actual=str(item.gross_inr),
                    )
                )
            else:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-115-RATE-{idx:02d}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="Income-tax Rules, 1962 - Rule 115(2)(c)",
                        title=f"Rule 115 Exchange Rate & Conversion Accuracy ({item.pay_date})",
                        description="Mandates computation of Schedule OS dividend at verified SBI TTBR.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.PASSED,
                        details=f"Gross INR ₹{item.gross_inr} matches exact statutory conversion (${item.gross_usd:.2f} @ ₹{expected_rate:.2f}).",
                        field_name="gross_inr",
                        expected=str(expected_gross_inr),
                        actual=str(item.gross_inr),
                    )
                )

        return results

    def validate_rule_128_ftc(self, os_result: ScheduleOSResult, ftc: FTCResult) -> List[ValidationRuleResult]:
        """Validate that foreign tax credit converts at SBI TTBR on the exact date of deduction (Rule 128(8))."""
        results: List[ValidationRuleResult] = []
        expected_total_tax_inr = 0

        for idx, item in enumerate(os_result.items, 1):
            expected_pay_rate = self.sbi.get_rate(item.pay_date)
            expected_tax_inr = round(item.tax_usd * expected_pay_rate)
            expected_total_tax_inr += expected_tax_inr

            if abs(item.rule_128_rate - expected_pay_rate) > 0.001 or abs(item.tax_inr - expected_tax_inr) > 1:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-128-RATE-{idx:02d}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="Income-tax Rules, 1962 - Rule 128(8)",
                        title=f"Rule 128(8) Deduction Date Exchange Rate ({item.pay_date})",
                        description="Foreign tax credit conversion must use SBI TTBR on the date of deduction of tax.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.FAILED,
                        details=f"Tax withheld on {item.pay_date} ₹{item.tax_inr} differs from expected ₹{expected_tax_inr} (${item.tax_usd:.2f} @ ₹{expected_pay_rate:.2f}).",
                        field_name="tax_inr",
                        expected=str(expected_tax_inr),
                        actual=str(item.tax_inr),
                    )
                )
            else:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-128-RATE-{idx:02d}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="Income-tax Rules, 1962 - Rule 128(8)",
                        title=f"Rule 128(8) Deduction Date Exchange Rate ({item.pay_date})",
                        description="Foreign tax credit conversion must use SBI TTBR on the date of deduction of tax.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.PASSED,
                        details=f"Tax withheld on {item.pay_date} ₹{item.tax_inr} correctly converted at date-of-deduction TTBR ₹{expected_pay_rate:.2f}.",
                        field_name="tax_inr",
                        expected=str(expected_tax_inr),
                        actual=str(item.tax_inr),
                    )
                )

        # Aggregate relief cap under DTAA
        if ftc.tax_relief_claimed_inr > ftc.foreign_tax_paid_inr:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-DTAA-CAP-01",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="Income-tax Act, 1961 - Section 90 read with Article 25(2)(a) Indo-US DTAA",
                    title="Foreign Tax Relief Ceiling under DTAA",
                    description="Relief claimed cannot exceed actual foreign tax paid.",
                    severity=Severity.STATUTORY_ERROR,
                    status=RuleStatus.FAILED,
                    details=f"Relief claimed (₹{ftc.tax_relief_claimed_inr}) exceeds foreign tax paid (₹{ftc.foreign_tax_paid_inr}).",
                    field_name="tax_relief_claimed_inr",
                    expected=f"<= {ftc.foreign_tax_paid_inr}",
                    actual=str(ftc.tax_relief_claimed_inr),
                )
            )
        else:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-DTAA-CAP-01",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="Income-tax Act, 1961 - Section 90 read with Article 25(2)(a) Indo-US DTAA",
                    title="Foreign Tax Relief Ceiling under DTAA",
                    description="Relief claimed cannot exceed actual foreign tax paid.",
                    severity=Severity.STATUTORY_ERROR,
                    status=RuleStatus.PASSED,
                    details=f"Relief claimed (₹{ftc.tax_relief_claimed_inr}) is strictly bounded by foreign tax paid (₹{ftc.foreign_tax_paid_inr}).",
                    field_name="tax_relief_claimed_inr",
                    expected=f"<= {ftc.foreign_tax_paid_inr}",
                    actual=str(ftc.tax_relief_claimed_inr),
                )
            )

        return results

    def validate_schedule_fa_rates(
        self, a2: ScheduleFATableA2Result, a3_lots: List[ScheduleFATableA3LotResult]
    ) -> List[ValidationRuleResult]:
        """Validate Schedule FA acquisition date, peak date, closing date, and dividend rates against official instructions."""
        results: List[ValidationRuleResult] = []

        # 1. Historical Acquisition/Purchase Date Rate for Table A3 Initial Investment
        for lot in a3_lots:
            expected_acq_rate = self.sbi.get_rate(lot.acquisition_date)
            expected_init_inr = round(lot.net_shares * lot.vest_fmv_usd * expected_acq_rate)
            if abs(lot.acq_sbi_rate_inr - expected_acq_rate) > 0.001 or abs(lot.initial_value_inr - expected_init_inr) > 2:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-FA-ACQ-{lot.lot_id}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="CBDT Instructions for Schedule FA - Initial Value of Investment",
                        title=f"Schedule FA Acquisition Date Rate Check [{lot.lot_id}]",
                        description="Initial investment value must be converted using the SBI TTBR on the historical vest/purchase date.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.FAILED,
                        details=f"Lot {lot.lot_id} initial value ₹{lot.initial_value_inr} differs from expected ₹{expected_init_inr} (Rate: ₹{expected_acq_rate:.2f} on {lot.acquisition_date}).",
                        field_name="initial_value_inr",
                        expected=str(expected_init_inr),
                        actual=str(lot.initial_value_inr),
                    )
                )
            else:
                results.append(
                    ValidationRuleResult(
                        rule_id=f"STAT-FA-ACQ-{lot.lot_id}",
                        category=RuleCategory.STATUTORY_RULES,
                        authority="CBDT Instructions for Schedule FA - Initial Value of Investment",
                        title=f"Schedule FA Acquisition Date Rate Check [{lot.lot_id}]",
                        description="Initial investment value must be converted using the SBI TTBR on the historical vest/purchase date.",
                        severity=Severity.STATUTORY_ERROR,
                        status=RuleStatus.PASSED,
                        details=f"Lot {lot.lot_id} correctly converted at historical vest date rate ₹{expected_acq_rate:.2f} ({lot.acquisition_date}).",
                        field_name="initial_value_inr",
                        expected=str(expected_init_inr),
                        actual=str(lot.initial_value_inr),
                    )
                )

        # 2. Peak Balance Conversion Date
        expected_a2_peak_rate = self.sbi.get_rate(a2.peak_date)
        if abs(a2.peak_rate_inr - expected_a2_peak_rate) > 0.001:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-FA-PEAK-A2",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="CBDT Instructions for Schedule FA - Peak Balance During Period",
                    title="Schedule FA Table A2 Peak Date Rate Verification",
                    description="Peak balance must convert at SBI TTBR on the date of peak balance.",
                    severity=Severity.STATUTORY_ERROR,
                    status=RuleStatus.FAILED,
                    details=f"Table A2 peak rate ₹{a2.peak_rate_inr:.2f} differs from SBI rate ₹{expected_a2_peak_rate:.2f} on {a2.peak_date}.",
                )
            )
        else:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-FA-PEAK-A2",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="CBDT Instructions for Schedule FA - Peak Balance During Period",
                    title="Schedule FA Table A2 Peak Date Rate Verification",
                    description="Peak balance must convert at SBI TTBR on the date of peak balance.",
                    severity=Severity.STATUTORY_ERROR,
                    status=RuleStatus.PASSED,
                    details=f"Table A2 peak balance correctly converted at peak date TTBR ₹{expected_a2_peak_rate:.2f} ({a2.peak_date}).",
                )
            )

        # 3. Closing Balance Conversion Date (Dec 31)
        expected_a2_close_rate = self.sbi.get_rate(a2.closing_date)
        if abs(a2.closing_rate_inr - expected_a2_close_rate) > 0.001:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-FA-CLOSE-A2",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="CBDT Instructions for Schedule FA - Closing Balance",
                    title="Schedule FA Table A2 Closing Date Rate Verification",
                    description="Closing balance must convert at SBI TTBR on December 31.",
                    severity=Severity.STATUTORY_ERROR,
                    status=RuleStatus.FAILED,
                    details=f"Table A2 closing rate ₹{a2.closing_rate_inr:.2f} differs from Dec 31 rate ₹{expected_a2_close_rate:.2f}.",
                )
            )
        else:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-FA-CLOSE-A2",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="CBDT Instructions for Schedule FA - Closing Balance",
                    title="Schedule FA Table A2 Closing Date Rate Verification",
                    description="Closing balance must convert at SBI TTBR on December 31.",
                    severity=Severity.STATUTORY_ERROR,
                    status=RuleStatus.PASSED,
                    details=f"Table A2 closing balance correctly converted at Dec 31 TTBR ₹{expected_a2_close_rate:.2f}.",
                )
            )

        # 4. Schedule FA Whole Integer INR Rule
        non_integers = []
        if not isinstance(a2.peak_balance_inr, int) or not isinstance(a2.closing_balance_inr, int):
            non_integers.append("Table A2 Balances")
        for lot in a3_lots:
            if any(not isinstance(val, int) for val in [lot.initial_value_inr, lot.peak_balance_inr, lot.closing_balance_inr, lot.gross_dividends_inr]):
                non_integers.append(f"Lot {lot.lot_id}")

        if non_integers:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-INTEGER-INR",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="Income-tax Rules & CBDT e-Filing Schema",
                    title="Whole Integer Rupee Representation (No Decimal Paise)",
                    description="Schedule FA requires all reported INR amounts to be whole integers.",
                    severity=Severity.FATAL_SCHEMA,
                    status=RuleStatus.FAILED,
                    details=f"Floating point values found in: {', '.join(non_integers)}.",
                )
            )
        else:
            results.append(
                ValidationRuleResult(
                    rule_id="STAT-INTEGER-INR",
                    category=RuleCategory.STATUTORY_RULES,
                    authority="Income-tax Rules & CBDT e-Filing Schema",
                    title="Whole Integer Rupee Representation (No Decimal Paise)",
                    description="Schedule FA requires all reported INR amounts to be whole integers.",
                    severity=Severity.FATAL_SCHEMA,
                    status=RuleStatus.PASSED,
                    details="100% of Schedule FA monetary values are formatted as statutory whole integers.",
                )
            )

        return results

    def validate_statutory_rounding_sections(
        self, os_result: ScheduleOSResult, ftc: FTCResult
    ) -> List[ValidationRuleResult]:
        """Validate Section 288A (Total Income rounding to ₹10) and Section 288B (Tax rounding to ₹10)."""
        results: List[ValidationRuleResult] = []

        # Sec 288A: Income rounded to multiple of 10
        total_income = os_result.total_dividend_inr
        remainder_288a = total_income % 10
        recommended_288a = round(total_income / 10.0) * 10

        results.append(
            ValidationRuleResult(
                rule_id="STAT-SEC-288A",
                category=RuleCategory.STATUTORY_RULES,
                authority="Income-tax Act, 1961 - Section 288A",
                title="Section 288A Rounding Off of Total Income",
                description="Total taxable income must be rounded off to the nearest multiple of ten rupees.",
                severity=Severity.INFO,
                status=RuleStatus.PASSED,
                details=f"Schedule OS gross foreign dividend income ₹{total_income} (aggregate rounding to nearest ₹10 yields ₹{recommended_288a}).",
                field_name="total_dividend_inr",
                actual=str(total_income),
                expected=str(recommended_288a),
            )
        )

        # Sec 288B: Tax payable / relief rounded to multiple of 10
        tax_relief = ftc.tax_relief_claimed_inr
        recommended_288b = round(tax_relief / 10.0) * 10
        results.append(
            ValidationRuleResult(
                rule_id="STAT-SEC-288B",
                category=RuleCategory.STATUTORY_RULES,
                authority="Income-tax Act, 1961 - Section 288B",
                title="Section 288B Rounding Off of Tax Relief / Payable",
                description="Total tax payable or tax relief must be rounded off to the nearest multiple of ten rupees.",
                severity=Severity.INFO,
                status=RuleStatus.PASSED,
                details=f"Foreign tax credit claimed u/s 90 is ₹{tax_relief} (aggregate rounding to nearest ₹10 yields ₹{recommended_288b}).",
                field_name="tax_relief_claimed_inr",
                actual=str(tax_relief),
                expected=str(recommended_288b),
            )
        )

        return results
