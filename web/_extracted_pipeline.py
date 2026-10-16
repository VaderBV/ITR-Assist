
import json, traceback
from datetime import date
from itr_assist.parsers import BrokerParserFactory
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.reconciliation.verifier import DocumentVerifier
from itr_assist.reports.excel_generator import ITRWorkbookGenerator
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.open_years import fy_to_calendar_year
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import ValuationEngine
from itr_assist.validation import ValidationEngine

def run_pipeline(fy, taxpayer_name, pan, stmt_paths_json):
    cy = fy_to_calendar_year(fy)
    next_cy = cy + 1
    ay_y1 = cy + 1
    ay = f"{ay_y1}-{(ay_y1 + 1) % 100:02d}"

    stmt_paths = json.loads(stmt_paths_json)
    if not stmt_paths:
        raise ValueError("No statement PDFs were provided - select every month's PDF for both the Calendar Year and Q4/FY-End slots.")

    adapter = BrokerParserFactory.auto_detect(stmt_paths[0])
    all_lots = adapter.parse_benefit_history("/uploads/benefit.xlsx")
    holdings_lots = adapter.parse_holdings("/uploads/holdings.xlsx")
    primary_symbol = all_lots[0].symbol if all_lots else None
    summaries, dividends, sales = adapter.parse_statements(
        stmt_paths, symbol_hint=primary_symbol, calendar_year_hint=cy
    )
    form_1042s = adapter.parse_tax_documents("/uploads/taxdoc.pdf", calendar_year_hint=cy)

    tp_name = taxpayer_name or (form_1042s.recipient_name if form_1042s and form_1042s.recipient_name else "SAMPLE TAXPAYER")
    tp_pan = pan or (form_1042s.recipient_tin if form_1042s and form_1042s.recipient_tin else "ABCDE1234F")

    ledger = LotLedger(all_lots)
    enriched_sales = ledger.allocate_sales(sales)
    verifier = DocumentVerifier(ledger, holdings_lots)
    report = verifier.verify_holdings()

    sbi = SBIRateService()

    detected_symbols = list(set(l.symbol for l in all_lots if l.symbol))
    symbols = detected_symbols if detected_symbols else list(set(d.symbol for d in dividends if d.symbol))

    market_warning = None
    mkt = MarketDataService()
    for sym in symbols:
        try:
            mkt.load_symbol(sym)
        except Exception as e:
            market_warning = f"Could not load live market data for {sym}: {e}"

    primary_sym = symbols[0] if symbols else "STOCK"
    account_num = form_1042s.account_number if form_1042s and form_1042s.account_number else ""
    engine = ValuationEngine(
        ledger=ledger, sbi_service=sbi, market_service=mkt,
        employer_entity_name=f"{primary_sym} Corporation",
        broker_name=adapter.broker_name, account_number=account_num,
    )

    dec_summary = next((s for s in summaries if s.end_date == date(cy, 12, 31)), None)
    if dec_summary is None:
        raise ValueError(f"No statement period ending 31-Dec-{cy} found - check the Calendar Year Statement covers all of {cy}.")

    a2_res = engine.compute_table_a2(cy, dec_summary, dividends)
    a3_res = engine.compute_table_a3(cy, dividends, enriched_sales)

    fy_divs = [d for d in dividends if date(cy, 4, 1) <= d.pay_date <= date(next_cy, 3, 31)]
    os_res, ftc_res = engine.compute_schedule_os_and_ftc(fy_divs, calendar_year=cy)

    validator = ValidationEngine(sbi_service=sbi)
    cy_div_usd = sum(d.gross_amount_usd for d in dividends if d.pay_date.year == cy)
    cy_tax_usd = sum(d.tax_withheld_usd for d in dividends if d.pay_date.year == cy)
    val_report = validator.validate(
        a2=a2_res, a3_lots=a3_res, os_result=os_res, ftc=ftc_res, recon=report,
        form_1042s=form_1042s, cy_dividends_usd=cy_div_usd, cy_tax_withheld_usd=cy_tax_usd,
        is_resident=True, part_b_tti_sl19_yes=True,
    )

    out_path = "/output/ITR_Schedules.xlsx"
    generator = ITRWorkbookGenerator(output_path=out_path)
    generator.generate(
        a2_result=a2_res, a3_lots=a3_res, os_result=os_res, ftc_result=ftc_res,
        form_1042s=form_1042s, reconciliation_report=report, dividends=dividends,
        statement_summaries=summaries, taxpayer_name=tp_name, pan=tp_pan,
        ay=ay, fy=fy, sbi_service=sbi, val_report=val_report,
    )

    sc = val_report.scorecard
    return json.dumps({
        "ok": True,
        "outPath": out_path,
        "marketWarning": market_warning,
        "kpis": {
            "peak": a2_res.peak_balance_usd,
            "closing": a2_res.closing_balance_usd,
            "dividends": sum(i.gross_usd for i in os_res.items),
            "proceeds": sum(l.gross_proceeds_usd for l in a3_res),
            "ftcInr": ftc_res.tax_relief_claimed_inr,
            "accounts": 1,
        },
        "scorecard": [
            {"id": r.rule_id, "title": r.title, "status": r.status.value, "details": r.details}
            for r in val_report.results
        ],
        "scoreSummary": {"total": sc.total_rules, "passed": sc.passed, "status": sc.compute_status()},
        "outputFile": f"ITR2_Foreign_Assets_Working_AY{ay}.xlsx",
    })

try:
    result = run_pipeline(fy, taxpayer_name, pan, stmt_paths_json)
except Exception as e:
    import json as _json
    result = _json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()})
result
