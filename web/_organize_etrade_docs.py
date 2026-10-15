"""Organizes downloaded E*TRADE documents into FY-based folders for ITR filing.

Rules (derived from the actual tool's required inputs, verified against CBDT
Schedule FA guidance earlier this session):
- Schedule FA for FY(Y)-(Y+1) covers calendar year Y (Jan-Dec Y).
- The "Calendar Year Statement" input = all of CY(Y)'s monthly statements -> FY(Y)-(Y+1).
- The "Q4/FY-End Statement" input = Jan-Mar of CY(Y+1) -> completes the SAME FY(Y)-(Y+1).
- Jan-Mar of year Y+1 therefore belongs to TWO folders: as the Q4 piece of FY(Y)-(Y+1),
  AND as part of FY(Y+1)-(Y+2)'s own full Calendar Year Statement. Both are copied, not
  a conflict - they serve different purposes in different filings.
- TaxDocuments_<YYYY>.zip is the 1042-S for calendar year YYYY -> FY(YYYY)-(YYYY+1).
- TradeConfirmations follow the exact same month-based split as Client Statements.
- Benefit History (all-time, cumulative) is copied into EVERY FY folder - every year's
  lot reconstruction needs the complete history, not just that year's slice.
- Current Holdings is a point-in-time-TODAY snapshot, not date-ranged. It's only
  genuinely accurate for reconciling the FY that's open right now, not a historical one.
"""
import os
import re
import shutil
import zipfile
from datetime import date

ROOT = r"D:\Downloads\Etrade documents"
STAGING = r"D:\Downloads\Etrade documents\_unzipped_staging"

FY_FOLDERS = ["FY23-24", "FY24-25", "FY25-26", "FY26-27"]


def fy_name(start_year: int) -> str:
    return f"FY{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


def ensure_dirs():
    for fy in FY_FOLDERS:
        for sub in ["BenefitHistory", "CurrentHoldings", "CalendarYearStatements",
                    "Q4_FY-End_Statements", "TaxDocuments_1042S", "TradeConfirmations"]:
            os.makedirs(os.path.join(ROOT, fy, sub), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "_reference_all_years"), exist_ok=True)


def unzip_all():
    os.makedirs(STAGING, exist_ok=True)
    manifest = {}  # zip_name -> extracted dir
    for fname in os.listdir(ROOT):
        if fname.endswith(".zip"):
            out_dir = os.path.join(STAGING, fname[:-4])
            os.makedirs(out_dir, exist_ok=True)
            with zipfile.ZipFile(os.path.join(ROOT, fname)) as z:
                z.extractall(out_dir)
            manifest[fname] = out_dir
    return manifest


# Filenames look like ..._MMDDYY.pdf or ..._MMDDYY_1.pdf
DATE_RE = re.compile(r"_(\d{2})(\d{2})(\d{2})(?:_\d+)?\.pdf$", re.IGNORECASE)


def parse_file_date(filename: str):
    m = DATE_RE.search(filename)
    if not m:
        return None
    mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(2000 + yy, mm, dd)


def process_statements(manifest, log):
    for zip_name, out_dir in manifest.items():
        if not zip_name.startswith("ClientStatements_") and not zip_name.startswith("TradeConfirmations_"):
            continue
        kind = "CalendarYearStatements" if zip_name.startswith("ClientStatements_") else "TradeConfirmations"
        for fname in sorted(os.listdir(out_dir)):
            if not fname.lower().endswith(".pdf"):
                continue
            d = parse_file_date(fname)
            if d is None:
                log.append(f"  SKIPPED (no parseable date): {zip_name}/{fname}")
                continue
            src = os.path.join(out_dir, fname)

            # Always: full-year home -> FY(d.year)-(d.year+1), CalendarYearStatements/TradeConfirmations bucket
            home_fy = fy_name(d.year)
            if home_fy in FY_FOLDERS:
                dst_dir = os.path.join(ROOT, home_fy, kind)
                shutil.copy2(src, dst_dir)
                log.append(f"  {fname}  ({d.isoformat()})  -> {home_fy}/{kind}/")

            # Jan-Mar also completes the PRIOR FY's Q4/FY-End bucket
            if d.month <= 3:
                prior_fy = fy_name(d.year - 1)
                if prior_fy in FY_FOLDERS:
                    q4_kind = "Q4_FY-End_Statements" if kind == "CalendarYearStatements" else "TradeConfirmations"
                    dst_dir = os.path.join(ROOT, prior_fy, q4_kind)
                    shutil.copy2(src, dst_dir)
                    log.append(f"  {fname}  ({d.isoformat()})  -> {prior_fy}/{q4_kind}/  (Q4 completion)")


def process_tax_documents(manifest, log):
    for zip_name, out_dir in manifest.items():
        if not zip_name.startswith("TaxDocuments_"):
            continue
        m = re.search(r"TaxDocuments_(\d{4})\.zip", zip_name)
        if not m:
            log.append(f"  SKIPPED (can't parse year from zip name): {zip_name}")
            continue
        cy = int(m.group(1))
        fy = fy_name(cy)
        if fy not in FY_FOLDERS:
            continue
        for fname in sorted(os.listdir(out_dir)):
            if not fname.lower().endswith(".pdf"):
                continue
            src = os.path.join(out_dir, fname)
            dst_dir = os.path.join(ROOT, fy, "TaxDocuments_1042S")
            shutil.copy2(src, dst_dir)
            log.append(f"  {fname}  (1042-S for CY{cy})  -> {fy}/TaxDocuments_1042S/")


def process_standalone_files(log):
    benefit_src = os.path.join(ROOT, "Etrade-BenefitHistory.xlsx")
    if os.path.exists(benefit_src):
        for fy in FY_FOLDERS:
            shutil.copy2(benefit_src, os.path.join(ROOT, fy, "BenefitHistory"))
        log.append(f"  Etrade-BenefitHistory.xlsx -> copied into all {len(FY_FOLDERS)} FY folders (all-time history, needed by every year)")

    for holdings_name in ["Etrade-ByStatus_expanded.xlsx", "Etrade-ByBenefitType_expanded.xlsx"]:
        src = os.path.join(ROOT, holdings_name)
        if os.path.exists(src):
            # Only genuinely valid as a snapshot for whichever FY is open right now.
            dst_dir = os.path.join(ROOT, "FY26-27", "CurrentHoldings")
            shutil.copy2(src, dst_dir)
            log.append(f"  {holdings_name} -> FY26-27/CurrentHoldings/ ONLY (point-in-time-today snapshot, not valid retroactively for older FYs)")

    orders_src = os.path.join(ROOT, "Etrade-Orders-july2023-oct-2026.pdf")
    if os.path.exists(orders_src):
        shutil.copy2(orders_src, os.path.join(ROOT, "_reference_all_years"))
        log.append("  Etrade-Orders-july2023-oct-2026.pdf -> _reference_all_years/ (spans all years, not splittable by FY)")


def main():
    ensure_dirs()
    manifest = unzip_all()
    log = []
    log.append("=== Client Statements & Trade Confirmations ===")
    process_statements(manifest, log)
    log.append("")
    log.append("=== Tax Documents (Form 1042-S) ===")
    process_tax_documents(manifest, log)
    log.append("")
    log.append("=== Standalone files (Benefit History, Holdings, Orders) ===")
    process_standalone_files(log)
    print("\n".join(log))

    print("\n=== Folder completeness check ===")
    for fy in FY_FOLDERS:
        cy_dir = os.path.join(ROOT, fy, "CalendarYearStatements")
        q4_dir = os.path.join(ROOT, fy, "Q4_FY-End_Statements")
        cy_count = len([f for f in os.listdir(cy_dir) if f.endswith(".pdf")]) if os.path.exists(cy_dir) else 0
        q4_count = len([f for f in os.listdir(q4_dir) if f.endswith(".pdf")]) if os.path.exists(q4_dir) else 0
        tax_dir = os.path.join(ROOT, fy, "TaxDocuments_1042S")
        tax_count = len([f for f in os.listdir(tax_dir) if f.endswith(".pdf")]) if os.path.exists(tax_dir) else 0
        print(f"{fy}: {cy_count} calendar-year statement(s), {q4_count} Q4 statement(s), {tax_count} 1042-S doc(s)")


if __name__ == "__main__":
    main()
