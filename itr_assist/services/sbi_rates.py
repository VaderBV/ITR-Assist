"""Service for fetching and querying historical SBI TT Buying Rates."""
from calendar import monthrange
from datetime import date, datetime, timedelta
import os
from typing import Dict, Optional, Tuple
import pandas as pd
import requests


SBI_USD_CSV_URL = (
    "https://raw.githubusercontent.com/sahilgupta/sbi-fx-ratekeeper/master/csv_files/SBI_REFERENCE_RATES_USD.csv"
)
DEFAULT_CACHE_PATH = os.path.join("data", "cache", "SBI_REFERENCE_RATES_USD.csv")


class SBIRateService:
    """Manages historical SBI TT Buying Rates with offline caching and Rule 115/128 helpers."""

    def __init__(self, cache_path: str = DEFAULT_CACHE_PATH, auto_download: bool = True):
        self.cache_path = cache_path
        self._rates: Dict[date, float] = {}
        self._sorted_dates = []

        if auto_download:
            self._ensure_cache()
        self._load_cache()

    def _ensure_cache(self) -> None:
        """Fetch the latest SBI rates CSV from upstream repository if internet is available, falling back to disk cache."""
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            resp = requests.get(SBI_USD_CSV_URL, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(self.cache_path, "wb") as f:
                    f.write(resp.content)
        except Exception:
            # If network is unavailable or request times out, fall back to existing local disk cache
            if not os.path.exists(self.cache_path):
                raise FileNotFoundError(
                    f"Could not download SBI rates from {SBI_USD_CSV_URL} and no local cache found at {self.cache_path}"
                )

    def _load_cache(self) -> None:
        """Parse cached CSV into date -> TT BUY mapping."""
        if not os.path.exists(self.cache_path):
            raise FileNotFoundError(f"SBI Rates cache not found at {self.cache_path}")

        df = pd.read_csv(self.cache_path)
        for _, row in df.iterrows():
            d_str = str(row.get("DATE", "")).strip().split(" ")[0]
            try:
                d_val = datetime.strptime(d_str, "%Y-%m-%d").date()
                rate_val = float(row.get("TT BUY", 0.0) or 0.0)
                if rate_val > 0.0:
                    self._rates[d_val] = rate_val
            except (ValueError, TypeError):
                continue

        self._sorted_dates = sorted(self._rates.keys())

    def get_rate(self, target_date: date) -> float:
        """Return the SBI TT Buying Rate for target_date (or most recent prior trading day)."""
        if not self._sorted_dates:
            raise ValueError("No SBI rates loaded.")

        if target_date in self._rates:
            return self._rates[target_date]

        # Step backwards up to 10 days for weekends / public holidays
        cur = target_date - timedelta(days=1)
        while cur >= self._sorted_dates[0]:
            if cur in self._rates:
                return self._rates[cur]
            cur -= timedelta(days=1)

        # Fallback to earliest available rate
        return self._rates[self._sorted_dates[0]]

    def get_rule_115_dividend_rate(self, dividend_date: date) -> Tuple[date, float]:
        """
        Rule 115(1) rate for dividend income:
        Telegraphic Transfer Buying Rate of SBI on the last day of the month
        immediately preceding the month in which dividend is declared/paid.
        """
        # Determine preceding month
        year = dividend_date.year
        month = dividend_date.month - 1
        if month == 0:
            month = 12
            year -= 1

        last_day_num = monthrange(year, month)[1]
        preceding_month_end = date(year, month, last_day_num)
        rate = self.get_rate(preceding_month_end)
        return preceding_month_end, rate

    def get_rule_128_rate(self, deduction_date: date) -> Tuple[date, float]:
        """
        Rule 128(5)(ii) rate for Foreign Tax Credit (FTC):
        Telegraphic Transfer Buying Rate of SBI on the last day of the month
        immediately preceding the month in which the foreign tax was paid or deducted.
        (Not the rate on the deduction date itself - verified against Rule 128(5)(ii) text.)
        """
        year = deduction_date.year
        month = deduction_date.month - 1
        if month == 0:
            month = 12
            year -= 1

        last_day_num = monthrange(year, month)[1]
        preceding_month_end = date(year, month, last_day_num)
        rate = self.get_rate(preceding_month_end)
        return preceding_month_end, rate
