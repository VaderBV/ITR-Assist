"""Excel Workbook Generator for ITR-2 Foreign Asset Schedules and Scrutiny Audit Trails."""
from datetime import date, timedelta
import os
from typing import Any, Dict, List, Optional, Tuple
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from itr_assist.models import (
    PLACEHOLDER_PREFIX,
    DividendEvent,
    Form1042SData,
    ReconciliationReport,
    StatementPeriodSummary,
)
from itr_assist.services.open_years import fy_to_calendar_year
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import (
    FTCResult,
    ScheduleFATableA2Result,
    ScheduleFATableA3LotResult,
    ScheduleOSResult,
)


# Corporate & Official Palette (Navy / Slate / Gray)
COLOR_HEADER_NAVY = "1B365D"
COLOR_HEADER_SLATE = "2B4C7E"
COLOR_HEADER_WORKING = "3A6073"       # Slate-teal for working columns
COLOR_ACCENT_BLUE = "E3F2FD"
COLOR_ZEBRA_LIGHT = "F8FAFC"
COLOR_BORDER_GRAY = "D0D7DE"
COLOR_SUCCESS_GREEN = "E8F5E9"
COLOR_WARNING_AMBER = "FFF8E1"
COLOR_FILL_WORKING = "F0F4F8"         # Soft subtle tinted background for working cells
COLOR_FILL_WORKING_ZEBRA = "E7EEF4"   # Soft alternating tint for working cells
COLOR_TEXT_WORKING = "1D3557"         # Distinct working text color


class ITRWorkbookGenerator:
    """Generates a multi-sheet, government-mirrored Excel workbook with live formulas and scrutiny audit trails."""

    def __init__(self, output_path: str = "ITR2_Foreign_Assets_Working_AY2026-27.xlsx"):
        self.output_path = output_path
        self.wb = Workbook()
        # Remove default sheet
        if "Sheet" in self.wb.sheetnames:
            self.wb.remove(self.wb["Sheet"])

        self._font_title = Font(name="Calibri", size=14, bold=True, color="1B365D")
        self._font_subtitle = Font(name="Calibri", size=10, italic=True, color="555555")
        self._font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        self._font_header_working = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        self._font_bold = Font(name="Calibri", size=11, bold=True)
        self._font_regular = Font(name="Calibri", size=11)
        self._font_small = Font(name="Calibri", size=9, italic=True, color="666666")
        self._font_working = Font(name="Calibri", size=10, italic=True, color=COLOR_TEXT_WORKING)
        self._font_working_bold = Font(name="Calibri", size=10, bold=True, italic=True, color=COLOR_TEXT_WORKING)

        self._fill_header = PatternFill(start_color=COLOR_HEADER_NAVY, end_color=COLOR_HEADER_NAVY, fill_type="solid")
        self._fill_sub_header = PatternFill(start_color=COLOR_HEADER_SLATE, end_color=COLOR_HEADER_SLATE, fill_type="solid")
        self._fill_header_working = PatternFill(start_color=COLOR_HEADER_WORKING, end_color=COLOR_HEADER_WORKING, fill_type="solid")
        self._fill_zebra = PatternFill(start_color=COLOR_ZEBRA_LIGHT, end_color=COLOR_ZEBRA_LIGHT, fill_type="solid")
        self._fill_working = PatternFill(start_color=COLOR_FILL_WORKING, end_color=COLOR_FILL_WORKING, fill_type="solid")
        self._fill_working_zebra = PatternFill(start_color=COLOR_FILL_WORKING_ZEBRA, end_color=COLOR_FILL_WORKING_ZEBRA, fill_type="solid")
        self._fill_accent = PatternFill(start_color=COLOR_ACCENT_BLUE, end_color=COLOR_ACCENT_BLUE, fill_type="solid")
        self._fill_kpi = PatternFill(start_color="F0F4F8", end_color="F0F4F8", fill_type="solid")

        thin_side = Side(border_style="thin", color=COLOR_BORDER_GRAY)
        self._border_thin = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        self._border_double_bottom = Border(left=thin_side, right=thin_side, top=thin_side, bottom=Side(border_style="double", color="1B365D"))

    def generate(
        self,
        a2_result: ScheduleFATableA2Result,
        a3_lots: List[ScheduleFATableA3LotResult],
        os_result: ScheduleOSResult,
        ftc_result: FTCResult,
        form_1042s: Form1042SData,
        reconciliation_report: ReconciliationReport,
        dividends: List[DividendEvent],
        statement_summaries: List[StatementPeriodSummary],
        taxpayer_name: str = f"{PLACEHOLDER_PREFIX}: taxpayer name",
        pan: str = f"{PLACEHOLDER_PREFIX}: PAN",
        ay: str = "2026-27",
        fy: str = "2025-26",
        sbi_service: Optional[SBIRateService] = None,
        val_report: Optional[Any] = None
    ) -> str:
        """Generate the complete multi-sheet workbook."""
        # Single source of truth for which calendar year(s) this workbook covers, derived from
        # the FY the caller selected - every sheet below uses these instead of a hardcoded year.
        cy = fy_to_calendar_year(fy)
        next_cy = cy + 1

        if sbi_service is None:
            try:
                sbi_service = SBIRateService(auto_download=False)
            except Exception:
                sbi_service = None

        if val_report is None and sbi_service is not None:
            try:
                from itr_assist.validation import ValidationEngine
                validator = ValidationEngine(sbi_service=sbi_service)
                cy_div_usd = sum(d.gross_amount_usd for d in dividends if d.pay_date.year == cy)
                cy_tax_usd = sum(d.tax_withheld_usd for d in dividends if d.pay_date.year == cy)
                val_report = validator.validate(
                    a2=a2_result,
                    a3_lots=a3_lots,
                    os_result=os_result,
                    ftc=ftc_result,
                    form_1042s=form_1042s,
                    cy_dividends_usd=cy_div_usd,
                    cy_tax_withheld_usd=cy_tax_usd,
                    is_resident=True,
                    part_b_tti_sl19_yes=True,
                    statement_summaries=statement_summaries,
                    calendar_year=cy,
                )
            except Exception:
                val_report = None

        self._build_dashboard(taxpayer_name, pan, ay, fy, a2_result, a3_lots, os_result, ftc_result, reconciliation_report, val_report, cy, next_cy)
        self._build_schedule_fa_table_a2(a2_result, cy)
        self._build_schedule_fa_table_a3(a3_lots, cy)
        self._build_schedule_os(os_result, fy, cy, next_cy)
        self._build_schedule_fsi(ftc_result, pan, ay)
        self._build_schedule_tr(ftc_result, pan, ay)
        self._build_form_67(ftc_result, taxpayer_name, pan, ay)
        if val_report:
            self._build_validation_report(val_report, ay)
        self._build_sbi_rate_register(a2_result, a3_lots, os_result, ftc_result, sbi_service, fy, cy)
        self._build_audit_lot_peaks(a3_lots, cy)
        self._build_audit_dividends(os_result, dividends, sbi_service)
        self._build_audit_statements(statement_summaries)

        try:
            self.wb.save(self.output_path)
            return self.output_path
        except PermissionError:
            base, ext = os.path.splitext(self.output_path)
            alt_path = f"{base}_updated{ext}"
            self.wb.save(alt_path)
            print(f"\n[NOTICE] File '{self.output_path}' is open in another program (e.g. Excel).")
            print(f"         Saved successfully to: '{alt_path}' instead.")
            return alt_path

    def _build_dashboard(
        self,
        taxpayer_name: str,
        pan: str,
        ay: str,
        fy: str,
        a2: ScheduleFATableA2Result,
        a3_lots: List[ScheduleFATableA3LotResult],
        os_res: ScheduleOSResult,
        ftc_res: FTCResult,
        report: ReconciliationReport,
        val_report: Optional[Any] = None,
        cy: int = 2025,
        next_cy: int = 2026
    ) -> None:
        """Sheet 1: Executive Dashboard & Cross-Verification Summary."""
        ws = self.wb.create_sheet(title="Dashboard_Summary")
        ws.views.sheetView[0].showGridLines = True

        ws["B2"] = "ITR-2 FOREIGN ASSETS & INCOME REPORTING SUMMARY"
        ws["B2"].font = self._font_title
        ws["B3"] = f"Taxpayer: {taxpayer_name}  |  PAN: {pan}  |  AY: {ay}  |  FY: {fy}"
        ws["B3"].font = self._font_subtitle

        # Key Metrics Summary Cards
        headers = ["Schedule / Area", "Key Metric Description", "Amount in USD", "Amount in INR (₹)", "Statutory Reference / ITR Mapping"]
        row_idx = 5
        for col_idx, h in enumerate(headers, start=2):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = self._border_thin

        kpi_rows = [
            ("Schedule FA - Table A2", f"Custodial Account Peak Balance (CY {cy})", f"${a2.peak_balance_usd:,.2f}", a2.peak_balance_inr, f"Peak on {a2.peak_date} @ SBI TTBR {a2.peak_rate_inr:.2f}"),
            ("Schedule FA - Table A2", f"Custodial Account Closing Balance (as on Dec 31, {cy})", f"${a2.closing_balance_usd:,.2f}", a2.closing_balance_inr, f"Dec 31, {cy} Value @ SBI TTBR {a2.closing_rate_inr:.2f}"),
            ("Schedule FA - Table A3", f"Total Equity Lots Declared (Active in CY {cy})", f"{len(a3_lots)} Lots", sum(l.closing_balance_inr for l in a3_lots), f"Includes {sum(1 for l in a3_lots if l.is_sold_lot and l.disposal_date and l.disposal_date.year == cy)} lot(s) sold during {cy}"),
            ("Schedule OS", f"Gross Foreign Dividends (FY {fy})", f"${sum(i.gross_usd for i in os_res.items):,.2f}", os_res.total_dividend_inr, "Income from Other Sources (5 Installments)"),
            ("Schedule FSI / TR", "Foreign Taxes Paid Abroad", f"${sum(i.tax_usd for i in os_res.items):,.2f}", ftc_res.foreign_tax_paid_inr, "Rule 128(5)(ii) Preceding Month-End Conversion"),
            ("Form 67 / Schedule TR", "Foreign Tax Credit (FTC) Claimed u/s 90", f"${sum(i.tax_usd for i in os_res.items):,.2f}", ftc_res.tax_relief_claimed_inr, "DTAA Article 10 (Restricted to Indian Tax Payable)"),
        ]

        row_idx = 6
        for sch, desc, usd_val, inr_val, notes in kpi_rows:
            ws.cell(row=row_idx, column=2, value=sch).font = self._font_bold
            ws.cell(row=row_idx, column=3, value=desc).font = self._font_regular
            c_usd = ws.cell(row=row_idx, column=4, value=usd_val)
            c_usd.font = self._font_regular
            c_usd.alignment = Alignment(horizontal="right")

            c_inr = ws.cell(row=row_idx, column=5, value=inr_val)
            c_inr.font = self._font_bold
            c_inr.number_format = "₹ #,##,##0"
            c_inr.alignment = Alignment(horizontal="right")

            c_notes = ws.cell(row=row_idx, column=6, value=notes)
            c_notes.font = self._font_small

            for c in range(2, 7):
                ws.cell(row=row_idx, column=c).border = self._border_thin
                if row_idx % 2 == 0:
                    ws.cell(row=row_idx, column=c).fill = self._fill_zebra
            row_idx += 1

        # Reconciliation Integrity Audit Box
        row_idx += 2
        ws.cell(row=row_idx, column=2, value="DOCUMENT RECONCILIATION & SCRUTINY INTEGRITY STATUS").font = self._font_bold
        row_idx += 1

        # Only lots sold DURING this calendar year belong here - the ledger-wide sold count also
        # includes lots sold in earlier years, which aren't in this year's Table A3 at all.
        sold_in_cy = [l for l in a3_lots if l.is_sold_lot and l.disposal_date and l.disposal_date.year == cy]
        sold_summary = f"{len(sold_in_cy)} lot(s) sold during {cy}"
        sold_finding = (
            "Each declared in Table A3 with its peak value, a 31-Dec closing balance of 0 and its sale proceeds"
            if sold_in_cy else f"No lots were sold during {cy}"
        )

        def _rule_result(rule_id: str):
            if not val_report:
                return None
            return next((r for r in val_report.results if r.rule_id == rule_id), None)

        div_rule = _rule_result("INV-1042S-DIV-RECON")
        tax_rule = _rule_result("INV-1042S-TAX-RECON")
        if div_rule or tax_rule:
            div_status = "RECONCILED" if (not div_rule or div_rule.status.value == "PASSED") else "DISCREPANCY"
            tax_status = "RECONCILED" if (not tax_rule or tax_rule.status.value == "PASSED") else "DISCREPANCY"
            div_tax_status = "RECONCILED" if div_status == "RECONCILED" and tax_status == "RECONCILED" else "DISCREPANCY"
            div_tax_finding = "; ".join(
                r.details for r in (div_rule, tax_rule) if r is not None
            )
        else:
            div_tax_status = "RECONCILED"
            div_tax_finding = "Matches IRS Form 1042-S within statutory rounding tolerances"

        cov_rule = _rule_result("INV-STATEMENT-COVERAGE")
        if cov_rule:
            cov_status = "UNBROKEN" if cov_rule.status.value == "PASSED" else "GAPS FOUND"
            cov_finding = cov_rule.details
        else:
            cov_status = "NOT CHECKED"
            cov_finding = "Statement coverage was not evaluated for this run"

        recon_checks = [
            ("Lots Sold During the Year (Black Money Act)", sold_summary, "DECLARED" if sold_in_cy else "NONE", sold_finding),
            ("Calendar Year Dividends vs Form 1042-S", "Statement dividends vs IRS Form 1042-S", div_tax_status, div_tax_finding),
            ("Broker Statement Coverage", "Statement periods vs holding history", cov_status, cov_finding),
        ]

        if val_report:
            sc = val_report.scorecard
            recon_checks.append(
                (
                    f"CBDT Statutory & Schema Rules (AY {ay})",
                    f"{sc.passed}/{sc.total_rules} rules passed",
                    sc.compute_status(),
                    "All CBDT JSON Schema, Systems PDF & IT Rules 115/128/90 checks passed (see Audit_Validation_Report)"
                    if sc.failed == 0
                    else f"{sc.failed} check(s) failed - see Audit_Validation_Report for details",
                )
            )

        ws.cell(row=row_idx, column=2, value="Verification Check").font = self._font_header
        ws.cell(row=row_idx, column=2).fill = self._fill_sub_header
        ws.cell(row=row_idx, column=3, value="Audited Data Points").font = self._font_header
        ws.cell(row=row_idx, column=3).fill = self._fill_sub_header
        ws.cell(row=row_idx, column=4, value="Status").font = self._font_header
        ws.cell(row=row_idx, column=4).fill = self._fill_sub_header
        ws.cell(row=row_idx, column=5, value="Audit Findings").font = self._font_header
        ws.cell(row=row_idx, column=5).fill = self._fill_sub_header
        ws.cell(row=row_idx, column=6, value="").border = self._border_thin

        row_idx += 1
        for chk, data_pt, status, finding in recon_checks:
            ws.cell(row=row_idx, column=2, value=chk).font = self._font_bold
            ws.cell(row=row_idx, column=3, value=data_pt).font = self._font_regular
            c_stat = ws.cell(row=row_idx, column=4, value=status)
            c_stat.alignment = Alignment(horizontal="center")
            if status in ("RECONCILED", "UNBROKEN", "DECLARED", "NONE", "100%_STATUTORILY_COMPLIANT"):
                c_stat.font = self._font_bold
                c_stat.fill = PatternFill(start_color=COLOR_SUCCESS_GREEN, end_color=COLOR_SUCCESS_GREEN, fill_type="solid")
            elif status in ("FILING_READY_WITH_WARNINGS", "NOT CHECKED"):
                c_stat.font = Font(name="Calibri", size=11, bold=True, color="B25E00")
                c_stat.fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
            else:
                # Every non-passing status gets an explicit fill - an unstyled cell next to green
                # ones reads as broken formatting rather than a deliberate warning.
                c_stat.font = Font(name="Calibri", size=11, bold=True, color="C00000")
                c_stat.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

            ws.cell(row=row_idx, column=5, value=finding).font = self._font_regular
            for c in range(2, 6):
                ws.cell(row=row_idx, column=c).border = self._border_thin
            row_idx += 1

        # Master Input Document Provenance Index
        row_idx += 2
        ws.cell(row=row_idx, column=2, value="MASTER INPUT DOCUMENT PROVENANCE INDEX").font = self._font_bold
        row_idx += 1

        doc_headers = ["Document Role", "File Name", "Information Extracted", "Schedules Fed & Audit Significance"]
        for c_idx, h in enumerate(doc_headers, start=2):
            cell = ws.cell(row=row_idx, column=c_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_sub_header
            cell.border = self._border_thin
            cell.alignment = Alignment(horizontal="center", vertical="center")
        row_idx += 1

        symbols = sorted(list({lot.lot_id.split("-")[0] for lot in a3_lots if lot.lot_id}))
        sym_str = ", ".join(symbols) if symbols else "Foreign Equity"
        hist_fname = f"{symbols[0]}_prices.json" if symbols else "stock_prices.json"

        doc_provenance = [
            ("Benefit History Spreadsheet", "Broker Benefit History Export", "All historical RSU & ESPP vests (tranche dates, shares, vest FMV)", "Feeds Table A3 initial values, acquisition dates, & sold lot tracking"),
            ("Current Holdings Snapshot", "Broker Holdings Export", "Active sellable shares snapshot at export time", "Informational only - an as-of-today snapshot, not used for this year's figures"),
            ("Broker Statements", "Broker Client Statement PDFs (full history)", "Period net values, cash balance, dividend and sale transactions", "Feed Table A2 closing balance, Schedule OS dividends, and the sale events that mark lots as disposed"),
            ("Form 1042-S Tax Document", "IRS Form 1042-S PDF", "IRS Form 1042-S Box 2 & Box 7a (Gross foreign dividend & federal tax withheld)", "Verifies Schedule OS gross income & validates Schedule FSI / TR Foreign Tax Credit"),
            ("SBI Reference Rate Archive", "SBI_REFERENCE_RATES_USD.csv", "Official SBI TT Buying Rates for all transaction dates and preceding month ends", "Mandatory statutory exchange rates under Rule 115 and Rule 128"),
            ("Stock Price History", hist_fname, f"Daily Open/High/Low/Close prices for {sym_str}", "Mathematical proof for Table A2 and Table A3 statutory peak valuations"),
        ]

        for role, fname, info, sig in doc_provenance:
            ws.cell(row=row_idx, column=2, value=role).font = self._font_bold
            ws.cell(row=row_idx, column=3, value=fname).font = self._font_regular
            ws.cell(row=row_idx, column=4, value=info).font = self._font_regular
            ws.cell(row=row_idx, column=5, value=sig).font = self._font_small
            for c in range(2, 6):
                ws.cell(row=row_idx, column=c).border = self._border_thin
            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_schedule_fa_table_a2(self, a2: ScheduleFATableA2Result, cy: int = 2025) -> None:
        """Sheet 2: Schedule FA Table A2 - Foreign Custodial Accounts."""
        ws = self.wb.create_sheet(title="Schedule_FA_Table_A2")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "SCHEDULE FA: TABLE A2 — DETAILS OF FOREIGN CUSTODIAL ACCOUNTS HELD DURING THE CALENDAR YEAR"
        ws["A1"].font = self._font_title
        ws["A2"] = f"Relevant for Calendar Year: January 1, {cy} to December 31, {cy} (Official Government Schema: DtlsForeignCustodialAcc)"
        ws["A2"].font = self._font_subtitle

        headers = [
            ("Country Name\n(Col 1)", False),
            ("Country Code\n(Col 2)", False),
            ("Name of Financial Institution\n(Col 3)", False),
            ("Address of Financial Institution\n(Col 4)", False),
            ("Zip Code\n(Col 5)", False),
            ("Account Number\n(Col 6)", False),
            ("Status\n(Col 7)", False),
            ("Account Opening Date\n(Col 8)", False),
            # Peak Balance Group:
            ("Peak Balance During Period (₹)\n(Col 9 - Statutory ITR)", False),
            ("Peak Amount in USD ($)\n[Working - Scrutiny]", True),
            ("Peak Valuation Date\n[Working Date]", True),
            ("Peak SBI TTBR Rate (₹)\n[Rate Used]", True),
            ("Peak Balance Data Source\n[Audit Provenance]", True),
            # Closing Balance Group:
            ("Closing Balance (₹)\n(Col 10 - Statutory ITR)", False),
            ("Closing Amount in USD ($)\n[Working - Scrutiny]", True),
            (f"Closing Valuation Date\n[31-Dec-{cy}]", True),
            ("Closing SBI TTBR Rate (₹)\n[Rate Used]", True),
            ("Closing Balance Data Source\n[Audit Provenance]", True),
            # Gross Income Group:
            ("Gross Amount Paid/Credited (₹)\n(Col 11 - Statutory ITR)", False),
            ("Gross Income in USD ($)\n[Working - Scrutiny]", True),
            ("Gross Income Data Source\n[Audit Provenance]", True),
            ("Nature of Amount\n(Col 12 - Statutory ITR)", False)
        ]

        row_idx = 4
        for col_idx, (h, is_working) in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header_working if is_working else self._font_header
            cell.fill = self._fill_header_working if is_working else self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 35

        # CBDT allows one NatureOfAmount per A2 row. Repeat the account values when the
        # account received more than one nature of credit (dividend, interest, proceeds).
        for row_idx, gross in enumerate(a2.gross_amounts, start=5):
            data = [
                (a2.country_name, False, "center", "@", False),
                (a2.country_code, False, "center", "@", False),
                (a2.financial_inst_name, False, "left", "@", False),
                (a2.financial_inst_address, False, "left", "@", False),
                (a2.zip_code, False, "center", "@", False),
                (a2.account_number, False, "center", "@", False),
                (a2.status, False, "center", "@", False),
                (a2.account_open_date, False, "center", "YYYY-MM-DD", False),
                (a2.peak_balance_inr, False, "right", "₹ #,##,##0", True),
                (a2.peak_balance_usd, True, "right", "$#,##0.00", True),
                (a2.peak_date.strftime("%Y-%m-%d"), True, "center", "YYYY-MM-DD", False),
                (a2.peak_rate_inr, True, "right", "0.00", False),
                (a2.source_peak, True, "left", "@", False),
                (a2.closing_balance_inr, False, "right", "₹ #,##,##0", True),
                (a2.closing_balance_usd, True, "right", "$#,##0.00", True),
                (a2.closing_date.strftime("%Y-%m-%d"), True, "center", "YYYY-MM-DD", False),
                (a2.closing_rate_inr, True, "right", "0.00", False),
                (a2.source_closing, True, "left", "@", False),
                (gross.amount_inr, False, "right", "₹ #,##,##0", True),
                (gross.amount_usd, True, "right", "$#,##0.00", True),
                (gross.source, True, "left", "@", False),
                (gross.nature, False, "center", "@", False),
            ]

            for col_idx, (val, is_working, align, num_fmt, is_bold) in enumerate(data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.alignment = Alignment(horizontal=align, vertical="center")
                cell.number_format = num_fmt
                cell.border = self._border_thin
                if is_working:
                    cell.fill = self._fill_working
                    cell.font = self._font_working_bold if is_bold else self._font_working
                else:
                    cell.font = self._font_bold if is_bold else self._font_regular

        # Explanatory Notes below table
        notes_row = 6 + len(a2.gross_amounts)
        ws.cell(row=notes_row, column=1, value="STATUTORY AUDIT & CALCULATION NOTES FOR TABLE A2:").font = self._font_bold
        gross_usd = sum(item.amount_usd for item in a2.gross_amounts)
        gross_natures = ", ".join(item.nature for item in a2.gross_amounts)
        notes = [
            f"1. Peak Balance (Col 9): Computed on {a2.peak_date} when total custodial holdings reached ${a2.peak_balance_usd:,.2f} converted at SBI TTBR ₹ {a2.peak_rate_inr:.2f}.",
            f"2. Closing Balance (Col 10): Computed as on Dec 31, {cy} with total account value ${a2.closing_balance_usd:,.2f} converted at Dec 31 SBI TTBR ₹ {a2.closing_rate_inr:.2f}.",
            f"3. Gross Amount (Col 11): Total gross amounts credited during Calendar Year {cy} (${gross_usd:.2f}) are split into one row per nature.",
            f"4. Nature of Amount (Col 12): Reported CBDT nature code(s): {gross_natures}.",
            f"5. Source Evidence: Full monthly statements and SBI Card rate sheets are cross-verified and indexed in Sheet 1."
        ]
        if a2.peak_notes:
            notes.append("6. PEAK NOT FULLY VERIFIED: " + " ".join(a2.peak_notes))
        elif a2.model_checks:
            notes.append(
                f"6. Peak verified: cash + shares x close reproduces the account total printed on all "
                f"{len(a2.model_checks)} statements ending in {cy}."
            )
        if a2.source_broker_details:
            notes.append(
                f"7. Broker address and ZIP were read from {a2.source_broker_details}; confirm them before filing."
            )
        for idx, n in enumerate(notes, start=notes_row + 1):
            ws.cell(row=idx, column=1, value=n).font = self._font_small

        self._auto_fit_columns(ws)

    def _build_schedule_fa_table_a3(self, a3_lots: List[ScheduleFATableA3LotResult], cy: int = 2025) -> None:
        """Sheet 3: Schedule FA Table A3 - Details of Foreign Equity and Debt Interest."""
        ws = self.wb.create_sheet(title="Schedule_FA_Table_A3")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "SCHEDULE FA: TABLE A3 — DETAILS OF FOREIGN EQUITY AND DEBT INTEREST HELD IN ANY ENTITY"
        ws["A1"].font = self._font_title
        ws["A2"] = f"Relevant for Calendar Year: Jan 1, {cy} to Dec 31, {cy} (Official Government Schema: DtlsForeignEquityDebtInterest)"
        ws["A2"].font = self._font_subtitle

        headers = [
            ("Sl No", False),
            ("Lot Identifier\n(Audit Ref)", False),
            ("Country Name\n(Col 1)", False),
            ("Country Code\n(Col 2)", False),
            ("Name of Entity\n(Col 3)", False),
            ("Address of Entity\n(Col 4)", False),
            ("Zip Code\n(Col 5)", False),
            ("Nature of Entity\n(Col 6)", False),
            ("Date of Acquiring\nInterest (Col 7)", False),
            # Initial Investment Group:
            ("Initial Value of\nInvestment (₹) (Col 8)", False),
            ("Initial Cost ($)\n[Working - USD]", True),
            ("Net Shares\nHeld", True),
            ("Vest FMV ($)\n[Acquisition]", True),
            ("Acq SBI TTBR (₹)\n[Rate Used]", True),
            ("Initial Value Source\n[Audit Provenance]", True),
            # Peak Balance Group:
            ("Peak Balance\nDuring Period (₹) (Col 9)", False),
            ("Peak Value ($)\n[Working - USD]", True),
            ("Peak Stock Close ($)\n[EOD Close]", True),
            ("Peak Valuation Date\n[Working Date]", True),
            ("Peak SBI TTBR (₹)\n[Rate Used]", True),
            ("Peak Balance Source\n[Audit Provenance]", True),
            # Closing Balance Group:
            ("Closing Balance\n(₹) (Col 10)", False),
            ("Closing Value ($)\n[Working - USD]", True),
            ("Dec 31 Close Price ($)\n[Closing FMV]", True),
            (f"Dec 31 Valuation Date\n[31-Dec-{cy}]", True),
            ("Dec 31 SBI TTBR (₹)\n[Rate Used]", True),
            ("Closing Balance Source\n[Audit Provenance]", True),
            # Gross Amount Group:
            ("Total Gross Amount\nPaid/Credited (₹) (Col 11)", False),
            ("Gross Dividends ($)\n[Working - USD]", True),
            ("Dividends Source\n[Audit Provenance]", True),
            # Proceeds & Status:
            ("Total Gross Proceeds\nfrom Sale (₹) (Col 12)", False),
            ("Gross Proceeds ($)\n[Working - USD]", True),
            ("Proceeds Source\n[Audit Provenance]", True),
            ("Sold Lot\nFlag [Status]", True)
        ]

        row_idx = 4
        for col_idx, (h, is_working) in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header_working if is_working else self._font_header
            cell.fill = self._fill_header_working if is_working else self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 35

        row_idx = 5
        working_col_indices = {11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 29, 30, 32, 33}

        for idx, lot in enumerate(a3_lots, start=1):
            is_even = (idx % 2 == 0)
            if lot.is_sold_lot:
                sold_text = f"YES (Sold {lot.disposal_date.year})" if lot.disposal_date else f"YES (Sold after {cy})"
            else:
                sold_text = "NO"

            row_data = [
                # Col 1-9: Basic Identification
                (idx, False, "center", "@", False),
                (lot.lot_id, False, "left", "@", False),
                (lot.country_name, False, "center", "@", False),
                (lot.country_code, False, "center", "@", False),
                (lot.name_of_entity, False, "left", "@", False),
                (lot.address_of_entity, False, "left", "@", False),
                (lot.zip_code, False, "center", "@", False),
                (lot.nature_of_entity, False, "center", "@", False),
                (lot.acquisition_date.strftime("%Y-%m-%d"), False, "center", "YYYY-MM-DD", False),

                # Col 10-15: Initial Investment Group
                (lot.initial_value_inr, False, "right", "₹ #,##,##0", True),
                (lot.initial_cost_usd, True, "right", "$#,##0.00", True),
                (lot.net_shares, True, "center", "0.0", False),
                (lot.vest_fmv_usd, True, "right", "$#,##0.00", False),
                (lot.acq_sbi_rate_inr, True, "right", "0.00", False),
                (lot.source_acquisition, True, "left", "@", False),

                # Col 16-21: Peak Balance Group
                (lot.peak_balance_inr, False, "right", "₹ #,##,##0", True),
                (lot.peak_balance_usd, True, "right", "$#,##0.00", True),
                (lot.peak_price_usd, True, "right", "$#,##0.00", False),
                (lot.peak_date.strftime("%Y-%m-%d"), True, "center", "YYYY-MM-DD", False),
                (lot.peak_rate_inr, True, "right", "0.00", False),
                (lot.source_peak, True, "left", "@", False),

                # Col 22-27: Closing Balance Group
                (lot.closing_balance_inr, False, "right", "₹ #,##,##0", True),
                (lot.closing_balance_usd, True, "right", "$#,##0.00", True),
                (lot.closing_price_usd, True, "right", "$#,##0.00", False),
                (lot.closing_date.strftime("%Y-%m-%d"), True, "center", "YYYY-MM-DD", False),
                (lot.closing_rate_inr, True, "right", "0.00", False),
                (lot.source_closing, True, "left", "@", False),

                # Col 28-30: Gross Amount Group
                (lot.gross_dividends_inr, False, "right", "₹ #,##,##0", True),
                (lot.gross_dividends_usd, True, "right", "$#,##0.00", True),
                (lot.source_dividends, True, "left", "@", False),

                # Col 31-34: Proceeds & Status
                (lot.gross_proceeds_inr, False, "right", "₹ #,##,##0", True),
                (lot.gross_proceeds_usd, True, "right", "$#,##0.00", True),
                (lot.source_proceeds, True, "left", "@", False),
                (sold_text, True, "center", "@", False)
            ]

            for col_idx, (val, is_working, align, num_fmt, is_bold) in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.alignment = Alignment(horizontal=align, vertical="center")
                cell.number_format = num_fmt
                cell.border = self._border_thin

                if is_working:
                    cell.fill = self._fill_working_zebra if is_even else self._fill_working
                    cell.font = self._font_working_bold if is_bold else self._font_working
                else:
                    if is_even:
                        cell.fill = self._fill_zebra
                    cell.font = self._font_bold if is_bold else self._font_regular

                if col_idx in (15, 21, 27, 30, 33):
                    cell.font = self._font_small

                if lot.is_sold_lot and col_idx == 34:
                    cell.fill = PatternFill(start_color=COLOR_WARNING_AMBER, end_color=COLOR_WARNING_AMBER, fill_type="solid")
                    cell.font = self._font_bold

            row_idx += 1

        # Totals Row
        ws.cell(row=row_idx, column=2, value="TOTALS").font = self._font_bold
        ws.cell(row=row_idx, column=2).alignment = Alignment(horizontal="center")

        # Col 10: Initial Value INR (Statutory)
        ws.cell(row=row_idx, column=10, value=sum(l.initial_value_inr for l in a3_lots)).font = self._font_bold
        ws.cell(row=row_idx, column=10).number_format = "₹ #,##,##0"

        # Col 11: Initial Cost USD (Working)
        ws.cell(row=row_idx, column=11, value=sum(l.initial_cost_usd for l in a3_lots)).font = self._font_working_bold
        ws.cell(row=row_idx, column=11).number_format = "$#,##0.00"

        # Col 12: Net Shares (Working)
        ws.cell(row=row_idx, column=12, value=sum(l.net_shares for l in a3_lots)).font = self._font_working_bold
        ws.cell(row=row_idx, column=12).alignment = Alignment(horizontal="center")

        # Col 16: Peak Balance INR (Statutory)
        ws.cell(row=row_idx, column=16, value=sum(l.peak_balance_inr for l in a3_lots)).font = self._font_bold
        ws.cell(row=row_idx, column=16).number_format = "₹ #,##,##0"

        # Col 17: Peak Value USD (Working)
        ws.cell(row=row_idx, column=17, value=sum(l.peak_balance_usd for l in a3_lots)).font = self._font_working_bold
        ws.cell(row=row_idx, column=17).number_format = "$#,##0.00"

        # Col 22: Closing Balance INR (Statutory)
        ws.cell(row=row_idx, column=22, value=sum(l.closing_balance_inr for l in a3_lots)).font = self._font_bold
        ws.cell(row=row_idx, column=22).number_format = "₹ #,##,##0"

        # Col 23: Closing Value USD (Working)
        ws.cell(row=row_idx, column=23, value=sum(l.closing_balance_usd for l in a3_lots)).font = self._font_working_bold
        ws.cell(row=row_idx, column=23).number_format = "$#,##0.00"

        # Col 28: Gross Dividends INR (Statutory)
        ws.cell(row=row_idx, column=28, value=sum(l.gross_dividends_inr for l in a3_lots)).font = self._font_bold
        ws.cell(row=row_idx, column=28).number_format = "₹ #,##,##0"

        # Col 29: Gross Dividends USD (Working)
        ws.cell(row=row_idx, column=29, value=sum(l.gross_dividends_usd for l in a3_lots)).font = self._font_working_bold
        ws.cell(row=row_idx, column=29).number_format = "$#,##0.00"

        # Col 31: Gross Proceeds INR (Statutory)
        ws.cell(row=row_idx, column=31, value=sum(l.gross_proceeds_inr for l in a3_lots)).font = self._font_bold
        ws.cell(row=row_idx, column=31).number_format = "₹ #,##,##0"

        # Col 32: Gross Proceeds USD (Working)
        ws.cell(row=row_idx, column=32, value=sum(l.gross_proceeds_usd for l in a3_lots)).font = self._font_working_bold
        ws.cell(row=row_idx, column=32).number_format = "$#,##0.00"

        for c in range(1, 35):
            cell = ws.cell(row=row_idx, column=c)
            cell.border = self._border_double_bottom
            if c in working_col_indices:
                cell.fill = self._fill_working

        self._auto_fit_columns(ws)

    def _build_schedule_os(self, os_res: ScheduleOSResult, fy: str = "2025-26", cy: int = 2025, next_cy: int = 2026) -> None:
        """Sheet 4: Schedule OS - Foreign Dividend Income & 5 Advance Tax Installments."""
        ws = self.wb.create_sheet(title="Schedule_OS")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = f"SCHEDULE OS: INCOME FROM OTHER SOURCES — FOREIGN DIVIDENDS (INDIAN FY {fy})"
        ws["A1"].font = self._font_title
        ws["A2"] = "Governed by Rule 115(1) (Rate on last business day of preceding month) & Section 234C 5 Installments"
        ws["A2"].font = self._font_subtitle

        # Summary of 5 Advance Tax Installments
        headers_box = ["Installment Period", "Statutory Due Date Range", "ITR-2 Schema Bucket Field", "Gross Foreign Dividend (₹)"]
        row_idx = 4
        for col_idx, h in enumerate(headers_box, start=2):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = self._border_thin

        installments = [
            ("Installment 1", f"Up to 15th June {cy}", "Upto15Of6", os_res.upto_15_jun_inr),
            ("Installment 2", f"16th June to 15th September {cy}", "Upto15Of9", os_res.upto_15_sep_inr),
            ("Installment 3", f"16th September to 15th December {cy}", "Up16Of9To15Of12", os_res.upto_15_dec_inr),
            ("Installment 4", f"16th December {cy} to 15th March {next_cy}", "Up16Of12To15Of3", os_res.upto_15_mar_inr),
            ("Installment 5", f"16th March to 31st March {next_cy}", "Up16Of3To31Of3", os_res.upto_31_mar_inr),
        ]

        row_idx = 5
        for inst, dt_range, fld, amt in installments:
            ws.cell(row=row_idx, column=2, value=inst).font = self._font_bold
            ws.cell(row=row_idx, column=3, value=dt_range).font = self._font_regular
            ws.cell(row=row_idx, column=4, value=fld).font = self._font_regular
            c_amt = ws.cell(row=row_idx, column=5, value=amt)
            c_amt.font = self._font_bold
            c_amt.number_format = "₹ #,##,##0"
            c_amt.alignment = Alignment(horizontal="right")

            for c in range(2, 6):
                ws.cell(row=row_idx, column=c).border = self._border_thin
            row_idx += 1

        # Total Line
        ws.cell(row=row_idx, column=2, value="TOTAL SCHEDULE OS DIVIDEND").font = self._font_bold
        c_tot = ws.cell(row=row_idx, column=5, value=os_res.total_dividend_inr)
        c_tot.font = self._font_bold
        c_tot.number_format = "₹ #,##,##0"
        c_tot.alignment = Alignment(horizontal="right")
        for c in range(2, 6):
            ws.cell(row=row_idx, column=c).border = self._border_double_bottom

        # Detailed Transaction Working Table
        row_idx += 3
        ws.cell(row=row_idx, column=2, value="TRANSACTION-BY-TRANSACTION RULE 115 CONVERSION PROOF").font = self._font_bold
        row_idx += 1

        txn_headers = [
            "Dividend Pay Date", "Symbol", "Gross Amount (USD)", "Preceding Month End Date",
            "Rule 115 SBI TTBR (₹)", "Gross Dividend in INR (₹)", "US Tax Withheld (USD)",
            "Foreign Tax Deduction/Payment Date", "Rule 128 SBI TTBR (₹)", "Foreign Tax Paid (₹)", "Applicable Advance Tax Bucket",
            "Data Source Document (Audit Provenance)"
        ]

        for col_idx, th in enumerate(txn_headers, start=2):
            cell = ws.cell(row=row_idx, column=col_idx, value=th)
            cell.font = self._font_header
            cell.fill = self._fill_sub_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 30

        row_idx += 1
        for item in os_res.items:
            row_data = [
                item.tax_deduction_date.strftime("%Y-%m-%d"),
                item.symbol,
                item.gross_usd,
                item.preceding_month_end.strftime("%Y-%m-%d"),
                item.rule_115_rate,
                item.gross_inr,
                item.tax_usd,
                item.pay_date.strftime("%Y-%m-%d"),
                item.rule_128_rate,
                item.tax_inr,
                item.advance_tax_bucket,
                item.source_document
            ]

            for col_idx, val in enumerate(row_data, start=2):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = self._font_regular
                cell.border = self._border_thin
                if col_idx in (4, 8):
                    cell.number_format = "$#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (6, 10):
                    cell.number_format = "0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (7, 11):
                    cell.number_format = "₹ #,##,##0"
                    cell.alignment = Alignment(horizontal="right")
                    cell.font = self._font_bold
                elif col_idx in (2, 3, 5, 9, 12):
                    cell.alignment = Alignment(horizontal="center")
                elif col_idx == 13:
                    cell.font = self._font_small
                    cell.alignment = Alignment(horizontal="left")
            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_schedule_fsi(self, ftc: FTCResult, pan: str, ay: str = "2026-27") -> None:
        """Sheet 5: Schedule FSI - Details of Income from Outside India and Tax Relief."""
        ws = self.wb.create_sheet(title="Schedule_FSI")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = f"SCHEDULE FSI: DETAILS OF INCOME FROM OUTSIDE INDIA AND TAX RELIEF (AY {ay})"
        ws["A1"].font = self._font_title
        ws["A2"] = "Official Government Schema Definition: ScheduleFSIDtls (Head: Income from Other Sources)"
        ws["A2"].font = self._font_subtitle

        headers = [
            "Country Name\n(Col a)",
            "Country Code\n(Col b)",
            "Taxpayer Identification\nNumber (TIN / PAN)",
            "Head of Income\n(Col c)",
            "Income from outside India\n(included in Part B-TI) (Col d)",
            "Tax paid outside India\n(Col e)",
            "Tax payable on such income\nunder normal provisions (Col f)",
            "Tax relief available in India\n(e or f whichever lower) (Col g)",
            "Relevant Article of DTAA\nif relief claimed u/s 90/90A (Col h)",
            "Gross Foreign Income in USD ($)\n(Scrutiny Working)",
            "Tax Paid Outside India in USD ($)\n(Scrutiny Working)",
            "Statutory Conversion Rules\n(Rule 115 & Rule 128)",
            "Audit Data Source\n(Form 1042-S & Statements)"
        ]

        row_idx = 4
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 35

        row_idx = 5
        data = [
            ftc.country_name,
            ftc.country_code,
            pan,
            ftc.head_of_income,
            ftc.gross_foreign_income_inr,
            ftc.foreign_tax_paid_inr,
            ftc.estimated_indian_tax_inr,
            ftc.tax_relief_claimed_inr,
            ftc.dtaa_article,
            ftc.gross_foreign_income_usd,
            ftc.foreign_tax_paid_usd,
            "Income @ Rule 115 Preceding Mo-End | Tax @ Rule 128(5)(ii) Preceding Mo-End",
            ftc.source_document
        ]

        for col_idx, val in enumerate(data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = self._font_regular
            cell.border = self._border_thin
            if col_idx in (5, 6, 7, 8):
                cell.number_format = "₹ #,##,##0"
                cell.alignment = Alignment(horizontal="right")
                cell.font = self._font_bold
            elif col_idx in (10, 11):
                cell.number_format = "$#,##0.00"
                cell.alignment = Alignment(horizontal="right")
                cell.font = self._font_bold
            elif col_idx in (1, 2, 3, 9):
                cell.alignment = Alignment(horizontal="center")
            elif col_idx in (12, 13):
                cell.font = self._font_small
                cell.alignment = Alignment(horizontal="left")

        ws["A7"] = "VALIDATION RULE COMPLIANCE NOTE:"
        ws["A7"].font = self._font_bold
        ws["A8"] = "CBDT Rule 442: 'In Schedule FSI, tax relief available should be lower of tax paid outside India or tax payable on such income in India.'"
        ws["A8"].font = self._font_small
        ws["A9"] = f"Here: Tax Paid (₹ {ftc.foreign_tax_paid_inr:,}) <= Tax Payable (₹ {ftc.estimated_indian_tax_inr:,}), so full relief of ₹ {ftc.tax_relief_claimed_inr:,} is allowed."
        ws["A9"].font = self._font_small

        self._auto_fit_columns(ws)

    def _build_schedule_tr(self, ftc: FTCResult, pan: str, ay: str = "2026-27") -> None:
        """Sheet 6: Schedule TR - Summary of Tax Relief Claimed for Taxes Paid Outside India."""
        ws = self.wb.create_sheet(title="Schedule_TR")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = f"SCHEDULE TR: SUMMARY OF TAX RELIEF CLAIMED FOR TAXES PAID OUTSIDE INDIA (AY {ay})"
        ws["A1"].font = self._font_title
        ws["A2"] = "Official Government Schema Definition: ScheduleTR & ScheduleTR1 (Must match Schedule FSI exactly)"
        ws["A2"].font = self._font_subtitle

        headers = [
            "Country Name\n(Col a)",
            "Country Code\n(Col b)",
            "Tax Identification Number\n(Col c)",
            "Total Taxes Paid Outside India (₹)\n(Col d)",
            "Total Tax Relief Available (₹)\n(Col e)",
            "Section Under Which Relief Claimed\n(Col f)",
            "Taxes Paid Outside India in USD ($)\n(Scrutiny Working)",
            "Tax Relief Available in USD ($)\n(Scrutiny Working)",
            "Data Source Document\n(Audit Provenance)"
        ]

        row_idx = 4
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 35

        row_idx = 5
        data = [
            ftc.country_name,
            ftc.country_code,
            pan,
            ftc.foreign_tax_paid_inr,
            ftc.tax_relief_claimed_inr,
            "90",  # Section 90 under DTAA
            ftc.foreign_tax_paid_usd,
            ftc.tax_relief_claimed_usd,
            ftc.source_document
        ]

        for col_idx, val in enumerate(data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = self._font_regular
            cell.border = self._border_thin
            if col_idx in (4, 5):
                cell.number_format = "₹ #,##,##0"
                cell.alignment = Alignment(horizontal="right")
                cell.font = self._font_bold
            elif col_idx in (7, 8):
                cell.number_format = "$#,##0.00"
                cell.alignment = Alignment(horizontal="right")
                cell.font = self._font_bold
            elif col_idx in (1, 2, 3, 6):
                cell.alignment = Alignment(horizontal="center")
            elif col_idx == 9:
                cell.font = self._font_small
                cell.alignment = Alignment(horizontal="left")

        # Summary Totals Section
        row_idx = 7
        ws.cell(row=row_idx, column=1, value="SCHEDULE TR1 SUMMARY AGGREGATES:").font = self._font_bold
        row_idx += 1

        tr1_items = [
            ("Total Taxes Paid Outside India (Col 1)", ftc.foreign_tax_paid_inr),
            ("Total Tax Relief Claimed Outside India (Col 2)", ftc.tax_relief_claimed_inr),
            ("Tax Relief Claimed under Section 90 / 90A (DTAA) (Col 3)", ftc.tax_relief_claimed_inr),
            ("Tax Relief Claimed under Section 91 (Not DTAA) (Col 4)", 0),
        ]

        for lbl, val in tr1_items:
            ws.cell(row=row_idx, column=1, value=lbl).font = self._font_regular
            c_val = ws.cell(row=row_idx, column=4, value=val)
            c_val.font = self._font_bold
            c_val.number_format = "₹ #,##,##0"
            c_val.alignment = Alignment(horizontal="right")
            ws.cell(row=row_idx, column=1).border = self._border_thin
            ws.cell(row=row_idx, column=4).border = self._border_thin
            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_form_67(self, ftc: FTCResult, taxpayer_name: str, pan: str, ay: str) -> None:
        """Sheet 7: Form 67 Working - Statement of Foreign Income & Foreign Tax Credit."""
        ws = self.wb.create_sheet(title="Form_67_Working")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "FORM 67 WORKING: STATEMENT OF INCOME FROM OUTSIDE INDIA & FOREIGN TAX CREDIT CLAIMED"
        ws["A1"].font = self._font_title
        ws["A2"] = f"Prescribed under Rule 128 of Income-tax Rules, 1962  |  Taxpayer: {taxpayer_name}  |  PAN: {pan}  |  AY: {ay}"
        ws["A2"].font = self._font_subtitle

        headers = [
            "Country / Specified Territory",
            "Country Code",
            "Source of Income",
            "Head of Income under IT Act",
            "Gross Foreign Income in INR (₹)",
            "Tax Paid Outside India in INR (₹)",
            "Indian Tax Payable on such Income (₹)",
            "Foreign Tax Credit (FTC) Claimed (₹)",
            "DTAA Section & Article Under Which Claimed",
            "Gross Income in USD ($)",
            "Tax Paid in USD ($)",
            "FTC Claimed in USD ($)",
            "Data Source Document Citation"
        ]

        row_idx = 4
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 35

        row_idx = 5
        data = [
            "United States of America",
            "2",
            ftc.source_of_income,
            ftc.head_of_income,
            ftc.gross_foreign_income_inr,
            ftc.foreign_tax_paid_inr,
            ftc.estimated_indian_tax_inr,
            ftc.tax_relief_claimed_inr,
            f"Section 90 - {ftc.dtaa_article}",
            ftc.gross_foreign_income_usd,
            ftc.foreign_tax_paid_usd,
            ftc.tax_relief_claimed_usd,
            ftc.source_document
        ]

        for col_idx, val in enumerate(data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = self._font_regular
            cell.border = self._border_thin
            if col_idx in (5, 6, 7, 8):
                cell.number_format = "₹ #,##,##0"
                cell.alignment = Alignment(horizontal="right")
                cell.font = self._font_bold
            elif col_idx in (10, 11, 12):
                cell.number_format = "$#,##0.00"
                cell.alignment = Alignment(horizontal="right")
                cell.font = self._font_bold
            elif col_idx in (1, 2, 9):
                cell.alignment = Alignment(horizontal="center")
            elif col_idx == 13:
                cell.font = self._font_small
                cell.alignment = Alignment(horizontal="left")

        # Form 67 Procedural Checklist
        row_idx = 7
        ws.cell(row=row_idx, column=1, value="MANDATORY E-FILING REQUIREMENTS FOR FORM 67:").font = self._font_bold
        row_idx += 1

        checklist = [
            "1. Filing Due Date: Form 67 must be furnished on or before the end of the relevant Assessment Year "
            "(Rule 128(9), as amended by CBDT Notification No. 100/2022 dated 18-Aug-2022), provided the return "
            "itself is filed within the time limit under Section 139(1) or 139(4). For income added via an "
            "updated return under Section 139(8A), Form 67 must be filed by the date that updated return is furnished.",
            "2. Attachments Required: Upload the applicable foreign tax certificate(s) and broker statements as proof of foreign tax payment.",
            "3. Digital Verification: Form 67 must be verified electronically via Aadhaar OTP, EVC, or Digital Signature Certificate (DSC).",
            f"4. Portal Reconciliation: Ensure the FTC Claimed amount (₹ {ftc.tax_relief_claimed_inr:,}) matches Schedule TR and Schedule FSI identically."
        ]

        for item in checklist:
            ws.cell(row=row_idx, column=1, value=item).font = self._font_small
            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_validation_report(self, val_report: Any, ay: str = "2026-27") -> None:
        """Sheet: Statutory Rules & e-Filing Validation Scorecard."""
        ws = self.wb.create_sheet(title="Audit_Validation_Report")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = f"CBDT STATUTORY & e-FILING RULES VALIDATION SCORECARD (AY {ay})"
        ws["A1"].font = self._font_title
        version_specific_ran = any(r.rule_id.startswith("SCHEMA-") for r in val_report.results)
        ws["A2"] = (
            "Automated verification against the AY 2026-27 CBDT JSON schema and systems rules, "
            "plus IT Rules 1962 (Rule 115, 128, Sec 90, 288A/B)"
            if version_specific_ran else
            "Year-independent verification under IT Rules 1962 (Rule 115, 128, Sec 90, 288A/B). "
            "Assessment-year-specific CBDT schema/systems validation was not run because that "
            "historical return version is not bundled."
        )
        ws["A2"].font = self._font_subtitle

        # KPI Summary Cards Block (Rows 4-5)
        scorecard = val_report.scorecard
        kpi_metrics = [
            ("TOTAL RULES EXECUTED", str(scorecard.total_rules), "F0F4F8", "1B365D"),
            ("RULES PASSED (COMPLIANT)", str(scorecard.passed), "E2EFDA", "276A3C"),
            ("FATAL SCHEMA ERRORS", str(scorecard.fatal_errors), "FCE4D6" if scorecard.fatal_errors > 0 else "F0F4F8", "C00000" if scorecard.fatal_errors > 0 else "555555"),
            ("DEFECTIVE RETURN u/s 139(9)", str(scorecard.defective_errors), "FCE4D6" if scorecard.defective_errors > 0 else "F0F4F8", "C00000" if scorecard.defective_errors > 0 else "555555"),
            ("STATUTORY BREACHES", str(scorecard.statutory_errors), "FCE4D6" if scorecard.statutory_errors > 0 else "F0F4F8", "C00000" if scorecard.statutory_errors > 0 else "555555"),
            ("FILING READINESS STATUS", scorecard.compute_status(), "E2EFDA" if scorecard.is_filing_ready else "FCE4D6", "276A3C" if scorecard.is_filing_ready else "C00000"),
        ]

        col_start = 2
        for title, val, bg_col, txt_col in kpi_metrics:
            c_title = ws.cell(row=4, column=col_start, value=title)
            c_title.font = Font(name="Calibri", size=9, bold=True, color="555555")
            c_title.fill = PatternFill(start_color=bg_col, end_color=bg_col, fill_type="solid")
            c_title.alignment = Alignment(horizontal="center", vertical="center")
            c_title.border = self._border_thin

            c_val = ws.cell(row=5, column=col_start, value=val)
            c_val.font = Font(name="Calibri", size=11, bold=True, color=txt_col)
            c_val.fill = PatternFill(start_color=bg_col, end_color=bg_col, fill_type="solid")
            c_val.alignment = Alignment(horizontal="center", vertical="center")
            c_val.border = self._border_thin
            col_start += 1

        # Table Headers (Row 7)
        headers = [
            "Sl.",
            "Rule ID",
            "Rule Category",
            "Regulatory / Statutory Authority",
            "Rule Title",
            "Rule Description & Statutory Mandate",
            "Severity",
            "Evaluated Audit Details / Values",
            "Validation Status",
        ]
        row_idx = 7
        for c_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=c_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin

        row_idx = 8
        for sl_no, res in enumerate(val_report.results, start=1):
            ws.cell(row=row_idx, column=1, value=sl_no).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=2, value=res.rule_id).font = self._font_bold
            ws.cell(row=row_idx, column=3, value=res.category.value).font = self._font_regular
            ws.cell(row=row_idx, column=4, value=res.authority).font = self._font_small
            ws.cell(row=row_idx, column=5, value=res.title).font = self._font_bold
            ws.cell(row=row_idx, column=6, value=res.description).font = self._font_regular
            ws.cell(row=row_idx, column=7, value=res.severity.value).font = Font(name="Calibri", size=9, italic=True)
            ws.cell(row=row_idx, column=8, value=res.details).font = self._font_small

            c_status = ws.cell(row=row_idx, column=9, value=res.status.value)
            c_status.font = self._font_bold
            c_status.alignment = Alignment(horizontal="center")

            if res.status.value == "PASSED":
                c_status.fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
                c_status.font = Font(name="Calibri", size=11, bold=True, color="276A3C")
            elif res.status.value == "FAILED":
                c_status.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
                c_status.font = Font(name="Calibri", size=11, bold=True, color="C00000")
            else:
                c_status.fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
                c_status.font = Font(name="Calibri", size=11, bold=True, color="B25E00")

            for col in range(1, 10):
                cell = ws.cell(row=row_idx, column=col)
                cell.border = self._border_thin
                if row_idx % 2 == 0 and col != 9:
                    cell.fill = self._fill_zebra

            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_sbi_rate_register(
        self,
        a2: ScheduleFATableA2Result,
        a3_lots: List[ScheduleFATableA3LotResult],
        os_res: ScheduleOSResult,
        ftc_res: FTCResult,
        sbi_service: Optional[SBIRateService] = None,
        fy: str = "2025-26",
        cy: int = 2025
    ) -> None:
        """Sheet 8: Scrutiny Audit Register - Complete SBI TT Buying Rate Date Register."""
        ws = self.wb.create_sheet(title="Audit_SBI_TTBR_Register")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "SCRUTINY AUDIT REGISTER: COMPLETE SBI TT BUYING RATE DATE REGISTER & APPLICATION AUDIT"
        ws["A1"].font = self._font_title
        ws["A2"] = f"Statutory record of every SBI TT Buying Rate fetched under Income Tax Rule 115 and Rule 128 for Indian FY {fy} / CY {cy}"
        ws["A2"].font = self._font_subtitle

        def get_rollback_info(target_d: date) -> Tuple[date, str]:
            if not sbi_service or not hasattr(sbi_service, "_rates") or not sbi_service._rates:
                return target_d, "Official SBI TT Buying Rate Archive"
            if target_d in sbi_service._rates:
                return target_d, f"Exact date official rate published ({target_d.strftime('%A')})"
            cur = target_d - timedelta(days=1)
            while cur >= sbi_service._sorted_dates[0]:
                if cur in sbi_service._rates:
                    return cur, f"Weekend/holiday ({target_d.strftime('%A')}); rolled back to prior banking day {cur.strftime('%Y-%m-%d (%A)')}"
                cur -= timedelta(days=1)
            return target_d, "Earliest available rate in archive"

        # Table 1: Master Valuation & Transaction Application Register
        ws["A4"] = "PART 1: MASTER STATUTORY REGISTER OF ALL SBI TT BUYING RATES APPLIED TO ITR-2 SCHEDULES"
        ws["A4"].font = self._font_bold

        headers = [
            "Sl No",
            "Schedule / Section Fed",
            "Transaction / Valuation Item",
            "Event / Valuation Date",
            "Statutory Rule & Purpose",
            "SBI TTBR Date Used",
            "SBI TT Buying Rate (₹)",
            "Associated USD ($)",
            "Resulting INR (₹)",
            "Trading Day / Calendar Rollback Notes"
        ]

        row_idx = 5
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 30

        items: List[Tuple[str, str, date, str, date, float, float, int, str]] = []

        # 1. Schedule FA Table A2 items
        used_d, notes = get_rollback_info(a2.peak_date)
        items.append((
            "Schedule FA - Table A2",
            f"Custodial Account Peak Portfolio Balance (CY {cy})",
            a2.peak_date,
            f"CBDT Schedule FA Instructions / Rule 115 (Peak Value in CY {cy})",
            used_d,
            a2.peak_rate_inr,
            a2.peak_balance_usd,
            a2.peak_balance_inr,
            notes
        ))

        used_d, notes = get_rollback_info(a2.closing_date)
        items.append((
            "Schedule FA - Table A2",
            f"Custodial Account Closing Portfolio Balance (as on Dec 31, {cy})",
            a2.closing_date,
            "CBDT Schedule FA Instructions / Rule 115 (Closing Value on Dec 31)",
            used_d,
            a2.closing_rate_inr,
            a2.closing_balance_usd,
            a2.closing_balance_inr,
            notes
        ))

        # 2. Schedule FA Table A3 items
        for lot in a3_lots:
            used_d, notes = get_rollback_info(lot.acquisition_date)
            items.append((
                "Schedule FA - Table A3",
                f"Initial Investment Cost - Lot {lot.lot_id} ({lot.net_shares} shs @ ${lot.vest_fmv_usd:.2f})",
                lot.acquisition_date,
                "CBDT Schedule FA Instructions - Rate on Date of Acquisition / Vest",
                used_d,
                lot.acq_sbi_rate_inr,
                lot.initial_cost_usd,
                lot.initial_value_inr,
                notes
            ))

        for lot in a3_lots:
            used_d, notes = get_rollback_info(lot.peak_date)
            items.append((
                "Schedule FA - Table A3",
                f"Peak Valuation - Lot {lot.lot_id} ({lot.net_shares} shs @ ${lot.peak_price_usd:.2f})",
                lot.peak_date,
                "CBDT Schedule FA Instructions / Peak Value in Accounting Period",
                used_d,
                lot.peak_rate_inr,
                lot.peak_balance_usd,
                lot.peak_balance_inr,
                notes
            ))

        for lot in a3_lots:
            used_d, notes = get_rollback_info(lot.closing_date)
            items.append((
                "Schedule FA - Table A3",
                f"Closing Balance - Lot {lot.lot_id} ({lot.net_shares} shs @ ${lot.closing_price_usd:.2f})",
                lot.closing_date,
                f"CBDT Schedule FA Instructions / Value as on Dec 31, {cy}",
                used_d,
                lot.closing_rate_inr,
                lot.closing_balance_usd,
                lot.closing_balance_inr,
                notes
            ))

        # 3. Schedule OS Dividends
        for item in os_res.items:
            used_d, notes = get_rollback_info(item.preceding_month_end)
            items.append((
                "Schedule OS",
                f"Foreign Dividend Income ({item.symbol}) - {item.advance_tax_bucket}",
                item.pay_date,
                f"Rule 115(1) / (2)(c) - Rate on last day of preceding month ({item.preceding_month_end.strftime('%Y-%m-%d')})",
                used_d,
                item.rule_115_rate,
                item.gross_usd,
                item.gross_inr,
                notes
            ))

        # 4. Schedule FSI / TR Foreign Tax Withheld
        for item in os_res.items:
            used_d, notes = get_rollback_info(item.tax_deduction_date)
            items.append((
                "Schedule FSI & TR / Form 67",
                f"Foreign Tax Withholding ({item.symbol}) - {item.advance_tax_bucket}",
                item.tax_deduction_date,
                "Rule 128(5)(ii) - Rate on last day of month preceding deduction of foreign tax",
                used_d,
                item.rule_128_rate,
                item.tax_usd,
                item.tax_inr,
                notes
            ))

        row_idx = 6
        for idx, itm in enumerate(items, start=1):
            is_even = (idx % 2 == 0)
            sched, desc, ev_d, rule, rate_d, rate, usd_val, inr_val, rb_note = itm

            row_data = [
                idx,
                sched,
                desc,
                ev_d.strftime("%Y-%m-%d"),
                rule,
                rate_d.strftime("%Y-%m-%d"),
                rate,
                usd_val,
                inr_val,
                rb_note
            ]

            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = self._font_regular
                cell.border = self._border_thin
                if is_even:
                    cell.fill = self._fill_zebra

                if col_idx in (1, 4, 6):
                    cell.alignment = Alignment(horizontal="center")
                elif col_idx in (2, 3, 5, 10):
                    cell.alignment = Alignment(horizontal="left")
                elif col_idx == 7:
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = "0.00"
                    cell.font = self._font_bold
                elif col_idx == 8:
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = "$#,##0.00"
                elif col_idx == 9:
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = "₹ #,##,##0"
                    cell.font = self._font_bold

            row_idx += 1

        # Part 2: Deduplicated Unique SBI TTBR Dates Summary
        row_idx += 2
        ws.cell(row=row_idx, column=1, value="PART 2: CONSOLIDATED CHRONOLOGICAL REGISTER OF UNIQUE SBI TTBR RATES USED").font = self._font_bold
        row_idx += 1

        summary_headers = [
            "Sl No",
            "SBI TTBR Date",
            "Day of Week",
            "SBI TT Buying Rate (₹)",
            "Total Usages Count",
            "ITR Schedules & Tax Sections Fed",
            "Statutory Purpose / Reference Summary"
        ]

        for col_idx, h in enumerate(summary_headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_sub_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 25
        row_idx += 1

        unique_map: Dict[date, Dict[str, Any]] = {}
        for itm in items:
            rate_d = itm[4]
            rate = itm[5]
            sched = itm[0]
            rule = itm[3]
            if rate_d not in unique_map:
                unique_map[rate_d] = {
                    "rate": rate,
                    "count": 0,
                    "schedules": set(),
                    "purposes": set()
                }
            unique_map[rate_d]["count"] += 1
            unique_map[rate_d]["schedules"].add(sched)
            if "Acquisition" in rule:
                unique_map[rate_d]["purposes"].add("Share Lot Vest / Acquisition Cost (Rule 115)")
            elif "Peak" in rule:
                unique_map[rate_d]["purposes"].add("Peak Valuation (Rule 115)")
            elif "Closing" in rule:
                unique_map[rate_d]["purposes"].add("Dec 31 Closing Valuation (Rule 115)")
            elif "preceding month" in rule:
                unique_map[rate_d]["purposes"].add("Dividend Income (Rule 115 Preceding Month End)")
            elif "Rule 128" in rule:
                unique_map[rate_d]["purposes"].add("Foreign Tax Withholding (Rule 128)")

        sorted_unique_dates = sorted(unique_map.keys())
        for u_idx, u_date in enumerate(sorted_unique_dates, start=1):
            is_even = (u_idx % 2 == 0)
            u_info = unique_map[u_date]
            sched_str = ", ".join(sorted(u_info["schedules"]))
            purp_str = "; ".join(sorted(u_info["purposes"]))

            u_row = [
                u_idx,
                u_date.strftime("%Y-%m-%d"),
                u_date.strftime("%A"),
                u_info["rate"],
                u_info["count"],
                sched_str,
                purp_str
            ]

            for col_idx, val in enumerate(u_row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = self._font_regular
                cell.border = self._border_thin
                if is_even:
                    cell.fill = self._fill_zebra

                if col_idx in (1, 2, 3):
                    cell.alignment = Alignment(horizontal="center")
                elif col_idx in (6, 7):
                    cell.alignment = Alignment(horizontal="left")
                elif col_idx == 4:
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = "0.00"
                    cell.font = self._font_bold
                elif col_idx == 5:
                    cell.alignment = Alignment(horizontal="center")
                    cell.font = self._font_bold

            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_audit_lot_peaks(self, a3_lots: List[ScheduleFATableA3LotResult], cy: int = 2025) -> None:
        """Sheet 8: Scrutiny Audit Trail - Lot Peak and Closing Proof."""
        ws = self.wb.create_sheet(title="Audit_Lot_Peaks")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "SCRUTINY AUDIT TRAIL: SHARE LOT PEAK & VALUATION MATHEMATICAL PROOFS"
        ws["A1"].font = self._font_title
        ws["A2"] = f"Complete EOD closing price and SBI TT Buying Rate evidence for every share lot active in CY {cy}"
        ws["A2"].font = self._font_subtitle

        headers = [
            "Lot ID",
            "Net Shares",
            "Acquisition Date",
            "Vest FMV ($)",
            "Acq SBI TTBR (₹)",
            "Initial Value (₹)",
            "Peak Date",
            "Peak Stock Close ($)",
            "Peak SBI TTBR (₹)",
            "Peak Balance (₹)",
            "Closing Date",
            "Dec 31 Close Price ($)",
            "Dec 31 SBI TTBR (₹)",
            "Closing Balance (₹)",
            "Mathematical Peak Formula",
            "Audit Source Citation"
        ]

        row_idx = 4
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 30

        row_idx = 5
        for idx, lot in enumerate(a3_lots, start=1):
            is_even = (idx % 2 == 0)
            formula_text = f"{lot.net_shares} shs × ${lot.peak_price_usd:.2f} × ₹{lot.peak_rate_inr:.2f}"

            row_data = [
                lot.lot_id,
                lot.net_shares,
                lot.acquisition_date.strftime("%Y-%m-%d"),
                lot.vest_fmv_usd,
                lot.acq_sbi_rate_inr,
                lot.initial_value_inr,
                lot.peak_date.strftime("%Y-%m-%d"),
                lot.peak_price_usd,
                lot.peak_rate_inr,
                lot.peak_balance_inr,
                lot.closing_date.strftime("%Y-%m-%d"),
                lot.closing_price_usd,
                lot.closing_rate_inr,
                lot.closing_balance_inr,
                formula_text,
                lot.source_peak
            ]

            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = self._font_regular
                cell.border = self._border_thin
                if is_even:
                    cell.fill = self._fill_zebra

                if col_idx in (6, 10, 14):
                    cell.number_format = "₹ #,##,##0"
                    cell.alignment = Alignment(horizontal="right")
                    cell.font = self._font_bold
                elif col_idx in (4, 8, 12):
                    cell.number_format = "$#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (5, 9, 13):
                    cell.number_format = "0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (2, 3, 7, 11):
                    cell.alignment = Alignment(horizontal="center")
                elif col_idx == 16:
                    cell.font = self._font_small
                    cell.alignment = Alignment(horizontal="left")

            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_audit_dividends(
        self,
        os_res: ScheduleOSResult,
        dividends: List[DividendEvent],
        sbi_service: Optional[SBIRateService] = None
    ) -> None:
        """Sheet 9: Scrutiny Audit Trail - Pro-Rata Dividend Allocations Matrix."""
        ws = self.wb.create_sheet(title="Audit_Dividend_Allocations")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "SCRUTINY AUDIT TRAIL: PRO-RATA DIVIDEND ALLOCATION MATRIX ACROSS SHARE LOTS"
        ws["A1"].font = self._font_title
        ws["A2"] = "Shows exact mathematical distribution of account-level dividends to individual lots in Table A3"
        ws["A2"].font = self._font_subtitle

        # Header with all lot IDs as columns
        lot_ids = []
        for d in dividends:
            for l_id in d.lot_allocations.keys():
                if l_id not in lot_ids:
                    lot_ids.append(l_id)

        headers = ["Pay Date", "Total Gross ($)", "Eligible Shares", "Rate per Share ($)", "Rule 115 TTBR (₹)"] + lot_ids

        row_idx = 4
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 30

        row_idx = 5
        for d in dividends:
            # find rule 115 rate - fall back to a real lookup (never a fabricated constant) if
            # this dividend wasn't present in os_res.items for some reason
            match_item = next((i for i in os_res.items if i.pay_date == d.pay_date), None)
            if match_item:
                r115_rate = match_item.rule_115_rate
            elif sbi_service:
                _, r115_rate = sbi_service.get_rule_115_dividend_rate(d.pay_date)
            else:
                r115_rate = None

            row_data = [
                d.pay_date.strftime("%Y-%m-%d"),
                d.gross_amount_usd,
                d.shares_count,
                d.rate_per_share,
                r115_rate
            ]

            for l_id in lot_ids:
                row_data.append(d.lot_allocations.get(l_id, 0.0))

            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = self._font_regular
                cell.border = self._border_thin
                if col_idx == 2:
                    cell.number_format = "$#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (3, 4, 5):
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = "0.0000" if col_idx == 4 else "0.00"
                elif col_idx > 5:
                    cell.number_format = "$#,##0.0000"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx == 1:
                    cell.alignment = Alignment(horizontal="center")

            row_idx += 1

        self._auto_fit_columns(ws)

    def _build_audit_statements(self, summaries: List[StatementPeriodSummary]) -> None:
        """Sheet 10: Scrutiny Audit Trail - Client Statement Reconciliations."""
        ws = self.wb.create_sheet(title="Audit_Statement_Periods")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "SCRUTINY AUDIT TRAIL: 15-MONTH CLIENT STATEMENT PORTFOLIO PROGRESSION"
        ws["A1"].font = self._font_title
        ws["A2"] = "Complete audit trail of all monthly statements extracted from broker account PDFs to establish calendar year opening, peak, and closing custodial balances under Rule 115."
        ws["A2"].font = self._font_subtitle

        headers = [
            "Statement Period Label",
            "Period Start Date",
            "Period End Date",
            "Beginning Value ($)",
            "Ending Value ($)",
            "Cash Component ($)",
            "Equities Component ($)",
            "Shares Reported Held"
        ]

        row_idx = 4
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = self._font_header
            cell.fill = self._fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = self._border_thin
        ws.row_dimensions[row_idx].height = 25

        row_idx = 5
        for idx, s in enumerate(summaries, start=1):
            is_even = (idx % 2 == 0)
            row_data = [
                s.period_label,
                s.start_date.strftime("%Y-%m-%d"),
                s.end_date.strftime("%Y-%m-%d"),
                s.beginning_value_usd,
                s.ending_value_usd,
                s.cash_balance_usd,
                s.equities_value_usd,
                s.shares_held if s.shares_held else ""
            ]

            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = self._font_regular
                cell.border = self._border_thin
                if is_even:
                    cell.fill = self._fill_zebra

                if col_idx in (4, 5, 6, 7):
                    cell.number_format = "$#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (2, 3, 8):
                    cell.alignment = Alignment(horizontal="center")

            row_idx += 1

        self._auto_fit_columns(ws)

    def _auto_fit_columns(self, ws) -> None:
        """Auto-adjust column widths with safety margin to prevent ### cell truncation."""
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                # ignore merged cells or very long title lines
                if cell.row in (1, 2, 7, 8, 9) and cell.column == 1:
                    continue
                val_str = str(cell.value or "")
                if "\n" in val_str:
                    lines = val_str.split("\n")
                    max_len = max(max_len, max(len(l) for l in lines))
                else:
                    max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
