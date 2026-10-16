"""Domain models for ITR Assist."""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional, Tuple


# Prefix for any statutory field the source documents cannot supply (e.g. the employer's
# address, the broker account's opening date). Written in place of a made-up value so the
# workbook shows exactly what the taxpayer must fill in, and validation fails until they do.
PLACEHOLDER_PREFIX = "TO BE FILLED"


def is_placeholder(value: object) -> bool:
    """True for a value that stands in for a statutory field the documents could not supply."""
    return isinstance(value, str) and value.startswith(PLACEHOLDER_PREFIX)


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
    # FIFO allocation of this sale's quantity/proceeds across one or more lots, populated by
    # LotLedger.allocate_sales(). A single sell order can close out more than one vest/purchase
    # lot (e.g. selling 20 shares when lot A has 12 remaining and lot B has 20).
    lot_allocations: Dict[str, float] = field(default_factory=dict)
    # Shares this sale couldn't be matched to any active lot for (e.g. the lot was sold/released
    # in a year whose statements weren't supplied, so no candidate lot had enough remaining
    # shares). Nonzero means gross_proceeds in lot_allocations understates the true sale
    # proceeds - surfaced as a validation finding rather than silently dropped.
    unmatched_quantity: float = 0.0
    # Net cash actually credited to the account (statement "Credits" column: gross minus
    # commission/fees). Gross proceeds stay quantity x price; this feeds the account's cash.
    net_credit_usd: float = 0.0


@dataclass
class DividendEvent:
    pay_date: date
    symbol: str
    gross_amount_usd: float
    tax_withheld_usd: float
    tax_deduction_date: Optional[date] = None
    record_date: Optional[date] = None
    shares_count: Optional[float] = None
    rate_per_share: Optional[float] = None
    lot_allocations: Dict[str, float] = field(default_factory=dict)
    # False when the statement showed no matching Tax Withholding line: tax_withheld_usd is
    # then 0, never an assumed rate, and validation flags it for the taxpayer to confirm.
    tax_line_found: bool = True


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
    # Period-end positions from the statement's holdings section, keyed by ticker:
    # quantity and the statement's own period-end share price (e.g. "ACME CORP (ACME)
    # 40.000 $150.000 ..."). shares_held is the total quantity across all positions.
    holdings_qty: Dict[str, float] = field(default_factory=dict)
    holdings_price: Dict[str, float] = field(default_factory=dict)
    # Security description as the statement prints it, keyed by ticker ("ACME CORP").
    holdings_name: Dict[str, str] = field(default_factory=dict)
    # Interest income credited during the period (e.g. bank-deposit sweep interest).
    interest_usd: float = 0.0
    # Dated interest credits (activity date, USD). interest_usd is their sum; the dates are
    # needed to convert each credit at its own Rule 115 rate.
    interest_events: List[Tuple[date, float]] = field(default_factory=list)
    # Cash roll-forward printed on the statement: OPENING CASH, every row of the "CASH FLOW
    # ACTIVITY BY DATE" table dated by the day it hits cash (settlement date), and the
    # CLOSING CASH. opening + sum(events) == cash_balance_usd is checked by CashTimeline.
    opening_cash_usd: Optional[float] = None
    cash_events: List[Tuple[date, float, str]] = field(default_factory=list)


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
    # Withholding agent's (the custodian's) address as printed in Form 1042-S box 12; empty when
    # it could not be read with confidence, in which case the taxpayer must supply it.
    withholding_agent_address: str = ""
    withholding_agent_zip: str = ""


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
