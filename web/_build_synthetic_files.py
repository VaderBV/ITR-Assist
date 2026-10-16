"""Builds real .xlsx/.pdf files (not mocked objects) matching the exact formats the
parsers expect, so the glue pipeline in app.js can be tested end-to-end through the
REAL file-parsing layer, not just in-memory objects."""
import os
import pandas as pd
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(__file__), "_synth")
os.makedirs(OUT, exist_ok=True)

# --- Benefit History (RSU + ESPP) ---
espp_df = pd.DataFrame([
    {"Record Type": "Purchase", "Symbol": "ACME", "Purchase Date": "2023-12-01",
     "Purchased Qty.": 6.0, "Net Shares": 6.0, "Purchase Price": "$59.50", "Purchase Date FMV": "$70.00"},
])
rsu_df = pd.DataFrame([
    {"Record Type": "Grant", "Symbol": "ACME"},
    {"Record Type": "Vest Schedule", "Grant Number": "G100", "Vest Date": "2024-05-15",
     "Vested Qty..1": 15.0, "Sellable Qty..1": 10.0, "Total Taxes Paid": "$500.00"},
    {"Record Type": "Tax Withholding", "Taxable Gain": "$1000.00"},
])
bh_path = os.path.join(OUT, "benefit.xlsx")
with pd.ExcelWriter(bh_path, engine="openpyxl") as writer:
    espp_df.to_excel(writer, sheet_name="ESPP", index=False)
    rsu_df.to_excel(writer, sheet_name="Restricted Stock", index=False)

# --- Holdings (ByStatus expanded) ---
holdings_df = pd.DataFrame([
    {"Record Type": "Holding", "Symbol": "ACME", "Plan Type": "RSU", "Date Acquired": "05/15/2024",
     "Grant Number": "G100", "Sellable Qty.": 10.0, "Est. Cost Basis (per share):": "$100.00"},
])
hold_path = os.path.join(OUT, "holdings.xlsx")
with pd.ExcelWriter(hold_path, engine="openpyxl") as writer:
    holdings_df.to_excel(writer, sheet_name="Sellable", index=False)

# --- Calendar Year Statement PDF ---
stmt_cy_path = os.path.join(OUT, "stmt_cy.pdf")
c = canvas.Canvas(stmt_cy_path, pagesize=(612, 792))
c.setFont("Helvetica", 9)
lines = [
    "CLIENT STATEMENT For the Period December 1-31, 2025 Page 1",
    "Beginning Total Value $2,400.00",
    "Ending Total Value $2,800.00",
    "Cash $100.00",
    "Equities 2,700.00",
    "15.000 shs from Stock Plan",
    "Activity Summary",
    "12/09 Qualified Dividend ACME CORPORATION $25.00",
    "12/09 Tax Withholding ($6.25)",
    "06/10 Sold 4.000 shs ACME CORPORATION @ $120.00 $480.00",
]
y = 760
for line in lines:
    c.drawString(40, y, line)
    y -= 14
c.save()

# --- Q4/FY-end statement PDF (minimal, reuses the same period so dec_summary resolves) ---
stmt_fy_path = os.path.join(OUT, "stmt_fy.pdf")
c = canvas.Canvas(stmt_fy_path, pagesize=(612, 792))
c.setFont("Helvetica", 9)
lines2 = [
    "CLIENT STATEMENT For the Period January 1-31, 2026 Page 1",
    "Beginning Total Value $2,800.00",
    "Ending Total Value $2,850.00",
    "Cash $120.00",
    "Equities 2,730.00",
    "15.000 shs from Stock Plan",
]
y = 760
for line in lines2:
    c.drawString(40, y, line)
    y -= 14
c.save()

# --- Form 1042-S PDF ---
taxdoc_path = os.path.join(OUT, "taxdoc.pdf")
c = canvas.Canvas(taxdoc_path, pagesize=(612, 792))
c.setFont("Helvetica", 9)
lines3 = [
    "2025 Form 1042-S",
    "06 Chap. 3 $25.00 15 15.0% 15 15.0% $6.25",
    "889 000000",
    "JOHN DOE",
    "ABCDE1234F",
]
y = 760
for line in lines3:
    c.drawString(40, y, line)
    y -= 14
c.save()

print("Synthetic files written to", OUT)
for f in os.listdir(OUT):
    print(" -", f, os.path.getsize(os.path.join(OUT, f)), "bytes")
