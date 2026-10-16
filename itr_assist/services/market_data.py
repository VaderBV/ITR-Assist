"""Service for fetching and querying historical daily stock prices."""
from datetime import date, datetime, timedelta, timezone
import json
import os
from typing import Any, Dict, Optional, Tuple
import requests

from itr_assist.models import ShareLot
from itr_assist.services.cache_paths import default_cache_dir
from itr_assist.services.sbi_rates import SBIRateService


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Fallback for browser builds: Yahoo Finance sends no CORS headers, so a direct in-browser
# fetch is always blocked (confirmed - not an intermittent issue). Twelve Data's free tier
# does support direct browser calls (Access-Control-Allow-Origin: *, confirmed) and works for
# any public symbol, not just one company - the user supplies their own free key (no backend
# of ours is involved, never shipped/committed in source).
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# Weekends plus the longest US market closures; a longer hole is missing data.
MAX_PRICE_LOOKBACK_DAYS = 7
# A cache whose newest close is older than this is re-fetched before use.
STALE_AFTER_DAYS = 4


class MarketDataService:
    """Manages historical daily stock prices with offline caching."""

    def __init__(self, cache_dir: Optional[str] = None, auto_download: bool = True, api_key: Optional[str] = None):
        self.cache_dir = cache_dir or default_cache_dir()
        self.auto_download = auto_download
        self.api_key = api_key
        self._price_cache: Dict[str, Dict[date, Dict[str, float]]] = {}
        # Symbols with no daily prices at all (provider blocked/offline and nothing cached).
        # Valuation then falls back to statement month-end prices and flags figures as degraded.
        self.unavailable_symbols: set = set()
        # Symbols whose cache could not be refreshed: symbol -> newest cached trading day.
        # Dates after it have no prices; lookups there fail rather than reuse an old close.
        self.stale_symbols: Dict[str, date] = {}

    def _get_cache_path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, f"{symbol}_prices.json")

    def load_symbol(self, symbol: str) -> None:
        """Load daily prices for symbol from cache, fetching when missing or stale."""
        if symbol in self._price_cache:
            return

        cache_path = self._get_cache_path(symbol)
        parsed = self._read_cache(cache_path) if os.path.exists(cache_path) else {}
        newest = max(parsed) if parsed else None
        if self.auto_download and (newest is None or newest < date.today() - timedelta(days=STALE_AFTER_DAYS)):
            try:
                self._fetch_and_cache(symbol)
                parsed = self._read_cache(cache_path)
                newest = max(parsed) if parsed else None
            except Exception:
                # Network unavailable/blocked or provider error: keep whatever is cached.
                pass

        if not parsed:
            self.unavailable_symbols.add(symbol)
        elif newest < date.today() - timedelta(days=STALE_AFTER_DAYS):
            self.stale_symbols[symbol] = newest
        self._price_cache[symbol] = parsed

    @staticmethod
    def _read_cache(cache_path: str) -> Dict[date, Dict[str, float]]:
        with open(cache_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        parsed: Dict[date, Dict[str, float]] = {}
        for d_str, ohlc in raw_data.items():
            parsed[datetime.strptime(d_str, "%Y-%m-%d").date()] = {
                "open": float(ohlc["open"]),
                "high": float(ohlc["high"]),
                "low": float(ohlc["low"]),
                "close": float(ohlc["close"]),
            }
        return parsed

    def _fetch_and_cache(self, symbol: str) -> None:
        """Fetch historical daily prices and cache locally.

        Tries Yahoo Finance first (works fine for the desktop/CLI build, no CORS
        restriction there). If that fails - which it always will in a browser build, since
        Yahoo sends no Access-Control-Allow-Origin header - and the caller supplied an API
        key, falls back to Twelve Data (confirmed CORS-open, works for any public symbol).
        """
        try:
            daily_dict = self._fetch_from_yahoo(symbol)
        except Exception:
            if not self.api_key:
                raise
            daily_dict = self._fetch_from_twelve_data(symbol)

        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self._get_cache_path(symbol), "w", encoding="utf-8") as f:
            json.dump(daily_dict, f, indent=2)

    def _fetch_from_yahoo(self, symbol: str) -> Dict[str, Dict[str, float]]:
        # Fetch 5 years of daily data
        params = {"range": "5y", "interval": "1d"}
        url = YAHOO_CHART_URL.format(symbol=symbol)
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]
        # Bar timestamps are the session open in UTC; shift by the exchange's own UTC offset so
        # the trading day doesn't depend on the machine's local time zone.
        gmtoffset = int(result.get("meta", {}).get("gmtoffset", 0) or 0)

        daily_dict: Dict[str, Dict[str, float]] = {}
        for idx, ts in enumerate(timestamps):
            dt = datetime.fromtimestamp(ts + gmtoffset, tz=timezone.utc).date()
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
        return daily_dict

    def _fetch_from_twelve_data(self, symbol: str) -> Dict[str, Dict[str, float]]:
        params = {
            "symbol": symbol,
            "interval": "1day",
            "outputsize": 5000,  # ~ 5 years of trading days, same window as the Yahoo path
            "apikey": self.api_key,
            "format": "JSON",
        }
        resp = requests.get(TWELVE_DATA_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "error" or "values" not in data:
            raise ValueError(f"Twelve Data error for {symbol}: {data.get('message', data)}")

        daily_dict: Dict[str, Dict[str, float]] = {}
        for row in data["values"]:
            daily_dict[row["datetime"]] = {
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
            }
        return daily_dict

    def get_prices(self, target_date: date, symbol: str) -> Dict[str, float]:
        """OHLC for target_date, or the most recent trading day within MAX_PRICE_LOOKBACK_DAYS
        before it (weekends/holidays). Raises ValueError rather than reaching further back."""
        found = self.close_on_or_before(symbol, target_date)
        if found is None:
            raise ValueError(f"No price data available for {symbol} on or shortly before {target_date}")
        return self._price_cache[symbol][found[0]]

    def close_on_or_before(self, symbol: str, target_date: date) -> Optional[Tuple[date, float]]:
        """(trading day, close) for target_date or the nearest trading day up to
        MAX_PRICE_LOOKBACK_DAYS before it; None when there is no such price."""
        self.load_symbol(symbol)
        cache = self._price_cache[symbol]
        for back in range(MAX_PRICE_LOOKBACK_DAYS + 1):
            d = target_date - timedelta(days=back)
            if d in cache:
                return d, cache[d]["close"]
        return None

    def daily_closes(self, symbol: str, start: date, end: date) -> Dict[date, float]:
        """Every trading day's close for symbol within [start, end]."""
        self.load_symbol(symbol)
        return {d: ohlc["close"] for d, ohlc in self._price_cache[symbol].items() if start <= d <= end}

    def get_peak_for_lot(
        self,
        lot: ShareLot,
        calendar_year: int,
        sbi_service: SBIRateService,
        use_eod_close: bool = True,
    ) -> Dict[str, Any]:
        """Return the maximum INR value of a lot while it was held during the calendar year."""
        cy_start = date(calendar_year, 1, 1)
        cy_end = date(calendar_year, 12, 31)
        active_start = max(lot.acquisition_date, cy_start)
        active_end = min(lot.disposal_date or cy_end, cy_end)
        if active_start > active_end:
            raise ValueError(f"Lot {lot.lot_id} was not active during calendar year {calendar_year}")

        self.load_symbol(lot.symbol)
        cache = self._price_cache[lot.symbol]
        candidates = []
        for price_date, ohlc in cache.items():
            if active_start <= price_date <= active_end:
                price = ohlc["close"] if use_eod_close else ohlc["high"]
                rate = sbi_service.get_rate(price_date)
                candidates.append((lot.net_shares * price * rate, price_date, price, rate))

        if not candidates:
            raise ValueError(
                f"No verified daily market prices for {lot.symbol} while lot {lot.lot_id} "
                f"was held ({active_start} to {active_end})."
            )

        peak_inr, peak_date, peak_price, peak_rate = max(candidates, key=lambda item: item[0])
        return {
            "peak_balance_inr": round(peak_inr),
            "peak_date": peak_date,
            "peak_price_usd": peak_price,
            "peak_rate_inr": peak_rate,
            "shares": lot.net_shares,
            "degraded": False,
        }

    def get_closing_for_lot(
        self,
        lot: ShareLot,
        calendar_year: int,
        sbi_service: SBIRateService,
    ) -> Dict[str, Any]:
        """Return the verified calendar-year closing value for a lot."""
        cy_end = date(calendar_year, 12, 31)
        closing_rate = sbi_service.get_rate(cy_end)
        if lot.disposal_date and lot.disposal_date < cy_end:
            return {
                "closing_balance_inr": 0,
                "closing_date": cy_end,
                "closing_price_usd": 0.0,
                "closing_rate_inr": closing_rate,
                "shares": 0.0,
                "degraded": False,
                "sold_before_year_end": True,
            }

        found = self.close_on_or_before(lot.symbol, cy_end)
        if found is None:
            raise ValueError(
                f"No verified closing market price for {lot.symbol} on or shortly before {cy_end}."
            )
        price_date, close_price = found
        return {
            "closing_balance_inr": round(lot.net_shares * close_price * closing_rate),
            "closing_date": cy_end,
            "closing_price_date": price_date,
            "closing_price_usd": close_price,
            "closing_rate_inr": closing_rate,
            "shares": lot.net_shares,
            "degraded": False,
            "sold_before_year_end": False,
        }
