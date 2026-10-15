"""Cross-document verification and reconciliation engine."""
from datetime import date
from typing import List, Optional

from itr_assist.models import Form1042SData, ReconciliationReport, ShareLot, StatementPeriodSummary
from itr_assist.reconciliation.lot_ledger import LotLedger


class DocumentVerifier:
    """Verifies consistency across Benefit History, Current Holdings, Statements, and 1042-S."""

    def __init__(self, ledger: LotLedger, holdings_lots: List[ShareLot]):
        self.ledger = ledger
        self.holdings_lots = holdings_lots

    def verify_holdings(self, as_of_date: Optional[date] = None) -> ReconciliationReport:
        """Verify reconstructed lot positions against current holdings export."""
        if as_of_date is None:
            # Default to the latest acquisition date in holdings
            as_of_date = max(l.acquisition_date for l in self.holdings_lots)

        discrepancies: List[str] = []

        total_holdings_shares = sum(l.remaining_shares for l in self.holdings_lots)
        total_reconstructed_shares = sum(l.remaining_shares for l in self.ledger.lots if l.remaining_shares > 0)

        # Detect sold lots (lots that had shares, but now have 0 remaining)
        sold_lots = [l for l in self.ledger.lots if l.is_sold_lot]
        active_lots = [l for l in self.ledger.lots if l.remaining_shares > 0]

        # Check total active share count
        if abs(total_holdings_shares - total_reconstructed_shares) > 0.001:
            discrepancies.append(
                f"Share count mismatch: Reconstructed active shares ({total_reconstructed_shares:.2f}) "
                f"!= Current Holdings shares ({total_holdings_shares:.2f})"
            )

        # Check lot-level alignment
        holdings_by_key = {
            (l.acquisition_date, l.plan_type, round(l.remaining_shares, 2)): l
            for l in self.holdings_lots
        }

        reconstructed_by_key = {
            (l.acquisition_date, l.plan_type, round(l.remaining_shares, 2)): l
            for l in active_lots
        }

        missing_in_holdings = []
        for key, lot in reconstructed_by_key.items():
            if key not in holdings_by_key:
                missing_in_holdings.append(lot)

        missing_in_reconstructed = []
        for key, lot in holdings_by_key.items():
            if key not in reconstructed_by_key:
                missing_in_reconstructed.append(lot)

        if missing_in_holdings:
            for l in missing_in_holdings:
                discrepancies.append(f"Reconstructed lot missing from Holdings: {l.lot_id} ({l.net_shares} shares)")

        if missing_in_reconstructed:
            for l in missing_in_reconstructed:
                discrepancies.append(f"Holdings lot missing from Benefit History: {l.lot_id} ({l.net_shares} shares)")

        status = "MATCH" if len(discrepancies) == 0 else "DISCREPANCY"

        return ReconciliationReport(
            status=status,
            as_of_date=as_of_date,
            total_reconstructed_shares=total_reconstructed_shares,
            total_holdings_shares=total_holdings_shares,
            reconstructed_lots_count=len(active_lots),
            holdings_lots_count=len(self.holdings_lots),
            sold_lots_count=len(sold_lots),
            active_lots=active_lots,
            sold_lots=sold_lots,
            discrepancies=discrepancies
        )

    def verify_tax_1042s(self, cy_dividends_usd: float, cy_tax_withheld_usd: float, form_1042s: Form1042SData) -> List[str]:
        """Verify calendar year statement dividends and tax against IRS Form 1042-S."""
        notes = []
        diff_div = abs(cy_dividends_usd - form_1042s.gross_dividend_usd)
        diff_tax = abs(cy_tax_withheld_usd - form_1042s.tax_withheld_usd)

        # Form 1042-S is rounded to the nearest dollar
        if diff_div > 1.0:
            notes.append(
                f"CY Gross Dividend discrepancy: Statement (${cy_dividends_usd:.2f}) "
                f"differs from Form 1042-S Box 2 (${form_1042s.gross_dividend_usd:.2f})"
            )
        else:
            notes.append(
                f"CY Gross Dividend RECONCILED: Statement ${cy_dividends_usd:.2f} rounds to 1042-S ${form_1042s.gross_dividend_usd:.2f}"
            )

        if diff_tax > 1.0:
            notes.append(
                f"CY Tax Withholding discrepancy: Statement (${cy_tax_withheld_usd:.2f}) "
                f"differs from Form 1042-S Box 7a (${form_1042s.tax_withheld_usd:.2f})"
            )
        else:
            notes.append(
                f"CY Tax Withholding RECONCILED: Statement ${cy_tax_withheld_usd:.2f} rounds to 1042-S ${form_1042s.tax_withheld_usd:.2f}"
            )

        return notes
