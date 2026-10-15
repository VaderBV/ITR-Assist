"""E*TRADE parsers and broker adapter."""
from itr_assist.parsers.etrade.adapter import ETradeAdapter
from itr_assist.parsers.etrade.benefit_history import ETradeBenefitHistoryParser
from itr_assist.parsers.etrade.holdings import ETradeHoldingsParser
from itr_assist.parsers.etrade.statements import ETradeStatementParser
from itr_assist.parsers.etrade.tax_documents import ETradeTaxDocumentParser

__all__ = [
    "ETradeAdapter",
    "ETradeBenefitHistoryParser",
    "ETradeHoldingsParser",
    "ETradeStatementParser",
    "ETradeTaxDocumentParser",
]
