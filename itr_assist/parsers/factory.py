"""Broker parser factory for resolving and auto-detecting broker adapters."""
from typing import Dict, Type
from pypdf import PdfReader

from itr_assist.parsers.base import BaseBrokerAdapter
from itr_assist.parsers.etrade.adapter import ETradeAdapter
from itr_assist.parsers.fidelity.adapter import FidelityAdapter


class BrokerParserFactory:
    """Factory to retrieve or auto-detect broker-specific document adapters."""

    _registry: Dict[str, Type[BaseBrokerAdapter]] = {
        "etrade": ETradeAdapter,
        "morgan_stanley": ETradeAdapter,
        "fidelity": FidelityAdapter,
    }

    @classmethod
    def register_adapter(cls, broker_key: str, adapter_cls: Type[BaseBrokerAdapter]) -> None:
        """Register a new broker adapter class."""
        cls._registry[broker_key.lower()] = adapter_cls

    @classmethod
    def get_adapter(cls, broker_name: str = "etrade") -> BaseBrokerAdapter:
        """Retrieve an instance of the broker adapter by name."""
        key = broker_name.lower().replace("*", "").replace(" ", "_")
        if key not in cls._registry:
            supported = ", ".join(cls._registry.keys())
            raise ValueError(f"Unsupported broker '{broker_name}'. Currently supported: {supported}")
        return cls._registry[key]()

    @classmethod
    def auto_detect(cls, file_path: str) -> BaseBrokerAdapter:
        """
        Auto-detect the appropriate broker adapter by inspecting document contents.
        Supports PDF statements and Excel exports.
        """
        # 1. If PDF file, inspect first page text
        if file_path.lower().endswith(".pdf"):
            try:
                reader = PdfReader(file_path)
                if len(reader.pages) > 0:
                    first_page_text = (reader.pages[0].extract_text() or "").upper()
                    if "FIDELITY" in first_page_text:
                        return cls.get_adapter("fidelity")
                    if any(term in first_page_text for term in ["E*TRADE", "ETRADE", "MORGAN STANLEY"]):
                        return cls.get_adapter("etrade")
            except Exception:
                pass

        # 2. Default to E*TRADE if file is from E*TRADE or unknown
        return cls.get_adapter("etrade")
