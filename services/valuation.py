"""Equity valuation — fetch financials via yfinance."""

import logging
from .wacc import compute_wacc, fetch_risk_free_rate

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
    dna_latest_m       = 0.0   # D&A most-recent year ($M)
    sbc_latest_m       = 0.0   # Stock-Based Comp most-recent year ($M)
    buybacks_latest_m  = 0.0   # Share repurchases most-recent year ($M, positive)
    dividends_paid_m   = 0.0   # Cash dividends paid most-recent year ($M, positive)
    try:
        cf = t.cashflow
        if cf is not None and not cf.empty:
            for col in cf.columns:
                try:
                    yr = col.year if hasattr(col, 'year') else int(str(col)[:4])
                except Exception:
                    continue
                op_cf, capex, dna, sbc = 0.0, 0.0, 0.0, 0.0
                buyback, div_cash = 0.0, 0.0
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
                for label in ("Depreciation And Amortization", "Depreciation Amortization Depletion",
                               "Depreciation", "Amortization"):
                    if label in cf.index:
                        v = cf.loc[label, col]
                        if not _isnan(v):
                            dna = abs(float(v))   # always positive
                            break
                for label in ("Stock Based Compensation", "Share Based Compensation Expense",
                               "Stock Based Compensation Expense"):
                    if label in cf.index:
                        v = cf.loc[label, col]
                        if not _isnan(v):
                            sbc = abs(float(v))
                            break
                # Share repurchases (stored as negative → take abs)
                for label in ("Repurchase Of Capital Stock", "Common Stock Repurchased",
                               "Repurchase Of Common Stock", "Purchase Of Common Stock",
                               "Treasury Stock Purchased"):
                    if label in cf.index:
                        v = cf.loc[label, col]
                        if not _isnan(v):
                            buyback = abs(float(v))
                            break
                # Cash dividends paid (stored as negative → take abs)
                for label in ("Cash Dividends Paid", "Common Stock Dividend Paid",
                               "Dividends Paid"):
                    if label in cf.index:
                        v = cf.loc[label, col]
                        if not _isnan(v):
                            div_cash = abs(float(v))
                            break
                fcf = op_cf + capex   # capex is stored as negative
                # Owner Earnings ≈ FCF − SBC
                # (maintenance capex ≈ D&A, so D&A adds back; they roughly cancel)
                owner_earnings = fcf - sbc
                historical_fcf.append({
                    "year":             yr,
                    "op_cf_m":          round(op_cf          / 1e6, 1),
                    "capex_m":          round(capex          / 1e6, 1),
                    "fcf_m":            round(fcf            / 1e6, 1),
                    "dna_m":            round(dna            / 1e6, 1),
                    "sbc_m":            round(sbc            / 1e6, 1),
                    "buyback_m":        round(buyback        / 1e6, 1),
                    "div_paid_m":       round(div_cash       / 1e6, 1),
                    "owner_earnings_m": round(owner_earnings / 1e6, 1),
                })
            historical_fcf.sort(key=lambda x: -x["year"])
            if historical_fcf:
                fcf_total_latest   = historical_fcf[0]["fcf_m"] * 1e6
                dna_latest_m       = historical_fcf[0]["dna_m"]
                sbc_latest_m       = historical_fcf[0]["sbc_m"]
                buybacks_latest_m  = historical_fcf[0].get("buyback_m", 0.0)
                dividends_paid_m   = historical_fcf[0].get("div_paid_m", 0.0)
    except Exception as e:
        logger.warning("Could not parse cashflow: %s", e)

    fcf_per_share = fcf_total_latest / shares if shares else 0

    # ── Income statement ─────────────────────────────────────────
    ebit_m             = 0.0
    interest_expense_m = 0.0   # absolute value, $M
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
            # Interest expense (absolute value)
            for label in ("Interest Expense", "Interest Expense Non Operating",
                           "Net Interest Income"):
                if label in fin.index:
                    v = fin.loc[label, col0]
                    if not _isnan(v):
                        interest_expense_m = abs(float(v)) / 1e6
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
    total_assets_m    = 0.0
    total_equity_m    = 0.0
    goodwill_m        = 0.0
    intangibles_m     = 0.0
    op_lease_liab_m   = 0.0    # Operating lease liability
    pension_liab_m    = 0.0    # Pension deficit / post-retirement obligation
    preferred_stock_m = 0.0    # Preferred equity
    minority_int_m    = 0.0    # Non-controlling / minority interest
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
            for label in ("Total Assets",):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        total_assets_m = float(v) / 1e6
                        break
            for label in ("Stockholders Equity", "Total Equity Gross Minority Interest",
                           "Common Stock Equity"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        total_equity_m = float(v) / 1e6
                        break
            for label in ("Goodwill",):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        goodwill_m = float(v) / 1e6
                        break
            for label in ("Other Intangible Assets", "Intangible Assets",
                           "Goodwill And Other Intangible Assets"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        intangibles_m = float(v) / 1e6
                        break
            # Operating lease liability (current + non-current)
            for label in ("Long Term Capital Lease Obligation",
                           "Operating Lease Liability Noncurrent",
                           "Capital Lease Obligations"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        op_lease_liab_m += float(v) / 1e6
                        break
            for label in ("Current Capital Lease Obligation",
                           "Operating Lease Liability Current"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        op_lease_liab_m += float(v) / 1e6
                        break
            for label in ("Pension And Other Post Retirement Benefit Plans Current",
                           "Pensionand Other Post Retirement Benefit Plans Current"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        pension_liab_m += float(v) / 1e6
                        break
            for label in ("Non Current Pension And Other Postretirement Benefit Plans",
                           "Pension And Other Post Retirement Benefit Plans"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        pension_liab_m += float(v) / 1e6
                        break
            for label in ("Preferred Stock Equity", "Preferred Stock",
                           "Preferred Securities Outside Stock Equity"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        preferred_stock_m = float(v) / 1e6
                        break
            for label in ("Minority Interest", "Non Controlling Interests",
                           "Noncontrolling Interest"):
                if label in bs.index:
                    v = bs.loc[label, col0]
                    if not _isnan(v):
                        minority_int_m = float(v) / 1e6
                        break
    except Exception as e:
        logger.warning("Could not parse balance sheet: %s", e)

    ncav_per_share = ((current_assets_m - total_liab_m) * 1e6 / shares) if shares else 0

    # Tangible book value = total equity − goodwill − other intangibles
    tangible_book_m = max(0.0, total_equity_m - goodwill_m - intangibles_m)
    tangible_book_ps = (tangible_book_m * 1e6 / shares) if shares else 0

    # Asset Reproduction Value (Graham/Greenwald style):
    # Tangible assets at book + partial credit for intangibles (50%) and goodwill (25%)
    # representing replacement cost of brand / customer base / R&D stock
    asset_reproduction_m = tangible_book_m + 0.5 * intangibles_m + 0.25 * goodwill_m
    asset_reproduction_ps = (asset_reproduction_m * 1e6 / shares) if shares else 0

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

    # ── WACC — proper CAPM + capital-structure weighting ──────────
    country_str = info.get("country") or "United States"
    try:
        wacc_detail = compute_wacc(
            beta               = beta,
            market_cap_m       = mktcap / 1e6,
            total_debt_m       = total_debt  / 1e6,
            interest_expense_m = interest_expense_m,
            tax_rate           = tax_rate,
            country            = country_str,
        )
        wacc = wacc_detail["wacc"]
    except Exception as e:
        logger.warning("compute_wacc failed: %s", e)
        wacc        = round(4.3 + beta * 5.5, 1)
        wacc_detail = {}

    # ── FCFF (Free Cash Flow to Firm) — for EV-based DCF ─────────
    # FCFF = OCF + Interest×(1−t) − Capex
    # Since our FCF already = OCF + capex (capex negative), we add back after-tax interest
    fcf_latest_m  = round(fcf_total_latest / 1e6, 1)
    fcff_latest_m = round(fcf_latest_m + interest_expense_m * (1.0 - tax_rate), 1)

    # Owner earnings ≈ FCF − SBC
    owner_earnings_latest_m  = round(fcf_latest_m - sbc_latest_m, 1)
    owner_earnings_per_share = (owner_earnings_latest_m * 1e6 / shares) if shares else 0

    # ── Cost of equity from WACC breakdown (used by DDM) ──────────
    cost_of_equity_pct = wacc_detail.get("ke") if wacc_detail else wacc

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
    business_summary = info.get("longBusinessSummary") or ""

    # ── Piotroski F-Score & Altman Z-Score ───────────────────────
    scores = _calc_scores(t, mktcap)

    # ── Historical annual data for model charts ───────────────────
    pe_history        = []     # per-fiscal-year ratio + paired price
    ps_history        = []
    ev_ebitda_history = []
    ev_ebit_history   = []
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
            _hist = t.history(period='10y', interval='1wk')
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
                                    'year':  yr,
                                    'pe':    round(hist_px / eps_yr, 1),
                                    'price': round(hist_px, 2),
                                })
                            if rev and rev > 0:
                                hist_mc = hist_px * shares
                                ps_history.append({
                                    'year':  yr,
                                    'ps':    round(hist_mc / rev, 2),
                                    'price': round(hist_px, 2),
                                })
                            hist_mc  = hist_px * shares
                            hist_ev  = hist_mc + (total_debt - cash)
                            if ebitda_v and ebitda_v > 0 and hist_ev > 0:
                                ev_ebitda_history.append({
                                    'year':      yr,
                                    'ev_ebitda': round(hist_ev / ebitda_v, 1),
                                    'price':     round(hist_px, 2),
                                })
                            if ebit_v and ebit_v > 0 and hist_ev > 0:
                                ev_ebit_history.append({
                                    'year':    yr,
                                    'ev_ebit': round(hist_ev / ebit_v, 1),
                                    'price':   round(hist_px, 2),
                                })
                    except Exception:
                        pass

        for lst in [revenue_annual, ebit_annual, ebitda_annual, eps_history,
                    pe_history, ps_history, ev_ebitda_history, ev_ebit_history]:
            lst.sort(key=lambda x: x['year'])

    except Exception as e:
        logger.warning("Could not compute annual history: %s", e)

    # ── FCF YoY growth rates (appended to each row) ────────────────
    # historical_fcf is sorted newest→oldest
    try:
        for i in range(len(historical_fcf) - 1):
            cur = historical_fcf[i]["fcf_m"]
            prv = historical_fcf[i + 1]["fcf_m"]
            if prv and prv != 0:
                historical_fcf[i]["yoy_pct"] = round(((cur - prv) / abs(prv)) * 100, 1)
    except Exception:
        pass

    # ── Ratio ↔ Price correlation coefficients ─────────────────────
    def _corr(rows, key):
        try:
            xs = [r[key] for r in rows if r.get(key) and r.get('price')]
            ys = [r['price'] for r in rows if r.get(key) and r.get('price')]
            n = len(xs)
            if n < 3:
                return None
            mx = sum(xs) / n
            my = sum(ys) / n
            num = sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
            dx  = (sum((x-mx)**2 for x in xs)) ** 0.5
            dy  = (sum((y-my)**2 for y in ys)) ** 0.5
            if dx == 0 or dy == 0:
                return None
            return round(num / (dx * dy), 3)
        except Exception:
            return None

    correlations = {
        "pe":        _corr(pe_history,        "pe"),
        "ps":        _corr(ps_history,        "ps"),
        "ev_ebitda": _corr(ev_ebitda_history, "ev_ebitda"),
        "ev_ebit":   _corr(ev_ebit_history,   "ev_ebit"),
    }

    # Identify which multiple best explains price (highest |correlation|)
    best_multiple = None
    best_corr     = 0.0
    for k, v in correlations.items():
        if v is not None and abs(v) > abs(best_corr):
            best_corr, best_multiple = v, k

    # Price sparkline (1 year, weekly)
    price_history = []
    try:
        _ph = t.history(period='1y', interval='1wk')
        if _ph is not None and not _ph.empty:
            for dt, row in _ph.iterrows():
                price_history.append({
                    'date': dt.strftime('%Y-%m-%d'),
                    'close': round(float(row['Close']), 2),
                })
    except Exception as e:
        logger.warning("Could not fetch price history: %s", e)

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

    # ── C1: Normalized EBIT, maintenance capex, moat premium ────────
    # Blend 5-10yr historical EBIT margin with current revenue.
    normalized_ebit_m    = ebit_m
    avg_ebit_margin_pct  = 0.0
    try:
        # Align annual revenue and EBIT by year; compute margin per year
        rev_by_yr  = {r['year']: r['revenue_m'] for r in revenue_annual if r.get('revenue_m')}
        ebit_by_yr = {r['year']: r['ebit_m']    for r in ebit_annual    if r.get('ebit_m') is not None}
        margins = []
        for yr, rev in rev_by_yr.items():
            eb = ebit_by_yr.get(yr)
            if eb is not None and rev and rev > 0:
                margins.append(eb / rev)
        # Trim min/max for robustness if we have >=5 points
        if len(margins) >= 5:
            margins_sorted = sorted(margins)
            margins_trim   = margins_sorted[1:-1]
            avg_margin     = sum(margins_trim) / len(margins_trim)
        elif margins:
            avg_margin = sum(margins) / len(margins)
        else:
            avg_margin = (ebit_m / revenue_m) if revenue_m else 0.0
        avg_ebit_margin_pct = round(avg_margin * 100, 2)
        if revenue_m and avg_margin:
            normalized_ebit_m = round(avg_margin * revenue_m, 1)
    except Exception as e:
        logger.warning("Could not compute normalized EBIT: %s", e)

    # Maintenance capex ≈ D&A (Buffett rule of thumb). Diff vs total capex =
    # growth capex, which we back out of the EPV no-growth scenario.
    maintenance_capex_m = round(dna_latest_m, 1)

    # Moat premium = (EPV − Asset Reproduction Value) / EPV
    # EPV = NOPAT / WACC. If EPV > asset value, the excess is attributable to
    # durable competitive advantage (Greenwald). If EPV < asset value, the
    # company destroys capital.
    moat_premium_pct = None
    epv_firm_m       = None
    try:
        nopat_m = normalized_ebit_m * (1.0 - tax_rate)
        if wacc and wacc > 0:
            epv_firm_m = round(nopat_m / (wacc / 100.0), 1)
            if epv_firm_m and asset_reproduction_m and epv_firm_m != 0:
                moat_premium_pct = round(
                    ((epv_firm_m - asset_reproduction_m) / abs(epv_firm_m)) * 100, 1
                )
    except Exception:
        pass

    # ── C2: Payout ratio & total shareholder yield ─────────────────
    payout_ratio_pct = None
    try:
        # Pull most recent net income from eps_history proxy
        # (net_inc / shares = eps_yr — invert to net_inc)
        latest_net_income_m = None
        if eps_history:
            last = eps_history[-1]
            if last.get('eps') and shares:
                latest_net_income_m = (last['eps'] * shares) / 1e6
        if latest_net_income_m and latest_net_income_m > 0 and dividends_paid_m > 0:
            payout_ratio_pct = round((dividends_paid_m / latest_net_income_m) * 100, 1)
    except Exception:
        pass

    buyback_yield_pct = 0.0
    if buybacks_latest_m > 0 and mktcap > 0:
        buyback_yield_pct = round((buybacks_latest_m * 1e6 / mktcap) * 100, 2)
    total_shareholder_yield_pct = round(div_yield + buyback_yield_pct, 2)

    # ── C3: EV waterfall bridge ────────────────────────────────────
    # Enterprise Value ≈ Market Cap + Total Debt + Operating Leases
    #                  + Pension Deficit + Preferred Stock + Minority Interest
    #                  − Cash & Equivalents
    mc_m       = round(mktcap     / 1e6, 1)
    debt_m     = round(total_debt / 1e6, 1)
    cash_m     = round(cash       / 1e6, 1)
    ev_bridge_m = round(
        mc_m + debt_m + op_lease_liab_m + pension_liab_m
        + preferred_stock_m + minority_int_m - cash_m, 1
    )
    ev_bridge = {
        "market_cap_m":    mc_m,
        "debt_m":          debt_m,
        "op_leases_m":     round(op_lease_liab_m,  1),
        "pension_m":       round(pension_liab_m,   1),
        "preferred_m":     round(preferred_stock_m, 1),
        "minority_m":      round(minority_int_m,   1),
        "cash_m":          cash_m,
        "ev_total_m":      ev_bridge_m,
    }

    # ── D1: ROIC history + Economic Profit ─────────────────────────
    # ROIC(yr) = NOPAT(yr) / Invested Capital(yr)
    # Invested Capital ≈ Shareholders' Equity + Total Debt − Cash
    roic_history = []
    invested_capital_m = 0.0
    try:
        bs_full = t.balance_sheet
        if bs_full is not None and not bs_full.empty:
            bs_by_yr = {}
            for col in bs_full.columns:
                try:
                    yr_b = col.year
                except Exception:
                    continue
                eq_v = _get_label(bs_full, ("Stockholders Equity", "Total Equity Gross Minority Interest",
                                             "Common Stock Equity"), col)
                td_v = _get_label(bs_full, ("Total Debt", "Long Term Debt And Capital Lease Obligation",
                                             "Long Term Debt"), col)
                cash_v = _get_label(bs_full, ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments",
                                               "Cash"), col)
                bs_by_yr[yr_b] = (eq_v or 0.0, td_v or 0.0, cash_v or 0.0)

            ebit_by_yr = {r['year']: r['ebit_m'] for r in ebit_annual if r.get('ebit_m') is not None}
            for yr_r in sorted(bs_by_yr.keys()):
                eq_v, td_v, cash_v = bs_by_yr[yr_r]
                ic_m = (eq_v + td_v - cash_v) / 1e6
                eb   = ebit_by_yr.get(yr_r)
                if ic_m <= 0 or eb is None:
                    continue
                nopat_m = eb * (1.0 - tax_rate)
                roic_pct = (nopat_m / ic_m) * 100
                # Sanity clip
                if -100 <= roic_pct <= 200:
                    roic_history.append({
                        "year":     yr_r,
                        "roic_pct": round(roic_pct, 1),
                        "ic_m":     round(ic_m,     1),
                        "nopat_m":  round(nopat_m,  1),
                    })
        if roic_history:
            invested_capital_m = roic_history[-1]["ic_m"]
    except Exception as e:
        logger.warning("Could not compute ROIC history: %s", e)

    roic_ttm_pct     = roic_history[-1]["roic_pct"] if roic_history else None
    roic_5yr_avg_pct = None
    if roic_history:
        last5 = roic_history[-5:]
        roic_5yr_avg_pct = round(sum(r["roic_pct"] for r in last5) / len(last5), 1)

    # Economic Profit ≈ (ROIC − WACC) × Invested Capital  [$M]
    economic_profit_m   = None
    roic_wacc_spread_pct = None
    if roic_ttm_pct is not None and invested_capital_m > 0 and wacc:
        roic_wacc_spread_pct = round(roic_ttm_pct - wacc, 2)
        economic_profit_m    = round((roic_wacc_spread_pct / 100.0) * invested_capital_m, 1)

    # ── D2: Reinvestment rate + fundamentals-implied growth ────────
    # Reinvestment = (Capex − D&A) / NOPAT  → net capital that funds growth
    # Implied g = ROIC × Reinvestment  (Damodaran fundamentals-driven growth)
    reinvestment_rate_pct          = None
    implied_growth_fundamentals_pct = None
    try:
        if historical_fcf and ebit_m and ebit_m != 0:
            latest = historical_fcf[0]
            capex_abs_m = abs(latest.get("capex_m") or 0)       # stored negative
            dna_m       = latest.get("dna_m") or 0
            net_invest_m = capex_abs_m - dna_m                   # growth capex
            nopat_m      = ebit_m * (1.0 - tax_rate)
            if nopat_m > 0:
                reinvest_frac = max(0.0, net_invest_m) / nopat_m
                reinvestment_rate_pct = round(reinvest_frac * 100, 1)
                if roic_ttm_pct is not None:
                    implied_growth_fundamentals_pct = round(
                        roic_ttm_pct * reinvest_frac, 1
                    )
    except Exception:
        pass

    # ── D3: Earnings quality ───────────────────────────────────────
    # Cash conversion  = Σ5yr FCF / Σ5yr Net Income
    # Accruals ratio   = (NI − CFO) / Total Assets  (TTM)
    # SBC drag         = Σ5yr SBC / Σ5yr FCF
    # WC change        = ΔCurrent Assets − ΔCurrent Liabilities (most recent)
    cash_conversion_pct  = None
    accruals_ratio_pct   = None
    sbc_drag_pct         = None
    working_cap_change_m = None
    try:
        # Σ5yr FCF and SBC
        last5_fcf = [r for r in historical_fcf[:5]]
        fcf_sum   = sum(r.get("fcf_m") or 0 for r in last5_fcf)
        sbc_sum   = sum(r.get("sbc_m") or 0 for r in last5_fcf)

        # Σ5yr Net Income from eps_history (oldest→newest, take last 5)
        ni_sum = 0.0
        for r in (eps_history[-5:] if len(eps_history) >= 5 else eps_history):
            if r.get("eps") is not None and shares:
                ni_sum += (r["eps"] * shares) / 1e6

        if ni_sum > 0 and fcf_sum > 0:
            cash_conversion_pct = round((fcf_sum / ni_sum) * 100, 1)
        if fcf_sum > 0 and sbc_sum > 0:
            sbc_drag_pct = round((sbc_sum / fcf_sum) * 100, 1)

        # Accruals ratio (most recent year)
        if historical_fcf and total_assets_m > 0:
            latest   = historical_fcf[0]
            cfo_ttm_m = latest.get("op_cf_m") or 0
            ni_ttm_m  = None
            if eps_history:
                last_eps = eps_history[-1]
                if last_eps.get("eps") is not None and shares:
                    ni_ttm_m = (last_eps["eps"] * shares) / 1e6
            if ni_ttm_m is not None:
                accruals_ratio_pct = round(((ni_ttm_m - cfo_ttm_m) / total_assets_m) * 100, 2)
    except Exception as e:
        logger.warning("Could not compute earnings quality: %s", e)

    # ── Composite "Ultimate" quality score (0-100) ────────────────
    # Blends fundamentals (F-Score), solvency (Z-Score), and valuation signal.
    composite_score = None
    composite_band  = None
    composite_parts = {}
    try:
        f = scores.get("f_score")
        z = scores.get("z_score")
        z_band = scores.get("z_score_band")

        # F-Score component (0-40 points): 9 tests × ~4.4 pts each
        f_pts = round((f / 9.0) * 40, 1) if f is not None else 20.0

        # Z-Score component (0-25 points)
        if z is None:
            z_pts = 12.5
        elif z_band == "safe":
            z_pts = 25.0
        elif z_band == "grey":
            z_pts = 15.0
        else:
            z_pts = 5.0

        # Valuation component (0-20 points): compare current P/E to historical
        v_pts = 10.0
        if pe_history:
            pes = [r["pe"] for r in pe_history if r.get("pe")]
            if pes and pe_ttm and pe_ttm > 0:
                # cheap vs history = high score
                lo, hi = min(pes), max(pes)
                if hi > lo:
                    pctile = max(0.0, min(1.0, (pe_ttm - lo) / (hi - lo)))
                    v_pts = round((1.0 - pctile) * 20, 1)

        # Growth component (0-15 points)
        g_pts = max(0.0, min(15.0, (earnings_growth_pct + 5) / 40 * 15))

        composite_score = round(f_pts + z_pts + v_pts + g_pts, 1)
        composite_parts = {
            "fundamentals": f_pts,
            "solvency":     z_pts,
            "valuation":    v_pts,
            "growth":       round(g_pts, 1),
        }
        if composite_score >= 75:
            composite_band = "excellent"
        elif composite_score >= 55:
            composite_band = "good"
        elif composite_score >= 40:
            composite_band = "fair"
        else:
            composite_band = "weak"
    except Exception as e:
        logger.warning("Could not compute composite score: %s", e)

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
        "fcf_total_m":            round(fcf_total_latest / 1e6, 1),
        "fcf_per_share":          round(fcf_per_share, 2),
        "fcff_m":                 fcff_latest_m,
        "dna_m":                  round(dna_latest_m, 1),
        "sbc_m":                  round(sbc_latest_m, 1),
        "interest_expense_m":     round(interest_expense_m, 1),
        "owner_earnings_m":       owner_earnings_latest_m,
        "owner_earnings_per_share": round(owner_earnings_per_share, 2),
        "wacc_suggestion":        wacc,
        "wacc_detail":            wacc_detail,
        "earnings_growth_pct":    round(earnings_growth_pct, 1),

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

        # C1: Normalized earnings power + asset reproduction + moat
        "normalized_ebit_m":      normalized_ebit_m,
        "avg_ebit_margin_pct":    avg_ebit_margin_pct,
        "maintenance_capex_m":    maintenance_capex_m,
        "asset_reproduction_m":   round(asset_reproduction_m,  1),
        "asset_reproduction_ps":  round(asset_reproduction_ps, 2),
        "tangible_book_m":        round(tangible_book_m,       1),
        "tangible_book_ps":       round(tangible_book_ps,      2),
        "goodwill_m":             round(goodwill_m,            1),
        "intangibles_m":          round(intangibles_m,         1),
        "epv_firm_m":             epv_firm_m,
        "moat_premium_pct":       moat_premium_pct,

        # C2: Shareholder return
        "buybacks_m":                  round(buybacks_latest_m, 1),
        "dividends_paid_m":            round(dividends_paid_m,  1),
        "buyback_yield_pct":           buyback_yield_pct,
        "total_shareholder_yield_pct": total_shareholder_yield_pct,
        "payout_ratio_pct":            payout_ratio_pct,
        "cost_of_equity_pct":          cost_of_equity_pct,

        # C3: EV waterfall bridge
        "ev_bridge":          ev_bridge,
        "op_lease_liab_m":    round(op_lease_liab_m, 1),
        "pension_liab_m":     round(pension_liab_m,  1),
        "preferred_stock_m":  round(preferred_stock_m, 1),
        "minority_int_m":     round(minority_int_m,  1),

        # D1: ROIC & Economic Profit
        "roic_history":         roic_history,
        "roic_ttm_pct":         roic_ttm_pct,
        "roic_5yr_avg_pct":     roic_5yr_avg_pct,
        "roic_wacc_spread_pct": roic_wacc_spread_pct,
        "invested_capital_m":   round(invested_capital_m, 1),
        "economic_profit_m":    economic_profit_m,

        # D2: Fundamentals-implied growth
        "reinvestment_rate_pct":           reinvestment_rate_pct,
        "implied_growth_fundamentals_pct": implied_growth_fundamentals_pct,

        # D3: Earnings quality
        "cash_conversion_pct":  cash_conversion_pct,
        "accruals_ratio_pct":   accruals_ratio_pct,
        "sbc_drag_pct":         sbc_drag_pct,

        # PEG
        "peg_ratio": round(pe_ttm / earnings_growth_pct, 2)
                     if earnings_growth_pct > 0 and pe_ttm > 0 else 0,

        # Historical data for model charts
        "pe_history":         pe_history,
        "ps_history":         ps_history,
        "ev_ebitda_history":  ev_ebitda_history,
        "ev_ebit_history":    ev_ebit_history,
        "ebit_annual":        ebit_annual,
        "ebitda_annual":      ebitda_annual,
        "revenue_annual":     revenue_annual,
        "eps_history":        eps_history,
        "dividend_history":   dividend_history,

        # Ratio ↔ price correlations
        "correlations":       correlations,
        "best_multiple":      best_multiple,

        # Composite "Ultimate" score (0-100)
        "composite_score":    composite_score,
        "composite_band":     composite_band,
        "composite_parts":    composite_parts,

        # Business info
        "business_summary": business_summary,
        "price_history":    price_history,

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


# ── Gemini AI Business Analysis ──────────────────────────────────────────────

def get_business_analysis(ticker: str, financials: dict) -> dict:
    """Call Gemini to generate structured business analysis for a company."""
    from .gemini import generate_json

    prompt = f"""You are a senior equity research analyst. Produce a structured business analysis for {ticker} ({financials.get('name', ticker)}).

Company context:
- Sector: {financials.get('sector', 'N/A')}
- Industry: {financials.get('industry', 'N/A')}
- Market Cap: {financials.get('market_cap_fmt', 'N/A')}
- Revenue: ${financials.get('revenue_m', 0):.0f}M
- EBITDA: ${financials.get('ebitda_m', 0):.0f}M
- EBIT: ${financials.get('ebit_m', 0):.0f}M
- P/E TTM: {financials.get('pe_ttm', 'N/A')}
- EV/EBITDA: {financials.get('ev_ebitda_current', 'N/A')}
- Beta: {financials.get('beta', 'N/A')}
- Business Summary: {(financials.get('business_summary', '') or '')[:500]}

Return ONLY valid JSON with these exact keys:
{{
  "business_model": "80-120 words: what does this company do, how does it make money, what is the core value proposition",
  "revenue_segments": "80-120 words: break down key revenue streams / business segments, approximate % contribution of each, and which are growing fastest",
  "swot": {{
    "strengths": ["3-4 bullet points, each 10-20 words"],
    "weaknesses": ["3-4 bullet points"],
    "opportunities": ["3-4 bullet points"],
    "threats": ["3-4 bullet points"]
  }},
  "moat": "60-80 words: assess the company's economic moat (brand, network effects, cost advantage, switching costs, intangible assets). Rate as: None, Narrow, or Wide",
  "moat_rating": "None|Narrow|Wide",
  "governance": "60-80 words: assess corporate governance quality — management tenure, insider ownership, board independence, capital allocation track record, any red flags. Rate as: Weak, Average, or Strong",
  "governance_rating": "Weak|Average|Strong"
}}

Be specific to this company. Reference actual facts. Return only valid JSON."""

    # Cache per-ticker per-sector — changes in financials rarely alter analysis
    cache_key = f"biz_analysis:{ticker.upper()}:{financials.get('sector', '')}"
    result = generate_json(prompt, cache_key=cache_key, temperature=0.3)
    if result is None:
        return {"error": "AI analysis unavailable"}
    return result
