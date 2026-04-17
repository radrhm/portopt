"""Input validation helpers. All functions raise ValueError on invalid input."""

import re
from datetime import datetime

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def validate_ticker(sym) -> str:
    """Normalise and validate a single ticker symbol."""
    if not isinstance(sym, str):
        raise ValueError("ticker must be a string.")
    s = sym.strip().upper()
    if not s:
        raise ValueError("ticker is empty.")
    if not _TICKER_RE.match(s):
        raise ValueError(f"Invalid ticker format: {sym!r}")
    return s


def validate_tickers(syms, *, min_count: int = 1, max_count: int = 50) -> list[str]:
    """Validate a list of ticker symbols; returns normalised list (uppercased, deduped)."""
    if not isinstance(syms, list):
        raise ValueError("tickers must be a list.")
    if len(syms) < min_count:
        raise ValueError(f"at least {min_count} ticker(s) required.")
    if len(syms) > max_count:
        raise ValueError(f"at most {max_count} tickers allowed.")
    seen, out = set(), []
    for s in syms:
        t = validate_ticker(s)
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def validate_date(s, name: str = "date") -> str:
    """Validate an ISO YYYY-MM-DD string; returns it unchanged."""
    if not isinstance(s, str):
        raise ValueError(f"{name} must be a date string (YYYY-MM-DD).")
    try:
        datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: {exc}") from exc
    return s


def validate_date_range(start: str, end: str) -> tuple[str, str]:
    """Validate that both dates parse and start < end."""
    s = validate_date(start, "start_date")
    e = validate_date(end, "end_date")
    if datetime.fromisoformat(s) >= datetime.fromisoformat(e):
        raise ValueError("start_date must be before end_date.")
    return s, e


def validate_float(
    v,
    name: str,
    *,
    lo: float | None = None,
    hi: float | None = None,
    default: float | None = None,
) -> float:
    """Coerce *v* to float with optional bounds and default."""
    if v is None or v == "":
        if default is not None:
            return default
        raise ValueError(f"{name} is required.")
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if lo is not None and f < lo:
        raise ValueError(f"{name} must be >= {lo}.")
    if hi is not None and f > hi:
        raise ValueError(f"{name} must be <= {hi}.")
    return f


def validate_weights(weights, *, allow_zero: bool = True) -> dict[str, float]:
    """Validate weight mapping {TICKER: weight}. Returns normalised dict."""
    if not isinstance(weights, dict):
        raise ValueError("weights must be an object.")
    if not weights:
        raise ValueError("weights must not be empty.")
    out: dict[str, float] = {}
    for k, v in weights.items():
        sym = validate_ticker(k)
        w = validate_float(v, f"weights[{sym}]", lo=0.0, hi=1.0, default=0.0)
        if not allow_zero and w == 0:
            continue
        out[sym] = w
    if not out:
        raise ValueError("weights sum to zero after filtering.")
    return out
