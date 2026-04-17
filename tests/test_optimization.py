import numpy as np
import pandas as pd
import pytest

from services import optimization


@pytest.fixture
def mu_S():
    mu = pd.Series({"AAA": 0.10, "BBB": 0.08, "CCC": 0.12})
    S = pd.DataFrame(
        [[0.04, 0.01, 0.02],
         [0.01, 0.03, 0.015],
         [0.02, 0.015, 0.05]],
        index=["AAA", "BBB", "CCC"],
        columns=["AAA", "BBB", "CCC"],
    )
    return mu, S


class TestSimpleMethods:
    def test_equal_weight(self):
        w = optimization.run_equal_weight(["A", "B", "C", "D"])
        assert all(abs(v - 0.25) < 1e-9 for v in w.values())
        assert sum(w.values()) == pytest.approx(1.0)

    def test_max_sharpe_sums_to_one(self, mu_S):
        mu, S = mu_S
        w = optimization.run_max_sharpe(mu, S, weight_bounds=(0, 1), rfr=0.04)
        assert abs(sum(w.values()) - 1.0) < 1e-4

    def test_min_volatility(self, mu_S):
        mu, S = mu_S
        w = optimization.run_min_volatility(mu, S, weight_bounds=(0, 1))
        assert abs(sum(w.values()) - 1.0) < 1e-4


class TestRiskParity:
    def test_sums_to_one(self, mu_S):
        _, S = mu_S
        w = optimization.run_risk_parity(["AAA", "BBB", "CCC"], S, weight_bounds=(0, 1))
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_equal_risk_contribution(self, mu_S):
        _, S = mu_S
        w = optimization.run_risk_parity(["AAA", "BBB", "CCC"], S, weight_bounds=(0, 1))
        arr = np.array([w[t] for t in ("AAA", "BBB", "CCC")])
        cov = S.values
        pv = arr @ cov @ arr
        rc = arr * (cov @ arr) / pv
        # All risk contributions should be approximately equal (1/3)
        assert all(abs(r - 1/3) < 0.05 for r in rc)


class TestHRP:
    def test_hrp_shape(self, mu_S):
        _, S = mu_S
        w, info = optimization.run_hrp(["AAA", "BBB", "CCC"], S)
        assert abs(sum(w.values()) - 1.0) < 1e-4
        assert "sorted_tickers" in info
        assert "risk_contributions" in info
