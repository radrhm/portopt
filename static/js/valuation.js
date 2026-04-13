/* ═══════════════════════════════════════════════════════════════
   valuation.js — Equity Valuation module
   All calculations are client-side for instant re-calc.
   Only the financial data fetch hits the server.
   ═══════════════════════════════════════════════════════════════ */

// ── App-level switcher ────────────────────────────────────────────────────────

function switchApp(mode) {
  const isValuation = mode === 'valuation';

  // Header nav
  document.getElementById('nav-portfolio').classList.toggle('active', !isValuation);
  document.getElementById('nav-valuation').classList.toggle('active', isValuation);

  // Show/hide portfolio panels (aside + main share the grid)
  document.querySelector('aside').style.display          = isValuation ? 'none' : '';
  document.querySelector('main').style.display           = isValuation ? 'none' : '';
  document.querySelector('.app-tabs-row').style.display  = isValuation ? 'none' : '';

  // Show/hide valuation app
  document.getElementById('valuation-app').style.display = isValuation ? 'block' : 'none';
}

// ── State ─────────────────────────────────────────────────────────────────────

let _vData = null;   // raw financials from server

// ── Load financials ───────────────────────────────────────────────────────────

async function loadValuation() {
  const ticker = document.getElementById('val-ticker-input').value.trim().toUpperCase();
  if (!ticker) { setValStatus('Please enter a ticker symbol.', true); return; }

  setValStatus('');
  document.getElementById('val-results').style.display = 'none';
  document.getElementById('val-loading').style.display = 'block';
  document.getElementById('val-search-btn').disabled   = true;

  try {
    const res  = await fetch(`/api/valuation/financials?ticker=${encodeURIComponent(ticker)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to fetch financials.');

    _vData = data;
    populateInputs(data);
    renderHeader(data);
    recalcAll();
    document.getElementById('val-results').style.display = 'block';
    setValStatus('');
  } catch (e) {
    setValStatus(e.message, true);
  } finally {
    document.getElementById('val-loading').style.display = 'none';
    document.getElementById('val-search-btn').disabled   = false;
  }
}

function setValStatus(msg, isErr) {
  const el = document.getElementById('val-status');
  el.textContent  = msg;
  el.style.color  = isErr ? 'var(--red)' : 'var(--muted)';
}

// ── Populate inputs from server data ─────────────────────────────────────────

function populateInputs(d) {
  // DCF
  setVal('dcf-fcf',   d.fcf_per_share);
  setVal('dcf-g1',    Math.min(d.earnings_growth_pct, 40));
  setVal('dcf-g2',    Math.min(d.earnings_growth_pct * 0.6, 25).toFixed(1));
  setVal('dcf-tg',    2.5);
  setVal('dcf-wacc',  d.wacc_suggestion);
  setVal('dcf-mos',   15);

  // DDM
  setVal('ddm-div', d.dividend_annual);
  setVal('ddm-g',   Math.min(d.earnings_growth_pct * 0.5, 8).toFixed(1));
  setVal('ddm-r',   d.wacc_suggestion);
  const noDivEl   = document.getElementById('ddm-no-div');
  const ddmInpEl  = document.getElementById('ddm-inputs');
  if (!d.dividend_annual || d.dividend_annual <= 0) {
    noDivEl.style.display  = 'block';
    ddmInpEl.style.display = 'none';
  } else {
    noDivEl.style.display  = 'none';
    ddmInpEl.style.display = 'block';
  }

  // P/E
  setVal('pe-eps-ttm', d.eps_ttm);
  setVal('pe-eps-fwd', d.eps_forward);
  setVal('pe-mult-ttm', d.sector_pe);
  setVal('pe-mult-fwd', Math.max(d.sector_pe - 2, 10).toFixed(1));

  // EV/EBITDA
  setVal('ev-ebitda',   d.ebitda_m);
  setVal('ev-mult',     d.ev_multiple_suggestion);
  setVal('ev-netdebt',  d.net_debt_m);
  setVal('ev-shares',   d.shares_outstanding_m);

  // Graham
  setVal('gr-eps',  d.eps_ttm);
  setVal('gr-bvps', d.book_value_ps);

  // PEG
  setVal('peg-eps',    d.eps_ttm);
  setVal('peg-g',      d.earnings_growth_pct);
  setVal('peg-target', 1.0);
}

function setVal(id, v) {
  const el = document.getElementById(id);
  if (el) el.value = (v === null || v === undefined || isNaN(v)) ? '' : v;
}

function getVal(id, fallback = 0) {
  const el = document.getElementById(id);
  const v  = parseFloat(el ? el.value : '');
  return isNaN(v) ? fallback : v;
}

// ── Render stock header ───────────────────────────────────────────────────────

function renderHeader(d) {
  document.getElementById('val-name').textContent =
    `${d.ticker}  —  ${d.name}`;
  document.getElementById('val-meta').textContent =
    `${d.sector}  ·  ${d.industry}  ·  Mkt Cap: ${d.market_cap_fmt}  ·  Beta: ${d.beta}`;
  document.getElementById('val-price').textContent =
    fmtPrice(d.current_price, d.currency);
}

// ── Recalculate all methods ───────────────────────────────────────────────────

function recalcAll() {
  if (!_vData) return;
  const price    = _vData.current_price;
  const currency = _vData.currency;

  const results = {};

  // DCF
  results.dcf = calcDCF();
  setResult('res-dcf', results.dcf, currency);
  setUpDown('ud-dcf', results.dcf, price);

  // DDM
  results.ddm = calcDDM();
  setResult('res-ddm', results.ddm, currency);
  setUpDown('ud-ddm', results.ddm, price);

  // P/E
  const peTtm = calcPE(getVal('pe-eps-ttm'), getVal('pe-mult-ttm'));
  const peFwd = calcPE(getVal('pe-eps-fwd'), getVal('pe-mult-fwd'));
  results.pe  = (peTtm && peFwd) ? (peTtm + peFwd) / 2 : (peTtm || peFwd);
  document.getElementById('res-pe-ttm').textContent = peTtm ? fmtPrice(peTtm, currency) : '—';
  document.getElementById('res-pe-fwd').textContent = peFwd ? fmtPrice(peFwd, currency) : '—';
  setResult('res-pe', results.pe, currency);
  setUpDown('ud-pe', results.pe, price);

  // EV/EBITDA
  results.ev = calcEV();
  setResult('res-ev', results.ev, currency);
  setUpDown('ud-ev', results.ev, price);

  // Graham
  results.graham = calcGraham();
  const grahamNa = document.getElementById('graham-na');
  grahamNa.style.display = results.graham ? 'none' : 'block';
  setResult('res-graham', results.graham, currency);
  setUpDown('ud-graham', results.graham, price);

  // PEG
  results.peg = calcPEG();
  setResult('res-peg', results.peg, currency);
  setUpDown('ud-peg', results.peg, price);

  // Update comparison chart
  renderCompareChart(results, price, currency);
}

// ── Individual calculation functions ─────────────────────────────────────────

function calcDCF() {
  const fcf  = getVal('dcf-fcf');
  const g1   = getVal('dcf-g1')   / 100;
  const g2   = getVal('dcf-g2')   / 100;
  const tg   = getVal('dcf-tg')   / 100;
  const wacc = getVal('dcf-wacc') / 100;
  const mos  = getVal('dcf-mos')  / 100;

  if (!fcf || wacc <= tg || wacc <= 0) return null;

  let pv = 0;
  let cf = fcf;
  for (let y = 1; y <= 5; y++) {
    cf *= (1 + g1);
    pv += cf / Math.pow(1 + wacc, y);
  }
  for (let y = 6; y <= 10; y++) {
    cf *= (1 + g2);
    pv += cf / Math.pow(1 + wacc, y);
  }
  // Terminal value (Gordon Growth)
  const terminalCF = cf * (1 + tg);
  const tv = terminalCF / (wacc - tg);
  pv += tv / Math.pow(1 + wacc, 10);

  return pv > 0 ? round2(pv * (1 - mos)) : null;
}

function calcDDM() {
  const div  = getVal('ddm-div');
  const g    = getVal('ddm-g') / 100;
  const r    = getVal('ddm-r') / 100;
  if (!div || div <= 0 || r <= g || r <= 0) return null;
  const nextDiv = div * (1 + g);
  return round2(nextDiv / (r - g));
}

function calcPE(eps, mult) {
  if (!eps || eps <= 0 || !mult || mult <= 0) return null;
  return round2(eps * mult);
}

function calcEV() {
  const ebitda  = getVal('ev-ebitda');   // $M
  const mult    = getVal('ev-mult');
  const netdebt = getVal('ev-netdebt'); // $M
  const shares  = getVal('ev-shares');  // M shares
  if (!ebitda || !mult || !shares || shares <= 0) return null;
  const evTarget   = ebitda * mult;              // $M
  const equityVal  = evTarget - netdebt;         // $M
  const perShare   = (equityVal * 1e6) / (shares * 1e6);
  return perShare > 0 ? round2(perShare) : null;
}

function calcGraham() {
  const eps  = getVal('gr-eps');
  const bvps = getVal('gr-bvps');
  if (!eps || eps <= 0 || !bvps || bvps <= 0) return null;
  return round2(Math.sqrt(22.5 * eps * bvps));
}

function calcPEG() {
  const eps    = getVal('peg-eps');
  const g      = getVal('peg-g');
  const target = getVal('peg-target', 1.0);
  if (!eps || eps <= 0 || !g || g <= 0) return null;
  // Fair value = EPS × (growth rate × target PEG)
  return round2(eps * g * target);
}

// ── Render comparison bar chart ───────────────────────────────────────────────

function renderCompareChart(results, price, currency) {
  const labelMap = {
    dcf:    'DCF',
    ddm:    'DDM',
    pe:     'P/E (avg)',
    ev:     'EV/EBITDA',
    graham: 'Graham',
    peg:    'PEG',
  };

  const labels = [], values = [], colors = [];
  for (const [key, val] of Object.entries(results)) {
    if (!val) continue;
    labels.push(labelMap[key] || key);
    values.push(val);
    colors.push(val >= price ? '#10b981' : '#ef4444');
  }

  if (!labels.length) return;

  const trace = {
    type: 'bar',
    x: labels,
    y: values,
    marker: { color: colors, opacity: 0.85 },
    text: values.map(v => fmtPrice(v, currency)),
    textposition: 'outside',
    textfont: { size: 11, color: '#e2e8f0' },
    cliponaxis: false,
  };

  const priceLine = {
    type: 'scatter',
    x: labels,
    y: Array(labels.length).fill(price),
    mode: 'lines',
    line: { color: '#ef4444', width: 2, dash: 'dot' },
    name: `Market Price (${fmtPrice(price, currency)})`,
  };

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    font:  { color: '#94a3b8', size: 11 },
    margin: { t: 30, r: 20, b: 40, l: 60 },
    xaxis: { gridcolor: '#263348', zerolinecolor: '#263348', fixedrange: true },
    yaxis: {
      gridcolor: '#263348', zerolinecolor: '#263348', fixedrange: true,
      tickprefix: currency === 'USD' ? '$' : '',
    },
    showlegend: true,
    legend: { orientation: 'h', y: -0.15, x: 0.5, xanchor: 'center',
              font: { size: 11 }, bgcolor: 'transparent' },
    shapes: [{
      type: 'line', xref: 'paper', x0: 0, x1: 1,
      y0: price, y1: price,
      line: { color: '#ef4444', width: 1.5, dash: 'dot' },
    }],
  };

  Plotly.react('val-chart-compare', [trace, priceLine], layout,
    { displayModeBar: false, responsive: true });
}

// ── Helper: set result display ────────────────────────────────────────────────

function setResult(id, val, currency) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!val) { el.textContent = 'N/A'; el.style.color = 'var(--muted)'; return; }
  el.textContent  = fmtPrice(val, currency);
  el.style.color  = 'var(--accent2)';
}

function setUpDown(id, intrinsic, price) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!intrinsic || !price) {
    el.textContent = '';
    el.className   = 'val-updown neutral';
    return;
  }
  const pct   = ((intrinsic - price) / price) * 100;
  const up    = pct >= 0;
  const arrow = up ? '▲' : '▼';
  el.className   = `val-updown ${up ? 'up' : 'down'}`;
  el.innerHTML   = `${arrow} ${Math.abs(pct).toFixed(1)}% ${up ? 'upside' : 'downside'} — `
                 + `Intrinsic value ${fmtPrice(intrinsic, _vData?.currency || 'USD')} `
                 + `vs market price ${fmtPrice(price, _vData?.currency || 'USD')}`;
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function fmtPrice(v, currency) {
  if (!v && v !== 0) return '—';
  const sym = (currency && currency !== 'USD') ? currency + ' ' : '$';
  return sym + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function round2(v) {
  return Math.round(v * 100) / 100;
}
