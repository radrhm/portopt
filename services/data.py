"""Market data helpers — price fetching via yfinance."""

import warnings
import yfinance as yf
import pandas as pd

# Scope warnings to just the noisy libraries
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
warnings.filterwarnings("ignore", category=UserWarning, module="yfinance")

TRADING_DAYS = 252
BENCHMARK = "SPY"


def fetch_prices(tickers: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Download adjusted close prices for *tickers* and return a clean DataFrame."""
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
    return prices


def fetch_benchmark(start_date: str, end_date: str) -> pd.Series | None:
    """Download SPY adjusted close prices; returns None on failure."""
    try:
        raw = yf.download(
            BENCHMARK,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            progress=False,
        )
        if isinstance(raw.columns, pd.MultiIndex):
            return raw["Close"].iloc[:, 0]
        return raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
    except Exception:
        return None
