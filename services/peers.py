"""Peer comparison — curated industry→peer-set map + fetch + justified P/E.

Produces, for a target ticker:
    - a peer table (up to ~6 companies) with P/E, growth, ROE, ROIC, margin
    - sector-median target P/E
    - regression-based "justified" P/E = a + b·growth + c·ROE
    - historical average target P/E if available

The curated map avoids needing a real database — yfinance doesn't ship a
"same industry, size band ±50%" screener. Keep the list small and updateable.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


# ── Curated industry-ish peer sets ──────────────────────────────────────────
# Key is a ticker; value is its peer group (excluding itself in the response).
# Keeping this curated by hand → small & fast on a serverless Flask.
_PEER_SETS = {
    # ── Mega-cap tech ────────────────────────────────────────────
    "AAPL":  ["MSFT", "GOOGL", "META", "AMZN", "NVDA", "ORCL"],
    "MSFT":  ["AAPL", "GOOGL", "META", "AMZN", "ORCL", "CRM"],
    "GOOGL": ["META", "MSFT", "AAPL", "AMZN", "PINS", "SNAP"],
    "GOOG":  ["META", "MSFT", "AAPL", "AMZN", "PINS", "SNAP"],
    "META":  ["GOOGL", "PINS", "SNAP", "MSFT", "AAPL", "AMZN"],
    "AMZN":  ["MSFT", "GOOGL", "AAPL", "META", "SHOP", "MELI"],
    "NVDA":  ["AMD", "INTC", "QCOM", "AVGO", "MRVL", "TSM"],
    "AMD":   ["NVDA", "INTC", "QCOM", "AVGO", "MRVL", "TSM"],
    "INTC":  ["NVDA", "AMD", "AVGO", "QCOM", "TSM", "MU"],
    "TSLA":  ["F", "GM", "TM", "RIVN", "LCID", "BYDDY"],

    # ── Semis / hardware ─────────────────────────────────────────
    "AVGO":  ["NVDA", "AMD", "QCOM", "INTC", "TSM", "MRVL"],
    "QCOM":  ["AVGO", "NVDA", "AMD", "MRVL", "INTC", "TSM"],
    "TSM":   ["NVDA", "AVGO", "INTC", "AMD", "ASML", "MU"],
    "ASML":  ["AMAT", "LRCX", "KLAC", "TSM", "INTC"],
    "AMAT":  ["ASML", "LRCX", "KLAC", "TSM", "INTC"],

    # ── Software / SaaS ──────────────────────────────────────────
    "CRM":   ["MSFT", "ORCL", "ADBE", "NOW", "WDAY", "SAP"],
    "ORCL":  ["MSFT", "CRM", "SAP", "IBM", "ADBE"],
    "ADBE":  ["CRM", "MSFT", "ORCL", "INTU", "NOW"],
    "NOW":   ["CRM", "WDAY", "ADBE", "INTU", "SNOW"],
    "SNOW":  ["MDB", "DDOG", "NET", "NOW", "CRM"],
    "SHOP":  ["AMZN", "SQ", "ETSY", "MELI", "EBAY"],

    # ── Financial services ───────────────────────────────────────
    "JPM":   ["BAC", "WFC", "C", "GS", "MS"],
    "BAC":   ["JPM", "WFC", "C", "GS", "MS"],
    "WFC":   ["JPM", "BAC", "C", "GS", "PNC"],
    "C":     ["JPM", "BAC", "WFC", "GS", "MS"],
    "GS":    ["MS", "JPM", "BAC", "C"],
    "MS":    ["GS", "JPM", "BAC", "C"],
    "V":     ["MA", "AXP", "PYPL", "DFS"],
    "MA":    ["V", "AXP", "PYPL", "DFS"],
    "BRK-B": ["JPM", "BAC", "V", "MA"],
    "BLK":   ["MS", "GS", "BX", "KKR", "APO"],

    # ── Healthcare / pharma ──────────────────────────────────────
    "JNJ":   ["PFE", "MRK", "ABBV", "LLY", "BMY"],
    "PFE":   ["JNJ", "MRK", "ABBV", "LLY", "BMY"],
    "MRK":   ["JNJ", "PFE", "ABBV", "LLY", "BMY"],
    "LLY":   ["NVO", "MRK", "PFE", "JNJ", "ABBV"],
    "ABBV":  ["JNJ", "PFE", "MRK", "LLY", "BMY"],
    "UNH":   ["CVS", "CI", "HUM", "ELV", "CNC"],

    # ── Consumer staples & defensives ────────────────────────────
    "KO":    ["PEP", "MNST", "KDP"],
    "PEP":   ["KO", "MNST", "KDP"],
    "PG":    ["UL", "CL", "KMB", "CHD"],
    "WMT":   ["COST", "TGT", "KR", "DG", "DLTR"],
    "COST":  ["WMT", "TGT", "BJ", "KR"],
    "MCD":   ["SBUX", "YUM", "CMG", "DPZ", "QSR"],
    "SBUX":  ["MCD", "YUM", "CMG", "DPZ"],
    "NKE":   ["LULU", "UAA", "ADDYY", "DECK", "ONON"],

    # ── Energy ───────────────────────────────────────────────────
    "XOM":   ["CVX", "COP", "SHEL", "BP", "TTE"],
    "CVX":   ["XOM", "COP", "SHEL", "BP", "TTE"],
    "COP":   ["XOM", "CVX", "EOG", "OXY", "DVN"],

    # ── Industrials ──────────────────────────────────────────────
    "BA":    ["LMT", "RTX", "NOC", "GD", "HII"],
    "CAT":   ["DE", "CMI", "PCAR", "ETN"],
    "DE":    ["CAT", "CNH", "AGCO"],
    "HON":   ["GE", "MMM", "EMR", "ITW", "ROK"],

    # ── Communication services ───────────────────────────────────
    "NFLX":  ["DIS", "PARA", "WBD", "ROKU", "SPOT"],
    "DIS":   ["NFLX", "PARA", "WBD", "CMCSA", "SONY"],
    "T":     ["VZ", "TMUS", "CMCSA", "CHTR"],
    "VZ":    ["T", "TMUS", "CMCSA", "CHTR"],
}


def get_peer_tickers(ticker: str) -> list[str]:
    """Return up to 6 peer tickers (excluding self). Empty list if unknown."""
    key = ticker.upper().strip()
    peers = _PEER_SETS.get(key) or []
    # Deduplicate + cap at 6
    seen, out = set(), []
    for p in peers:
        if p and p != key and p not in seen:
            seen.add(p); out.append(p)
        if len(out) >= 6:
            break
    return out


def _safe_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        f = float(v)
        if f != f:       # NaN
            return default
        return f
    except Exception:
        return default


def fetch_peer_metrics(ticker: str) -> dict:
    """Return { target: {...}, peers: [...], stats: {...} } for the P/E card.

    Heavy network call (yfinance .info once per peer). Caller should cache.
    """
    import yfinance as yf

    peers = get_peer_tickers(ticker)
    if not peers:
        return {
            "target":  _fetch_one(yf.Ticker(ticker), ticker),
            "peers":   [],
            "stats":   {},
            "message": "No curated peer set for this ticker yet.",
        }

    tgt  = _fetch_one(yf.Ticker(ticker), ticker)
    rows = []
    for sym in peers:
        try:
            rows.append(_fetch_one(yf.Ticker(sym), sym))
        except Exception as e:
            logger.warning("Peer %s fetch failed: %s", sym, e)

    # Keep only peers with a usable P/E
    usable = [r for r in rows if r.get("pe") and 2 < r["pe"] < 200]

    pes      = [r["pe"]     for r in usable]
    growths  = [r["growth"] for r in usable if r.get("growth") is not None]
    roes     = [r["roe"]    for r in usable if r.get("roe")    is not None]
    roics    = [r["roic"]   for r in usable if r.get("roic")   is not None]
    margins  = [r["margin"] for r in usable if r.get("margin") is not None]

    median_pe = _median(pes)

    # Regression: fair-P/E ≈ a + b·growth + c·ROE
    regression = _regress_pe(usable)
    justified_pe = None
    if regression and tgt:
        try:
            tg = tgt.get("growth") or 0.0
            tr = tgt.get("roe")    or 0.0
            justified_pe = round(
                regression["a"] + regression["b"] * tg + regression["c"] * tr, 1
            )
            if justified_pe < 2 or justified_pe > 100:
                justified_pe = None
        except Exception:
            justified_pe = None

    stats = {
        "median_pe":     round(median_pe,  1) if median_pe  else None,
        "median_growth": round(_median(growths) * 100, 1) if growths else None,
        "median_roe":    round(_median(roes)    * 100, 1) if roes    else None,
        "median_roic":   round(_median(roics)   * 100, 1) if roics   else None,
        "median_margin": round(_median(margins) * 100, 1) if margins else None,
        "regression":    regression,
        "justified_pe":  justified_pe,
        "n_peers":       len(usable),
    }
    return {"target": tgt, "peers": rows, "stats": stats}


def _fetch_one(t, sym: str) -> dict:
    """Pull 5 fields from yfinance .info for one ticker."""
    try:
        info = t.info or {}
    except Exception:
        info = {}
    mcap   = _safe_float(info.get("marketCap"))
    pe     = _safe_float(info.get("trailingPE"))
    fwd_pe = _safe_float(info.get("forwardPE"))
    growth = info.get("earningsGrowth")
    if growth is None:
        growth = info.get("earningsQuarterlyGrowth")
    roe    = info.get("returnOnEquity")
    # yfinance doesn't ship a ROIC — approximate with ROA × leverage
    roa    = info.get("returnOnAssets")
    margin = info.get("profitMargins")

    # Rough ROIC proxy: EBIT × (1−tax) / invested capital.
    # Without balance-sheet hitting here, reuse ROE × (equity / (equity+debt))
    # to dampen leverage effects. Fall back to ROA when book value is absent.
    roic = None
    try:
        eq  = _safe_float(info.get("marketCap"))
        td  = _safe_float(info.get("totalDebt"))
        bk  = _safe_float(info.get("bookValue"))
        sh  = _safe_float(info.get("sharesOutstanding"))
        if roe is not None and bk and sh:
            book_eq = bk * sh
            total_cap = book_eq + td
            roic = float(roe) * (book_eq / total_cap) if total_cap else float(roe)
        elif roa is not None:
            roic = float(roa)
    except Exception:
        pass

    return {
        "ticker":  sym.upper(),
        "name":    info.get("shortName") or info.get("longName") or sym.upper(),
        "mcap_m":  round(mcap / 1e6, 0) if mcap else None,
        "pe":      round(pe,     1) if pe     else None,
        "fwd_pe":  round(fwd_pe, 1) if fwd_pe else None,
        "growth":  _safe_float(growth, None) if growth is not None else None,
        "roe":     _safe_float(roe,    None) if roe    is not None else None,
        "roic":    roic,
        "margin":  _safe_float(margin, None) if margin is not None else None,
    }


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if not n:
        return None
    if n % 2 == 1:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _regress_pe(peers: list[dict]) -> dict | None:
    """Multivariate OLS: pe ~ a + b·growth + c·roe. Needs ≥4 valid points."""
    X, Y = [], []
    for r in peers:
        g = r.get("growth")
        e = r.get("roe")
        p = r.get("pe")
        if p is None or g is None or e is None:
            continue
        X.append([1.0, float(g), float(e)])
        Y.append(float(p))
    if len(X) < 4:
        # Fall back to univariate pe ~ a + b·growth
        return _regress_simple(peers)

    # Closed-form OLS via numpy
    try:
        import numpy as np
        xm = np.array(X, dtype=float)
        ym = np.array(Y, dtype=float)
        coef, *_ = np.linalg.lstsq(xm, ym, rcond=None)
        a, b, c = float(coef[0]), float(coef[1]), float(coef[2])
        return {"a": round(a, 2), "b": round(b, 2), "c": round(c, 2),
                "form": "pe = a + b·growth + c·ROE", "n": len(X)}
    except Exception:
        return _regress_simple(peers)


def _regress_simple(peers: list[dict]) -> dict | None:
    xs, ys = [], []
    for r in peers:
        g = r.get("growth")
        p = r.get("pe")
        if g is None or p is None:
            continue
        xs.append(float(g)); ys.append(float(p))
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den == 0:
        return None
    b = num / den
    a = my - b * mx
    return {"a": round(a, 2), "b": round(b, 2), "c": 0.0,
            "form": "pe = a + b·growth", "n": n}
