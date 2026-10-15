"""Data models and enums for the Statutory Rules and Validation Engine."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Severity(str, Enum):
    """Severity classification for validation findings."""
    FATAL_SCHEMA = "FATAL_SCHEMA"         # Immediate rejection by CBDT e-Filing upload portal
    DEFECTIVE_139_9 = "DEFECTIVE_139_9"   # Defective return notice under Section 139(9)
    STATUTORY_ERROR = "STATUTORY_ERROR"   # Non-compliance with Income Tax Act / Rules 1962
    AUDIT_WARNING = "AUDIT_WARNING"       # Scrutiny inconsistency, roundoff flag, or missing optional field
    INFO = "INFO"                         # Informational validation confirmation


class RuleCategory(str, Enum):
    """Category of the tax / validation rule."""
    CBDT_SCHEMA = "CBDT JSON Schema (AY 2026-27)"
    STATUTORY_RULES = "Statutory Tax Rules (IT Act & Rules 1962)"
    CBDT_SYSTEMS_PDF = "CBDT Systems PDF Validation Rules"
    DOCUMENT_RECONCILIATION = "Document & Cross-Schedule Invariants"


class RuleStatus(str, Enum):
    """Validation outcome status."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"


@dataclass
class ValidationRuleResult:
    """Detailed result of a single statutory or schema validation rule check."""
    rule_id: str
    category: RuleCategory
    authority: str
    title: str
    description: str
    severity: Severity
    status: RuleStatus
    details: str
    field_name: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None


@dataclass
class ValidationScorecard:
    """Aggregate scorecard summarizing the validation run."""
    total_rules: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    fatal_errors: int = 0
    defective_errors: int = 0
    statutory_errors: int = 0
    is_filing_ready: bool = True

    def compute_status(self) -> str:
        if self.fatal_errors > 0:
            return "PORTAL_REJECTION_RISK"
        elif self.defective_errors > 0 or self.statutory_errors > 0:
            return "DEFECTIVE_OR_NON_COMPLIANT"
        elif self.warnings > 0:
            return "FILING_READY_WITH_WARNINGS"
        else:
            return "100%_STATUTORILY_COMPLIANT"


@dataclass
class ValidationReport:
    """Complete validation report containing all executed rule results and summary."""
    scorecard: ValidationScorecard
    results: List[ValidationRuleResult] = field(default_factory=list)

    @property
    def failures(self) -> List[ValidationRuleResult]:
        return [r for r in self.results if r.status == RuleStatus.FAILED]

    @property
    def warnings(self) -> List[ValidationRuleResult]:
        return [r for r in self.results if r.status == RuleStatus.WARNING]

    @property
    def passed_rules(self) -> List[ValidationRuleResult]:
        return [r for r in self.results if r.status == RuleStatus.PASSED]
