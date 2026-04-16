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

    # ── Piotroski F-Score & Altman Z-Score ───────────────────────
    scores = _calc_scores(t, mktcap)

    # ── Historical annual data for model charts ───────────────────
    pe_history        = []
    ps_history        = []
    ev_ebitda_history = []
    ebit_annual       = []
    ebitda_annual     = []
    revenue_annual    = []
    eps_history       = []
    dividend_history  = []

    try:
        import pandas as pd
        fin_full = t.financials  # annual income statement

        # Weekly price history for ratio computation
        prices_s = None
        try:
            _hist = t.history(period='6y', interval='1wk')
            if _hist is not None and not _hist.empty:
                prices_s = _hist['Close']
        except Exception:
            pass

        if fin_full is not None and not fin_full.empty:
            for col in sorted(fin_full.columns, key=lambda c: c):
                try:
                    yr = col.year
                except Exception:
                    continue

                rev = ebit_v = ebitda_v = net_inc = None

                for lbl in ('Total Revenue', 'Revenue', 'Operating Revenue'):
                    if lbl in fin_full.index:
                        v = fin_full.loc[lbl, col]
                        if not _isnan(v): rev = float(v); break

                for lbl in ('EBIT', 'Operating Income', 'Ebit'):
                    if lbl in fin_full.index:
                        v = fin_full.loc[lbl, col]
                        if not _isnan(v): ebit_v = float(v); break

                for lbl in ('EBITDA', 'Normalized EBITDA'):
                    if lbl in fin_full.index:
                        v = fin_full.loc[lbl, col]
                        if not _isnan(v): ebitda_v = float(v); break

                for lbl in ('Net Income', 'Net Income Common Stockholders'):
                    if lbl in fin_full.index:
                        v = fin_full.loc[lbl, col]
                        if not _isnan(v): net_inc = float(v); break

                if rev:
                    revenue_annual.append({'year': yr, 'revenue_m': round(rev / 1e6, 1)})
                if ebit_v is not None:
                    ebit_annual.append({'year': yr, 'ebit_m': round(ebit_v / 1e6, 1)})
                if ebitda_v:
                    ebitda_annual.append({'year': yr, 'ebitda_m': round(ebitda_v / 1e6, 1)})

                eps_yr = round(net_inc / shares, 2) if (net_inc and shares) else None
                if eps_yr is not None:
                    eps_history.append({'year': yr, 'eps': eps_yr})

                # Historical price at this fiscal year-end for ratio computation
                if prices_s is not None and len(prices_s) > 0:
                    try:
                        target = pd.Timestamp(col)
                        idx = prices_s.index.searchsorted(target)
                        if idx >= len(prices_s):
                            idx = len(prices_s) - 1
                        hist_px = float(prices_s.iloc[idx])
                        if hist_px > 0:
                            if eps_yr and eps_yr > 0:
                                pe_history.append({
                                    'year': yr,
                                    'pe': round(hist_px / eps_yr, 1)
                                })
                            if rev and rev > 0:
                                hist_mc = hist_px * shares
                                ps_history.append({
                                    'year': yr,
                                    'ps': round(hist_mc / rev, 2)
                                })
                            if ebitda_v and ebitda_v > 0:
                                hist_mc  = hist_px * shares
                                hist_ev  = hist_mc + (total_debt - cash)
                                if hist_ev > 0:
                                    ev_ebitda_history.append({
                                        'year': yr,
                                        'ev_ebitda': round(hist_ev / ebitda_v, 1)
                                    })
                    except Exception:
                        pass

        for lst in [revenue_annual, ebit_annual, ebitda_annual, eps_history,
                    pe_history, ps_history, ev_ebitda_history]:
            lst.sort(key=lambda x: x['year'])

    except Exception as e:
        logger.warning("Could not compute annual history: %s", e)

    # Dividend history (annual sum, last 5 years)
    try:
        import pandas as pd
        divs = t.dividends
        if divs is not None and not divs.empty:
            annual_d = divs.resample('YE').sum()
            for dt, amt in annual_d.items():
                if float(amt) > 0:
                    dividend_history.append({
                        'year': dt.year,
                        'dividend': round(float(amt), 2)
                    })
            dividend_history = sorted(dividend_history, key=lambda x: x['year'])[-5:]
    except Exception as e:
        logger.warning("Could not parse dividend history: %s", e)

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

        # Historical data for model charts
        "pe_history":         pe_history,
        "ps_history":         ps_history,
        "ev_ebitda_history":  ev_ebitda_history,
        "ebit_annual":        ebit_annual,
        "ebitda_annual":      ebitda_annual,
        "revenue_annual":     revenue_annual,
        "eps_history":        eps_history,
        "dividend_history":   dividend_history,

        # Quality scores
        **scores,
    }


def _isnan(v) -> bool:
    try:
        import math
        return v is None or (isinstance(v, float) and math.isnan(v))
    except Exception:
        return False


def _get_label(df, labels, col):
    """Return first matching label value as float, or None."""
    if df is None or df.empty:
        return None
    for lbl in labels:
        if lbl in df.index:
            try:
                v = df.loc[lbl, col]
                if not _isnan(v):
                    return float(v)
            except Exception:
                continue
    return None


def _calc_scores(t, mktcap: float) -> dict:
    """Piotroski F-Score (9 tests) + Altman Z-Score."""
    out = {}
    try:
        fin = t.financials
        bs  = t.balance_sheet
        cf  = t.cashflow
        if fin is None or fin.empty or bs is None or bs.empty:
            return out
        if len(fin.columns) < 2 or len(bs.columns) < 2:
            # Not enough history for YoY tests — still try Z-score
            pass

        c0 = fin.columns[0]
        c1 = fin.columns[1] if len(fin.columns) > 1 else None
        b0 = bs.columns[0]
        b1 = bs.columns[1] if len(bs.columns) > 1 else None
        cf0 = cf.columns[0] if (cf is not None and not cf.empty) else None

        # Income statement values
        ni_labels   = ("Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations")
        rev_labels  = ("Total Revenue", "Revenue", "Operating Revenue")
        gp_labels   = ("Gross Profit",)

        ni_0   = _get_label(fin, ni_labels, c0)
        rev_0  = _get_label(fin, rev_labels, c0)
        rev_1  = _get_label(fin, rev_labels, c1) if c1 is not None else None
        gp_0   = _get_label(fin, gp_labels, c0)
        gp_1   = _get_label(fin, gp_labels, c1) if c1 is not None else None
        ebit_0 = _get_label(fin, ("EBIT", "Operating Income", "Ebit"), c0)

        # Balance sheet values
        ta_labels  = ("Total Assets",)
        tl_labels  = ("Total Liabilities Net Minority Interest", "Total Liabilities")
        ca_labels  = ("Current Assets", "Total Current Assets")
        cl_labels  = ("Current Liabilities", "Total Current Liabilities")
        ltd_labels = ("Long Term Debt", "Long Term Debt And Capital Lease Obligation")
        sh_labels  = ("Share Issued", "Ordinary Shares Number", "Common Stock")
        re_labels  = ("Retained Earnings",)

        ta_0  = _get_label(bs, ta_labels, b0)
        ta_1  = _get_label(bs, ta_labels, b1) if b1 is not None else None
        tl_0  = _get_label(bs, tl_labels, b0)
        ca_0  = _get_label(bs, ca_labels, b0)
        ca_1  = _get_label(bs, ca_labels, b1) if b1 is not None else None
        cl_0  = _get_label(bs, cl_labels, b0)
        cl_1  = _get_label(bs, cl_labels, b1) if b1 is not None else None
        ltd_0 = _get_label(bs, ltd_labels, b0)
        ltd_1 = _get_label(bs, ltd_labels, b1) if b1 is not None else None
        sh_0  = _get_label(bs, sh_labels, b0)
        sh_1  = _get_label(bs, sh_labels, b1) if b1 is not None else None
        re_0  = _get_label(bs, re_labels, b0)

        # Cashflow values
        ocf_0 = _get_label(cf, ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"), cf0) if cf0 is not None else None

        # ── Piotroski F-Score ──────────────────────────────────────
        tests = {}
        # 1. Profitability: Net income > 0
        tests["profit_pos"] = 1 if (ni_0 is not None and ni_0 > 0) else 0
        # 2. ROA > 0
        roa_0 = (ni_0 / ta_0) if (ni_0 is not None and ta_0) else None
        tests["roa_pos"] = 1 if (roa_0 is not None and roa_0 > 0) else 0
        # 3. OCF > 0
        tests["ocf_pos"] = 1 if (ocf_0 is not None and ocf_0 > 0) else 0
        # 4. OCF > Net Income (quality of earnings)
        tests["accruals"] = 1 if (ocf_0 is not None and ni_0 is not None and ocf_0 > ni_0) else 0
        # 5. LT Debt / Total Assets decreased
        if ltd_0 is not None and ltd_1 is not None and ta_0 and ta_1:
            tests["leverage"] = 1 if (ltd_0 / ta_0) < (ltd_1 / ta_1) else 0
        else:
            tests["leverage"] = 0
        # 6. Current ratio increased
        if ca_0 and cl_0 and ca_1 and cl_1:
            tests["liquidity"] = 1 if (ca_0 / cl_0) > (ca_1 / cl_1) else 0
        else:
            tests["liquidity"] = 0
        # 7. No new shares issued (shares <= prior +0.5%)
        if sh_0 and sh_1:
            tests["dilution"] = 1 if sh_0 <= sh_1 * 1.005 else 0
        else:
            tests["dilution"] = 0
        # 8. Gross margin increased
        if gp_0 is not None and gp_1 is not None and rev_0 and rev_1:
            tests["margin"] = 1 if (gp_0 / rev_0) > (gp_1 / rev_1) else 0
        else:
            tests["margin"] = 0
        # 9. Asset turnover increased
        if rev_0 and rev_1 and ta_0 and ta_1:
            tests["turnover"] = 1 if (rev_0 / ta_0) > (rev_1 / ta_1) else 0
        else:
            tests["turnover"] = 0

        out["f_score"] = sum(tests.values())
        out["f_score_details"] = tests

        # ── Altman Z-Score ─────────────────────────────────────────
        if ta_0 and tl_0:
            wc = (ca_0 or 0) - (cl_0 or 0)
            A = wc / ta_0
            B = (re_0 / ta_0) if re_0 is not None else 0
            C = (ebit_0 / ta_0) if ebit_0 is not None else 0
            D = (mktcap / tl_0) if (mktcap and tl_0) else 0
            E = (rev_0 / ta_0) if rev_0 else 0
            z = 1.2 * A + 1.4 * B + 3.3 * C + 0.6 * D + 1.0 * E
            out["z_score"] = round(z, 2)
            if z > 2.99:
                out["z_score_band"] = "safe"
            elif z >= 1.81:
                out["z_score_band"] = "grey"
            else:
                out["z_score_band"] = "distress"
    except Exception as e:
        logger.warning("Could not compute quality scores: %s", e)
    return out


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
