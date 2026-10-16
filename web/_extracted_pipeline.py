import json, traceback
from datetime import date
from itr_assist.models import PLACEHOLDER_PREFIX
from itr_assist.parsers import BrokerParserFactory
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.reconciliation.verifier import DocumentVerifier
from itr_assist.reports.excel_generator import ITRWorkbookGenerator
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.open_years import fy_to_calendar_year
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import ValuationEngine
from itr_assist.validation import ValidationEngine

def run_pipeline(fy, taxpayer_name, pan, stmt_paths_json, market_api_key, details_json="{}"):
    details = json.loads(details_json or "{}")
    cy = fy_to_calendar_year(fy)
    next_cy = cy + 1
    ay_y1 = cy + 1
    ay = f"{ay_y1}-{(ay_y1 + 1) % 100:02d}"

    stmt_paths = json.loads(stmt_paths_json)
    if not stmt_paths:
        raise ValueError("No statement PDFs were provided - select every statement you have, from account-open through the end of the filing year.")

    adapter = BrokerParserFactory.auto_detect(stmt_paths[0])
    all_lots = adapter.parse_benefit_history("/uploads/benefit.xlsx")
    holdings_lots = adapter.parse_holdings("/uploads/holdings.xlsx")
    primary_symbol = all_lots[0].symbol if all_lots else None
    summaries, dividends, sales = adapter.parse_statements(
        stmt_paths, symbol_hint=primary_symbol, calendar_year_hint=cy
    )
    form_1042s = adapter.parse_tax_documents("/uploads/taxdoc.pdf", calendar_year_hint=cy)

    tp_name = taxpayer_name or (form_1042s.recipient_name if form_1042s and form_1042s.recipient_name else f"{PLACEHOLDER_PREFIX}: taxpayer name")
    tp_pan = pan or (form_1042s.recipient_tin if form_1042s and form_1042s.recipient_tin else f"{PLACEHOLDER_PREFIX}: PAN")

    ledger = LotLedger(all_lots)
    enriched_sales = ledger.allocate_sales(sales)
    verifier = DocumentVerifier(ledger, holdings_lots)
    report = verifier.verify_holdings()

    sbi = SBIRateService()

    detected_symbols = list(set(l.symbol for l in all_lots if l.symbol))
    symbols = detected_symbols if detected_symbols else list(set(d.symbol for d in dividends if d.symbol))

    mkt = MarketDataService(api_key=(market_api_key or None))
    for sym in symbols:
        mkt.load_symbol(sym)
    if mkt.unavailable_symbols:
        key_note = "even with the provided API key" if market_api_key else "no API key was provided"
        raise ValueError(
            f"Verified daily market data is unavailable for {', '.join(sorted(mkt.unavailable_symbols))} "
            f"({key_note}). Generation is blocked because Schedule FA peak and closing values "
            f"must not be approximated. Configure a market-data API key or retry with connectivity."
        )

    primary_sym = symbols[0] if symbols else "STOCK"
    account_num = form_1042s.account_number if form_1042s and form_1042s.account_number else ""

    # Details no broker document states (company address/ZIP, account opening date) come from the
    # taxpayer; anything still blank becomes a "TO BE FILLED" placeholder that validation flags.
    def detail(key):
        return (details.get(key) or "").strip()

    security_names = {}
    for s in summaries:
        security_names.update(s.holdings_name)
    broker_address, broker_zip, broker_source = detail("broker_address"), detail("broker_zip"), ""
    if not broker_address and form_1042s and form_1042s.withholding_agent_address:
        broker_address = form_1042s.withholding_agent_address
        broker_zip = broker_zip or form_1042s.withholding_agent_zip
        broker_source = "Form 1042-S box 12 (withholding agent)"
    engine = ValuationEngine(
        ledger=ledger, sbi_service=sbi, market_service=mkt,
        employer_entity_name=detail("company_name") or security_names.get(primary_sym, ""),
        employer_entity_address=detail("company_address"), employer_zip=detail("company_zip"),
        broker_name=adapter.broker_name, account_number=account_num,
        broker_address=broker_address, broker_zip=broker_zip,
        account_open_date=detail("account_open_date"), broker_details_source=broker_source,
    )

    dec_summary = next((s for s in summaries if s.end_date == date(cy, 12, 31)), None)
    if dec_summary is None:
        raise ValueError(f"No statement period ending 31-Dec-{cy} found - check the Calendar Year Statement covers all of {cy}.")

    a2_res = engine.compute_table_a2(
        cy, dec_summary, dividends, statement_summaries=summaries, cy_sales=enriched_sales
    )
    a3_res = engine.compute_table_a3(cy, dividends, enriched_sales)

    fy_divs = [d for d in dividends if date(cy, 4, 1) <= d.pay_date <= date(next_cy, 3, 31)]
    os_res, ftc_res = engine.compute_schedule_os_and_ftc(fy_divs, calendar_year=cy)

    validator = ValidationEngine(sbi_service=sbi)
    cy_div_usd = sum(d.gross_amount_usd for d in dividends if d.pay_date.year == cy)
    cy_tax_usd = sum(d.tax_withheld_usd for d in dividends if d.pay_date.year == cy)
    val_report = validator.validate(
        a2=a2_res, a3_lots=a3_res, os_result=os_res, ftc=ftc_res,
        form_1042s=form_1042s, cy_dividends_usd=cy_div_usd, cy_tax_withheld_usd=cy_tax_usd,
        is_resident=True, part_b_tti_sl19_yes=True, sales=enriched_sales,
        statement_summaries=summaries, lots=ledger.lots, calendar_year=cy,
        taxpayer_fields={"taxpayer name": tp_name, "PAN": tp_pan},
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
        "kpis": {
            "peak": a2_res.peak_balance_usd,
            "closing": a2_res.closing_balance_usd,
            "dividends": sum(i.gross_usd for i in os_res.items),
            "proceeds": sum(l.gross_proceeds_usd for l in a3_res),
            "ftcInr": ftc_res.tax_relief_claimed_inr,
            "accounts": 1,
        },
        "scorecard": [
            {"id": r.rule_id, "title": r.title, "status": r.status.value,
             "severity": r.severity.value, "details": r.details}
            for r in val_report.results
        ],
        "scoreSummary": {"total": sc.total_rules, "passed": sc.passed, "status": sc.compute_status()},
        "downloadAllowed": sc.is_filing_ready,
        "outputFile": f"ITR2_Foreign_Assets_Working_AY{ay}.xlsx",
    })

try:
    result = run_pipeline(fy, taxpayer_name, pan, stmt_paths_json, market_api_key, globals().get("details_json", "{}"))
except Exception as e:
    import json as _json
    result = _json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()})
result
