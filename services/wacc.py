"""Weighted Average Cost of Capital — proper CAPM + capital-structure weighting.

Replaces the old heuristic `wacc = 4.3 + beta * 5.5`. Components:

    Ke = Rf + β · ERP                                (CAPM cost of equity)
    Kd = interest expense / total debt               (effective pre-tax cost of debt)
    WACC = (E/V) · Ke + (D/V) · Kd · (1 − t)

Data sources
------------
• Rf    : live 10-yr US Treasury yield via yfinance ^TNX (fallback 4.3%)
• ERP   : Damodaran-style country equity risk premium (static table — refresh
          periodically from https://pages.stern.nyu.edu/~adamodar/)
• β     : yfinance `info["beta"]` (5-yr monthly regression vs market)
• D, E  : book total debt, market capitalisation
• Kd    : interest expense / total debt; fallback Rf + 150 bp spread
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


# ── Live risk-free rate ──────────────────────────────────────────────────────

def fetch_risk_free_rate(fallback: float = 4.3) -> float:
    """Current 10-yr US Treasury yield as a percentage (e.g. 4.32)."""
    try:
        import yfinance as yf
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="5d")
        if hist is not None and not hist.empty:
            # ^TNX is already quoted in percent (e.g. 4.32 means 4.32%)
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as e:
        logger.warning("Could not fetch ^TNX (10-yr Treasury): %s", e)
    return fallback


# ── Country equity risk premiums (Damodaran July 2024 snapshot) ──────────────
# Units: percentage points. Update periodically.
_COUNTRY_ERP = {
    "United States":   4.60, "USA": 4.60, "US": 4.60,
    "Canada":          4.60,
    "United Kingdom":  5.02, "UK": 5.02,
    "Germany":         4.60, "France":      4.60,
    "Netherlands":     4.60, "Switzerland": 4.60,
    "Sweden":          4.60, "Denmark":     4.60, "Norway":      4.60,
    "Finland":         4.60, "Belgium":     4.60, "Austria":     4.60,
    "Ireland":         4.60, "Luxembourg":  4.60,
    "Japan":           5.02, "Australia":   4.60, "New Zealand": 4.60,
    "South Korea":     5.47, "Taiwan":      5.47, "Singapore":   4.60,
    "Hong Kong":       5.02, "China":       5.47,
    "India":           6.44, "Indonesia":   7.36, "Malaysia":    5.47,
    "Thailand":        6.12, "Philippines": 6.90, "Vietnam":     7.36,
    "Brazil":          7.36, "Mexico":      6.90, "Chile":       5.47,
    "Argentina":      11.00, "Colombia":    7.36, "Peru":        6.44,
    "Spain":           5.79, "Italy":       6.12, "Portugal":    6.12,
    "Greece":          8.12, "Turkey":      9.36,
    "Israel":          5.47, "Saudi Arabia": 5.47, "UAE":        5.02,
    "South Africa":    8.12, "Nigeria":    11.00, "Egypt":      11.00,
    "Russia":         15.00, "Ukraine":    15.00, "Poland":      5.79,
}
_DEFAULT_ERP = 5.50


def country_erp(country: str | None) -> float:
    """Damodaran-style country equity risk premium (percentage points)."""
    if not country:
        return _DEFAULT_ERP
    return _COUNTRY_ERP.get(country, _DEFAULT_ERP)


# ── WACC computation ─────────────────────────────────────────────────────────

def compute_wacc(
    *,
    beta: float,
    market_cap_m: float,
    total_debt_m: float,
    interest_expense_m: float,
    tax_rate: float,
    country: str | None = "United States",
    rf_override: float | None = None,
    erp_override: float | None = None,
) -> dict:
    """Return a dict with WACC and every component it was built from.

    All dollar inputs are in $M. Tax rate is a fraction (0.21 for 21%).
    Output WACC and rates are in percentage points (e.g. 8.5 = 8.5%).
    """
    rf  = rf_override  if rf_override  is not None else fetch_risk_free_rate()
    erp = erp_override if erp_override is not None else country_erp(country)

    # Market-value weights. Equity = market cap, Debt = book total debt.
    e = max(float(market_cap_m), 1e-6)
    d = max(float(total_debt_m), 0.0)
    v = e + d
    we = e / v
    wd = d / v

    # Cost of equity via CAPM
    ke = rf + beta * erp

    # Cost of debt: effective yield from actual interest expense. Fallback to
    # risk-free + 150 bp when either leg is missing.
    if total_debt_m > 0 and interest_expense_m > 0:
        kd_raw = (interest_expense_m / total_debt_m) * 100.0
        kd = min(20.0, max(1.5, kd_raw))          # sanity-clip
    else:
        kd = rf + 1.5

    wacc = we * ke + wd * kd * (1.0 - tax_rate)

    return {
        "wacc":          round(wacc, 2),
        "ke":            round(ke,   2),
        "kd_pretax":     round(kd,   2),
        "kd_aftertax":   round(kd * (1.0 - tax_rate), 2),
        "rf":            round(rf,   2),
        "erp":           round(erp,  2),
        "beta":          round(float(beta), 2),
        "weight_equity": round(we * 100, 1),
        "weight_debt":   round(wd * 100, 1),
        "tax_rate_pct":  round(tax_rate * 100, 1),
        "country":       country or "United States",
        "equity_m":      round(e, 1),
        "debt_m":        round(d, 1),
    }
