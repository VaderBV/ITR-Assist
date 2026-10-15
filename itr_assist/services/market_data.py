"""Service for fetching and querying historical stock prices (Yahoo Finance)."""
from datetime import date, datetime, timedelta
import json
import os
from typing import Any, Dict, List, Optional, Tuple
import requests

from itr_assist.models import ShareLot
from itr_assist.services.sbi_rates import SBIRateService


DEFAULT_CACHE_DIR = os.path.join("data", "cache")
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


class MarketDataService:
    """Manages historical daily stock prices with offline caching."""

    def __init__(self, cache_dir: str = DEFAULT_CACHE_DIR, auto_download: bool = True):
        self.cache_dir = cache_dir
        self.auto_download = auto_download
        self._price_cache: Dict[str, Dict[date, Dict[str, float]]] = {}

    def _get_cache_path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, f"{symbol}_prices.json")

    def load_symbol(self, symbol: str) -> None:
        """Load or fetch daily prices for symbol covering 2024 to present."""
        if symbol in self._price_cache:
            return

        cache_path = self._get_cache_path(symbol)
        if not os.path.exists(cache_path) and self.auto_download:
            try:
                self._fetch_and_cache(symbol)
            except Exception:
                # Mirrors SBIRateService._ensure_cache: if the network is unavailable, blocked,
                # or Yahoo Finance errors, fall through to the cache-missing check below instead
                # of letting a raw network exception crash the whole generation pipeline.
                pass

        if not os.path.exists(cache_path):
            raise FileNotFoundError(f"Market data cache for {symbol} not found at {cache_path}")

        with open(cache_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        parsed: Dict[date, Dict[str, float]] = {}
        for d_str, ohlc in raw_data.items():
            d_val = datetime.strptime(d_str, "%Y-%m-%d").date()
            parsed[d_val] = {
                "open": float(ohlc["open"]),
                "high": float(ohlc["high"]),
                "low": float(ohlc["low"]),
                "close": float(ohlc["close"])
            }

        self._price_cache[symbol] = parsed

    def _fetch_and_cache(self, symbol: str) -> None:
        """Fetch historical chart data from Yahoo Finance and cache locally."""
        os.makedirs(self.cache_dir, exist_ok=True)
        # Fetch 5 years of daily data
        params = {"range": "5y", "interval": "1d"}
        url = YAHOO_CHART_URL.format(symbol=symbol)
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]

        daily_dict: Dict[str, Dict[str, float]] = {}
        for idx, ts in enumerate(timestamps):
            dt = datetime.fromtimestamp(ts).date()
            o = quotes["open"][idx]
            h = quotes["high"][idx]
            l = quotes["low"][idx]
            c = quotes["close"][idx]

            if None in (o, h, l, c):
                continue

            daily_dict[dt.strftime("%Y-%m-%d")] = {
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4)
            }

        cache_path = self._get_cache_path(symbol)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(daily_dict, f, indent=2)

    def get_prices(self, target_date: date, symbol: str) -> Dict[str, float]:
        """Return OHLC prices for target_date (or step back to most recent trading day)."""
        self.load_symbol(symbol)
        cache = self._price_cache[symbol]

        if target_date in cache:
            return cache[target_date]

        # Step back up to 10 days for weekends / holidays
        cur = target_date - timedelta(days=1)
        earliest_date = min(cache.keys())
        while cur >= earliest_date:
            if cur in cache:
                return cache[cur]
            cur -= timedelta(days=1)

        raise ValueError(f"No price data available for {symbol} near {target_date}")

    def get_peak_for_lot(
        self,
        lot: ShareLot,
        calendar_year: int,
        sbi_service: SBIRateService,
        use_eod_close: bool = True
    ) -> Dict[str, Any]:
        """
        Calculate Schedule FA Table A3 Peak Balance for a specific lot during calendar_year.
        Evaluates daily (shares * price * sbi_ttbr) across active days in the CY.
        By default, uses EOD Closing Price (standard tax software practice).
        """
        self.load_symbol(lot.symbol)
        cache = self._price_cache[lot.symbol]

        cy_start = date(calendar_year, 1, 1)
        cy_end = date(calendar_year, 12, 31)

        # Lot start is max(acq_date, cy_start)
        active_start = max(lot.acquisition_date, cy_start)
        active_end = cy_end
        if lot.disposal_date and lot.disposal_date < cy_end:
            active_end = lot.disposal_date

        peak_inr = -1.0
        peak_date = active_start
        peak_price_usd = 0.0
        peak_rate_inr = 0.0

        for d, ohlc in cache.items():
            if active_start <= d <= active_end:
                eval_price = ohlc["close"] if use_eod_close else ohlc["high"]
                ttbr = sbi_service.get_rate(d)
                val_inr = lot.net_shares * eval_price * ttbr

                if val_inr > peak_inr:
                    peak_inr = val_inr
                    peak_date = d
                    peak_price_usd = eval_price
                    peak_rate_inr = ttbr

        return {
            "peak_balance_inr": round(peak_inr),
            "peak_date": peak_date,
            "peak_price_usd": peak_price_usd,
            "peak_rate_inr": peak_rate_inr,
            "shares": lot.net_shares
        }

    def get_closing_for_lot(
        self,
        lot: ShareLot,
        calendar_year: int,
        sbi_service: SBIRateService
    ) -> Dict[str, Any]:
        """
        Calculate Schedule FA Table A3 Closing Balance as of Dec 31 of calendar_year.
        """
        cy_end = date(calendar_year, 12, 31)

        # If sold before Dec 31, closing balance is 0
        if lot.disposal_date and lot.disposal_date < cy_end:
            return {
                "closing_balance_inr": 0,
                "closing_date": cy_end,
                "closing_price_usd": 0.0,
                "closing_rate_inr": sbi_service.get_rate(cy_end),
                "shares": 0.0
            }

        ohlc = self.get_prices(cy_end, lot.symbol)
        close_price = ohlc["close"]
        ttbr = sbi_service.get_rate(cy_end)
        val_inr = round(lot.net_shares * close_price * ttbr)

        return {
            "closing_balance_inr": val_inr,
            "closing_date": cy_end,
            "closing_price_usd": close_price,
            "closing_rate_inr": ttbr,
            "shares": lot.net_shares
        }
