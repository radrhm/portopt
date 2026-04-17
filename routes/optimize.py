"""Optimization, analytics, and simulation API routes."""

import logging
import traceback

import numpy as np
from flask import Blueprint, jsonify, request

import config
from services import optimization
from services.analytics import (
    apply_overrides,
    compute_descriptive_stats,
    compute_risk_metrics,
    generate_frontier,
)
from services.data import fetch_benchmark, fetch_prices
from validators import (
    validate_date_range,
    validate_float,
    validate_ticker,
    validate_tickers,
    validate_weights,
)

logger = logging.getLogger(__name__)
optimize_bp = Blueprint("optimize", __name__)


def _bad(msg: str):
    return jsonify({"error": msg}), 400


def _server_error(e: Exception):
    logger.error("Server error: %s", traceback.format_exc())
    return jsonify({"error": str(e)}), 500


# ── Ticker validation ────────────────────────────────────────────────────────

@optimize_bp.route("/api/validate_ticker", methods=["POST"])
def validate_ticker_route():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")
    try:
        sym = validate_ticker(data.get("ticker", ""))
    except ValueError as exc:
        return jsonify({"valid": False, "error": str(exc)}), 400

    import yfinance as yf
    try:
        info = yf.Ticker(sym).info
    except Exception as exc:
        logger.warning("yfinance lookup failed for %s: %s", sym, exc)
        return jsonify({"valid": False, "error": "Lookup failed."}), 502

    price = (info.get("currentPrice") or info.get("regularMarketPrice")
             or info.get("previousClose") or 0)
    if not price:
        return jsonify({"valid": False, "error": "No price data."})

    return jsonify({
        "valid":      True,
        "ticker":     sym,
        "name":       info.get("longName") or info.get("shortName") or sym,
        "price":      round(float(price), 2),
        "sector":     info.get("sector", "N/A"),
        "market_cap": info.get("marketCap", 0),
    })


# ── Stock data ───────────────────────────────────────────────────────────────

@optimize_bp.route("/api/stock_data", methods=["POST"])
def stock_data():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")

    try:
        tickers = validate_tickers(data.get("tickers", []))
        start_date, end_date = validate_date_range(data.get("start_date"), data.get("end_date"))
    except ValueError as exc:
        return _bad(str(exc))

    try:
        from pypfopt import expected_returns
        prices = fetch_prices(tickers, start_date, end_date)
        result = {}
        for sym in prices.columns:
            col = prices[sym].dropna()
            if len(col) < 5:
                continue
            rets = col.pct_change().dropna()
            ann_ret = float(expected_returns.mean_historical_return(prices[[sym]].dropna()).iloc[0])
            ann_vol = float(np.sqrt(config.TRADING_DAYS) * rets.std())
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
    except ValueError as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _server_error(exc)


# ── Optimization ─────────────────────────────────────────────────────────────

@optimize_bp.route("/api/optimize", methods=["POST"])
def optimize():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")

    try:
        tickers = validate_tickers(data.get("tickers", []), min_count=2)
        start_date, end_date = validate_date_range(data.get("start_date"), data.get("end_date"))
        method = data.get("method")
        if method not in config.VALID_METHODS:
            raise ValueError(
                f"Invalid method. Choose from: {', '.join(sorted(config.VALID_METHODS))}"
            )
        rfr = validate_float(data.get("risk_free_rate"), "risk_free_rate",
                             lo=-0.05, hi=0.5, default=0.04)
        min_w = validate_float(data.get("min_weight"), "min_weight",
                               lo=0.0, hi=1.0, default=0.0)
        max_w = validate_float(data.get("max_weight"), "max_weight",
                               lo=0.0, hi=1.0, default=1.0)
        if min_w >= max_w:
            raise ValueError("min_weight must be less than max_weight.")
    except ValueError as exc:
        return _bad(str(exc))

    weight_bounds = (min_w, max_w)
    try:
        ret_ov = {k: float(v) / 100 for k, v in (data.get("return_overrides") or {}).items()}
        vol_ov = {k: float(v) / 100 for k, v in (data.get("vol_overrides") or {}).items()}
    except (TypeError, ValueError):
        return _bad("Invalid override values — must be numeric.")

    try:
        from pypfopt import expected_returns, risk_models
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
        frontier_bl = bl_info = hrp_info = None

        if method == "black_litterman":
            cleaned, frontier_bl, bl_info = optimization.run_black_litterman(
                available, mu, S, weight_bounds, rfr,
                views_data=data.get("views", {}),
                market_caps=data.get("market_caps", {}),
                tau=float(data.get("tau", 0.05)),
                risk_aversion=float(data.get("risk_aversion", 2.5)),
            )
        elif method == "max_sharpe":
            cleaned = optimization.run_max_sharpe(mu, S, weight_bounds, rfr)
        elif method == "min_volatility":
            cleaned = optimization.run_min_volatility(mu, S, weight_bounds)
        elif method == "risk_parity":
            cleaned = optimization.run_risk_parity(available, S, weight_bounds)
        elif method == "hrp":
            cleaned, hrp_info = optimization.run_hrp(available, S)
        elif method == "equal_weight":
            cleaned = optimization.run_equal_weight(available)
        elif method == "max_return":
            cleaned = optimization.run_max_return(mu, S, weight_bounds)
        else:
            return _bad(f"Unsupported method: {method}")

        analytics = compute_risk_metrics(cleaned, prices, rfr, bench_prices)
        descriptive_stats = compute_descriptive_stats(prices)
        resp = {
            "weights":           dict(cleaned),
            "analytics":         analytics,
            "frontier":          frontier,
            "descriptive_stats": descriptive_stats,
        }
        if frontier_bl:
            resp["frontier_bl"] = frontier_bl
        if bl_info:
            resp["bl_info"] = bl_info
        if hrp_info:
            resp["hrp_info"] = hrp_info
        return jsonify(resp)

    except ValueError as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _server_error(exc)


# ── Analyze (custom / toggled weights) ───────────────────────────────────────

@optimize_bp.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")

    try:
        weights = validate_weights(data.get("weights"), allow_zero=True)
        start_date, end_date = validate_date_range(data.get("start_date"), data.get("end_date"))
        rfr = validate_float(data.get("risk_free_rate"), "risk_free_rate",
                             lo=-0.05, hi=0.5, default=0.04)
    except ValueError as exc:
        return _bad(str(exc))

    try:
        active = {t: w for t, w in weights.items() if w > 0}
        if not active:
            return _bad("Need at least 1 active stock.")
        total = sum(active.values())
        active = {t: w / total for t, w in active.items()}

        prices = fetch_prices(list(active), start_date, end_date)
        bench = fetch_benchmark(start_date, end_date)
        analytics = compute_risk_metrics(active, prices, rfr, bench)
        descriptive_stats = compute_descriptive_stats(prices)
        return jsonify({"weights": active, "analytics": analytics,
                        "descriptive_stats": descriptive_stats})
    except ValueError as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _server_error(exc)


# ── Rebalancing ──────────────────────────────────────────────────────────────

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
        if tw_sum <= 0:
            return _bad("Target weights sum to zero.")
        target_w = {k: float(v) / tw_sum for k, v in target_weights.items()}
        trades = {}
        for sym in set(list(current_values) + list(target_w)):
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
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _server_error(exc)


# ── Monte Carlo ──────────────────────────────────────────────────────────────

@optimize_bp.route("/api/montecarlo", methods=["POST"])
def montecarlo():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")

    try:
        weights = validate_weights(data.get("weights"), allow_zero=True)
        start_date, end_date = validate_date_range(data.get("start_date"), data.get("end_date"))
        n_sims = int(validate_float(data.get("n_sims"), "n_sims", lo=50, hi=2000, default=500))
        horizon = int(validate_float(data.get("horizon"), "horizon", lo=5, hi=1260, default=252))
    except ValueError as exc:
        return _bad(str(exc))

    try:
        tickers = [t for t, w in weights.items() if w > 0]
        if not tickers:
            return _bad("No active weights.")
        prices = fetch_prices(tickers, start_date, end_date)
        active_w = {t: weights[t] for t in tickers if t in prices.columns}
        total = sum(active_w.values())
        if total <= 0:
            return _bad("Weights sum to zero.")
        active_w = {t: v / total for t, v in active_w.items()}
        tickers = list(active_w)
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
    except ValueError as exc:
        return _bad(str(exc))
    except Exception as exc:
        return _server_error(exc)


# ── Stress Test ──────────────────────────────────────────────────────────────

@optimize_bp.route("/api/stress", methods=["POST"])
def stress_test():
    data = request.get_json(silent=True)
    if not data:
        return _bad("Invalid or missing JSON body.")

    try:
        weights = validate_weights(data.get("weights"), allow_zero=True)
    except ValueError as exc:
        return _bad(str(exc))

    try:
        tickers = [t for t, w in weights.items() if w > 0]
        if not tickers:
            return _bad("No active weights.")
        active_w = {t: weights[t] for t in tickers}
        total = sum(active_w.values())
        active_w = {t: v / total for t, v in active_w.items()}

        results = {}
        for key, (name, sc_start, sc_end) in config.STRESS_SCENARIOS.items():
            try:
                prices = fetch_prices(tickers, sc_start, sc_end)
            except ValueError as exc:
                logger.info("Stress scenario %s skipped: %s", key, exc)
                results[key] = {"name": name, "period": f"{sc_start} → {sc_end}",
                                "error": True, "reason": str(exc)}
                continue

            asset_rets: dict[str, float | None] = {}
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
            bench = fetch_benchmark(sc_start, sc_end)
            if bench is not None and len(bench) >= 2:
                spy_ret = round(float(bench.iloc[-1] / bench.iloc[0] - 1) * 100, 2)

            results[key] = {
                "name":             name,
                "period":           f"{sc_start} → {sc_end}",
                "portfolio_return": round(port_ret * 100, 2),
                "spy_return":       spy_ret,
                "asset_returns":    asset_rets,
            }

        return jsonify({"scenarios": results})
    except Exception as exc:
        return _server_error(exc)
