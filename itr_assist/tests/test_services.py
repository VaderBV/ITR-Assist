"""Unit tests for SBIRateService, MarketDataService, and ValuationEngine without external file fixtures."""
from datetime import date, timedelta
import unittest

from itr_assist.models import (
    DividendEvent,
    LotStatus,
    PlanType,
    ShareLot,
    StatementPeriodSummary,
)
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import ValuationEngine


class TestSBIRateService(unittest.TestCase):
    """Unit tests for SBIRateService and RBI/Rule 115 rollback rules."""

    @classmethod
    def setUpClass(cls):
        cls.sbi = SBIRateService()

    def test_rates_loaded(self):
        self.assertGreater(len(self.sbi._rates), 500)

    def test_specific_date_rate(self):
        rate = self.sbi.get_rate(date(2025, 12, 31))
        self.assertEqual(rate, 89.47)

    def test_weekend_rollback(self):
        # 2025-06-01 was a Sunday -> should roll back to Saturday 2025-05-31
        rate_sun = self.sbi.get_rate(date(2025, 6, 1))
        rate_sat = self.sbi.get_rate(date(2025, 5, 31))
        self.assertEqual(rate_sun, rate_sat)

    def test_rule_115_dividend_rate(self):
        # Dividend on 2025-06-05 -> rate should be for last day of preceding month (2025-05-31)
        date_used, rule115_rate = self.sbi.get_rule_115_dividend_rate(date(2025, 6, 5))
        self.assertEqual(date_used, date(2025, 5, 31))
        self.assertEqual(rule115_rate, self.sbi.get_rate(date(2025, 5, 31)))

    def test_rule_128_rate(self):
        # Rule 128(5)(ii): tax deducted 2025-06-05 -> rate should be for last day of the
        # PRECEDING month (2025-05-31), not the deduction date itself. Verified against the
        # primary rule text: "...telegraphic transfer buying rate on the last day of the month
        # immediately preceding the month in which such tax has been paid or deducted."
        date_used, rule128_rate = self.sbi.get_rule_128_rate(date(2025, 6, 5))
        self.assertEqual(date_used, date(2025, 5, 31))
        self.assertEqual(rule128_rate, self.sbi.get_rate(date(2025, 5, 31)))

    def test_rule_128_rate_january_rolls_back_to_prior_year(self):
        # Tax deducted in January must roll back to 31 December of the PRIOR year.
        date_used, _ = self.sbi.get_rule_128_rate(date(2025, 1, 10))
        self.assertEqual(date_used, date(2024, 12, 31))


class TestMarketDataService(unittest.TestCase):
    """Unit tests for MarketDataService price cache and step-back logic."""

    @classmethod
    def setUpClass(cls):
        cls.mkt = MarketDataService(auto_download=False)
        cls.mkt._price_cache["TEST"] = {
            date(2025, 12, 31): {"open": 99.0, "high": 102.0, "low": 98.0, "close": 100.0},
            date(2025, 12, 30): {"open": 98.0, "high": 101.0, "low": 97.0, "close": 99.0},
        }

    def test_get_prices_exact_date(self):
        prices = self.mkt.get_prices(date(2025, 12, 31), "TEST")
        self.assertEqual(prices["close"], 100.0)

    def test_get_prices_stepback_weekend(self):
        # Step back to the most recent trading day
        prices = self.mkt.get_prices(date(2026, 1, 1), "TEST")
        self.assertEqual(prices["close"], 100.0)

    def test_cache_path_format(self):
        path = self.mkt._get_cache_path("TEST")
        self.assertTrue(path.endswith("TEST_prices.json"))


class TestValuationEngine(unittest.TestCase):
    """Unit tests for ValuationEngine using in-memory synthetic models."""

    @classmethod
    def setUpClass(cls):
        cls.sbi = SBIRateService()
        cls.mkt = MarketDataService(auto_download=False)

        # Populate in-memory daily pricing for ACME across 2024-2026
        acme_prices = {}
        cur = date(2023, 1, 1)
        end_dt = date(2026, 12, 31)
        while cur <= end_dt:
            if cur.weekday() < 5:
                acme_prices[cur] = {"open": 99.0, "high": 102.0, "low": 98.0, "close": 100.0}
            cur += timedelta(days=1)
        cls.mkt._price_cache["ACME"] = acme_prices

        # Synthetic Ledger with 2 active lots and 1 sold lot
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

        # Synthetic quarterly period summaries
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

        # Synthetic dividends
        cls.dividends = [
            DividendEvent(pay_date=date(2025, 3, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 6, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 9, 5), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
            DividendEvent(pay_date=date(2025, 12, 9), symbol="ACME", gross_amount_usd=25.0, tax_withheld_usd=6.25),
        ]

        cls.engine = ValuationEngine(
            ledger=cls.ledger,
            sbi_service=cls.sbi,
            market_service=cls.mkt,
            broker_name="Morgan Stanley Smith Barney LLC (E*TRADE)",
            account_number="ACC-1234567"
        )

    def test_schedule_fa_table_a3_computation(self):
        """Verify Table A3 computes for all 3 synthetic lots with non-zero peak and initial values."""
        results = self.engine.compute_table_a3(calendar_year=2025, cy_dividends=self.dividends)
        self.assertEqual(len(results), 3)

        for res in results:
            self.assertGreater(res.initial_value_inr, 0)
            self.assertGreater(res.peak_balance_inr, 0)
            self.assertGreater(res.peak_price_usd, 0.0)
            if res.is_sold_lot:
                self.assertEqual(res.gross_shares, 6.0)

    def test_schedule_fa_table_a2_computation(self):
        """Verify Table A2 custodial account closing and peak balances."""
        dec_summary = next(s for s in self.summaries if s.end_date == date(2025, 12, 31))
        res = self.engine.compute_table_a2(
            calendar_year=2025,
            dec_summary=dec_summary,
            cy_dividends=self.dividends
        )
        self.assertEqual(res.closing_balance_usd, 2800.0)
        self.assertGreater(res.closing_balance_inr, 200000)
        self.assertGreaterEqual(res.peak_balance_inr, res.closing_balance_inr)
        self.assertEqual(res.gross_amounts[0].nature, "D")
        self.assertGreater(res.gross_amounts[0].amount_inr, 5000)

    def test_schedule_os_and_ftc_computation(self):
        """Verify Schedule OS advance tax buckets and Form 67 FTC claim."""
        fy_divs = [d for d in self.dividends if date(2025, 4, 1) <= d.pay_date <= date(2026, 3, 31)]
        os_res, ftc_res = self.engine.compute_schedule_os_and_ftc(fy_divs)

        self.assertGreater(len(os_res.items), 0)
        self.assertGreater(os_res.total_dividend_inr, 0)

        bucket_sum = (
            os_res.upto_15_jun_inr +
            os_res.upto_15_sep_inr +
            os_res.upto_15_dec_inr +
            os_res.upto_15_mar_inr +
            os_res.upto_31_mar_inr
        )
        self.assertEqual(bucket_sum, os_res.total_dividend_inr)

        self.assertGreater(ftc_res.foreign_tax_paid_inr, 0)
        self.assertEqual(ftc_res.tax_relief_claimed_inr, ftc_res.foreign_tax_paid_inr)
        self.assertEqual(ftc_res.dtaa_article, "Article 10")


if __name__ == "__main__":
    unittest.main()
