"""Domain models for ITR Assist."""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional


class PlanType(str, Enum):
    RSU = "RSU"
    ESPP = "ESPP"
    OPEN_MARKET = "OPEN_MARKET"
    OTHER = "OTHER"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_SOLD = "PARTIALLY_SOLD"
    FULLY_SOLD = "FULLY_SOLD"


@dataclass
class SaleEvent:
    sale_date: date
    symbol: str
    quantity: float
    price_usd: float
    gross_proceeds_usd: float
    matched_lot_id: Optional[str] = None
    cost_basis_usd: Optional[float] = None
    gain_loss_usd: Optional[float] = None


@dataclass
class DividendEvent:
    pay_date: date
    symbol: str
    gross_amount_usd: float
    tax_withheld_usd: float
    record_date: Optional[date] = None
    shares_count: Optional[float] = None
    rate_per_share: Optional[float] = None
    lot_allocations: Dict[str, float] = field(default_factory=dict)


@dataclass
class ShareLot:
    lot_id: str
    symbol: str
    plan_type: PlanType
    acquisition_date: date
    gross_shares: float
    withheld_shares: float
    net_shares: float
    vest_fmv_usd: float
    cost_basis_per_share_usd: float
    remaining_shares: float
    status: LotStatus = LotStatus.ACTIVE
    grant_number: Optional[str] = None
    grant_date: Optional[date] = None
    disposal_date: Optional[date] = None
    disposal_qty: float = 0.0
    notes: Optional[str] = None

    @property
    def is_sold_lot(self) -> bool:
        """A lot that was held at some point but currently has 0 sellable shares (sold lot)."""
        return self.remaining_shares == 0.0 and self.net_shares > 0.0


@dataclass
class StatementPeriodSummary:
    period_label: str
    start_date: date
    end_date: date
    beginning_value_usd: float
    ending_value_usd: float
    cash_balance_usd: float
    equities_value_usd: float
    shares_held: float
    dividends_received_usd: float = 0.0
    tax_withheld_usd: float = 0.0
    transfers_in_shares: float = 0.0


@dataclass
class Form1042SData:
    calendar_year: int
    recipient_name: str
    recipient_tin: str
    gross_dividend_usd: float
    tax_withheld_usd: float
    withholding_rate: float
    withholding_agent: str
    account_number: str


@dataclass
class ReconciliationReport:
    status: str  # 'MATCH' or 'DISCREPANCY'
    as_of_date: date
    total_reconstructed_shares: float
    total_holdings_shares: float
    reconstructed_lots_count: int
    holdings_lots_count: int
    sold_lots_count: int = 0
    active_lots: List[ShareLot] = field(default_factory=list)
    sold_lots: List[ShareLot] = field(default_factory=list)
    discrepancies: List[str] = field(default_factory=list)
