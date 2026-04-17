"""Portfolio optimization algorithms.

Pure functions operating on (mu, S) inputs — no Flask, no yfinance, no I/O.
Extracted from routes for testability and reuse.
"""

import logging

import numpy as np

from .analytics import generate_frontier

logger = logging.getLogger(__name__)


def _pypfopt():
    """Lazy import — PyPortfolioOpt pulls in ~50MB of transitive deps."""
    from pypfopt import (
        BlackLittermanModel,
        EfficientFrontier,
        expected_returns,
        risk_models,
    )
    return EfficientFrontier, risk_models, expected_returns, BlackLittermanModel


# ── Simple methods ───────────────────────────────────────────────────────────

def run_max_sharpe(mu, S, weight_bounds, rfr):
    EfficientFrontier, *_ = _pypfopt()
    ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
    try:
        ef.max_sharpe(risk_free_rate=rfr)
    except Exception as exc:
        logger.warning("max_sharpe failed (%s); falling back to min_volatility", exc)
        ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
        ef.min_volatility()
    return ef.clean_weights()


def run_min_volatility(mu, S, weight_bounds):
    EfficientFrontier, *_ = _pypfopt()
    ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
    ef.min_volatility()
    return ef.clean_weights()


def run_max_return(mu, S, weight_bounds):
    EfficientFrontier, *_ = _pypfopt()
    ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
    ef.efficient_return(target_return=float(mu.max()) * 0.98)
    return ef.clean_weights()


def run_equal_weight(tickers: list[str]) -> dict[str, float]:
    n = len(tickers)
    return {t: 1.0 / n for t in tickers}


# ── Black-Litterman ──────────────────────────────────────────────────────────

def run_black_litterman(
    available: list[str],
    mu,
    S,
    weight_bounds,
    rfr: float,
    *,
    views_data: dict,
    market_caps: dict,
    tau: float = 0.05,
    risk_aversion: float = 2.5,
) -> tuple[dict, dict, dict]:
    """Returns (cleaned_weights, frontier_bl, bl_info)."""
    EfficientFrontier, _risk_models, _expected_returns, BlackLittermanModel = _pypfopt()

    raw_caps = {
        k: float(v) for k, v in market_caps.items()
        if k in available and float(v or 0) > 0
    }
    if not raw_caps:
        raw_caps = {t: 1.0 for t in available}
    tc = sum(raw_caps.values())
    mcap_w = {k: v / tc for k, v in raw_caps.items()}

    abs_views: dict[str, float] = {}
    confidences: list[float] = []
    for sym, vd in views_data.items():
        if sym in available and vd.get("enabled") and vd.get("return") is not None:
            abs_views[sym] = float(vd["return"])
            confidences.append(max(0.01, min(0.99, float(vd.get("confidence", 0.5)))))

    bl_kwargs = dict(pi="market", market_caps=mcap_w, risk_aversion=risk_aversion, tau=tau)
    if abs_views:
        bl = BlackLittermanModel(S, absolute_views=abs_views, omega="idzorek",
                                 view_confidences=confidences, **bl_kwargs)
    else:
        bl = BlackLittermanModel(S, **bl_kwargs)

    mu_bl = bl.bl_returns()
    S_bl = bl.bl_cov()
    prior_r = dict(zip(available, bl.pi.flatten().tolist()))
    post_r = dict(mu_bl)

    ef = EfficientFrontier(mu_bl, S_bl, weight_bounds=weight_bounds)
    try:
        ef.max_sharpe(risk_free_rate=rfr)
    except Exception as exc:
        logger.warning("BL max_sharpe failed (%s); falling back to min_volatility", exc)
        ef = EfficientFrontier(mu_bl, S_bl, weight_bounds=weight_bounds)
        ef.min_volatility()
    cleaned = ef.clean_weights()
    frontier_bl = generate_frontier(mu_bl, S_bl, weight_bounds, rfr)

    enabled_syms = [
        s for s, vd in views_data.items()
        if s in available and vd.get("enabled") and vd.get("return") is not None
    ]
    bl_info = {
        "prior_returns":     {k: round(v, 6) for k, v in prior_r.items()},
        "posterior_returns": {k: round(float(v), 6) for k, v in post_r.items()},
        "views":             abs_views,
        "market_weights":    {k: round(float(v), 6) for k, v in mcap_w.items()},
        "confidences":       {sym: round(conf, 4)
                              for sym, conf in zip(enabled_syms, confidences)},
    }

    sensitivity: dict = {}
    if abs_views:
        conf_low = [c * 0.5 for c in confidences]
        conf_high = [min(0.99, c * 1.5) for c in confidences]
        try:
            bl_low = BlackLittermanModel(S, absolute_views=abs_views, omega="idzorek",
                                         view_confidences=conf_low, **bl_kwargs)
            ef_low = EfficientFrontier(bl_low.bl_returns(), bl_low.bl_cov(),
                                       weight_bounds=weight_bounds)
            ef_low.max_sharpe(risk_free_rate=rfr)
            sl = ef_low.clean_weights()

            bl_high = BlackLittermanModel(S, absolute_views=abs_views, omega="idzorek",
                                          view_confidences=conf_high, **bl_kwargs)
            ef_high = EfficientFrontier(bl_high.bl_returns(), bl_high.bl_cov(),
                                        weight_bounds=weight_bounds)
            ef_high.max_sharpe(risk_free_rate=rfr)
            sh = ef_high.clean_weights()

            for sym in cleaned:
                sensitivity[sym] = {
                    "base": round(cleaned.get(sym, 0), 4),
                    "low":  round(sl.get(sym, 0), 4),
                    "high": round(sh.get(sym, 0), 4),
                }
        except Exception as exc:
            logger.warning("BL sensitivity analysis failed: %s", exc)
    bl_info["sensitivity"] = sensitivity
    return cleaned, frontier_bl, bl_info


# ── Risk parity ──────────────────────────────────────────────────────────────

def run_risk_parity(available: list[str], S, weight_bounds) -> dict[str, float]:
    from scipy.optimize import minimize

    n = len(available)
    cov_arr = S.values

    def rp_obj(w):
        pv = w @ cov_arr @ w
        if pv <= 0:
            return 1e9
        rc = w * (cov_arr @ w) / pv
        return float(np.sum((rc - np.ones(n) / n) ** 2))

    res = minimize(
        rp_obj, np.ones(n) / n, method="SLSQP",
        bounds=[weight_bounds] * n,
        constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1}],
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    raw_w = {available[i]: max(0.0, res.x[i]) for i in range(n)}
    tot = sum(raw_w.values())
    return {k: v / tot for k, v in raw_w.items()}


# ── Hierarchical risk parity ─────────────────────────────────────────────────

def run_hrp(available: list[str], S) -> tuple[dict, dict]:
    """Returns (cleaned_weights, hrp_info)."""
    from pypfopt.hierarchical_portfolio import HRPOpt
    import scipy.cluster.hierarchy as sch
    import scipy.spatial.distance as ssd

    hrp = HRPOpt(cov_matrix=S)
    cleaned = dict(hrp.optimize())

    corr_mat = S.copy()
    vols = np.sqrt(np.diag(S))
    for i in range(len(S.columns)):
        for j in range(len(S.columns)):
            if vols[i] * vols[j] > 0:
                corr_mat.iloc[i, j] = S.iloc[i, j] / (vols[i] * vols[j])
    corr_mat = corr_mat.clip(-1.0, 1.0)
    dist_mat = np.sqrt(np.clip((1 - corr_mat) / 2.0, 0.0, 1.0))
    np.fill_diagonal(dist_mat.values, 0.0)

    dist_array = ssd.squareform(dist_mat)
    if len(dist_array) > 0:
        link = sch.linkage(dist_array, "single")
        sort_ix = sch.leaves_list(link)
    else:
        link = None
        sort_ix = list(range(len(S.columns)))

    sorted_tickers = [available[int(i)] for i in sort_ix]
    qd_corr = corr_mat.iloc[sort_ix, sort_ix]
    w_arr = np.array([cleaned.get(t, 0) for t in sorted_tickers])
    cov_sorted = S.iloc[sort_ix, sort_ix].values
    port_var = w_arr.T @ cov_sorted @ w_arr
    if port_var > 0:
        marginal_contrib = cov_sorted @ w_arr
        risk_contrib = np.multiply(w_arr, marginal_contrib) / port_var
    else:
        risk_contrib = np.zeros(len(w_arr))

    hrp_info = {
        "tickers":            available,
        "sorted_tickers":     sorted_tickers,
        "distance_matrix":    dist_mat.values.tolist(),
        "qd_correlation":     qd_corr.values.tolist(),
        "risk_contributions": dict(zip(sorted_tickers, (risk_contrib * 100).tolist())),
        "linkage":            link.tolist() if link is not None else [],
    }
    return cleaned, hrp_info
