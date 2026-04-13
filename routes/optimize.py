"""Optimization, analytics, and simulation API routes."""

import logging
import traceback

import numpy as np
import yfinance as yf
import pandas as pd
from flask import Blueprint, request, jsonify
from pypfopt import EfficientFrontier, risk_models, expected_returns, BlackLittermanModel
from scipy.optimize import minimize

from services.data import fetch_prices, fetch_benchmark, BENCHMARK, TRADING_DAYS
from services.analytics import compute_risk_metrics, apply_overrides, generate_frontier, compute_descriptive_stats

logger = logging.getLogger(__name__)
optimize_bp = Blueprint("optimize", __name__)

VALID_METHODS = {
    "max_sharpe", "min_volatility", "black_litterman",
    "risk_parity", "hrp", "equal_weight", "max_return",
}

STRESS_SCENARIOS = {
    "gfc_2008":     ("2008 Financial Crisis",     "2008-09-01", "2008-12-31"),
    "covid_2020":   ("COVID Crash",               "2020-02-19", "2020-03-23"),
    "rout_2022":    ("2022 Rate-Hike Selloff",    "2022-01-03", "2022-10-12"),
    "dot_com":      ("Dot-com Bust",              "2000-03-10", "2002-10-09"),
    "rate_1994":    ("1994 Bond Shock",           "1994-01-01", "1994-11-30"),
    "inflation_80": ("1980 Inflation Shock",      "1980-01-01", "1982-08-12"),
}


def _bad(msg: str):
    return jsonify({"error": msg}), 400


def _server_error(e: Exception):
    logger.error(traceback.format_exc())
    return jsonify({"error": str(e)}), 500


# ── Ticker validation ──────────────────────────────────────────────────────────

@optimize_bp.route("/api/validate_ticker", methods=["POST"])
def validate_ticker():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")
    sym = str(data.get("ticker", "")).upper().strip()
    if not sym:
        return jsonify({"valid": False, "error": "Empty ticker symbol."}), 400
    try:
        t = yf.Ticker(sym)
        info = t.info
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
            or 0
        )
        name = info.get("longName") or info.get("shortName") or sym
        return jsonify({
            "valid": True,
            "ticker": sym,
            "name": name,
            "price": round(float(price), 2) if price else 0,
            "sector": info.get("sector", "N/A"),
            "market_cap": info.get("marketCap", 0),
        })
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)})


# ── Stock data ─────────────────────────────────────────────────────────────────

@optimize_bp.route("/api/stock_data", methods=["POST"])
def stock_data():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")
    tickers = data.get("tickers", [])
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not isinstance(tickers, list) or not tickers:
        return _bad("tickers must be a non-empty list.")
    if not start_date or not end_date:
        return _bad("start_date and end_date are required.")
    try:
        prices = fetch_prices(tickers, start_date, end_date)
        result = {}
        for sym in prices.columns:
            col = prices[sym].dropna()
            if len(col) < 5:
                continue
            rets = col.pct_change().dropna()
            ann_ret = float(expected_returns.mean_historical_return(prices[[sym]].dropna()).iloc[0])
            ann_vol = float(np.sqrt(TRADING_DAYS) * rets.std())
            total = float(col.iloc[-1] / col.iloc[0] - 1)
            sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
            spark = col.iloc[-120:]
            base = float(spark.iloc[0]) if float(spark.iloc[0]) != 0 else 1
            result[sym] = {
                "ann_return":   round(ann_ret * 100, 2),
                "ann_vol":      round(ann_vol * 100, 2),
                "total_return": round(total * 100, 2),
                "sharpe":       round(sharpe, 3),
                "n_days":       int(len(rets)),
                "sparkline":    [round(float(v) / base, 4) for v in spark.tolist()],
            }
        return jsonify({"data": result})
    except ValueError as e:
        return _bad(str(e))
    except Exception as e:
        return _server_error(e)


# ── Optimization ───────────────────────────────────────────────────────────────

@optimize_bp.route("/api/optimize", methods=["POST"])
def optimize():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")

    tickers = data.get("tickers")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    method = data.get("method")

    if not isinstance(tickers, list) or len(tickers) < 2:
        return _bad("tickers must be a list of at least 2 symbols.")
    if not start_date or not end_date:
        return _bad("start_date and end_date are required.")
    if method not in VALID_METHODS:
        return _bad(f"Invalid method. Choose from: {', '.join(sorted(VALID_METHODS))}")

    try:
        rfr = float(data.get("risk_free_rate", 0.04))
        min_w = float(data.get("min_weight", 0.0))
        max_w = float(data.get("max_weight", 1.0))
        weight_bounds = (min_w, max_w)
        ret_ov = {k: float(v) / 100 for k, v in (data.get("return_overrides") or {}).items()}
        vol_ov = {k: float(v) / 100 for k, v in (data.get("vol_overrides") or {}).items()}

        prices = fetch_prices(tickers, start_date, end_date)
        if len(prices) < 30:
            return _bad(f"Only {len(prices)} trading days. Extend the date range.")
        available = list(prices.columns)
        if len(available) < 2:
            return _bad(f"Only {available} had data.")

        bench_prices = fetch_benchmark(start_date, end_date)
        mu = expected_returns.mean_historical_return(prices)
        S = risk_models.sample_cov(prices)
        mu, S = apply_overrides(mu, S, ret_ov, vol_ov)

        frontier = generate_frontier(mu, S, weight_bounds, rfr)
        frontier_bl = None
        bl_info = None
        hrp_info = None

        # ── Dispatch by method ─────────────────────────────────────────────────
        if method == "black_litterman":
            cleaned, frontier_bl, bl_info = _run_black_litterman(
                data, available, mu, S, weight_bounds, rfr
            )
        elif method == "max_sharpe":
            ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
            try:
                ef.max_sharpe(risk_free_rate=rfr)
            except Exception:
                ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
                ef.min_volatility()
            cleaned = ef.clean_weights()
        elif method == "min_volatility":
            ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
            ef.min_volatility()
            cleaned = ef.clean_weights()
        elif method == "risk_parity":
            cleaned = _run_risk_parity(available, S, weight_bounds)
        elif method == "hrp":
            cleaned, hrp_info = _run_hrp(available, S)
        elif method == "equal_weight":
            cleaned = {t: 1.0 / len(available) for t in available}
        elif method == "max_return":
            ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
            ef.efficient_return(target_return=float(mu.max()) * 0.98)
            cleaned = ef.clean_weights()

        analytics = compute_risk_metrics(cleaned, prices, rfr, bench_prices)
        descriptive_stats = compute_descriptive_stats(prices)
        resp = {"weights": dict(cleaned), "analytics": analytics, "frontier": frontier,
                "descriptive_stats": descriptive_stats}
        if frontier_bl:
            resp["frontier_bl"] = frontier_bl
        if bl_info:
            resp["bl_info"] = bl_info
        if hrp_info:
            resp["hrp_info"] = hrp_info
        return jsonify(resp)

    except ValueError as e:
        return _bad(str(e))
    except Exception as e:
        return _server_error(e)


def _run_black_litterman(data, available, mu, S, weight_bounds, rfr):
    views_data = data.get("views", {})
    market_caps = data.get("market_caps", {})
    tau = float(data.get("tau", 0.05))
    risk_aversion = float(data.get("risk_aversion", 2.5))

    raw_caps = {k: float(v) for k, v in market_caps.items() if k in available and float(v or 0) > 0}
    if not raw_caps:
        raw_caps = {t: 1.0 for t in available}
    tc = sum(raw_caps.values())
    mcap_w = {k: v / tc for k, v in raw_caps.items()}

    abs_views, confidences = {}, []
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
    except Exception:
        ef = EfficientFrontier(mu_bl, S_bl, weight_bounds=weight_bounds)
        ef.min_volatility()
    cleaned = ef.clean_weights()
    frontier_bl = generate_frontier(mu_bl, S_bl, weight_bounds, rfr)

    bl_info = {
        "prior_returns":     {k: round(v, 6) for k, v in prior_r.items()},
        "posterior_returns": {k: round(float(v), 6) for k, v in post_r.items()},
        "views":             abs_views,
        "market_weights":    {k: round(float(v), 6) for k, v in mcap_w.items()},
        "confidences":       {
            sym: round(conf, 4)
            for sym, conf in zip(
                [s for s, vd in views_data.items() if s in available and vd.get("enabled") and vd.get("return") is not None],
                confidences,
            )
        },
    }

    sensitivity = {}
    if abs_views:
        conf_low = [c * 0.5 for c in confidences]
        conf_high = [min(0.99, c * 1.5) for c in confidences]
        try:
            bl_low = BlackLittermanModel(S, absolute_views=abs_views, omega="idzorek",
                                          view_confidences=conf_low, **bl_kwargs)
            ef_low = EfficientFrontier(bl_low.bl_returns(), bl_low.bl_cov(), weight_bounds=weight_bounds)
            ef_low.max_sharpe(risk_free_rate=rfr)
            sl = ef_low.clean_weights()

            bl_high = BlackLittermanModel(S, absolute_views=abs_views, omega="idzorek",
                                           view_confidences=conf_high, **bl_kwargs)
            ef_high = EfficientFrontier(bl_high.bl_returns(), bl_high.bl_cov(), weight_bounds=weight_bounds)
            ef_high.max_sharpe(risk_free_rate=rfr)
            sh = ef_high.clean_weights()

            for sym in cleaned.keys():
                sensitivity[sym] = {
                    "base": round(cleaned.get(sym, 0), 4),
                    "low":  round(sl.get(sym, 0), 4),
                    "high": round(sh.get(sym, 0), 4),
                }
        except Exception:
            pass
    bl_info["sensitivity"] = sensitivity
    return cleaned, frontier_bl, bl_info


def _run_risk_parity(available, S, weight_bounds):
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


def _run_hrp(available, S):
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
        "tickers":          available,
        "sorted_tickers":   sorted_tickers,
        "distance_matrix":  dist_mat.values.tolist(),
        "qd_correlation":   qd_corr.values.tolist(),
        "risk_contributions": dict(zip(sorted_tickers, (risk_contrib * 100).tolist())),
        "linkage":          link.tolist() if len(dist_array) > 0 else [],
    }
    return cleaned, hrp_info


# ── Analyze (custom / toggled weights) ────────────────────────────────────────

@optimize_bp.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")
    weights = data.get("weights")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not isinstance(weights, dict) or not weights:
        return _bad("weights must be a non-empty object.")
    if not start_date or not end_date:
        return _bad("start_date and end_date are required.")
    try:
        rfr = float(data.get("risk_free_rate", 0.04))
        tickers = [t for t, w in weights.items() if w > 0]
        if not tickers:
            return _bad("Need at least 1 active stock.")
        active_w = {t: weights[t] for t in tickers}
        total = sum(active_w.values())
        if total <= 0:
            return _bad("Weights sum to zero.")
        active_w = {t: w / total for t, w in active_w.items()}
        prices = fetch_prices(tickers, start_date, end_date)
        bench = fetch_benchmark(start_date, end_date)
        analytics = compute_risk_metrics(active_w, prices, rfr, bench)
        descriptive_stats = compute_descriptive_stats(prices)
        return jsonify({"weights": active_w, "analytics": analytics,
                        "descriptive_stats": descriptive_stats})
    except ValueError as e:
        return _bad(str(e))
    except Exception as e:
        return _server_error(e)


# ── Rebalancing ────────────────────────────────────────────────────────────────

@optimize_bp.route("/api/rebalance", methods=["POST"])
def rebalance():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")
    current_values = data.get("current_values")
    target_weights = data.get("target_weights")
    if not isinstance(current_values, dict) or not isinstance(target_weights, dict):
        return _bad("current_values and target_weights must be objects.")
    try:
        total_value = sum(float(v) for v in current_values.values())
        if total_value <= 0:
            return _bad("Total portfolio value is zero.")
        tw_sum = sum(float(w) for w in target_weights.values())
        target_w = {k: float(v) / tw_sum for k, v in target_weights.items()}
        trades = {}
        for sym in set(list(current_values.keys()) + list(target_w.keys())):
            cur = float(current_values.get(sym, 0))
            tgt = target_w.get(sym, 0) * total_value
            diff = tgt - cur
            trades[sym] = {
                "current_value":  round(cur, 2),
                "current_weight": round(cur / total_value * 100, 2),
                "target_value":   round(tgt, 2),
                "target_weight":  round(target_w.get(sym, 0) * 100, 2),
                "trade_value":    round(diff, 2),
                "action":         "BUY" if diff > 0.5 else ("SELL" if diff < -0.5 else "HOLD"),
            }
        return jsonify({"total_value": round(total_value, 2), "trades": trades})
    except Exception as e:
        return _server_error(e)


# ── Monte Carlo ────────────────────────────────────────────────────────────────

@optimize_bp.route("/api/montecarlo", methods=["POST"])
def montecarlo():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")
    weights = data.get("weights")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not isinstance(weights, dict) or not weights:
        return _bad("weights must be a non-empty object.")
    if not start_date or not end_date:
        return _bad("start_date and end_date are required.")
    try:
        n_sims = min(int(data.get("n_sims", 500)), 2000)
        horizon = min(int(data.get("horizon", 252)), 1260)
        tickers = [t for t, w in weights.items() if float(w) > 0]
        if not tickers:
            return _bad("No active weights.")
        prices = fetch_prices(tickers, start_date, end_date)
        active_w = {t: float(weights[t]) for t in tickers if t in prices.columns}
        total = sum(active_w.values())
        if total <= 0:
            return _bad("Weights sum to zero.")
        active_w = {t: v / total for t, v in active_w.items()}
        tickers = list(active_w.keys())
        w_arr = np.array([active_w[t] for t in tickers])
        rets = prices[tickers].pct_change().dropna()
        mean_vec = rets.mean().values
        cov_mat = rets.cov().values
        rng = np.random.default_rng(42)
        daily = rng.multivariate_normal(mean_vec, cov_mat, size=(n_sims, horizon))
        port_daily = daily @ w_arr
        cum = np.cumprod(1 + port_daily, axis=1) - 1
        pcts = np.percentile(cum, [5, 25, 50, 75, 95], axis=0)
        final = cum[:, -1]
        idx = rng.choice(n_sims, size=min(50, n_sims), replace=False)
        sample_paths = (cum[idx] * 100).round(2).tolist()
        return jsonify({
            "percentiles": {
                "p5":  (pcts[0] * 100).round(2).tolist(),
                "p25": (pcts[1] * 100).round(2).tolist(),
                "p50": (pcts[2] * 100).round(2).tolist(),
                "p75": (pcts[3] * 100).round(2).tolist(),
                "p95": (pcts[4] * 100).round(2).tolist(),
            },
            "sample_paths":    sample_paths,
            "horizon":         horizon,
            "n_sims":          n_sims,
            "prob_profit":     round(float((final > 0).mean() * 100), 1),
            "prob_loss_20pct": round(float((final < -0.2).mean() * 100), 1),
            "final_p5":        round(float(np.percentile(final, 5) * 100), 2),
            "final_median":    round(float(np.percentile(final, 50) * 100), 2),
            "final_p95":       round(float(np.percentile(final, 95) * 100), 2),
        })
    except ValueError as e:
        return _bad(str(e))
    except Exception as e:
        return _server_error(e)


# ── Stress Test ────────────────────────────────────────────────────────────────

@optimize_bp.route("/api/stress", methods=["POST"])
def stress_test():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")
    weights = data.get("weights")
    if not isinstance(weights, dict) or not weights:
        return _bad("weights must be a non-empty object.")
    try:
        tickers = [t for t, w in weights.items() if float(w) > 0]
        active_w = {t: float(weights[t]) for t in tickers}
        total = sum(active_w.values())
        active_w = {t: v / total for t, v in active_w.items()}

        results = {}
        for key, (name, sc_start, sc_end) in STRESS_SCENARIOS.items():
            try:
                prices = fetch_prices(tickers, sc_start, sc_end)
                asset_rets = {}
                port_ret = 0.0
                weight_used = 0.0
                for t in tickers:
                    if t in prices.columns:
                        col = prices[t].dropna()
                        if len(col) >= 2:
                            r = float(col.iloc[-1] / col.iloc[0] - 1)
                            asset_rets[t] = round(r * 100, 2)
                            port_ret += active_w[t] * r
                            weight_used += active_w[t]
                    else:
                        asset_rets[t] = None
                if weight_used > 0:
                    port_ret /= weight_used

                spy_ret = None
                try:
                    raw = yf.download(BENCHMARK, start=sc_start, end=sc_end,
                                      auto_adjust=True, progress=False)
                    if not raw.empty:
                        sc_col = raw["Close"].iloc[:, 0] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
                        spy_ret = round(float(sc_col.iloc[-1] / sc_col.iloc[0] - 1) * 100, 2)
                except Exception:
                    pass

                results[key] = {
                    "name":             name,
                    "period":           f"{sc_start} → {sc_end}",
                    "portfolio_return": round(port_ret * 100, 2),
                    "spy_return":       spy_ret,
                    "asset_returns":    asset_rets,
                }
            except Exception:
                results[key] = {"name": name, "period": f"{sc_start} → {sc_end}", "error": True}

        return jsonify({"scenarios": results})
    except Exception as e:
        return _server_error(e)
