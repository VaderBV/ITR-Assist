"""E*TRADE Broker Adapter integrating all E*TRADE document parsers."""
from typing import List, Optional, Tuple

from itr_assist.models import DividendEvent, Form1042SData, ShareLot, StatementPeriodSummary
from itr_assist.parsers.base import BaseBrokerAdapter
from itr_assist.parsers.etrade.benefit_history import ETradeBenefitHistoryParser
from itr_assist.parsers.etrade.holdings import ETradeHoldingsParser
from itr_assist.parsers.etrade.statements import ETradeStatementParser
from itr_assist.parsers.etrade.tax_documents import ETradeTaxDocumentParser


class ETradeAdapter(BaseBrokerAdapter):
    """Unified document adapter for E*TRADE / Morgan Stanley at Work."""

    def __init__(self):
        self._benefit_parser = ETradeBenefitHistoryParser()
        self._holdings_parser = ETradeHoldingsParser()
        self._statement_parser = ETradeStatementParser()
        self._tax_parser = ETradeTaxDocumentParser()

    @property
    def broker_name(self) -> str:
        return "E*TRADE"

    def parse_benefit_history(self, file_path: str) -> List[ShareLot]:
        """Parse E*TRADE BenefitHistory.xlsx."""
        return self._benefit_parser.parse(file_path)

    def parse_holdings(self, file_path: str) -> List[ShareLot]:
        """Parse E*TRADE ByStatus_expanded.xlsx."""
        return self._holdings_parser.parse(file_path)

    def parse_statements(self, file_paths: List[str], symbol_hint: Optional[str] = None) -> Tuple[List[StatementPeriodSummary], List[DividendEvent]]:
        """Parse E*TRADE client statement PDFs."""
        return self._statement_parser.parse(file_paths, symbol_hint=symbol_hint)

    def parse_tax_documents(self, file_path: str) -> Optional[Form1042SData]:
        """Parse E*TRADE / Morgan Stanley Form 1042-S PDF."""
        return self._tax_parser.parse(file_path)
