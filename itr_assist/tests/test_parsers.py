"""Unit tests for modular document parsers, adapters, and factory without external file fixtures."""
from datetime import date
from unittest.mock import MagicMock, patch
import pandas as pd
import unittest

from itr_assist.models import LotStatus, PlanType
from itr_assist.parsers.common import clean_currency, parse_date
from itr_assist.parsers.etrade import (
    ETradeAdapter,
    ETradeBenefitHistoryParser,
    ETradeHoldingsParser,
    ETradeStatementParser,
    ETradeTaxDocumentParser,
)
from itr_assist.parsers.factory import BrokerParserFactory
from itr_assist.parsers.fidelity import FidelityAdapter


class TestParserHelpers(unittest.TestCase):
    """Test date and currency parsing utility functions."""

    def test_parse_date_formats(self):
        self.assertEqual(parse_date("15-AUG-2024"), date(2024, 8, 15))
        self.assertEqual(parse_date("08/15/2024"), date(2024, 8, 15))
        self.assertEqual(parse_date("2024-08-15"), date(2024, 8, 15))
        self.assertIsNone(parse_date(None))
        self.assertIsNone(parse_date(""))

    def test_clean_currency(self):
        self.assertEqual(clean_currency("$1,234.56"), 1234.56)
        self.assertEqual(clean_currency("57.86"), 57.86)
        self.assertEqual(clean_currency(100), 100.0)
        self.assertEqual(clean_currency(None), 0.0)


class TestBrokerParserFactory(unittest.TestCase):
    """Unit tests for BrokerParserFactory and auto-detection."""

    def test_factory_get_etrade(self):
        adapter = BrokerParserFactory.get_adapter("etrade")
        self.assertIsInstance(adapter, ETradeAdapter)
        self.assertEqual(adapter.broker_name, "E*TRADE")

    def test_factory_get_fidelity(self):
        adapter = BrokerParserFactory.get_adapter("fidelity")
        self.assertIsInstance(adapter, FidelityAdapter)
        self.assertEqual(adapter.broker_name, "Fidelity")

    @patch("itr_assist.parsers.factory.PdfReader")
    def test_factory_auto_detect_etrade(self, mock_pdf_reader):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "E*TRADE FROM MORGAN STANLEY CLIENT STATEMENT"
        mock_pdf_reader.return_value.pages = [mock_page]

        adapter = BrokerParserFactory.auto_detect("statements.pdf")
        self.assertIsInstance(adapter, ETradeAdapter)

    @patch("itr_assist.parsers.factory.PdfReader")
    def test_factory_auto_detect_fidelity(self, mock_pdf_reader):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "FIDELITY INVESTMENTS ACCOUNT STATEMENT"
        mock_pdf_reader.return_value.pages = [mock_page]

        adapter = BrokerParserFactory.auto_detect("fidelity_stmt.pdf")
        self.assertIsInstance(adapter, FidelityAdapter)

    def test_factory_unsupported_broker(self):
        with self.assertRaises(ValueError):
            BrokerParserFactory.get_adapter("unsupported_broker_xyz")

    def test_fidelity_adapter_not_implemented(self):
        fidelity = FidelityAdapter()
        with self.assertRaises(NotImplementedError):
            fidelity.parse_benefit_history("dummy.xlsx")


class TestDocumentParsers(unittest.TestCase):
    """Unit tests for document parsing logic using synthetic text and data frames."""

    @patch("itr_assist.parsers.etrade.tax_documents.PdfReader")
    def test_parse_form_1042s_pdf(self, mock_pdf_reader):
        """Test extraction of calendar year, gross income, tax withheld, and recipient info."""
        mock_text = (
            "2025 Form 1042-S Foreign Person's U.S. Source Income\n"
            "06 Chap. 3 $100.00 00 25.00% 00 0.00% $25.00\n"
            "Recipient's Name: JOHN DOE\n"
            "TIN: ABCDE1234F\n"
            "Account: 889-000000\n"
            "Morgan Stanley Smith Barney LLC\n"
        )
        mock_page = MagicMock()
        mock_page.extract_text.return_value = mock_text
        mock_pdf_reader.return_value.pages = [mock_page]

        parser = ETradeTaxDocumentParser()
        tax_data = parser.parse("dummy_1042s.pdf")

        self.assertIsNotNone(tax_data)
        self.assertEqual(tax_data.calendar_year, 2025)
        self.assertEqual(tax_data.gross_dividend_usd, 100.0)
        self.assertEqual(tax_data.tax_withheld_usd, 25.0)
        self.assertEqual(tax_data.withholding_rate, 0.25)
        self.assertEqual(tax_data.recipient_tin, "ABCDE1234F")
        self.assertEqual(tax_data.account_number, "889-000000")
        self.assertEqual(tax_data.withholding_agent, "Morgan Stanley Smith Barney LLC")

    @patch("itr_assist.parsers.etrade.statements.PdfReader")
    def test_parse_statements_pdf(self, mock_pdf_reader):
        """Test extraction of monthly period summaries and dividend activity."""
        page1_text = (
            "CLIENT STATEMENT For the Period December 1-31, 2025 Page 1\n"
            "Beginning Total Value $2,400.00\n"
            "Ending Total Value $2,800.00\n"
            "Cash $100.00\n"
            "Equities 2,700.00\n"
            "15.000 shs from Stock Plan\n"
        )
        page2_text = (
            "Activity Summary\n"
            "12/09 Qualified Dividend ACME CORPORATION $25.00\n"
            "12/09 Tax Withholding ($6.25)\n"
        )
        p1 = MagicMock()
        p1.extract_text.return_value = page1_text
        p2 = MagicMock()
        p2.extract_text.return_value = page2_text
        mock_pdf_reader.return_value.pages = [p1, p2]

        parser = ETradeStatementParser()
        # page2_text (the dividend activity page) has no "CLIENT STATEMENT ... For the Period"
        # header of its own, so the parser falls back to calendar_year_hint - exactly what this
        # fixture's year (2025) is for. Without a hint, it would fall back to today's year,
        # which is why this must be passed explicitly rather than relying on an implicit default.
        summaries, dividends, sales = parser.parse(["dummy_stmt.pdf"], calendar_year_hint=2025)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].beginning_value_usd, 2400.0)
        self.assertEqual(summaries[0].ending_value_usd, 2800.0)
        self.assertEqual(summaries[0].cash_balance_usd, 100.0)
        self.assertEqual(summaries[0].equities_value_usd, 2700.0)
        self.assertEqual(summaries[0].shares_held, 15.0)

        self.assertEqual(len(dividends), 1)
        self.assertEqual(dividends[0].pay_date, date(2025, 12, 9))
        self.assertEqual(dividends[0].gross_amount_usd, 25.0)
        self.assertEqual(dividends[0].tax_withheld_usd, 6.25)
        self.assertEqual(dividends[0].symbol, "ACME CORPORATION")

    @patch("itr_assist.parsers.etrade.statements.PdfReader")
    def test_parse_statements_pdf_sale_transaction(self, mock_pdf_reader):
        """Test extraction of a sell transaction line.

        IMPORTANT CAVEAT: the sell-line regex in statements.py is a best-effort pattern
        modelled on the already-proven dividend-line pattern - it has NOT been validated
        against a real E*TRADE statement's actual "Account Activity" sell-line wording
        (no real sample was available to build against). This test only proves the parser
        correctly extracts data from the wording it currently expects; it does NOT prove that
        wording matches a real statement. If real sales aren't picked up, start by comparing
        the actual statement text against the pattern in statements.py.
        """
        page_text = (
            "CLIENT STATEMENT For the Period June 1-30, 2025 Page 1\n"
            "Activity Summary\n"
            "06/10 Sold 4.000 shs ACME CORPORATION @ $120.00 $480.00\n"
        )
        p1 = MagicMock()
        p1.extract_text.return_value = page_text
        mock_pdf_reader.return_value.pages = [p1]

        parser = ETradeStatementParser()
        _, _, sales = parser.parse(["dummy_stmt.pdf"], calendar_year_hint=2025)

        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0].sale_date, date(2025, 6, 10))
        self.assertEqual(sales[0].quantity, 4.0)
        self.assertEqual(sales[0].price_usd, 120.0)
        self.assertEqual(sales[0].gross_proceeds_usd, 480.0)
        self.assertEqual(sales[0].symbol, "ACME CORPORATION")

    @patch("pandas.read_excel")
    def test_parse_benefit_history_excel(self, mock_read_excel):
        """Test parsing of ESPP purchase/sell and RSU vesting records."""
        espp_df = pd.DataFrame([
            {
                "Record Type": "Purchase",
                "Symbol": "ACME",
                "Purchase Date": "2023-12-01",
                "Purchased Qty.": 6.0,
                "Net Shares": 6.0,
                "Purchase Price": "$59.50",
                "Purchase Date FMV": "$70.00",
            },
            {
                "Record Type": "Event",
                "Event Type": "Sell",
                "Date": "2025-06-15",
                "Qty": 6.0,
            },
            {
                "Record Type": "Purchase",
                "Symbol": "ACME",
                "Purchase Date": "2024-06-03",
                "Purchased Qty.": 5.0,
                "Net Shares": 5.0,
                "Purchase Price": "$68.00",
                "Purchase Date FMV": "$80.00",
            },
        ])
        rsu_df = pd.DataFrame([
            {
                "Record Type": "Grant",
                "Symbol": "ACME",
            },
            {
                "Record Type": "Vest Schedule",
                "Grant Number": "G100",
                "Vest Date": "2024-05-15",
                "Vested Qty..1": 15.0,
                "Sellable Qty..1": 10.0,
                "Total Taxes Paid": "$500.00",
            },
            {
                "Record Type": "Tax Withholding",
                "Taxable Gain": "$100.00",
            },
        ])

        def mock_read_sheet(path, sheet_name=None, **kwargs):
            if sheet_name == "ESPP":
                return espp_df
            elif sheet_name == "Restricted Stock":
                return rsu_df
            return pd.DataFrame()

        mock_read_excel.side_effect = mock_read_sheet

        parser = ETradeBenefitHistoryParser()
        lots = parser.parse("dummy_bh.xlsx")

        self.assertEqual(len(lots), 3)
        sold_lot = next((l for l in lots if l.is_sold_lot), None)
        self.assertIsNotNone(sold_lot)
        self.assertEqual(sold_lot.net_shares, 6.0)
        self.assertEqual(sold_lot.remaining_shares, 0.0)

        rsu_lot = next((l for l in lots if l.plan_type == PlanType.RSU), None)
        self.assertIsNotNone(rsu_lot)
        self.assertEqual(rsu_lot.net_shares, 10.0)
        self.assertEqual(rsu_lot.grant_number, "G100")

    @patch("pandas.read_excel")
    def test_parse_holdings_excel(self, mock_read_excel):
        """Test parsing of Sellable snapshot holdings sheet."""
        holdings_df = pd.DataFrame([
            {
                "Record Type": "Holding",
                "Symbol": "ACME",
                "Plan Type": "Restricted Stock",
                "Vest Date": "2024-05-15",
                "Sellable Qty.": 10.0,
                "Est. Cost Basis (per share):": "$100.00",
                "Grant Number": "G100",
            },
            {
                "Record Type": "Holding",
                "Symbol": "ACME",
                "Plan Type": "Employee Stock Purchase Plan",
                "Date Acquired": "2024-06-03",
                "Sellable Qty.": 5.0,
                "Est. Cost Basis (per share):": "$80.00",
            },
        ])
        mock_read_excel.return_value = holdings_df

        parser = ETradeHoldingsParser()
        holdings = parser.parse("dummy_holdings.xlsx")

        self.assertEqual(len(holdings), 2)
        self.assertEqual(sum(h.remaining_shares for h in holdings), 15.0)


if __name__ == "__main__":
    unittest.main()
