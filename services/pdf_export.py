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

METHOD_DESCRIPTIONS = {
    "max_sharpe":      "Maximum Sharpe Ratio maximises return per unit of risk, seeking the most efficient point on the efficient frontier where the reward-to-risk trade-off is highest.",
    "min_volatility":  "Minimum Volatility targets the lowest possible portfolio variance, prioritising capital preservation by minimising exposure to market fluctuations.",
    "black_litterman": "Black-Litterman blends market equilibrium returns with investor views, producing more intuitive and stable allocations than raw mean-variance optimisation.",
    "risk_parity":     "Risk Parity (Equal Risk Contribution) ensures each asset contributes the same amount of risk to the portfolio, promoting balanced diversification across all holdings.",
    "hrp":             "Hierarchical Risk Parity uses machine-learning clustering to group correlated assets before allocating inversely to their volatility, creating robust diversification.",
    "equal_weight":    "Equal Weight (1/N) distributes capital evenly across all assets. It requires no return forecasts and has historically outperformed many complex models out-of-sample.",
    "max_return":      "Maximum Return concentrates allocation toward the highest expected-return assets subject to weight constraints. Suitable for investors with high risk tolerance.",
    "custom":          "Custom Weights reflect user-defined allocation preferences, normalised to sum to 100%. Results show how the chosen weights perform on historical and risk metrics.",
}


# ── Gemini AI text ───────────────────────────────────────────────────────────────

def _get_gemini_text(metrics: dict, weights: dict, method: str,
                     tickers: list, settings: dict, desc_stats: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return _default_ai_text(method, metrics)

    prompt = f"""You are a senior investment analyst writing a professional portfolio report for an investor client.
The tone should be clear, confident, and written in plain English — like a letter from a fund manager to their investors.
Avoid jargon, equations, or academic language. Focus on what the numbers mean for the investor.

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

Write investor-friendly analysis in JSON with these exact keys:
{{
  "abstract": "150-180 word executive summary: what this portfolio is, how it was built, what the key numbers tell an investor, and the bottom-line assessment of its quality",
  "overview": "80-100 word plain-English summary of how capital is distributed, which positions dominate, and what the overall return/risk profile implies for an investor",
  "overview_insight": "One punchy sentence (max 25 words) starting with a verb — the single most important takeaway from the portfolio composition for an investor",
  "performance": "80-100 word investor-friendly commentary on return history, worst drawdown experienced, win rate, and how consistently the portfolio has delivered",
  "performance_insight": "One punchy sentence (max 25 words) starting with a verb — the single most important takeaway from the performance data",
  "risk": "80-100 word plain-English explanation of the key risks: how bad a bad day could get (VaR/CVaR), how closely it tracks the market (beta), and whether the manager adds value above the index (alpha)",
  "risk_insight": "One punchy sentence (max 25 words) starting with a verb — the single most important takeaway from the risk profile",
  "statistics": "80-100 word investor-friendly discussion: are individual stock returns normally distributed or do they have fat tails / skew? What does this mean for estimating risk?",
  "statistics_insight": "One punchy sentence (max 25 words) starting with a verb — the key implication of the distribution shape for the investor",
  "method": "80-100 word plain-English explanation of why the {METHOD_NAMES.get(method, method)} approach was used, what problem it solves, and how the resulting weights reflect that goal",
  "method_insight": "One punchy sentence (max 25 words) starting with a verb — the key advantage this method offers over simpler alternatives",
  "scenarios": "80-100 word investor-friendly forward-looking commentary: what the Monte Carlo fan chart tells us about upside/downside range, and how the portfolio held up in historical crises",
  "scenarios_insight": "One punchy sentence (max 25 words) starting with a verb — the key resilience or vulnerability revealed by the stress tests"
}}

Reference actual numbers from the data. Write every section as if explaining to an intelligent investor who is not a quant.
Return only valid JSON."""

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
    m   = METHOD_NAMES.get(method, method)
    ret = metrics.get("expected_return", 0) or 0
    vol = metrics.get("volatility", 0) or 0
    sr  = metrics.get("sharpe_ratio", 0) or 0
    mdd = metrics.get("max_drawdown", 0) or 0
    beta = metrics.get("beta", 0) or 0
    alpha = metrics.get("alpha", 0) or 0
    wr  = metrics.get("win_rate", 0) or 0
    var = metrics.get("var_95_daily", 0) or 0
    desc = METHOD_DESCRIPTIONS.get(method, f"The {m} method was used to construct this portfolio.")
    sr_quality = "strong" if sr > 1.0 else ("solid" if sr > 0.5 else "modest")
    mdd_desc = "relatively contained" if abs(mdd) < 20 else ("significant" if abs(mdd) < 40 else "severe")
    return {
        "abstract": (
            f"This portfolio was built using the {m} approach and targets an expected annual return "
            f"of {ret:.1f}% with annual volatility of {vol:.1f}%. The Sharpe ratio of {sr:.2f} "
            f"reflects {sr_quality} risk-adjusted performance — for every unit of risk taken, "
            f"the portfolio has historically delivered {sr:.2f} units of excess return. "
            f"The worst peak-to-trough decline over the period was {abs(mdd):.1f}%, which is "
            f"{mdd_desc} for an equity portfolio. With a market beta of {beta:.2f} and an alpha "
            f"of {alpha:.1f}%, the portfolio {'outperforms' if alpha > 0 else 'underperforms'} "
            f"passive index exposure on a risk-adjusted basis. Overall, the portfolio offers a "
            f"{'compelling' if sr > 1 else 'reasonable'} balance of return and risk for the "
            f"assets and time period selected."
        ),
        "overview": (
            f"The portfolio targets {ret:.1f}% annualised returns at {vol:.1f}% volatility, "
            f"giving a Sharpe ratio of {sr:.2f}. The {m} method was used to determine weights, "
            f"selecting the combination of assets that best meets the chosen objective. "
            f"The allocation reflects the relative attractiveness and correlation structure "
            f"of the underlying holdings over the analysis period."
        ),
        "overview_insight": (
            f"The {sr_quality} Sharpe ratio of {sr:.2f} suggests this allocation earns "
            f"{'meaningful' if sr > 0.5 else 'limited'} compensation for the risk taken."
        ),
        "performance": (
            f"The portfolio delivered {ret:.1f}% expected annual returns with a maximum drawdown "
            f"of {abs(mdd):.1f}% — the worst losing streak an investor would have experienced. "
            f"Closing days were profitable {wr:.0f}% of the time. The Calmar ratio contextualises "
            f"return relative to that worst-case loss, and higher values indicate quicker recovery "
            f"from drawdowns."
        ),
        "performance_insight": (
            f"{'Winning' if wr > 55 else 'Losing'} on {wr:.0f}% of trading days, the portfolio "
            f"{'consistently compounded gains' if wr > 55 else 'faced frequent small losses offset by larger gains'}."
        ),
        "risk": (
            f"On a typical bad day (5% tail), this portfolio is expected to lose no more than "
            f"{abs(var):.2f}%. The market beta of {beta:.2f} means it moves roughly "
            f"{beta:.0%} as much as the S&P 500 — {'amplifying' if beta > 1 else 'dampening'} "
            f"broader market swings. An alpha of {alpha:.1f}% indicates the portfolio "
            f"{'adds value' if alpha > 0 else 'lags'} beyond what passive index exposure would deliver."
        ),
        "risk_insight": (
            f"{'Low beta of' if beta < 0.8 else 'Elevated beta of'} {beta:.2f} means this portfolio "
            f"{'buffers' if beta < 1 else 'amplifies'} S&P 500 moves."
        ),
        "statistics": (
            "The distribution of individual stock returns reveals how predictable each holding's "
            "behaviour is. Stocks with fat tails (high kurtosis) can deliver extreme surprises — "
            "in either direction — more often than a normal bell curve would suggest. Negative skew "
            "means losses tend to be sharper than gains, which matters for risk budgeting. "
            "The Jarque-Bera test flags which holdings deviate most from normal behaviour."
        ),
        "statistics_insight": (
            "Fat-tailed holdings require larger risk buffers — standard deviation alone understates "
            "their true downside potential."
        ),
        "method": (
            f"{desc} "
            f"In practice, this means the weight assigned to each asset was determined by a "
            f"disciplined, data-driven process rather than subjective judgement, reducing the "
            f"risk of concentration in a single idea."
        ),
        "method_insight": (
            f"Using {m} removes allocation guesswork and grounds every weight in historical "
            f"data and a clear risk objective."
        ),
        "scenarios": (
            "The Monte Carlo simulation shows the range of outcomes an investor might realistically "
            "experience over time — not a single forecast but a distribution of possibilities. "
            "The stress tests apply the current weights to periods like the 2008 financial crisis "
            "and the 2020 COVID crash, revealing how the portfolio would have held up under "
            "extreme market conditions."
        ),
        "scenarios_insight": (
            "Stress-test results reveal whether historical crisis periods would have been "
            "survivable without forcing a panic sale."
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
        "insight_label": ps("il",  fontName="Helvetica-Bold", fontSize=7,
                             textColor=HexColor(C_BLUE), spaceAfter=2),
        "insight_body":  ps("ib",  fontName="Helvetica-Oblique", fontSize=9,
                             textColor=HexColor(C_NAVY), leading=13, spaceAfter=0),
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



def _insight_box(text: str, styles: dict) -> list:
    """Render a highlighted investor insight callout."""
    from reportlab.platypus import Paragraph, Table, TableStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import cm
    label = Paragraph('<b>KEY INSIGHT</b>', styles["insight_label"])
    body  = Paragraph(text, styles["insight_body"])
    tbl = Table([[label], [body]], colWidths=None)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), HexColor("#eef4fd")),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LINEBEFORE",   (0, 0), (0, -1),  3, HexColor(C_BLUE)),
    ]))
    return [tbl]


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
                    fig_num: list, text_w: float) -> list:
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

    story += _insight_box(ai.get("overview_insight", ""), styles)
    return story


def _build_performance(req: dict, ai: dict, styles: dict, charts: dict,
                       fig_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Spacer
    metrics = req.get("analytics", {}).get("metrics", {})
    story   = _section_heading(2, "Historical Performance", styles)
    story  += [Paragraph(ai.get("performance", ""), styles["body"])]
    story += _embed_chart(_decode_chart(charts.get("chart-returns")), fig_num,
        "Cumulative returns: each asset normalised to $1 at the start date "
        "(bold line = portfolio blend; dashed = SPY benchmark).",
        styles, text_w, 0.36)
    story += _embed_chart(_decode_chart(charts.get("chart-drawdown")), fig_num,
        "Portfolio drawdown — percentage decline from the most recent peak at each date. "
        f"Maximum observed drawdown: {metrics.get('max_drawdown', 0):.2f}%.",
        styles, text_w, 0.28)
    story += _embed_chart(_decode_chart(charts.get("chart-rolling")), fig_num,
        "Rolling 60-day volatility (blue, left axis) and Sharpe ratio (gold, right axis) "
        "through the analysis period.",
        styles, text_w, 0.32)

    story += _insight_box(ai.get("performance_insight", ""), styles)
    return story


def _build_risk(req: dict, ai: dict, styles: dict, charts: dict,
                fig_num: list, text_w: float) -> list:
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

    story += _insight_box(ai.get("risk_insight", ""), styles)
    return story


def _build_statistics(req: dict, ai: dict, styles: dict,
                      text_w: float) -> list:
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

    story += _insight_box(ai.get("statistics_insight", ""), styles)
    return story


def _build_method(req: dict, ai: dict, styles: dict, charts: dict,
                  fig_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph
    method = req.get("method", "unknown")
    story  = _section_heading(5, f"Optimization Method: {METHOD_NAMES.get(method, method)}", styles)
    story += [Paragraph(ai.get("method", ""), styles["body"])]

    # Method-specific charts
    if method == "black_litterman":
        story += _embed_chart(_decode_chart(charts.get("chart-bl-step1")), fig_num,
            "Step 1: Market-implied equilibrium returns (CAPM prior — market weights).",
            styles, text_w, 0.40)
        story += _embed_chart(_decode_chart(charts.get("chart-bl-step5")), fig_num,
            "Step 5: Prior (blue) vs posterior (gold) expected returns after blending investor views.",
            styles, text_w, 0.40)
    elif method == "hrp":
        story += _embed_chart(_decode_chart(charts.get("chart-hrp-step3")), fig_num,
            "Step 3: Asset risk contributions after hierarchical clustering allocation.",
            styles, text_w, 0.40)

    story += _insight_box(ai.get("method_insight", ""), styles)
    return story


def _build_scenarios(req: dict, ai: dict, styles: dict, charts: dict,
                     fig_num: list, text_w: float) -> list:
    from reportlab.platypus import Paragraph, Table
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
        hdr = ["Scenario", "Period", "Portfolio", "SPY", "Δ vs SPY"]
        tbl_data = [[Paragraph(h, styles["tbl_head"]) for h in hdr]]
        for _key, sc in scenarios.items():
            if sc.get("error"):
                continue
            p_ret = sc.get("portfolio_return", 0) or 0
            s_ret = sc.get("spy_return")
            delta = (p_ret - s_ret) if s_ret is not None else None
            sty_p = styles["tbl_cell_g"] if p_ret > 0 else styles["tbl_cell_r"]
            sty_d = styles["tbl_cell_g"] if (delta or 0) > 0 else styles["tbl_cell_r"]
            tbl_data.append([
                Paragraph(sc.get("name",""), styles["tbl_cell"]),
                Paragraph(sc.get("period",""), styles["tbl_cell"]),
                Paragraph(f"{p_ret:.1f}%", sty_p),
                Paragraph(f"{s_ret:.1f}%" if s_ret is not None else "—", styles["tbl_cell"]),
                Paragraph(f"{delta:+.1f}%" if delta is not None else "—", sty_d),
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

    story += _insight_box(ai.get("scenarios_insight", ""), styles)
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

    fig_num = [0]   # [current figure number]

    story = []
    story += _build_cover(req_data, styles, TEXT_W)
    story.append(PageBreak())

    story += _build_abstract(req_data, ai, styles, TEXT_W)
    story.append(PageBreak())

    story += _build_overview(req_data, ai, styles, charts, fig_num, TEXT_W)
    story.append(PageBreak())

    story += _build_performance(req_data, ai, styles, charts, fig_num, TEXT_W)
    story.append(PageBreak())

    story += _build_risk(req_data, ai, styles, charts, fig_num, TEXT_W)
    story.append(PageBreak())

    story += _build_statistics(req_data, ai, styles, TEXT_W)
    story.append(PageBreak())

    story += _build_method(req_data, ai, styles, charts, fig_num, TEXT_W)
    story.append(PageBreak())

    story += _build_scenarios(req_data, ai, styles, charts, fig_num, TEXT_W)

    doc.build(story, onFirstPage=_page_cb, onLaterPages=_page_cb)
    return buf.getvalue()
