/* ═══════════════════════════════════════════════════════════════
   valuation.js  —  Equity Valuation module
   Multi-tab, 9 models in 4 categories, math workings panel.
   All calculations client-side; only data fetch hits the server.
   ═══════════════════════════════════════════════════════════════ */

// ── State: map tickerKey → { data, id } ──────────────────────────────────────
const _vStocks = {};   // { AAPL: { data: {...}, id: 'vs-AAPL' }, ... }
let   _vActive = null; // currently shown ticker key

// ── Lists state ───────────────────────────────────────────────────────────────
let _vLists    = [];   // [{id, name, tickers:[{ticker,name,price}]}]
let _vAtlTicker = null; // ticker for which the Add-to-List dropdown is open

// ── Add stock ─────────────────────────────────────────────────────────────────

async function valAddStock() {
  const raw    = document.getElementById('val-ticker-input').value.trim().toUpperCase();
  const ticker = raw.replace(/[^A-Z0-9.\-]/g, '');
  const statusEl = document.getElementById('val-status');
  if (!ticker) { statusEl.textContent = 'Enter a ticker.'; return; }
  if (_vStocks[ticker]) { valSwitchTab(ticker); return; }

  statusEl.textContent = '';
  document.getElementById('val-ticker-input').value = '';

  // Create a loading tab immediately
  _vStocks[ticker] = { data: null, id: `vs-${ticker}` };
  _renderTab(ticker, null, true);
  valSwitchTab(ticker);

  try {
    const res  = await fetch(`/api/valuation/financials?ticker=${encodeURIComponent(ticker)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Fetch failed.');
    _vStocks[ticker].data = data;
    _renderTab(ticker, data, false);
    _renderStockPanel(ticker, data);
    valSwitchTab(ticker);
  } catch (e) {
    statusEl.textContent = e.message;
    _removeTab(ticker);
  }
}

// ── Tab management ────────────────────────────────────────────────────────────

function valSwitchTab(ticker) {
  _vActive = ticker;
  // Deactivate all tabs & panels
  document.querySelectorAll('.val-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.val-stock-panel').forEach(p => p.classList.remove('active'));
  // Activate target
  const tabEl   = document.getElementById(`vtab-${ticker}`);
  const panelEl = document.getElementById(`vs-${ticker}`);
  if (tabEl)   tabEl.classList.add('active');
  if (panelEl) panelEl.classList.add('active');
  // Hide empty state
  document.getElementById('val-empty-state').style.display =
    Object.keys(_vStocks).length ? 'none' : 'block';
}

function _removeTab(ticker) {
  delete _vStocks[ticker];
  document.getElementById(`vtab-${ticker}`)?.remove();
  document.getElementById(`vs-${ticker}`)?.remove();
  const remaining = Object.keys(_vStocks);
  if (remaining.length) valSwitchTab(remaining[remaining.length - 1]);
  else document.getElementById('val-empty-state').style.display = 'block';
}

function _renderTab(ticker, data, loading) {
  const container = document.getElementById('val-tabs-container');
  let tab = document.getElementById(`vtab-${ticker}`);
  if (!tab) {
    tab = document.createElement('button');
    tab.className = 'val-tab';
    tab.id        = `vtab-${ticker}`;
    tab.onclick   = () => valSwitchTab(ticker);
    container.appendChild(tab);
  }
  const price = data ? _fp(data.current_price, data.currency) : '';
  tab.innerHTML = `
    ${loading ? `<span class="val-tab-loading"></span>` : ''}
    <span class="val-tab-ticker">${ticker}</span>
    ${price ? `<span class="val-tab-price">${price}</span>` : ''}
    <button class="val-tab-close" onclick="event.stopPropagation();_removeTab('${ticker}')" title="Close">×</button>`;
}

// ── Render stock panel ────────────────────────────────────────────────────────

function _renderStockPanel(ticker, d) {
  const container = document.getElementById('val-stocks-container');
  // Remove old panel if exists
  document.getElementById(`vs-${ticker}`)?.remove();

  const panel = document.createElement('div');
  panel.className = 'val-stock-panel';
  panel.id        = `vs-${ticker}`;

  panel.innerHTML = `
    ${_stockHeaderHTML(d)}
    <div class="val-compare-card">
      <div class="chart-header" style="margin-bottom:6px;">
        <div class="chart-title" style="margin:0;font-size:12px;">Intrinsic Value vs Market Price</div>
        <div style="font-size:10px;color:var(--muted);">Red line = current price ${_fp(d.current_price, d.currency)}</div>
      </div>
      <div id="val-chart-${ticker}" style="height:200px;"></div>
    </div>
    ${_categoriesHTML(ticker, d)}`;

  container.appendChild(panel);

  // Bind all inputs to recalc
  panel.querySelectorAll('input[type=number]').forEach(inp => {
    inp.addEventListener('input', () => _recalcTicker(ticker));
  });

  // Initial calc
  _recalcTicker(ticker);
}

function _stockHeaderHTML(d) {
  const upChip = d.beta > 1.2
    ? `<span class="val-chip red">β ${d.beta} High</span>`
    : d.beta < 0.8
    ? `<span class="val-chip green">β ${d.beta} Low</span>`
    : `<span class="val-chip">β ${d.beta}</span>`;
  return `
  <div class="val-stock-header">
    <div>
      <div style="display:flex;align-items:baseline;gap:10px;">
        <span class="val-stock-ticker">${d.ticker}</span>
        <span style="font-size:11px;color:var(--muted);">${d.currency}</span>
      </div>
      <div class="val-stock-name">${d.name}</div>
      <div class="val-stock-chips" style="margin-top:6px;">
        <span class="val-chip">${d.sector}</span>
        <span class="val-chip">${d.industry}</span>
        <span class="val-chip">Mkt Cap ${d.market_cap_fmt}</span>
        ${upChip}
        ${d.pe_ttm ? `<span class="val-chip">P/E ${d.pe_ttm}×</span>` : ''}
        ${d.ev_ebitda_current ? `<span class="val-chip">EV/EBITDA ${d.ev_ebitda_current}×</span>` : ''}
        ${d.dividend_annual ? `<span class="val-chip green">Div $${d.dividend_annual} (${d.dividend_yield.toFixed(1)}%)</span>` : '<span class="val-chip">No Dividend</span>'}
      </div>
    </div>
    <div style="text-align:right;flex-shrink:0;display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
      <div>
        <div class="val-stock-price">${_fp(d.current_price, d.currency)}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:2px;">Current Market Price</div>
      </div>
      <button class="val-save-list-btn" onclick="valShowAddToList('${d.ticker}')">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
        Save to List ▾
      </button>
    </div>
  </div>`;
}

// ── Categories & model HTML ───────────────────────────────────────────────────

function _categoriesHTML(tk, d) {
  const s = d.shares_m;  // pre-fill shares for all models

  return `
  <!-- CATEGORY 1: Intrinsic Cash Flow -->
  <div class="val-category">
    <div class="val-category-title">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
      Cash Flow Models
    </div>
    <div class="val-methods-grid">
      ${_dcfCardHTML(tk, d)}
      ${_epvCardHTML(tk, d)}
    </div>
  </div>

  <!-- CATEGORY 2: Dividend -->
  <div class="val-category">
    <div class="val-category-title">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
      Dividend Models
    </div>
    <div class="val-methods-grid">
      ${_ddmCardHTML(tk, d)}
    </div>
  </div>

  <!-- CATEGORY 3: Relative / Multiples -->
  <div class="val-category">
    <div class="val-category-title">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
      Relative / Multiples Models
    </div>
    <div class="val-methods-grid">
      ${_peCardHTML(tk, d)}
      ${_evEbitdaCardHTML(tk, d)}
      ${_evEbitCardHTML(tk, d)}
      ${_psCardHTML(tk, d)}
      ${_pegCardHTML(tk, d)}
    </div>
  </div>

  <!-- CATEGORY 4: Asset-Based -->
  <div class="val-category">
    <div class="val-category-title">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6M9 12h6M9 15h4"/></svg>
      Asset-Based Models
    </div>
    <div class="val-methods-grid">
      ${_grahamCardHTML(tk, d)}
      ${_ncavCardHTML(tk, d)}
    </div>
  </div>`;
}

// ── Model card builders ───────────────────────────────────────────────────────

function _cardWrap(id, tk, title, subtitle, bodyHTML) {
  return `
  <div class="val-card" id="vcard-${tk}-${id}">
    <div class="val-card-header">
      <div>
        <div class="val-card-title">${title}</div>
        <div class="val-card-subtitle">${subtitle}</div>
      </div>
      <div class="val-card-result" id="res-${tk}-${id}">—</div>
    </div>
    <div class="val-card-body">
      ${bodyHTML}
      <div class="val-updown neutral" id="ud-${tk}-${id}"></div>
      <button class="val-workings-btn" onclick="toggleWorkings('${tk}','${id}')">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h20M12 2v20"/></svg>
        Show working
      </button>
      <div class="val-workings-panel" id="wp-${tk}-${id}"></div>
    </div>
  </div>`;
}

function _inp(id, label, val, hint, step='0.01', min='', max='') {
  const minA = min !== '' ? `min="${min}"` : '';
  const maxA = max !== '' ? `max="${max}"` : '';
  return `
  <div class="val-inp-group">
    <label>${label}</label>
    <input type="number" id="${id}" value="${val}" step="${step}" ${minA} ${maxA}/>
    <div class="val-inp-hint">${hint}</div>
  </div>`;
}

// 1. DCF ───────────────────────────────────────────────────────────────────────
function _dcfCardHTML(tk, d) {
  const g1  = Math.min(d.earnings_growth_pct, 40).toFixed(1);
  const g2  = Math.min(d.earnings_growth_pct * 0.6, 25).toFixed(1);
  const fcfHistory = d.historical_fcf.length
    ? `<table class="val-fcf-table">
        <thead><tr><th>Year</th><th>Op. Cash Flow ($M)</th><th>CapEx ($M)</th><th>FCF ($M)</th></tr></thead>
        <tbody>${d.historical_fcf.map(r => `
          <tr><td>${r.year}</td><td>${r.op_cf_m.toLocaleString()}</td>
          <td class="neg">${r.capex_m.toLocaleString()}</td>
          <td class="${r.fcf_m >= 0 ? 'pos' : 'neg'}">${r.fcf_m.toLocaleString()}</td></tr>`).join('')}
        </tbody></table>
        <div style="font-size:10px;color:var(--muted);margin-bottom:8px;">
          ℹ️ yfinance provides up to 4 years of annual cash flow data.
        </div>`
    : `<div class="val-note" style="margin-bottom:8px;">No historical cash flow data available.</div>`;

  const body = `
    ${fcfHistory}
    <div class="val-inputs-grid">
      ${_inp(`${tk}-dcf-fcf`,  'FCF — Latest Year ($M)', d.fcf_total_m,   'Total free cash flow, most recent year', '1')}
      ${_inp(`${tk}-dcf-mktcap`, 'Market Cap ($M)', d.market_cap_m, 'Current market capitalisation in millions', '10')}
      ${_inp(`${tk}-dcf-shares`, 'Shares Outstanding (M)', d.shares_m, 'Total diluted shares outstanding', '0.1', '0.001')}
      ${_inp(`${tk}-dcf-g1`,   'Growth Yr 1–5 (%)', g1,              'Expected annual FCF growth, first 5 years', '0.5', '-30', '80')}
      ${_inp(`${tk}-dcf-g2`,   'Growth Yr 6–10 (%)', g2,             'Slower growth phase, years 6–10', '0.5', '-20', '50')}
      ${_inp(`${tk}-dcf-tg`,   'Terminal Growth (%)', '2.5',          'Perpetual growth after yr 10 (≈ GDP)', '0.1', '0', '5')}
      ${_inp(`${tk}-dcf-wacc`, 'WACC (%)', d.wacc_suggestion,        'Weighted avg cost of capital (from beta)', '0.1', '3', '30')}
      ${_inp(`${tk}-dcf-mos`,  'Margin of Safety (%)', '15',          'Discount applied to final DCF value', '1', '0', '50')}
    </div>`;

  return _cardWrap('dcf', tk, 'Discounted Cash Flow (DCF)',
    '2-stage growth model: discount projected FCFs + terminal value back to today',
    body);
}

// 2. EPV ───────────────────────────────────────────────────────────────────────
function _epvCardHTML(tk, d) {
  const body = `
    <div class="val-inputs-grid">
      ${_inp(`${tk}-epv-ebit`,  'EBIT ($M)', d.ebit_m, 'Earnings before interest & tax', '1')}
      ${_inp(`${tk}-epv-tax`,   'Tax Rate (%)', d.tax_rate_pct, 'Effective corporate tax rate', '0.5', '0', '50')}
      ${_inp(`${tk}-epv-wacc`,  'WACC (%)', d.wacc_suggestion, 'Discount rate', '0.1', '3', '30')}
      ${_inp(`${tk}-epv-netdebt`, 'Net Debt ($M)', d.net_debt_m, 'Total debt minus cash', '1')}
      ${_inp(`${tk}-epv-shares`, 'Shares (M)', d.shares_m, 'Diluted shares outstanding', '0.1', '0.001')}
    </div>`;
  return _cardWrap('epv', tk, 'Earnings Power Value (EPV)',
    'Assumes no growth — values the business on current normalised earnings capacity only',
    body);
}

// 3. DDM ───────────────────────────────────────────────────────────────────────
function _ddmCardHTML(tk, d) {
  const noDivNote = (!d.dividend_annual || d.dividend_annual <= 0)
    ? `<div class="val-note" style="margin-bottom:8px;">⚠️ This stock pays no dividend. DDM is not applicable — result will be N/A.</div>`
    : '';
  const body = `
    ${noDivNote}
    <div class="val-inputs-grid col2">
      ${_inp(`${tk}-ddm-div`, 'Annual Dividend / Share ($)', d.dividend_annual || 0, 'Last declared annual dividend per share', '0.01', '0')}
      ${_inp(`${tk}-ddm-g`,   'Dividend Growth Rate (%)', Math.min(d.earnings_growth_pct * 0.4, 8).toFixed(1), 'Long-term expected annual dividend growth', '0.5', '0', '20')}
      ${_inp(`${tk}-ddm-r`,   'Required Return (%)', d.wacc_suggestion, 'Your minimum acceptable annual return (cost of equity)', '0.1', '1', '30')}
    </div>`;
  return _cardWrap('ddm', tk, 'Dividend Discount Model (DDM)',
    'Gordon Growth Model: P = D₁ ÷ (r − g) — present value of all future dividends',
    body);
}

// 4. P/E ───────────────────────────────────────────────────────────────────────
function _peCardHTML(tk, d) {
  const fwdPe = Math.max((d.sector_pe - 2), 10).toFixed(1);
  const body = `
    <div class="val-inputs-grid">
      ${_inp(`${tk}-pe-epsttm`, 'EPS TTM ($)', d.eps_ttm,    'Trailing twelve months earnings per share', '0.01')}
      ${_inp(`${tk}-pe-epsfwd`, 'EPS Forward ($)', d.eps_forward, 'Next twelve months consensus estimate', '0.01')}
      ${_inp(`${tk}-pe-multtm`, 'Target P/E (TTM)', d.sector_pe, 'Sector / historical fair P/E multiple', '0.5', '1')}
      ${_inp(`${tk}-pe-mulfwd`, 'Target P/E (Fwd)', fwdPe,   'Forward P/E to apply to next-year earnings', '0.5', '1')}
      ${_inp(`${tk}-pe-shares`, 'Shares (M)', d.shares_m, 'For reference — price is EPS × multiple', '0.1', '0.001')}
    </div>
    <div class="val-two-results">
      <div class="val-two-item"><span class="val-two-label">TTM P/E Fair Value</span><span class="val-card-result sml" id="res-${tk}-pe-ttm">—</span></div>
      <div class="val-two-item"><span class="val-two-label">Forward P/E Fair Value</span><span class="val-card-result sml" id="res-${tk}-pe-fwd">—</span></div>
    </div>`;
  return _cardWrap('pe', tk, 'Price / Earnings (P/E)',
    'Fair value = EPS × target multiple. Shown for both trailing and forward EPS.',
    body);
}

// 5. EV/EBITDA ─────────────────────────────────────────────────────────────────
function _evEbitdaCardHTML(tk, d) {
  const body = `
    <div class="val-inputs-grid">
      ${_inp(`${tk}-evda-ebitda`, 'EBITDA ($M)', d.ebitda_m, 'Earnings before interest, tax, D&A', '10')}
      ${_inp(`${tk}-evda-mult`,   'Target EV/EBITDA ×', d.sector_ev, 'Sector fair-value multiple', '0.5', '1')}
      ${_inp(`${tk}-evda-netdebt`, 'Net Debt ($M)', d.net_debt_m, 'Total debt minus cash', '10')}
      ${_inp(`${tk}-evda-shares`, 'Shares (M)', d.shares_m, 'To convert equity value to per share', '0.1', '0.001')}
    </div>`;
  return _cardWrap('evda', tk, 'EV / EBITDA',
    'Target EV = EBITDA × multiple → subtract net debt → divide by shares',
    body);
}

// 6. EV/EBIT ───────────────────────────────────────────────────────────────────
function _evEbitCardHTML(tk, d) {
  const ebitMult = d.sector_ev * 0.8;
  const body = `
    <div class="val-inputs-grid">
      ${_inp(`${tk}-eveb-ebit`,   'EBIT ($M)', d.ebit_m, 'Operating profit (before interest & tax)', '1')}
      ${_inp(`${tk}-eveb-mult`,   'Target EV/EBIT ×', ebitMult.toFixed(1), 'Sector fair-value EV/EBIT multiple', '0.5', '1')}
      ${_inp(`${tk}-eveb-netdebt`, 'Net Debt ($M)', d.net_debt_m, 'Total debt minus cash', '10')}
      ${_inp(`${tk}-eveb-shares`, 'Shares (M)', d.shares_m, 'To convert equity value to per share', '0.1', '0.001')}
    </div>`;
  return _cardWrap('eveb', tk, 'EV / EBIT',
    'Similar to EV/EBITDA but uses EBIT — penalises capital-heavy businesses more',
    body);
}

// 7. P/S ───────────────────────────────────────────────────────────────────────
function _psCardHTML(tk, d) {
  const body = `
    <div class="val-inputs-grid col2">
      ${_inp(`${tk}-ps-rev`,    'Revenue ($M)', d.revenue_m, 'Last twelve months total revenue', '10')}
      ${_inp(`${tk}-ps-mult`,   'Target P/S ×', d.sector_ps, 'Price-to-sales multiple for sector', '0.1', '0.1')}
      ${_inp(`${tk}-ps-shares`, 'Shares (M)', d.shares_m, 'Diluted shares outstanding', '0.1', '0.001')}
    </div>`;
  return _cardWrap('ps', tk, 'Price / Sales (P/S)',
    'Fair Market Cap = Revenue × P/S multiple → divide by shares. Useful for unprofitable growth cos.',
    body);
}

// 8. PEG ───────────────────────────────────────────────────────────────────────
function _pegCardHTML(tk, d) {
  const body = `
    <div class="val-inputs-grid">
      ${_inp(`${tk}-peg-eps`,    'EPS ($)', d.eps_ttm, 'Trailing twelve months EPS', '0.01')}
      ${_inp(`${tk}-peg-g`,      'EPS Growth Rate (%)', d.earnings_growth_pct, '5-year expected annual earnings growth', '0.5', '0.1')}
      ${_inp(`${tk}-peg-target`, 'Target PEG', '1.0', '1.0 = fairly valued; <1 = undervalued', '0.1', '0.1', '3')}
    </div>`;
  return _cardWrap('peg', tk, 'PEG Ratio',
    'Fair P/E = Growth Rate × Target PEG → Fair Price = EPS × Fair P/E',
    body);
}

// 9. Graham Number ─────────────────────────────────────────────────────────────
function _grahamCardHTML(tk, d) {
  const body = `
    <div class="val-inputs-grid col2">
      ${_inp(`${tk}-gr-eps`,  'EPS TTM ($)', d.eps_ttm, 'Must be positive', '0.01')}
      ${_inp(`${tk}-gr-bvps`, 'Book Value / Share ($)', d.book_value_ps, 'Total equity ÷ shares outstanding', '0.01')}
    </div>
    <div id="${tk}-graham-na" class="val-note" style="display:none;">⚠️ Graham Number requires positive EPS and book value.</div>`;
  return _cardWrap('graham', tk, 'Graham Number',
    'Benjamin Graham conservative fair value: √(22.5 × EPS × BVPS)',
    body);
}

// 10. NCAV ─────────────────────────────────────────────────────────────────────
function _ncavCardHTML(tk, d) {
  const body = `
    <div class="val-inputs-grid">
      ${_inp(`${tk}-ncav-ca`,    'Current Assets ($M)', d.current_assets_m, 'Cash, receivables, inventory — most liquid assets', '10')}
      ${_inp(`${tk}-ncav-tl`,    'Total Liabilities ($M)', d.total_liab_m, 'All obligations (current + long-term)', '10')}
      ${_inp(`${tk}-ncav-shares`, 'Shares (M)', d.shares_m, 'Diluted shares outstanding', '0.1', '0.001')}
    </div>
    <div class="val-note" style="margin-top:8px;">
      Net Current Asset Value = (Current Assets − Total Liabilities) ÷ Shares. Graham's deep-value floor: buy below NCAV.
    </div>`;
  return _cardWrap('ncav', tk, 'Net Current Asset Value (NCAV)',
    'Graham asset floor: value if the company liquidated all current assets and paid all debts',
    body);
}

// ── Calculations ──────────────────────────────────────────────────────────────

function _recalcTicker(tk) {
  const d = _vStocks[tk]?.data;
  if (!d) return;
  const price = d.current_price;
  const cur   = d.currency;

  const results = {};

  // DCF
  const dcfFcf   = _gv(`${tk}-dcf-fcf`);
  const dcfShares = Math.max(_gv(`${tk}-dcf-shares`), 0.001);
  const dcfFcfPs = dcfShares > 0 ? (dcfFcf * 1e6) / (dcfShares * 1e6) : 0;
  const dcfG1   = _gv(`${tk}-dcf-g1`)   / 100;
  const dcfG2   = _gv(`${tk}-dcf-g2`)   / 100;
  const dcfTg   = _gv(`${tk}-dcf-tg`)   / 100;
  const dcfWacc = _gv(`${tk}-dcf-wacc`) / 100;
  const dcfMos  = _gv(`${tk}-dcf-mos`)  / 100;
  results.dcf = _calcDCF(dcfFcfPs, dcfG1, dcfG2, dcfTg, dcfWacc, dcfMos);
  _setResult(`res-${tk}-dcf`, results.dcf, cur);
  _setUD(`ud-${tk}-dcf`, results.dcf, price);
  _setDCFWorkings(tk, dcfFcfPs, dcfG1, dcfG2, dcfTg, dcfWacc, dcfMos, results.dcf, cur);

  // EPV
  const epvEbit    = _gv(`${tk}-epv-ebit`);
  const epvTax     = _gv(`${tk}-epv-tax`)   / 100;
  const epvWacc    = _gv(`${tk}-epv-wacc`)  / 100;
  const epvNetDebt = _gv(`${tk}-epv-netdebt`);
  const epvShares  = Math.max(_gv(`${tk}-epv-shares`), 0.001);
  results.epv = _calcEPV(epvEbit, epvTax, epvWacc, epvNetDebt, epvShares);
  _setResult(`res-${tk}-epv`, results.epv, cur);
  _setUD(`ud-${tk}-epv`, results.epv, price);
  _setEPVWorkings(tk, epvEbit, epvTax, epvWacc, epvNetDebt, epvShares, results.epv, cur);

  // DDM
  const ddmDiv = _gv(`${tk}-ddm-div`);
  const ddmG   = _gv(`${tk}-ddm-g`) / 100;
  const ddmR   = _gv(`${tk}-ddm-r`) / 100;
  results.ddm = (ddmDiv > 0) ? _calcDDM(ddmDiv, ddmG, ddmR) : null;
  _setResult(`res-${tk}-ddm`, results.ddm, cur);
  _setUD(`ud-${tk}-ddm`, results.ddm, price);
  _setDDMWorkings(tk, ddmDiv, ddmG, ddmR, results.ddm, cur);

  // P/E
  const peEpsTtm = _gv(`${tk}-pe-epsttm`);
  const peEpsFwd = _gv(`${tk}-pe-epsfwd`);
  const peMulTtm = _gv(`${tk}-pe-multtm`);
  const peMulFwd = _gv(`${tk}-pe-mulfwd`);
  const peTtmVal = (peEpsTtm > 0 && peMulTtm > 0) ? r2(peEpsTtm * peMulTtm) : null;
  const peFwdVal = (peEpsFwd > 0 && peMulFwd > 0) ? r2(peEpsFwd * peMulFwd) : null;
  results.pe = (peTtmVal && peFwdVal) ? r2((peTtmVal + peFwdVal) / 2) : (peTtmVal || peFwdVal);
  document.getElementById(`res-${tk}-pe-ttm`).textContent = peTtmVal ? _fp(peTtmVal, cur) : '—';
  document.getElementById(`res-${tk}-pe-fwd`).textContent = peFwdVal ? _fp(peFwdVal, cur) : '—';
  _setResult(`res-${tk}-pe`, results.pe, cur);
  _setUD(`ud-${tk}-pe`, results.pe, price);
  _setPEWorkings(tk, peEpsTtm, peEpsFwd, peMulTtm, peMulFwd, peTtmVal, peFwdVal, cur);

  // EV/EBITDA
  const evdaEbitda  = _gv(`${tk}-evda-ebitda`);
  const evdaMult    = _gv(`${tk}-evda-mult`);
  const evdaNetDebt = _gv(`${tk}-evda-netdebt`);
  const evdaShares  = Math.max(_gv(`${tk}-evda-shares`), 0.001);
  results.evda = _calcEVMult(evdaEbitda, evdaMult, evdaNetDebt, evdaShares);
  _setResult(`res-${tk}-evda`, results.evda, cur);
  _setUD(`ud-${tk}-evda`, results.evda, price);
  _setEVWorkings(tk, 'evda', 'EBITDA', evdaEbitda, evdaMult, evdaNetDebt, evdaShares, results.evda, cur);

  // EV/EBIT
  const evebEbit    = _gv(`${tk}-eveb-ebit`);
  const evebMult    = _gv(`${tk}-eveb-mult`);
  const evebNetDebt = _gv(`${tk}-eveb-netdebt`);
  const evebShares  = Math.max(_gv(`${tk}-eveb-shares`), 0.001);
  results.eveb = _calcEVMult(evebEbit, evebMult, evebNetDebt, evebShares);
  _setResult(`res-${tk}-eveb`, results.eveb, cur);
  _setUD(`ud-${tk}-eveb`, results.eveb, price);
  _setEVWorkings(tk, 'eveb', 'EBIT', evebEbit, evebMult, evebNetDebt, evebShares, results.eveb, cur);

  // P/S
  const psRev    = _gv(`${tk}-ps-rev`);
  const psMult   = _gv(`${tk}-ps-mult`);
  const psShares = Math.max(_gv(`${tk}-ps-shares`), 0.001);
  results.ps = (psRev > 0 && psMult > 0 && psShares > 0)
    ? r2((psRev * psMult * 1e6) / (psShares * 1e6)) : null;
  _setResult(`res-${tk}-ps`, results.ps, cur);
  _setUD(`ud-${tk}-ps`, results.ps, price);
  _setPSWorkings(tk, psRev, psMult, psShares, results.ps, cur);

  // PEG
  const pegEps    = _gv(`${tk}-peg-eps`);
  const pegG      = _gv(`${tk}-peg-g`);
  const pegTarget = _gv(`${tk}-peg-target`, 1);
  results.peg = (pegEps > 0 && pegG > 0) ? r2(pegEps * pegG * pegTarget) : null;
  _setResult(`res-${tk}-peg`, results.peg, cur);
  _setUD(`ud-${tk}-peg`, results.peg, price);
  _setPEGWorkings(tk, pegEps, pegG, pegTarget, results.peg, cur);

  // Graham
  const grEps  = _gv(`${tk}-gr-eps`);
  const grBvps = _gv(`${tk}-gr-bvps`);
  const grNA   = document.getElementById(`${tk}-graham-na`);
  results.graham = (grEps > 0 && grBvps > 0) ? r2(Math.sqrt(22.5 * grEps * grBvps)) : null;
  if (grNA) grNA.style.display = results.graham ? 'none' : 'block';
  _setResult(`res-${tk}-graham`, results.graham, cur);
  _setUD(`ud-${tk}-graham`, results.graham, price);
  _setGrahamWorkings(tk, grEps, grBvps, results.graham, cur);

  // NCAV
  const ncavCa     = _gv(`${tk}-ncav-ca`);
  const ncavTl     = _gv(`${tk}-ncav-tl`);
  const ncavShares = Math.max(_gv(`${tk}-ncav-shares`), 0.001);
  const ncavRaw    = (ncavCa - ncavTl) * 1e6 / (ncavShares * 1e6);
  results.ncav = ncavShares > 0 ? r2(ncavRaw) : null;
  _setResult(`res-${tk}-ncav`, results.ncav, cur);
  _setUD(`ud-${tk}-ncav`, results.ncav, price);
  _setNCAVWorkings(tk, ncavCa, ncavTl, ncavShares, results.ncav, cur);

  // Comparison chart
  _renderCompareChart(tk, results, price, cur);
}

// ── Core math ─────────────────────────────────────────────────────────────────

function _calcDCF(fcfPs, g1, g2, tg, wacc, mos) {
  if (!fcfPs || wacc <= tg || wacc <= 0) return null;
  let pv = 0, cf = fcfPs;
  for (let y = 1; y <= 5;  y++) { cf *= (1 + g1); pv += cf / Math.pow(1 + wacc, y); }
  for (let y = 6; y <= 10; y++) { cf *= (1 + g2); pv += cf / Math.pow(1 + wacc, y); }
  const tv = (cf * (1 + tg)) / (wacc - tg);
  pv += tv / Math.pow(1 + wacc, 10);
  return pv > 0 ? r2(pv * (1 - mos)) : null;
}

function _calcEPV(ebitM, tax, wacc, netDebtM, sharesM) {
  if (!ebitM || !wacc || wacc <= 0 || !sharesM) return null;
  const nopat     = ebitM * (1 - tax);          // $M
  const firmValue = nopat / wacc;               // $M
  const equity    = firmValue - netDebtM;       // $M
  return equity > 0 ? r2((equity * 1e6) / (sharesM * 1e6)) : null;
}

function _calcDDM(div, g, r) {
  if (!div || div <= 0 || r <= g || r <= 0) return null;
  return r2((div * (1 + g)) / (r - g));
}

function _calcEVMult(earnM, mult, netDebtM, sharesM) {
  if (!earnM || !mult || !sharesM || sharesM <= 0) return null;
  const equity = earnM * mult - netDebtM;  // $M
  return equity > 0 ? r2((equity * 1e6) / (sharesM * 1e6)) : null;
}

// ── Workings panels ───────────────────────────────────────────────────────────

function toggleWorkings(tk, modelId) {
  const panel = document.getElementById(`wp-${tk}-${modelId}`);
  const btn   = panel.previousElementSibling;
  const open  = panel.classList.toggle('open');
  btn.innerHTML = open
    ? `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/></svg> Hide working`
    : `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h20M12 2v20"/></svg> Show working`;
}

function _steps(arr) {
  return arr.map(([num, eq, label]) =>
    `<div class="step"><span class="step-num">${num}</span>
     <div><div class="step-eq">${eq}</div>
     ${label ? `<div class="step-label">${label}</div>` : ''}</div></div>`).join('');
}

function _setDCFWorkings(tk, fcfPs, g1, g2, tg, wacc, mos, result, cur) {
  const el = document.getElementById(`wp-${tk}-dcf`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">Cannot compute — check inputs.</div>'; return; }
  let cf = fcfPs, pv5 = 0;
  const yr5 = [];
  for (let y = 1; y <= 5; y++) { cf *= (1+g1); pv5 += cf/Math.pow(1+wacc,y); yr5.push(cf); }
  let pv10 = 0;
  const yr10 = [];
  for (let y = 6; y <= 10; y++) { cf *= (1+g2); pv10 += cf/Math.pow(1+wacc,y); yr10.push(cf); }
  const tv = (cf*(1+tg))/(wacc-tg);
  const pvTv = tv/Math.pow(1+wacc,10);
  const total = pv5 + pv10 + pvTv;
  const final = total * (1 - mos);
  el.innerHTML = _steps([
    ['1', `Base FCF/share = ${_fp(fcfPs, cur)}`, 'Starting free cash flow per share'],
    ['2', `Year 1–5 FCFs: ${yr5.map(v=>_fp(v,cur)).join(', ')}`, `Growing at ${(g1*100).toFixed(1)}% / yr → PV sum = ${_fp(pv5, cur)}`],
    ['3', `Year 6–10 FCFs: ${yr10.map(v=>_fp(v,cur)).join(', ')}`, `Slowing to ${(g2*100).toFixed(1)}% / yr → PV sum = ${_fp(pv10, cur)}`],
    ['4', `Terminal Value (yr 10) = ${_fp(cf,cur)} × (1 + ${(tg*100).toFixed(1)}%) ÷ (${(wacc*100).toFixed(1)}% − ${(tg*100).toFixed(1)}%) = ${_fp(tv, cur)}`, `Discounted back: PV(TV) = ${_fp(pvTv, cur)}`],
    ['5', `Total intrinsic value = ${_fp(pv5,cur)} + ${_fp(pv10,cur)} + ${_fp(pvTv,cur)} = ${_fp(total, cur)}`, ''],
    ['6', `After ${(mos*100).toFixed(0)}% margin of safety: ${_fp(total,cur)} × ${(1-mos).toFixed(2)} = ${_fp(final, cur)}`, 'Final DCF fair value'],
  ]);
}

function _setEPVWorkings(tk, ebitM, tax, wacc, netDebtM, sharesM, result, cur) {
  const el = document.getElementById(`wp-${tk}-epv`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">Cannot compute.</div>'; return; }
  const nopat = ebitM * (1-tax);
  const firm  = nopat / wacc;
  const eq    = firm - netDebtM;
  el.innerHTML = _steps([
    ['1', `NOPAT = EBIT × (1 − Tax Rate) = $${ebitM.toFixed(0)}M × (1 − ${(tax*100).toFixed(1)}%) = $${nopat.toFixed(0)}M`, 'Net Operating Profit After Tax'],
    ['2', `EPV (firm) = NOPAT ÷ WACC = $${nopat.toFixed(0)}M ÷ ${(wacc*100).toFixed(1)}% = $${firm.toFixed(0)}M`, 'Capitalise at WACC — no growth assumed'],
    ['3', `Equity Value = EPV − Net Debt = $${firm.toFixed(0)}M − $${netDebtM.toFixed(0)}M = $${eq.toFixed(0)}M`, ''],
    ['4', `Per Share = $${eq.toFixed(0)}M ÷ ${sharesM.toFixed(0)}M shares = ${_fp(result, cur)}`, 'Final EPV fair value'],
  ]);
}

function _setDDMWorkings(tk, div, g, r, result, cur) {
  const el = document.getElementById(`wp-${tk}-ddm`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">No dividend or r ≤ g.</div>'; return; }
  const d1 = div * (1+g);
  el.innerHTML = _steps([
    ['1', `D₁ = D₀ × (1 + g) = ${_fp(div,cur)} × (1 + ${(g*100).toFixed(1)}%) = ${_fp(d1,cur)}`, 'Next year expected dividend'],
    ['2', `P = D₁ ÷ (r − g) = ${_fp(d1,cur)} ÷ (${(r*100).toFixed(1)}% − ${(g*100).toFixed(1)}%)`, ''],
    ['3', `P = ${_fp(d1,cur)} ÷ ${((r-g)*100).toFixed(1)}% = ${_fp(result,cur)}`, 'Gordon Growth Model fair value'],
  ]);
}

function _setPEWorkings(tk, epsTtm, epsFwd, mulTtm, mulFwd, valTtm, valFwd, cur) {
  const el = document.getElementById(`wp-${tk}-pe`); if (!el) return;
  el.innerHTML = _steps([
    ['1', `TTM Fair Value = EPS(TTM) × Target P/E = ${_fp(epsTtm,cur)} × ${mulTtm} = ${valTtm ? _fp(valTtm,cur) : 'N/A'}`, ''],
    ['2', `Fwd Fair Value = EPS(Fwd) × Target P/E(Fwd) = ${_fp(epsFwd,cur)} × ${mulFwd} = ${valFwd ? _fp(valFwd,cur) : 'N/A'}`, ''],
    ['3', `Displayed result = average of TTM and Forward values`, ''],
  ]);
}

function _setEVWorkings(tk, id, label, earnM, mult, netDebtM, sharesM, result, cur) {
  const el = document.getElementById(`wp-${tk}-${id}`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">Cannot compute.</div>'; return; }
  const targetEV = earnM * mult;
  const equity   = targetEV - netDebtM;
  el.innerHTML = _steps([
    ['1', `Target EV = ${label} × Multiple = $${earnM.toFixed(0)}M × ${mult} = $${targetEV.toFixed(0)}M`, ''],
    ['2', `Equity Value = Target EV − Net Debt = $${targetEV.toFixed(0)}M − $${netDebtM.toFixed(0)}M = $${equity.toFixed(0)}M`, ''],
    ['3', `Per Share = $${equity.toFixed(0)}M ÷ ${sharesM.toFixed(0)}M = ${_fp(result, cur)}`, 'Fair value per share'],
  ]);
}

function _setPSWorkings(tk, revM, mult, sharesM, result, cur) {
  const el = document.getElementById(`wp-${tk}-ps`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">Cannot compute.</div>'; return; }
  const mktCapTarget = revM * mult;
  el.innerHTML = _steps([
    ['1', `Target Market Cap = Revenue × P/S = $${revM.toFixed(0)}M × ${mult} = $${mktCapTarget.toFixed(0)}M`, ''],
    ['2', `Per Share = $${mktCapTarget.toFixed(0)}M ÷ ${sharesM.toFixed(0)}M shares = ${_fp(result, cur)}`, 'Fair value per share'],
  ]);
}

function _setPEGWorkings(tk, eps, g, target, result, cur) {
  const el = document.getElementById(`wp-${tk}-peg`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">Cannot compute.</div>'; return; }
  const fairPE = g * target;
  el.innerHTML = _steps([
    ['1', `Fair P/E = Growth Rate × Target PEG = ${g.toFixed(1)} × ${target} = ${fairPE.toFixed(1)}×`, 'At PEG = target, P/E equals growth rate × target'],
    ['2', `Fair Price = EPS × Fair P/E = ${_fp(eps,cur)} × ${fairPE.toFixed(1)} = ${_fp(result, cur)}`, ''],
  ]);
}

function _setGrahamWorkings(tk, eps, bvps, result, cur) {
  const el = document.getElementById(`wp-${tk}-graham`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">Requires positive EPS and book value.</div>'; return; }
  el.innerHTML = _steps([
    ['1', `Graham Number = √(22.5 × EPS × BVPS)`, 'Assumes max fair P/E = 15× and max fair P/B = 1.5× (15 × 1.5 = 22.5)'],
    ['2', `= √(22.5 × ${eps} × ${bvps})`, ''],
    ['3', `= √(${(22.5 * eps * bvps).toFixed(2)})`, ''],
    ['4', `= ${_fp(result, cur)}`, 'Conservative fair value per Graham'],
  ]);
}

function _setNCAVWorkings(tk, caM, tlM, sharesM, result, cur) {
  const el = document.getElementById(`wp-${tk}-ncav`); if (!el) return;
  const net = caM - tlM;
  el.innerHTML = _steps([
    ['1', `NCAV = Current Assets − Total Liabilities = $${caM.toFixed(0)}M − $${tlM.toFixed(0)}M = $${net.toFixed(0)}M`, 'Net liquidation value'],
    ['2', `Per Share = $${net.toFixed(0)}M ÷ ${sharesM.toFixed(0)}M shares = ${result ? _fp(result, cur) : 'negative (liabilities exceed assets)'}`, ''],
    ['3', `Graham's rule: buy when Price < NCAV (deep discount to liquidation value)`, ''],
  ]);
}

// ── Comparison chart ──────────────────────────────────────────────────────────

function _renderCompareChart(tk, results, price, cur) {
  const labels = {
    dcf:'DCF', epv:'EPV', ddm:'DDM', pe:'P/E',
    evda:'EV/EBITDA', eveb:'EV/EBIT', ps:'P/S', peg:'PEG',
    graham:'Graham', ncav:'NCAV'
  };
  const xs = [], ys = [], colors = [];
  for (const [key, val] of Object.entries(results)) {
    if (!val) continue;
    xs.push(labels[key] || key);
    ys.push(val);
    colors.push(val >= price ? '#10b981' : '#ef4444');
  }
  if (!xs.length) return;

  Plotly.react(`val-chart-${tk}`, [
    { type:'bar', x:xs, y:ys, marker:{color:colors,opacity:.85},
      text:ys.map(v=>_fp(v,cur)), textposition:'outside',
      textfont:{size:10,color:'#e2e8f0'}, cliponaxis:false },
    { type:'scatter', x:xs, y:Array(xs.length).fill(price), mode:'lines',
      line:{color:'#ef4444',width:2,dash:'dot'},
      name:`Market ${_fp(price,cur)}` }
  ], {
    paper_bgcolor:'transparent', plot_bgcolor:'transparent',
    font:{color:'#94a3b8',size:10},
    margin:{t:24,r:16,b:36,l:56},
    xaxis:{gridcolor:'#263348',zerolinecolor:'#263348',fixedrange:true},
    yaxis:{gridcolor:'#263348',zerolinecolor:'#263348',fixedrange:true,
           tickprefix: cur==='USD' ? '$' : ''},
    showlegend:true,
    legend:{orientation:'h',y:-0.18,x:.5,xanchor:'center',
            font:{size:10},bgcolor:'transparent'},
  }, {displayModeBar:false, responsive:true});
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function _gv(id, fallback=0) {
  const v = parseFloat(document.getElementById(id)?.value);
  return isNaN(v) ? fallback : v;
}

function _fp(v, currency) {
  if (v === null || v === undefined) return '—';
  const sym = (currency && currency !== 'USD') ? currency + '\u00a0' : '$';
  return sym + v.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
}

function r2(v) { return Math.round(v * 100) / 100; }

function _setResult(id, val, cur) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!val && val !== 0) { el.textContent='N/A'; el.style.color='var(--muted)'; return; }
  el.textContent = _fp(val, cur);
  el.style.color = 'var(--accent2)';
}

function _setUD(id, intrinsic, price) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!intrinsic || !price) {
    el.textContent=''; el.className='val-updown neutral'; return;
  }
  const pct = ((intrinsic - price) / price) * 100;
  const up  = pct >= 0;
  el.className = `val-updown ${up ? 'up' : 'down'}`;
  // derive currency from any loaded stock (all share same currency assumption)
  const cur = Object.values(_vStocks).find(s=>s.data)?.data?.currency || 'USD';
  el.innerHTML = `${up?'▲':'▼'} ${Math.abs(pct).toFixed(1)}% ${up?'upside':'downside'} &nbsp;·&nbsp; Intrinsic ${_fp(intrinsic, cur)} vs market ${_fp(price, cur)}`;
}

// ══════════════════════════════════════════════════════════════════════════════
// LISTS MANAGEMENT
// ══════════════════════════════════════════════════════════════════════════════

// ── Init: load lists from server on page load ─────────────────────────────────
async function valListsInit() {
  try {
    const res = await fetch('/api/valuation/lists');
    if (res.ok) _vLists = await res.json();
  } catch (_) {}
  _renderLists();
}

// ── Render sidebar ────────────────────────────────────────────────────────────
function _renderLists() {
  const container = document.getElementById('val-lists-container');
  if (!container) return;

  if (!_vLists.length) {
    container.innerHTML = '<div class="val-lists-empty">No lists yet.<br/>Click <strong>New</strong> to create one.</div>';
    return;
  }

  container.innerHTML = _vLists.map(lst => {
    const tickers = lst.tickers || [];
    const tickerRows = tickers.length
      ? tickers.map(t => `
          <div class="val-list-ticker-row" onclick="valSwitchOrLoadTicker('${t.ticker}')">
            <span class="val-list-ticker-sym">${t.ticker}</span>
            <span class="val-list-ticker-price">${t.price ? _fp(t.price, 'USD') : ''}</span>
            <button class="val-list-ticker-del" title="Remove from list"
              onclick="event.stopPropagation();valRemoveFromList(${lst.id},'${t.ticker}')">×</button>
          </div>`).join('')
      : '<div class="val-list-tickers-empty">No stocks yet</div>';

    const convertBtn = tickers.length
      ? `<button class="val-list-btn convert" title="Convert to portfolio"
           onclick="event.stopPropagation();valConvertList(${lst.id})">
           <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
         </button>`
      : '';

    return `
    <div class="val-list-item" id="vlist-${lst.id}">
      <div class="val-list-row" id="vlist-row-${lst.id}"
           onclick="_toggleList(${lst.id})"
           ondblclick="event.stopPropagation();_startRenameList(${lst.id})">
        <span class="val-list-chevron">›</span>
        <span class="val-list-name" id="vlist-name-${lst.id}">${_escHtml(lst.name)}</span>
        <span class="val-list-count">${tickers.length}</span>
        <div class="val-list-actions">
          ${convertBtn}
          <button class="val-list-btn del" title="Delete list"
            onclick="event.stopPropagation();_valDeleteList(${lst.id})">×</button>
        </div>
      </div>
      <div class="val-list-tickers" id="vlist-tickers-${lst.id}">
        ${tickerRows}
      </div>
    </div>`;
  }).join('');
}

// ── Toggle expand/collapse ────────────────────────────────────────────────────
function _toggleList(id) {
  const row     = document.getElementById(`vlist-row-${id}`);
  const tickers = document.getElementById(`vlist-tickers-${id}`);
  if (!row || !tickers) return;
  const open = tickers.classList.toggle('open');
  row.classList.toggle('expanded', open);
}

// ── Inline rename ─────────────────────────────────────────────────────────────
function _startRenameList(id) {
  const nameEl = document.getElementById(`vlist-name-${id}`);
  if (!nameEl) return;
  const current = nameEl.textContent;
  const input   = document.createElement('input');
  input.className = 'val-list-name-input';
  input.value     = current;
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  const commit = () => {
    const newName = input.value.trim() || current;
    _valRenameList(id, newName);
  };
  input.addEventListener('blur',  commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { input.blur(); }
    if (e.key === 'Escape') { input.value = current; input.blur(); }
  });
}

// ── CRUD wrappers ─────────────────────────────────────────────────────────────

async function valNewList() {
  try {
    const res  = await fetch('/api/valuation/lists', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name: 'New List'})
    });
    const lst = await res.json();
    _vLists.unshift(lst);
    _renderLists();
    // Auto-expand and start rename
    setTimeout(() => {
      _toggleList(lst.id);
      _startRenameList(lst.id);
    }, 50);
  } catch (_) {
    _valToast('Failed to create list.');
  }
}

async function _valRenameList(id, name) {
  const lst = _vLists.find(l => l.id === id);
  if (!lst) return;
  lst.name = name;
  _renderLists();
  try {
    await fetch(`/api/valuation/lists/${id}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name})
    });
  } catch (_) {}
}

async function _valDeleteList(id) {
  _vLists = _vLists.filter(l => l.id !== id);
  _renderLists();
  try {
    await fetch(`/api/valuation/lists/${id}`, {method: 'DELETE'});
  } catch (_) {}
}

async function valAddToList(listId, ticker) {
  const lst    = _vLists.find(l => l.id === listId);
  const stock  = _vStocks[ticker];
  if (!lst || !stock?.data) return;

  // Toggle: if already in list, remove it
  const existing = lst.tickers.findIndex(t => t.ticker === ticker);
  if (existing >= 0) {
    lst.tickers.splice(existing, 1);
  } else {
    lst.tickers.push({
      ticker,
      name:  stock.data.name  || ticker,
      price: stock.data.current_price || 0,
    });
  }
  _renderLists();
  // Re-render dropdown to reflect new checked state
  _renderAtlDropdown(ticker);

  try {
    await fetch(`/api/valuation/lists/${listId}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({tickers: lst.tickers})
    });
  } catch (_) {}
}

async function valRemoveFromList(listId, ticker) {
  const lst = _vLists.find(l => l.id === listId);
  if (!lst) return;
  lst.tickers = lst.tickers.filter(t => t.ticker !== ticker);
  _renderLists();
  try {
    await fetch(`/api/valuation/lists/${listId}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({tickers: lst.tickers})
    });
  } catch (_) {}
}

async function valConvertList(id) {
  const lst = _vLists.find(l => l.id === id);
  if (!lst) return;
  if (!lst.tickers.length) {
    _valToast('Add stocks to the list first.');
    return;
  }
  try {
    const res  = await fetch(`/api/valuation/lists/${id}/to-portfolio`, {method: 'POST'});
    const data = await res.json();
    if (data.portfolio_id) {
      _valToast(
        `"${lst.name}" saved as portfolio — `,
        'Open Portfolio Optimizer',
        '/'
      );
    }
  } catch (_) {
    _valToast('Conversion failed.');
  }
}

// ── Create new list and immediately add current ticker ────────────────────────
async function valNewListAndAdd() {
  const ticker = _vAtlTicker;
  _hideAtlDropdown();
  try {
    const res  = await fetch('/api/valuation/lists', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name: ticker ? `${ticker} list` : 'New List'})
    });
    const lst = await res.json();
    _vLists.unshift(lst);
    if (ticker) await valAddToList(lst.id, ticker);
    else _renderLists();
    // Expand new list
    setTimeout(() => _toggleList(lst.id), 80);
  } catch (_) {
    _valToast('Failed to create list.');
  }
}

// ── Click a ticker in the sidebar: switch to its tab or load it ───────────────
function valSwitchOrLoadTicker(ticker) {
  if (_vStocks[ticker]) {
    valSwitchTab(ticker);
  } else {
    document.getElementById('val-ticker-input').value = ticker;
    valAddStock();
  }
}

// ── Add-to-List dropdown ──────────────────────────────────────────────────────
function valShowAddToList(ticker) {
  _vAtlTicker = ticker;
  const btn = event.currentTarget;
  _renderAtlDropdown(ticker);
  const dd  = document.getElementById('val-atl-dropdown');
  dd.style.display = 'block';

  // Position below the button
  const rect = btn.getBoundingClientRect();
  const ddW  = 200;
  let   left = rect.left;
  if (left + ddW > window.innerWidth - 8) left = window.innerWidth - ddW - 8;
  dd.style.left = `${left}px`;
  dd.style.top  = `${rect.bottom + 4}px`;

  // Close on outside click
  setTimeout(() => {
    document.addEventListener('click', _atlOutsideClick, {once: true, capture: true});
  }, 0);
}

function _renderAtlDropdown(ticker) {
  const listEl = document.getElementById('val-atl-list');
  if (!listEl) return;
  if (!_vLists.length) {
    listEl.innerHTML = '<div class="val-atl-no-lists">No lists yet</div>';
    return;
  }
  listEl.innerHTML = _vLists.map(lst => {
    const inList = (lst.tickers || []).some(t => t.ticker === ticker);
    return `
    <div class="val-atl-item ${inList ? 'checked' : ''}"
         onclick="valAddToList(${lst.id},'${ticker}')">
      <span class="val-atl-check">${inList ? '✓' : ''}</span>
      <span>${_escHtml(lst.name)}</span>
    </div>`;
  }).join('');
}

function _atlOutsideClick(e) {
  const dd = document.getElementById('val-atl-dropdown');
  if (dd && !dd.contains(e.target)) _hideAtlDropdown();
  else document.addEventListener('click', _atlOutsideClick, {once: true, capture: true});
}

function _hideAtlDropdown() {
  const dd = document.getElementById('val-atl-dropdown');
  if (dd) dd.style.display = 'none';
  _vAtlTicker = null;
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTimer = null;
function _valToast(msg, linkText, linkHref) {
  const el = document.getElementById('val-toast');
  if (!el) return;
  el.innerHTML = msg + (linkText ? `<a href="${linkHref}">${linkText}</a>` : '');
  el.style.display = 'flex';
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.style.display = 'none'; }, 4000);
}

// ── Escape HTML helper ────────────────────────────────────────────────────────
function _escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Bootstrap on load ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', valListsInit);
