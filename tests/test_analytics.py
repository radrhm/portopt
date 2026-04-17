import numpy as np
import pandas as pd
import pytest

from services.analytics import (
    apply_overrides,
    compute_descriptive_stats,
    compute_risk_metrics,
    generate_frontier,
)


@pytest.fixture
def prices():
    """Synthetic 2-ticker daily price series, 500 trading days."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2022-01-03", periods=500, freq="B")
    a_rets = rng.normal(0.0005, 0.012, 500)
    b_rets = rng.normal(0.0003, 0.015, 500)
    a_px = 100 * np.cumprod(1 + a_rets)
    b_px = 50 * np.cumprod(1 + b_rets)
    return pd.DataFrame({"AAA": a_px, "BBB": b_px}, index=dates)


class TestRiskMetrics:
    def test_shape(self, prices):
        weights = {"AAA": 0.6, "BBB": 0.4}
        result = compute_risk_metrics(weights, prices, rfr=0.04)
        assert "metrics" in result
        assert "contributions" in result
        assert "cumulative_returns" in result
        assert "drawdown_series" in result
        assert "correlation" in result

    def test_basic_metrics(self, prices):
        weights = {"AAA": 0.5, "BBB": 0.5}
        result = compute_risk_metrics(weights, prices, rfr=0.04)
        m = result["metrics"]
        # All these must be present
        for k in ("expected_return", "volatility", "sharpe_ratio",
                  "sortino_ratio", "max_drawdown", "win_rate"):
            assert k in m
            assert isinstance(m[k], (int, float))

    def test_contributions_sum_to_1(self, prices):
        weights = {"AAA": 0.6, "BBB": 0.4}
        result = compute_risk_metrics(weights, prices, rfr=0.04)
        total_w = sum(c["weight"] for c in result["contributions"].values())
        assert abs(total_w - 1.0) < 1e-6

    def test_single_asset(self, prices):
        weights = {"AAA": 1.0}
        result = compute_risk_metrics(weights, prices[["AAA"]], rfr=0.04)
        assert result["metrics"]["n_days"] > 0


class TestApplyOverrides:
    def test_return_override(self):
        mu = pd.Series({"AAA": 0.1, "BBB": 0.08})
        S = pd.DataFrame(np.eye(2) * 0.04, index=["AAA", "BBB"], columns=["AAA", "BBB"])
        new_mu, _ = apply_overrides(mu, S, {"AAA": 0.15}, None)
        assert new_mu["AAA"] == 0.15
        assert new_mu["BBB"] == 0.08

    def test_vol_override_scales_covariance(self):
        mu = pd.Series({"AAA": 0.1, "BBB": 0.08})
        S = pd.DataFrame([[0.04, 0.01], [0.01, 0.04]],
                         index=["AAA", "BBB"], columns=["AAA", "BBB"])
        # AAA vol was 0.2; override to 0.4 — covariance should scale by 2x
        _, new_S = apply_overrides(mu, S, None, {"AAA": 0.4})
        assert new_S.loc["AAA", "BBB"] == pytest.approx(0.02)

    def test_immutable(self):
        """apply_overrides must not mutate inputs."""
        mu = pd.Series({"AAA": 0.1})
        S = pd.DataFrame([[0.04]], index=["AAA"], columns=["AAA"])
        apply_overrides(mu, S, {"AAA": 0.5}, None)
        assert mu["AAA"] == 0.1


class TestDescriptiveStats:
    def test_basic_output(self, prices):
        result = compute_descriptive_stats(prices)
        assert "AAA" in result
        assert "BBB" in result
        for sym in ("AAA", "BBB"):
            s = result[sym]
            for k in ("n_obs", "mean_daily", "std_daily", "ann_return",
                      "ann_vol", "sharpe", "var_95_daily"):
                assert k in s

    def test_skips_short_series(self):
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        short = pd.DataFrame({"AAA": range(10)}, index=dates)
        result = compute_descriptive_stats(short)
        assert "AAA" not in result


class TestGenerateFrontier:
    def test_returns_lists(self, prices):
        mu = pd.Series({"AAA": 0.1, "BBB": 0.08})
        S = pd.DataFrame([[0.04, 0.01], [0.01, 0.04]],
                         index=["AAA", "BBB"], columns=["AAA", "BBB"])
        result = generate_frontier(mu, S, weight_bounds=(0, 1), rfr=0.04, n_points=10)
        assert "volatilities" in result
        assert "returns" in result
        assert isinstance(result["volatilities"], list)
