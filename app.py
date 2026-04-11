from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np
from pypfopt import EfficientFrontier, risk_models, expected_returns, BlackLittermanModel
from scipy.optimize import minimize
from scipy.stats import norm
import traceback
import warnings
import db

warnings.filterwarnings("ignore")
app = Flask(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────
TRADING_DAYS = 252
BENCHMARK = "SPY"


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_prices(tickers, start_date, end_date):
    raw = yf.download(
        tickers if len(tickers) > 1 else tickers[0],
        start=start_date, end=end_date,
        auto_adjust=True, progress=False
    )
    if raw.empty:
        raise ValueError("No price data returned.")

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"]
    else:
        col = "Close" if "Close" in raw.columns else raw.columns[0]
        prices = raw[[col]].rename(columns={col: tickers[0]})

    if isinstance(prices, pd.Series):
        prices = prices.to_frame(name=tickers[0])

    available = [t for t in tickers if t in prices.columns]
    if not available:
        raise ValueError(f"None of {tickers} had data.")
    prices = prices[available].dropna(how="all").ffill().dropna(how="any")
    return prices


def fetch_benchmark(start_date, end_date):
    try:
        raw = yf.download(BENCHMARK, start=start_date, end=end_date,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            return raw["Close"].iloc[:, 0]
        return raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  RISK ANALYTICS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_risk_metrics(weights_dict, prices, rfr, bench_prices=None):
    """Compute comprehensive risk metrics for a portfolio."""
    tickers = list(weights_dict.keys())
    w = np.array([weights_dict[t] for t in tickers])
    rets = prices[tickers].pct_change().dropna()

    port_rets = rets @ w
    n_days = len(port_rets)

    # ── Basic ─────────────────────────────────────────────────
    ann_ret = float((1 + port_rets).prod() ** (TRADING_DAYS / n_days) - 1)
    ann_vol = float(port_rets.std() * np.sqrt(TRADING_DAYS))
    sharpe = (ann_ret - rfr) / ann_vol if ann_vol > 0 else 0.0

    # ── Sortino ───────────────────────────────────────────────
    downside_diff = port_rets - (rfr / TRADING_DAYS)
    downside_sq = downside_diff[downside_diff < 0] ** 2
    downside_var = float(downside_sq.mean()) if len(downside_sq) > 0 else 0.0
    downside_vol = float(np.sqrt(downside_var) * np.sqrt(TRADING_DAYS)) if downside_var > 0 else 0.001
    sortino = (ann_ret - rfr) / downside_vol if downside_vol > 0 else 0.0

    # ── VaR & CVaR (Expected Shortfall) ───────────────────────
    var_95 = float(np.percentile(port_rets, 5))
    var_99 = float(np.percentile(port_rets, 1))
    cvar_95 = float(port_rets[port_rets <= var_95].mean()) if len(port_rets[port_rets <= var_95]) else var_95
    cvar_99 = float(port_rets[port_rets <= var_99].mean()) if len(port_rets[port_rets <= var_99]) else var_99

    # Parametric VaR (annualized)
    daily_mean = float(port_rets.mean())
    daily_std = float(port_rets.std())
    param_var_95 = float(-(daily_mean * TRADING_DAYS + norm.ppf(0.05) * daily_std * np.sqrt(TRADING_DAYS)))
    param_var_99 = float(-(daily_mean * TRADING_DAYS + norm.ppf(0.01) * daily_std * np.sqrt(TRADING_DAYS)))

    # ── Drawdown ──────────────────────────────────────────────
    cum = (1 + port_rets).cumprod()
    running_max = cum.cummax()
    drawdowns = (cum - running_max) / running_max
    max_drawdown = float(drawdowns.min())
    avg_drawdown = float(drawdowns[drawdowns < 0].mean()) if len(drawdowns[drawdowns < 0]) else 0.0

    # Calmar ratio
    calmar = ann_ret / abs(max_drawdown) if max_drawdown != 0 else 0.0

    # Drawdown duration
    in_dd = drawdowns < 0
    dd_groups = (in_dd != in_dd.shift()).cumsum()
    dd_durations = in_dd.groupby(dd_groups).sum()
    max_dd_duration = int(dd_durations.max()) if len(dd_durations) else 0
    avg_dd_duration = float(dd_durations[dd_durations > 0].mean()) if len(dd_durations[dd_durations > 0]) else 0.0

    # ── Beta & Alpha (vs SPY) ─────────────────────────────────
    beta = 0.0
    alpha = 0.0
    treynor = 0.0
    tracking_error = 0.0
    info_ratio = 0.0
    r_squared = 0.0
    bench_rets_aligned = None  # kept for rolling beta

    if bench_prices is not None and len(bench_prices) > 1:
        bench_rets = bench_prices.pct_change().dropna()
        bench_rets_aligned = bench_rets.reindex(port_rets.index)
        common = port_rets.index.intersection(bench_rets.index)
        if len(common) > 10:
            pr = port_rets.loc[common]
            br = bench_rets.loc[common]
            cov_pb = float(np.cov(pr, br)[0, 1])
            var_b = float(br.var())
            beta = cov_pb / var_b if var_b > 0 else 0.0
            bench_ann_ret = float(br.mean() * TRADING_DAYS)
            alpha = ann_ret - (rfr + beta * (bench_ann_ret - rfr))
            treynor = (ann_ret - rfr) / beta if beta != 0 else 0.0

            excess = pr - br
            tracking_error = float(excess.std() * np.sqrt(TRADING_DAYS))
            info_ratio = float(excess.mean() * TRADING_DAYS) / tracking_error if tracking_error > 0 else 0.0

            corr = float(np.corrcoef(pr, br)[0, 1])
            r_squared = corr ** 2

    # ── Higher moments ────────────────────────────────────────
    skewness = float(port_rets.skew())
    kurtosis = float(port_rets.kurtosis())
    gain_loss = float(port_rets[port_rets > 0].mean() / abs(port_rets[port_rets < 0].mean())) if len(port_rets[port_rets < 0]) > 0 else 0.0
    win_rate = float((port_rets > 0).sum() / len(port_rets)) if n_days > 0 else 0.0

    # ── Tail risk ─────────────────────────────────────────────
    worst_day = float(port_rets.min())
    best_day = float(port_rets.max())
    worst_month = 0.0
    best_month = 0.0
    if n_days > 21:
        monthly = port_rets.resample("ME").apply(lambda x: (1 + x).prod() - 1)
        if len(monthly) > 0:
            worst_month = float(monthly.min())
            best_month = float(monthly.max())

    # ── Rolling metrics ───────────────────────────────────────
    rolling_metrics = {}
    for win in [30, 60, 90, 180]:
        if n_days > win + 10:
            roll_ret = port_rets.rolling(win).mean() * TRADING_DAYS
            roll_vol = port_rets.rolling(win).std() * np.sqrt(TRADING_DAYS)
            roll_sharpe = (roll_ret - rfr) / roll_vol.clip(lower=1e-8)
            dates_str = [str(d.date()) for d in port_rets.index]
            rd = {
                "dates":      dates_str,
                "return":     [round(float(v) * 100, 3) if np.isfinite(v) else None for v in roll_ret],
                "volatility": [round(float(v) * 100, 3) if np.isfinite(v) else None for v in roll_vol],
                "sharpe":     [round(float(v), 4)       if np.isfinite(v) else None for v in roll_sharpe],
            }
            if bench_rets_aligned is not None:
                roll_cov  = port_rets.rolling(win).cov(bench_rets_aligned)
                roll_varb = bench_rets_aligned.rolling(win).var()
                roll_beta = roll_cov / roll_varb.clip(lower=1e-10)
                rd["beta"] = [round(float(v), 4) if np.isfinite(v) else None for v in roll_beta]
            rolling_metrics[str(win)] = rd

    # ── Per-stock contribution ────────────────────────────────
    cov_matrix = rets[tickers].cov().values * TRADING_DAYS
    port_var = float(w @ cov_matrix @ w)
    port_vol_total = np.sqrt(port_var) if port_var > 0 else 0.001

    # Marginal & component risk
    mcr = (cov_matrix @ w) / port_vol_total  # marginal contribution to risk
    cr = w * mcr  # component risk

    # Return contribution
    mu_vec = rets[tickers].mean().values * TRADING_DAYS
    ret_contrib = w * mu_vec
    total_ret_contrib = ret_contrib.sum()

    contributions = {}
    for i, t in enumerate(tickers):
        contributions[t] = {
            "weight": round(float(w[i]), 6),
            "ann_return": round(float(mu_vec[i]) * 100, 2),
            "ann_vol": round(float(rets[t].std() * np.sqrt(TRADING_DAYS)) * 100, 2),
            "return_contrib": round(float(ret_contrib[i]) * 100, 4),
            "return_contrib_pct": round(float(ret_contrib[i] / total_ret_contrib * 100) if total_ret_contrib != 0 else 0, 2),
            "risk_contrib": round(float(cr[i]) * 100, 4),
            "risk_contrib_pct": round(float(cr[i] / cr.sum() * 100) if cr.sum() != 0 else 0, 2),
            "marginal_risk": round(float(mcr[i]) * 100, 4),
            "beta_to_portfolio": round(float(mcr[i] / port_vol_total) if port_vol_total > 0 else 0, 4),
        }

    # ── Cumulative returns data ───────────────────────────────
    cum_data = {}
    for col in prices[tickers].columns:
        c = prices[col].dropna()
        cr_series = c / c.iloc[0]
        cum_data[col] = {
            "dates": [str(d.date()) for d in cr_series.index],
            "values": [round(float(v), 6) for v in cr_series.tolist()],
        }
    # Portfolio cumulative
    port_cum = (1 + port_rets).cumprod()
    cum_data["__PORTFOLIO__"] = {
        "dates": [str(d.date()) for d in port_cum.index],
        "values": [round(float(v), 6) for v in port_cum.tolist()],
    }

    # SPY benchmark cumulative (aligned to portfolio dates)
    if bench_rets_aligned is not None:
        try:
            spy_cum = (1 + bench_rets_aligned.fillna(0)).cumprod()
            cum_data["__SPY__"] = {
                "dates": [str(d.date()) for d in spy_cum.index],
                "values": [round(float(v), 6) for v in spy_cum.tolist()],
            }
        except Exception:
            pass

    # Drawdown series
    dd_series = {
        "dates": [str(d.date()) for d in drawdowns.index],
        "values": [round(float(v) * 100, 4) for v in drawdowns.tolist()],
    }

    # Correlation
    corr_matrix = rets[tickers].corr().round(4).to_dict()

    return {
        "metrics": {
            "expected_return":   round(ann_ret * 100, 4),
            "volatility":       round(ann_vol * 100, 4),
            "sharpe_ratio":     round(sharpe, 4),
            "sortino_ratio":    round(sortino, 4),
            "calmar_ratio":     round(calmar, 4),
            "var_95_daily":     round(var_95 * 100, 4),
            "var_99_daily":     round(var_99 * 100, 4),
            "cvar_95_daily":    round(cvar_95 * 100, 4),
            "cvar_99_daily":    round(cvar_99 * 100, 4),
            "param_var_95_ann": round(param_var_95 * 100, 4),
            "param_var_99_ann": round(param_var_99 * 100, 4),
            "max_drawdown":     round(max_drawdown * 100, 4),
            "avg_drawdown":     round(avg_drawdown * 100, 4),
            "max_dd_duration":  max_dd_duration,
            "avg_dd_duration":  round(avg_dd_duration, 1),
            "beta":             round(beta, 4),
            "alpha":            round(alpha * 100, 4),
            "treynor_ratio":    round(treynor, 4),
            "tracking_error":   round(tracking_error * 100, 4),
            "info_ratio":       round(info_ratio, 4),
            "r_squared":        round(r_squared, 4),
            "skewness":         round(skewness, 4),
            "kurtosis":         round(kurtosis, 4),
            "gain_loss_ratio":  round(gain_loss, 4),
            "win_rate":         round(win_rate * 100, 2),
            "worst_day":        round(worst_day * 100, 4),
            "best_day":         round(best_day * 100, 4),
            "worst_month":      round(worst_month * 100, 4),
            "best_month":       round(best_month * 100, 4),
            "n_days":           n_days,
        },
        "contributions": contributions,
        "cumulative_returns": cum_data,
        "drawdown_series": dd_series,
        "correlation": corr_matrix,
        "rolling_metrics": rolling_metrics,
    }


def apply_overrides(mu, S, return_overrides, vol_overrides):
    mu = mu.copy()
    S = S.copy()
    for sym, val in (return_overrides or {}).items():
        if sym in mu.index:
            mu[sym] = float(val)
    for sym, new_vol in (vol_overrides or {}).items():
        if sym in S.index:
            old_vol = float(np.sqrt(S.loc[sym, sym]))
            if old_vol > 0:
                scale = float(new_vol) / old_vol
                S.loc[sym, :] *= scale
                S.loc[:, sym] *= scale
    return mu, S


def generate_frontier(mu, S, weight_bounds, rfr, n_points=50):
    try:
        from pypfopt.cla import CLA
        cla = CLA(mu, S, weight_bounds=weight_bounds)
        mu_arr, vol_arr, _ = cla.efficient_frontier(points=n_points)
        return {
            "volatilities": [round(float(v), 6) for v in vol_arr],
            "returns": [round(float(r), 6) for r in mu_arr]
        }
    except Exception as e:
        vols, rets = [], []
        lo = float(mu.min()) * (1.01 if mu.min() > 0 else 0.99)
        hi = float(mu.max()) * (0.99 if mu.max() > 0 else 1.01)
        if lo >= hi:
            lo, hi = float(mu.min()) * 0.8, float(mu.max()) * 1.2
        for target in np.linspace(lo, hi, n_points):
            try:
                ef_t = EfficientFrontier(mu, S, weight_bounds=weight_bounds,
                                         solver_options={"max_iters": 1000})
                ef_t.efficient_return(target_return=float(target))
                p = ef_t.portfolio_performance(risk_free_rate=rfr)
                vols.append(round(p[1], 6))
                rets.append(round(p[0], 6))
            except Exception:
                continue
        return {"volatilities": vols, "returns": rets}


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ── Ticker validation ─────────────────────────────────────────────────────────

@app.route("/api/validate_ticker", methods=["POST"])
def validate_ticker():
    sym = request.json.get("ticker", "").upper().strip()
    if not sym:
        return jsonify({"valid": False, "error": "Empty"})
    try:
        t = yf.Ticker(sym)
        info = t.info
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0
        name = info.get("longName") or info.get("shortName") or sym
        return jsonify({
            "valid": True, "ticker": sym, "name": name,
            "price": round(float(price), 2) if price else 0,
            "sector": info.get("sector", "N/A"),
            "market_cap": info.get("marketCap", 0),
        })
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)})


# ── Stock data fetch ──────────────────────────────────────────────────────────

@app.route("/api/stock_data", methods=["POST"])
def stock_data():
    tickers = request.json.get("tickers", [])
    start_date = request.json.get("start_date")
    end_date = request.json.get("end_date")
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
                "ann_return": round(ann_ret * 100, 2),
                "ann_vol": round(ann_vol * 100, 2),
                "total_return": round(total * 100, 2),
                "sharpe": round(sharpe, 3),
                "n_days": int(len(rets)),
                "sparkline": [round(float(v) / base, 4) for v in spark.tolist()],
            }
        return jsonify({"data": result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)})


# ── Optimization ──────────────────────────────────────────────────────────────

@app.route("/api/optimize", methods=["POST"])
def optimize():
    try:
        data = request.json
        tickers = data["tickers"]
        start_date = data["start_date"]
        end_date = data["end_date"]
        method = data["method"]
        rfr = float(data.get("risk_free_rate", 0.04))
        min_w = float(data.get("min_weight", 0.0))
        max_w = float(data.get("max_weight", 1.0))
        weight_bounds = (min_w, max_w)
        ret_ov = {k: float(v) / 100 for k, v in (data.get("return_overrides") or {}).items()}
        vol_ov = {k: float(v) / 100 for k, v in (data.get("vol_overrides") or {}).items()}

        if len(tickers) < 2:
            return jsonify({"error": "Need at least 2 tickers."})

        prices = fetch_prices(tickers, start_date, end_date)
        if len(prices) < 30:
            return jsonify({"error": f"Only {len(prices)} trading days. Extend the date range."})

        available = list(prices.columns)
        if len(available) < 2:
            return jsonify({"error": f"Only {available} had data."})

        bench_prices = fetch_benchmark(start_date, end_date)

        mu = expected_returns.mean_historical_return(prices)
        S = risk_models.sample_cov(prices)
        mu, S = apply_overrides(mu, S, ret_ov, vol_ov)

        frontier = generate_frontier(mu, S, weight_bounds, rfr)
        frontier_bl = None
        bl_info = None
        hrp_info = None

        # ── Dispatch ──────────────────────────────────────────
        if method == "black_litterman":
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

            if abs_views:
                bl = BlackLittermanModel(S, pi="market", market_caps=mcap_w,
                                         absolute_views=abs_views, omega="idzorek",
                                         view_confidences=confidences,
                                         risk_aversion=risk_aversion, tau=tau)
            else:
                bl = BlackLittermanModel(S, pi="market", market_caps=mcap_w,
                                         risk_aversion=risk_aversion, tau=tau)

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
                "prior_returns": {k: round(v, 6) for k, v in prior_r.items()},
                "posterior_returns": {k: round(float(v), 6) for k, v in post_r.items()},
                "views": abs_views,
                "market_weights": {k: round(float(v), 6) for k, v in mcap_w.items()},
                "confidences": {sym: round(conf, 4) for sym, conf in zip([s for s, vd in views_data.items() if s in available and vd.get("enabled") and vd.get("return") is not None], confidences)},
            }

            sensitivity = {}
            if abs_views:
                conf_low = [c * 0.5 for c in confidences]
                conf_high = [min(0.99, c * 1.5) for c in confidences]
                try:
                    bl_low = BlackLittermanModel(S, pi="market", market_caps=mcap_w, absolute_views=abs_views, omega="idzorek", view_confidences=conf_low, risk_aversion=risk_aversion, tau=tau)
                    ef_low = EfficientFrontier(bl_low.bl_returns(), bl_low.bl_cov(), weight_bounds=weight_bounds)
                    ef_low.max_sharpe(risk_free_rate=rfr)
                    sl = ef_low.clean_weights()

                    bl_high = BlackLittermanModel(S, pi="market", market_caps=mcap_w, absolute_views=abs_views, omega="idzorek", view_confidences=conf_high, risk_aversion=risk_aversion, tau=tau)
                    ef_high = EfficientFrontier(bl_high.bl_returns(), bl_high.bl_cov(), weight_bounds=weight_bounds)
                    ef_high.max_sharpe(risk_free_rate=rfr)
                    sh = ef_high.clean_weights()

                    for sym in cleaned.keys():
                        sensitivity[sym] = {"base": round(cleaned.get(sym,0), 4), "low": round(sl.get(sym,0), 4), "high": round(sh.get(sym,0), 4)}
                except Exception:
                    pass
            bl_info["sensitivity"] = sensitivity
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
            n = len(available)
            cov_arr = S.values
            def rp_obj(w):
                pv = w @ cov_arr @ w
                if pv <= 0: return 1e9
                rc = w * (cov_arr @ w) / pv
                return float(np.sum((rc - np.ones(n) / n) ** 2))
            res = minimize(rp_obj, np.ones(n) / n, method="SLSQP",
                           bounds=[weight_bounds] * n,
                           constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1}],
                           options={"ftol": 1e-12, "maxiter": 2000})
            raw_w = {available[i]: max(0.0, res.x[i]) for i in range(n)}
            tot = sum(raw_w.values())
            cleaned = {k: v / tot for k, v in raw_w.items()}
        elif method == "hrp":
            from pypfopt.hierarchical_portfolio import HRPOpt
            import scipy.cluster.hierarchy as sch
            import scipy.spatial.distance as ssd

            hrp = HRPOpt(cov_matrix=S)
            cleaned = dict(hrp.optimize())

            corr_mat = S.copy()
            vols = np.sqrt(np.diag(S))
            for i in range(len(S.columns)):
                for j in range(len(S.columns)):
                    if vols[i]*vols[j] > 0:
                        corr_mat.iloc[i, j] = S.iloc[i, j] / (vols[i]*vols[j])
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
                "tickers": available,
                "sorted_tickers": sorted_tickers,
                "distance_matrix": dist_mat.values.tolist(),
                "qd_correlation": qd_corr.values.tolist(),
                "risk_contributions": dict(zip(sorted_tickers, (risk_contrib * 100).tolist())),
                "linkage": link.tolist() if len(dist_array) > 0 else []
            }
        elif method == "equal_weight":
            n = len(available)
            cleaned = {t: 1.0 / n for t in available}
        elif method == "max_return":
            ef = EfficientFrontier(mu, S, weight_bounds=weight_bounds)
            ef.efficient_return(target_return=float(mu.max()) * 0.98)
            cleaned = ef.clean_weights()
        else:
            return jsonify({"error": f"Unknown method: {method}"})

        # Risk analytics
        analytics = compute_risk_metrics(cleaned, prices, rfr, bench_prices)

        resp = {
            "weights": dict(cleaned),
            "analytics": analytics,
            "frontier": frontier,
        }
        if frontier_bl:
            resp["frontier_bl"] = frontier_bl
        if bl_info:
            resp["bl_info"] = bl_info
        if hrp_info:
            resp["hrp_info"] = hrp_info

        return jsonify(resp)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)})


# ── Analyze (for custom portfolios or toggling) ──────────────────────────────

@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Compute risk metrics for arbitrary weights (custom portfolio, toggle)."""
    try:
        data = request.json
        weights = data["weights"]  # {sym: weight}
        tickers = [t for t, w in weights.items() if w > 0]
        if len(tickers) < 1:
            return jsonify({"error": "Need at least 1 active stock."})
        active_w = {t: weights[t] for t in tickers}
        # Renormalize
        total = sum(active_w.values())
        if total <= 0:
            return jsonify({"error": "Weights sum to zero."})
        active_w = {t: w / total for t, w in active_w.items()}

        start_date = data["start_date"]
        end_date = data["end_date"]
        rfr = float(data.get("risk_free_rate", 0.04))

        prices = fetch_prices(tickers, start_date, end_date)
        bench = fetch_benchmark(start_date, end_date)

        analytics = compute_risk_metrics(active_w, prices, rfr, bench)
        return jsonify({"weights": active_w, "analytics": analytics})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)})


# ── Rebalancing ───────────────────────────────────────────────────────────────

@app.route("/api/rebalance", methods=["POST"])
def rebalance():
    """Given current $ values and target weights, compute trades."""
    try:
        data = request.json
        current_values = data["current_values"]  # {sym: $ value}
        target_weights = data["target_weights"]   # {sym: weight 0–1}
        total_value = sum(float(v) for v in current_values.values())
        if total_value <= 0:
            return jsonify({"error": "Total portfolio value is zero."})

        # Normalize target weights
        tw_sum = sum(float(w) for w in target_weights.values())
        target_w = {k: float(v) / tw_sum for k, v in target_weights.items()}

        trades = {}
        for sym in set(list(current_values.keys()) + list(target_w.keys())):
            cur = float(current_values.get(sym, 0))
            tgt = target_w.get(sym, 0) * total_value
            diff = tgt - cur
            trades[sym] = {
                "current_value": round(cur, 2),
                "current_weight": round(cur / total_value * 100, 2),
                "target_value": round(tgt, 2),
                "target_weight": round(target_w.get(sym, 0) * 100, 2),
                "trade_value": round(diff, 2),
                "action": "BUY" if diff > 0.5 else ("SELL" if diff < -0.5 else "HOLD"),
            }

        return jsonify({
            "total_value": round(total_value, 2),
            "trades": trades,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)})


# ── Monte Carlo Simulation ────────────────────────────────────────────────────

@app.route("/api/montecarlo", methods=["POST"])
def montecarlo():
    try:
        data = request.json
        weights = data["weights"]
        start_date = data["start_date"]
        end_date = data["end_date"]
        n_sims = min(int(data.get("n_sims", 500)), 2000)
        horizon = min(int(data.get("horizon", 252)), 1260)

        tickers = [t for t, w in weights.items() if float(w) > 0]
        if not tickers:
            return jsonify({"error": "No active weights."})

        prices = fetch_prices(tickers, start_date, end_date)
        active_w = {t: float(weights[t]) for t in tickers if t in prices.columns}
        total = sum(active_w.values())
        if total <= 0:
            return jsonify({"error": "Weights sum to zero."})
        active_w = {t: v / total for t, v in active_w.items()}
        tickers = list(active_w.keys())
        w_arr = np.array([active_w[t] for t in tickers])

        rets = prices[tickers].pct_change().dropna()
        mean_vec = rets.mean().values
        cov_mat  = rets.cov().values

        rng = np.random.default_rng(42)
        daily = rng.multivariate_normal(mean_vec, cov_mat, size=(n_sims, horizon))
        port_daily = daily @ w_arr                          # (n_sims, horizon)
        cum = np.cumprod(1 + port_daily, axis=1) - 1       # cumulative return

        pcts = np.percentile(cum, [5, 25, 50, 75, 95], axis=0)
        final = cum[:, -1]

        # 50 random sample paths for visualisation
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
            "final_p5":        round(float(np.percentile(final, 5)  * 100), 2),
            "final_median":    round(float(np.percentile(final, 50) * 100), 2),
            "final_p95":       round(float(np.percentile(final, 95) * 100), 2),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)})


# ── Stress Test ───────────────────────────────────────────────────────────────

STRESS_SCENARIOS = {
    "gfc_2008":    ("2008 Financial Crisis",      "2008-09-01", "2008-12-31"),
    "covid_2020":  ("COVID Crash",                "2020-02-19", "2020-03-23"),
    "rout_2022":   ("2022 Rate-Hike Selloff",     "2022-01-03", "2022-10-12"),
    "dot_com":     ("Dot-com Bust",               "2000-03-10", "2002-10-09"),
    "rate_1994":   ("1994 Bond Shock",            "1994-01-01", "1994-11-30"),
    "inflation_80":("1980 Inflation Shock",       "1980-01-01", "1982-08-12"),
}

@app.route("/api/stress", methods=["POST"])
def stress_test():
    try:
        data = request.json
        weights = data["weights"]
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
                            port_ret    += active_w[t] * r
                            weight_used += active_w[t]
                    else:
                        asset_rets[t] = None
                if weight_used > 0:
                    port_ret /= weight_used   # scale to available weight

                spy_ret = None
                try:
                    raw = yf.download(BENCHMARK, start=sc_start, end=sc_end,
                                      auto_adjust=True, progress=False)
                    if not raw.empty:
                        sc = raw["Close"].iloc[:, 0] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
                        spy_ret = round(float(sc.iloc[-1] / sc.iloc[0] - 1) * 100, 2)
                except Exception:
                    pass

                results[key] = {
                    "name": name,
                    "period": f"{sc_start} → {sc_end}",
                    "portfolio_return": round(port_ret * 100, 2),
                    "spy_return": spy_ret,
                    "asset_returns": asset_rets,
                }
            except Exception:
                results[key] = {"name": name, "period": f"{sc_start} → {sc_end}", "error": True}

        return jsonify({"scenarios": results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)})


# ── Portfolio CRUD ────────────────────────────────────────────────────────────

@app.route("/api/portfolios", methods=["GET"])
def list_portfolios():
    return jsonify({"portfolios": db.list_portfolios()})


@app.route("/api/portfolios/<int:pid>", methods=["GET"])
def get_portfolio(pid):
    p = db.get_portfolio(pid)
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p)


@app.route("/api/portfolios", methods=["POST"])
def create_portfolio():
    data = request.json
    pid = db.save_portfolio(data)
    return jsonify({"id": pid})


@app.route("/api/portfolios/<int:pid>", methods=["PUT"])
def update_portfolio(pid):
    data = request.json
    data["id"] = pid
    db.save_portfolio(data)
    return jsonify({"ok": True})


@app.route("/api/portfolios/<int:pid>", methods=["DELETE"])
def delete_portfolio(pid):
    db.delete_portfolio(pid)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
