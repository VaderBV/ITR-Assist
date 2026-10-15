"""Abstract base classes and interfaces for broker document parsing."""
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from itr_assist.models import DividendEvent, Form1042SData, ShareLot, StatementPeriodSummary


class BaseBenefitHistoryParser(ABC):
    """Abstract interface for parsing broker RSU/ESPP benefit history."""

    @abstractmethod
    def parse(self, file_path: str) -> List[ShareLot]:
        """Parse benefit history file and return list of all share lots."""
        pass


class BaseHoldingsParser(ABC):
    """Abstract interface for parsing broker current holdings snapshot."""

    @abstractmethod
    def parse(self, file_path: str) -> List[ShareLot]:
        """Parse holdings file and return list of active share lots."""
        pass


class BaseStatementParser(ABC):
    """Abstract interface for parsing periodic client account statements."""

    @abstractmethod
    def parse(
        self,
        file_paths: List[str],
        symbol_hint: Optional[str] = None,
        calendar_year_hint: Optional[int] = None,
    ) -> Tuple[List[StatementPeriodSummary], List[DividendEvent]]:
        """Parse account statement files and return period summaries and dividend events.

        calendar_year_hint is the user-selected calendar year (first year of the FY being
        filed). It is used only as a last-resort fallback when a statement's own text does not
        declare its year — it must never override a year actually read from the document.
        """
        pass


class BaseTaxDocumentParser(ABC):
    """Abstract interface for parsing Form 1042-S / annual tax documents."""

    @abstractmethod
    def parse(self, file_path: str, calendar_year_hint: Optional[int] = None) -> Optional[Form1042SData]:
        """Parse tax document and return Form 1042-S data.

        calendar_year_hint is used only as a last-resort fallback when the document's own text
        does not state its calendar year.
        """
        pass


class BaseBrokerAdapter(ABC):
    """
    Abstract adapter for a specific brokerage (e.g., E*TRADE, Fidelity, Schwab).
    Combines individual document parsers into a unified broker interface.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Name of the brokerage."""
        pass

    @abstractmethod
    def parse_benefit_history(self, file_path: str) -> List[ShareLot]:
        """Extract historical share lots (vests & ESPP purchases)."""
        pass

    @abstractmethod
    def parse_holdings(self, file_path: str) -> List[ShareLot]:
        """Extract active share lots from current holdings snapshot."""
        pass

    @abstractmethod
    def parse_statements(
        self,
        file_paths: List[str],
        symbol_hint: Optional[str] = None,
        calendar_year_hint: Optional[int] = None,
    ) -> Tuple[List[StatementPeriodSummary], List[DividendEvent]]:
        """Extract periodic statement summaries and dividend transactions."""
        pass

    @abstractmethod
    def parse_tax_documents(self, file_path: str, calendar_year_hint: Optional[int] = None) -> Optional[Form1042SData]:
        """Extract Form 1042-S foreign income and tax withholding data."""
        pass
