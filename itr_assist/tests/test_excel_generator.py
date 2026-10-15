"""Unit tests for ITRWorkbookGenerator without external file fixtures."""
from datetime import date, timedelta
import os
import unittest
import openpyxl

from itr_assist.models import (
    DividendEvent,
    Form1042SData,
    LotStatus,
    PlanType,
    ShareLot,
    StatementPeriodSummary,
)
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.reconciliation.verifier import DocumentVerifier
from itr_assist.reports.excel_generator import ITRWorkbookGenerator
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import ValuationEngine


class TestITRWorkbookGenerator(unittest.TestCase):
    """Unit tests for Excel workbook generation using in-memory synthetic models."""

    @classmethod
    def setUpClass(cls):
        cls.output_file = "test_ITR2_Foreign_Assets_Working.xlsx"
        cls.sbi = SBIRateService()
        cls.mkt = MarketDataService(auto_download=False)

        # In-memory pricing
        acme_prices = {}
        cur = date(2023, 1, 1)
        end_dt = date(2026, 12, 31)
        while cur <= end_dt:
            if cur.weekday() < 5:
                acme_prices[cur] = {"open": 99.0, "high": 102.0, "low": 98.0, "close": 100.0}
            cur += timedelta(days=1)
        cls.mkt._price_cache["ACME"] = acme_prices

        # In-memory historical lots
        sold_lot = ShareLot(
            lot_id="ACME-ESPP-20231201",
            symbol="ACME",
            plan_type=PlanType.ESPP,
            acquisition_date=date(2023, 12, 1),
            gross_shares=6.0,
            withheld_shares=0.0,
            net_shares=6.0,
            vest_fmv_usd=70.0,
            cost_basis_per_share_usd=70.0,
            remaining_shares=0.0,
            status=LotStatus.FULLY_SOLD,
            disposal_date=date(2025, 6, 15),
            disposal_qty=6.0,
        )
        rsu_lot = ShareLot(
            lot_id="ACME-G100-T1-20240515",
            symbol="ACME",
            plan_type=PlanType.RSU,
            acquisition_date=date(2024, 5, 15),
            gross_shares=15.0,
            withheld_shares=5.0,
            net_shares=10.0,
            vest_fmv_usd=100.0,
            cost_basis_per_share_usd=100.0,
            remaining_shares=10.0,
            status=LotStatus.ACTIVE,
            grant_number="G100",
        )
        espp_lot = ShareLot(
            lot_id="ACME-ESPP-20240603",
            symbol="ACME",
            plan_type=PlanType.ESPP,
            acquisition_date=date(2024, 6, 3),
            gross_shares=5.0,
            withheld_shares=0.0,
            net_shares=5.0,
            vest_fmv_usd=80.0,
            cost_basis_per_share_usd=80.0,
            remaining_shares=5.0,
            status=LotStatus.ACTIVE,
        )
        cls.ledger = LotLedger([sold_lot, rsu_lot, espp_lot])

        # In-memory holdings
        h_rsu = ShareLot(
            lot_id="ACME-G100-T1-20240515",
            symbol="ACME",
            plan_type=PlanType.RSU,
            acquisition_date=date(2024, 5, 15),
            gross_shares=10.0,
            withheld_shares=0.0,
            net_shares=10.0,
            vest_fmv_usd=100.0,
            cost_basis_per_share_usd=100.0,
            remaining_shares=10.0,
            status=LotStatus.ACTIVE,
            grant_number="G100",
        )
        h_espp = ShareLot(
            lot_id="ACME-ESPP-20240603",
            symbol="ACME",
            plan_type=PlanType.ESPP,
            acquisition_date=date(2024, 6, 3),
            gross_shares=5.0,
            withheld_shares=0.0,
            net_shares=5.0,
            vest_fmv_usd=80.0,
            cost_basis_per_share_usd=80.0,
            remaining_shares=5.0,
            status=LotStatus.ACTIVE,
        )
        cls.holdings = [h_rsu, h_espp]

        # In-memory statement summaries and dividends
        cls.summaries = [
            StatementPeriodSummary(
                period_label="December 1-31, 2025",
                start_date=date(2025, 12, 1),
                end_date=date(2025, 12, 31),
                beginning_value_usd=2400.0,
                ending_value_usd=2800.0,
                cash_balance_usd=100.0,
                equities_value_usd=2700.0,
                shares_held=15.0,
            )
        ]
        cls.dividends = [
            DividendEvent(pay_date=date(2025, 3, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 6, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 9, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 12, 9), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
        ]

        cls.form_1042s = Form1042SData(
            calendar_year=2025,
            recipient_name="JOHN DOE",
            recipient_tin="ABCDE1234F",
            gross_dividend_usd=100.0,
            tax_withheld_usd=25.0,
            withholding_rate=0.25,
            withholding_agent="Morgan Stanley Smith Barney LLC",
            account_number="889-000000",
        )

        cls.verifier = DocumentVerifier(cls.ledger, cls.holdings)
        cls.report = cls.verifier.verify_holdings()

        cls.engine = ValuationEngine(
            cls.ledger,
            cls.sbi,
            cls.mkt,
            broker_name="Morgan Stanley Smith Barney LLC (E*TRADE)",
            account_number="ACC-1234567"
        )
        dec_summary = next(s for s in cls.summaries if s.end_date == date(2025, 12, 31))
        cls.a2 = cls.engine.compute_table_a2(2025, dec_summary, cls.dividends)
        cls.a3_lots = cls.engine.compute_table_a3(2025, cls.dividends)

        fy_divs = [d for d in cls.dividends if date(2025, 4, 1) <= d.pay_date <= date(2026, 3, 31)]
        cls.os_res, cls.ftc_res = cls.engine.compute_schedule_os_and_ftc(fy_divs)

        cls.generator = ITRWorkbookGenerator(output_path=cls.output_file)
        cls.generator.generate(
            a2_result=cls.a2,
            a3_lots=cls.a3_lots,
            os_result=cls.os_res,
            ftc_result=cls.ftc_res,
            form_1042s=cls.form_1042s,
            reconciliation_report=cls.report,
            dividends=cls.dividends,
            statement_summaries=cls.summaries
        )

        cls.wb = openpyxl.load_workbook(cls.output_file, data_only=False)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.output_file):
            try:
                os.remove(cls.output_file)
            except Exception:
                pass

    def test_sheets_present(self):
        expected_sheets = [
            "Dashboard_Summary",
            "Schedule_FA_Table_A2",
            "Schedule_FA_Table_A3",
            "Schedule_OS",
            "Schedule_FSI",
            "Schedule_TR",
            "Form_67_Working",
            "Audit_SBI_TTBR_Register",
            "Audit_Lot_Peaks",
            "Audit_Dividend_Allocations",
            "Audit_Statement_Periods"
        ]
        for s in expected_sheets:
            self.assertIn(s, self.wb.sheetnames)

    def test_table_a2_content(self):
        ws = self.wb["Schedule_FA_Table_A2"]
        # Row 5 has the account details
        self.assertEqual(ws["A5"].value, "UNITED STATES OF AMERICA")
        self.assertEqual(ws["B5"].value, "2")
        self.assertEqual(ws["C5"].value, "Morgan Stanley Smith Barney LLC (E*TRADE)")
        self.assertEqual(ws["F5"].value, "ACC-1234567")
        self.assertEqual(ws["G5"].value, "OWNER")
        # Peak Balance Group: Statutory Col 9 followed immediately by Working cols
        self.assertEqual(ws["I5"].value, 250516)  # Peak Balance INR
        self.assertAlmostEqual(ws["J5"].value, 2800.0, places=1)  # Peak USD (Working)
        self.assertEqual(ws["K5"].value, "2025-12-31")             # Peak Date
        self.assertAlmostEqual(ws["L5"].value, 89.47, places=1)    # Peak Rate
        self.assertIn("E*TRADE Statement", ws["M5"].value)         # Source Peak
        # Closing Balance Group: Statutory Col 10 followed immediately by Working cols
        self.assertEqual(ws["N5"].value, 250516)  # Closing INR
        self.assertAlmostEqual(ws["O5"].value, 2800.0, places=1)  # Closing USD (Working)
        self.assertEqual(ws["P5"].value, "2025-12-31")             # Closing Date
        self.assertAlmostEqual(ws["Q5"].value, 89.47, places=1)    # Closing Rate
        self.assertIn("E*TRADE Statement", ws["R5"].value)         # Source Closing
        # Gross Amount Group: Statutory Col 11 followed immediately by Working cols
        self.assertEqual(ws["S5"].value, 8736)    # Gross Amount INR
        self.assertAlmostEqual(ws["T5"].value, 100.0, places=1)    # Gross USD (Working)
        self.assertIn("E*TRADE CY 2025 Statement", ws["U5"].value) # Source Gross
        self.assertEqual(ws["V5"].value, "D")     # Nature of Amount (Col 12)

    def test_table_a3_content(self):
        ws = self.wb["Schedule_FA_Table_A3"]
        # Must have header on row 4 and 3 lot rows from row 5 to 7
        self.assertEqual(ws["B5"].value, "ACME-ESPP-20231201")
        self.assertEqual(ws["C5"].value, "UNITED STATES OF AMERICA")
        self.assertEqual(ws["D5"].value, "2")
        self.assertEqual(ws["I5"].value, "2023-12-01")

        # Initial Investment Group: Col 10 Statutory followed immediately by Working cols 11-15
        self.assertEqual(ws["J5"].value, 34810)                    # Initial Value INR (Col 8)
        self.assertAlmostEqual(ws["K5"].value, 420.0, places=1)    # Initial Cost USD (Working)
        self.assertEqual(ws["L5"].value, 6.0)                      # Net Shares
        self.assertAlmostEqual(ws["M5"].value, 70.0, places=1)     # Vest FMV USD
        self.assertAlmostEqual(ws["N5"].value, 82.88, places=1)    # Acq SBI Rate
        self.assertIn("Benefit History", ws["O5"].value)           # Source Initial

        # Peak Balance Group: Col 16 Statutory followed immediately by Working cols 17-21
        self.assertEqual(ws["P5"].value, 52260)                    # Peak Balance INR (Col 9)
        self.assertAlmostEqual(ws["Q5"].value, 600.0, places=1)    # Peak Value USD (Working)
        self.assertAlmostEqual(ws["R5"].value, 100.0, places=1)    # Peak Stock Close
        self.assertEqual(ws["S5"].value, "2025-02-06")             # Peak Valuation Date
        self.assertAlmostEqual(ws["T5"].value, 87.10, places=1)    # Peak SBI Rate
        self.assertIn("Yahoo Finance", ws["U5"].value)             # Source Peak

        # Closing Balance Group: Col 22 Statutory followed immediately by Working cols 23-27
        self.assertEqual(ws["V5"].value, 0)                        # Closing Balance INR (Col 10)
        self.assertAlmostEqual(ws["W5"].value, 0.0, places=1)      # Closing Value USD (Working)
        self.assertAlmostEqual(ws["X5"].value, 0.0, places=1)      # Dec 31 Close Price
        self.assertEqual(ws["Y5"].value, "2025-12-31")             # Dec 31 Date
        self.assertAlmostEqual(ws["Z5"].value, 89.47, places=1)    # Dec 31 SBI Rate
        self.assertIn("Yahoo Finance", ws["AA5"].value)            # Source Closing

        # Gross Dividends & Sold Lot Flag
        self.assertEqual(ws["AB5"].value, 1229)                    # Gross Dividends INR (Col 11)
        self.assertAlmostEqual(ws["AC5"].value, 14.29, places=1)   # Gross Dividends USD (Working)
        self.assertEqual(ws["AE5"].value, 0)                       # Gross Proceeds INR (Col 12)
        self.assertIn("Sold Lot", ws["AF4"].value)                 # Sold Lot Header
        self.assertEqual(ws["AF5"].value, "YES (Sold 2026)")       # Sold Lot Flag

        # Check total formulas on row 8
        self.assertEqual(ws["J8"].value, "=SUM(J5:J7)")            # Initial Value INR Total
        self.assertEqual(ws["K8"].value, "=SUM(K5:K7)")            # Initial Cost USD Total
        self.assertEqual(ws["L8"].value, "=SUM(L5:L7)")            # Shares Total
        self.assertEqual(ws["P8"].value, "=SUM(P5:P7)")            # Peak Balance INR Total
        self.assertEqual(ws["Q8"].value, "=SUM(Q5:Q7)")            # Peak Value USD Total
        self.assertEqual(ws["V8"].value, "=SUM(V5:V7)")            # Closing Balance INR Total
        self.assertEqual(ws["W8"].value, "=SUM(W5:W7)")            # Closing Value USD Total

    def test_sbi_rate_register_content(self):
        ws = self.wb["Audit_SBI_TTBR_Register"]
        # Verify title and headers
        self.assertIn("SCRUTINY AUDIT REGISTER", ws["A1"].value)
        self.assertEqual(ws["B5"].value, "Schedule / Section Fed")
        self.assertEqual(ws["G5"].value, "SBI TT Buying Rate (₹)")
        # Verify Table A2 Peak entry on row 6
        self.assertEqual(ws["B6"].value, "Schedule FA - Table A2")
        self.assertEqual(ws["D6"].value, "2025-12-31")
        self.assertAlmostEqual(ws["G6"].value, 89.47, places=1)
        self.assertAlmostEqual(ws["H6"].value, 2800.0, places=1)
        self.assertEqual(ws["I6"].value, 250516)

    def test_schedule_os_content(self):
        ws = self.wb["Schedule_OS"]
        # Installment values on rows 5 to 9
        self.assertEqual(ws["E5"].value, 2128)  # Upto15Of6
        self.assertEqual(ws["E6"].value, 2192)  # Upto15Of9
        self.assertEqual(ws["E7"].value, 2224)  # Up16Of9To15Of12
        self.assertEqual(ws["E8"].value, 0)     # Up16Of12To15Of3
        self.assertEqual(ws["E9"].value, 0)     # Up16Of3To31Of3
        self.assertEqual(ws["E10"].value, "=SUM(E5:E9)")

        # Verify transaction table has source document citation on row 15
        self.assertIn("E*TRADE Statement", ws["M15"].value)

    def test_schedule_fsi_and_tr_content(self):
        ws_fsi = self.wb["Schedule_FSI"]
        self.assertEqual(ws_fsi["E5"].value, 6544)  # Income outside India
        self.assertEqual(ws_fsi["F5"].value, 1643)  # Tax paid outside India
        self.assertEqual(ws_fsi["H5"].value, 1643)  # Relief available
        self.assertEqual(ws_fsi["I5"].value, "Article 10")
        self.assertAlmostEqual(ws_fsi["J5"].value, 75.0, places=1)  # Income USD
        self.assertAlmostEqual(ws_fsi["K5"].value, 18.75, places=1) # Tax USD
        self.assertIn("Form 1042-S", ws_fsi["M5"].value)

        ws_tr = self.wb["Schedule_TR"]
        self.assertEqual(ws_tr["D5"].value, 1643)  # Total tax paid
        self.assertEqual(ws_tr["E5"].value, 1643)  # Relief available
        self.assertEqual(ws_tr["F5"].value, "90")
        self.assertAlmostEqual(ws_tr["G5"].value, 18.75, places=1)  # Tax USD
        self.assertIn("Form 1042-S", ws_tr["I5"].value)

    def test_provenance_index_in_summary(self):
        ws = self.wb["Dashboard_Summary"]
        found_provenance = False
        for row in ws.iter_rows(values_only=True):
            if "MASTER INPUT DOCUMENT PROVENANCE INDEX" in [str(c) for c in row if c]:
                found_provenance = True
                break
        self.assertTrue(found_provenance, "Master provenance index header missing from summary sheet")


if __name__ == "__main__":
    unittest.main()
