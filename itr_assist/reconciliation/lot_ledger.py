"""Lot ledger and chronological lifecycle engine."""
from datetime import date
from typing import Dict, List, Optional, Tuple

from itr_assist.models import DividendEvent, LotStatus, PlanType, SaleEvent, ShareLot


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

    def get_shares_held_on_date(self, target_date: date, symbol: Optional[str] = None) -> Tuple[float, List[ShareLot]]:
        """Shares held (and the lots holding them) at end of target_date, optionally for one ticker."""
        active: List[ShareLot] = []
        total_shares = 0.0
        for lot in self.lots:
            if symbol is not None and lot.symbol != symbol:
                continue
            if lot.acquisition_date <= target_date:
                if lot.disposal_date is None or lot.disposal_date > target_date:
                    active.append(lot)
                    total_shares += lot.net_shares
        return total_shares, active

    def allocate_dividends(self, dividends: List[DividendEvent]) -> List[DividendEvent]:
        """Pro-rata allocate each dividend across the lots of that ticker that were entitled to
        it - held on the record date when the statement provides one, else the pay date."""
        enriched_dividends: List[DividendEvent] = []

        for div in dividends:
            total_shares, active_lots = self.get_shares_held_on_date(div.record_date or div.pay_date, div.symbol)

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
                tax_deduction_date=div.tax_deduction_date,
                record_date=div.record_date,
                shares_count=total_shares,
                rate_per_share=round(div.gross_amount_usd / total_shares, 4) if total_shares > 0 else 0.0,
                lot_allocations=allocations,
                tax_line_found=div.tax_line_found,
            )
            enriched_dividends.append(enriched_div)

        return enriched_dividends

    def allocate_sales(self, sales: List[SaleEvent]) -> List[SaleEvent]:
        """FIFO-match each sale against active lots of the same symbol (oldest acquisition
        first - the standard convention for identifying which tranche was sold). Mutates
        self.lots in place:
        - A sale that exactly consumes a lot's remaining shares sets that lot's
          disposal_date/disposal_qty and zeroes remaining_shares.
        - A sale that only partially consumes a lot SPLITS it into a disposed sub-lot (for the
          sold portion, with disposal_date set) and a remaining sub-lot (still active), so the
          existing peak/closing valuation logic - which operates on whole lots - stays correct
          for both the sold and still-held portions without needing to change.

        Must be called before get_schedule_fa_lots()/compute_table_a3() so they see the
        post-sale lot state (correct disposal dates, correct still-active share counts).
        """
        enriched_sales: List[SaleEvent] = []

        for sale in sorted(sales, key=lambda s: s.sale_date):
            remaining_to_match = sale.quantity
            allocations: Dict[str, float] = {}
            new_sub_lots: List[ShareLot] = []

            candidates = [
                lot for lot in self.lots
                if lot.symbol == sale.symbol
                and lot.acquisition_date <= sale.sale_date
                and lot.remaining_shares > 1e-6
                and (lot.disposal_date is None or lot.disposal_date >= sale.sale_date)
            ]
            candidates.sort(key=lambda lot: lot.acquisition_date)

            for lot in candidates:
                if remaining_to_match <= 1e-6:
                    break
                take = min(lot.remaining_shares, remaining_to_match)
                proceeds_for_take = (
                    round(sale.gross_proceeds_usd * (take / sale.quantity), 2)
                    if sale.quantity > 1e-6 else 0.0
                )

                if take >= lot.remaining_shares - 1e-6:
                    # Fully consumes this lot - no split needed.
                    lot.disposal_date = sale.sale_date
                    lot.disposal_qty = (lot.disposal_qty or 0.0) + take
                    lot.remaining_shares = 0.0
                    lot.status = LotStatus.FULLY_SOLD
                    allocations[lot.lot_id] = allocations.get(lot.lot_id, 0.0) + proceeds_for_take
                else:
                    # Partial sale: split into a disposed sub-lot (sold portion) and shrink
                    # the original lot down to the still-active remaining portion. gross_shares/
                    # withheld_shares are historical facts about the original vest/purchase and
                    # are not meaningfully splittable - they are left on the remaining portion
                    # and mirrored (not re-derived) on the disposed sub-lot since neither feeds
                    # into any Table A3 valuation figure (only net_shares does).
                    # Unique per split: two partial sales of one lot on the same day would
                    # otherwise share an id and their proceeds would be counted twice.
                    base_id = f"{lot.lot_id}-SOLD-{sale.sale_date.strftime('%Y%m%d')}"
                    existing_ids = {l.lot_id for l in self.lots} | {l.lot_id for l in new_sub_lots}
                    sub_id, seq = base_id, 2
                    while sub_id in existing_ids:
                        sub_id, seq = f"{base_id}-{seq}", seq + 1
                    disposed = ShareLot(
                        lot_id=sub_id,
                        symbol=lot.symbol,
                        plan_type=lot.plan_type,
                        acquisition_date=lot.acquisition_date,
                        gross_shares=take,
                        withheld_shares=0.0,
                        net_shares=take,
                        vest_fmv_usd=lot.vest_fmv_usd,
                        cost_basis_per_share_usd=lot.cost_basis_per_share_usd,
                        remaining_shares=0.0,
                        status=LotStatus.FULLY_SOLD,
                        grant_number=lot.grant_number,
                        grant_date=lot.grant_date,
                        disposal_date=sale.sale_date,
                        disposal_qty=take,
                        notes=f"Split from {lot.lot_id} on partial sale of {sale.sale_date}",
                    )
                    lot.net_shares -= take
                    lot.remaining_shares -= take
                    lot.status = LotStatus.PARTIALLY_SOLD
                    new_sub_lots.append(disposed)
                    allocations[disposed.lot_id] = proceeds_for_take

                remaining_to_match -= take

            if new_sub_lots:
                self.lots.extend(new_sub_lots)
                self.lots.sort(key=lambda x: x.acquisition_date)

            enriched_sales.append(SaleEvent(
                sale_date=sale.sale_date,
                symbol=sale.symbol,
                quantity=sale.quantity,
                price_usd=sale.price_usd,
                gross_proceeds_usd=sale.gross_proceeds_usd,
                matched_lot_id=next(iter(allocations)) if len(allocations) == 1 else None,
                lot_allocations=allocations,
                unmatched_quantity=max(0.0, remaining_to_match),
                net_credit_usd=sale.net_credit_usd,
            ))

        return enriched_sales
