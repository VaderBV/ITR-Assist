"""E*TRADE implementation of BaseHoldingsParser."""
from typing import List
import pandas as pd

from itr_assist.models import LotStatus, PlanType, ShareLot
from itr_assist.parsers.base import BaseHoldingsParser
from itr_assist.parsers.common import clean_currency, parse_date


class ETradeHoldingsParser(BaseHoldingsParser):
    """Parses E*TRADE ByStatus_expanded.xlsx (Sellable sheet)."""

    def parse(self, file_path: str) -> List[ShareLot]:
        """Extract active lots from E*TRADE ByStatus_expanded.xlsx."""
        lots: List[ShareLot] = []
        df = pd.read_excel(file_path, sheet_name="Sellable")

        for idx, row in df.iterrows():
            rec_type = str(row.get("Record Type", "")).strip()
            if rec_type in ("Overall Total", "Totals", "") or pd.isna(row.get("Symbol")):
                continue

            symbol = str(row.get("Symbol", "")).strip()
            plan_str = str(row.get("Plan Type", "")).strip().upper()
            plan_type = PlanType.ESPP if ("ESPP" in plan_str or "PURCHASE" in plan_str) else PlanType.RSU

            acq_date = parse_date(row.get("Date Acquired")) or parse_date(row.get("Vest Date"))
            grant_date = parse_date(row.get("Grant Date"))
            grant_number = str(row.get("Grant Number", "")).strip()

            sellable_qty = float(row.get("Sellable Qty.", 0.0) or 0.0)
            cost_basis = clean_currency(row.get("Est. Cost Basis (per share):"))

            lot_id = f"{symbol}-{grant_number or plan_type.value}-{acq_date.strftime('%Y%m%d')}"

            lot = ShareLot(
                lot_id=lot_id,
                symbol=symbol,
                plan_type=plan_type,
                acquisition_date=acq_date,
                gross_shares=sellable_qty,
                withheld_shares=0.0,
                net_shares=sellable_qty,
                vest_fmv_usd=cost_basis,
                cost_basis_per_share_usd=cost_basis,
                remaining_shares=sellable_qty,
                status=LotStatus.ACTIVE,
                grant_number=grant_number if grant_number != "nan" else None,
                grant_date=grant_date,
                notes=f"Holdings snapshot lot (Acquired: {acq_date})"
            )
            lots.append(lot)

        lots.sort(key=lambda x: x.acquisition_date)
        return lots
