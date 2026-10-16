# ITR Assist: Foreign Assets & Tax Relief Automation (ITR-2)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Statutory Rules: AY 2026-27](https://img.shields.io/badge/CBDT-AY%202026--27%20V1.2-green.svg)](https://www.incometax.gov.in/)
[![Deploy GitHub Pages](https://github.com/VaderBV/ITR-Assist/actions/workflows/pages.yml/badge.svg)](https://github.com/VaderBV/ITR-Assist/actions/workflows/pages.yml)

**ITR Assist** is an open-source, privacy-first automation utility designed for Indian residents holding foreign company shares (RSUs, ESPPs, direct stock) via US brokerages (such as E*TRADE / Morgan Stanley, Fidelity, Schwab).

It ingests standard broker exports (PDF account statements, Excel benefit histories, and IRS Form 1042-S), reconstructs the taxpayer's complete share lot lifecycle, applies mandatory Indian statutory exchange rates (Rule 115 & Rule 128), and generates a multi-sheet, scrutiny-ready Excel working paper with a 100% compliant statutory audit scorecard.

![ITR Assist web app](docs/screenshot.jpg)

---

## 🔒 Strict Data Privacy Guarantee

> **Your uploaded financial documents are processed locally in your browser or on your machine.**

* **Zero Telemetry / Analytics:** There is no tracking, analytics, or application telemetry.
* **No Embedded PII or User Profiles:** No personal data (PAN, taxpayer name, account numbers, employer details) is hardcoded or stored in configuration files.
* **In-Memory Dynamic Extraction:** The utility dynamically reads taxpayer details directly from your broker tax documents (IRS Form 1042-S) and account statements during execution and places them solely into the final generated local workbook.
* **Public Network Requests:** The hosted app downloads Pyodide and its public Python dependencies, and it requests public exchange-rate and market-price data. The browser market-data key is sent only to the configured market-data provider. Uploaded broker documents, extracted taxpayer data, and generated workbooks are never included in those requests.
* **Public Reference Data Only:**
  * **SBI TT Buying Rates:** The tool can sync historical State Bank of India reference rates from the public [SBI FX Ratekeeper Archive](https://github.com/sahilgupta/sbi-fx-ratekeeper) and falls back to the bundled/cache snapshot if offline.
  * **Stock Closing Prices:** Verified peak and closing market valuations are fetched from Yahoo Finance or Twelve Data and cached locally.

---

## 📑 Schedules & Tax Forms Handled

| Schedule / Form | Description & Statutory Grounding |
| :--- | :--- |
| **Schedule FA (Table A2)** | Foreign Custodial Broker Accounts. Reports calendar year peak custodial balance, closing balance, gross foreign dividends, and interest credited using exact date SBI TT Buying Rates. |
| **Schedule FA (Table A3)** | Foreign Equity & Debt Interest. Detailed tranche-level breakdown for every historical RSU vest and ESPP purchase active during the calendar year. Computes initial investment cost, peak market valuation, closing value, and lot-level dividends. |
| **Sold Lot Detection** | Detects lots held at any point during the calendar year that were subsequently sold (0 sellable shares at year-end). Strictly mandates disclosure under the Black Money (Undisclosed Foreign Income and Assets) and Imposition of Tax Act, 2015. |
| **Schedule OS** | Foreign Dividend Income converted to INR under **Rule 115, Explanation clause (e)** (TT Buying Rate of the last day of the month preceding the payment month). Automatically broken down into the 5 statutory advance tax instalment quarters. |
| **Schedule FSI & TR** | Foreign Source Income and Tax Relief claims under **Section 90** and **Article 10 (Dividends)** of the Indo-US Double Taxation Avoidance Agreement (DTAA). |
| **Form 67 Working** | Complete working computation for Form 67 (Statement of Foreign Tax Credit) under **Rule 128(5)(ii)** (TT Buying Rate of the last day of the month preceding the month tax was paid/deducted - not the deduction date itself) with Section 90 DTAA rate caps. |
| **SBI TTBR Register** | A dedicated statutory rate register documenting the date, purpose, rule citation, and official SBI TT Buying Rate for every transaction. |
| **Scrutiny Audit Trails** | 15-month continuous portfolio progression, pro-rata dividend allocations per lot, and EOD closing price proofs. |
| **Statutory Scorecard** | Automated 57-rule validation against official CBDT JSON Schema (`ITR-2_2026_Main_V1.2.json`), CBDT Systems PDF rules, and IT Rules 115/128/90. |

---

## 🚀 Quick Start

### Option A: Web App (Recommended — No Install)

Open **[the live app](https://vaderbv.github.io/ITR-Assist/)** directly in your browser. Nothing to clone, install, or run — the entire tool (including the Python engine) runs client-side via [Pyodide](https://pyodide.org/), and your documents never leave the tab. Upload your broker documents, pick your filing year, and click **Generate Schedules**.

Prefer to run it locally instead of the hosted link? Clone the repo, then serve the `web/` folder as a static site (it must be served over `http://`, not opened as a local `file://` path — the browser blocks the fetches that path needs):

```bash
git clone https://github.com/VaderBV/ITR-Assist.git
cd ITR-Assist/web
python -m http.server 8743
# then open http://127.0.0.1:8743/
```

**Verified market data is required:** Yahoo Finance cannot be reached directly from a browser (no CORS support), and Schedule FA peak/closing values are not safely approximated. Get a free API key from [twelvedata.com](https://twelvedata.com) (no credit card) and enter it in the app. Generation stops rather than producing an unverifiable workbook when daily prices are unavailable.

For local use, you can prefill the field by creating `web/local.config.js`:

```js
window.ITR_ASSIST_MARKET_API_KEY = "your-key-here";
```

This file is git-ignored — it stays on your machine and is never committed or uploaded anywhere.

#### GitHub Pages deployment

The repository includes `.github/workflows/pages.yml`, which publishes the contents of `web/` whenever a change to the site reaches `main`. In the repository settings, select **Settings → Pages → Source → GitHub Actions** once; subsequent deployments are automatic. The workflow can also be run manually from the Actions tab.

### Option B: Desktop GUI / CLI (Python)

### 1. Installation

Ensure you have **Python 3.10+** installed:

```bash
# Clone the repository
git clone https://github.com/<your-username>/itr-assist.git
cd itr-assist

# Create and activate virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e .
```

---

### 2. Desktop GUI Application

Run the intuitive desktop interface:

```bash
itr-assist-gui
# OR: python -m itr_assist.gui
```

#### GUI Highlights:
* **Filing Year Discovery:** Automatically queries the official Income Tax e-Filing portal downloads directory in the background to discover and present all open Assessment Years (AY 2026-27, AY 2025-26, AY 2024-25) in strictly descending order.
* **Individual File Selectors:** Browse and select each broker statement, benefit history, and tax document independently.
* **Auto-Extraction:** Taxpayer Name and PAN are auto-extracted from Form 1042-S upon ingestion.
* **Interactive Results:** Inspect live KPIs, Table A3 lots, and quarterly Schedule OS dividends directly within the application.

---

### 3. Command Line Interface (CLI)

Run headlessly or automate via CLI:

```bash
itr-assist \
  --benefit-file data/BenefitHistory.xlsx \
  --holdings-file data/ByStatus_expanded.xlsx \
  --stmt-cy data/ClientStatements_2025.pdf \
  --stmt-fy data/ClientStatements_Jan-March26.pdf \
  --tax-doc data/TaxDocuments_1042S.pdf \
  --ay 2026-27 \
  --fy 2025-26 \
  --output ITR2_Foreign_Assets_Working_AY2026-27.xlsx
```

---

## 📂 Required Broker Documents

Place your files in a local directory (e.g. `Data/`). These files are ignored by git to protect your privacy:

1. **Benefit History Spreadsheet (`BenefitHistory.xlsx`):**
   * Exported from your broker (e.g., E*TRADE *My Account > Stock Plans > Benefit History*).
   * Contains the `ESPP` and `Restricted Stock` sheets detailing all historical grant dates, vest dates, quantities, and taxable fair market values.
2. **Current Holdings Snapshot (`ByStatus_expanded.xlsx`):**
   * Exported from your broker (e.g., E*TRADE *Holdings > View By Status > Expand All > Export*).
   * Used to reconcile reconstructed active shares and detect sold lots.
3. **Calendar Year Statements (`ClientStatements_2025.pdf`):**
   * Monthly PDF statement export covering January to December of the calendar year (2025).
4. **Q4 / FY-End Statements (`ClientStatements_Jan-March26.pdf`):**
   * Account statements covering January to March of the following year (2026) to complete the continuous 15-month Indian Financial Year window (FY 2025-26).
5. **Form 1042-S Tax Document (`TaxDocuments_1042S.pdf`):**
   * IRS Form 1042-S issued by the US withholding agent showing Box 2 (Gross Income) and Box 7a (Federal Tax Withheld).

> ⚠️ **If you've ever sold shares in a prior financial year, feed in every statement since your account was opened, not just the current filing year's 15-month window.** This is not optional for correctness: a lot fully sold in an earlier year, if that year's statement is never supplied, has no sale event for the engine to find, so its disposal date never gets set and it is incorrectly treated as still active — **inflating Schedule FA Table A3's peak/closing balances for the current filing year itself**, not just tripping the holdings-reconciliation sanity check. **The web app's "All Broker Statements" picker already supports selecting any number of files at once; the CLI's `--stmt-cy`/`--stmt-fy` currently each take exactly one file**, so CLI users need to merge their PDFs into one file per flag first (e.g. with any PDF-merge tool) until the CLI is updated to accept multiple paths too.

---

## ⚖️ Statutory Grounding & Rules Engine

ITR Assist features a built-in statutory rules engine enforcing Indian tax laws:

* **Rule 115, Explanation clause (e) — Dividend Rate Timing:** Dividends received in foreign currency must be converted to INR using the SBI TT Buying Rate of the **last day of the month immediately preceding the month of dividend receipt**. Clause (f) applies the same mechanism to capital gains/sale proceeds on transfer of a foreign asset.
* **Rule 128(5)(ii) Rate Timing:** Foreign tax credit claimed under Section 90 must be converted using the SBI TT Buying Rate of the **last day of the month immediately preceding the month in which the foreign tax was paid or deducted** — not the deduction date itself, a distinction verified word-for-word against the official rule text.
* **Section 90 DTAA Article 10 Cap:** Maximum foreign tax credit claimable on foreign dividends under the Indo-US treaty is capped at 25% (or treaty rate), preventing defective return notices under Section 139(9).
* **Section 288A & 288B Rounding:** Total income and tax amounts rounded to the nearest integer rupee or multiple of ₹10 as statutorily mandated.
* **Peak Valuation Standard:** Peak market values for Schedule FA Table A3 are established using End-of-Day (EOD) closing prices under official CBDT guidance.
* **CBDT Schema Conformance:** Direct programmatic validation against the official CBDT e-Filing JSON Schema (`ITR-2_2026_Main_V1.2.json`).

---

## 🧪 Testing

The repository includes a comprehensive synthetic test suite that runs without needing any private user documents:

```bash
# Run the entire test suite
pytest -v
```

The test suite validates:
* Chronological lot ledger reconstruction & sold lot detection.
* Pro-rata dividend allocation across tranches.
* Offline SBI rate caching and weekend/holiday rollbacks.
* Parser and adapter extraction across broker formats.
* Automated broker detection (`BrokerParserFactory.auto_detect`).
* End-to-end multi-sheet Excel generation and formula accuracy.
* 100% compliance across all 57 statutory and CBDT schema validation rules.

---

## 🤝 Contributing

Contributions are welcome! If you would like to add an adapter for another broker (e.g., Charles Schwab, Fidelity NetBenefits, Zerodha Global, Interactive Brokers), check out `itr_assist/parsers/base.py` and submit a Pull Request.

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

---

## ⚠️ Disclaimer

*This software is an independent open-source automation utility and is not affiliated with the Income Tax Department of India, State Bank of India, E\*TRADE, Morgan Stanley, or the IRS. It is designed to assist taxpayers in compiling and reconciling their filings. Always verify your final calculations with a certified Chartered Accountant or tax professional before submitting your return.*
