"""Valuation Engine for Schedule FA, Schedule OS, Schedule FSI, Schedule TR, and Form 67."""
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from itr_assist.models import DividendEvent, SaleEvent, ShareLot, StatementPeriodSummary
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.sbi_rates import SBIRateService


@dataclass
class A2GrossAmount:
    """One Table A2 "gross amount paid/credited" line. The CBDT schema allows a single
    NatureOfAmount per DtlsForeignCustodialAcc row, so an account credited with dividends,
    interest and sale proceeds is reported as one row per nature (peak/closing repeated)."""
    nature: str        # CBDT NatureOfAmount: "D" dividend, "I" interest, "S" sale proceeds, "O" other, "N" none
    amount_usd: float
    amount_inr: int
    rate_inr: float
    rate_date: date
    source: str


@dataclass
class ScheduleFATableA2Result:
    country_name: str
    country_code: str
    financial_inst_name: str
    financial_inst_address: str
    zip_code: str
    account_number: str
    status: str
    account_open_date: str
    peak_balance_usd: float
    peak_balance_inr: int
    peak_date: date
    peak_rate_inr: float
    closing_balance_usd: float
    closing_balance_inr: int
    closing_date: date
    closing_rate_inr: float
    gross_amounts: List[A2GrossAmount] = field(default_factory=list)
    peak_degraded: bool = False   # True when daily prices were unavailable and the peak is a floor estimate
    source_peak: str = "Broker Statement (Peak Account Value) & SBI TTBR Sheet"
    source_closing: str = "Broker Statement (Ending Net Portfolio Value) & SBI TTBR Sheet"


@dataclass
class ScheduleFATableA3LotResult:
    lot_id: str
    country_name: str
    country_code: str
    name_of_entity: str
    address_of_entity: str
    zip_code: str
    nature_of_entity: str
    acquisition_date: date
    gross_shares: float
    net_shares: float
    vest_fmv_usd: float
    acq_sbi_rate_inr: float
    initial_value_inr: int
    peak_balance_inr: int
    peak_date: date
    peak_price_usd: float
    peak_rate_inr: float
    closing_balance_inr: int
    closing_date: date
    closing_price_usd: float
    closing_rate_inr: float
    gross_dividends_usd: float
    gross_dividends_inr: int
    gross_proceeds_inr: int
    is_sold_lot: bool = False
    disposal_date: Optional[date] = None
    initial_cost_usd: float = 0.0
    peak_balance_usd: float = 0.0
    closing_balance_usd: float = 0.0
    source_acquisition: str = "Benefit History Spreadsheet"
    source_peak: str = "Yahoo Finance Daily Stock Price & SBI TTBR Card"
    source_closing: str = "Yahoo Finance Stock Dec 31 Close & SBI TTBR Card"
    source_dividends: str = "Client Statements Account Activity"
    gross_proceeds_usd: float = 0.0
    source_proceeds: str = ""
    # Schedule FA income columns (11: dividends, 12: proceeds) convert at the TTBR of the
    # calendar year's closing date (31-Dec), per the CBDT Schedule FA guide.
    income_rate_inr: float = 0.0
    income_rate_date: Optional[date] = None
    peak_degraded: bool = False     # peak not from daily prices in the holding window
    closing_degraded: bool = False  # closing price not from 31-Dec market/statement data
    fmv_source: str = ""            # how vest_fmv_usd was established (vest-day close vs derived)


@dataclass
class DividendTaxResult:
    pay_date: date
    symbol: str
    gross_usd: float
    tax_usd: float
    tax_deduction_date: date
    preceding_month_end: date
    rule_115_rate: float
    gross_inr: int
    rule_128_rate: float
    tax_inr: int
    advance_tax_bucket: str
    source_document: str = "ClientStatements_*.pdf & Form 1042-S"


@dataclass
class ScheduleOSResult:
    total_dividend_inr: int
    upto_15_jun_inr: int
    upto_15_sep_inr: int
    upto_15_dec_inr: int
    upto_15_mar_inr: int
    upto_31_mar_inr: int
    items: List[DividendTaxResult] = field(default_factory=list)


@dataclass
class FTCResult:
    country_name: str
    country_code: str
    head_of_income: str
    source_of_income: str
    dtaa_article: str
    gross_foreign_income_inr: int
    foreign_tax_paid_inr: int
    estimated_indian_tax_inr: int
    tax_relief_claimed_inr: int
    gross_foreign_income_usd: float = 0.0
    foreign_tax_paid_usd: float = 0.0
    tax_relief_claimed_usd: float = 0.0
    # Inputs/caps behind the relief: Rule 128(5)(i) limits credit to the lower of the Indian
    # tax payable on this income (at indian_tax_rate) and the foreign tax paid, and India-US
    # DTAA Art. 10(2)(b) caps the creditable US tax at dtaa_rate_cap x gross dividend.
    indian_tax_rate: float = 0.312
    dtaa_rate_cap: float = 0.25
    source_document: str = "IRS Form 1042-S (Box 2 & Box 7a) & E*TRADE Statements"


class ValuationEngine:
    """Computes all tax and valuation figures required for ITR-2 foreign asset schedules."""

    def __init__(
        self,
        ledger: LotLedger,
        sbi_service: SBIRateService,
        market_service: MarketDataService,
        employer_entity_name: str = "Foreign Employer Entity",
        employer_entity_address: str = "Corporate Headquarters Address",
        employer_zip: str = "00000",
        broker_name: str = "Foreign Custodial Broker",
        broker_address: str = "Broker Operating Address",
        broker_zip: str = "00000",
        account_number: str = "",
        account_open_date: str = "2021-01-01"
    ):
        self.ledger = ledger
        self.sbi = sbi_service
        self.mkt = market_service
        self.employer_entity_name = employer_entity_name
        self.employer_entity_address = employer_entity_address
        self.employer_zip = employer_zip
        self.broker_name = broker_name
        self.broker_address = broker_address
        self.broker_zip = broker_zip
        self.account_number = account_number
        self.account_open_date = account_open_date

    def compute_table_a3(
        self,
        calendar_year: int,
        cy_dividends: Optional[List[DividendEvent]] = None,
        cy_sales: Optional[List[SaleEvent]] = None,
    ) -> List[ScheduleFATableA3LotResult]:
        """Compute Schedule FA Table A3 row details for each lot active in calendar_year.

        cy_sales must already be ENRICHED (i.e. the List[SaleEvent] returned by
        self.ledger.allocate_sales(), with .lot_allocations populated) - the caller must call
        allocate_sales() itself, once, before building the reconciliation report too, since it
        mutates the ledger's lots (splitting partially-sold lots, setting disposal dates) and
        that mutation needs to happen before ANY other step reads the ledger's lot state.
        """
        lot_proceeds_usd: Dict[str, float] = {}
        lot_proceeds_inr: Dict[str, int] = {}
        if cy_sales:
            for s in cy_sales:
                if s.sale_date.year == calendar_year:
                    # Explanation to Rule 115, clause (f): capital gains/sale proceeds convert
                    # at the TTBR of the last day of the month preceding the month of transfer.
                    _, sale_rate = self.sbi.get_rule_115_capital_gains_rate(s.sale_date)
                    for lot_id, proceeds_usd in s.lot_allocations.items():
                        lot_proceeds_usd[lot_id] = lot_proceeds_usd.get(lot_id, 0.0) + proceeds_usd
                        lot_proceeds_inr[lot_id] = lot_proceeds_inr.get(lot_id, 0) + round(proceeds_usd * sale_rate)

        fa_lots = self.ledger.get_schedule_fa_lots(calendar_year)
        results: List[ScheduleFATableA3LotResult] = []

        # If dividends provided, compute lot-level dividend sums
        lot_divs_usd: Dict[str, float] = {l.lot_id: 0.0 for l in fa_lots}
        lot_divs_inr: Dict[str, int] = {l.lot_id: 0 for l in fa_lots}

        if cy_dividends:
            enriched_divs = self.ledger.allocate_dividends(cy_dividends)
            for d in enriched_divs:
                if d.pay_date.year == calendar_year:
                    # Rule 115: dividend income converts at the TTBR of the last day of the
                    # month preceding the month of payment, not the TTBR on the pay date itself.
                    _, pay_rate = self.sbi.get_rule_115_dividend_rate(d.pay_date)
                    for lot_id, alloc_usd in d.lot_allocations.items():
                        if lot_id in lot_divs_usd:
                            lot_divs_usd[lot_id] += alloc_usd
                            lot_divs_inr[lot_id] += round(alloc_usd * pay_rate)

        for lot in fa_lots:
            # 1. Initial Investment (shares * vest_fmv * acq_rate)
            acq_rate = self.sbi.get_rate(lot.acquisition_date)
            init_val_inr = round(lot.net_shares * lot.vest_fmv_usd * acq_rate)

            # 2. Peak Balance (EOD Closing Price)
            peak_info = self.mkt.get_peak_for_lot(lot, calendar_year, self.sbi, use_eod_close=True)

            # 3. Closing Balance
            close_info = self.mkt.get_closing_for_lot(lot, calendar_year, self.sbi)

            init_cost_usd = round(lot.net_shares * lot.vest_fmv_usd, 2)
            peak_val_usd = round(lot.net_shares * peak_info["peak_price_usd"], 2)
            close_val_usd = round(lot.net_shares * close_info["closing_price_usd"], 2)
            src_acq = f"Benefit History Spreadsheet (Tranche Vest {lot.acquisition_date.strftime('%Y-%m-%d')})"
            src_peak = f"Yahoo Finance verified daily {lot.symbol} close (${peak_info['peak_price_usd']:.2f} on {peak_info['peak_date'].strftime('%Y-%m-%d')}) & SBI TTBR ₹{peak_info['peak_rate_inr']:.2f}"
            if close_info.get("sold_before_year_end"):
                src_close = f"Lot fully sold before Dec 31, {calendar_year} - closing balance is $0 by definition (no market data lookup needed)"
            else:
                price_date = close_info.get("closing_price_date", close_info["closing_date"])
                src_close = f"Yahoo Finance verified {lot.symbol} close (${close_info['closing_price_usd']:.2f} on {price_date.strftime('%Y-%m-%d')}) & 31-Dec SBI TTBR ₹{close_info['closing_rate_inr']:.2f}"
            src_div = f"Client Statements Account Activity (Dividends pro-rata)"
            src_proceeds = (
                f"Client Statements Account Activity (Sale proceeds, Rule 115 cl.(f) preceding-month-end rate)"
                if lot.lot_id in lot_proceeds_inr else ""
            )

            res = ScheduleFATableA3LotResult(
                lot_id=lot.lot_id,
                country_name="UNITED STATES OF AMERICA",
                country_code="2",
                name_of_entity=self.employer_entity_name,
                address_of_entity=self.employer_entity_address,
                zip_code=self.employer_zip,
                nature_of_entity="Company",
                acquisition_date=lot.acquisition_date,
                gross_shares=lot.gross_shares,
                net_shares=lot.net_shares,
                vest_fmv_usd=lot.vest_fmv_usd,
                acq_sbi_rate_inr=acq_rate,
                initial_value_inr=init_val_inr,
                peak_balance_inr=peak_info["peak_balance_inr"],
                peak_date=peak_info["peak_date"],
                peak_price_usd=peak_info["peak_price_usd"],
                peak_rate_inr=peak_info["peak_rate_inr"],
                closing_balance_inr=close_info["closing_balance_inr"],
                closing_date=close_info["closing_date"],
                closing_price_usd=close_info["closing_price_usd"],
                closing_rate_inr=close_info["closing_rate_inr"],
                gross_dividends_usd=round(lot_divs_usd.get(lot.lot_id, 0.0), 2),
                gross_dividends_inr=lot_divs_inr.get(lot.lot_id, 0),
                gross_proceeds_inr=lot_proceeds_inr.get(lot.lot_id, 0),
                gross_proceeds_usd=round(lot_proceeds_usd.get(lot.lot_id, 0.0), 2),
                is_sold_lot=lot.is_sold_lot,
                disposal_date=lot.disposal_date,
                initial_cost_usd=init_cost_usd,
                peak_balance_usd=peak_val_usd,
                closing_balance_usd=close_val_usd,
                source_acquisition=src_acq,
                source_peak=src_peak,
                source_closing=src_close,
                source_dividends=src_div,
                source_proceeds=src_proceeds,
                income_rate_inr=self.sbi.get_rate(date(calendar_year, 12, 31)),
                income_rate_date=date(calendar_year, 12, 31),
                peak_degraded=False,
                closing_degraded=False,
            )
            results.append(res)

        return results

    def compute_table_a2(
        self,
        calendar_year: int,
        dec_summary: StatementPeriodSummary,
        cy_dividends: List[DividendEvent]
    ) -> ScheduleFATableA2Result:
        """Compute Schedule FA Table A2 (Custodial Account level) results."""
        cy_start = date(calendar_year, 1, 1)
        cy_end = date(calendar_year, 12, 31)

        # 1. Closing Balance
        close_rate = self.sbi.get_rate(cy_end)
        closing_inr = round(dec_summary.ending_value_usd * close_rate)

        # 2. Peak Account Balance: Evaluate daily total account value (equities using EOD Close)
        peak_inr = -1.0
        peak_usd = 0.0
        peak_date = cy_start
        peak_rate = close_rate

        symbols = sorted({lot.symbol for lot in self.ledger.lots if lot.symbol})
        closes_by_symbol = {
            symbol: self.mkt.daily_closes(symbol, cy_start, cy_end)
            for symbol in symbols
        }
        valuation_dates = sorted({d for closes in closes_by_symbol.values() for d in closes})
        if symbols and not valuation_dates:
            raise ValueError(
                f"No verified daily market prices are available for {', '.join(symbols)} in {calendar_year}."
            )

        last_close: Dict[str, float] = {}
        for d in valuation_dates:
            day_usd = dec_summary.cash_balance_usd
            complete = True
            for symbol in symbols:
                if d in closes_by_symbol[symbol]:
                    last_close[symbol] = closes_by_symbol[symbol][d]
                shares, _ = self.ledger.get_shares_held_on_date(d, symbol)
                if shares > 0 and symbol not in last_close:
                    complete = False
                    break
                day_usd += shares * last_close.get(symbol, 0.0)
            if complete:
                day_rate = self.sbi.get_rate(d)
                day_inr = day_usd * day_rate
                if day_inr > peak_inr:
                    peak_inr = day_inr
                    peak_usd = day_usd
                    peak_date = d
                    peak_rate = day_rate

        # Table A2 Invariant: Peak balance must be at least closing balance
        if closing_inr > peak_inr:
            peak_inr = float(closing_inr)
            peak_usd = dec_summary.ending_value_usd
            peak_date = cy_end
            peak_rate = close_rate

        # 3. Gross amounts paid/credited in CY. Each nature is a separate CBDT A2 row.
        tot_div_usd = 0.0
        tot_div_inr = 0
        for d in cy_dividends:
            if d.pay_date.year == calendar_year:
                tot_div_usd += d.gross_amount_usd
                # Rule 115: same preceding-month-end TTBR rule as Schedule OS/Table A3.
                _, pay_rate = self.sbi.get_rule_115_dividend_rate(d.pay_date)
                tot_div_inr += round(d.gross_amount_usd * pay_rate)

        src_peak_a2 = (
            f"{self.broker_name} Statement cash balance plus verified daily closes for "
            f"{', '.join(symbols) or 'account holdings'} "
            f"cash balance on {peak_date.strftime('%Y-%m-%d')} & SBI TTBR ₹{peak_rate:.2f}"
        )
        src_close_a2 = f"{self.broker_name} Statement (Dec {calendar_year}, Page 1: Ending Net Portfolio Value) & SBI TTBR Sheet (31-Dec-{calendar_year})"
        src_gross_a2 = f"{self.broker_name} CY {calendar_year} Statement Account Activity & IRS Form 1042-S Box 2"
        gross_amounts = []
        if tot_div_usd or tot_div_inr:
            gross_amounts.append(A2GrossAmount(
                nature="D",
                amount_usd=round(tot_div_usd, 2),
                amount_inr=tot_div_inr,
                rate_inr=0.0,
                rate_date=cy_end,
                source=src_gross_a2,
            ))
        if dec_summary.interest_usd:
            gross_amounts.append(A2GrossAmount(
                nature="I",
                amount_usd=round(dec_summary.interest_usd, 2),
                amount_inr=round(dec_summary.interest_usd * close_rate),
                rate_inr=close_rate,
                rate_date=cy_end,
                source=f"{self.broker_name} statement interest credits",
            ))
        if not gross_amounts:
            gross_amounts.append(A2GrossAmount(
                nature="N",
                amount_usd=0.0,
                amount_inr=0,
                rate_inr=0.0,
                rate_date=cy_end,
                source="No gross amount paid or credited during the calendar year",
            ))

        return ScheduleFATableA2Result(
            country_name="UNITED STATES OF AMERICA",
            country_code="2",
            financial_inst_name=self.broker_name,
            financial_inst_address=self.broker_address,
            zip_code=self.broker_zip,
            account_number=self.account_number,
            status="OWNER",
            account_open_date=self.account_open_date,
            peak_balance_usd=round(peak_usd, 2),
            peak_balance_inr=round(peak_inr),
            peak_date=peak_date,
            peak_rate_inr=peak_rate,
            closing_balance_usd=dec_summary.ending_value_usd,
            closing_balance_inr=closing_inr,
            closing_date=cy_end,
            closing_rate_inr=close_rate,
            gross_amounts=gross_amounts,
            peak_degraded=False,
            source_peak=src_peak_a2,
            source_closing=src_close_a2,
        )

    def compute_schedule_os_and_ftc(
        self,
        fy_dividends: List[DividendEvent],
        indian_tax_rate: float = 0.312,  # taxpayer's rate on this income; default 30% slab + 4% cess
        calendar_year: Optional[int] = None,
        dtaa_rate_cap: float = 0.25,
    ) -> Tuple[ScheduleOSResult, FTCResult]:
        """Compute Schedule OS dividend buckets and Foreign Tax Credit claim for the Indian FY starting 1-Apr-calendar_year.

        calendar_year is the first (April-starting) calendar year of the Financial Year, e.g. for
        FY 2025-26 pass calendar_year=2025. If omitted, it is inferred as the earliest pay_date
        year among fy_dividends (kept for backward compatibility with older callers/tests).
        """
        items: List[DividendTaxResult] = []

        if calendar_year is None:
            calendar_year = min((d.pay_date.year for d in fy_dividends), default=date.today().year)
        next_year = calendar_year + 1

        installment_1_end = date(calendar_year, 6, 15)
        installment_2_end = date(calendar_year, 9, 15)
        installment_3_end = date(calendar_year, 12, 15)
        installment_4_end = date(next_year, 3, 15)

        b1, b2, b3, b4, b5 = 0, 0, 0, 0, 0
        total_gross_usd = 0.0
        total_tax_paid_usd = 0.0
        total_gross_inr = 0
        total_tax_paid_inr = 0

        for d in fy_dividends:
            total_gross_usd += d.gross_amount_usd
            total_tax_paid_usd += d.tax_withheld_usd

            # Rule 115 rate on last business day of preceding month
            p_month_end, r115 = self.sbi.get_rule_115_dividend_rate(d.pay_date)
            gross_inr = round(d.gross_amount_usd * r115)

            # Rule 128(5)(ii): TTBR on last day of month preceding month tax was paid/deducted
            tax_deduction_date = d.tax_deduction_date or d.pay_date
            _, r128 = self.sbi.get_rule_128_rate(tax_deduction_date)
            tax_inr = round(d.tax_withheld_usd * r128)

            total_gross_inr += gross_inr
            total_tax_paid_inr += tax_inr

            # Classify into 5 advance-tax installments
            p_date = d.pay_date
            if p_date <= installment_1_end:
                bucket = "Upto15Of6"
                b1 += gross_inr
            elif p_date <= installment_2_end:
                bucket = "Upto15Of9"
                b2 += gross_inr
            elif p_date <= installment_3_end:
                bucket = "Up16Of9To15Of12"
                b3 += gross_inr
            elif p_date <= installment_4_end:
                bucket = "Up16Of12To15Of3"
                b4 += gross_inr
            else:
                bucket = "Up16Of3To31Of3"
                b5 += gross_inr

            src_item = f"{self.broker_name} Statement ({d.pay_date.strftime('%b %Y')} Activity) & Form 1042-S"

            items.append(DividendTaxResult(
                pay_date=d.pay_date,
                symbol=d.symbol,
                gross_usd=d.gross_amount_usd,
                tax_usd=d.tax_withheld_usd,
                tax_deduction_date=tax_deduction_date,
                preceding_month_end=p_month_end,
                rule_115_rate=r115,
                gross_inr=gross_inr,
                rule_128_rate=r128,
                tax_inr=tax_inr,
                advance_tax_bucket=bucket,
                source_document=src_item
            ))

        os_res = ScheduleOSResult(
            total_dividend_inr=total_gross_inr,
            upto_15_jun_inr=b1,
            upto_15_sep_inr=b2,
            upto_15_dec_inr=b3,
            upto_15_mar_inr=b4,
            upto_31_mar_inr=b5,
            items=items
        )

        # FTC: Rule 128(5)(i) allows the lower of the Indian tax payable on this income and the
        # foreign tax paid; India-US DTAA Art. 10(2)(b) caps creditable US tax on dividends at
        # dtaa_rate_cap of the gross ("excess shall be ignored"). Same caps in INR and USD.
        indian_tax_est = round(total_gross_inr * indian_tax_rate)
        dtaa_cap_inr = round(total_gross_inr * dtaa_rate_cap)
        ftc_claimed = min(total_tax_paid_inr, indian_tax_est, dtaa_cap_inr)
        ftc_claimed_usd = round(min(total_tax_paid_usd, total_gross_usd * indian_tax_rate, total_gross_usd * dtaa_rate_cap), 2)

        ftc_res = FTCResult(
            country_name="UNITED STATES OF AMERICA",
            country_code="2",
            head_of_income="Income from Other Sources",
            source_of_income="Dividends",
            dtaa_article="Article 10",
            gross_foreign_income_inr=total_gross_inr,
            foreign_tax_paid_inr=total_tax_paid_inr,
            estimated_indian_tax_inr=indian_tax_est,
            tax_relief_claimed_inr=ftc_claimed,
            gross_foreign_income_usd=round(total_gross_usd, 2),
            foreign_tax_paid_usd=round(total_tax_paid_usd, 2),
            tax_relief_claimed_usd=ftc_claimed_usd,
            indian_tax_rate=indian_tax_rate,
            dtaa_rate_cap=dtaa_rate_cap,
            source_document="IRS Form 1042-S (Box 2 & Box 7a) & broker statements"
        )

        return os_res, ftc_res
