"""Service for fetching and querying historical SBI TT Buying Rates."""
from calendar import monthrange
from datetime import date, datetime, timedelta
import os
import shutil
from typing import Dict, Optional, Tuple
import pandas as pd
import requests

from itr_assist.services.cache_paths import BUNDLED_SBI_CSV, default_cache_dir


SBI_USD_CSV_URL = (
    "https://raw.githubusercontent.com/sahilgupta/sbi-fx-ratekeeper/master/csv_files/SBI_REFERENCE_RATES_USD.csv"
)
SBI_CSV_NAME = "SBI_REFERENCE_RATES_USD.csv"
# SBI publishes on banking days only; 7 calendar days spans weekends plus the longest holiday
# runs. A longer gap is missing data, and quietly reusing a weeks-old rate would be wrong.
MAX_RATE_LOOKBACK_DAYS = 7


class SBIRateService:
    """Manages historical SBI TT Buying Rates with offline caching and Rule 115/128 helpers."""

    def __init__(self, cache_path: Optional[str] = None, auto_download: bool = True):
        self.cache_path = cache_path or os.path.join(default_cache_dir(), SBI_CSV_NAME)
        self._rates: Dict[date, float] = {}
        self._sorted_dates = []

        if auto_download:
            self._ensure_cache()
        self._load_cache()

    def _ensure_cache(self) -> None:
        """Refresh the cached CSV from upstream; on any network failure keep the existing cache
        (or, on a first offline run, the snapshot bundled with the package)."""
        try:
            resp = requests.get(SBI_USD_CSV_URL, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
                with open(self.cache_path, "wb") as f:
                    f.write(resp.content)
        except Exception:
            pass

    def _load_cache(self) -> None:
        """Parse the cached (else bundled) CSV into a date -> TT BUY mapping."""
        path = self.cache_path
        if not os.path.exists(path):
            if not os.path.exists(BUNDLED_SBI_CSV):
                raise FileNotFoundError(
                    f"SBI rates not found: could not download {SBI_USD_CSV_URL} and no cached copy at {self.cache_path}"
                )
            try:
                os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
                shutil.copyfile(BUNDLED_SBI_CSV, self.cache_path)
            except OSError:
                path = BUNDLED_SBI_CSV  # read-only home: read the bundled snapshot in place
            else:
                path = self.cache_path

        df = pd.read_csv(path)
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

    def get_rate_with_date(self, target_date: date) -> Tuple[date, float]:
        """(date the rate was published, TT buying rate) for target_date: that day's rate, or the
        most recent one published within MAX_RATE_LOOKBACK_DAYS before it (weekends/holidays).
        Raises ValueError rather than reaching further back or forward."""
        if not self._sorted_dates:
            raise ValueError("No SBI rates loaded.")

        first, last = self._sorted_dates[0], self._sorted_dates[-1]
        cur = target_date
        while cur >= target_date - timedelta(days=MAX_RATE_LOOKBACK_DAYS):
            if cur in self._rates:
                return cur, self._rates[cur]
            cur -= timedelta(days=1)

        if target_date < first:
            raise ValueError(
                f"No SBI TT buying rate for {target_date.isoformat()}: the rate history starts on "
                f"{first.isoformat()}. Enter the INR value for this date manually."
            )
        if target_date > last:
            raise ValueError(
                f"No SBI TT buying rate for {target_date.isoformat()}: the rate history ends on "
                f"{last.isoformat()}. Re-run with internet access to refresh it."
            )
        raise ValueError(
            f"No SBI TT buying rate within {MAX_RATE_LOOKBACK_DAYS} days before {target_date.isoformat()} "
            f"(gap in the published rate history). Enter the INR value for this date manually."
        )

    def get_rate(self, target_date: date) -> float:
        """Return the SBI TT Buying Rate for target_date (or the most recent prior banking day)."""
        return self.get_rate_with_date(target_date)[1]

    def _preceding_month_end_rate(self, event_date: date) -> Tuple[date, float]:
        """Shared mechanism behind Rule 115's Explanation clauses (e), (f) and Rule 128(5)(ii):
        TTBR on the last day of the month immediately preceding the month of event_date."""
        year = event_date.year
        month = event_date.month - 1
        if month == 0:
            month = 12
            year -= 1

        last_day_num = monthrange(year, month)[1]
        preceding_month_end = date(year, month, last_day_num)
        rate = self.get_rate(preceding_month_end)
        return preceding_month_end, rate

    def get_rule_115_dividend_rate(self, dividend_date: date) -> Tuple[date, float]:
        """
        Explanation to Rule 115, clause (e) - foreign dividend income:
        Telegraphic Transfer Buying Rate of SBI on the last day of the month
        immediately preceding the month in which the dividend is declared, distributed, or paid.
        """
        return self._preceding_month_end_rate(dividend_date)

    def get_rule_115_capital_gains_rate(self, transfer_date: date) -> Tuple[date, float]:
        """
        Explanation to Rule 115, clause (f) - capital gains on transfer of a foreign asset:
        TTBR on the last day of the month immediately preceding the month of transfer. For a
        capital-gains computation only; Schedule FA's sale-proceeds column converts at the
        31-Dec rate instead (CBDT Schedule FA guide), so the valuation engine does not use this.
        """
        return self._preceding_month_end_rate(transfer_date)

    def get_rule_128_rate(self, deduction_date: date) -> Tuple[date, float]:
        """
        Rule 128(5)(ii) rate for Foreign Tax Credit (FTC):
        Telegraphic Transfer Buying Rate of SBI on the last day of the month
        immediately preceding the month in which the foreign tax was paid or deducted.
        (Not the rate on the deduction date itself - verified against Rule 128(5)(ii) text.)
        """
        return self._preceding_month_end_rate(deduction_date)
