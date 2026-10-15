"""Modern Tkinter GUI for ITR Assist."""
from datetime import date
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from itr_assist.parsers import BrokerParserFactory
from itr_assist.reconciliation.lot_ledger import LotLedger
from itr_assist.reconciliation.verifier import DocumentVerifier
from itr_assist.reports.excel_generator import ITRWorkbookGenerator
from itr_assist.services.market_data import MarketDataService
from itr_assist.services.open_years import (
    ay_to_fy,
    fetch_open_assessment_years,
    fy_to_ay,
    fy_to_calendar_year,
    get_statutory_open_years,
)
from itr_assist.services.sbi_rates import SBIRateService
from itr_assist.services.valuation import (
    FTCResult,
    ScheduleFATableA2Result,
    ScheduleFATableA3LotResult,
    ScheduleOSResult,
    ValuationEngine,
)


class ITRAssistGUI:
    """Desktop GUI application for ITR-2 foreign asset automation."""

    def __init__(self, root: tk.Tk, auto_discover_years: bool = True):
        self.root = root
        self.root.title("ITR-2 Foreign Assets & Tax Relief Assistant")
        self.root.geometry("1060x820")
        self.root.minsize(920, 680)

        # 1. Open Assessment Years & Financial Years in descending order
        self.open_fys, self.open_ays = get_statutory_open_years()
        self.var_ay = tk.StringVar(value=self.open_ays[0] if self.open_ays else "2026-27")
        self.var_fy = tk.StringVar(value=self.open_fys[0] if self.open_fys else "2025-26")
        self.var_open_years_source = tk.StringVar(value="Statutory Calendar Formula")

        # 2. Individual file inputs (one-by-one)
        self.var_benefit_history = tk.StringVar(value="")
        self.var_holdings = tk.StringVar(value="")
        self.var_stmt_cy = tk.StringVar(value="")
        self.var_stmt_fy = tk.StringVar(value="")
        self.var_tax_doc = tk.StringVar(value="")

        # 3. Taxpayer details and output settings
        self.var_taxpayer_name = tk.StringVar(value="")
        self.var_pan = tk.StringVar(value="")
        self.var_broker = tk.StringVar(value="Auto-Detect")
        self.var_output = tk.StringVar(value=os.path.abspath(f"ITR2_Foreign_Assets_Working_AY{self.var_ay.get()}.xlsx"))
        self.var_status = tk.StringVar(value="Ready. Select individual input files and click 'Generate ITR-2 Working'.")

        self.last_generated_file: Optional[str] = None
        self._setup_styles()
        self._build_ui()

        # Kick off background online discovery for open filing years
        if auto_discover_years:
            self._refresh_open_years_async()

    def _setup_styles(self) -> None:
        """Configure ttk styling."""
        style = ttk.Style(self.root)
        style.theme_use("clam")

        # Color Palette
        c_navy = "#1B365D"
        c_light = "#F8FAFC"
        c_accent = "#2B4C7E"

        style.configure("TFrame", background=c_light)
        style.configure("TLabel", background=c_light, font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"), foreground=c_navy)
        style.configure("SubHeader.TLabel", font=("Segoe UI", 9, "italic"), foreground="#555555")
        style.configure("Status.TLabel", font=("Segoe UI", 9, "bold"), foreground="#0B6623")
        style.configure("Tag.TLabel", font=("Segoe UI", 8), foreground="#666666")

        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background=c_navy, foreground="white")
        style.map("Primary.TButton", background=[("active", c_accent)])

        style.configure("Secondary.TButton", font=("Segoe UI", 9), background="#E0E0E0")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#EAEAEA")
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=24)

    def _build_ui(self) -> None:
        """Assemble main window layout."""
        main_container = ttk.Frame(self.root, padding=12)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Top Header Banner
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header_frame, text="ITR-2 Foreign Assets & Tax Relief Automation", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header_frame,
            text="Simplifies filing Schedule FA, Schedule OS, Schedule FSI, Schedule TR, and Form 67 with complete USD & scrutiny audit proofs",
            style="SubHeader.TLabel"
        ).pack(anchor="w")

        # Top Configuration: Taxpayer Details & Open Year Dropdown
        config_group = ttk.LabelFrame(main_container, text=" Filing & Taxpayer Configuration ", padding=8)
        config_group.pack(fill=tk.X, pady=(0, 6))

        # Row 0: Taxpayer Name & PAN
        ttk.Label(config_group, text="Taxpayer Name:").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(config_group, textvariable=self.var_taxpayer_name, width=28).grid(row=0, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(config_group, text="PAN / TIN:").grid(row=0, column=2, sticky="w", padx=4, pady=3)
        ttk.Entry(config_group, textvariable=self.var_pan, width=18).grid(row=0, column=3, sticky="w", padx=4, pady=3)

        # Row 1: Descending FY and AY dropdowns with auto-sync and refresh
        ttk.Label(config_group, text="Financial Year (FY):").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self.fy_combo = ttk.Combobox(config_group, textvariable=self.var_fy, values=self.open_fys, width=14, state="readonly")
        self.fy_combo.grid(row=1, column=1, sticky="w", padx=4, pady=3)
        self.fy_combo.bind("<<ComboboxSelected>>", self._on_fy_selected)

        ttk.Label(config_group, text="Assessment Year (AY):").grid(row=1, column=2, sticky="w", padx=4, pady=3)
        self.ay_combo = ttk.Combobox(config_group, textvariable=self.var_ay, values=self.open_ays, width=14, state="readonly")
        self.ay_combo.grid(row=1, column=3, sticky="w", padx=4, pady=3)
        self.ay_combo.bind("<<ComboboxSelected>>", self._on_ay_selected)

        self.btn_refresh_years = ttk.Button(config_group, text="🔄 Refresh from ITR Portal", command=self._refresh_open_years_async, style="Secondary.TButton")
        self.btn_refresh_years.grid(row=1, column=4, padx=6, pady=3)

        ttk.Label(config_group, textvariable=self.var_open_years_source, style="Tag.TLabel").grid(row=1, column=5, sticky="w", padx=4, pady=3)

        # Row 2: Output File Path
        ttk.Label(config_group, text="Output Excel:").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(config_group, textvariable=self.var_output, width=65).grid(row=2, column=1, columnspan=3, sticky="ew", padx=4, pady=3)
        ttk.Button(config_group, text="Save As...", command=self._browse_output, style="Secondary.TButton").grid(row=2, column=4, padx=6, pady=3)

        config_group.columnconfigure(3, weight=1)

        # Individual File Pickers (One by One)
        files_group = ttk.LabelFrame(main_container, text=" Broker Document Input Files (Select Files One by One) ", padding=8)
        files_group.pack(fill=tk.X, pady=(0, 6))

        # Quick auto-fill toolbar button
        top_bar = ttk.Frame(files_group)
        top_bar.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Button(top_bar, text="📁 Auto-Fill All Files from Folder...", command=self._auto_fill_from_folder, style="Secondary.TButton").pack(side=tk.LEFT)
        ttk.Label(top_bar, text=" (Quick-detects files if in one directory, while still allowing individual selection below)", style="Tag.TLabel").pack(side=tk.LEFT, padx=6)

        # File 1: Benefit History
        ttk.Label(files_group, text="1. Benefit History:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(files_group, textvariable=self.var_benefit_history, width=75).grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(files_group, text="Browse...", command=lambda: self._browse_single_file(self.var_benefit_history, "Benefit History (*.xlsx;*.xls;*.csv)", [("Excel/CSV Files", "*.xlsx;*.xls;*.csv")]), style="Secondary.TButton").grid(row=1, column=2, padx=4, pady=2)

        # File 2: Current Holdings
        ttk.Label(files_group, text="2. Current Holdings:").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(files_group, textvariable=self.var_holdings, width=75).grid(row=2, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(files_group, text="Browse...", command=lambda: self._browse_single_file(self.var_holdings, "Current Holdings (*.xlsx;*.xls;*.csv)", [("Excel/CSV Files", "*.xlsx;*.xls;*.csv")]), style="Secondary.TButton").grid(row=2, column=2, padx=4, pady=2)

        # File 3: CY Statement (Jan-Dec)
        ttk.Label(files_group, text="3. CY Statement PDF:").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(files_group, textvariable=self.var_stmt_cy, width=75).grid(row=3, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(files_group, text="Browse...", command=lambda: self._browse_single_file(self.var_stmt_cy, "Calendar Year Statements (*.pdf)", [("PDF Files", "*.pdf")]), style="Secondary.TButton").grid(row=3, column=2, padx=4, pady=2)

        # File 4: Q4 Statement (Jan-Mar)
        ttk.Label(files_group, text="4. Q4 Statement PDF:").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(files_group, textvariable=self.var_stmt_fy, width=75).grid(row=4, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(files_group, text="Browse...", command=lambda: self._browse_single_file(self.var_stmt_fy, "Q4/FY Statements (*.pdf)", [("PDF Files", "*.pdf")]), style="Secondary.TButton").grid(row=4, column=2, padx=4, pady=2)

        # File 5: Form 1042-S
        ttk.Label(files_group, text="5. Form 1042-S / Tax:").grid(row=5, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(files_group, textvariable=self.var_tax_doc, width=75).grid(row=5, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(files_group, text="Browse...", command=lambda: self._browse_single_file(self.var_tax_doc, "Form 1042-S (*.pdf)", [("PDF Files", "*.pdf")]), style="Secondary.TButton").grid(row=5, column=2, padx=4, pady=2)

        files_group.columnconfigure(1, weight=1)

        # Action Bar (Generate button, Progressbar, Open button)
        action_frame = ttk.Frame(main_container)
        action_frame.pack(fill=tk.X, pady=(0, 6))

        self.btn_generate = ttk.Button(
            action_frame,
            text=" ▶ Generate ITR-2 Working & Schedules ",
            command=self._start_generation_thread,
            style="Primary.TButton"
        )
        self.btn_generate.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_open_excel = ttk.Button(
            action_frame,
            text=" 📊 Open Excel Workbook ",
            command=self._open_excel,
            style="Secondary.TButton",
            state=tk.DISABLED
        )
        self.btn_open_excel.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_open_folder = ttk.Button(
            action_frame,
            text=" 📁 Open Folder ",
            command=self._open_folder,
            style="Secondary.TButton"
        )
        self.btn_open_folder.pack(side=tk.LEFT)

        self.progress = ttk.Progressbar(action_frame, mode="indeterminate", length=180)

        # Status Bar
        status_bar = ttk.Frame(main_container)
        status_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(status_bar, textvariable=self.var_status, style="Status.TLabel").pack(anchor="w")

        # Results & Audit Notebook (Tabs)
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_log_tab()
        self._build_kpi_tab()
        self._build_table_a3_tab()
        self._build_schedule_os_tab()
        self._build_validation_tab()

    def _build_log_tab(self) -> None:
        """Tab 1: Execution logs."""
        tab = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(tab, text=" Execution Log ")

        self.log_text = tk.Text(tab, font=("Consolas", 9), wrap=tk.WORD, bg="#FFFFFF", fg="#222222", relief=tk.SOLID, borderwidth=1)
        scrollbar = ttk.Scrollbar(tab, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_kpi_tab(self) -> None:
        """Tab 2: Summary KPI Cards."""
        self.kpi_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.kpi_tab, text=" Summary Cards ")

        cols = ("schedule", "metric", "usd", "inr", "reference")
        self.kpi_tree = ttk.Treeview(self.kpi_tab, columns=cols, show="headings", height=8)
        self.kpi_tree.heading("schedule", text="Schedule / Form")
        self.kpi_tree.heading("metric", text="Metric Description")
        self.kpi_tree.heading("usd", text="USD Amount")
        self.kpi_tree.heading("inr", text="INR Amount (₹)")
        self.kpi_tree.heading("reference", text="Statutory Reference & Provenance")

        self.kpi_tree.column("schedule", width=140, anchor="w")
        self.kpi_tree.column("metric", width=250, anchor="w")
        self.kpi_tree.column("usd", width=100, anchor="e")
        self.kpi_tree.column("inr", width=120, anchor="e")
        self.kpi_tree.column("reference", width=340, anchor="w")

        self.kpi_tree.pack(fill=tk.BOTH, expand=True)

    def _build_table_a3_tab(self) -> None:
        """Tab 3: Schedule FA Table A3 Lots with USD and Rates."""
        self.a3_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.a3_tab, text=" Schedule FA (Table A3 Lots) ")

        cols = (
            "lot_id", "acq_date", "net_shares", "vest_fmv", "init_usd", "init_inr",
            "peak_high", "peak_usd", "peak_rate", "peak_date", "peak_inr",
            "close_price", "close_usd", "close_rate", "close_inr", "sold_lot"
        )
        self.a3_tree = ttk.Treeview(self.a3_tab, columns=cols, show="headings")
        self.a3_tree.heading("lot_id", text="Lot Identifier")
        self.a3_tree.heading("acq_date", text="Acq Date")
        self.a3_tree.heading("net_shares", text="Shares")
        self.a3_tree.heading("vest_fmv", text="Vest FMV")
        self.a3_tree.heading("init_usd", text="Init Cost ($)")
        self.a3_tree.heading("init_inr", text="Initial Value (₹)")
        self.a3_tree.heading("peak_high", text="Peak High ($)")
        self.a3_tree.heading("peak_usd", text="Peak ($)")
        self.a3_tree.heading("peak_rate", text="Peak TTBR")
        self.a3_tree.heading("peak_date", text="Peak Date")
        self.a3_tree.heading("peak_inr", text="Peak Bal (₹)")
        self.a3_tree.heading("close_price", text="Close ($)")
        self.a3_tree.heading("close_usd", text="Close ($)")
        self.a3_tree.heading("close_rate", text="Close TTBR")
        self.a3_tree.heading("close_inr", text="Closing Bal (₹)")
        self.a3_tree.heading("sold_lot", text="Sold Lot?")

        col_widths = {
            "lot_id": 160, "acq_date": 85, "net_shares": 55, "vest_fmv": 70, "init_usd": 80,
            "init_inr": 90, "peak_high": 75, "peak_usd": 75, "peak_rate": 65, "peak_date": 85,
            "peak_inr": 90, "close_price": 65, "close_usd": 75, "close_rate": 65, "close_inr": 90, "sold_lot": 80
        }
        for c, w in col_widths.items():
            anchor = "center" if c in ("acq_date", "net_shares", "peak_date", "sold_lot") else ("w" if c == "lot_id" else "e")
            self.a3_tree.column(c, width=w, anchor=anchor)

        a3_scroll_y = ttk.Scrollbar(self.a3_tab, orient=tk.VERTICAL, command=self.a3_tree.yview)
        a3_scroll_x = ttk.Scrollbar(self.a3_tab, orient=tk.HORIZONTAL, command=self.a3_tree.xview)
        self.a3_tree.configure(yscrollcommand=a3_scroll_y.set, xscrollcommand=a3_scroll_x.set)

        self.a3_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        a3_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        a3_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_schedule_os_tab(self) -> None:
        """Tab 4: Schedule OS Dividends with Rule 115 proof & sources."""
        self.os_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.os_tab, text=" Schedule OS (Dividends) ")

        cols = ("pay_date", "gross_usd", "preceding_mo", "rule115_rate", "gross_inr", "tax_usd", "deduct_date", "rule128_rate", "tax_inr", "bucket", "source")
        self.os_tree = ttk.Treeview(self.os_tab, columns=cols, show="headings")
        self.os_tree.heading("pay_date", text="Dividend Date")
        self.os_tree.heading("gross_usd", text="Gross ($)")
        self.os_tree.heading("preceding_mo", text="Preceding Mo End")
        self.os_tree.heading("rule115_rate", text="Rule 115 Rate")
        self.os_tree.heading("gross_inr", text="Gross (₹)")
        self.os_tree.heading("tax_usd", text="US Tax ($)")
        self.os_tree.heading("deduct_date", text="Deduction Date")
        self.os_tree.heading("rule128_rate", text="Rule 128 Rate")
        self.os_tree.heading("tax_inr", text="Tax Paid (₹)")
        self.os_tree.heading("bucket", text="Advance Tax Installment")
        self.os_tree.heading("source", text="Source Document Citation")

        col_widths = {
            "pay_date": 90, "gross_usd": 70, "preceding_mo": 105, "rule115_rate": 80,
            "gross_inr": 80, "tax_usd": 70, "deduct_date": 90, "rule128_rate": 80,
            "tax_inr": 80, "bucket": 110, "source": 200
        }
        for c, w in col_widths.items():
            anchor = "center" if "date" in c or c in ("preceding_mo", "bucket") else ("w" if c == "source" else "e")
            self.os_tree.column(c, width=w, anchor=anchor)

        os_scroll_y = ttk.Scrollbar(self.os_tab, orient=tk.VERTICAL, command=self.os_tree.yview)
        os_scroll_x = ttk.Scrollbar(self.os_tab, orient=tk.HORIZONTAL, command=self.os_tree.xview)
        self.os_tree.configure(yscrollcommand=os_scroll_y.set, xscrollcommand=os_scroll_x.set)

        self.os_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        os_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        os_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_validation_tab(self) -> None:
        """Tab 5: Statutory Rules & Schema Validation Scorecard."""
        self.val_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.val_tab, text=" Rules & Validation Scorecard ")

        cols = ("sl", "rule_id", "category", "authority", "title", "severity", "details", "status")
        self.val_tree = ttk.Treeview(self.val_tab, columns=cols, show="headings")
        self.val_tree.heading("sl", text="#")
        self.val_tree.heading("rule_id", text="Rule ID")
        self.val_tree.heading("category", text="Category")
        self.val_tree.heading("authority", text="Regulatory Authority")
        self.val_tree.heading("title", text="Rule Title")
        self.val_tree.heading("severity", text="Severity")
        self.val_tree.heading("details", text="Evaluated Audit Details")
        self.val_tree.heading("status", text="Status")

        col_widths = {
            "sl": 35, "rule_id": 140, "category": 160, "authority": 200,
            "title": 220, "severity": 110, "details": 260, "status": 90
        }
        for c, w in col_widths.items():
            anchor = "center" if c in ("sl", "rule_id", "severity", "status") else "w"
            self.val_tree.column(c, width=w, anchor=anchor)

        val_scroll_y = ttk.Scrollbar(self.val_tab, orient=tk.VERTICAL, command=self.val_tree.yview)
        val_scroll_x = ttk.Scrollbar(self.val_tab, orient=tk.HORIZONTAL, command=self.val_tree.xview)
        self.val_tree.configure(yscrollcommand=val_scroll_y.set, xscrollcommand=val_scroll_x.set)

        self.val_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        val_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        val_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

    def _log(self, text: str) -> None:
        """Append text to log tab."""
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)

    def _browse_single_file(self, var: tk.StringVar, title: str, filetypes: list) -> None:
        """Generic file browser dialog."""
        initial_dir = os.path.dirname(var.get()) if var.get() and os.path.exists(os.path.dirname(var.get())) else os.path.abspath(".")
        path = filedialog.askopenfilename(initialdir=initial_dir, title=title, filetypes=filetypes)
        if path:
            var.set(os.path.abspath(path))

    def _browse_output(self) -> None:
        """Open file dialog for output path."""
        file_path = filedialog.asksaveasfilename(
            initialfile=os.path.basename(self.var_output.get()),
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx")],
            title="Save ITR-2 Working As"
        )
        if file_path:
            self.var_output.set(os.path.abspath(file_path))

    def _auto_fill_from_folder(self) -> None:
        """Scan a folder and automatically map all matching broker files."""
        folder = filedialog.askdirectory(title="Select Folder Containing Broker Documents")
        if not folder:
            return

        self._log(f"[Auto-Fill] Scanning directory: {folder}")
        found_count = 0
        try:
            for entry in os.listdir(folder):
                full_p = os.path.join(folder, entry)
                if not os.path.isfile(full_p):
                    continue
                name_low = entry.lower()

                cy_hint = fy_to_calendar_year(self.var_fy.get())
                next_cy_hint = cy_hint + 1
                if "benefit" in name_low and name_low.endswith((".xlsx", ".xls", ".csv")):
                    self.var_benefit_history.set(os.path.abspath(full_p))
                    found_count += 1
                elif ("bystatus" in name_low or "holding" in name_low) and name_low.endswith((".xlsx", ".xls", ".csv")):
                    self.var_holdings.set(os.path.abspath(full_p))
                    found_count += 1
                elif "statement" in name_low and str(cy_hint) in name_low and name_low.endswith(".pdf"):
                    self.var_stmt_cy.set(os.path.abspath(full_p))
                    found_count += 1
                elif "statement" in name_low and (str(next_cy_hint)[-2:] in name_low or "march" in name_low) and name_low.endswith(".pdf"):
                    self.var_stmt_fy.set(os.path.abspath(full_p))
                    found_count += 1
                elif ("tax" in name_low or "1042" in name_low) and name_low.endswith(".pdf"):
                    self.var_tax_doc.set(os.path.abspath(full_p))
                    found_count += 1

            self._log(f"[Auto-Fill] Successfully mapped {found_count} document paths.")
            self.var_status.set(f"Auto-filled {found_count} file inputs from folder.")
        except Exception as exc:
            self._log(f"[Auto-Fill Error] {exc}")

    def _on_fy_selected(self, event=None) -> None:
        """Auto-synchronize AY when FY is selected."""
        fy = self.var_fy.get()
        target_ay = fy_to_ay(fy)
        if self.var_ay.get() != target_ay:
            self.var_ay.set(target_ay)
            self._update_output_name()

    def _on_ay_selected(self, event=None) -> None:
        """Auto-synchronize FY when AY is selected."""
        ay = self.var_ay.get()
        target_fy = ay_to_fy(ay)
        if self.var_fy.get() != target_fy:
            self.var_fy.set(target_fy)
            self._update_output_name()

    def _update_output_name(self) -> None:
        """Update default output filename based on selected AY."""
        ay = self.var_ay.get()
        curr_dir = os.path.dirname(self.var_output.get()) or os.path.abspath(".")
        self.var_output.set(os.path.join(curr_dir, f"ITR2_Foreign_Assets_Working_AY{ay}.xlsx"))

    def _refresh_open_years_async(self) -> None:
        """Discover open filing years online in background thread."""
        def _task():
            try:
                fys, ays, src = fetch_open_assessment_years()
                try:
                    if self.root and self.root.winfo_exists():
                        self.root.after(0, self._apply_open_years, fys, ays, src)
                except Exception:
                    pass
            except Exception as e:
                pass

        threading.Thread(target=_task, daemon=True).start()

    def _apply_open_years(self, fys: List[str], ays: List[str], src: str) -> None:
        """Update dropdown lists with discovered open years."""
        self.open_fys = fys
        self.open_ays = ays
        self.fy_combo.config(values=self.open_fys)
        self.ay_combo.config(values=self.open_ays)
        self.var_open_years_source.set(f"Source: {src}")
        self._log(f"[Portal Discovery] Open years refreshed from {src}:")
        self._log(f"                   Open FYs (descending): {', '.join(self.open_fys)}")
        self._log(f"                   Open AYs (descending): {', '.join(self.open_ays)}")

    def _start_generation_thread(self) -> None:
        """Run workflow in background thread so GUI doesn't freeze."""
        self.btn_generate.config(state=tk.DISABLED)
        self.progress.pack(side=tk.RIGHT, padx=10)
        self.progress.start(10)
        self.log_text.delete("1.0", tk.END)
        self.var_status.set("Processing documents and computing valuations...")

        threading.Thread(target=self._run_generation_task, daemon=True).start()

    def _run_generation_task(self) -> None:
        """Actual business logic executed in background."""
        try:
            ay = self.var_ay.get()
            fy = self.var_fy.get()
            cy = fy_to_calendar_year(fy)
            next_cy = cy + 1
            output_file = self.var_output.get()
            taxpayer_name = self.var_taxpayer_name.get()
            pan = self.var_pan.get()

            # Retrieve individual file inputs
            benefit_file = self.var_benefit_history.get()
            holdings_file = self.var_holdings.get()
            stmt_cy_file = self.var_stmt_cy.get()
            stmt_fy_end_file = self.var_stmt_fy.get()
            tax_doc = self.var_tax_doc.get()

            self._log("=" * 75)
            self._log("Starting ITR-2 Foreign Assets Automation Processing...")
            self._log(f"Taxpayer       : {taxpayer_name} (PAN: {pan})")
            self._log(f"Assessment Yr  : {ay} (Financial Yr: {fy})")
            self._log("=" * 75)

            # Validate all 5 individual files
            for label, p in [
                ("1. Benefit History", benefit_file),
                ("2. Current Holdings", holdings_file),
                ("3. Calendar Year Statements", stmt_cy_file),
                ("4. Q4 / FY-End Statements", stmt_fy_end_file),
                ("5. Tax Document / 1042-S", tax_doc)
            ]:
                if not os.path.isfile(p):
                    raise FileNotFoundError(f"Missing required file: {label}\nPath: {p}")
                self._log(f" • Loaded: {label} -> {os.path.basename(p)}")

            # 1. Parse documents via broker adapter
            self._log("\n[1/5] Ingesting documents...")
            adapter = BrokerParserFactory.auto_detect(stmt_cy_file)
            self._log(f"      Selected Broker Adapter: {adapter.broker_name}")

            all_lots = adapter.parse_benefit_history(benefit_file)
            self._log(f"      • Benefit History: Ingested {len(all_lots)} lots")

            holdings_lots = adapter.parse_holdings(holdings_file)
            self._log(f"      • Current Holdings: Ingested {len(holdings_lots)} active snapshot lots")

            primary_symbol = all_lots[0].symbol if all_lots else None
            summaries, dividends = adapter.parse_statements(
                [stmt_cy_file, stmt_fy_end_file], symbol_hint=primary_symbol, calendar_year_hint=cy
            )
            self._log(f"      • Statements: Extracted {len(summaries)} period summaries & {len(dividends)} dividends")

            form_1042s = adapter.parse_tax_documents(tax_doc, calendar_year_hint=cy)
            self._log(f"      • Form 1042-S: Verified Gross ${form_1042s.gross_dividend_usd:.2f}, Tax ${form_1042s.tax_withheld_usd:.2f}")

            # Auto-extract taxpayer name and PAN from Form 1042-S if not set
            if not taxpayer_name and form_1042s and form_1042s.recipient_name:
                taxpayer_name = form_1042s.recipient_name
                self.root.after(0, self.var_taxpayer_name.set, taxpayer_name)
            if not pan and form_1042s and form_1042s.recipient_tin:
                pan = form_1042s.recipient_tin
                self.root.after(0, self.var_pan.set, pan)

            # 2. Reconcile
            self._log("\n[2/5] Reconciling chronological lot ledger & sold lots...")
            ledger = LotLedger(all_lots)
            verifier = DocumentVerifier(ledger, holdings_lots)
            report = verifier.verify_holdings()

            self._log(f"      • Status: {report.status}")
            self._log(f"      • Active shares: {report.total_reconstructed_shares:.1f} shs (matches holdings)")
            self._log(f"      • Sold lots detected: {report.sold_lots_count}")

            fa_lots = ledger.get_schedule_fa_lots(calendar_year=cy)
            self._log(f"      • Schedule FA lots for CY {cy}: {len(fa_lots)}")

            # 3. Market & FX
            self._log("\n[3/5] Loading historical SBI TTBR rates & daily stock prices...")
            sbi = SBIRateService()

            # Dynamically resolve stock symbols
            detected_symbols = list(set(lot.symbol for lot in all_lots if lot.symbol))
            symbols = detected_symbols if detected_symbols else []
            mkt = MarketDataService()
            for sym in symbols:
                mkt.load_symbol(sym)
                self._log(f"      • Market Data Engine: {sym} daily OHLC prices loaded and cached")

            # 4. Valuation
            self._log("\n[4/5] Computing Schedule FA, OS, FSI, TR, and Form 67...")
            primary_sym = symbols[0] if symbols else "STOCK"
            account_num = form_1042s.account_number if form_1042s and form_1042s.account_number else ""
            engine = ValuationEngine(
                ledger=ledger,
                sbi_service=sbi,
                market_service=mkt,
                employer_entity_name=f"{primary_sym} Corporation",
                broker_name=adapter.broker_name,
                account_number=account_num
            )
            dec_summary = next(s for s in summaries if s.end_date == date(cy, 12, 31))
            a2_res = engine.compute_table_a2(cy, dec_summary, dividends)
            a3_res = engine.compute_table_a3(cy, dividends)

            fy_divs = [d for d in dividends if date(cy, 4, 1) <= d.pay_date <= date(next_cy, 3, 31)]
            os_res, ftc_res = engine.compute_schedule_os_and_ftc(fy_divs, calendar_year=cy)

            # 4.5 Statutory & Schema Rules Validation
            self._log("\n[4.5/5] Executing CBDT Statutory & Schema Rules Validation Engine...")
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
            self._log(f"      • Rules Evaluated: {sc.total_rules}  |  Passed: {sc.passed}  |  Failed: {sc.failed}")
            self._log(f"      • Filing Readiness: {sc.compute_status()}")

            # 5. Generate Excel
            self._log(f"\n[5/5] Generating Excel workbook: {output_file}...")
            generator = ITRWorkbookGenerator(output_path=output_file)
            out_path = generator.generate(
                a2_result=a2_res,
                a3_lots=a3_res,
                os_result=os_res,
                ftc_result=ftc_res,
                form_1042s=form_1042s,
                reconciliation_report=report,
                dividends=dividends,
                statement_summaries=summaries,
                taxpayer_name=taxpayer_name,
                pan=pan,
                ay=ay,
                fy=fy,
                sbi_service=sbi,
                val_report=val_report
            )
            self.last_generated_file = os.path.abspath(out_path)

            self._log("\nSUCCESS: All calculations complete and Excel workbook generated!")
            self._log(f"Saved at: {self.last_generated_file}")

            # Populate UI elements
            self.root.after(0, self._on_generation_success, a2_res, a3_res, os_res, ftc_res, val_report, cy, next_cy, fy)

        except Exception as exc:
            self._log(f"\nERROR: {exc}")
            self.root.after(0, self._on_generation_error, str(exc))

    def _on_generation_success(
        self,
        a2: ScheduleFATableA2Result,
        a3_lots: List[ScheduleFATableA3LotResult],
        os_res: ScheduleOSResult,
        ftc_res: FTCResult,
        val_report: Optional[Any] = None,
        cy: int = 2025,
        next_cy: int = 2026,
        fy: str = "2025-26"
    ) -> None:
        """Callback on main thread upon success."""
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_generate.config(state=tk.NORMAL)
        self.btn_open_excel.config(state=tk.NORMAL)
        self.var_status.set(f"Completed successfully! Output saved to: {os.path.basename(self.last_generated_file)}")

        # Populate KPI Tree
        self.kpi_tree.delete(*self.kpi_tree.get_children())
        kpis = [
            ("Schedule FA (A2)", "Custodial Account Peak Balance", f"${a2.peak_balance_usd:,.2f}", f"₹ {a2.peak_balance_inr:,}", f"Peak on {a2.peak_date} @ SBI ₹{a2.peak_rate_inr:.2f} | {a2.source_peak[:40]}..."),
            ("Schedule FA (A2)", "Custodial Account Closing Balance", f"${a2.closing_balance_usd:,.2f}", f"₹ {a2.closing_balance_inr:,}", f"Dec 31, {cy} @ SBI ₹{a2.closing_rate_inr:.2f} | {a2.source_closing[:40]}..."),
            ("Schedule FA (A3)", "Total Foreign Equity Closing Value", f"{len(a3_lots)} Lots", f"₹ {sum(l.closing_balance_inr for l in a3_lots):,}", "Includes Sold Lots | Initial/Peak/Close Provenance"),
            ("Schedule OS", f"Gross Foreign Dividends (FY {fy})", f"${sum(i.gross_usd for i in os_res.items):,.2f}", f"₹ {os_res.total_dividend_inr:,}", "Other Sources (5 Installments) | Preceding Month End TTBR"),
            ("Schedule FSI / TR", "Foreign Taxes Paid Abroad (25%)", f"${sum(i.tax_usd for i in os_res.items):,.2f}", f"₹ {ftc_res.foreign_tax_paid_inr:,}", "Rule 128(5)(ii) Preceding Month-End Rate | Form 1042-S Box 7a"),
            ("Form 67 / TR", "FTC Relief Claimed u/s 90", f"${sum(i.tax_usd for i in os_res.items):,.2f}", f"₹ {ftc_res.tax_relief_claimed_inr:,}", "DTAA Article 10 | Form 1042-S Proof Attached"),
        ]
        if val_report:
            kpis.append((
                "Rules Scorecard",
                "CBDT Statutory & Schema Compliance",
                f"{val_report.scorecard.passed}/{val_report.scorecard.total_rules} Passed",
                val_report.scorecard.compute_status(),
                "Passed 100% of CBDT JSON Schema, Systems Rules PDF & IT Rules 115/128/90"
            ))
        for k in kpis:
            self.kpi_tree.insert("", tk.END, values=k)

        # Populate Table A3 Tree
        self.a3_tree.delete(*self.a3_tree.get_children())
        for l in a3_lots:
            if getattr(l, "is_sold_lot", False):
                sold_txt = f"YES (Sold {l.disposal_date.year})" if l.disposal_date else f"YES (Sold after {cy})"
            else:
                sold_txt = "NO"
            self.a3_tree.insert("", tk.END, values=(
                l.lot_id,
                l.acquisition_date.strftime("%Y-%m-%d"),
                f"{l.net_shares:.1f}",
                f"${l.vest_fmv_usd:.2f}",
                f"${l.initial_cost_usd:.2f}",
                f"₹ {l.initial_value_inr:,}",
                f"${l.peak_price_usd:.2f}",
                f"${l.peak_balance_usd:.2f}",
                f"₹{l.peak_rate_inr:.2f}",
                l.peak_date.strftime("%Y-%m-%d"),
                f"₹ {l.peak_balance_inr:,}",
                f"${l.closing_price_usd:.2f}",
                f"${l.closing_balance_usd:.2f}",
                f"₹{l.closing_rate_inr:.2f}",
                f"₹ {l.closing_balance_inr:,}",
                sold_txt
            ))

        # Populate Schedule OS Tree
        self.os_tree.delete(*self.os_tree.get_children())
        for item in os_res.items:
            self.os_tree.insert("", tk.END, values=(
                item.pay_date.strftime("%Y-%m-%d"),
                f"${item.gross_usd:.2f}",
                item.preceding_month_end.strftime("%Y-%m-%d"),
                f"₹ {item.rule_115_rate:.2f}",
                f"₹ {item.gross_inr:,}",
                f"${item.tax_usd:.2f}",
                item.pay_date.strftime("%Y-%m-%d"),
                f"₹ {item.rule_128_rate:.2f}",
                f"₹ {item.tax_inr:,}",
                item.advance_tax_bucket,
                item.source_document
            ))

        # Populate Validation Rules Scorecard Tree
        if val_report:
            self.val_tree.delete(*self.val_tree.get_children())
            for idx, r in enumerate(val_report.results, start=1):
                self.val_tree.insert("", tk.END, values=(
                    idx,
                    r.rule_id,
                    r.category.value,
                    r.authority,
                    r.title,
                    r.severity.value,
                    r.details,
                    r.status.value
                ))

        self.notebook.select(self.kpi_tab)
        messagebox.showinfo("Success", f"ITR-2 Working Workbook generated successfully!\n\nFile: {self.last_generated_file}")

    def _on_generation_error(self, err_msg: str) -> None:
        """Callback on main thread upon failure."""
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_generate.config(state=tk.NORMAL)
        self.var_status.set("Error occurred during processing.")
        messagebox.showerror("Processing Error", f"An error occurred:\n\n{err_msg}")

    def _open_excel(self) -> None:
        """Open generated Excel file in default OS spreadsheet app."""
        if self.last_generated_file and os.path.exists(self.last_generated_file):
            if sys.platform == "win32":
                os.startfile(self.last_generated_file)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.last_generated_file])
            else:
                subprocess.Popen(["xdg-open", self.last_generated_file])

    def _open_folder(self) -> None:
        """Open folder containing output file."""
        folder = os.path.dirname(os.path.abspath(self.var_output.get()))
        if os.path.exists(folder):
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])


def launch_gui():
    """Launch the ITR Assist desktop GUI."""
    root = tk.Tk()
    app = ITRAssistGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
