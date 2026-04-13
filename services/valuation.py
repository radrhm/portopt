"""Equity valuation — fetch financials via yfinance for all valuation methods."""

import logging
logger = logging.getLogger(__name__)


def fetch_financials(ticker: str) -> dict:
    import yfinance as yf

    t    = yf.Ticker(ticker)
    info = t.info

    if not info or not info.get("regularMarketPrice") and not info.get("currentPrice"):
        raise ValueError(f"No data found for ticker '{ticker}'. Check the symbol.")

    # ── Price & identity ──────────────────────────────────────────
    price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
    name  = info.get("longName") or info.get("shortName") or ticker
    sector   = info.get("sector")   or "—"
    industry = info.get("industry") or "—"
    currency = info.get("currency") or "USD"
    mktcap   = info.get("marketCap") or 0

    # ── Shares ───────────────────────────────────────────────────
    shares = float(info.get("sharesOutstanding") or 1)

    # ── FCF per share ─────────────────────────────────────────────
    fcf_abs = float(info.get("freeCashflow") or 0)
    try:
        cf = t.cashflow
        if "Operating Cash Flow" in cf.index and "Capital Expenditure" in cf.index:
            op_cf = float(cf.loc["Operating Cash Flow"].iloc[0])
            capex = float(cf.loc["Capital Expenditure"].iloc[0])   # negative
            fcf_abs = op_cf + capex
    except Exception:
        pass
    fcf_per_share = fcf_abs / shares if shares else 0

    # ── Earnings & growth ─────────────────────────────────────────
    eps_ttm  = float(info.get("trailingEps")  or 0)
    eps_fwd  = float(info.get("forwardEps")   or 0)
    pe_ttm   = float(info.get("trailingPE")   or 0)
    pe_fwd   = float(info.get("forwardPE")    or 0)

    eg = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
    earnings_growth_pct = float(eg) * 100 if eg else 10.0
    earnings_growth_pct = max(-50.0, min(earnings_growth_pct, 60.0))

    rg = info.get("revenueGrowth")
    revenue_growth_pct  = float(rg) * 100 if rg else 8.0

    # ── Dividend ─────────────────────────────────────────────────
    div_rate  = float(info.get("dividendRate")  or 0)
    div_yield = float(info.get("dividendYield") or 0) * 100

    # ── Book value ───────────────────────────────────────────────
    book_value_ps = float(info.get("bookValue") or 0)

    # ── EBITDA & EV ──────────────────────────────────────────────
    ebitda = float(info.get("ebitda") or 0)
    ev     = float(info.get("enterpriseValue") or 0)
    ev_ebitda_current = round(ev / ebitda, 1) if ebitda else 0

    total_debt = float(info.get("totalDebt")  or 0)
    cash       = float(info.get("totalCash")  or 0)
    net_debt   = total_debt - cash

    # ── WACC suggestion: rf (4.3%) + β × ERP (5.5%) ─────────────
    beta = float(info.get("beta") or 1.0)
    beta = max(0.1, min(beta, 3.0))
    wacc_suggestion = round(4.3 + beta * 5.5, 1)

    # ── Sector P/E suggestion (90% of trailing or sector default) ─
    if pe_ttm and 5 < pe_ttm < 80:
        sector_pe = round(pe_ttm * 0.9, 1)
    else:
        # Rough sector defaults
        sector_defaults = {
            "Technology": 25.0, "Healthcare": 22.0, "Consumer Cyclical": 20.0,
            "Financial Services": 14.0, "Industrials": 18.0, "Energy": 12.0,
            "Utilities": 16.0, "Real Estate": 18.0, "Consumer Defensive": 20.0,
            "Communication Services": 22.0, "Basic Materials": 14.0,
        }
        sector_pe = sector_defaults.get(sector, 18.0)

    # ── EV/EBITDA sector suggestion ───────────────────────────────
    if ev_ebitda_current and 3 < ev_ebitda_current < 40:
        ev_multiple_suggestion = round(ev_ebitda_current * 0.9, 1)
    else:
        sector_ev = {
            "Technology": 20.0, "Healthcare": 16.0, "Consumer Cyclical": 12.0,
            "Financial Services": 10.0, "Industrials": 12.0, "Energy": 7.0,
            "Utilities": 12.0, "Real Estate": 18.0, "Consumer Defensive": 14.0,
            "Communication Services": 14.0, "Basic Materials": 8.0,
        }
        ev_multiple_suggestion = sector_ev.get(sector, 12.0)

    return {
        # Identity
        "ticker":          ticker.upper(),
        "name":            name,
        "sector":          sector,
        "industry":        industry,
        "currency":        currency,
        "current_price":   round(price, 2),
        "market_cap":      mktcap,
        "market_cap_fmt":  _fmt_large(mktcap),
        "beta":            round(beta, 2),

        # DCF inputs
        "fcf_per_share":     round(fcf_per_share, 2),
        "fcf_total_m":       round(fcf_abs / 1e6, 1),
        "shares_outstanding_m": round(shares / 1e6, 2),
        "wacc_suggestion":   wacc_suggestion,
        "earnings_growth_pct": round(earnings_growth_pct, 1),
        "revenue_growth_pct":  round(revenue_growth_pct, 1),

        # DDM inputs
        "dividend_annual":  round(div_rate,  2),
        "dividend_yield":   round(div_yield, 2),

        # P/E inputs
        "eps_ttm":          round(eps_ttm,  2),
        "eps_forward":      round(eps_fwd,  2),
        "pe_ttm":           round(pe_ttm,   1),
        "pe_forward":       round(pe_fwd,   1),
        "sector_pe":        sector_pe,

        # EV/EBITDA inputs
        "ebitda_m":         round(ebitda / 1e6, 1),
        "net_debt_m":       round(net_debt / 1e6, 1),
        "ev_m":             round(ev / 1e6, 1),
        "ev_ebitda_current": ev_ebitda_current,
        "ev_multiple_suggestion": ev_multiple_suggestion,

        # Graham inputs
        "book_value_ps":    round(book_value_ps, 2),

        # PEG inputs (same as P/E + growth)
        "peg_ratio":        round(pe_ttm / earnings_growth_pct, 2) if earnings_growth_pct > 0 and pe_ttm > 0 else 0,
    }


def _fmt_large(n: float) -> str:
    if not n:
        return "—"
    if n >= 1e12:
        return f"${n/1e12:.2f}T"
    if n >= 1e9:
        return f"${n/1e9:.2f}B"
    if n >= 1e6:
        return f"${n/1e6:.1f}M"
    return f"${n:,.0f}"
