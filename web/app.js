// ITR Assist — browser-side orchestration.
// All processing runs client-side via Pyodide: the user's documents never leave this tab.
// (The page itself does go online to download the Python runtime/packages and to fetch public
// exchange-rate / price data.)

const FILE_SLOTS = [
  // .xlsx only: the browser build reads spreadsheets with openpyxl, which can't open legacy .xls.
  { key: "benefit", accept: ".xlsx", cardId: "card-benefit", nameId: "name-benefit" },
  { key: "holdings", accept: ".xlsx", cardId: "card-holdings", nameId: "name-holdings" },
  { key: "stmtAll", accept: ".pdf", cardId: "card-stmtAll", nameId: "name-stmtAll", multi: true },
  { key: "taxDoc", accept: ".pdf", cardId: "card-taxDoc", nameId: "name-taxDoc" },
];

const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
const SBI_CSV_URL = "./data/cache/SBI_REFERENCE_RATES_USD.csv";
const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const RUNTIME_LOAD_MSG = "Couldn't load the Python runtime. Check your internet connection and try again.";

// An error whose message is meant to be shown to the user as-is. Technical detail goes to
// console.error (and `cause`), never into the UI.
class FriendlyError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "FriendlyError";
  }
}

const state = {
  files: {}, // key -> File (File[] for multi slots)
  phase: "idle", // idle | loading | counting | done | error
  pyodide: null,
  errorMessage: "",
  fy: null, // set from today's date in initYearDropdown()
  lastOutputBlob: null,
  lastOutputName: null,
};

// Twelve Data market-data key used for in-browser daily prices (Yahoo is CORS-blocked).
const MARKET_API_KEY = "5021dde7c95e432ebb8a264e8aca0cbe";

// Bumped on every input change. A run whose inputs changed while it was in flight discards
// its output instead of showing results that no longer match the form.
let inputsVersion = 0;

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

function slotHasFiles(slot) {
  const v = state.files[slot.key];
  return slot.multi ? Array.isArray(v) && v.length > 0 : !!v;
}

function filesReadyCount() {
  return FILE_SLOTS.filter(slotHasFiles).length;
}

function updateFileCardUI(slot) {
  const card = $(slot.cardId);
  const nameEl = $(slot.nameId);
  if (slot.multi) {
    const files = state.files[slot.key] || [];
    if (files.length > 0) {
      card.classList.add("file-filled");
      const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
      nameEl.textContent = files.length === 1
        ? `${files[0].name} · ${fmtBytes(totalBytes)}`
        : `${files.length} files · ${fmtBytes(totalBytes)}`;
      nameEl.title = files.map((f) => f.name).join("\n");
    } else {
      card.classList.remove("file-filled");
      nameEl.textContent = "No files selected";
      nameEl.title = "";
    }
    const chooseEl = $(`choose-${slot.key}`);
    if (chooseEl) chooseEl.textContent = files.length > 0 ? "Add more" : "Choose files";
  } else {
    const file = state.files[slot.key];
    if (file) {
      card.classList.add("file-filled");
      nameEl.textContent = `${file.name} · ${fmtBytes(file.size)}`;
      nameEl.title = file.name;
    } else {
      card.classList.remove("file-filled");
      nameEl.textContent = "No file selected";
      nameEl.title = "";
    }
  }
  $("ready-count").textContent = `${filesReadyCount()} of ${FILE_SLOTS.length} received`;
  refreshGenerateControls();
}

const isBusy = () => state.phase === "loading" || state.phase === "counting";

// PAN as the user means it: uppercase, no spaces/punctuation, at most 10 chars.
function normalizePan(v) {
  return String(v || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10);
}

// Blank is fine (auto-filled from Form 1042-S); anything else must be a well-formed PAN.
function panIsValid() {
  const v = normalizePan($("tp-pan").value);
  return v === "" || PAN_RE.test(v);
}

function showPanHint(show) {
  const input = $("tp-pan");
  $("pan-hint").style.display = show ? "block" : "none";
  input.classList.toggle("is-invalid", show);
  input.setAttribute("aria-invalid", String(show));
}

function idleStatusText() {
  const missing = FILE_SLOTS.length - filesReadyCount();
  if (missing > 0) return `Select all documents above — ${missing} still missing`;
  if (!panIsValid()) return "Fix the PAN format above to continue";
  return "All documents are in — processing happens right here in this tab";
}

function refreshGenerateControls() {
  $("btn-generate").disabled = isBusy() || filesReadyCount() < FILE_SLOTS.length;
  if (state.phase === "idle") $("status-text").textContent = idleStatusText();
}

// Drop everything derived from the previous run so a stale workbook can never be downloaded.
function clearResults() {
  state.lastOutputBlob = null;
  state.lastOutputName = null;
  $("scorecard-list").innerHTML = "";
  const attention = $("attention-box");
  attention.innerHTML = "";
  attention.style.display = "none";
  $("score-summary").textContent = "—";
  $("score-dot").className = "dot dot-warning";
  $("scorecard-count").textContent = "";
  $("download-filename").textContent = "ITR_Schedules.xlsx";
  $("btn-download").disabled = true;
  $("hero-closing-value").textContent = "—";
}

// Called whenever any input (files, filing year, name, PAN) changes.
function onInputsChanged() {
  inputsVersion++;
  if (state.phase === "done" || state.phase === "error") {
    clearResults();
    setPhase("idle");
  } else {
    refreshGenerateControls();
  }
}

function setPhase(phase, errorMessage) {
  state.phase = phase;
  state.errorMessage = errorMessage || "";
  const btn = $("btn-generate");

  $("error-box").style.display = phase === "error" ? "flex" : "none";
  $("error-text").textContent = phase === "error" ? state.errorMessage : "";

  // Results only ever describe a finished run for the current inputs.
  const done = phase === "done";
  $("results-wrap").style.display = done ? "block" : "none";
  $("scorecard-block").style.display = done ? "block" : "none";

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

  const statusByPhase = {
    loading: "Parsing Benefit History, Holdings, and statements…",
    counting: "Applying Rule 115 / Rule 128 conversions and FIFO lot matching…",
    done: "Generated just now · editing any input clears these results",
    error: "Generation failed — see details below",
  };
  if (phase !== "idle") $("status-text").textContent = statusByPhase[phase];
  refreshGenerateControls(); // button enabled-state + idle status text
}

async function readFileBytes(file) {
  try {
    return new Uint8Array(await file.arrayBuffer());
  } catch (err) {
    // Typically NotReadableError: the file was moved/edited on disk after it was picked.
    throw new FriendlyError(
      `Couldn't read "${file.name}" — it may have been moved or changed since you picked it. Pick it again and retry.`,
      { cause: err },
    );
  }
}

// Cached while pending and after success only; reset on failure so "Try again" really retries.
let pyodideReadyPromise = null;
// The interpreter itself, kept once loadPyodide() succeeds so a retry after a later step
// (package download, micropip, data fetch) doesn't spin up a second runtime.
let pyodideInstance = null;

// pyodide.js is loaded by a <script> tag in index.html; if the CDN was unreachable at page
// load, (re)inject it so a retry can recover without a page reload.
function ensurePyodideScript() {
  if (typeof globalThis.loadPyodide === "function") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = PYODIDE_INDEX_URL + "pyodide.js";
    s.onload = () => (typeof globalThis.loadPyodide === "function"
      ? resolve()
      : reject(new Error("pyodide.js loaded but loadPyodide() is not defined")));
    s.onerror = () => {
      s.remove();
      reject(new Error(`Failed to load ${s.src}`));
    };
    document.head.appendChild(s);
  });
}

function bootPyodide(onProgress) {
  if (!pyodideReadyPromise) {
    pyodideReadyPromise = initRuntime(onProgress).catch((err) => {
      pyodideReadyPromise = null;
      console.error("Python runtime failed to load:", err);
      throw err instanceof FriendlyError ? err : new FriendlyError(RUNTIME_LOAD_MSG, { cause: err });
    });
  }
  return pyodideReadyPromise;
}

async function initRuntime(onProgress) {
  if (!pyodideInstance) {
    onProgress("Loading Python runtime…");
    await ensurePyodideScript();
    pyodideInstance = await loadPyodide({ indexURL: PYODIDE_INDEX_URL });
  }
  const pyodide = pyodideInstance;

  onProgress("Loading pandas…");
  await pyodide.loadPackage(["pandas", "micropip"]);
  // loadPackage() may only log a failed download instead of rejecting - verify explicitly.
  await pyodide.runPythonAsync("import pandas, micropip");

  onProgress("Installing itr_assist and dependencies…");
  const micropip = pyodide.pyimport("micropip");
  // Exact pins for reproducible installs (every step below is a no-op on retry if satisfied).
  // - openpyxl / et-xmlfile / pypdf: pure-Python wheels from PyPI, same versions as the dev venv.
  //   et-xmlfile goes first, on its own, so openpyxl's unpinned dependency on it is already
  //   satisfied rather than racing the pin inside one transaction.
  // - jsonschema / referencing / pyodide-http: pinned to the builds bundled with Pyodide 0.26.2,
  //   so micropip takes them from the Pyodide lockfile. Newer jsonschema/referencing need a newer
  //   rpds-py, a native extension with no PyPI wasm wheel.
  await micropip.install("et-xmlfile==2.0.0");
  await micropip.install([
    "openpyxl==3.1.5",
    "pypdf==6.20.1",
    "jsonschema==4.21.1",
    "referencing==0.34.0",
    "pyodide-http==0.2.1",
  ]);
  await micropip.install("./dist/itr_assist-1.0.7-py3-none-any.whl");

  onProgress("Patching network calls for the browser…");
  await pyodide.runPythonAsync(`
import pyodide_http
pyodide_http.patch_all()
`);

  onProgress("Loading bundled exchange-rate data…");
  let sbiResp;
  try {
    sbiResp = await fetch(SBI_CSV_URL);
  } catch (err) {
    throw new FriendlyError(
      "Couldn't load the bundled SBI exchange-rate file. Check your internet connection and try again.",
      { cause: err },
    );
  }
  if (!sbiResp.ok) {
    throw new FriendlyError(
      `Couldn't load the bundled SBI exchange-rate file (HTTP ${sbiResp.status}). Reload the page and try again.`,
    );
  }
  const sbiBytes = new Uint8Array(await sbiResp.arrayBuffer());
  pyodide.FS.mkdirTree("/data/cache");
  pyodide.FS.writeFile("/data/cache/SBI_REFERENCE_RATES_USD.csv", sbiBytes);
  pyodide.FS.mkdirTree("/uploads");
  pyodide.FS.mkdirTree("/output");

  return pyodide;
}

// Mirrors cli.py's pipeline, adapted to read from the in-browser virtual filesystem
// instead of argparse paths. No change to itr_assist's own logic.
const PY_PIPELINE = `
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
`;

// Message for the error box: friendly text only; full detail is already in the console.
function userFacingError(err) {
  if (err instanceof FriendlyError) return err.message;
  if (err && err.name === "PythonError" && typeof err.message === "string") {
    // A Python traceback - show just its final "ExcType: message" line.
    const lines = err.message.trim().split("\n");
    return lines[lines.length - 1] || "Unexpected Python error";
  }
  return (err && err.message) || String(err);
}

async function generate() {
  if (isBusy()) return;

  // PAN: send it uppercased (CSS text-transform doesn't change the value) and block
  // generation on a malformed one instead of writing it into the workbook.
  const panEl = $("tp-pan");
  panEl.value = normalizePan(panEl.value);
  if (!panIsValid()) {
    showPanHint(true);
    panEl.focus();
    $("status-text").textContent = "Fix the PAN format above to continue";
    return;
  }

  const runVersion = inputsVersion;
  const inputsChanged = () => runVersion !== inputsVersion;
  clearResults();
  setPhase("loading");
  try {
    const pyodide = await bootPyodide((msg) => {
      if (isBusy()) $("status-text").textContent = msg;
    });

    // Remove statements left over from a previous run (which may have had more files).
    for (const name of pyodide.FS.readdir("/uploads")) {
      if (name.startsWith("stmt_")) pyodide.FS.unlink(`/uploads/${name}`);
    }

    const singleWrites = {
      benefit: "/uploads/benefit.xlsx",
      holdings: "/uploads/holdings.xlsx",
      taxDoc: "/uploads/taxdoc.pdf",
    };
    for (const [key, path] of Object.entries(singleWrites)) {
      const bytes = await readFileBytes(state.files[key]);
      pyodide.FS.writeFile(path, bytes);
    }

    // parse_statements() already accepts any number of files spanning any date range -
    // write every selected statement (the user's full account history, not just this FY)
    // and hand the combined list to Python.
    const stmtPaths = [];
    const stmtFiles = (state.files.stmtAll || []).slice();
    for (let i = 0; i < stmtFiles.length; i++) {
      const path = `/uploads/stmt_${i}.pdf`;
      const bytes = await readFileBytes(stmtFiles[i]);
      pyodide.FS.writeFile(path, bytes);
      stmtPaths.push(path);
    }

    setPhase("counting");
    const fy = state.fy;
    const taxpayerName = $("tp-name").value.trim();
    const pan = normalizePan($("tp-pan").value);
    // Hardcoded Twelve Data key (owner-approved, temporary until a keyless price source
    // is chosen). web/local.config.js can still override it locally.
    const marketApiKey = window.ITR_ASSIST_MARKET_API_KEY || MARKET_API_KEY;
    pyodide.globals.set("fy", fy);
    pyodide.globals.set("taxpayer_name", taxpayerName);
    pyodide.globals.set("pan", pan);
    pyodide.globals.set("details_json", JSON.stringify({
      account_open_date: $("d-open-date").value.trim(),
      broker_address: $("d-broker-address").value.trim(),
      broker_zip: $("d-broker-zip").value.trim(),
      company_name: $("d-company-name").value.trim(),
      company_address: $("d-company-address").value.trim(),
      company_zip: $("d-company-zip").value.trim(),
    }));
    pyodide.globals.set("stmt_paths_json", JSON.stringify(stmtPaths));
    pyodide.globals.set("market_api_key", marketApiKey);

    const resultJson = await pyodide.runPythonAsync(PY_PIPELINE);
    const result = JSON.parse(resultJson);

    if (inputsChanged()) {
      setPhase("idle");
      $("status-text").textContent = "Inputs changed while generating — generate again to use them";
      return;
    }

    if (!result.ok) {
      console.error("Pipeline error:", result.traceback);
      setPhase("error", result.error);
      return;
    }

    if (result.downloadAllowed) {
      const outBytes = pyodide.FS.readFile(result.outPath);
      state.lastOutputBlob = new Blob([outBytes], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      state.lastOutputName = result.outputFile;
    }

    renderResults(result);
    $("btn-download").disabled = !result.downloadAllowed;
    setPhase("done");
  } catch (err) {
    console.error(err);
    if (inputsChanged()) {
      setPhase("idle");
      $("status-text").textContent = "Inputs changed while generating — generate again to use them";
      return;
    }
    setPhase("error", userFacingError(err));
  }
}

// --- Results rendering -------------------------------------------------------------------

const ERROR_SEVERITY_RANK = { FATAL_SCHEMA: 0, DEFECTIVE_139_9: 1, STATUTORY_ERROR: 2 };

// "error" | "warning" | null (nothing to flag). INFO rows are never flagged or counted.
function rowAttention(row) {
  if (row.severity === "INFO" || row.status === "PASSED") return null;
  if (row.status === "FAILED" && row.severity !== "AUDIT_WARNING") return "error";
  return "warning"; // FAILED audit warnings, WARNING-status rows
}

function rowDotClass(row) {
  if (row.status === "PASSED") return "dot-success";
  const a = rowAttention(row);
  return a === "error" ? "dot-danger" : a === "warning" ? "dot-warning" : "dot-muted";
}

const CALLOUT_ICON =
  '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

function renderAttention(errorRows, warningRows, notes) {
  const box = $("attention-box");
  box.innerHTML = "";
  const groups = [];
  if (errorRows.length) {
    groups.push({
      cls: "callout-danger",
      heading: `Fix before filing (${errorRows.length})`,
      items: errorRows.map((r) => ({ title: r.title, details: r.details })),
    });
  }
  const warnItems = warningRows
    .map((r) => ({ title: r.title, details: r.details }))
    .concat(notes.map((n) => ({ title: n, details: "" })));
  if (warnItems.length) {
    groups.push({ cls: "callout-warning", heading: `Review before filing (${warnItems.length})`, items: warnItems });
  }
  for (const g of groups) {
    const el = document.createElement("div");
    el.className = `callout ${g.cls}`;
    const items = g.items.map((it) =>
      `<li><div class="callout-title">${escapeHtml(it.title)}</div>` +
      (it.details ? `<div class="callout-details">${escapeHtml(it.details)}</div>` : "") +
      `</li>`).join("");
    el.innerHTML = `<div class="callout-head">${CALLOUT_ICON}<span>${escapeHtml(g.heading)}</span></div>` +
      `<ul class="callout-list">${items}</ul>`;
    box.appendChild(el);
  }
  box.style.display = groups.length ? "block" : "none";
}

function renderResults(result) {
  const closing = result.kpis ? result.kpis.closing : null;
  $("hero-closing-value").textContent =
    closing != null && Number.isFinite(Number(closing)) ? fmtUSD(closing) : "—";

  const rows = Array.isArray(result.scorecard) ? result.scorecard : [];
  const errorRows = rows
    .filter((r) => rowAttention(r) === "error")
    .sort((a, b) => (ERROR_SEVERITY_RANK[a.severity] ?? 3) - (ERROR_SEVERITY_RANK[b.severity] ?? 3));
  const warningRows = rows.filter((r) => rowAttention(r) === "warning");
  const notes = [...new Set(
    (Array.isArray(result.warnings) ? result.warnings : [])
      .concat(result.marketWarning ? [result.marketWarning] : [])
      .filter(Boolean)
      .map(String),
  )];
  renderAttention(errorRows, warningRows, notes);

  // Summary pill: driven by what's flagged, escalated by the engine's overall status.
  const needs = errorRows.length + warningRows.length + notes.length;
  const status = result.scoreSummary ? result.scoreSummary.status : "";
  let tone = errorRows.length ? "danger" : needs ? "warning" : "success";
  if (status === "PORTAL_REJECTION_RISK" || status === "DEFECTIVE_OR_NON_COMPLIANT") tone = "danger";
  else if (tone === "success" && status === "FILING_READY_WITH_WARNINGS") tone = "warning";
  const STATUS_LABEL = {
    FILING_READY_WITH_WARNINGS: "Filing-ready, with warnings",
    DEFECTIVE_OR_NON_COMPLIANT: "Defective / non-compliant",
    PORTAL_REJECTION_RISK: "Portal rejection risk",
  };
  $("score-summary").textContent = needs > 0
    ? `${needs} need${needs === 1 ? "s" : ""} attention`
    : tone === "success" ? "All checks passed" : (STATUS_LABEL[status] || "Review the scorecard");
  $("score-dot").className = `dot dot-${tone}`;

  // Full list (collapsed by default): every row, details on a second line.
  const counted = rows.filter((r) => r.severity !== "INFO");
  const passed = counted.filter((r) => r.status === "PASSED").length;
  $("scorecard-count").textContent = counted.length ? `${passed} of ${counted.length} passed · ` : "";

  const list = $("scorecard-list");
  list.innerHTML = "";
  const addRow = (dotClass, title, details) => {
    const div = document.createElement("div");
    div.className = "score-row";
    div.innerHTML = `
      <div class="score-line">
        <span class="dot ${dotClass}"></span>
        <div style="min-width:0;">
          <div style="font-size:13.5px;">${escapeHtml(title)}</div>
          ${details ? `<div class="score-details">${escapeHtml(details)}</div>` : ""}
        </div>
      </div>`;
    list.appendChild(div);
  };
  for (const row of rows) addRow(rowDotClass(row), row.title, row.details);
  for (const note of notes) addRow("dot-warning", note, "");

  $("download-filename").textContent = result.outputFile || "ITR_Schedules.xlsx";
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function downloadOutput() {
  if (!state.lastOutputBlob || state.phase !== "done") return;
  const url = URL.createObjectURL(state.lastOutputBlob);
  const a = document.createElement("a");
  a.href = url;
  a.download = state.lastOutputName || "ITR_Schedules.xlsx";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const fileKey = (f) => `${f.name}|${f.size}|${f.lastModified}`;

function initFileInputs() {
  for (const slot of FILE_SLOTS) {
    const input = $(`input-${slot.key}`);
    input.addEventListener("change", () => {
      const picked = Array.from(input.files || []);
      // Reset so re-picking the same file(s) fires "change" again.
      input.value = "";
      if (picked.length === 0) return; // dialog cancelled: keep the current selection

      let changed;
      if (slot.multi) {
        // Accumulate across picker opens: statements usually sit in one folder per FY, and a
        // file dialog can only select from one folder at a time.
        const existing = state.files[slot.key] || [];
        const seen = new Set(existing.map(fileKey));
        const added = picked.filter((f) => {
          const k = fileKey(f);
          if (seen.has(k)) return false;
          seen.add(k);
          return true;
        });
        changed = added.length > 0;
        if (changed) state.files[slot.key] = existing.concat(added);
      } else {
        state.files[slot.key] = picked[0];
        changed = true;
      }
      updateFileCardUI(slot);
      if (changed) onInputsChanged();
    });
    updateFileCardUI(slot);
  }

  const clearStatements = $("btn-clear-stmtAll");
  if (clearStatements) {
    clearStatements.addEventListener("click", (e) => {
      // The button lives inside the card's <label>: don't let the click open the file picker.
      e.preventDefault();
      e.stopPropagation();
      const slot = FILE_SLOTS.find((s) => s.key === "stmtAll");
      if (!slotHasFiles(slot)) return;
      state.files.stmtAll = [];
      $("input-stmtAll").value = "";
      updateFileCardUI(slot);
      onInputsChanged();
    });
  }
}

function initTaxpayerInputs() {
  const pan = $("tp-pan");
  const sanitizePan = () => {
    const raw = pan.value;
    const next = normalizePan(raw);
    if (next === raw) return;
    const caret = pan.selectionStart == null ? raw.length : pan.selectionStart;
    const pos = Math.min(normalizePan(raw.slice(0, caret)).length, next.length);
    pan.value = next;
    try {
      pan.setSelectionRange(pos, pos);
    } catch (_) { /* not focused / unsupported - harmless */ }
  };
  sanitizePan(); // browser form-restore may bring back a lowercase value

  pan.addEventListener("input", () => {
    sanitizePan();
    // Hide the hint as soon as the value is valid; only raise it once a full 10 characters
    // are in (or it's already showing) so it doesn't nag mid-typing.
    if (panIsValid()) showPanHint(false);
    else if (pan.value.length === 10 || $("pan-hint").style.display !== "none") showPanHint(true);
    onInputsChanged();
  });
  pan.addEventListener("blur", () => {
    if (!panIsValid()) showPanHint(true);
  });

  $("tp-name").addEventListener("input", onInputsChanged);
  for (const id of ["d-open-date", "d-broker-address", "d-broker-zip", "d-company-name", "d-company-address", "d-company-zip"]) {
    $(id).addEventListener("input", onInputsChanged);
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

  $("range-stmtAll").textContent = `.pdf · Account-open through Mar ${nextCy}`;
  $("range-taxDoc").textContent = `.pdf · IRS Form 1042-S for calendar year ${cy}`;

  $("fy-guidance-banner").innerHTML =
    `For <strong>FY ${fy}</strong>: upload <strong>every statement PDF you have, from when your account was first opened through Mar ${nextCy}</strong> — ` +
    `not just the months inside this FY. Schedule FA needs your complete sale history to correctly ` +
    `work out which lots from earlier years are already sold, not just the ones sold during ${fy}. ` +
    `Also give the Form 1042-S issued for calendar year ${cy}. ` +
    `Benefit History should be your full all-time export, not date-limited.`;
}

const yy = (n) => String(n % 100).padStart(2, "0");
const fyKey = (start) => `${start}-${yy(start + 1)}`;
const fyLabel = (start) => `FY ${start}-${yy(start + 1)} · AY ${start + 1}-${yy(start + 2)}`;

// Filing years derived from today's date, never a hardcoded list. Only completed FYs are
// selectable because an in-progress year cannot have complete statements or closing values.
function filingYearChoices(today = new Date()) {
  const latest = today.getMonth() >= 3 ? today.getFullYear() - 1 : today.getFullYear() - 2;
  return { latest, starts: [latest, latest - 1, latest - 2, latest - 3, latest - 4] };
}

function initYearDropdown() {
  const trigger = $("year-trigger");
  const menu = $("year-menu");
  const label = $("year-trigger-label");
  const chevron = $("year-chevron");

  const { latest, starts } = filingYearChoices();
  for (const start of starts) {
    const opt = document.createElement("button");
    opt.type = "button";
    opt.className = "year-opt";
    opt.setAttribute("role", "option");
    opt.dataset.fy = fyKey(start);
    opt.textContent = fyLabel(start);
    const selected = start === latest;
    opt.classList.toggle("is-selected", selected);
    opt.setAttribute("aria-selected", String(selected));
    menu.appendChild(opt);
  }
  state.fy = fyKey(latest);
  label.textContent = fyLabel(latest);

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
      onInputsChanged();
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
  initTaxpayerInputs();
  initYearDropdown();
  $("btn-generate").addEventListener("click", generate);
  $("btn-download").addEventListener("click", downloadOutput);
  updateFyGuidance();
  setPhase("idle");
}

document.addEventListener("DOMContentLoaded", init);
