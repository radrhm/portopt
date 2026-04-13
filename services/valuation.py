"""Equity valuation — fetch financials via yfinance."""

import logging

logger = logging.getLogger(__name__)


def fetch_financials(ticker: str) -> dict:
    import yfinance as yf

    t    = yf.Ticker(ticker)
    info = t.info

    if not info or (not info.get("regularMarketPrice") and not info.get("currentPrice")):
        raise ValueError(f"No data found for '{ticker}'. Check the symbol.")

    # ── Price & identity ─────────────────────────────────────────
    price    = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
    name     = info.get("longName") or info.get("shortName") or ticker
    sector   = info.get("sector")   or "—"
    industry = info.get("industry") or "—"
    currency = info.get("currency") or "USD"
    mktcap   = float(info.get("marketCap") or 0)
    shares   = float(info.get("sharesOutstanding") or 1)

    beta = float(info.get("beta") or 1.0)
    beta = max(0.1, min(beta, 3.0))

    # ── Historical FCF from cash flow statement ──────────────────
    # yfinance provides up to 4 years of annual data reliably
    historical_fcf = []
    fcf_total_latest = float(info.get("freeCashflow") or 0)
    try:
        cf = t.cashflow
        if cf is not None and not cf.empty:
            for col in cf.columns:
                try:
                    yr = col.year if hasattr(col, 'year') else int(str(col)[:4])
                except Exception:
                    continue
                op_cf, capex = 0.0, 0.0
                for label in ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"):
                    if label in cf.index:
                        v = cf.loc[label, col]
                        if not _isnan(v):
                            op_cf = float(v)
                            break
                for label in ("Capital Expenditure", "Capital Expenditures",
                               "Purchase Of Property Plant And Equipment"):
                    if label in cf.index:
                        v = cf.loc[label, col]
                        if not _isnan(v):
                            capex = float(v)
                            break
                fcf = op_cf + capex   # capex is stored as negative
                historical_fcf.append({
                    "year":    yr,
                    "op_cf_m": round(op_cf  / 1e6, 1),
                    "capex_m": round(capex  / 1e6, 1),
                    "fcf_m":   round(fcf    / 1e6, 1),
                })
            historical_fcf.sort(key=lambda x: -x["year"])
            if historical_fcf:
                fcf_total_latest = historical_fcf[0]["fcf_m"] * 1e6
    except Exception as e:
        logger.warning("Could not parse cashflow: %s", e)

    fcf_per_share = fcf_total_latest / shares if shares else 0

    # ── Income statement ─────────────────────────────────────────
    ebit_m    = 0.0
    revenue_m = float((info.get("totalRevenue") or 0)) / 1e6
    tax_rate  = 0.21
    eps_ttm   = float(info.get("trailingEps")  or 0)
    eps_fwd   = float(info.get("forwardEps")   or 0)

    try:
        fin = t.financials
        if fin is not None and not fin.empty:
            col0 = fin.columns[0]
            for label in ("EBIT", "Operating Income", "Ebit"):
                if label in fin.index:
                    v = fin.loc[label, col0]
                    if not _isnan(v):
                        ebit_m = float(v) / 1e6
                        break
            for label in ("Total Revenue", "Revenue"):
                if label in fin.index:
                    v = fin.loc[label, col0]
                    if not _isnan(v):
                        revenue_m = float(v) / 1e6
                        break
            # Effective tax rate from net income and pretax income
            pre_tax, net_inc = None, None
            for label in ("Pretax Income", "Income Before Tax"):
                if label in fin.index:
                    v = fin.loc[label, col0]
                    if not _isnan(v):
                        pre_tax = float(v)
                        break
            for label in ("Net Income", "Net Income Common Stockholders"):
                if label in fin.index:
                    v = fin.loc[label, col0]
                    if not _isnan(v):
                        net_inc = float(v)
                        break
            if pre_tax and pre_tax > 0 and net_inc is not None:
                tax_rate = max(0.0, min(0.45, 1.0 - net_inc / pre_tax))
    except Exception as e:
        logger.warning("Could not parse financials: %s", e)

    ebit_per_share    = ebit_m * 1e6 / shares if shares else 0
    revenue_per_share = revenue_m * 1e6 / shares if shares else 0

    # ── Balance sheet ─────────────────────────────────────────────
    current_assets_m  = 0.0
    total_liab_m      = 0.0
    book_value_ps     = float(info.get("bookValue") or 0)
    total_debt        = float(info.get("totalDebt")  or 0)
    cash              = float(info.get("totalCash")  or 0)
    net_debt_m        = (total_debt - cash) / 1e6

    try:
        bs = t.balance_sheet
        if bs is not None and not bs.empty:
            col0 = bs.columns[0]
            for label in ("Current Assets", "Total Current Assets"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        current_assets_m = float(v) / 1e6
                        break
            for label in ("Total Liabilities Net Minority Interest", "Total Liabilities"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        total_liab_m = float(v) / 1e6
                        break
    except Exception as e:
        logger.warning("Could not parse balance sheet: %s", e)

    ncav_per_share = ((current_assets_m - total_liab_m) * 1e6 / shares) if shares else 0

    # ── Multiples ────────────────────────────────────────────────
    pe_ttm    = float(info.get("trailingPE")  or 0)
    pe_fwd    = float(info.get("forwardPE")   or 0)
    ebitda    = float(info.get("ebitda")       or 0)
    ev        = float(info.get("enterpriseValue") or 0)

    ev_ebitda_curr = round(ev / ebitda,      1) if ebitda    else 0
    ev_ebit_curr   = round(ev / (ebit_m*1e6), 1) if ebit_m   else 0
    ev_rev_curr    = round(ev / (revenue_m*1e6), 2) if revenue_m else 0
    ps_current     = round(mktcap / (revenue_m * 1e6), 2) if revenue_m else 0
    pb_current     = round(price / book_value_ps, 2)       if book_value_ps else 0

    # ── Growth rates ─────────────────────────────────────────────
    eg = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
    earnings_growth_pct = float(eg) * 100 if eg else 10.0
    earnings_growth_pct = max(-50.0, min(earnings_growth_pct, 60.0))

    # ── WACC suggestion ───────────────────────────────────────────
    wacc = round(4.3 + beta * 5.5, 1)

    # ── Sector P/E & EV/EBITDA suggestions ───────────────────────
    pe_sector_defaults = {
        "Technology": 25.0, "Healthcare": 22.0, "Consumer Cyclical": 20.0,
        "Financial Services": 14.0, "Industrials": 18.0, "Energy": 12.0,
        "Utilities": 16.0, "Real Estate": 18.0, "Consumer Defensive": 20.0,
        "Communication Services": 22.0, "Basic Materials": 14.0,
    }
    ev_sector_defaults = {
        "Technology": 20.0, "Healthcare": 16.0, "Consumer Cyclical": 12.0,
        "Financial Services": 10.0, "Industrials": 12.0, "Energy": 7.0,
        "Utilities": 12.0, "Real Estate": 18.0, "Consumer Defensive": 14.0,
        "Communication Services": 14.0, "Basic Materials": 8.0,
    }
    ps_sector_defaults = {
        "Technology": 6.0, "Healthcare": 4.0, "Consumer Cyclical": 1.5,
        "Financial Services": 2.0, "Industrials": 1.5, "Energy": 1.0,
        "Utilities": 2.5, "Real Estate": 4.0, "Consumer Defensive": 1.2,
        "Communication Services": 3.0, "Basic Materials": 1.5,
    }
    pb_sector_defaults = {
        "Technology": 8.0, "Healthcare": 4.0, "Consumer Cyclical": 3.0,
        "Financial Services": 1.5, "Industrials": 3.0, "Energy": 1.5,
        "Utilities": 1.5, "Real Estate": 2.0, "Consumer Defensive": 4.0,
        "Communication Services": 4.0, "Basic Materials": 2.0,
    }
    sector_pe  = pe_sector_defaults.get(sector, 18.0)
    sector_ev  = ev_sector_defaults.get(sector, 12.0)
    sector_ps  = ps_sector_defaults.get(sector, 2.0)
    sector_pb  = pb_sector_defaults.get(sector, 3.0)

    # Calibrate against actual multiples if sensible
    if pe_ttm and 5 < pe_ttm < 80:
        sector_pe = round(pe_ttm * 0.9, 1)
    if ev_ebitda_curr and 3 < ev_ebitda_curr < 40:
        sector_ev = round(ev_ebitda_curr * 0.9, 1)
    if ps_current and 0.3 < ps_current < 30:
        sector_ps = round(ps_current * 0.85, 2)
    if pb_current and 0.5 < pb_current < 30:
        sector_pb = round(pb_current * 0.85, 2)

    div_rate  = float(info.get("dividendRate")  or 0)
    div_yield = float(info.get("dividendYield") or 0) * 100

    return {
        # Identity
        "ticker":          ticker.upper(),
        "name":            name,
        "sector":          sector,
        "industry":        industry,
        "currency":        currency,
        "current_price":   round(price, 2),
        "market_cap_m":    round(mktcap / 1e6, 2),
        "market_cap_fmt":  _fmt_large(mktcap),
        "shares_m":        round(shares / 1e6, 2),
        "beta":            round(beta, 2),

        # Historical FCF (up to 4 years from yfinance)
        "historical_fcf":    historical_fcf,
        "fcf_years":         len(historical_fcf),

        # DCF inputs
        "fcf_total_m":       round(fcf_total_latest / 1e6, 1),
        "fcf_per_share":     round(fcf_per_share, 2),
        "wacc_suggestion":   wacc,
        "earnings_growth_pct": round(earnings_growth_pct, 1),

        # DDM
        "dividend_annual":  round(div_rate,  2),
        "dividend_yield":   round(div_yield, 2),

        # P/E
        "eps_ttm":          round(eps_ttm,  2),
        "eps_forward":      round(eps_fwd,  2),
        "pe_ttm":           round(pe_ttm,   1),
        "pe_forward":       round(pe_fwd,   1),
        "sector_pe":        sector_pe,

        # EV multiples
        "ebitda_m":          round(ebitda / 1e6,     1),
        "ebit_m":            round(ebit_m,            1),
        "revenue_m":         round(revenue_m,         1),
        "net_debt_m":        round(net_debt_m,        1),
        "ev_m":              round(ev / 1e6,          1),
        "ev_ebitda_current": ev_ebitda_curr,
        "ev_ebit_current":   ev_ebit_curr,
        "ev_rev_current":    ev_rev_curr,
        "sector_ev":         sector_ev,
        "sector_ps":         sector_ps,
        "ps_current":        ps_current,

        # Asset-based
        "book_value_ps":    round(book_value_ps, 2),
        "pb_current":       pb_current,
        "sector_pb":        sector_pb,
        "current_assets_m": round(current_assets_m, 1),
        "total_liab_m":     round(total_liab_m,     1),
        "ncav_per_share":   round(ncav_per_share,   2),

        # EPV
        "ebit_per_share":     round(ebit_per_share, 2),
        "revenue_per_share":  round(revenue_per_share, 2),
        "tax_rate_pct":       round(tax_rate * 100, 1),

        # PEG
        "peg_ratio": round(pe_ttm / earnings_growth_pct, 2)
                     if earnings_growth_pct > 0 and pe_ttm > 0 else 0,
    }


def _isnan(v) -> bool:
    try:
        import math
        return v is None or (isinstance(v, float) and math.isnan(v))
    except Exception:
        return False


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
