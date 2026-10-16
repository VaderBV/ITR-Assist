"""Unit tests for LotLedger and DocumentVerifier without external file fixtures."""
from datetime import date
import unittest

from itr_assist.models import (
    DividendEvent,
    Form1042SData,
    LotStatus,
    PlanType,
    SaleEvent,
    ShareLot,
)
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.reconciliation.verifier import DocumentVerifier


class TestLotLedgerAndVerifier(unittest.TestCase):
    """Unit tests for reconciliation and verification engines using in-memory synthetic models."""

    @classmethod
    def setUpClass(cls):
        # 1. Historical Lots: 2 Active lots + 1 Sold lot (sold in 2025)
        cls.sold_lot = ShareLot(
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
        cls.rsu_lot = ShareLot(
            lot_id="ACME-RSU-G100-20240515",
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
        cls.espp_lot = ShareLot(
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
        cls.all_lots = [cls.sold_lot, cls.rsu_lot, cls.espp_lot]

        # 2. Holdings snapshot: 15 active shares
        cls.h_rsu = ShareLot(
            lot_id="ACME-RSU-G100-20240515",
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
        cls.h_espp = ShareLot(
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
        cls.holdings_lots = [cls.h_rsu, cls.h_espp]

        # 3. Quarterly Dividends: $100.00 gross, $25.00 tax
        cls.dividends = [
            DividendEvent(pay_date=date(2025, 3, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 6, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 9, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 12, 9), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
        ]

        # 4. Form 1042-S matching $100.00 and $25.00
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

        cls.ledger = LotLedger(cls.all_lots)
        cls.verifier = DocumentVerifier(cls.ledger, cls.holdings_lots)

    def test_schedule_fa_lots_count(self):
        """Schedule FA for CY 2025 must include all 3 lots held during the calendar year."""
        fa_lots = self.ledger.get_schedule_fa_lots(calendar_year=2025)
        self.assertEqual(len(fa_lots), 3)

    def test_sold_lot_inclusion_in_fa(self):
        """The 2023-12-01 ESPP lot (sold in 2025) must be included in Schedule FA despite 0 current shares."""
        fa_lots = self.ledger.get_schedule_fa_lots(calendar_year=2025)
        sold_lot = next((l for l in fa_lots if l.is_sold_lot), None)
        self.assertIsNotNone(sold_lot)
        self.assertEqual(sold_lot.net_shares, 6.0)
        self.assertTrue(sold_lot.is_sold_lot)

    def test_shares_progression_across_dates(self):
        """Verify exact share count on key chronological dates."""
        shares_jan1_24, _ = self.ledger.get_shares_held_on_date(date(2024, 1, 1))
        self.assertEqual(shares_jan1_24, 6.0)

        shares_may15_24, _ = self.ledger.get_shares_held_on_date(date(2024, 5, 15))
        self.assertEqual(shares_may15_24, 16.0)

        shares_jun3_24, _ = self.ledger.get_shares_held_on_date(date(2024, 6, 3))
        self.assertEqual(shares_jun3_24, 21.0)

        shares_jan1_25, _ = self.ledger.get_shares_held_on_date(date(2025, 1, 1))
        self.assertEqual(shares_jan1_25, 21.0)

        shares_dec31_25, _ = self.ledger.get_shares_held_on_date(date(2025, 12, 31))
        self.assertEqual(shares_dec31_25, 15.0)

    def test_holdings_verification_report(self):
        """Verify that reconciliation between Benefit History and Holdings reports MATCH."""
        report = self.verifier.verify_holdings()
        self.assertEqual(report.status, "MATCH")
        self.assertEqual(report.total_reconstructed_shares, 15.0)
        self.assertEqual(report.total_holdings_shares, 15.0)
        self.assertEqual(report.reconstructed_lots_count, 2)
        self.assertEqual(report.holdings_lots_count, 2)
        self.assertEqual(report.sold_lots_count, 1)
        self.assertEqual(len(report.discrepancies), 0)

    def test_form_1042s_verification(self):
        """Verify CY 2025 statement dividends match Form 1042-S within rounding tolerance."""
        cy_divs = [d for d in self.dividends if d.pay_date.year == 2025]
        cy_div_total = sum(d.gross_amount_usd for d in cy_divs)
        cy_tax_total = sum(d.tax_withheld_usd for d in cy_divs)

        notes = self.verifier.verify_tax_1042s(cy_div_total, cy_tax_total, self.form_1042s)
        self.assertTrue(any("Gross Dividend RECONCILED" in n for n in notes))
        self.assertTrue(any("Tax Withholding RECONCILED" in n for n in notes))

    def test_pro_rata_dividend_allocation(self):
        """Verify dividend allocation sums back up to gross dividend amount."""
        enriched_divs = self.ledger.allocate_dividends(self.dividends)
        for div in enriched_divs:
            allocated_sum = sum(div.lot_allocations.values())
            self.assertAlmostEqual(allocated_sum, div.gross_amount_usd, places=1)


class TestAllocateSales(unittest.TestCase):
    """Unit tests for LotLedger.allocate_sales() - FIFO lot matching, full and partial sales.

    Each test builds its own fresh lots/ledger since allocate_sales() mutates lot state
    in place (disposal dates, remaining_shares, and lot splitting on partial sales).
    """

    def _make_lot(self, lot_id, acq_date, net_shares, symbol="ACME"):
        return ShareLot(
            lot_id=lot_id,
            symbol=symbol,
            plan_type=PlanType.RSU,
            acquisition_date=acq_date,
            gross_shares=net_shares,
            withheld_shares=0.0,
            net_shares=net_shares,
            vest_fmv_usd=100.0,
            cost_basis_per_share_usd=100.0,
            remaining_shares=net_shares,
            status=LotStatus.ACTIVE,
        )

    def test_full_lot_sale_sets_disposal_and_zeroes_remaining(self):
        """Selling exactly a lot's full remaining quantity disposes it cleanly - no split."""
        lot = self._make_lot("LOT-A", date(2024, 5, 15), 10.0)
        ledger = LotLedger([lot])
        sale = SaleEvent(sale_date=date(2025, 6, 10), symbol="ACME", quantity=10.0,
                          price_usd=120.0, gross_proceeds_usd=1200.0)

        enriched = ledger.allocate_sales([sale])

        self.assertEqual(len(ledger.lots), 1)  # no split - fully consumed
        self.assertEqual(lot.disposal_date, date(2025, 6, 10))
        self.assertEqual(lot.remaining_shares, 0.0)
        self.assertEqual(lot.status, LotStatus.FULLY_SOLD)
        self.assertEqual(enriched[0].lot_allocations, {"LOT-A": 1200.0})
        self.assertTrue(lot.is_sold_lot)

    def test_partial_lot_sale_splits_into_disposed_and_remaining(self):
        """Selling less than a lot's full quantity splits it; the remaining portion stays active."""
        lot = self._make_lot("LOT-B", date(2024, 5, 15), 10.0)
        ledger = LotLedger([lot])
        sale = SaleEvent(sale_date=date(2025, 6, 10), symbol="ACME", quantity=4.0,
                          price_usd=120.0, gross_proceeds_usd=480.0)

        enriched = ledger.allocate_sales([sale])

        self.assertEqual(len(ledger.lots), 2)
        disposed = next(l for l in ledger.lots if l.is_sold_lot)
        remaining = next(l for l in ledger.lots if not l.is_sold_lot)

        self.assertEqual(disposed.net_shares, 4.0)
        self.assertEqual(disposed.disposal_date, date(2025, 6, 10))
        self.assertEqual(disposed.remaining_shares, 0.0)

        self.assertEqual(remaining.lot_id, "LOT-B")  # original lot, shrunk, not replaced
        self.assertEqual(remaining.net_shares, 6.0)
        self.assertEqual(remaining.remaining_shares, 6.0)
        self.assertIsNone(remaining.disposal_date)

        total_allocated = sum(enriched[0].lot_allocations.values())
        self.assertAlmostEqual(total_allocated, 480.0, places=2)

    def test_fifo_matches_oldest_lot_first_across_two_lots(self):
        """A sale spanning two lots must consume the OLDER acquisition first (FIFO)."""
        older = self._make_lot("LOT-OLD", date(2023, 1, 10), 5.0)
        newer = self._make_lot("LOT-NEW", date(2024, 1, 10), 10.0)
        ledger = LotLedger([newer, older])  # intentionally out of order on input
        # Sell 8 shares: should take all 5 from LOT-OLD, then 3 from LOT-NEW.
        sale = SaleEvent(sale_date=date(2025, 6, 10), symbol="ACME", quantity=8.0,
                          price_usd=100.0, gross_proceeds_usd=800.0)

        enriched = ledger.allocate_sales([sale])
        allocations = enriched[0].lot_allocations

        self.assertEqual(older.remaining_shares, 0.0)
        self.assertTrue(older.is_sold_lot)
        self.assertAlmostEqual(allocations["LOT-OLD"], 500.0, places=2)  # 5/8 of $800

        # LOT-NEW was only partially consumed (3 of 10) -> split into a disposed sub-lot
        # for those 3, and the original LOT-NEW id shrinks to the remaining 7.
        self.assertEqual(newer.net_shares, 7.0)
        self.assertEqual(newer.remaining_shares, 7.0)
        self.assertIsNone(newer.disposal_date)

        disposed_from_new = next(k for k in allocations if k.startswith("LOT-NEW-SOLD"))
        self.assertAlmostEqual(allocations[disposed_from_new], 300.0, places=2)  # 3/8 of $800

    def test_capital_gains_rate_matches_published_worked_example(self):
        """Explanation to Rule 115, clause (f): a foreign asset sold on 25 July converts at the
        SBI TTBR of 30 June (the last day of the PRECEDING month) - not 25 July's own rate.
        This is the exact worked example independently confirmed during research (a CA
        practitioner guide + the official incometaxindia.gov.in capital-gains clause text),
        used here as a concrete, externally-verifiable fact rather than re-deriving the
        "expected" value from the same function under test.
        """
        from itr_assist.services.sbi_rates import SBIRateService
        sbi = SBIRateService()
        rate_date, _ = sbi.get_rule_115_capital_gains_rate(date(2025, 7, 25))
        self.assertEqual(rate_date, date(2025, 6, 30))

    def test_sale_proceeds_use_rule_115_preceding_month_end_rate_not_sale_date_rate(self):
        """compute_table_a3 must convert sale proceeds at the preceding-month-end TTBR
        (Explanation to Rule 115 clause (f)), proven here by checking it against the SBI rate
        for 31-May-2025 specifically (the correct preceding-month-end for a 10-June-2025 sale),
        not against whatever get_rate() would return for the sale date itself."""
        from itr_assist.services.market_data import MarketDataService
        from itr_assist.services.sbi_rates import SBIRateService
        from itr_assist.services.valuation import ValuationEngine

        lot = self._make_lot("LOT-RATE", date(2024, 5, 15), 10.0)
        ledger = LotLedger([lot])
        sale = SaleEvent(sale_date=date(2025, 6, 10), symbol="ACME", quantity=10.0,
                          price_usd=120.0, gross_proceeds_usd=1200.0)
        enriched_sales = ledger.allocate_sales([sale])

        sbi = SBIRateService()
        mkt = MarketDataService(auto_download=False)
        mkt._price_cache["ACME"] = {
            date(2025, 6, 10): {"open": 100, "high": 100, "low": 100, "close": 100},
            date(2025, 12, 31): {"open": 100, "high": 100, "low": 100, "close": 100},
        }
        engine = ValuationEngine(ledger=ledger, sbi_service=sbi, market_service=mkt)

        a3 = engine.compute_table_a3(2025, cy_dividends=None, cy_sales=enriched_sales)
        lot_row = next(r for r in a3 if r.lot_id == "LOT-RATE")

        # The correct basis: SBI TTBR for 31-May-2025 (preceding month-end), looked up directly
        # rather than through the function under test.
        may_31_rate = sbi.get_rate(date(2025, 5, 31))
        jun_10_rate = sbi.get_rate(date(2025, 6, 10))
        self.assertNotEqual(may_31_rate, jun_10_rate)  # sanity: this test actually discriminates

        self.assertEqual(lot_row.gross_proceeds_inr, round(1200.0 * may_31_rate))
        self.assertNotEqual(lot_row.gross_proceeds_inr, round(1200.0 * jun_10_rate))
        self.assertEqual(lot_row.gross_proceeds_usd, 1200.0)


if __name__ == "__main__":
    unittest.main()
