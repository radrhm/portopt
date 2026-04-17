"""Market data helpers — price fetching via yfinance with caching."""

import logging
import warnings

import pandas as pd
import yfinance as yf

import config
from .cache import TTLCache

logger = logging.getLogger(__name__)

# Re-export for back-compat with existing imports
TRADING_DAYS = config.TRADING_DAYS
BENCHMARK = config.BENCHMARK

# Scoped to the noisy libraries only
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
warnings.filterwarnings("ignore", category=UserWarning, module="yfinance")

_PRICE_CACHE = TTLCache(
    maxsize=config.PRICE_CACHE_MAXSIZE,
    ttl=config.PRICE_CACHE_TTL,
)


def _cache_key(tickers: list[str], start_date: str, end_date: str) -> str:
    return f"prices:{','.join(sorted(tickers))}:{start_date}:{end_date}"


def fetch_prices(tickers: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Download adjusted close prices for *tickers*. Cached in-process for TTL."""
    if not tickers:
        raise ValueError("tickers must not be empty.")

    key = _cache_key(tickers, start_date, end_date)
    hit = _PRICE_CACHE.get(key)
    if hit is not None:
        return hit.copy()

    raw = yf.download(
        tickers if len(tickers) > 1 else tickers[0],
        start=start_date,
        end=end_date,
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        raise ValueError("No price data returned.")

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"]
    else:
        col = "Close" if "Close" in raw.columns else raw.columns[0]
        prices = raw[[col]].rename(columns={col: tickers[0]})

    if isinstance(prices, pd.Series):
        prices = prices.to_frame(name=tickers[0])

    available = [t for t in tickers if t in prices.columns]
    if not available:
        raise ValueError(f"None of {tickers} had data.")

    prices = prices[available].dropna(how="all").ffill().dropna(how="any")
    _PRICE_CACHE.set(key, prices.copy())
    return prices


def fetch_benchmark(start_date: str, end_date: str) -> pd.Series | None:
    """Download SPY adjusted close prices; returns None on failure."""
    try:
        df = fetch_prices([BENCHMARK], start_date, end_date)
        return df[BENCHMARK]
    except (ValueError, KeyError) as exc:
        logger.warning("Benchmark fetch failed: %s", exc)
        return None


def clear_cache() -> None:
    _PRICE_CACHE.clear()
