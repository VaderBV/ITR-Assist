"""Unified Validation Engine orchestrating schema, statutory, PDF, and invariant rules."""
from typing import List, Optional

from itr_assist.models import Form1042SData, ReconciliationReport
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import (
    FTCResult,
    ScheduleFATableA2Result,
    ScheduleFATableA3LotResult,
    ScheduleOSResult,
)
from itr_assist.validation.cbdt_pdf_rules import CBDTPDFRuleValidator
from itr_assist.validation.invariants import InvariantValidator
from itr_assist.validation.models import (
    RuleStatus,
    Severity,
    ValidationReport,
    ValidationRuleResult,
    ValidationScorecard,
)
from itr_assist.validation.schema_validator import CBDTSchemaValidator
from itr_assist.validation.statutory_rules import StatutoryRuleValidator


class ValidationEngine:
    """Master orchestrator for all statutory, schema, and cross-schedule validation checks."""

    def __init__(self, sbi_service: SBIRateService, schema_path: Optional[str] = None):
        self.sbi_service = sbi_service
        self.schema_validator = CBDTSchemaValidator(schema_path=schema_path)
        self.statutory_validator = StatutoryRuleValidator(sbi_service=sbi_service)
        self.pdf_validator = CBDTPDFRuleValidator()
        self.invariant_validator = InvariantValidator()

    def validate(
        self,
        a2: ScheduleFATableA2Result,
        a3_lots: List[ScheduleFATableA3LotResult],
        os_result: ScheduleOSResult,
        ftc: FTCResult,
        recon: Optional[ReconciliationReport] = None,
        form_1042s: Optional[Form1042SData] = None,
        cy_dividends_usd: float = 0.0,
        cy_tax_withheld_usd: float = 0.0,
        is_resident: bool = True,
        part_b_tti_sl19_yes: bool = True,
    ) -> ValidationReport:
        """Run all validation tiers and produce an authoritative validation report."""
        all_results: List[ValidationRuleResult] = []

        # 1. CBDT JSON Schema Conformance
        all_results.extend(self.schema_validator.validate_table_a2(a2))
        all_results.extend(self.schema_validator.validate_table_a3(a3_lots))
        all_results.extend(self.schema_validator.validate_schedule_fsi(ftc, os_result))
        all_results.extend(self.schema_validator.validate_schedule_tr(ftc))

        # 2. Statutory Rules (Rule 115, Rule 128, Sec 90, Sec 288A/B)
        all_results.extend(self.statutory_validator.validate_rule_115_dividends(os_result))
        all_results.extend(self.statutory_validator.validate_rule_128_ftc(os_result, ftc))
        all_results.extend(self.statutory_validator.validate_schedule_fa_rates(a2, a3_lots))
        all_results.extend(self.statutory_validator.validate_statutory_rounding_sections(os_result, ftc))

        # 3. CBDT Systems PDF Validation Rules
        all_results.extend(
            self.pdf_validator.validate_rules(
                a2=a2,
                a3_lots=a3_lots,
                os_result=os_result,
                ftc=ftc,
                is_resident=is_resident,
                part_b_tti_sl19_yes=part_b_tti_sl19_yes,
            )
        )

        # 4. Valuation Invariants & Document Reconciliation
        all_results.extend(self.invariant_validator.validate_peak_closing_invariants(a2, a3_lots))
        all_results.extend(
            self.invariant_validator.validate_cross_document_reconciliation(
                recon=recon,
                form_1042s=form_1042s,
                cy_dividends_usd=cy_dividends_usd,
                cy_tax_withheld_usd=cy_tax_withheld_usd,
            )
        )

        # Compute Scorecard metrics
        scorecard = ValidationScorecard(
            total_rules=len(all_results),
            passed=sum(1 for r in all_results if r.status == RuleStatus.PASSED),
            failed=sum(1 for r in all_results if r.status == RuleStatus.FAILED),
            warnings=sum(1 for r in all_results if r.status == RuleStatus.WARNING),
            fatal_errors=sum(
                1 for r in all_results if r.status == RuleStatus.FAILED and r.severity == Severity.FATAL_SCHEMA
            ),
            defective_errors=sum(
                1 for r in all_results if r.status == RuleStatus.FAILED and r.severity == Severity.DEFECTIVE_139_9
            ),
            statutory_errors=sum(
                1 for r in all_results if r.status == RuleStatus.FAILED and r.severity == Severity.STATUTORY_ERROR
            ),
        )
        scorecard.is_filing_ready = (scorecard.fatal_errors == 0 and scorecard.defective_errors == 0 and scorecard.statutory_errors == 0)

        return ValidationReport(scorecard=scorecard, results=all_results)
