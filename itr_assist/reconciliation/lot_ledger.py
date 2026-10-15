"""Lot ledger and chronological lifecycle engine."""
from datetime import date
from typing import Dict, List, Optional, Tuple

from itr_assist.models import DividendEvent, LotStatus, PlanType, ShareLot


class LotLedger:
    """Maintains and reconstructs the chronological lifecycle of share lots."""

    def __init__(self, all_lots: List[ShareLot]):
        # Sort lots chronologically
        self.lots = sorted(all_lots, key=lambda x: x.acquisition_date)

    def get_lots_active_in_window(self, start_date: date, end_date: date) -> List[ShareLot]:
        """Return all lots that were held at ANY point in [start_date, end_date]."""
        active_lots: List[ShareLot] = []
        for lot in self.lots:
            # Lot was acquired on or before window end
            if lot.acquisition_date <= end_date:
                # Lot was not fully disposed before window start
                if lot.disposal_date is None or lot.disposal_date >= start_date:
                    active_lots.append(lot)
        return active_lots

    def get_schedule_fa_lots(self, calendar_year: int) -> List[ShareLot]:
        """Return all lots to be declared in Schedule FA Table A3 for the calendar year."""
        cy_start = date(calendar_year, 1, 1)
        cy_end = date(calendar_year, 12, 31)
        return self.get_lots_active_in_window(cy_start, cy_end)

    def get_shares_held_on_date(self, target_date: date) -> Tuple[float, List[ShareLot]]:
        """Compute total shares held and list of active lots on a specific date."""
        active: List[ShareLot] = []
        total_shares = 0.0
        for lot in self.lots:
            if lot.acquisition_date <= target_date:
                if lot.disposal_date is None or lot.disposal_date > target_date:
                    active.append(lot)
                    total_shares += lot.net_shares
        return total_shares, active

    def allocate_dividends(self, dividends: List[DividendEvent]) -> List[DividendEvent]:
        """Pro-rata allocate each dividend payment across active lots on that date."""
        enriched_dividends: List[DividendEvent] = []

        for div in dividends:
            # Total shares eligible on dividend record/pay date
            total_shares, active_lots = self.get_shares_held_on_date(div.pay_date)
            
            allocations: Dict[str, float] = {}
            if total_shares > 0:
                rate_per_share = div.gross_amount_usd / total_shares
                for lot in active_lots:
                    lot_div = round(lot.net_shares * rate_per_share, 4)
                    allocations[lot.lot_id] = lot_div
            
            enriched_div = DividendEvent(
                pay_date=div.pay_date,
                symbol=div.symbol,
                gross_amount_usd=div.gross_amount_usd,
                tax_withheld_usd=div.tax_withheld_usd,
                record_date=div.record_date,
                shares_count=total_shares,
                rate_per_share=round(div.gross_amount_usd / total_shares, 4) if total_shares > 0 else 0.0,
                lot_allocations=allocations
            )
            enriched_dividends.append(enriched_div)

        return enriched_dividends
