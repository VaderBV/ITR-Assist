"""E*TRADE implementation of BaseStatementParser."""
from datetime import date, datetime
import re
from typing import Dict, List, Optional, Tuple
from pypdf import PdfReader

from itr_assist.models import DividendEvent, SaleEvent, StatementPeriodSummary
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
    ) -> Tuple[List[StatementPeriodSummary], List[DividendEvent], List[SaleEvent]]:
        """Extract all period summaries, dividend events, and sale events from E*TRADE statement files.

        calendar_year_hint (the user-selected CY, e.g. 2025 for FY 2025-26) is only a last-resort
        fallback for the rare page where the statement's own header text can't be matched by the
        year regex below. It never overrides a year actually read from the document.
        """
        summaries: List[StatementPeriodSummary] = []
        dividends: List[DividendEvent] = []
        sales: List[SaleEvent] = []

        seen_div_keys = set()
        seen_sale_keys = set()
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

            doc_period = None  # statement period from the most recent page header in this file
            for idx, page in enumerate(reader.pages):
                txt = page.extract_text() or ""

                # Detect statement year from header
                page_year_m = re.search(r'CLIENT STATEMENT\s+For the Period[^\n]*?(20\d\d)', txt)
                page_year = int(page_year_m.group(1)) if page_year_m else year_hint
                header_m = re.search(r'For the Period\s+([A-Za-z0-9\s,\-]+?)(?:\s+Page|\n|$)', txt)
                page_period = self._parse_period_dates(header_m.group(1).strip(), page_year) if header_m else None
                if page_period:
                    doc_period = page_period
                else:
                    page_period = doc_period

                # Extract period summaries from Account Summary pages
                if "Ending Total Value" in txt and "CLIENT STATEMENT" in txt:
                    pm = re.search(r'For the Period\s+([A-Za-z0-9\s,\-]+?)(?:\s+Page|\n|$)', txt)
                    beg_m = re.search(r'Beginning Total Value[^\$]+\$([\d,]+\.\d+)', txt)
                    end_m = re.search(r'Ending Total Value[^\$]+\$([\d,]+\.\d+)', txt)
                    cash_m = re.search(r'Cash\s+\$([\d,]+\.\d+)', txt)
                    eq_m = re.search(r'Equities\s+([\d,]+\.\d+)', txt)
                    shs_m = re.search(r'([\d,]+\.\d+)\s+shs from Stock Plan', txt)

                    period_dates = self._parse_period_dates(pm.group(1).strip(), page_year) if pm else None
                    if period_dates:
                        period_label = pm.group(1).strip()
                        if period_label not in seen_period_keys:
                            seen_period_keys.add(period_label)
                            start_d, end_d = period_dates

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

                # Extract Dividend line items. The $ sign on the Credits amount is present on
                # some statements (monthly) and absent on others (quarterly) - confirmed on two
                # real statements for the same account - so it must be optional here.
                for m in re.finditer(r'(\d{1,2}/\d{1,2})\s+Qualified Dividend\s+([A-Z\s]+?)\s+\$?([\d,]+\.\d+)', txt):
                    date_part, sym, amt_str = m.groups()
                    amt = float(amt_str.replace(',', ''))

                    tax_m = re.search(
                        re.escape(date_part) + r'\s+Tax Withholding[^\(\n]*\(\$?([\d,]+\.\d+)\)',
                        txt,
                    )
                    tax_amt = float(tax_m.group(1).replace(',', '')) if tax_m else 0.0

                    m_num, d_num = map(int, date_part.split('/'))
                    pay_date = date(self._infer_year(m_num, d_num, page_period, page_year), m_num, d_num)

                    div_key = (pay_date, sym.strip(), amt)
                    if div_key not in seen_div_keys:
                        seen_div_keys.add(div_key)
                        div_symbol = symbol_hint if symbol_hint else sym.strip()
                        dividends.append(DividendEvent(
                            pay_date=pay_date,
                            symbol=div_symbol,
                            gross_amount_usd=amt,
                            tax_withheld_usd=tax_amt,
                            tax_deduction_date=pay_date if tax_m is not None else None,
                            tax_line_found=tax_m is not None,
                        ))

                # Extract Sale/Sell transaction line items from the "CASH FLOW ACTIVITY BY DATE"
                # table. Verified against two real Morgan Stanley/E*TRADE statements (not a
                # guess): a sold row's raw extracted text looks like
                #   "10/27 10/28 Sold QUALCOMM INC ACTED AS AGENT\nUNSOLICITED TRADE\n9.000 $190.0000 $1,705.05"
                # i.e. activity date, settlement date, "Sold", a description/comments block that
                # can wrap onto its own line(s), then quantity/price/credits on a later line. The
                # description text is in the same all-caps style as the comments that can follow
                # it (e.g. "ACTED AS AGENT"), so it is NOT reliably extractable by itself - the
                # symbol comes from symbol_hint instead, same fallback already used for dividends.
                # The statement's "Credits" column is the NET amount (after commission/fees, e.g.
                # $1,705.05 for a $1,710.00 gross sale) - confirmed against the matching Trade
                # Confirmation document, which showed Principal (gross) separately from Net
                # Amount. Gross proceeds for Schedule FA/capital-gains purposes must be the GROSS
                # sale consideration, so it's computed here as quantity * price, not read from
                # the Credits column.
                # The quantity/price/credits triple is required to start its own line (anchored
                # on a preceding newline) rather than matching the first 3 decimal-looking
                # numbers found anywhere in the next 200 chars - without this, a description/
                # comments block containing an unrelated dollar figure or CUSIP-like number
                # could bind to the wrong triple and still pass the sanity check below (e.g. if
                # it happens to look like a plausible credits-vs-gross ratio). Both verified real
                # examples have the triple on its own line after the description/comments.
                for m in re.finditer(
                    r'(\d{1,2}/\d{1,2})\s+\d{1,2}/\d{1,2}\s+Sold\b[\s\S]{0,200}?\n\s*([\d,]+\.\d+)\s+\$?([\d,]+\.\d+)\s+\$?([\d,]+\.\d+)',
                    txt,
                ):
                    date_part, qty_str, price_str, credits_str = m.groups()
                    qty = float(qty_str.replace(',', ''))
                    price = float(price_str.replace(',', ''))
                    credits_net = float(credits_str.replace(',', ''))
                    gross_proceeds = round(qty * price, 2)
                    # Sanity check: the net credit should be close to (but not exceed) the gross
                    # value - if it's wildly different, this likely matched the wrong numbers
                    # (e.g. a different table entirely), so skip it rather than record garbage.
                    if credits_net <= 0 or credits_net > gross_proceeds * 1.05:
                        continue

                    m_num, d_num = map(int, date_part.split('/'))
                    sale_date = date(self._infer_year(m_num, d_num, page_period, page_year), m_num, d_num)

                    sale_symbol = symbol_hint if symbol_hint else "STOCK"
                    sale_key = (sale_date, sale_symbol, qty, gross_proceeds)
                    if sale_key not in seen_sale_keys:
                        seen_sale_keys.add(sale_key)
                        sales.append(SaleEvent(
                            sale_date=sale_date,
                            symbol=sale_symbol,
                            quantity=qty,
                            price_usd=price,
                            gross_proceeds_usd=gross_proceeds,
                            net_credit_usd=credits_net,
                        ))

        summaries.sort(key=lambda x: x.start_date)
        dividends.sort(key=lambda x: x.pay_date)
        sales.sort(key=lambda x: x.sale_date)
        return summaries, dividends, sales

    def _parse_period_dates(self, period_str: str, default_year: int) -> Optional[Tuple[date, date]]:
        """Parse 'December 1-31, 2025' or 'January 1- February 28, 2025'. Returns None for an
        unrecognised label - never a guessed range: a fabricated Jan-Dec period would mask
        statement gaps and could be mistaken for the Dec-31 closing statement."""
        years = re.findall(r'(20\d\d)', period_str)
        year = int(years[-1]) if years else default_year

        multi_m = re.search(r'([A-Za-z]+)\s+(\d{1,2})\s*-\s*([A-Za-z]+)\s+(\d{1,2})', period_str)
        if multi_m:
            m1_name, d1, m2_name, d2 = multi_m.groups()
            m1, m2 = MONTH_MAP.get(m1_name.lower()), MONTH_MAP.get(m2_name.lower())
            if m1 and m2:
                start_year = year - 1 if m1 > m2 else year  # e.g. "November 1- January 31, 2026"
                return date(start_year, m1, int(d1)), date(year, m2, int(d2))

        single_m = re.search(r'([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2})', period_str)
        if single_m:
            m_name, d1, d2 = single_m.groups()
            m = MONTH_MAP.get(m_name.lower())
            if m:
                return date(year, m, int(d1)), date(year, m, int(d2))

        return None

    @staticmethod
    def _infer_year(month: int, day: int, period: Optional[Tuple[date, date]], fallback: int) -> int:
        """Year of an MM/DD activity date: the candidate year that puts it inside (else nearest
        to) the statement's own printed period. A 06/25 dividend on a June-2026 statement is
        2026 regardless of which filing year the user selected."""
        if period is None:
            return fallback
        start, end = period
        best = None
        for y in sorted({start.year - 1, start.year, end.year, end.year + 1}):
            try:
                d = date(y, month, day)
            except ValueError:
                continue
            if start <= d <= end:
                return y
            gap = (start - d).days if d < start else (d - end).days
            if best is None or gap < best[0]:
                best = (gap, y)
        return best[1] if best else fallback
