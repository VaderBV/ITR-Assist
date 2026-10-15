"""E*TRADE implementation of BaseStatementParser."""
from datetime import date, datetime
import re
from typing import Dict, List, Optional, Tuple
from pypdf import PdfReader

from itr_assist.models import DividendEvent, StatementPeriodSummary
from itr_assist.parsers.base import BaseStatementParser


MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}


class ETradeStatementParser(BaseStatementParser):
    """Parses monthly/multi-month E*TRADE client statement PDFs."""

    def parse(
        self,
        file_paths: List[str],
        symbol_hint: Optional[str] = None,
        calendar_year_hint: Optional[int] = None,
    ) -> Tuple[List[StatementPeriodSummary], List[DividendEvent]]:
        """Extract all period summaries and dividend events from E*TRADE statement files.

        calendar_year_hint (the user-selected CY, e.g. 2025 for FY 2025-26) is only a last-resort
        fallback for the rare page where the statement's own header text can't be matched by the
        year regex below. It never overrides a year actually read from the document.
        """
        summaries: List[StatementPeriodSummary] = []
        dividends: List[DividendEvent] = []

        seen_div_keys = set()
        seen_period_keys = set()
        fallback_year = calendar_year_hint if calendar_year_hint is not None else date.today().year

        for fpath in file_paths:
            reader = PdfReader(fpath)

            # Filename is only a weak secondary hint; the per-page CLIENT STATEMENT header
            # (matched below as `page_year`) takes precedence whenever it's present.
            year_hint = fallback_year
            next_year_str = str(fallback_year + 1)
            if next_year_str in fpath or "jan-march" in fpath.lower():
                year_hint = fallback_year + 1

            for idx, page in enumerate(reader.pages):
                txt = page.extract_text() or ""

                # Detect statement year from header
                page_year_m = re.search(r'CLIENT STATEMENT\s+For the Period[^\n]*?(20\d\d)', txt)
                page_year = int(page_year_m.group(1)) if page_year_m else year_hint

                # Extract period summaries from Account Summary pages
                if "Ending Total Value" in txt and "CLIENT STATEMENT" in txt:
                    pm = re.search(r'For the Period\s+([A-Za-z0-9\s,\-]+?)(?:\s+Page|\n|$)', txt)
                    beg_m = re.search(r'Beginning Total Value[^\$]+\$([\d,]+\.\d+)', txt)
                    end_m = re.search(r'Ending Total Value[^\$]+\$([\d,]+\.\d+)', txt)
                    cash_m = re.search(r'Cash\s+\$([\d,]+\.\d+)', txt)
                    eq_m = re.search(r'Equities\s+([\d,]+\.\d+)', txt)
                    shs_m = re.search(r'([\d,]+\.\d+)\s+shs from Stock Plan', txt)

                    if pm:
                        period_label = pm.group(1).strip()
                        if period_label not in seen_period_keys:
                            seen_period_keys.add(period_label)
                            start_d, end_d = self._parse_period_dates(period_label, page_year)

                            amounts = re.findall(r'\$([\d,]+\.\d+)', txt)
                            if len(amounts) >= 2:
                                beg_val = float(amounts[0].replace(',', ''))
                                end_val = float(amounts[1].replace(',', ''))
                            else:
                                beg_val = float(beg_m.group(1).replace(',', '')) if beg_m else 0.0
                                end_val = float(end_m.group(1).replace(',', '')) if end_m else 0.0

                            cash_val = float(cash_m.group(1).replace(',', '')) if cash_m else 0.0
                            eq_val = float(eq_m.group(1).replace(',', '')) if eq_m else end_val - cash_val
                            shs_held = float(shs_m.group(1).replace(',', '')) if shs_m else 0.0

                            summaries.append(StatementPeriodSummary(
                                period_label=period_label,
                                start_date=start_d,
                                end_date=end_d,
                                beginning_value_usd=beg_val,
                                ending_value_usd=end_val,
                                cash_balance_usd=cash_val,
                                equities_value_usd=eq_val,
                                shares_held=shs_held
                            ))

                # Extract Dividend line items
                for m in re.finditer(r'(\d{1,2}/\d{1,2})\s+Qualified Dividend\s+([A-Z\s]+?)\s+\$([\d,]+\.\d+)', txt):
                    date_part, sym, amt_str = m.groups()
                    amt = float(amt_str.replace(',', ''))

                    tax_m = re.search(r'' + re.escape(date_part) + r'\s+Tax Withholding[^\(]+\(([\d,]+\.\d+)\)', txt)
                    tax_amt = float(tax_m.group(1).replace(',', '')) if tax_m else round(amt * 0.25, 2)

                    m_num, d_num = map(int, date_part.split('/'))
                    div_year = page_year
                    # A page from the Q4/FY-end ("Jan-March") statement is labeled with the
                    # later calendar year, but can carry a trailing Account Activity section for
                    # a transaction dated after March, which actually belongs to the prior CY.
                    if page_year == fallback_year + 1 and m_num > 3:
                        div_year = fallback_year
                    pay_date = date(div_year, m_num, d_num)

                    div_key = (pay_date, sym.strip(), amt)
                    if div_key not in seen_div_keys:
                        seen_div_keys.add(div_key)
                        div_symbol = symbol_hint if symbol_hint else sym.strip()
                        dividends.append(DividendEvent(
                            pay_date=pay_date,
                            symbol=div_symbol,
                            gross_amount_usd=amt,
                            tax_withheld_usd=tax_amt
                        ))

        summaries.sort(key=lambda x: x.start_date)
        dividends.sort(key=lambda x: x.pay_date)
        return summaries, dividends

    def _parse_period_dates(self, period_str: str, default_year: int) -> Tuple[date, date]:
        """Parse period string like 'December 1-31, 2025' or 'January 1- February 28, 2025'."""
        year_m = re.search(r'(20\d\d)', period_str)
        year = int(year_m.group(1)) if year_m else default_year

        multi_m = re.search(r'([A-Za-z]+)\s+(\d{1,2})\s*-\s*([A-Za-z]+)\s+(\d{1,2})', period_str)
        if multi_m:
            m1_name, d1, m2_name, d2 = multi_m.groups()
            m1 = MONTH_MAP.get(m1_name.lower(), 1)
            m2 = MONTH_MAP.get(m2_name.lower(), 1)
            return date(year, m1, int(d1)), date(year, m2, int(d2))

        single_m = re.search(r'([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2})', period_str)
        if single_m:
            m_name, d1, d2 = single_m.groups()
            m = MONTH_MAP.get(m_name.lower(), 1)
            return date(year, m, int(d1)), date(year, m, int(d2))

        return date(year, 1, 1), date(year, 12, 31)
