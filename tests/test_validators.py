import pytest

from validators import (
    validate_date,
    validate_date_range,
    validate_float,
    validate_ticker,
    validate_tickers,
    validate_weights,
)


class TestTicker:
    def test_valid(self):
        assert validate_ticker("aapl") == "AAPL"
        assert validate_ticker("  msft  ") == "MSFT"
        assert validate_ticker("BRK.B") == "BRK.B"
        assert validate_ticker("BF-B") == "BF-B"

    def test_empty(self):
        with pytest.raises(ValueError):
            validate_ticker("")
        with pytest.raises(ValueError):
            validate_ticker("   ")

    def test_not_string(self):
        with pytest.raises(ValueError):
            validate_ticker(123)
        with pytest.raises(ValueError):
            validate_ticker(None)

    def test_invalid_chars(self):
        with pytest.raises(ValueError):
            validate_ticker("AAPL@")
        with pytest.raises(ValueError):
            validate_ticker("123")

    def test_too_long(self):
        with pytest.raises(ValueError):
            validate_ticker("ABCDEFGHIJK")


class TestTickers:
    def test_dedupe(self):
        assert validate_tickers(["AAPL", "aapl", "MSFT"]) == ["AAPL", "MSFT"]

    def test_min_count(self):
        with pytest.raises(ValueError):
            validate_tickers(["AAPL"], min_count=2)

    def test_not_list(self):
        with pytest.raises(ValueError):
            validate_tickers("AAPL")

    def test_max_count(self):
        with pytest.raises(ValueError):
            validate_tickers([f"T{i}" for i in range(100)], max_count=50)


class TestDate:
    def test_valid(self):
        assert validate_date("2024-01-15") == "2024-01-15"

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            validate_date("01/15/2024")
        with pytest.raises(ValueError):
            validate_date("not-a-date")

    def test_not_string(self):
        with pytest.raises(ValueError):
            validate_date(None)


class TestDateRange:
    def test_valid(self):
        assert validate_date_range("2024-01-01", "2024-12-31") == ("2024-01-01", "2024-12-31")

    def test_start_after_end(self):
        with pytest.raises(ValueError, match="before"):
            validate_date_range("2024-12-31", "2024-01-01")

    def test_same_date(self):
        with pytest.raises(ValueError):
            validate_date_range("2024-01-01", "2024-01-01")


class TestFloat:
    def test_valid(self):
        assert validate_float(0.5, "x") == 0.5
        assert validate_float("0.5", "x") == 0.5

    def test_default(self):
        assert validate_float(None, "x", default=0.04) == 0.04

    def test_required(self):
        with pytest.raises(ValueError, match="required"):
            validate_float(None, "x")

    def test_bounds(self):
        with pytest.raises(ValueError, match=">="):
            validate_float(-1, "x", lo=0)
        with pytest.raises(ValueError, match="<="):
            validate_float(2, "x", hi=1)

    def test_not_numeric(self):
        with pytest.raises(ValueError, match="must be a number"):
            validate_float("nope", "x")


class TestWeights:
    def test_valid(self):
        result = validate_weights({"AAPL": 0.6, "msft": 0.4})
        assert result == {"AAPL": 0.6, "MSFT": 0.4}

    def test_empty(self):
        with pytest.raises(ValueError):
            validate_weights({})

    def test_not_dict(self):
        with pytest.raises(ValueError):
            validate_weights([("AAPL", 1.0)])

    def test_out_of_bounds(self):
        with pytest.raises(ValueError):
            validate_weights({"AAPL": 1.5})
        with pytest.raises(ValueError):
            validate_weights({"AAPL": -0.1})

    def test_all_zero_filtered(self):
        with pytest.raises(ValueError, match="zero"):
            validate_weights({"AAPL": 0.0, "MSFT": 0.0}, allow_zero=False)
