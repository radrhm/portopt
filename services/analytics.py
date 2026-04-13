"""Portfolio analytics — risk metrics, overrides, efficient frontier."""

import warnings
import logging
import numpy as np
import pandas as pd
from scipy.stats import norm, jarque_bera
from pypfopt import EfficientFrontier

# Suppress solver noise only from these specific modules
warnings.filterwarnings("ignore", category=UserWarning, module="cvxpy")
warnings.filterwarnings("ignore", category=FutureWarning, module="pypfopt")

from .data import TRADING_DAYS

logger = logging.getLogger(__name__)


def compute_risk_metrics(
    weights_dict: dict,
    prices: pd.DataFrame,
    rfr: float,
    bench_prices: pd.Series | None = None,
) -> dict:
    """Compute comprehensive risk metrics for a portfolio."""
    tickers = list(weights_dict.keys())
    w = np.array([weights_dict[t] for t in tickers])
    rets = prices[tickers].pct_change().dropna()

    port_rets = rets @ w
    n_days = len(port_rets)

    # ── Basic ──────────────────────────────────────────────────────────────────
    ann_ret = float((1 + port_rets).prod() ** (TRADING_DAYS / n_days) - 1)
    ann_vol = float(port_rets.std() * np.sqrt(TRADING_DAYS))
    sharpe = (ann_ret - rfr) / ann_vol if ann_vol > 0 else 0.0

    # ── Sortino ────────────────────────────────────────────────────────────────
    downside_diff = port_rets - (rfr / TRADING_DAYS)
    downside_sq = downside_diff[downside_diff < 0] ** 2
    downside_var = float(downside_sq.mean()) if len(downside_sq) > 0 else 0.0
    downside_vol = float(np.sqrt(downside_var) * np.sqrt(TRADING_DAYS)) if downside_var > 0 else 0.001
    sortino = (ann_ret - rfr) / downside_vol if downside_vol > 0 else 0.0

    # ── VaR & CVaR ─────────────────────────────────────────────────────────────
    var_95 = float(np.percentile(port_rets, 5))
    var_99 = float(np.percentile(port_rets, 1))
    cvar_95 = float(port_rets[port_rets <= var_95].mean()) if len(port_rets[port_rets <= var_95]) else var_95
    cvar_99 = float(port_rets[port_rets <= var_99].mean()) if len(port_rets[port_rets <= var_99]) else var_99

    daily_mean = float(port_rets.mean())
    daily_std = float(port_rets.std())
    param_var_95 = float(-(daily_mean * TRADING_DAYS + norm.ppf(0.05) * daily_std * np.sqrt(TRADING_DAYS)))
    param_var_99 = float(-(daily_mean * TRADING_DAYS + norm.ppf(0.01) * daily_std * np.sqrt(TRADING_DAYS)))

    # ── Drawdown ───────────────────────────────────────────────────────────────
    cum = (1 + port_rets).cumprod()
    running_max = cum.cummax()
    drawdowns = (cum - running_max) / running_max
    max_drawdown = float(drawdowns.min())
    avg_drawdown = float(drawdowns[drawdowns < 0].mean()) if len(drawdowns[drawdowns < 0]) else 0.0
    calmar = ann_ret / abs(max_drawdown) if max_drawdown != 0 else 0.0

    in_dd = drawdowns < 0
    dd_groups = (in_dd != in_dd.shift()).cumsum()
    dd_durations = in_dd.groupby(dd_groups).sum()
    max_dd_duration = int(dd_durations.max()) if len(dd_durations) else 0
    avg_dd_duration = float(dd_durations[dd_durations > 0].mean()) if len(dd_durations[dd_durations > 0]) else 0.0

    # ── Beta & Alpha ───────────────────────────────────────────────────────────
    beta = 0.0
    alpha = 0.0
    treynor = 0.0
    tracking_error = 0.0
    info_ratio = 0.0
    r_squared = 0.0
    bench_rets_aligned = None

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

    # ── Higher moments ─────────────────────────────────────────────────────────
    skewness = float(port_rets.skew())
    kurtosis = float(port_rets.kurtosis())
    gain_loss = (
        float(port_rets[port_rets > 0].mean() / abs(port_rets[port_rets < 0].mean()))
        if len(port_rets[port_rets < 0]) > 0 else 0.0
    )
    win_rate = float((port_rets > 0).sum() / len(port_rets)) if n_days > 0 else 0.0

    # ── Tail risk ──────────────────────────────────────────────────────────────
    worst_day = float(port_rets.min())
    best_day = float(port_rets.max())
    worst_month = 0.0
    best_month = 0.0
    if n_days > 21:
        monthly = port_rets.resample("ME").apply(lambda x: (1 + x).prod() - 1)
        if len(monthly) > 0:
            worst_month = float(monthly.min())
            best_month = float(monthly.max())

    # ── Rolling metrics ────────────────────────────────────────────────────────
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
                roll_cov = port_rets.rolling(win).cov(bench_rets_aligned)
                roll_varb = bench_rets_aligned.rolling(win).var()
                roll_beta = roll_cov / roll_varb.clip(lower=1e-10)
                rd["beta"] = [round(float(v), 4) if np.isfinite(v) else None for v in roll_beta]
            rolling_metrics[str(win)] = rd

    # ── Per-stock contribution ─────────────────────────────────────────────────
    cov_matrix = rets[tickers].cov().values * TRADING_DAYS
    port_var = float(w @ cov_matrix @ w)
    port_vol_total = np.sqrt(port_var) if port_var > 0 else 0.001
    mcr = (cov_matrix @ w) / port_vol_total
    cr = w * mcr
    mu_vec = rets[tickers].mean().values * TRADING_DAYS
    ret_contrib = w * mu_vec
    total_ret_contrib = ret_contrib.sum()

    contributions = {}
    for i, t in enumerate(tickers):
        contributions[t] = {
            "weight":             round(float(w[i]), 6),
            "ann_return":         round(float(mu_vec[i]) * 100, 2),
            "ann_vol":            round(float(rets[t].std() * np.sqrt(TRADING_DAYS)) * 100, 2),
            "return_contrib":     round(float(ret_contrib[i]) * 100, 4),
            "return_contrib_pct": round(float(ret_contrib[i] / total_ret_contrib * 100) if total_ret_contrib != 0 else 0, 2),
            "risk_contrib":       round(float(cr[i]) * 100, 4),
            "risk_contrib_pct":   round(float(cr[i] / cr.sum() * 100) if cr.sum() != 0 else 0, 2),
            "marginal_risk":      round(float(mcr[i]) * 100, 4),
            "beta_to_portfolio":  round(float(mcr[i] / port_vol_total) if port_vol_total > 0 else 0, 4),
        }

    # ── Cumulative returns ─────────────────────────────────────────────────────
    cum_data = {}
    for col in prices[tickers].columns:
        c = prices[col].dropna()
        cr_series = c / c.iloc[0]
        cum_data[col] = {
            "dates":  [str(d.date()) for d in cr_series.index],
            "values": [round(float(v), 6) for v in cr_series.tolist()],
        }
    port_cum = (1 + port_rets).cumprod()
    cum_data["__PORTFOLIO__"] = {
        "dates":  [str(d.date()) for d in port_cum.index],
        "values": [round(float(v), 6) for v in port_cum.tolist()],
    }
    if bench_rets_aligned is not None:
        try:
            spy_cum = (1 + bench_rets_aligned.fillna(0)).cumprod()
            cum_data["__SPY__"] = {
                "dates":  [str(d.date()) for d in spy_cum.index],
                "values": [round(float(v), 6) for v in spy_cum.tolist()],
            }
        except Exception:
            pass

    dd_series = {
        "dates":  [str(d.date()) for d in drawdowns.index],
        "values": [round(float(v) * 100, 4) for v in drawdowns.tolist()],
    }
    corr_matrix = rets[tickers].corr().round(4).to_dict()

    return {
        "metrics": {
            "expected_return":   round(ann_ret * 100, 4),
            "volatility":        round(ann_vol * 100, 4),
            "sharpe_ratio":      round(sharpe, 4),
            "sortino_ratio":     round(sortino, 4),
            "calmar_ratio":      round(calmar, 4),
            "var_95_daily":      round(var_95 * 100, 4),
            "var_99_daily":      round(var_99 * 100, 4),
            "cvar_95_daily":     round(cvar_95 * 100, 4),
            "cvar_99_daily":     round(cvar_99 * 100, 4),
            "param_var_95_ann":  round(param_var_95 * 100, 4),
            "param_var_99_ann":  round(param_var_99 * 100, 4),
            "max_drawdown":      round(max_drawdown * 100, 4),
            "avg_drawdown":      round(avg_drawdown * 100, 4),
            "max_dd_duration":   max_dd_duration,
            "avg_dd_duration":   round(avg_dd_duration, 1),
            "beta":              round(beta, 4),
            "alpha":             round(alpha * 100, 4),
            "treynor_ratio":     round(treynor, 4),
            "tracking_error":    round(tracking_error * 100, 4),
            "info_ratio":        round(info_ratio, 4),
            "r_squared":         round(r_squared, 4),
            "skewness":          round(skewness, 4),
            "kurtosis":          round(kurtosis, 4),
            "gain_loss_ratio":   round(gain_loss, 4),
            "win_rate":          round(win_rate * 100, 2),
            "worst_day":         round(worst_day * 100, 4),
            "best_day":          round(best_day * 100, 4),
            "worst_month":       round(worst_month * 100, 4),
            "best_month":        round(best_month * 100, 4),
            "n_days":            n_days,
        },
        "contributions":     contributions,
        "cumulative_returns": cum_data,
        "drawdown_series":    dd_series,
        "correlation":        corr_matrix,
        "rolling_metrics":    rolling_metrics,
    }


def apply_overrides(
    mu: pd.Series,
    S: pd.DataFrame,
    return_overrides: dict | None,
    vol_overrides: dict | None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Apply analyst return / volatility overrides to mu and the covariance matrix."""
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


def compute_descriptive_stats(prices: pd.DataFrame) -> dict:
    """Per-stock descriptive statistics: distribution, moments, risk, normality."""
    result = {}
    for col in prices.columns:
        series = prices[col].dropna()
        if len(series) < 20:
            continue
        rets = series.pct_change().dropna() * 100  # daily returns in %
        n = len(rets)

        # Histogram (40 bins, balanced around 0)
        counts, edges = np.histogram(rets, bins=40)

        # Normality: Jarque-Bera test
        jb_stat, jb_pval = jarque_bera(rets)

        # Autocorrelation lag-1
        autocorr1 = float(rets.autocorr(lag=1)) if n > 5 else 0.0

        # Historical VaR / CVaR (daily, %)
        var_95 = float(np.percentile(rets, 5))
        tail = rets[rets <= var_95]
        cvar_95 = float(tail.mean()) if len(tail) > 0 else var_95

        # Per-stock drawdown
        cum = (1 + rets / 100).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_dd = float(dd.min()) * 100

        # Annualised
        ann_ret = float((1 + rets / 100).prod() ** (TRADING_DAYS / n) - 1) * 100
        ann_vol = float(rets.std() * np.sqrt(TRADING_DAYS))
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

        result[col] = {
            "n_obs":         n,
            "mean_daily":    round(float(rets.mean()), 4),
            "median_daily":  round(float(rets.median()), 4),
            "std_daily":     round(float(rets.std()), 4),
            "skewness":      round(float(rets.skew()), 4),
            "kurtosis":      round(float(rets.kurtosis()), 4),  # excess kurtosis
            "min_daily":     round(float(rets.min()), 4),
            "max_daily":     round(float(rets.max()), 4),
            "p5":            round(float(rets.quantile(0.05)), 4),
            "p25":           round(float(rets.quantile(0.25)), 4),
            "p75":           round(float(rets.quantile(0.75)), 4),
            "p95":           round(float(rets.quantile(0.95)), 4),
            "ann_return":    round(ann_ret, 4),
            "ann_vol":       round(ann_vol, 4),
            "sharpe":        round(sharpe, 4),
            "max_drawdown":  round(max_dd, 4),
            "win_rate":      round(float((rets > 0).sum() / n * 100), 2),
            "autocorr_1":    round(autocorr1, 4),
            "jb_pvalue":     round(float(jb_pval), 6),
            "jb_normal":     bool(jb_pval > 0.05),
            "var_95_daily":  round(var_95, 4),
            "cvar_95_daily": round(cvar_95, 4),
            "hist_counts":   counts.tolist(),
            "hist_edges":    [round(float(e), 4) for e in edges.tolist()],
        }
    return result


def generate_frontier(
    mu: pd.Series,
    S: pd.DataFrame,
    weight_bounds: tuple,
    rfr: float,
    n_points: int = 50,
) -> dict:
    """Compute the efficient frontier curve; falls back to grid scan on CLA failure."""
    try:
        from pypfopt.cla import CLA
        cla = CLA(mu, S, weight_bounds=weight_bounds)
        mu_arr, vol_arr, _ = cla.efficient_frontier(points=n_points)
        return {
            "volatilities": [round(float(v), 6) for v in vol_arr],
            "returns":      [round(float(r), 6) for r in mu_arr],
        }
    except Exception:
        vols, ret_vals = [], []
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
                ret_vals.append(round(p[0], 6))
            except Exception:
                continue
        return {"volatilities": vols, "returns": ret_vals}
