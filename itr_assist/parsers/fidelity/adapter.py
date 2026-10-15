"""Fidelity Broker Adapter skeleton for future extension."""
from typing import List, Optional, Tuple

from itr_assist.models import DividendEvent, Form1042SData, ShareLot, StatementPeriodSummary
from itr_assist.parsers.base import BaseBrokerAdapter


class FidelityAdapter(BaseBrokerAdapter):
    """
    Adapter for Fidelity NetBenefits / Fidelity Investments.
    Provides stubbed interfaces ready for Fidelity statement, holdings, and RSU history parsers.
    """

    @property
    def broker_name(self) -> str:
        return "Fidelity"

    def parse_benefit_history(self, file_path: str) -> List[ShareLot]:
        """Parse Fidelity NetBenefits Stock Plan History export."""
        raise NotImplementedError("Fidelity Benefit History parsing will be implemented with Fidelity sample data.")

    def parse_holdings(self, file_path: str) -> List[ShareLot]:
        """Parse Fidelity Position/Holdings export CSV."""
        raise NotImplementedError("Fidelity Holdings parsing will be implemented with Fidelity sample data.")

    def parse_statements(
        self,
        file_paths: List[str],
        symbol_hint: Optional[str] = None,
        calendar_year_hint: Optional[int] = None,
    ) -> Tuple[List[StatementPeriodSummary], List[DividendEvent]]:
        """Parse Fidelity periodic brokerage statements."""
        raise NotImplementedError("Fidelity statement parsing will be implemented with Fidelity sample data.")

    def parse_tax_documents(self, file_path: str, calendar_year_hint: Optional[int] = None) -> Optional[Form1042SData]:
        """Parse Fidelity Form 1042-S PDF."""
        raise NotImplementedError("Fidelity Form 1042-S parsing will be implemented with Fidelity sample data.")
