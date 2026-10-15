// ITR Assist — browser-side orchestration.
// Everything runs client-side via Pyodide. No file is ever uploaded anywhere.

const FILE_SLOTS = [
  { key: "benefit", accept: ".xlsx,.xls", cardId: "card-benefit", nameId: "name-benefit" },
  { key: "holdings", accept: ".xlsx,.xls", cardId: "card-holdings", nameId: "name-holdings" },
  { key: "stmtCy", accept: ".pdf", cardId: "card-stmtCy", nameId: "name-stmtCy" },
  { key: "stmtFy", accept: ".pdf", cardId: "card-stmtFy", nameId: "name-stmtFy" },
  { key: "taxDoc", accept: ".pdf", cardId: "card-taxDoc", nameId: "name-taxDoc" },
];

const state = {
  files: {}, // key -> File
  phase: "idle", // idle | loading | counting | done | error
  pyodide: null,
  errorMessage: "",
  fy: "2025-26",
};

const $ = (id) => document.getElementById(id);

function fmtUSD(n) {
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtINR(n) {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}
function fmtBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
  return (n / (1024 * 1024)).toFixed(1) + " MB";
}

function filesReadyCount() {
  return FILE_SLOTS.filter((s) => state.files[s.key]).length;
}

function updateFileCardUI(slot) {
  const card = $(slot.cardId);
  const nameEl = $(slot.nameId);
  const file = state.files[slot.key];
  if (file) {
    card.classList.add("file-filled");
    nameEl.textContent = `${file.name} · ${fmtBytes(file.size)}`;
  } else {
    card.classList.remove("file-filled");
    nameEl.textContent = "No file selected";
  }
  $("ready-count").textContent = `${filesReadyCount()} of 5 received`;
  $("btn-generate").disabled = filesReadyCount() < 5 || state.phase === "loading" || state.phase === "counting";
}

function setPhase(phase, errorMessage) {
  state.phase = phase;
  state.errorMessage = errorMessage || "";
  const btn = $("btn-generate");
  const statusText = $("status-text");
  const resultsWrap = $("results-wrap");
  const errorBox = $("error-box");

  errorBox.style.display = phase === "error" ? "flex" : "none";
  if (phase === "error") $("error-text").textContent = state.errorMessage;

  resultsWrap.style.display = phase === "idle" ? "none" : "block";

  const labels = {
    idle: "Generate Schedules",
    loading: "Reading documents…",
    counting: "Computing schedules…",
    done: "Regenerate",
    error: "Try again",
  };
  btn.textContent = "";
  const icon = document.createElement("span");
  icon.className = "icon" + (phase === "loading" || phase === "counting" ? " spin" : "");
  icon.innerHTML = phase === "loading" || phase === "counting"
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" style="width:16px;height:16px;"><path d="M21 12a9 9 0 1 1-9-9"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
  btn.appendChild(icon);
  btn.appendChild(document.createTextNode(" " + labels[phase]));
  btn.disabled = phase === "loading" || phase === "counting" || filesReadyCount() < 5;

  statusText.textContent = {
    idle: "All five documents are in — this takes a few seconds, fully offline",
    loading: "Parsing Benefit History, Holdings, and both statements…",
    counting: "Applying Rule 115 / Rule 128 conversions and FIFO lot matching…",
    done: "Generated just now",
    error: "Generation failed — see details below",
  }[phase];

  const skeleton = $("skeleton-block");
  const numbers = $("numbers-block");
  const scorecard = $("scorecard-block");
  skeleton.style.display = phase === "loading" ? "grid" : "none";
  numbers.style.display = phase === "counting" || phase === "done" ? "grid" : "none";
  scorecard.style.display = phase === "done" ? "block" : "none";
}

async function readFileBytes(file) {
  const buf = await file.arrayBuffer();
  return new Uint8Array(buf);
}

let pyodideReadyPromise = null;

async function bootPyodide(onProgress) {
  if (pyodideReadyPromise) return pyodideReadyPromise;
  pyodideReadyPromise = (async () => {
    onProgress("Loading Python runtime…");
    const pyodide = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/" });

    onProgress("Loading pandas…");
    await pyodide.loadPackage(["pandas", "micropip"]);

    onProgress("Installing itr_assist and dependencies…");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install([
      "openpyxl",
      "pypdf",
      "jsonschema",
      "referencing",
      "pyodide-http",
    ]);
    await micropip.install("./dist/itr_assist-1.0.0-py3-none-any.whl");

    onProgress("Patching network calls for the browser…");
    await pyodide.runPythonAsync(`
import pyodide_http
pyodide_http.patch_all()
`);

    onProgress("Seeding bundled offline data…");
    const sbiResp = await fetch("./data/cache/SBI_REFERENCE_RATES_USD.csv");
    const sbiBytes = new Uint8Array(await sbiResp.arrayBuffer());
    pyodide.FS.mkdirTree("/data/cache");
    pyodide.FS.writeFile("/data/cache/SBI_REFERENCE_RATES_USD.csv", sbiBytes);
    pyodide.FS.mkdirTree("/uploads");
    pyodide.FS.mkdirTree("/output");

    return pyodide;
  })();
  return pyodideReadyPromise;
}

// Mirrors cli.py's pipeline, adapted to read from the in-browser virtual filesystem
// instead of argparse paths. No change to itr_assist's own logic.
const PY_PIPELINE = `
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

def run_pipeline(fy, taxpayer_name, pan):
    cy = fy_to_calendar_year(fy)
    next_cy = cy + 1
    ay_y1 = cy + 1
    ay = f"{ay_y1}-{(ay_y1 + 1) % 100:02d}"

    stmt_cy = "/uploads/stmt_cy.pdf"
    stmt_fy = "/uploads/stmt_fy.pdf"

    adapter = BrokerParserFactory.auto_detect(stmt_cy)
    all_lots = adapter.parse_benefit_history("/uploads/benefit.xlsx")
    holdings_lots = adapter.parse_holdings("/uploads/holdings.xlsx")
    primary_symbol = all_lots[0].symbol if all_lots else None
    summaries, dividends, sales = adapter.parse_statements(
        [stmt_cy, stmt_fy], symbol_hint=primary_symbol, calendar_year_hint=cy
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
    result = run_pipeline(fy, taxpayer_name, pan)
except Exception as e:
    import json as _json
    result = _json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()})
result
`;

async function generate() {
  setPhase("loading");
  try {
    const pyodide = await bootPyodide((msg) => (($("status-text").textContent = msg)));

    const writes = {
      benefit: "/uploads/benefit.xlsx",
      holdings: "/uploads/holdings.xlsx",
      stmtCy: "/uploads/stmt_cy.pdf",
      stmtFy: "/uploads/stmt_fy.pdf",
      taxDoc: "/uploads/taxdoc.pdf",
    };
    for (const [key, path] of Object.entries(writes)) {
      const bytes = await readFileBytes(state.files[key]);
      pyodide.FS.writeFile(path, bytes);
    }

    setPhase("counting");
    const fy = state.fy;
    const taxpayerName = $("tp-name").value;
    const pan = $("tp-pan").value;
    pyodide.globals.set("fy", fy);
    pyodide.globals.set("taxpayer_name", taxpayerName);
    pyodide.globals.set("pan", pan);

    const resultJson = await pyodide.runPythonAsync(PY_PIPELINE);
    const result = JSON.parse(resultJson);

    if (!result.ok) {
      console.error("Pipeline error:", result.traceback);
      setPhase("error", result.error);
      return;
    }

    const outBytes = pyodide.FS.readFile(result.outPath);
    state.lastOutputBlob = new Blob([outBytes], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    state.lastOutputName = result.outputFile;

    renderResults(result);
    setPhase("done");
  } catch (err) {
    console.error(err);
    setPhase("error", err.message || String(err));
  }
}

function renderResults(result) {
  $("kpi-peak").textContent = fmtUSD(result.kpis.peak);
  $("kpi-closing").textContent = fmtUSD(result.kpis.closing);
  $("kpi-div").textContent = fmtUSD(result.kpis.dividends);
  $("kpi-proceeds").textContent = fmtUSD(result.kpis.proceeds);
  $("kpi-ftc").textContent = fmtINR(result.kpis.ftcInr);
  $("kpi-accounts").textContent = String(result.kpis.accounts);

  $("score-summary").textContent = `${result.scoreSummary.passed} of ${result.scoreSummary.total} checks passed`;

  const list = $("scorecard-list");
  list.innerHTML = "";
  for (const row of result.scorecard) {
    const div = document.createElement("div");
    div.className = "score-row";
    const dotClass = row.status === "PASSED" ? "dot-success" : row.status === "FAILED" ? "dot-danger" : "dot-warning";
    div.innerHTML = `
      <div style="display:flex; align-items:center; gap:12px; min-width:0;">
        <span class="dot ${dotClass}" style="flex:none;"></span>
        <span style="font-size:13.5px;">${escapeHtml(row.title)}</span>
      </div>`;
    list.appendChild(div);
  }

  if (result.marketWarning) {
    const warnDiv = document.createElement("div");
    warnDiv.className = "score-row";
    warnDiv.innerHTML = `
      <div style="display:flex; align-items:center; gap:12px; min-width:0;">
        <span class="dot dot-warning" style="flex:none;"></span>
        <span style="font-size:13.5px;">${escapeHtml(result.marketWarning)} — peak/closing valuation may be incomplete</span>
      </div>`;
    list.appendChild(warnDiv);
  }

  $("download-filename").textContent = result.outputFile;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function downloadOutput() {
  if (!state.lastOutputBlob) return;
  const url = URL.createObjectURL(state.lastOutputBlob);
  const a = document.createElement("a");
  a.href = url;
  a.download = state.lastOutputName || "ITR_Schedules.xlsx";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function initFileInputs() {
  for (const slot of FILE_SLOTS) {
    const input = $(`input-${slot.key}`);
    input.addEventListener("change", () => {
      state.files[slot.key] = input.files[0] || null;
      updateFileCardUI(slot);
    });
    updateFileCardUI(slot);
  }
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fyToCalendarYear(fy) {
  // "2025-26" -> 2025. Mirrors itr_assist's fy_to_calendar_year() exactly.
  return parseInt(fy.split("-")[0], 10);
}

function updateFyGuidance() {
  const fy = state.fy;
  const cy = fyToCalendarYear(fy);
  const nextCy = cy + 1;

  $("range-stmtCy").textContent = `.pdf · Jan ${cy} – Dec ${cy}`;
  $("range-stmtFy").textContent = `.pdf · Jan ${nextCy} – Mar ${nextCy}`;
  $("range-taxDoc").textContent = `.pdf · IRS Form 1042-S for calendar year ${cy}`;

  $("fy-guidance-banner").innerHTML =
    `For <strong>FY ${fy}</strong>: give statements covering <strong>Jan ${cy} – Mar ${nextCy}</strong> ` +
    `(15 months total), and the Form 1042-S issued for calendar year ${cy}. ` +
    `Benefit History should be your full all-time export, not date-limited.`;
}

function initYearDropdown() {
  const trigger = $("year-trigger");
  const menu = $("year-menu");
  const label = $("year-trigger-label");
  const chevron = $("year-chevron");

  const setOpen = (open) => {
    menu.style.display = open ? "block" : "none";
    trigger.setAttribute("aria-expanded", String(open));
    chevron.style.transform = open ? "rotate(180deg)" : "rotate(0deg)";
  };

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    setOpen(menu.style.display === "none");
  });

  document.querySelectorAll(".year-opt").forEach((opt) => {
    opt.addEventListener("click", () => {
      state.fy = opt.dataset.fy;
      label.textContent = opt.textContent;
      document.querySelectorAll(".year-opt").forEach((o) => {
        const selected = o === opt;
        o.classList.toggle("is-selected", selected);
        o.setAttribute("aria-selected", String(selected));
      });
      setOpen(false);
      updateFyGuidance();
    });
  });

  document.addEventListener("click", (e) => {
    if (!trigger.contains(e.target) && !menu.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setOpen(false);
  });
}

function init() {
  initFileInputs();
  initYearDropdown();
  $("btn-generate").addEventListener("click", generate);
  $("btn-download").addEventListener("click", downloadOutput);
  updateFyGuidance();
  setPhase("idle");
}

document.addEventListener("DOMContentLoaded", init);
