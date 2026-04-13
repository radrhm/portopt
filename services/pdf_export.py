"""PDF report generation — reportlab layout, Gemini AI text via REST API."""

import io
import os
import json
import base64
import logging
import traceback
import concurrent.futures
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Colour palette (matches app dark theme but inverted for white PDF) ──────────
C_NAVY   = "#1e3a5f"
C_BLUE   = "#2563eb"
C_CYAN   = "#0891b2"
C_GREEN  = "#059669"
C_RED    = "#dc2626"
C_GOLD   = "#d97706"
C_MUTED  = "#64748b"
C_LIGHT  = "#f0f6ff"
C_ALT    = "#f8fafc"
C_BORDER = "#e2e8f0"

METHOD_NAMES = {
    "max_sharpe":      "Maximum Sharpe Ratio",
    "min_volatility":  "Minimum Volatility",
    "black_litterman": "Black-Litterman",
    "risk_parity":     "Risk Parity (ERC)",
    "hrp":             "Hierarchical Risk Parity (HRP)",
    "equal_weight":    "Equal Weight (1/N)",
    "max_return":      "Maximum Return",
    "custom":          "Custom Weights",
}

METHOD_FORMULAS = {
    "max_sharpe":      (r"\max_w\ S_p = \frac{\mu_p - r_f}{\sigma_p}",
                        r"\text{s.t.}\ \mathbf{1}^T w = 1,\ w_i \in [w_{min}, w_{max}]"),
    "min_volatility":  (r"\min_w\ \sigma_p^2 = w^T \Sigma w",
                        r"\text{s.t.}\ \mathbf{1}^T w = 1,\ w_i \in [w_{min}, w_{max}]"),
    "black_litterman": (r"\mu_{BL} = \left[(\tau\Sigma)^{-1} + P^T\Omega^{-1}P\right]^{-1}"
                        r"\left[(\tau\Sigma)^{-1}\Pi + P^T\Omega^{-1}q\right]",
                        r"\Pi = \lambda \Sigma w_{mkt}\ \text{(market equilibrium prior)}"),
    "risk_parity":     (r"RC_i = w_i \cdot \frac{\partial \sigma_p}{\partial w_i} = \frac{\sigma_p}{n}\ \forall i",
                        r"\text{Each asset contributes equally to portfolio volatility}"),
    "hrp":             (r"\text{Cluster assets via } d_{ij} = \sqrt{\frac{1-\rho_{ij}}{2}}",
                        r"\text{Bisection: } w_i \propto \frac{1}{\sigma_i^2}\ \text{within each cluster}"),
    "equal_weight":    (r"w_i = \frac{1}{N}\ \forall i",
                        r"\text{N = number of assets; no optimisation needed}"),
    "max_return":      (r"\max_w\ \mu_p = w^T \mu",
                        r"\text{s.t.}\ \mathbf{1}^T w = 1,\ w_i \in [w_{min}, w_{max}]"),
    "custom":          (r"w_i = \text{user-defined}",
                        r"\sum_i w_i = 1\ \text{(normalised)}"),
}


# ── Gemini AI text ───────────────────────────────────────────────────────────────

def _get_gemini_text(metrics: dict, weights: dict, method: str,
                     tickers: list, settings: dict, desc_stats: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return _default_ai_text(method, metrics)

    prompt = f"""You are a quantitative portfolio analyst writing an academic investment report.

Portfolio data:
- Assets ({len(tickers)}): {', '.join(tickers)}
- Optimization method: {METHOD_NAMES.get(method, method)}
- Expected Annual Return: {metrics.get('expected_return', 0):.2f}%
- Annual Volatility: {metrics.get('volatility', 0):.2f}%
- Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}
- Sortino Ratio: {metrics.get('sortino_ratio', 0):.3f}
- Calmar Ratio: {metrics.get('calmar_ratio', 0):.3f}
- Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%
- Beta vs SPY: {metrics.get('beta', 0):.3f}
- Alpha: {metrics.get('alpha', 0):.2f}%
- Win Rate: {metrics.get('win_rate', 0):.1f}%
- VaR 95% (daily): {metrics.get('var_95_daily', 0):.2f}%
- CVaR 95% (daily): {metrics.get('cvar_95_daily', 0):.2f}%
- Skewness: {metrics.get('skewness', 0):.3f}
- Excess Kurtosis: {metrics.get('kurtosis', 0):.3f}
- Tracking Error: {metrics.get('tracking_error', 0):.2f}%
- Information Ratio: {metrics.get('info_ratio', 0):.3f}
Portfolio weights: {json.dumps({{k: f"{v*100:.1f}%" for k, v in weights.items()}})}

Write a professional financial analysis report in JSON with these exact keys:
{{
  "abstract": "170-200 word executive summary covering method rationale, key performance metrics, risk profile, and overall portfolio quality",
  "overview": "90-100 word analysis of portfolio composition, weight concentration, and key return/risk metrics",
  "performance": "90-100 word analysis of historical returns, drawdown characteristics, and consistency metrics (win rate, Calmar)",
  "risk": "90-100 word analysis of VaR, CVaR, beta, tracking error, and tail-risk properties",
  "statistics": "90-100 word discussion of return distribution shape — skewness, excess kurtosis, departure from normality, and implications",
  "method": "90-100 word explanation of the {METHOD_NAMES.get(method, method)} approach: mathematical intuition, advantages, and how results reflect the method",
  "scenarios": "90-100 word forward-looking commentary on Monte Carlo uncertainty and historical stress resilience"
}}

Use precise financial language, reference actual numbers, and write in academic tone. Return only valid JSON."""

    def _call():
        import requests as _req
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.4},
        }
        try:
            r = _req.post(url, json=body, timeout=18)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0]
            return json.loads(text.strip())
        except Exception:
            logger.warning("Gemini REST call failed: %s", traceback.format_exc())
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_call)
        try:
            result = future.result(timeout=20)
            if result:
                return result
        except concurrent.futures.TimeoutError:
            logger.warning("Gemini API timed out; using default text.")

    return _default_ai_text(method, metrics)


def _default_ai_text(method: str, metrics: dict) -> dict:
    m = METHOD_NAMES.get(method, method)
    ret = metrics.get("expected_return", 0)
    vol = metrics.get("volatility", 0)
    sr  = metrics.get("sharpe_ratio", 0)
    mdd = metrics.get("max_drawdown", 0)
    return {
        "abstract": (
            f"This report presents a quantitative analysis of an optimised portfolio constructed using "
            f"the {m} method. The portfolio achieves an expected annual return of {ret:.2f}% with "
            f"annualised volatility of {vol:.2f}%, yielding a Sharpe ratio of {sr:.3f}. The maximum "
            f"drawdown observed over the analysis period was {mdd:.2f}%. Full risk decomposition, "
            f"distributional properties, and scenario analyses are provided in subsequent sections."
        ),
        "overview": (
            f"The portfolio was constructed via {m} optimisation. With an expected annual return "
            f"of {ret:.2f}% and volatility of {vol:.2f}%, it achieves a Sharpe ratio of {sr:.3f}, "
            f"reflecting the risk-adjusted efficiency of the selected asset combination."
        ),
        "performance": (
            f"Historical backtesting reveals an expected annualised return of {ret:.2f}% against "
            f"a volatility of {vol:.2f}%. The maximum drawdown of {mdd:.2f}% characterises the "
            f"worst peak-to-trough decline in the sample period."
        ),
        "risk": (
            f"Portfolio risk analysis indicates annualised volatility of {vol:.2f}%. VaR and CVaR "
            f"estimates quantify tail exposure. Beta and tracking error metrics contextualise "
            f"systematic risk relative to the SPY benchmark."
        ),
        "statistics": (
            "Return distribution analysis examines departure from normality via skewness and excess "
            "kurtosis. The Jarque-Bera test is applied to each constituent. Fat tails and negative "
            "skewness are common in equity returns and inform risk-management decisions."
        ),
        "method": (
            f"The {m} framework was selected to optimise the portfolio. This approach "
            f"provides a disciplined, quantitative allocation that balances return expectations "
            f"against risk constraints defined by the covariance structure of the asset universe."
        ),
        "scenarios": (
            "Monte Carlo simulation projects the distribution of future portfolio values across "
            "thousands of paths sampled from the historical return distribution. Stress tests "
            "replay portfolio weights through major historical crises to quantify downside resilience."
        ),
    }


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _decode_chart(url: str | None) -> io.BytesIO | None:
    if not url or "base64," not in url:
        return None
    try:
        b64 = url.split("base64,", 1)[1]
        return io.BytesIO(base64.b64decode(b64))
    except Exception:
        return None


def _latex_to_readable(latex: str) -> str:
    """Convert a LaTeX string to a human-readable Unicode approximation."""
    import re
    s = latex
    # Common substitutions — order matters
    s = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"(\1) / (\2)", s)
    s = re.sub(r"\\sqrt\{([^}]+)\}", r"√(\1)", s)
    s = s.replace(r"\mathbf{1}", "𝟏").replace(r"\mathbf{w}", "𝐰")
    s = s.replace(r"\mathbf", "").replace(r"\boldsymbol", "")
    s = s.replace(r"\Sigma", "Σ").replace(r"\sigma", "σ").replace(r"\mu", "μ")
    s = s.replace(r"\alpha", "α").replace(r"\beta", "β").replace(r"\pi", "π")
    s = s.replace(r"\tau", "τ").replace(r"\lambda", "λ").replace(r"\omega", "ω")
    s = s.replace(r"\Omega", "Ω").replace(r"\Pi", "Π").replace(r"\gamma", "γ")
    s = s.replace(r"\chi", "χ").replace(r"\rho", "ρ").replace(r"\Delta", "Δ")
    s = s.replace(r"\mathcal{N}", "𝒩").replace(r"\text{", "").replace(r"\quad", "   ")
    s = re.sub(r"\^(\{[^}]+\}|[^\s{])", lambda m: _superscript(m.group(1).strip("{}")), s)
    s = re.sub(r"_(\{[^}]+\}|[^\s{])",  lambda m: _subscript(m.group(1).strip("{}")),   s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)   # remove remaining commands
    s = re.sub(r"[{}]", "", s)
    return s.strip()


_SUP = {
    ord('0'): '\u2070', ord('1'): '\u00b9', ord('2'): '\u00b2', ord('3'): '\u00b3',
    ord('4'): '\u2074', ord('5'): '\u2075', ord('6'): '\u2076', ord('7'): '\u2077',
    ord('8'): '\u2078', ord('9'): '\u2079', ord('+'): '\u207a', ord('-'): '\u207b',
    ord('='): '\u207c', ord('('): '\u207d', ord(')'): '\u207e', ord('n'): '\u207f',
    ord('T'): '\u1d40', ord('p'): '\u1d56', ord('f'): '\u1da0', ord('m'): '\u1d50',
    ord('k'): '\u1d4f', ord('d'): '\u1d48',
}
_SUB = {
    ord('0'): '\u2080', ord('1'): '\u2081', ord('2'): '\u2082', ord('3'): '\u2083',
    ord('4'): '\u2084', ord('5'): '\u2085', ord('6'): '\u2086', ord('7'): '\u2087',
    ord('8'): '\u2088', ord('9'): '\u2089', ord('a'): '\u2090', ord('e'): '\u2091',
    ord('f'): 'f',      ord('i'): '\u1d62', ord('j'): '\u2c7c', ord('k'): '\u2096',
    ord('l'): '\u2097', ord('m'): '\u2098', ord('n'): '\u2099', ord('o'): '\u2092',
    ord('p'): '\u209a', ord('r'): '\u1d63', ord('s'): '\u209b', ord('t'): '\u209c',
    ord('u'): '\u1d64', ord('v'): '\u1d65', ord('x'): '\u2093', ord('y'): 'y',
    ord('z'): 'z',      ord('+'): '\u208a', ord('-'): '\u208b', ord('='): '\u208c',
    ord('('): '\u208d', ord(')'): '\u208e',
}


def _superscript(s: str) -> str:
    return s.translate(_SUP)


def _subscript(s: str) -> str:
    return s.translate(_SUB)


def _make_styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
    from reportlab.lib.colors import HexColor

    def ps(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "cover_title":   ps("ct",  fontName="Helvetica-Bold", fontSize=30,
                             textColor=HexColor(C_NAVY), spaceAfter=4, leading=34),
        "cover_sub":     ps("cs",  fontName="Helvetica",      fontSize=13,
                             textColor=HexColor(C_MUTED), spaceAfter=18),
        "cover_meta_k":  ps("cmk", fontName="Helvetica-Bold", fontSize=9,
                             textColor=HexColor(C_NAVY)),
        "cover_meta_v":  ps("cmv", fontName="Helvetica",      fontSize=9,
                             textColor=HexColor(C_MUTED)),
        "section_num":   ps("sn",  fontName="Helvetica",      fontSize=10,
                             textColor=HexColor(C_CYAN), spaceAfter=1),
        "section_head":  ps("sh",  fontName="Helvetica-Bold", fontSize=15,
                             textColor=HexColor(C_NAVY), spaceAfter=6, spaceBefore=4),
        "abstract_head": ps("ah",  fontName="Helvetica-Bold", fontSize=13,
                             textColor=HexColor(C_NAVY), spaceAfter=6),
        "body":          ps("b",   fontName="Helvetica",      fontSize=9,
                             textColor=HexColor("#1e293b"), leading=14,
                             alignment=TA_JUSTIFY, spaceAfter=8),
        "caption":       ps("cap", fontName="Helvetica",      fontSize=8,
                             textColor=HexColor(C_MUTED), alignment=TA_CENTER,
                             spaceAfter=10, spaceBefore=3),
        "formula_label": ps("fl",  fontName="Helvetica-Bold", fontSize=8,
                             textColor=HexColor(C_CYAN), spaceAfter=2, spaceBefore=8),
        "formula_alt":   ps("fa",  fontName="Helvetica-Oblique", fontSize=9,
                             textColor=HexColor(C_NAVY), alignment=TA_CENTER,
                             spaceAfter=6, spaceBefore=6,
                             backColor=HexColor("#eef4fd"),
                             borderPad=6),
        "tbl_head":      ps("th",  fontName="Helvetica-Bold", fontSize=8,
                             textColor=HexColor("#ffffff")),
        "tbl_cell":      ps("tc",  fontName="Helvetica",      fontSize=8,
                             textColor=HexColor("#1e293b")),
        "tbl_cell_g":    ps("tcg", fontName="Helvetica-Bold", fontSize=8,
                             textColor=HexColor(C_GREEN)),
        "tbl_cell_r":    ps("tcr", fontName="Helvetica-Bold", fontSize=8,
                             textColor=HexColor(C_RED)),
        "tbl_cell_muted":ps("tcm", fontName="Helvetica",      fontSize=8,
                             textColor=HexColor(C_MUTED)),
        "watermark":     ps("wm",  fontName="Helvetica",      fontSize=8,
                             textColor=HexColor(C_MUTED), alignment=TA_CENTER),
    }


def _section_heading(num: int, title: str, styles: dict) -> list:
    from reportlab.platypus import Paragraph, Spacer, HRFlowable
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import cm
    return [
        Spacer(1, 0.3 * cm),
        HRFlowable(width="100%", thickness=2, color=HexColor(C_NAVY), spaceAfter=4),
        Paragraph(f"Section {num}", styles["section_num"]),
        Paragraph(title, styles["section_head"]),
        Spacer(1, 0.15 * cm),
    ]


def _formula_block(latex: str, label: str, counter: list, styles: dict,
                   text_w_pts: float = 0) -> list:
    """Render a numbered equation as a styled Unicode text block."""
    from reportlab.platypus import Paragraph

    counter[0] += 1
    readable = _latex_to_readable(latex)
    return [
        Paragraph(f"Equation {counter[0]}: {label}", styles["formula_label"]),
        Paragraph(readable, styles["formula_alt"]),
    ]


def _embed_chart(chart_buf: io.BytesIO | None, fig_num: list,
                 caption: str, styles: dict,
                 text_w_pts: float, height_ratio: float = 0.38) -> list:
    """Embed a chart image with a numbered caption."""
    from reportlab.platypus import Paragraph, Spacer, Image
    from reportlab.lib.units import cm

    if chart_buf is None:
        return []
    fig_num[0] += 1
    img_h = text_w_pts * height_ratio
    items = [
        Spacer(1, 0.2 * cm),
        Image(chart_buf, width=text_w_pts, height=img_h),
        Paragraph(f"<b>Figure {fig_num[0]}.</b> {caption}", styles["caption"]),
    ]
    return items


def _metric_table(rows: list[tuple], styles: dict, col_widths: list) -> "Table":
    """Thin wrapper: rows = [(label, value, colour_flag), ...]"""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.colors import HexColor

    header = [
        Paragraph(rows[0][0], styles["tbl_head"]),
        Paragraph(rows[0][1], styles["tbl_head"]),
    ]
    data = [header]
    for label, val, flag in rows[1:]:
        sty = (styles["tbl_cell_g"] if flag == "+" else
               styles["tbl_cell_r"] if flag == "-" else styles["tbl_cell"])
        data.append([Paragraph(label, styles["tbl_cell"]), Paragraph(val, sty)])

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(C_NAVY)),
        ("GRID",       (0, 0), (-1, -1), 0.4, HexColor(C_BORDER)),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND", (0, i), (-1, i), HexColor(C_ALT)))
    tbl.setStyle(ts)
    return tbl


# ── Cover page ───────────────────────────────────────────────────────────────────

def _build_cover(req: dict, styles: dict, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer, Table, HRFlowable, Image
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import cm

    story = []
    # Logo
    logo_path = os.path.join(os.path.dirname(__file__), "..", "static", "favicon.png")
    logo_path = os.path.normpath(logo_path)
    if os.path.exists(logo_path):
        story.append(Image(logo_path, width=54, height=54))
        story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("PortOpt", styles["cover_title"]))
    story.append(Paragraph("Interactive Portfolio Optimization", styles["cover_sub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor(C_CYAN), spaceAfter=14))
    story.append(_bold_para("Portfolio Analysis Report", 18, C_NAVY))
    story.append(Spacer(1, 0.5 * cm))

    # Metadata table
    weights = req.get("weights", {})
    tickers = list(weights.keys())
    method  = req.get("method", "unknown")
    settings= req.get("settings", {})
    metrics = req.get("analytics", {}).get("metrics", {})
    gen_date = datetime.now().strftime("%B %d, %Y")

    rows = [
        ("Portfolio Name",    req.get("portfolio_name", "Untitled")),
        ("Generated",         gen_date),
        ("Optimization Method", METHOD_NAMES.get(method, method)),
        ("Assets",            ", ".join(tickers)),
        ("Date Range",        f"{settings.get('start','—')}  →  {settings.get('end','—')}"),
        ("Risk-Free Rate",    f"{float(settings.get('rfr', 0.04)) * 100:.2f}%"),
        ("Trading Days",      str(metrics.get("n_days", "—"))),
    ]
    from reportlab.platypus import TableStyle
    meta_data = [[Paragraph(k, styles["cover_meta_k"]),
                  Paragraph(v, styles["cover_meta_v"])] for k, v in rows]
    meta_tbl = Table(meta_data, colWidths=[text_w * 0.38, text_w * 0.62])
    meta_tbl.setStyle([
        ("GRID",        (0, 0), (-1, -1), 0.4, HexColor(C_BORDER)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [HexColor("#ffffff"), HexColor(C_ALT)]),
    ])
    story.append(meta_tbl)
    story.append(Spacer(1, 0.7 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor(C_BORDER)))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Prepared by PortOpt — Interactive Portfolio Optimization  •  "
        f"Report generated {gen_date}",
        styles["watermark"],
    ))
    return story


def _bold_para(text: str, size: int, colour: str) -> "Paragraph":
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    sty = ParagraphStyle("_bp", fontName="Helvetica-Bold", fontSize=size,
                         textColor=HexColor(colour), spaceAfter=4)
    return Paragraph(text, sty)


# ── Abstract ─────────────────────────────────────────────────────────────────────

def _build_abstract(req: dict, ai: dict, styles: dict, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import cm

    metrics = req.get("analytics", {}).get("metrics", {})
    story = [
        Paragraph("Abstract", styles["abstract_head"]),
        HRFlowable(width="100%", thickness=1, color=HexColor(C_BORDER), spaceAfter=8),
        Paragraph(ai.get("abstract", ""), styles["body"]),
        Spacer(1, 0.4 * cm),
        _bold_para("Key Performance Summary", 10, C_NAVY),
        Spacer(1, 0.1 * cm),
    ]

    def fmt(v, pct=True, dec=2):
        if v is None:
            return "—"
        s = f"{v:.{dec}f}{'%' if pct else ''}"
        return s

    def sign(v):
        if v is None: return "n"
        return "+" if v > 0 else ("-" if v < 0 else "n")

    kpi_rows = [
        ("Metric", "Value", "n"),
        ("Expected Annual Return",     fmt(metrics.get("expected_return")),  sign(metrics.get("expected_return"))),
        ("Annual Volatility",          fmt(metrics.get("volatility")),       "n"),
        ("Sharpe Ratio",               fmt(metrics.get("sharpe_ratio"), pct=False, dec=3),  sign(metrics.get("sharpe_ratio"))),
        ("Sortino Ratio",              fmt(metrics.get("sortino_ratio"), pct=False, dec=3), sign(metrics.get("sortino_ratio"))),
        ("Calmar Ratio",               fmt(metrics.get("calmar_ratio"),  pct=False, dec=3), sign(metrics.get("calmar_ratio"))),
        ("Maximum Drawdown",           fmt(metrics.get("max_drawdown")),      "-"),
        ("Beta (vs SPY)",              fmt(metrics.get("beta"), pct=False, dec=3),           "n"),
        ("Alpha",                      fmt(metrics.get("alpha")),             sign(metrics.get("alpha"))),
        ("Win Rate",                   fmt(metrics.get("win_rate")),          "n"),
        ("VaR 95% (daily)",            fmt(metrics.get("var_95_daily")),      "-"),
        ("CVaR 95% (daily)",           fmt(metrics.get("cvar_95_daily")),     "-"),
    ]
    story.append(_metric_table(kpi_rows, styles,
                               [text_w * 0.55, text_w * 0.45]))
    return story


# ── Section builders ─────────────────────────────────────────────────────────────

def _build_overview(req: dict, ai: dict, styles: dict, charts: dict,
                    fig_num: list, eq_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import cm

    weights  = req.get("weights", {})
    contrib  = req.get("analytics", {}).get("contributions", {})
    story    = _section_heading(1, "Portfolio Overview", styles)
    story   += [Paragraph(ai.get("overview", ""), styles["body"])]

    # Allocation chart
    story += _embed_chart(
        _decode_chart(charts.get("chart-alloc")), fig_num,
        "Optimal portfolio allocation. Each sector represents an asset's weight "
        "in the optimised portfolio.",
        styles, text_w, height_ratio=0.45,
    )

    # Weights table
    story.append(Spacer(1, 0.2 * cm))
    story.append(_bold_para("Portfolio Weights & Risk Contributions", 9, C_NAVY))
    rows = [("Ticker", "Weight (%)", "Ann Return (%)", "Ann Vol (%)", "Risk Contrib (%)","n")]
    for sym, w in sorted(weights.items(), key=lambda x: -x[1]):
        c = contrib.get(sym, {})
        rows.append((sym, f"{w*100:.2f}", f"{c.get('ann_return','—')}", f"{c.get('ann_vol','—')}",
                     f"{c.get('risk_contrib_pct','—')}", "n"))
    from reportlab.platypus import Table as RLTable
    # Rebuild as proper table
    tbl_data = []
    hdr = [Paragraph(h, styles["tbl_head"]) for h in ("Ticker","Weight (%)","Ann Return","Ann Vol","Risk Contrib")]
    tbl_data.append(hdr)
    for r in rows[1:]:
        tbl_data.append([Paragraph(str(c), styles["tbl_cell"]) for c in r[:5]])
    col_ws = [text_w * x for x in [0.12, 0.17, 0.24, 0.24, 0.23]]
    tbl = RLTable(tbl_data, colWidths=col_ws, repeatRows=1)
    ts = [("BACKGROUND",(0,0),(-1,0), HexColor(C_NAVY)),
          ("GRID",(0,0),(-1,-1),0.4, HexColor(C_BORDER)),
          ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
          ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
    for i in range(1, len(tbl_data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND",(0,i),(-1,i), HexColor(C_ALT)))
    tbl.setStyle(ts)
    story.append(tbl)

    # Formula
    story += _formula_block(
        r"w^T \mathbf{1} = 1, \quad \sigma_p^2 = w^T \Sigma w",
        "Portfolio Constraint & Variance", eq_num, styles, text_w,
    )
    return story


def _build_performance(req: dict, ai: dict, styles: dict, charts: dict,
                       fig_num: list, eq_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer
    metrics = req.get("analytics", {}).get("metrics", {})
    story   = _section_heading(2, "Historical Performance", styles)
    story  += [Paragraph(ai.get("performance", ""), styles["body"])]
    story += _embed_chart(_decode_chart(charts.get("chart-returns")), fig_num,
        "Cumulative returns: each asset normalised to $1 at the start date "
        "(bold white line = portfolio blend; grey dashed = SPY benchmark).",
        styles, text_w, 0.36)
    story += _embed_chart(_decode_chart(charts.get("chart-drawdown")), fig_num,
        "Portfolio drawdown — percentage decline from the most recent peak at each date. "
        f"Maximum observed drawdown: {metrics.get('max_drawdown', 0):.2f}%.",
        styles, text_w, 0.28)
    story += _embed_chart(_decode_chart(charts.get("chart-rolling")), fig_num,
        "Rolling 60-day volatility (blue, left axis) and Sharpe ratio (gold, right axis) "
        "through the analysis period.",
        styles, text_w, 0.32)

    story += _formula_block(
        r"S_p = \frac{\mu_p - r_f}{\sigma_p}",
        "Sharpe Ratio", eq_num, styles, text_w)
    story += _formula_block(
        r"Sortino = \frac{\mu_p - r_f}{\sigma_d}, \quad \sigma_d = \sqrt{\frac{1}{T}\sum_{t:r_t<0} r_t^2}",
        "Sortino Ratio (downside deviation)", eq_num, styles, text_w)
    story += _formula_block(
        r"MDD = \min_{t}\left(\frac{V_t - \max_{\tau \leq t} V_\tau}{\max_{\tau \leq t} V_\tau}\right)",
        "Maximum Drawdown", eq_num, styles, text_w)
    return story


def _build_risk(req: dict, ai: dict, styles: dict, charts: dict,
                fig_num: list, eq_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer
    metrics = req.get("analytics", {}).get("metrics", {})
    story   = _section_heading(3, "Risk Analysis", styles)
    story  += [Paragraph(ai.get("risk", ""), styles["body"])]

    story += _embed_chart(_decode_chart(charts.get("chart-corr")), fig_num,
        "Pairwise correlation matrix of daily returns. Values near −1 indicate "
        "opposing movements (diversification); near +1 indicate co-movement (concentration risk).",
        styles, text_w, 0.50)
    story += _embed_chart(_decode_chart(charts.get("chart-frontier")), fig_num,
        "Efficient frontier: each blue point is a feasible portfolio. The gold star marks "
        "the optimal portfolio; the green dashed line is the Capital Allocation Line.",
        styles, text_w, 0.46)

    # Risk metrics table
    def fmt(v, pct=True, dec=2):
        return f"{v:.{dec}f}{'%' if pct else ''}" if v is not None else "—"
    def sign(v):
        return "+" if (v or 0) > 0 else ("-" if (v or 0) < 0 else "n")

    risk_rows = [
        ("Metric", "Value", "n"),
        ("VaR 95% (daily)",        fmt(metrics.get("var_95_daily")),       "-"),
        ("CVaR 95% (daily)",       fmt(metrics.get("cvar_95_daily")),      "-"),
        ("VaR 99% (daily)",        fmt(metrics.get("var_99_daily")),       "-"),
        ("CVaR 99% (daily)",       fmt(metrics.get("cvar_99_daily")),      "-"),
        ("Param VaR 95% (ann)",    fmt(metrics.get("param_var_95_ann")),   "-"),
        ("Beta",                   fmt(metrics.get("beta"),  pct=False, dec=3), "n"),
        ("Alpha",                  fmt(metrics.get("alpha")),               sign(metrics.get("alpha"))),
        ("Treynor Ratio",          fmt(metrics.get("treynor_ratio"), pct=False, dec=3), sign(metrics.get("treynor_ratio"))),
        ("Tracking Error",         fmt(metrics.get("tracking_error")),     "n"),
        ("Information Ratio",      fmt(metrics.get("info_ratio"), pct=False, dec=3), sign(metrics.get("info_ratio"))),
        ("R²",                     fmt(metrics.get("r_squared"), pct=False, dec=4), "n"),
        ("Worst Day",              fmt(metrics.get("worst_day")),           "-"),
        ("Best Day",               fmt(metrics.get("best_day")),            "+"),
        ("Gain/Loss Ratio",        fmt(metrics.get("gain_loss_ratio"), pct=False, dec=3), sign(metrics.get("gain_loss_ratio"))),
    ]
    story.append(Spacer(1, 0.15 * 28.35))
    story.append(_metric_table(risk_rows, styles, [text_w * 0.55, text_w * 0.45]))

    story += _formula_block(
        r"VaR_\alpha = -Q_\alpha(R_p)",
        "Value at Risk (historical)", eq_num, styles, text_w)
    story += _formula_block(
        r"CVaR_\alpha = -E\left[R_p \mid R_p \leq VaR_\alpha\right]",
        "Conditional Value at Risk (Expected Shortfall)", eq_num, styles, text_w)
    story += _formula_block(
        r"\beta = \frac{Cov(R_p, R_m)}{Var(R_m)}, \quad \alpha = R_p - r_f - \beta(R_m - r_f)",
        "Portfolio Beta & Jensen's Alpha", eq_num, styles, text_w)
    return story


def _build_statistics(req: dict, ai: dict, styles: dict,
                      eq_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer, Table
    from reportlab.lib.colors import HexColor

    desc  = req.get("descriptive_stats", {})
    story = _section_heading(4, "Descriptive Statistics", styles)
    story += [Paragraph(ai.get("statistics", ""), styles["body"])]

    if not desc:
        story.append(Paragraph("No descriptive statistics available.", styles["body"]))
        return story

    # Build stats table (one row per stock)
    hdr = ["Ticker", "Obs", "Ann Ret", "Ann Vol", "Sharpe", "Skew", "Kurt",
           "Max DD", "Win%", "VaR95", "Normal?"]
    tbl_data = [[Paragraph(h, styles["tbl_head"]) for h in hdr]]
    for sym, s in desc.items():
        normal = "Yes" if s.get("jb_normal") else "No"
        ret_v  = s.get("ann_return", 0) or 0
        row = [sym, str(s.get("n_obs","—")),
               f"{ret_v:.1f}%", f"{s.get('ann_vol',0):.1f}%",
               f"{s.get('sharpe',0):.2f}", f"{s.get('skewness',0):.3f}",
               f"{s.get('kurtosis',0):.3f}", f"{s.get('max_drawdown',0):.1f}%",
               f"{s.get('win_rate',0):.1f}%", f"{s.get('var_95_daily',0):.2f}%",
               normal]
        sty = styles["tbl_cell_g"] if ret_v > 0 else styles["tbl_cell_r"]
        cells = [Paragraph(str(v), styles["tbl_cell"]) for v in row]
        cells[2] = Paragraph(row[2], sty)  # colour Ann Ret
        tbl_data.append(cells)

    col_ws = [text_w * x for x in [0.10, 0.07, 0.10, 0.10, 0.09, 0.09, 0.09, 0.10, 0.08, 0.10, 0.08]]
    tbl = Table(tbl_data, colWidths=col_ws, repeatRows=1)
    ts = [("BACKGROUND",(0,0),(-1,0), HexColor(C_NAVY)),
          ("GRID",(0,0),(-1,-1),0.4, HexColor(C_BORDER)),
          ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
          ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
    for i in range(1, len(tbl_data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND",(0,i),(-1,i), HexColor(C_ALT)))
    tbl.setStyle(ts)
    story.append(tbl)

    story += _formula_block(
        r"\gamma_1 = \frac{\mu_3}{\sigma^3} \quad \text{(skewness)}",
        "Skewness (third standardised moment)", eq_num, styles, text_w)
    story += _formula_block(
        r"\gamma_2 = \frac{\mu_4}{\sigma^4} - 3 \quad \text{(excess kurtosis)}",
        "Excess Kurtosis (fourth standardised moment)", eq_num, styles, text_w)
    story += _formula_block(
        r"JB = \frac{n}{6}\left(\gamma_1^2 + \frac{(\gamma_2)^2}{4}\right) \sim \chi^2(2)",
        "Jarque-Bera Normality Test", eq_num, styles, text_w)
    return story


def _build_method(req: dict, ai: dict, styles: dict, charts: dict,
                  fig_num: list, eq_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer
    method = req.get("method", "unknown")
    story  = _section_heading(5, f"Optimization Method: {METHOD_NAMES.get(method, method)}", styles)
    story += [Paragraph(ai.get("method", ""), styles["body"])]

    # Method-specific charts
    if method == "black_litterman":
        story += _embed_chart(_decode_chart(charts.get("chart-bl-step1")), fig_num,
            "Step 1: Market-implied equilibrium returns (CAPM prior π = λΣw_mkt).",
            styles, text_w, 0.40)
        story += _embed_chart(_decode_chart(charts.get("chart-bl-step5")), fig_num,
            "Step 5: Prior (blue) vs posterior (gold) expected returns after blending investor views.",
            styles, text_w, 0.40)
    elif method == "hrp":
        story += _embed_chart(_decode_chart(charts.get("chart-hrp-step3")), fig_num,
            "Step 3: Asset risk contributions after hierarchical clustering allocation.",
            styles, text_w, 0.40)

    f1, f2 = METHOD_FORMULAS.get(method, (r"w^T\mathbf{1}=1", r"w_i \geq 0"))
    story += _formula_block(f1, "Primary optimisation objective", eq_num, styles, text_w)
    story += _formula_block(f2, "Constraint / supplementary formula",    eq_num, styles, text_w)
    return story


def _build_scenarios(req: dict, ai: dict, styles: dict, charts: dict,
                     fig_num: list, eq_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer, Table
    from reportlab.lib.colors import HexColor

    story = _section_heading(6, "Forward-Looking Analysis & Stress Tests", styles)
    story += [Paragraph(ai.get("scenarios", ""), styles["body"])]

    # Monte Carlo chart
    story += _embed_chart(_decode_chart(charts.get("chart-montecarlo")), fig_num,
        "Monte Carlo simulation: fan chart of 5th–95th percentile paths sampled from "
        "the historical return distribution. Not a forecast.",
        styles, text_w, 0.40)

    # Stress test table if data present
    scenarios = req.get("stress_results", {})
    if scenarios:
        Paragraph_ = Paragraph
        hdr = ["Scenario", "Period", "Portfolio", "SPY", "Δ vs SPY"]
        tbl_data = [[Paragraph_(h, styles["tbl_head"]) for h in hdr]]
        for _key, sc in scenarios.items():
            if sc.get("error"):
                continue
            p_ret = sc.get("portfolio_return", 0) or 0
            s_ret = sc.get("spy_return")
            delta = (p_ret - s_ret) if s_ret is not None else None
            sty_p = styles["tbl_cell_g"] if p_ret > 0 else styles["tbl_cell_r"]
            sty_d = styles["tbl_cell_g"] if (delta or 0) > 0 else styles["tbl_cell_r"]
            tbl_data.append([
                Paragraph_(sc.get("name",""), styles["tbl_cell"]),
                Paragraph_(sc.get("period",""), styles["tbl_cell"]),
                Paragraph_(f"{p_ret:.1f}%", sty_p),
                Paragraph_(f"{s_ret:.1f}%" if s_ret is not None else "—", styles["tbl_cell"]),
                Paragraph_(f"{delta:+.1f}%" if delta is not None else "—", sty_d),
            ])
        if len(tbl_data) > 1:
            col_ws = [text_w * x for x in [0.30, 0.27, 0.15, 0.14, 0.14]]
            tbl = Table(tbl_data, colWidths=col_ws, repeatRows=1)
            ts = [("BACKGROUND",(0,0),(-1,0), HexColor(C_NAVY)),
                  ("GRID",(0,0),(-1,-1),0.4, HexColor(C_BORDER)),
                  ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
                  ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]
            for i in range(1, len(tbl_data)):
                if i % 2 == 0:
                    ts.append(("BACKGROUND",(0,i),(-1,i), HexColor(C_ALT)))
            tbl.setStyle(ts)
            story.append(tbl)

    story += _formula_block(
        r"\hat{V}_t = V_0 \prod_{i=1}^{t}(1 + r_i), \quad r_i \sim \mathcal{N}(\mu, \Sigma)",
        "Monte Carlo path simulation (geometric Brownian motion approximation)",
        eq_num, styles, text_w)
    return story


# ── Main entry point ─────────────────────────────────────────────────────────────

def build_pdf(req_data: dict) -> bytes:
    """Generate the full academic PDF report. Returns raw PDF bytes."""
    from reportlab.platypus import SimpleDocTemplate, Spacer, PageBreak
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor

    weights  = req_data.get("weights", {})
    metrics  = req_data.get("analytics", {}).get("metrics", {})
    method   = req_data.get("method", "unknown")
    tickers  = list(weights.keys())
    settings = req_data.get("settings", {})
    desc     = req_data.get("descriptive_stats", {})
    charts   = req_data.get("charts", {})

    # Fetch AI text (with timeout / fallback)
    ai = _get_gemini_text(metrics, weights, method, tickers, settings, desc)

    styles = _make_styles()
    PAGE_W, PAGE_H = A4
    L = R = 2.0 * cm
    T = B = 2.2 * cm
    TEXT_W = PAGE_W - L - R

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=L, rightMargin=R, topMargin=T, bottomMargin=B,
        title="PortOpt Portfolio Analysis Report",
        author="PortOpt",
    )

    def _page_cb(canvas, doc):
        canvas.saveState()
        pn = canvas._pageNumber
        # Footer
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(HexColor(C_MUTED))
        canvas.drawCentredString(
            PAGE_W / 2, B * 0.45,
            f"Page {pn}  —  PortOpt Portfolio Analysis Report  —  {datetime.now().strftime('%Y-%m-%d')}",
        )
        # Header line (not on cover)
        if pn > 1:
            canvas.setStrokeColor(HexColor(C_BORDER))
            canvas.line(L, PAGE_H - T * 0.75, PAGE_W - R, PAGE_H - T * 0.75)
            canvas.setFont("Helvetica-Bold", 7.5)
            canvas.setFillColor(HexColor(C_NAVY))
            canvas.drawString(L, PAGE_H - T * 0.55, "PortOpt")
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(HexColor(C_MUTED))
            canvas.drawRightString(PAGE_W - R, PAGE_H - T * 0.55,
                                   METHOD_NAMES.get(method, method))
        canvas.restoreState()

    # Shared mutable counters
    fig_num = [0]   # [current figure number]
    eq_num  = [0]   # [current equation number]

    story = []
    story += _build_cover(req_data, styles, TEXT_W)
    story.append(PageBreak())

    story += _build_abstract(req_data, ai, styles, TEXT_W)
    story.append(PageBreak())

    story += _build_overview(req_data, ai, styles, charts, fig_num, eq_num, TEXT_W)
    story.append(PageBreak())

    story += _build_performance(req_data, ai, styles, charts, fig_num, eq_num, TEXT_W)
    story.append(PageBreak())

    story += _build_risk(req_data, ai, styles, charts, fig_num, eq_num, TEXT_W)
    story.append(PageBreak())

    story += _build_statistics(req_data, ai, styles, eq_num, TEXT_W)
    story.append(PageBreak())

    story += _build_method(req_data, ai, styles, charts, fig_num, eq_num, TEXT_W)
    story.append(PageBreak())

    story += _build_scenarios(req_data, ai, styles, charts, fig_num, eq_num, TEXT_W)

    doc.build(story, onFirstPage=_page_cb, onLaterPages=_page_cb)
    return buf.getvalue()
