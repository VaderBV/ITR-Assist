"""CBDT JSON Schema Validator for ITR-2 Foreign Asset Schedules."""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema
from jsonschema import Draft4Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT4

from itr_assist.models import ShareLot
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


class CBDTSchemaValidator:
    """Validates foreign asset schedule objects directly against official CBDT JSON Schema."""

    def __init__(self, schema_path: Optional[str] = None):
        if schema_path is None:
            # Look in typical project locations
            potential_paths = [
                Path("ITR-2_2026_Main_V1.2.json"),
                Path(__file__).parent.parent.parent / "ITR-2_2026_Main_V1.2.json",
                Path(__file__).parent.parent / "ITR-2_2026_Main_V1.2.json",
            ]
            for p in potential_paths:
                if p.exists():
                    schema_path = str(p.resolve())
                    break

        if not schema_path or not os.path.exists(schema_path):
            raise FileNotFoundError(f"Official CBDT JSON Schema file not found. Checked: {schema_path}")

        self.schema_path = schema_path
        with open(self.schema_path, "r", encoding="utf-8") as f:
            self.full_schema = json.load(f)

        resource = Resource.from_contents(self.full_schema, default_specification=DRAFT4)
        self.registry = Registry().with_resource("itr2.json", resource)

    def _validate_subschema(
        self, subschema_ref: str, payload: Dict[str, Any], rule_prefix: str, schedule_name: str, item_id: str = ""
    ) -> List[ValidationRuleResult]:
        """Validate a single dict payload against a referenced definition in the CBDT schema."""
        results: List[ValidationRuleResult] = []
        sub_schema = {"$ref": f"itr2.json#/definitions/{subschema_ref}"}
        validator = Draft4Validator(sub_schema, registry=self.registry)

        errors = list(validator.iter_errors(payload))
        if not errors:
            results.append(
                ValidationRuleResult(
                    rule_id=f"{rule_prefix}-VALID",
                    category=RuleCategory.CBDT_SCHEMA,
                    authority="CBDT e-Filing Schema AY 2026-27 (ITR-2_2026_Main_V1.2.json)",
                    title=f"{schedule_name} Schema Conformance {item_id}".strip(),
                    description=f"Ensures {schedule_name} payload complies with official CBDT data types, enums, regexes, and mandatory fields.",
                    severity=Severity.FATAL_SCHEMA,
                    status=RuleStatus.PASSED,
                    details=f"All {len(payload)} properties conform strictly to definition '#/definitions/{subschema_ref}'.",
                )
            )
        else:
            for idx, err in enumerate(errors, 1):
                field_name = ".".join(str(p) for p in err.path) if err.path else "root"
                results.append(
                    ValidationRuleResult(
                        rule_id=f"{rule_prefix}-ERR-{idx:02d}",
                        category=RuleCategory.CBDT_SCHEMA,
                        authority="CBDT e-Filing Schema AY 2026-27 (ITR-2_2026_Main_V1.2.json)",
                        title=f"{schedule_name} Schema Violation on '{field_name}' {item_id}".strip(),
                        description=f"Fatal schema validation error in {schedule_name}: {err.message}",
                        severity=Severity.FATAL_SCHEMA,
                        status=RuleStatus.FAILED,
                        details=f"Portal rejection error: {err.message} at '{field_name}'.",
                        field_name=field_name,
                        actual=str(err.instance),
                    )
                )

        return results

    def validate_table_a2(self, a2: ScheduleFATableA2Result) -> List[ValidationRuleResult]:
        """Validate Table A2 Custodial Account against DtlsForeignCustodialAcc."""
        results: List[ValidationRuleResult] = []
        for index, gross in enumerate(a2.gross_amounts, start=1):
            payload = {
                "CountryName": a2.country_name,
                "CountryCodeExcludingIndia": a2.country_code,
                "FinancialInstName": a2.financial_inst_name,
                "FinancialInstAddress": a2.financial_inst_address,
                "ZipCode": a2.zip_code,
                "AccountNumber": a2.account_number,
                "Status": a2.status,
                "AccOpenDate": a2.account_open_date,
                "PeakBalanceDuringPeriod": a2.peak_balance_inr,
                "ClosingBalance": a2.closing_balance_inr,
                "GrossAmtPaidCredited": gross.amount_inr,
                "NatureOfAmount": gross.nature,
            }
            results.extend(self._validate_subschema(
                subschema_ref="DtlsForeignCustodialAcc",
                payload=payload,
                rule_prefix="SCHEMA-FA-A2",
                schedule_name="Schedule FA Table A2",
                item_id=f"[{a2.account_number}:{index}:{gross.nature}]",
            ))
        return results

    def validate_table_a3(self, a3_lots: List[ScheduleFATableA3LotResult]) -> List[ValidationRuleResult]:
        """Validate all Table A3 Equity lots against DtlsForeignEquityDebtInterest."""
        all_results: List[ValidationRuleResult] = []
        for lot in a3_lots:
            payload = {
                "CountryName": lot.country_name,
                "CountryCodeExcludingIndia": lot.country_code,
                "NameOfEntity": lot.name_of_entity,
                "AddressOfEntity": lot.address_of_entity,
                "ZipCode": lot.zip_code,
                "NatureOfEntity": lot.nature_of_entity,
                "InterestAcquiringDate": lot.acquisition_date.strftime("%Y-%m-%d"),
                "InitialValOfInvstmnt": lot.initial_value_inr,
                "PeakBalanceDuringPeriod": lot.peak_balance_inr,
                "ClosingBalance": lot.closing_balance_inr,
                "TotGrossAmtPaidCredited": lot.gross_dividends_inr,
                "TotGrossProceeds": lot.gross_proceeds_inr,
            }
            res = self._validate_subschema(
                subschema_ref="DtlsForeignEquityDebtInterest",
                payload=payload,
                rule_prefix=f"SCHEMA-FA-A3-{lot.lot_id}",
                schedule_name="Schedule FA Table A3",
                item_id=f"[{lot.lot_id}]",
            )
            all_results.extend(res)
        return all_results

    def validate_schedule_fsi(self, fsi: FTCResult, os_result: ScheduleOSResult) -> List[ValidationRuleResult]:
        """Validate Schedule FSI against ScheduleFSIDtls."""
        blank_inc = {
            "IncFrmOutsideInd": 0,
            "TaxPaidOutsideInd": 0,
            "TaxPayableinInd": 0,
            "TaxReliefinInd": 0,
        }
        oth_src_inc = {
            "IncFrmOutsideInd": fsi.gross_foreign_income_inr,
            "TaxPaidOutsideInd": fsi.foreign_tax_paid_inr,
            "TaxPayableinInd": fsi.estimated_indian_tax_inr,
            "TaxReliefinInd": fsi.tax_relief_claimed_inr,
            "DTAAReliefUs90or90A": "90",
        }
        total_country = {
            "IncFrmOutsideInd": fsi.gross_foreign_income_inr,
            "TaxPaidOutsideInd": fsi.foreign_tax_paid_inr,
            "TaxPayableinInd": fsi.estimated_indian_tax_inr,
            "TaxReliefinInd": fsi.tax_relief_claimed_inr,
        }
        payload = {
            "CountryName": fsi.country_name,
            "CountryCodeExcludingIndia": fsi.country_code,
            "TaxIdentificationNo": "000-00-0000",
            "IncFromSal": blank_inc,
            "IncFromHP": blank_inc,
            "IncCapGain": blank_inc,
            "IncOthSrc": oth_src_inc,
            "TotalCountryWise": total_country,
        }
        return self._validate_subschema(
            subschema_ref="ScheduleFSIDtls",
            payload=payload,
            rule_prefix="SCHEMA-FSI",
            schedule_name="Schedule FSI",
            item_id=f"[{fsi.country_name}]",
        )

    def validate_schedule_tr(self, tr: FTCResult) -> List[ValidationRuleResult]:
        """Validate Schedule TR against ScheduleTR."""
        payload = {
            "CountryName": tr.country_name,
            "CountryCodeExcludingIndia": tr.country_code,
            "TaxIdentificationNo": "000-00-0000",
            "TaxPaidOutsideIndia": tr.foreign_tax_paid_inr,
            "TaxReliefOutsideIndia": tr.tax_relief_claimed_inr,
            "ReliefClaimedUsSection": "90",
        }
        return self._validate_subschema(
            subschema_ref="ScheduleTR",
            payload=payload,
            rule_prefix="SCHEMA-TR",
            schedule_name="Schedule TR",
            item_id=f"[{tr.country_name}]",
        )
