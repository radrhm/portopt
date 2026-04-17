"""Central configuration — constants and environment-based settings."""

import os

# ── Market data ──────────────────────────────────────────────────────────────
TRADING_DAYS = 252
BENCHMARK = "SPY"

# ── Cache tuning ─────────────────────────────────────────────────────────────
PRICE_CACHE_TTL = int(os.environ.get("PRICE_CACHE_TTL", "900"))       # 15 min
PRICE_CACHE_MAXSIZE = int(os.environ.get("PRICE_CACHE_MAXSIZE", "128"))
GEMINI_CACHE_TTL = int(os.environ.get("GEMINI_CACHE_TTL", "3600"))    # 1 hr
GEMINI_CACHE_MAXSIZE = int(os.environ.get("GEMINI_CACHE_MAXSIZE", "64"))

# ── Optimization ─────────────────────────────────────────────────────────────
VALID_METHODS = frozenset({
    "max_sharpe", "min_volatility", "black_litterman",
    "risk_parity", "hrp", "equal_weight", "max_return",
})

STRESS_SCENARIOS = {
    "gfc_2008":     ("2008 Financial Crisis",  "2008-09-01", "2008-12-31"),
    "covid_2020":   ("COVID Crash",            "2020-02-19", "2020-03-23"),
    "rout_2022":    ("2022 Rate-Hike Selloff", "2022-01-03", "2022-10-12"),
    "dot_com":      ("Dot-com Bust",           "2000-03-10", "2002-10-09"),
    "rate_1994":    ("1994 Bond Shock",        "1994-01-01", "1994-11-30"),
    "inflation_80": ("1980 Inflation Shock",   "1980-01-01", "1982-08-12"),
}

# ── Gemini ───────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_REQUEST_TIMEOUT = int(os.environ.get("GEMINI_REQUEST_TIMEOUT", "18"))
GEMINI_OVERALL_TIMEOUT = int(os.environ.get("GEMINI_OVERALL_TIMEOUT", "20"))

# ── App ──────────────────────────────────────────────────────────────────────
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
