"""E*TRADE implementation of BaseBenefitHistoryParser."""
from datetime import date
from typing import Dict, List, Tuple
import pandas as pd

from itr_assist.models import LotStatus, PlanType, ShareLot
from itr_assist.parsers.base import BaseBenefitHistoryParser
from itr_assist.parsers.common import clean_currency, parse_date


class ETradeBenefitHistoryParser(BaseBenefitHistoryParser):
    """Parses E*TRADE BenefitHistory.xlsx for RSU and ESPP acquisitions."""

    def parse(self, file_path: str) -> List[ShareLot]:
        """Extract all vested RSU and purchased ESPP lots from E*TRADE BenefitHistory.xlsx.

        Not every account has an ESPP sheet (RSU-only accounts don't) - try it and skip
        quietly if the sheet doesn't exist, rather than requiring a separate sheet-list call
        (which real workbooks support but test fixtures mocking read_excel directly don't).
        """
        lots: List[ShareLot] = []
        try:
            lots.extend(self._parse_espp(file_path))
        except ValueError as e:
            if "ESPP" not in str(e):
                raise
        lots.extend(self._parse_rsu(file_path))
        lots.sort(key=lambda x: x.acquisition_date)
        return lots

    def _parse_espp(self, file_path: str) -> List[ShareLot]:
        """Parse ESPP sheet."""
        lots: List[ShareLot] = []
        df = pd.read_excel(file_path, sheet_name="ESPP")

        i = 0
        while i < len(df):
            row = df.iloc[i]
            rec_type = str(row.get("Record Type", "")).strip()

            if rec_type == "Purchase":
                raw_sym = str(row.get("Symbol", "")).strip()
                symbol = raw_sym if raw_sym and raw_sym.lower() != "nan" else "STOCK"
                acq_date = parse_date(row.get("Purchase Date"))
                grant_date = parse_date(row.get("Grant Date"))
                purchased_qty = float(row.get("Purchased Qty.", 0.0) or 0.0)
                net_shares = float(row.get("Net Shares", purchased_qty) or purchased_qty)
                purchase_price = clean_currency(row.get("Purchase Price"))
                purchase_fmv = clean_currency(row.get("Purchase Date FMV"))

                # Check child Event rows for disposal/sell events
                disposal_date = None
                disposal_qty = 0.0
                j = i + 1
                while j < len(df) and str(df.iloc[j].get("Record Type", "")).strip() == "Event":
                    event_row = df.iloc[j]
                    event_type = str(event_row.get("Event Type", "")).upper()
                    if "SELL" in event_type or "DISPOSITION" in event_type:
                        disposal_date = parse_date(event_row.get("Date"))
                        disposal_qty += float(event_row.get("Qty", 0.0) or 0.0)
                    j += 1

                remaining = max(0.0, net_shares - disposal_qty)
                status = LotStatus.ACTIVE if remaining > 0 else LotStatus.FULLY_SOLD
                lot_id = f"{symbol}-ESPP-{acq_date.strftime('%Y%m%d')}"

                lot = ShareLot(
                    lot_id=lot_id,
                    symbol=symbol,
                    plan_type=PlanType.ESPP,
                    acquisition_date=acq_date,
                    gross_shares=purchased_qty,
                    withheld_shares=purchased_qty - net_shares,
                    net_shares=net_shares,
                    vest_fmv_usd=purchase_fmv if purchase_fmv > 0 else purchase_price,
                    cost_basis_per_share_usd=purchase_fmv if purchase_fmv > 0 else purchase_price,
                    remaining_shares=remaining,
                    status=status,
                    grant_number="ESPP_INTL",
                    grant_date=grant_date,
                    disposal_date=disposal_date,
                    disposal_qty=disposal_qty,
                    notes=f"ESPP Purchase Price: ${purchase_price:.4f}, FMV: ${purchase_fmv:.2f}"
                )
                lots.append(lot)
                i = j
            else:
                i += 1

        return lots

    def _parse_rsu(self, file_path: str) -> List[ShareLot]:
        """Parse Restricted Stock sheet for vested tranches."""
        lots: List[ShareLot] = []
        df = pd.read_excel(file_path, sheet_name="Restricted Stock")

        # The grant's "Shares released" Event rows record what actually reached the account at
        # each vest. They are the source of truth: under net settlement the employer keeps
        # shares back for tax, yet the Vest Schedule row's "Released Qty" column still shows the
        # full vested quantity (real data: 7-8 vested, 4-5 released from Nov 2024 onward).
        released_events: Dict[Tuple[str, date], float] = {}
        for _, ev in df[df["Record Type"].astype(str).str.strip() == "Event"].iterrows():
            if str(ev.get("Event Type", "")).strip().lower() == "shares released" and not pd.isna(ev.get("Date")):
                key = (str(ev.get("Grant Number", "")).strip(), parse_date(ev.get("Date")))
                released_events[key] = released_events.get(key, 0.0) + float(ev.get("Qty. or Amount") or 0.0)

        current_symbol = ""
        i = 0
        while i < len(df):
            row = df.iloc[i]
            rec_type = str(row.get("Record Type", "")).strip()

            if rec_type == "Grant":
                sym = row.get("Symbol")
                if not pd.isna(sym) and str(sym).strip():
                    current_symbol = str(sym).strip()

            if rec_type == "Vest Schedule":
                vested_qty = float(row.get("Vested Qty..1", 0.0) or 0.0)
                if vested_qty > 0.0:
                    grant_num = str(row.get("Grant Number", "")).strip()
                    vest_date = parse_date(row.get("Vest Date"))
                    # Shares actually credited at vest: the "Shares released" event (see above),
                    # else the row's "Released Qty". Never "Sellable Qty..1" - that is the
                    # CURRENT remaining balance at export time, already reduced by later sales.
                    released_col = row.get("Released Qty")
                    released_qty = released_events.get(
                        (grant_num, vest_date),
                        vested_qty if pd.isna(released_col) else float(released_col),
                    )
                    tax_paid = clean_currency(row.get("Total Taxes Paid"))
                    withheld_qty = vested_qty - released_qty

                    # Following 'Tax Withholding' rows carry the Taxable Gain (summed - a vest can
                    # have several). This FMV is provisional: the gain also covers fractional
                    # dividend-equivalent shares paid as cash, so gain/whole-shares overstates the
                    # per-share FMV; the pipeline replaces it with the vest-day close when prices
                    # are available (see itr_assist.pipeline.refine_vest_fmv).
                    vest_fmv = 0.0
                    total_gain = 0.0
                    j = i + 1
                    while j < len(df) and str(df.iloc[j].get("Record Type", "")).strip() == "Tax Withholding":
                        total_gain += clean_currency(df.iloc[j].get("Taxable Gain"))
                        j += 1
                    if total_gain > 0:
                        vest_fmv = round(total_gain / vested_qty, 4)

                    if vest_fmv == 0.0 and tax_paid > 0 and withheld_qty > 0:
                        vest_fmv = round(tax_paid / withheld_qty, 4)

                    period = int(row.get("Vest Period", 1.0) or 1.0)
                    lot_sym = current_symbol or "STOCK"
                    lot_id = f"{lot_sym}-{grant_num}-T{period}-{vest_date.strftime('%Y%m%d')}"
                    # Disposal is determined later by allocate_sales() matching real SaleEvents
                    # parsed from statements, not by this (current-snapshot) export.
                    status = LotStatus.ACTIVE if released_qty > 0 else LotStatus.FULLY_SOLD

                    lot = ShareLot(
                        lot_id=lot_id,
                        symbol=lot_sym,
                        plan_type=PlanType.RSU,
                        acquisition_date=vest_date,
                        gross_shares=vested_qty,
                        withheld_shares=withheld_qty,
                        net_shares=released_qty,
                        vest_fmv_usd=vest_fmv,
                        cost_basis_per_share_usd=vest_fmv,
                        remaining_shares=released_qty,
                        status=status,
                        grant_number=grant_num,
                        notes=f"RSU Vest Grant {grant_num} Tranche {period}"
                    )
                    lots.append(lot)
            i += 1

        return lots
