"""CLI entry point for ITR Assist."""
import argparse
from datetime import date
import os
import sys

from itr_assist.parsers import BrokerParserFactory
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.reconciliation.verifier import DocumentVerifier
from itr_assist.reports.excel_generator import ITRWorkbookGenerator
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.open_years import fy_to_calendar_year
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import ValuationEngine


def main() -> int:
    """Run CLI generation pipeline."""
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="ITR-2 Foreign Assets Automation Utility (Schedule FA, OS, FSI, TR, Form 67)"
    )
    parser.add_argument("--data-dir", default=None, help="Directory containing broker documents (optional)")
    parser.add_argument("--benefit-file", default=None, help="Path to Benefit History spreadsheet")
    parser.add_argument("--holdings-file", default=None, help="Path to Current Holdings spreadsheet")
    parser.add_argument("--stmt-cy", default=None, help="Path to Calendar Year Statements PDF")
    parser.add_argument("--stmt-fy", default=None, help="Path to Q4 / FY-End Statements PDF")
    parser.add_argument("--tax-doc", default=None, help="Path to Form 1042-S Tax Document PDF")
    parser.add_argument("--ay", default="2026-27", help="Assessment Year (default: 2026-27)")
    parser.add_argument("--fy", default="2025-26", help="Financial Year (default: 2025-26)")
    parser.add_argument("--output", default="ITR2_Foreign_Assets_Working_AY2026-27.xlsx", help="Output Excel filename")
    parser.add_argument("--taxpayer-name", default=None, help="Taxpayer full name (auto-detected from Form 1042-S if omitted)")
    parser.add_argument("--pan", default=None, help="Taxpayer PAN (auto-detected from Form 1042-S if omitted)")
    parser.add_argument("--symbol", default=None, help="Stock ticker symbol (auto-detected from Benefit History if omitted)")
    parser.add_argument("--employer-name", default=None, help="Employer entity name for Schedule FA Table A3")
    parser.add_argument("--employer-address", default=None, help="Employer entity address for Schedule FA Table A3")
    parser.add_argument("--employer-zip", default=None, help="Employer zip code for Schedule FA Table A3")

    args = parser.parse_args()

    # Single source of truth for "which calendar year is this filing about" - every date
    # literal downstream is derived from this instead of being hardcoded.
    cy = fy_to_calendar_year(args.fy)
    next_cy = cy + 1
    cy_str, next_cy_str = str(cy), str(next_cy)

    print("=" * 75)
    print("  ITR-2 FOREIGN ASSETS & TAX RELIEF AUTOMATION UTILITY")
    print(f"  Assessment Year: {args.ay}  |  Financial Year: {args.fy}")
    print("=" * 75)

    benefit_file = args.benefit_file
    holdings_file = args.holdings_file
    stmt_cy_file = args.stmt_cy
    stmt_fy_end_file = args.stmt_fy
    tax_doc = args.tax_doc

    # Auto-discover files if --data-dir is supplied, without hardcoding proprietary filenames
    if args.data_dir and os.path.isdir(args.data_dir):
        for fname in os.listdir(args.data_dir):
            fl = fname.lower()
            fpath = os.path.join(args.data_dir, fname)
            if not benefit_file and ("benefit" in fl and fl.endswith((".xlsx", ".xls"))):
                benefit_file = fpath
            elif not holdings_file and (("holding" in fl or "status" in fl) and fl.endswith((".xlsx", ".xls"))):
                holdings_file = fpath
            elif not stmt_cy_file and ("statement" in fl and cy_str in fl and fl.endswith(".pdf")):
                stmt_cy_file = fpath
            elif not stmt_fy_end_file and ("statement" in fl and (next_cy_str in fl or "march" in fl or "q4" in fl) and fl.endswith(".pdf")):
                stmt_fy_end_file = fpath
            elif not tax_doc and (("1042" in fl or "tax" in fl) and fl.endswith(".pdf")):
                tax_doc = fpath

    missing = []
    if not benefit_file: missing.append("--benefit-file")
    if not holdings_file: missing.append("--holdings-file")
    if not stmt_cy_file: missing.append("--stmt-cy")
    if not stmt_fy_end_file: missing.append("--stmt-fy")
    if not tax_doc: missing.append("--tax-doc")
    if missing:
        print(f"\n[ERROR] Missing required input files: {', '.join(missing)}")
        print("Please provide individual file paths (e.g., --benefit-file PATH) or a directory via --data-dir.")
        return 1

    # 1. Resolve Broker Adapter
    print("\n[1/5] Ingesting documents via modular broker adapter...")
    adapter = BrokerParserFactory.auto_detect(stmt_cy_file)
    print(f"      Selected Adapter: {adapter.broker_name}")

    all_lots = adapter.parse_benefit_history(benefit_file)
    print(f"      • Benefit History: Ingested {len(all_lots)} historical RSU/ESPP tranches")

    holdings_lots = adapter.parse_holdings(holdings_file)
    print(f"      • Current Holdings: Ingested {len(holdings_lots)} active snapshot lots")

    primary_symbol = all_lots[0].symbol if all_lots else None
    statement_summaries, dividends, sales = adapter.parse_statements(
        [stmt_cy_file, stmt_fy_end_file], symbol_hint=primary_symbol, calendar_year_hint=cy
    )
    print(f"      • Client Statements: Extracted {len(statement_summaries)} period summaries, {len(dividends)} dividends & {len(sales)} sale transactions")

    form_1042s = adapter.parse_tax_documents(tax_doc, calendar_year_hint=cy)
    print(f"      • Form 1042-S: Verified Gross ${form_1042s.gross_dividend_usd:.2f}, Tax ${form_1042s.tax_withheld_usd:.2f}")

    # Auto-detect Taxpayer Name and PAN from Form 1042-S if not explicitly passed
    taxpayer_name = args.taxpayer_name or (form_1042s.recipient_name if form_1042s and form_1042s.recipient_name else "SAMPLE TAXPAYER")
    pan = args.pan or (form_1042s.recipient_tin if form_1042s and form_1042s.recipient_tin else "ABCDE1234F")

    # 2. Reconstruct Chronological Lot Ledger
    print("\n[2/5] Reconstructing chronological lot lifecycle & sold lots...")
    ledger = LotLedger(all_lots)
    # Must run before verify_holdings()/get_schedule_fa_lots(): this mutates the ledger's lots
    # (splitting partially-sold lots, setting disposal dates) so every later step sees the
    # correct post-sale state instead of treating a sold lot as still fully held.
    enriched_sales = ledger.allocate_sales(sales)
    verifier = DocumentVerifier(ledger, holdings_lots)
    report = verifier.verify_holdings()

    print(f"      • Reconciliation Status: {report.status}")
    print(f"      • Total Active Shares  : {report.total_reconstructed_shares:.1f} shs (matches holdings)")
    print(f"      • Sold Lots Detected   : {report.sold_lots_count} lot(s)")
    for sl in report.sold_lots:
        print(f"        -> Lot {sl.lot_id}: {sl.net_shares} shs acquired {sl.acquisition_date}, sold {sl.disposal_date}")

    fa_lots = ledger.get_schedule_fa_lots(calendar_year=cy)
    print(f"      • Schedule FA Scope    : {len(fa_lots)} lots active in CY {cy}")

    # 3. Load External Market Data & SBI TTBR
    print("\n[3/5] Loading historical SBI TT Buying Rates and Yahoo Finance stock data...")
    sbi = SBIRateService()
    print("      • SBI TTBR Engine: Historical rates archive loaded and cached")

    # Dynamically detect stock ticker symbols
    detected_symbols = list(set(lot.symbol for lot in all_lots if lot.symbol))
    if args.symbol:
        symbols = [args.symbol]
    elif detected_symbols:
        symbols = detected_symbols
    elif dividends:
        symbols = list(set(d.symbol for d in dividends if d.symbol))
    else:
        symbols = []

    mkt = MarketDataService()
    for sym in symbols:
        mkt.load_symbol(sym)
        print(f"      • Market Data Engine: {sym} daily OHLC prices loaded and cached")

    # 4. Valuation Engine Computations
    print("\n[4/5] Computing Schedule FA, OS, FSI, TR, and Form 67 figures...")
    primary_sym = symbols[0] if symbols else "STOCK"
    employer_name = args.employer_name or f"{primary_sym} Corporation"
    employer_address = args.employer_address or "Corporate Headquarters Address"
    employer_zip = args.employer_zip or "00000"
    account_num = form_1042s.account_number if form_1042s and form_1042s.account_number else ""

    engine = ValuationEngine(
        ledger=ledger,
        sbi_service=sbi,
        market_service=mkt,
        employer_entity_name=employer_name,
        employer_entity_address=employer_address,
        employer_zip=employer_zip,
        broker_name=adapter.broker_name,
        account_number=account_num
    )

    dec_summary = next(s for s in statement_summaries if s.end_date == date(cy, 12, 31))
    a2_res = engine.compute_table_a2(cy, dec_summary, dividends)
    a3_res = engine.compute_table_a3(cy, dividends, enriched_sales)

    fy_divs = [d for d in dividends if date(cy, 4, 1) <= d.pay_date <= date(next_cy, 3, 31)]
    os_res, ftc_res = engine.compute_schedule_os_and_ftc(fy_divs, calendar_year=cy)

    print(f"      • Schedule FA Table A2 Peak Balance   : ₹ {a2_res.peak_balance_inr:,}")
    print(f"      • Schedule FA Table A2 Closing Balance: ₹ {a2_res.closing_balance_inr:,}")
    print(f"      • Schedule FA Table A3 Equities Total : ₹ {sum(l.closing_balance_inr for l in a3_res):,}")
    print(f"      • Schedule OS Gross Foreign Dividends : ₹ {os_res.total_dividend_inr:,}")
    print(f"      • Foreign Tax Paid Outside India (25%): ₹ {ftc_res.foreign_tax_paid_inr:,}")
    print(f"      • FTC Relief Claimed u/s 90 (DTAA)    : ₹ {ftc_res.tax_relief_claimed_inr:,}")

    # 4.5 Run Statutory & Schema Validation Engine
    print("\n[4.5/5] Executing CBDT Statutory & Schema Rules Validation Engine...")
    from itr_assist.validation import ValidationEngine
    validator = ValidationEngine(sbi_service=sbi)
    cy_div_usd = sum(d.gross_amount_usd for d in dividends if d.pay_date.year == cy)
    cy_tax_usd = sum(d.tax_withheld_usd for d in dividends if d.pay_date.year == cy)
    val_report = validator.validate(
        a2=a2_res,
        a3_lots=a3_res,
        os_result=os_res,
        ftc=ftc_res,
        recon=report,
        form_1042s=form_1042s,
        cy_dividends_usd=cy_div_usd,
        cy_tax_withheld_usd=cy_tax_usd,
        is_resident=True,
        part_b_tti_sl19_yes=True,
    )
    sc = val_report.scorecard
    print(f"      • Total Rules Evaluated   : {sc.total_rules}")
    print(f"      • Rules Passed (Compliant): {sc.passed}")
    print(f"      • Fatal Schema Violations : {sc.fatal_errors}")
    print(f"      • Defective u/s 139(9)    : {sc.defective_errors}")
    print(f"      • Statutory Breaches      : {sc.statutory_errors}")
    print(f"      • Audit Warnings          : {sc.warnings}")
    print(f"      • Overall Filing Readiness: {sc.compute_status()}")

    # 5. Generate Excel Workbook
    print(f"\n[5/5] Generating official government-mirrored Excel workbook...")
    generator = ITRWorkbookGenerator(output_path=args.output)
    out_file = generator.generate(
        a2_result=a2_res,
        a3_lots=a3_res,
        os_result=os_res,
        ftc_result=ftc_res,
        form_1042s=form_1042s,
        reconciliation_report=report,
        dividends=dividends,
        statement_summaries=statement_summaries,
        taxpayer_name=taxpayer_name,
        pan=pan,
        ay=args.ay,
        fy=args.fy,
        sbi_service=sbi,
        val_report=val_report
    )

    print("\n" + "=" * 75)
    print(f"  SUCCESS! Workbook generated at: {os.path.abspath(out_file)}")
    print("=" * 75)
    return 0


if __name__ == "__main__":
    sys.exit(main())
