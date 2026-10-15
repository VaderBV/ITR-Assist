"""Modular document parsing package with multi-broker support."""
from itr_assist.parsers.base import (
    BaseBenefitHistoryParser,
    BaseBrokerAdapter,
    BaseHoldingsParser,
    BaseStatementParser,
    BaseTaxDocumentParser,
)
from itr_assist.parsers.common import clean_currency, parse_date
from itr_assist.parsers.etrade import (
    ETradeAdapter,
    ETradeBenefitHistoryParser,
    ETradeHoldingsParser,
    ETradeStatementParser,
    ETradeTaxDocumentParser,
)
from itr_assist.parsers.factory import BrokerParserFactory
from itr_assist.parsers.fidelity import FidelityAdapter

# Backward compatibility aliases
BenefitHistoryParser = ETradeBenefitHistoryParser
HoldingsParser = ETradeHoldingsParser
StatementParser = ETradeStatementParser
Form1042SParser = ETradeTaxDocumentParser

__all__ = [
    "BaseBenefitHistoryParser",
    "BaseBrokerAdapter",
    "BaseHoldingsParser",
    "BaseStatementParser",
    "BaseTaxDocumentParser",
    "BrokerParserFactory",
    "clean_currency",
    "parse_date",
    "ETradeAdapter",
    "ETradeBenefitHistoryParser",
    "ETradeHoldingsParser",
    "ETradeStatementParser",
    "ETradeTaxDocumentParser",
    "FidelityAdapter",
    "BenefitHistoryParser",
    "HoldingsParser",
    "StatementParser",
    "Form1042SParser",
]
