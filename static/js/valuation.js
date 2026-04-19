/* ═══════════════════════════════════════════════════════════════
   valuation.js  —  Equity Valuation module
   Workspace-based: each workspace owns its own stocks + inputs,
   auto-saved to the server in real time.
   ═══════════════════════════════════════════════════════════════ */

// ── Current workspace in-memory caches ───────────────────────────────────────
const _vStocks = {};    // { TICKER: { data, id } } — current workspace only
let   _vActive = null;  // currently shown ticker in current workspace

// ── Workspaces state ─────────────────────────────────────────────────────────
let _vWs         = [];    // [{id, name, activeTicker, stocks:[{ticker,name,price,data,inputs}]}]
let _vActiveWsId = null;  // currently active workspace id

// ── Autosave status ──────────────────────────────────────────────────────────
let _vSaveTimer = null;
let _vSaving    = false;

function _setSaveStatus(state) {
  const el = document.getElementById('val-save-status');
  if (!el) return;
  el.className = `val-save-status ${state}`;
  const label = el.querySelector('.val-save-label');
  if (label) label.textContent = {
    idle: 'Saved', saved: 'Saved',
    dirty: 'Unsaved', saving: 'Saving…', error: 'Save failed'
  }[state] || '';
}

function _scheduleSave() {
  _setSaveStatus('dirty');
  clearTimeout(_vSaveTimer);
  _vSaveTimer = setTimeout(_flushSave, 600);
}

async function _flushSave() {
  clearTimeout(_vSaveTimer);
  if (!_vActiveWsId || _vSaving) return;
  const ws = _vWs.find(w => w.id === _vActiveWsId);
  if (!ws) return;
  _syncCurrentWsFromDOM(ws);
  _vSaving = true;
  _setSaveStatus('saving');
  try {
    const res = await fetch(`/api/valuation/lists/${ws.id}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        name: ws.name,
        tickers: { active: ws.activeTicker, stocks: ws.stocks }
      })
    });
    if (!res.ok) throw new Error();
    _setSaveStatus('saved');
  } catch (_) {
    _setSaveStatus('error');
  } finally {
    _vSaving = false;
  }
}

// Capture current DOM state into the workspace object
function _syncCurrentWsFromDOM(ws) {
  ws.activeTicker = _vActive;
  ws.stocks = Object.keys(_vStocks).map(tk => {
    const s = _vStocks[tk];
    const inputs = {};
    document.querySelectorAll(`#vs-${tk} input[type=number]`).forEach(inp => {
      const key = inp.id.startsWith(`${tk}-`) ? inp.id.slice(tk.length + 1) : inp.id;
      inputs[key] = inp.value;
    });
    return {
      ticker: tk,
      name:  s.data?.name || tk,
      price: s.data?.current_price || 0,
      data:  s.data,
      inputs,
    };
  });
}

// ── Workspace lifecycle ──────────────────────────────────────────────────────

function _wsNormalize(row) {
  // Support both legacy (array) and new ({active,stocks}) tickers shapes
  let t = row.tickers, active = null, stocks = [];
  if (Array.isArray(t)) {
    stocks = t.map(x => ({
      ticker: x.ticker, name: x.name, price: x.price,
      data: x.data || null, inputs: x.inputs || {}
    }));
  } else if (t && typeof t === 'object') {
    active = t.active || null;
    stocks = Array.isArray(t.stocks) ? t.stocks : [];
  }
  return { id: row.id, name: row.name, activeTicker: active, stocks };
}

async function valNewWorkspace(initialName) {
  if (_vActiveWsId) await _flushSave();
  const name = initialName || `Workspace ${_vWs.length + 1}`;
  try {
    const res = await fetch('/api/valuation/lists', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name})
    });
    const row = await res.json();
    const ws  = _wsNormalize(row);
    _vWs.push(ws);
    await _activateWorkspace(ws.id, true);
    _renderWsTabs();
  } catch (_) {
    _valToast('Failed to create workspace.');
  }
}

async function valDeleteWorkspace(id) {
  if (!confirm('Delete this workspace and all its stocks?')) return;
  try { await fetch(`/api/valuation/lists/${id}`, {method: 'DELETE'}); } catch (_) {}
  _vWs = _vWs.filter(w => w.id !== id);
  if (_vActiveWsId === id) {
    _vActiveWsId = null;
    _clearDOM();
    if (_vWs.length) {
      await _activateWorkspace(_vWs[0].id, true);
    } else {
      await valNewWorkspace('Workspace 1');
      return;
    }
  }
  _renderWsTabs();
}

async function valSwitchWorkspace(id) {
  if (id === _vActiveWsId) return;
  await _activateWorkspace(id, false);
  _renderWsTabs();
}

async function _activateWorkspace(id, skipSave) {
  if (!skipSave && _vActiveWsId) await _flushSave();
  _clearDOM();
  _vActiveWsId = id;
  const ws = _vWs.find(w => w.id === id);
  if (!ws) return;

  // Rebuild _vStocks + DOM panels from stored workspace
  for (const s of (ws.stocks || [])) {
    if (s.data) {
      _vStocks[s.ticker] = { data: s.data, id: `vs-${s.ticker}` };
      _renderStockPanel(s.ticker, s.data);
      _restoreInputs(s.ticker, s.inputs || {});
    } else {
      await _fetchAndRenderStock(s.ticker, s.inputs);
    }
  }

  const first = (ws.activeTicker && _vStocks[ws.activeTicker])
    ? ws.activeTicker
    : Object.keys(_vStocks)[0];
  if (first) valSwitchStock(first, /*silent*/true);
  else {
    const e = document.getElementById('val-empty-state');
    if (e) e.style.display = 'block';
  }
  _renderSidebarStocks();
  _setSaveStatus('idle');
}

function _clearDOM() {
  const c = document.getElementById('val-stocks-container');
  if (c) c.querySelectorAll('.val-stock-panel').forEach(el => el.remove());
  for (const k of Object.keys(_vStocks)) delete _vStocks[k];
  _vActive = null;
  const empty = document.getElementById('val-empty-state');
  if (empty) empty.style.display = 'block';
}

function _restoreInputs(ticker, inputs) {
  for (const [key, val] of Object.entries(inputs || {})) {
    const id = key.startsWith(`${ticker}-`) ? key : `${ticker}-${key}`;
    const el = document.getElementById(id);
    if (el) el.value = val;
  }
  _recalcTicker(ticker);
}

async function _fetchAndRenderStock(ticker, inputs) {
  try {
    const res  = await fetch(`/api/valuation/financials?ticker=${encodeURIComponent(ticker)}`);
    const data = await res.json();
    if (!res.ok) throw new Error();
    _vStocks[ticker] = { data, id: `vs-${ticker}` };
    _renderStockPanel(ticker, data);
    if (inputs) _restoreInputs(ticker, inputs);
  } catch (_) {}
}

// ── Workspace tab rendering (top bar) ────────────────────────────────────────

function _renderWsTabs() {
  const c = document.getElementById('ws-tabs-container');
  if (!c) return;
  c.innerHTML = _vWs.map(ws => {
    const active = ws.id === _vActiveWsId;
    const hasStocks = (ws.stocks || []).length > 0;
    return `
    <button class="tab${active ? ' active' : ''}${hasStocks ? ' has-results' : ''}"
            onclick="valSwitchWorkspace(${ws.id})" data-id="${ws.id}">
      <span class="tab-dot"></span>
      <span class="tab-name"
            ondblclick="_startRenameWs(event,${ws.id})"
            onblur="_finishRenameWs(event,${ws.id})"
            contenteditable="false"
            onkeydown="if(event.key==='Enter'){event.preventDefault();this.blur();}"
            id="ws-name-${ws.id}">${_escHtml(ws.name)}</span>
      ${_vWs.length > 1 ? `<span class="tab-close" onclick="event.stopPropagation();valDeleteWorkspace(${ws.id})">×</span>` : ''}
    </button>`;
  }).join('');
}

function _startRenameWs(e, id) {
  e.stopPropagation();
  const el = document.getElementById(`ws-name-${id}`);
  if (!el) return;
  el.contentEditable = 'true';
  el.focus();
  const range = document.createRange();
  range.selectNodeContents(el);
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(range);
}

function _finishRenameWs(e, id) {
  const el = e.target;
  el.contentEditable = 'false';
  const ws = _vWs.find(w => w.id === id);
  if (!ws) return;
  const nn = (el.textContent || '').trim() || ws.name;
  if (nn !== ws.name) {
    ws.name = nn;
    _scheduleSave();
  }
}

// ── Sidebar (stock list for current workspace) ───────────────────────────────

function _renderSidebarStocks() {
  const c = document.getElementById('val-sidebar-stocks');
  if (!c) return;
  const tickers = Object.keys(_vStocks);
  if (!tickers.length) {
    c.innerHTML = '<div class="val-sidebar-empty">No stocks yet.<br/>Add a ticker above.</div>';
    return;
  }
  c.innerHTML = tickers.map(tk => {
    const s = _vStocks[tk];
    const d = s.data;
    const active = tk === _vActive;
    const loading = s.loading;
    const nm = d?.name ? _escHtml(String(d.name)).slice(0, 22) : '';
    const pr = d ? _fp(d.current_price, d.currency) : '';
    return `
    <div class="val-side-stock${active ? ' active' : ''}" onclick="valSwitchStock('${tk}')">
      <div class="val-side-sym">${tk}${loading ? ' <span class="val-side-loading"></span>' : ''}</div>
      <div class="val-side-meta">
        <span class="val-side-name">${nm}</span>
        <span class="val-side-price">${pr}</span>
      </div>
      <button class="val-side-close" onclick="event.stopPropagation();valRemoveStock('${tk}')" title="Remove">×</button>
    </div>`;
  }).join('');
}

// ── Add / remove / switch stock ──────────────────────────────────────────────

async function valAddStock() {
  const raw    = document.getElementById('val-ticker-input').value.trim().toUpperCase();
  const ticker = raw.replace(/[^A-Z0-9.\-]/g, '');
  const statusEl = document.getElementById('val-status');
  if (!ticker) { statusEl.textContent = 'Enter a ticker.'; return; }
  if (_vStocks[ticker]) { valSwitchStock(ticker); return; }
  if (!_vActiveWsId) { await valNewWorkspace('Workspace 1'); }

  statusEl.textContent = '';
  document.getElementById('val-ticker-input').value = '';

  _vStocks[ticker] = { data: null, id: `vs-${ticker}`, loading: true };
  _renderSidebarStocks();

  try {
    const res  = await fetch(`/api/valuation/financials?ticker=${encodeURIComponent(ticker)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Fetch failed.');
    _vStocks[ticker].data = data;
    _vStocks[ticker].loading = false;
    _renderStockPanel(ticker, data);
    valSwitchStock(ticker);
    _renderSidebarStocks();
    _scheduleSave();
  } catch (e) {
    delete _vStocks[ticker];
    statusEl.textContent = e.message;
    _renderSidebarStocks();
  }
}

function valSwitchStock(ticker, silent) {
  _vActive = ticker;
  document.querySelectorAll('.val-stock-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(`vs-${ticker}`)?.classList.add('active');
  const empty = document.getElementById('val-empty-state');
  if (empty) empty.style.display = Object.keys(_vStocks).length ? 'none' : 'block';
  _renderSidebarStocks();
  if (silent) return;
  const ws = _vWs.find(w => w.id === _vActiveWsId);
  if (ws && ws.activeTicker !== ticker) {
    ws.activeTicker = ticker;
    _scheduleSave();
  }
}

function valRemoveStock(ticker) {
  if (!confirm(`Remove ${ticker} from this workspace?`)) return;
  delete _vStocks[ticker];
  document.getElementById(`vs-${ticker}`)?.remove();
  const remaining = Object.keys(_vStocks);
  if (remaining.length) valSwitchStock(remaining[remaining.length - 1]);
  else {
    _vActive = null;
    const e = document.getElementById('val-empty-state');
    if (e) e.style.display = 'block';
  }
  _renderSidebarStocks();
  _scheduleSave();
}

// ── Convert current workspace → portfolio ────────────────────────────────────

async function valConvertCurrentWs() {
  if (!_vActiveWsId) return;
  const ws = _vWs.find(w => w.id === _vActiveWsId);
  if (!ws || !Object.keys(_vStocks).length) {
    _valToast('Add stocks to the workspace first.');
    return;
  }
  await _flushSave();
  try {
    const res  = await fetch(`/api/valuation/lists/${ws.id}/to-portfolio`, {method: 'POST'});
    const data = await res.json();
    if (data.portfolio_id) {
      _valToast(`"${ws.name}" saved as portfolio — `, 'Open Portfolio Optimizer', '/');
    }
  } catch (_) { _valToast('Conversion failed.'); }
}

// Flush pending save on page unload
window.addEventListener('beforeunload', () => {
  if (_vSaveTimer) { clearTimeout(_vSaveTimer); _flushSave(); }
});

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
    <div id="val-ai-${ticker}" class="val-ai-section">
      <div class="val-ai-loading">
        <div class="val-ai-spinner"></div>
        <span>Generating AI business analysis...</span>
      </div>
    </div>
    <div class="val-compare-card">
      <div class="chart-header" style="margin-bottom:6px;">
        <div class="chart-title" style="margin:0;font-size:12px;">Intrinsic Value vs Market Price</div>
        <div style="font-size:10px;color:var(--muted);">Red line = current price ${_fp(d.current_price, d.currency)}</div>
      </div>
      <div id="val-chart-${ticker}" style="height:200px;"></div>
    </div>
    ${_categoriesHTML(ticker, d)}`;

  container.appendChild(panel);

  // Bind all inputs to recalc + autosave
  panel.querySelectorAll('input[type=number]').forEach(inp => {
    inp.addEventListener('input', () => { _recalcTicker(ticker); _scheduleSave(); });
  });

  // Initial calc + static historical charts
  _recalcTicker(ticker);
  _renderModelCharts(ticker, d);
  _setHistoricalBand(ticker, 'pe',   d.pe_history,        'pe',        d.pe_ttm,            '\u00d7');
  _setHistoricalBand(ticker, 'evda', d.ev_ebitda_history, 'ev_ebitda', d.ev_ebitda_current, '\u00d7');
  _setHistoricalBand(ticker, 'ps',   d.ps_history,        'ps',        d.ps_current,        '\u00d7');
  _renderSparkline(ticker, d);
  _fetchAIAnalysis(ticker, d);
  valApplyModelSettings();
}

function _stockHeaderHTML(d) {
  // 1Y price change
  const ph = d.price_history || [];
  let changeHTML = '';
  if (ph.length >= 2) {
    const first = ph[0].close, last = ph[ph.length-1].close;
    const chg = last - first, pct = (chg / first) * 100;
    const up = chg >= 0;
    changeHTML = `<span class="val-price-change ${up ? 'up' : 'down'}">${up?'+':''}${chg.toFixed(2)} (${up?'+':''}${pct.toFixed(1)}%) 1Y</span>`;
  }

  const summary = d.business_summary || '';
  const truncated = summary.length > 300 ? summary.slice(0, 300) + '...' : summary;

  return `
  <div class="val-stock-header-top">
    <div class="val-stock-info">
      <div style="display:flex;align-items:flex-end;gap:14px;flex-wrap:wrap;">
        <span class="val-stock-ticker">${d.ticker}</span>
        <span class="val-stock-name">${d.name}</span>
        <span style="font-size:12px;color:var(--muted);padding-bottom:6px;">${d.currency}</span>
      </div>
      <div class="val-stock-chips">
        ${_ultimateScoreHTML(d)}
        ${_tagHTML('Sector', d.sector,   `Industry group: ${d.industry}. Used to calibrate fair-value multiples (target P/E, EV/EBITDA, P/S defaults).`)}
        ${_tagHTML('Mkt Cap', d.market_cap_fmt, 'Market capitalization = current price × shares outstanding. Proxy for company size and liquidity.')}
        ${_betaTag(d)}
        ${_waccTag(d)}
        ${_peTag(d)}
        ${_psTag(d)}
        ${_evEbitdaTag(d)}
        ${_evEbitTag(d)}
        ${_divTag(d)}
        ${_fScoreTag(d)}
        ${_zScoreTag(d)}
        ${_bestMultipleTag(d)}
      </div>
      ${truncated ? `<div class="val-biz-summary">${truncated}</div>` : ''}
    </div>
    <div class="val-stock-chart-col">
      <div class="val-price-row">
        <div class="val-stock-price">${_fp(d.current_price, d.currency)}</div>
        ${changeHTML}
      </div>
      <div id="val-sparkline-${d.ticker}" class="val-sparkline"></div>
    </div>
  </div>`;
}

// ── Header badge helpers ────────────────────────────────────────────

function _tagHTML(key, value, tip, cls='') {
  if (value === undefined || value === null || value === '' || value === '—') return '';
  return `<span class="val-tag ${cls}" data-tip="${_escAttr(tip)}">
    <span class="val-tag-k">${key}</span>
    <span class="val-tag-v">${value}</span>
  </span>`;
}

function _escAttr(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _betaTag(d) {
  if (d.beta === undefined || d.beta === null) return '';
  const cls = d.beta > 1.3 ? 'red' : (d.beta < 0.8 ? 'green' : '');
  const flavor = d.beta > 1.3 ? 'More volatile than market — swings harder both ways.'
               : d.beta < 0.8 ? 'Less volatile than market — defensive profile.'
               : 'Moves roughly in line with the broad market.';
  return _tagHTML('β', d.beta.toFixed(2),
    `Beta = stock's historical sensitivity to market returns.\n` +
    `β = 1.0 → moves with market. β > 1 → amplifies. β < 1 → dampens.\n\n${flavor}\n\n` +
    `Used to compute cost of equity (WACC = Rf + β × ERP).`, cls);
}

function _waccTag(d) {
  const wacc = d.wacc_suggestion;
  if (wacc === undefined || wacc === null) return '';
  const wd = d.wacc_detail || {};
  let tip;
  if (wd.ke !== undefined) {
    tip = `WACC = ${wacc}% — Weighted Average Cost of Capital\n\n` +
      `CAPM Cost of Equity (Ke):\n` +
      `  Rf ${wd.rf}% + β ${wd.beta} × ERP ${wd.erp}% = ${wd.ke}%\n\n` +
      `Cost of Debt (Kd, pre-tax): ${wd.kd_pretax}%\n` +
      `Cost of Debt (after-tax):   ${wd.kd_aftertax}%\n\n` +
      `Capital Structure:\n` +
      `  Equity weight: ${wd.weight_equity}%\n` +
      `  Debt weight:   ${wd.weight_debt}%\n` +
      `  Tax rate:      ${wd.tax_rate_pct}%\n\n` +
      `WACC = ${wd.weight_equity}% × ${wd.ke}% + ${wd.weight_debt}% × ${wd.kd_pretax}% × (1 − ${wd.tax_rate_pct}%)\n     = ${wacc}%\n\n` +
      `Country ERP (${wd.country}): ${wd.erp}%  •  Rf: ${wd.rf}% (10-yr US Treasury)`;
  } else {
    tip = `WACC = ${wacc}% — used as discount rate in DCF/EPV models.\n\nWACC breakdown unavailable — using fallback estimate.`;
  }
  const cls = wacc < 7 ? 'green' : wacc > 11 ? 'red' : '';
  return _tagHTML('WACC', `${wacc}%`, tip, cls);
}

function _peTag(d) {
  if (!d.pe_ttm || d.pe_ttm <= 0) return _tagHTML('P/E', 'n/a',
    'P/E is not meaningful (negative or zero earnings). Use EV/Sales or P/B for loss-making companies.', 'gold');
  const vs = d.sector_pe ? `\n\nSector benchmark: ~${d.sector_pe}×. ` +
    (d.pe_ttm > d.sector_pe * 1.15 ? 'Trading at a premium to peers.' :
     d.pe_ttm < d.sector_pe * 0.85 ? 'Trading at a discount to peers.' : 'In line with peers.') : '';
  const cls = d.sector_pe && d.pe_ttm < d.sector_pe * 0.85 ? 'green' :
              d.sector_pe && d.pe_ttm > d.sector_pe * 1.15 ? 'red' : '';
  return _tagHTML('P/E', `${d.pe_ttm}×`,
    `Price / trailing 12-month earnings. How many years of current profit you pay for the stock.${vs}\n\n` +
    `Low P/E can mean "cheap" OR "stagnant". High P/E means growth expectations baked in.`, cls);
}

function _psTag(d) {
  if (!d.ps_current) return '';
  const vs = d.sector_ps ? `\nSector benchmark: ~${d.sector_ps}×.` : '';
  return _tagHTML('P/S', `${d.ps_current}×`,
    `Price / Sales. Market cap divided by revenue.\n` +
    `Useful when earnings are negative (high-growth tech, biotech).${vs}\n\n` +
    `Pitfall: ignores profitability — a high P/S on thin margins can be dangerous.`);
}

function _evEbitdaTag(d) {
  if (!d.ev_ebitda_current) return '';
  const vs = d.sector_ev ? `\nSector benchmark: ~${d.sector_ev}×.` : '';
  const cls = d.sector_ev && d.ev_ebitda_current < d.sector_ev * 0.85 ? 'green' :
              d.sector_ev && d.ev_ebitda_current > d.sector_ev * 1.15 ? 'red' : '';
  return _tagHTML('EV/EBITDA', `${d.ev_ebitda_current}×`,
    `Enterprise Value / EBITDA. Capital-structure neutral — better than P/E for comparing leveraged firms.${vs}\n\n` +
    `Pitfall: strips out D&A and capex — understates cost for capital-intensive businesses.`, cls);
}

function _evEbitTag(d) {
  if (!d.ev_ebit_current) return '';
  return _tagHTML('EV/EBIT', `${d.ev_ebit_current}×`,
    `Enterprise Value / EBIT. Like EV/EBITDA but includes depreciation — penalises capex-heavy firms ` +
    `(utilities, industrials) appropriately. Closer to a "true economic earnings" multiple.`);
}

function _divTag(d) {
  if (!d.dividend_annual || d.dividend_annual <= 0) {
    return _tagHTML('Div', 'None', 'Company pays no dividend. DDM model is not applicable.', 'gold');
  }
  return _tagHTML('Div Yield', `${d.dividend_yield.toFixed(2)}%`,
    `Annual dividend $${d.dividend_annual}/share → ${d.dividend_yield.toFixed(2)}% yield at current price.\n\n` +
    `Check payout ratio & FCF coverage: unsustainably high yields often precede cuts.`, 'green');
}

function _fScoreTag(d) {
  if (d.f_score === undefined || d.f_score === null) return '';
  const f = d.f_score;
  const cls = f >= 7 ? 'green' : (f <= 3 ? 'red' : 'gold');
  const grade = f >= 7 ? 'Strong' : (f <= 3 ? 'Weak' : 'Mixed');
  return _tagHTML('F-Score', `${f}/9 · ${grade}`,
    `Piotroski F-Score — 9 binary tests on fundamentals:\n` +
    `• Profitability (NI>0, ROA>0, OCF>0, OCF>NI)\n` +
    `• Leverage/liquidity (debt↓, current ratio↑, no dilution)\n` +
    `• Efficiency (gross margin↑, asset turnover↑)\n\n` +
    `≥7 = high quality · 4–6 mixed · ≤3 weak.`, cls);
}

function _zScoreTag(d) {
  if (d.z_score === undefined || d.z_score === null) return '';
  const band = d.z_score_band || 'grey';
  const cls = band === 'safe' ? 'green' : (band === 'distress' ? 'red' : 'gold');
  const label = band === 'safe' ? 'Safe' : (band === 'distress' ? 'Distress' : 'Grey');
  return _tagHTML('Z-Score', `${d.z_score} · ${label}`,
    `Altman Z-Score — predicts bankruptcy within 2 years:\n` +
    `Z = 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MV/TL + 1.0·Sales/TA\n\n` +
    `> 2.99 = Safe · 1.81–2.99 = Grey zone · < 1.81 = Distress.\n\n` +
    `Calibrated for manufacturers — less reliable for banks / asset-light tech.`, cls);
}

function _bestMultipleTag(d) {
  if (!d.best_multiple || !d.correlations) return '';
  const name = {pe:'P/E', ps:'P/S', ev_ebitda:'EV/EBITDA', ev_ebit:'EV/EBIT'}[d.best_multiple] || d.best_multiple;
  const corr = d.correlations[d.best_multiple];
  if (corr === null || corr === undefined) return '';
  const direction = corr >= 0 ? 'positive' : 'negative';
  return _tagHTML('Best-Fit Ratio', `${name} · r=${corr.toFixed(2)}`,
    `Among the historical multiples, ${name} has the strongest ${direction} correlation ` +
    `with the stock price over time (Pearson r = ${corr.toFixed(2)}).\n\n` +
    `This is the most reliable valuation lens for this particular stock — the market has historically ` +
    `priced it off this multiple more than the others.`, 'violet');
}

function _ultimateScoreHTML(d) {
  if (d.composite_score === null || d.composite_score === undefined) return '';
  const s = d.composite_score, band = d.composite_band || 'fair';
  const label = {excellent:'Excellent', good:'Good', fair:'Fair', weak:'Weak'}[band] || 'Fair';
  const C = 2 * Math.PI * 14;   // circumference
  const dash = (s / 100) * C;
  const parts = d.composite_parts || {};
  const tip = `Ultimate Quality Score (0–100) — blended health & valuation signal.\n\n` +
    `• Fundamentals (F-Score, 40 pts): ${(parts.fundamentals ?? 0).toFixed(1)}\n` +
    `• Solvency (Z-Score, 25 pts): ${(parts.solvency ?? 0).toFixed(1)}\n` +
    `• Valuation (P/E vs history, 20 pts): ${(parts.valuation ?? 0).toFixed(1)}\n` +
    `• Growth (earnings growth, 15 pts): ${(parts.growth ?? 0).toFixed(1)}\n\n` +
    `≥75 Excellent · 55–74 Good · 40–54 Fair · <40 Weak.\n` +
    `This is a heuristic — always verify with context.`;
  return `<span class="val-ultimate ${band}" data-tip="${_escAttr(tip)}">
    <span class="val-ultimate-ring">
      <svg viewBox="0 0 32 32">
        <circle class="val-ultimate-ring-bg" cx="16" cy="16" r="14" fill="none" stroke-width="3"/>
        <circle class="val-ultimate-ring-fg" cx="16" cy="16" r="14" fill="none" stroke-width="3"
          stroke-dasharray="${dash} ${C}" stroke-linecap="round"/>
      </svg>
      <span class="val-ultimate-score-txt">${Math.round(s)}</span>
    </span>
    <span class="val-ultimate-label">
      <span class="k">Ultimate Score</span>
      <span class="v">${label}</span>
    </span>
  </span>`;
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
      ${_reverseDcfCardHTML(tk, d)}
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
  <div class="val-card" id="vcard-${tk}-${id}" data-model="${id}">
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
      <div class="val-card-actions">
        <button class="val-workings-btn" onclick="toggleWorkings('${tk}','${id}')">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h20M12 2v20"/></svg>
          Show working
        </button>
        <button class="val-workings-btn" onclick="toggleExplainer('${tk}','${id}')">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
          About this model
        </button>
      </div>
      <div class="val-workings-panel" id="wp-${tk}-${id}"></div>
      <div class="val-explainer-panel" id="ex-${tk}-${id}">${_modelExplainerHTML(id)}</div>
    </div>
  </div>`;
}

// ── Model Explainer content ─────────────────────────────────────────────
// For each model: formula, key assumptions, what to care about, pitfalls.
const _MODEL_EXPLAINERS = {
  dcf: {
    formula: "V<sub>equity</sub> = Σ FCFₜ / (1+WACC)ᵗ + TV / (1+WACC)<sup>10</sup>,  where TV = FCF₁₀·(1+g) / (WACC−g)",
    assumptions: [
      "Two-stage growth: explicit high-growth years 1–5, slower years 6–10, then perpetual terminal growth.",
      "FCF = Operating Cash Flow + CapEx (capex is negative). Represents cash available to all capital providers.",
      "WACC is used as the discount rate — assumes debt and equity holders are compensated uniformly.",
      "Terminal growth (2–3%) must stay below long-run WACC, and realistically below long-run GDP growth.",
    ],
    care: [
      "Use a normalized FCF — exclude one-off items (asset sales, tax refunds, legal settlements).",
      "Check historical FCF growth (shown in the table) to sanity-check your Stage-1 growth input.",
      "Margin of safety: even 10–20% off can protect you from parameter misjudgement.",
    ],
    pitfalls: [
      "80%+ of the DCF value typically comes from the terminal value — this model is highly sensitive to WACC and terminal g.",
      "Companies with volatile or negative FCF (early-stage, cyclical, turnaround) break the model's stability.",
      "Garbage-in-garbage-out: small tweaks in WACC (±1%) can move value ±20%. Always run sensitivity analysis.",
    ],
  },
  rdcf: {
    formula: "Solve for g such that: Price = Σ FCF·(1+g)ᵗ / (1+WACC)ᵗ + TV discounted",
    assumptions: [
      "Inverts the DCF — instead of assuming growth and solving for value, we assume value (current price) and solve for growth.",
      "Uses the same WACC and terminal growth inputs as the standard DCF.",
      "Output = the annual FCF growth rate over years 1–5 that the market is implicitly pricing in.",
    ],
    care: [
      "Compare the implied growth to consensus analyst estimates and historical growth.",
      "If implied g exceeds 20%/year, the stock is 'priced for perfection' — any stumble causes severe drawdown.",
      "If implied g is negative or near-zero, the market is pessimistic — potentially a hidden value opportunity.",
    ],
    pitfalls: [
      "Extremely sensitive to WACC — the implied growth is only meaningful if the discount rate is realistic.",
      "Doesn't account for capital structure changes, share buybacks, or new equity issuance.",
      "The solution assumes FCF stability — unstable businesses yield misleading implied growth rates.",
    ],
  },
  epv: {
    formula: "EPV = (EBIT · (1−tax)) / WACC,   Equity = EPV − Net Debt,   Per Share = Equity / Shares",
    assumptions: [
      "Assumes zero growth — values the company on its current normalized earnings power alone.",
      "EBIT should be normalized (average 5–7 years, ex one-offs) to smooth cyclicality.",
      "Deducts net debt to get equity value; divides by shares for per-share price.",
    ],
    care: [
      "Most useful for mature, stable businesses (consumer staples, utilities, industrials with moat).",
      "Compare EPV to DCF: if EPV ≈ DCF, the market is paying mostly for current earnings, not growth.",
      "Gap between EPV and DCF = value attributed to growth — 'growth premium'.",
    ],
    pitfalls: [
      "Ignores growth entirely — will systematically undervalue high-growth companies.",
      "Sensitive to WACC choice, but less so than DCF (no terminal value).",
      "A single bad year's EBIT can distort the result — always normalize.",
    ],
  },
  ddm: {
    formula: "P = D₁ / (r − g),   where D₁ = next-year dividend, r = required return, g = perpetual growth",
    assumptions: [
      "Gordon Growth Model: assumes a constant perpetual dividend growth rate.",
      "Requires r > g — the required return must exceed the dividend growth rate, or the formula diverges.",
      "Best for stable dividend payers with decades of consistent history.",
    ],
    care: [
      "Check payout ratio and FCF coverage — sustainable dividends grow out of sustainable earnings.",
      "Use a growth rate grounded in history; rarely >6–8% sustainably.",
      "For non-dividend-paying stocks, DDM is simply not applicable.",
    ],
    pitfalls: [
      "Extremely sensitive near r ≈ g — small tweaks blow up the value.",
      "Dividend policy can change (cuts, suspensions) — past stability doesn't guarantee future.",
      "Ignores buybacks, which are effectively equivalent to dividends for shareholder returns.",
    ],
  },
  pe: {
    formula: "Fair Price = EPS × Target P/E",
    assumptions: [
      "The target multiple reflects what similar-quality, similar-growth companies trade at.",
      "Assumes earnings are clean (ex non-recurring items) and representative of ongoing business.",
      "Calibrated against sector median and the stock's own historical range (see band above).",
    ],
    care: [
      "Compare to both sector P/E AND the stock's own historical percentile — context matters.",
      "Use forward EPS for forward-looking valuation; TTM EPS for current snapshot.",
      "Quality counts: a high-moat company deserves a higher P/E than an average one.",
    ],
    pitfalls: [
      "Works poorly for loss-making companies (no meaningful P/E) or cyclicals at peak earnings.",
      "Accounting differences (one-offs, tax adjustments) distort EPS and P/E.",
      "A low P/E can be a value trap — always ask 'why is the market pricing it this cheap?'",
    ],
  },
  evda: {
    formula: "Fair EV = EBITDA × Multiple,   Equity = Fair EV − Net Debt,   Per Share = Equity / Shares",
    assumptions: [
      "EV/EBITDA is capital-structure-neutral — compares companies with different debt levels fairly.",
      "EBITDA = Earnings before Interest, Tax, Depreciation, Amortization — a rough cash-flow proxy.",
      "Target multiple based on sector median adjusted for growth/quality.",
    ],
    care: [
      "Better than P/E for comparing leveraged firms (LBOs, private equity targets).",
      "Check against the stock's historical EV/EBITDA range — percentile band shown above.",
      "Cross-reference with EV/EBIT — if gap is large, the company is capital-intensive (high depreciation).",
    ],
    pitfalls: [
      "'EBITDA' strips out real costs — D&A reflects capex you'll have to repeat. Avoid for capex-heavy industries.",
      "Doesn't include working-capital changes — EBITDA ≠ Cash.",
      "Charlie Munger: 'whenever I hear EBITDA, I substitute bullshit earnings'. Use alongside FCF.",
    ],
  },
  eveb: {
    formula: "Fair EV = EBIT × Multiple,   Equity = Fair EV − Net Debt,   Per Share = Equity / Shares",
    assumptions: [
      "Like EV/EBITDA, but uses EBIT — includes depreciation as a real operating cost.",
      "More conservative than EV/EBITDA for capital-intensive businesses.",
      "Target multiple ~20% below EV/EBITDA (since EBIT < EBITDA).",
    ],
    care: [
      "Preferred over EV/EBITDA when comparing asset-heavy companies (manufacturers, telecoms, utilities).",
      "Join Greenblatt's 'Magic Formula' approach: Earnings Yield = EBIT / EV.",
      "A high EV/EBIT with high ROIC often signals a moat — quality earnings.",
    ],
    pitfalls: [
      "EBIT is affected by depreciation methods, which vary across regions and accounting standards.",
      "Still ignores interest expense, so a highly leveraged firm may look cheaper than it is on equity basis.",
      "One-off impairments can crush a single year's EBIT — normalize before using.",
    ],
  },
  ps: {
    formula: "Fair Market Cap = Revenue × Target P/S,   Per Share = Fair Market Cap / Shares",
    assumptions: [
      "Revenue is harder to manipulate than earnings — P/S is useful for unprofitable growth companies.",
      "Assumes the company's sector has a stable 'normal' sales multiple.",
      "Target P/S set around historical/sector median, not peak.",
    ],
    care: [
      "Works well for SaaS, biotech, early-stage growth companies with scalable revenue.",
      "Pair with gross margin — high P/S only justified by durable high-margin revenue.",
      "Especially powerful combined with Rule of 40 (growth + margin ≥ 40%).",
    ],
    pitfalls: [
      "Ignores profitability — $1 of revenue at 5% margin ≠ $1 at 80% margin.",
      "A high P/S on shrinking revenue is a warning sign.",
      "Can be inflated by low-quality revenue (e.g. gross billings vs net).",
    ],
  },
  peg: {
    formula: "Fair P/E = Growth Rate × Target PEG,   Fair Price = EPS × Fair P/E",
    assumptions: [
      "Peter Lynch's rule of thumb: a P/E equal to the earnings growth rate is 'fairly valued' (PEG = 1).",
      "Assumes earnings growth persists over the medium term (3–5 years).",
      "Target PEG = 1.0 typically; lower = cheaper, higher = expensive.",
    ],
    care: [
      "Best for mid-cap growth stocks with consistent double-digit earnings growth.",
      "Cross-check growth rate with historical and analyst estimates — don't trust a single year.",
      "Adjust PEG by quality: a moat or ROIC > 15% justifies a PEG slightly above 1.",
    ],
    pitfalls: [
      "Meaningless when earnings are zero or negative.",
      "Very sensitive to the growth input — a small change in g shifts fair value materially.",
      "Ignores quality of growth (organic vs acquired) and return on invested capital.",
    ],
  },
  graham: {
    formula: "Graham Number = √(22.5 × EPS × Book Value per Share)",
    assumptions: [
      "Benjamin Graham's conservative 'max price' for a defensive investor: P/E ≤ 15 and P/B ≤ 1.5, so P/E × P/B ≤ 22.5.",
      "Requires positive EPS and positive book value.",
      "Designed for stable, mature, profitable companies.",
    ],
    care: [
      "Treat the Graham Number as an upper bound of a conservative fair value, not a target.",
      "Pair with current ratio ≥ 2 and consistent earnings for Graham's full defensive screen.",
      "Works best for industrials, financials, and tangible-asset-heavy businesses.",
    ],
    pitfalls: [
      "Fails for asset-light tech/software businesses where book value is essentially zero.",
      "Doesn't account for growth — will reject many high-quality compounders.",
      "Accounting book value ≠ economic value — intangibles and goodwill distort P/B.",
    ],
  },
  ncav: {
    formula: "NCAV per Share = (Current Assets − Total Liabilities) / Shares Outstanding",
    assumptions: [
      "Deep-value Graham floor: the company's near-liquidation value.",
      "Current Assets (cash, receivables, inventory) are assumed to cover ALL liabilities (current + LT).",
      "A stock trading below 2/3 of NCAV is Graham's 'net-net' — a classic deep-value buy signal.",
    ],
    care: [
      "Most applicable to distressed micro-caps and cyclical bottoms.",
      "Pair with share-issuance screen (Piotroski F-Score tests this) to avoid dilution traps.",
      "Check receivables/inventory quality — bloated, aging AR/inventory may not be recoverable at face value.",
    ],
    pitfalls: [
      "Assumes assets can be liquidated at book value — rarely true for inventory (discounted 20–50%) or AR.",
      "Value traps: stocks stay below NCAV for years while losses compound.",
      "Extremely rare among large/mid caps — mostly a micro-cap tool.",
    ],
  },
};

function _modelExplainerHTML(id) {
  const e = _MODEL_EXPLAINERS[id];
  if (!e) return '';
  const list = (items) => items.map(i => `<li>${i}</li>`).join('');
  return `
    <div class="val-ex-section">
      <div class="val-ex-h">Formula</div>
      <div class="val-ex-formula">${e.formula}</div>
    </div>
    <div class="val-ex-section">
      <div class="val-ex-h"><span class="val-ex-dot blue"></span>Key Assumptions</div>
      <ul class="val-ex-list">${list(e.assumptions)}</ul>
    </div>
    <div class="val-ex-section">
      <div class="val-ex-h"><span class="val-ex-dot green"></span>Things to Care About</div>
      <ul class="val-ex-list">${list(e.care)}</ul>
    </div>
    <div class="val-ex-section">
      <div class="val-ex-h"><span class="val-ex-dot red"></span>Pitfalls &amp; Watch-outs</div>
      <ul class="val-ex-list">${list(e.pitfalls)}</ul>
    </div>`;
}

function toggleExplainer(tk, id) {
  const el = document.getElementById(`ex-${tk}-${id}`);
  if (el) el.classList.toggle('open');
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
  const fcfData = d.historical_fcf.slice(0, 4);  // last 4 years (newest→oldest)

  // FCF YoY row — show growth rate (%); the oldest row has no prior year so blank
  const fmtYoY = (r) => {
    if (r.yoy_pct === undefined || r.yoy_pct === null) return '<span class="val-muted">—</span>';
    const v = r.yoy_pct;
    const cls = v >= 0 ? 'pos' : 'neg';
    return `<span class="${cls}">${v >= 0 ? '+' : ''}${v.toFixed(1)}%</span>`;
  };

  // 4-year FCF CAGR summary (if we have 4+ rows)
  let cagrHTML = '';
  if (fcfData.length >= 3) {
    const newest = fcfData[0].fcf_m;
    const oldest = fcfData[fcfData.length - 1].fcf_m;
    const yrs    = fcfData.length - 1;
    if (oldest > 0 && newest > 0) {
      const cagr = (Math.pow(newest / oldest, 1 / yrs) - 1) * 100;
      const cls = cagr >= 0 ? 'pos' : 'neg';
      cagrHTML = `<div style="font-size:11px;color:var(--muted);margin-bottom:6px;">
        <strong>${yrs}-yr FCF CAGR:</strong> <span class="${cls}">${cagr >= 0 ? '+' : ''}${cagr.toFixed(1)}%/yr</span>
        · Historical growth feeds your Stage-1 & Stage-2 assumptions below.
      </div>`;
    }
  }

  const fcfHistory = fcfData.length
    ? `${cagrHTML}
       <table class="val-fcf-table">
        <thead><tr>
          <th>Year</th>
          <th>Op. CF ($M)</th>
          <th>CapEx ($M)</th>
          <th>FCF ($M)</th>
          <th title="Stock-Based Compensation added back via cashflow">SBC ($M)</th>
          <th title="Free Cash Flow minus Stock-Based Compensation — Buffett's owner earnings approximation">Owner Earnings ($M)</th>
          <th>YoY (FCF)</th>
        </tr></thead>
        <tbody>${fcfData.map(r => `
          <tr>
            <td>${r.year}</td>
            <td>${(r.op_cf_m ?? 0).toLocaleString()}</td>
            <td class="neg">${(r.capex_m ?? 0).toLocaleString()}</td>
            <td class="${r.fcf_m >= 0 ? 'pos' : 'neg'}">${r.fcf_m.toLocaleString()}</td>
            <td class="neg">${r.sbc_m ? r.sbc_m.toLocaleString() : '—'}</td>
            <td class="${(r.owner_earnings_m ?? r.fcf_m) >= 0 ? 'pos' : 'neg'}">${r.owner_earnings_m !== undefined ? r.owner_earnings_m.toLocaleString() : '—'}</td>
            <td>${fmtYoY(r)}</td>
          </tr>`).join('')}
        </tbody></table>`
    : `<div class="val-note" style="margin-bottom:8px;">No historical cash flow data available.</div>`;

  // Owner-earnings fill button helper (inline JS)
  const oeBtn = d.owner_earnings_m !== undefined
    ? `<button class="val-oe-btn" onclick="document.getElementById('${tk}-dcf-fcf').value='${d.owner_earnings_m}';document.getElementById('${tk}-dcf-fcf').dispatchEvent(new Event('input'));" title="Switch base cash flow to Owner Earnings (FCF − SBC ≈ Buffett's owner earnings)">Use Owner Earnings (${d.owner_earnings_m}M)</button>`
    : '';
  const fcffNote = `<div class="val-note" style="margin-bottom:4px;">
    Model: FCFF discounted at WACC → Enterprise Value → subtract Net Debt → Equity Value ÷ Shares.
    ${oeBtn}
  </div>`;

  // Bear / Bull defaults (Base is tied to the main inputs above)
  const g1n = parseFloat(g1), g2n = parseFloat(g2);
  const waccSugg = d.wacc_suggestion || 9;
  const bearG1   = Math.max(-5, g1n * 0.4).toFixed(1);
  const bearG2   = Math.max(-5, g2n * 0.4).toFixed(1);
  const bearWacc = (waccSugg + 2.0).toFixed(1);
  const bullG1   = Math.min(60, g1n * 1.5).toFixed(1);
  const bullG2   = Math.min(40, g2n * 1.5).toFixed(1);
  const bullWacc = Math.max(4.0, waccSugg - 1.0).toFixed(1);

  const scenarioHTML = `
    <div class="val-scenario-section">
      <div class="val-scenario-title">
        Scenarios &amp; Probability-Weighted Fair Value
        <span class="val-scenario-hint">Adjust Bear/Bull + probabilities (Base uses the inputs above)</span>
      </div>
      <table class="val-scenario-table">
        <thead>
          <tr>
            <th></th><th>g₁ %</th><th>g₂ %</th><th>Tg %</th><th>WACC %</th><th>Prob %</th><th>Fair Value</th>
          </tr>
        </thead>
        <tbody>
          <tr class="scn-bear">
            <th>🐻 Bear</th>
            <td><input type="number" id="${tk}-dcf-bear-g1"   value="${bearG1}"  step="0.5"></td>
            <td><input type="number" id="${tk}-dcf-bear-g2"   value="${bearG2}"  step="0.5"></td>
            <td><input type="number" id="${tk}-dcf-bear-tg"   value="1.5"        step="0.1"></td>
            <td><input type="number" id="${tk}-dcf-bear-wacc" value="${bearWacc}" step="0.1"></td>
            <td><input type="number" id="${tk}-dcf-bear-p"    value="25"          step="5" min="0" max="100"></td>
            <td class="scn-fv" id="res-${tk}-dcf-bear">—</td>
          </tr>
          <tr class="scn-base">
            <th>➡️ Base</th>
            <td colspan="4" class="scn-base-note">Uses main inputs above</td>
            <td><input type="number" id="${tk}-dcf-base-p"    value="50"          step="5" min="0" max="100"></td>
            <td class="scn-fv" id="res-${tk}-dcf-base">—</td>
          </tr>
          <tr class="scn-bull">
            <th>🐂 Bull</th>
            <td><input type="number" id="${tk}-dcf-bull-g1"   value="${bullG1}"  step="0.5"></td>
            <td><input type="number" id="${tk}-dcf-bull-g2"   value="${bullG2}"  step="0.5"></td>
            <td><input type="number" id="${tk}-dcf-bull-tg"   value="3.0"        step="0.1"></td>
            <td><input type="number" id="${tk}-dcf-bull-wacc" value="${bullWacc}" step="0.1"></td>
            <td><input type="number" id="${tk}-dcf-bull-p"    value="25"          step="5" min="0" max="100"></td>
            <td class="scn-fv" id="res-${tk}-dcf-bull">—</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <th colspan="5" class="scn-weighted-lbl">Probability-Weighted Fair Value</th>
            <td id="res-${tk}-dcf-pw-sum" class="scn-pw-sum">—</td>
            <td id="res-${tk}-dcf-pw" class="scn-pw">—</td>
          </tr>
        </tfoot>
      </table>
    </div>`;

  const body = `
    ${fcfHistory}
    <div id="mchart-${tk}-dcf" class="val-mchart"></div>
    ${fcffNote}
    <div class="val-inputs-grid">
      ${_inp(`${tk}-dcf-fcf`,     'FCFF — Latest Year ($M)',  d.fcff_m ?? d.fcf_total_m, 'Free Cash Flow to Firm (OCF + after-tax interest − CapEx). Drives Enterprise Value.', '1')}
      ${_inp(`${tk}-dcf-netdebt`, 'Net Debt ($M)',            d.net_debt_m, 'Total debt minus cash. Subtracted from EV to get equity value.', '1')}
      ${_inp(`${tk}-dcf-shares`,  'Shares Outstanding (M)',   d.shares_m,   'Total diluted shares outstanding', '0.1', '0.001')}
      ${_inp(`${tk}-dcf-g1`,      'Growth Yr 1–5 (%)',        g1,           'Expected annual FCFF growth, first 5 years', '0.5', '-30', '80')}
      ${_inp(`${tk}-dcf-g2`,      'Growth Yr 6–10 (%)',       g2,           'Slower growth phase, years 6–10', '0.5', '-20', '50')}
      ${_inp(`${tk}-dcf-tg`,      'Terminal Growth (%)',      '2.5',        'Perpetual growth after yr 10 (≈ GDP)', '0.1', '0', '5')}
      ${_inp(`${tk}-dcf-wacc`,    'WACC (%)',                 d.wacc_suggestion, 'Weighted avg cost of capital — discounts FCFF to Enterprise Value', '0.1', '3', '30')}
      ${_inp(`${tk}-dcf-mos`,     'Margin of Safety (%)',     '15',         'Discount applied to final equity value', '1', '0', '50')}
    </div>
    ${scenarioHTML}`;

  return _cardWrap('dcf', tk, 'Discounted Cash Flow (DCF)',
    '2-stage growth model: discount projected FCFs + terminal value back to today',
    body);
}

// 1b. Reverse DCF ──────────────────────────────────────────────────────────────
function _reverseDcfCardHTML(tk, d) {
  const body = `
    <div class="val-note" style="margin-bottom:8px;">
      Solves for the FCFF growth rate implied by today's price. Target = Price + Net Debt/Share (i.e. solves for Enterprise Value). High implied growth = priced for perfection.
    </div>
    <div class="val-inputs-grid">
      ${_inp(`${tk}-rdcf-fcf`,     'FCFF — Latest Year ($M)', d.fcff_m ?? d.fcf_total_m, 'Free Cash Flow to Firm — same as DCF base', '1')}
      ${_inp(`${tk}-rdcf-netdebt`, 'Net Debt ($M)',            d.net_debt_m, 'Added to price to target Enterprise Value', '1')}
      ${_inp(`${tk}-rdcf-shares`,  'Shares Outstanding (M)',   d.shares_m, 'Diluted shares outstanding', '0.1', '0.001')}
      ${_inp(`${tk}-rdcf-wacc`,    'WACC (%)',                 d.wacc_suggestion, 'Discount rate', '0.1', '3', '30')}
      ${_inp(`${tk}-rdcf-tg`,      'Terminal Growth (%)',      '2.5', 'Perpetual growth after yr 10', '0.1', '0', '5')}
    </div>
    <div class="val-two-results">
      <div class="val-two-item"><span class="val-two-label">Implied 5-yr Growth</span><span class="val-card-result sml" id="res-${tk}-rdcf-g">—</span></div>
      <div class="val-two-item"><span class="val-two-label">Interpretation</span><span class="val-card-result sml" id="res-${tk}-rdcf-note" style="font-size:11px;">—</span></div>
    </div>
    <div id="rdcf-extras-${tk}" class="val-rdcf-extras"></div>`;
  return _cardWrap('rdcf', tk, 'Reverse DCF (Implied Growth)',
    'Inverts the DCF: given today\u2019s price, what FCF growth is baked in? Plus TV-share gauge and implied-g sensitivity curve.',
    body);
}

// 2. EPV ───────────────────────────────────────────────────────────────────────
function _epvCardHTML(tk, d) {
  const body = `
    <div id="mchart-${tk}-epv" class="val-mchart"></div>
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
    <div id="mchart-${tk}-ddm" class="val-mchart"></div>
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
    <div id="mchart-${tk}-pe" class="val-mchart"></div>
    ${_historicalBandHTML(tk, 'pe')}
    <div class="val-inputs-grid col2">
      ${_inp(`${tk}-pe-epsttm`, 'EPS TTM ($)', d.eps_ttm,    'Trailing twelve months earnings per share', '0.01')}
      ${_inp(`${tk}-pe-epsfwd`, 'EPS Forward ($)', d.eps_forward, 'Next twelve months consensus estimate', '0.01')}
      ${_inp(`${tk}-pe-multtm`, 'Target P/E (TTM)', d.sector_pe, 'Sector / historical fair P/E multiple', '0.5', '1')}
      ${_inp(`${tk}-pe-mulfwd`, 'Target P/E (Fwd)', fwdPe,   'Forward P/E to apply to next-year earnings', '0.5', '1')}
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
    <div id="mchart-${tk}-evda" class="val-mchart"></div>
    ${_historicalBandHTML(tk, 'evda')}
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
    <div id="mchart-${tk}-eveb" class="val-mchart"></div>
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
    <div id="mchart-${tk}-ps" class="val-mchart"></div>
    ${_historicalBandHTML(tk, 'ps')}
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
    <div id="mchart-${tk}-peg" class="val-mchart"></div>
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
    <div id="mchart-${tk}-graham" class="val-mchart"></div>
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
    <div id="mchart-${tk}-ncav" class="val-mchart"></div>
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

// ── Historical percentile bands ──────────────────────────────────────────────

function _historicalBandHTML(tk, modelId) {
  return `
  <div class="val-hband" id="hband-${tk}-${modelId}" style="display:none;">
    <div class="val-hband-label">
      <span id="hband-${tk}-${modelId}-title">Historical range</span>
      <span id="hband-${tk}-${modelId}-pct"></span>
    </div>
    <div class="val-hband-bar">
      <div class="val-hband-fill" id="hband-${tk}-${modelId}-fill"></div>
      <div class="val-hband-marker" id="hband-${tk}-${modelId}-marker"></div>
    </div>
    <div class="val-hband-range">
      <span id="hband-${tk}-${modelId}-min"></span>
      <span id="hband-${tk}-${modelId}-med"></span>
      <span id="hband-${tk}-${modelId}-max"></span>
    </div>
  </div>`;
}

function _setHistoricalBand(tk, modelId, history, key, current, suffix) {
  const el = document.getElementById(`hband-${tk}-${modelId}`);
  if (!el) return;
  if (!history || history.length < 3 || !current) { el.style.display = 'none'; return; }
  const vals = history.map(h => h[key]).filter(v => v && v > 0).sort((a,b)=>a-b);
  if (vals.length < 3) { el.style.display = 'none'; return; }
  const mn = vals[0], mx = vals[vals.length-1];
  const med = vals[Math.floor(vals.length/2)];
  const below = vals.filter(v => v <= current).length;
  const pct = Math.round((below / vals.length) * 100);
  const clamped = Math.max(0, Math.min(100, ((current - mn) / (mx - mn || 1)) * 100));
  const band = pct <= 33 ? 'green' : (pct >= 67 ? 'red' : 'gold');
  const fmt = v => `${v.toFixed(1)}${suffix}`;
  el.style.display = '';
  el.className = `val-hband ${band}`;
  document.getElementById(`hband-${tk}-${modelId}-pct`).textContent   = `${pct}th percentile · now ${fmt(current)}`;
  document.getElementById(`hband-${tk}-${modelId}-min`).textContent   = `min ${fmt(mn)}`;
  document.getElementById(`hband-${tk}-${modelId}-med`).textContent   = `median ${fmt(med)}`;
  document.getElementById(`hband-${tk}-${modelId}-max`).textContent   = `max ${fmt(mx)}`;
  document.getElementById(`hband-${tk}-${modelId}-marker`).style.left = `${clamped}%`;
  document.getElementById(`hband-${tk}-${modelId}-fill`).style.width  = `${clamped}%`;
}

// ── Calculations ──────────────────────────────────────────────────────────────

function _recalcTicker(tk) {
  const d = _vStocks[tk]?.data;
  if (!d) return;
  const price = d.current_price;
  const cur   = d.currency;

  const results = {};

  // DCF
  const dcfFcf     = _gv(`${tk}-dcf-fcf`);
  const dcfNetDebt = _gv(`${tk}-dcf-netdebt`);  // $M
  const dcfShares  = Math.max(_gv(`${tk}-dcf-shares`), 0.001);
  const dcfFcfPs   = dcfShares > 0 ? (dcfFcf    * 1e6) / (dcfShares * 1e6) : 0;
  const dcfNdPs    = dcfShares > 0 ? (dcfNetDebt * 1e6) / (dcfShares * 1e6) : 0;
  const dcfG1   = _gv(`${tk}-dcf-g1`)   / 100;
  const dcfG2   = _gv(`${tk}-dcf-g2`)   / 100;
  const dcfTg   = _gv(`${tk}-dcf-tg`)   / 100;
  const dcfWacc = _gv(`${tk}-dcf-wacc`) / 100;
  const dcfMos  = _gv(`${tk}-dcf-mos`)  / 100;
  results.dcf = _calcDCF(dcfFcfPs, dcfG1, dcfG2, dcfTg, dcfWacc, dcfMos, dcfNdPs);
  _setResult(`res-${tk}-dcf`, results.dcf, cur);
  _setUD(`ud-${tk}-dcf`, results.dcf, price);
  _setDCFWorkings(tk, dcfFcfPs, dcfG1, dcfG2, dcfTg, dcfWacc, dcfMos, results.dcf, cur, dcfNdPs, price);

  // DCF Scenarios (Bear / Base / Bull) & probability-weighted fair value
  _recalcDCFScenarios(tk, dcfFcfPs, dcfG1, dcfG2, dcfTg, dcfWacc, dcfMos, dcfNdPs, results.dcf, cur);

  // Reverse DCF — solves for implied growth, NOT added to `results` (excluded from compare chart)
  const rdFcf     = _gv(`${tk}-rdcf-fcf`);
  const rdNetDebt = _gv(`${tk}-rdcf-netdebt`);
  const rdSh      = Math.max(_gv(`${tk}-rdcf-shares`), 0.001);
  const rdFcfPs   = rdSh > 0 ? (rdFcf    * 1e6) / (rdSh * 1e6) : 0;
  const rdNdPs    = rdSh > 0 ? (rdNetDebt * 1e6) / (rdSh * 1e6) : 0;
  const rdWacc  = _gv(`${tk}-rdcf-wacc`) / 100;
  const rdTg    = _gv(`${tk}-rdcf-tg`)   / 100;
  const revRes  = _calcReverseDCF(rdFcfPs, rdWacc, rdTg, price, rdNdPs);
  const impliedG = revRes ? revRes.g : null;
  const revTvShare = revRes ? revRes.tvShare : null;
  const gEl = document.getElementById(`res-${tk}-rdcf-g`);
  const nEl = document.getElementById(`res-${tk}-rdcf-note`);
  const mainEl = document.getElementById(`res-${tk}-rdcf`);
  if (impliedG === null) {
    if (gEl) gEl.textContent = 'N/A';
    if (nEl) { nEl.textContent = 'Cannot solve'; nEl.className = 'val-card-result sml'; }
    if (mainEl) { mainEl.textContent = '—'; mainEl.className = 'val-card-result'; }
  } else {
    const pct = impliedG * 100;
    const txt = `${pct.toFixed(1)}%`;
    let note, cls;
    if (pct < 0)       { note = 'Undervalued (decline priced in)'; cls = 'green'; }
    else if (pct < 8)  { note = 'Modest expectations';             cls = 'green'; }
    else if (pct < 15) { note = 'Solid growth expected';           cls = ''; }
    else if (pct < 25) { note = 'Aggressive expectations';         cls = 'gold'; }
    else               { note = 'Priced for perfection';           cls = 'red'; }
    if (gEl) { gEl.textContent = txt; gEl.className = `val-card-result sml ${cls}`; }
    if (nEl) { nEl.textContent = note; nEl.className = `val-card-result sml ${cls}`; }
    if (mainEl) { mainEl.textContent = txt; mainEl.className = `val-card-result ${cls}`; }
  }
  _setReverseDCFExtras(tk, rdFcfPs, rdWacc, rdTg, price, rdNdPs, revTvShare, cur);
  const udEl = document.getElementById(`ud-${tk}-rdcf`);
  if (udEl) udEl.innerHTML = '';

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

function _calcDCFBreakdown(fcffPs, g1, g2, tg, wacc, mos, netDebtPerShare) {
  // Full decomposition: returns PV tranches, EV, equity, TV-share and final fair value.
  if (!fcffPs || wacc <= tg || wacc <= 0) return null;
  let pv5 = 0, pv10 = 0, cf = fcffPs;
  const yr5 = [], yr10 = [];
  for (let y = 1; y <= 5;  y++) { cf *= (1 + g1); pv5  += cf/Math.pow(1+wacc,y); yr5.push(cf); }
  for (let y = 6; y <= 10; y++) { cf *= (1 + g2); pv10 += cf/Math.pow(1+wacc,y); yr10.push(cf); }
  const tv   = (cf * (1 + tg)) / (wacc - tg);
  const pvTv = tv / Math.pow(1 + wacc, 10);
  const ev   = pv5 + pv10 + pvTv;
  const equityPs  = ev - (netDebtPerShare || 0);
  const fairValue = equityPs > 0 ? r2(equityPs * (1 - (mos || 0))) : null;
  return {
    fairValue, ev, equityPs, pv5, pv10, pvTv, tv, cf10: cf,
    tvShare: ev > 0 ? pvTv / ev : 0,
    yr5, yr10,
  };
}

function _calcDCF(fcffPs, g1, g2, tg, wacc, mos, netDebtPerShare) {
  const b = _calcDCFBreakdown(fcffPs, g1, g2, tg, wacc, mos, netDebtPerShare);
  return b ? b.fairValue : null;
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

function _calcReverseDCF(fcffPs, wacc, tg, targetPrice, netDebtPerShare) {
  // Bisects over g to find growth rate that makes DCF EV/share equal to
  // targetPrice + netDebtPerShare. Returns {g, tvShare, evPs} or null.
  if (!fcffPs || fcffPs <= 0 || wacc <= tg || wacc <= 0 || !targetPrice || targetPrice <= 0) return null;
  const targetEV = targetPrice + (netDebtPerShare || 0);
  let lo = -0.30, hi = 1.00;
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2;
    const g1 = mid, g2 = mid * 0.6;
    let pv = 0, cf = fcffPs;
    for (let y = 1; y <= 5;  y++) { cf *= (1 + g1); pv += cf / Math.pow(1 + wacc, y); }
    for (let y = 6; y <= 10; y++) { cf *= (1 + g2); pv += cf / Math.pow(1 + wacc, y); }
    const tv = (cf * (1 + tg)) / (wacc - tg);
    pv += tv / Math.pow(1 + wacc, 10);
    if (pv > targetEV) hi = mid; else lo = mid;
  }
  const g = (lo + hi) / 2;
  if (g <= -0.299 || g >= 0.999) return null;
  // Now re-run at the solution to compute TV share
  const b = _calcDCFBreakdown(fcffPs, g, g * 0.6, tg, wacc, 0, netDebtPerShare);
  if (!b) return { g, tvShare: 0, evPs: targetEV };
  return { g, tvShare: b.tvShare, evPs: b.ev };
}

// ── B1: DCF scenarios & probability-weighted fair value ──────────────────────

function _recalcDCFScenarios(tk, fcffPs, baseG1, baseG2, baseTg, baseWacc, mos, ndPs, baseFV, cur) {
  // Bear / Bull read from scenario inputs; Base uses the main DCF inputs.
  const read = (suffix) => {
    const bG1 = _gv(`${tk}-dcf-${suffix}-g1`)   / 100;
    const bG2 = _gv(`${tk}-dcf-${suffix}-g2`)   / 100;
    const bTg = _gv(`${tk}-dcf-${suffix}-tg`)   / 100;
    const bW  = _gv(`${tk}-dcf-${suffix}-wacc`) / 100;
    const bP  = Math.max(0, _gv(`${tk}-dcf-${suffix}-p`));
    const b   = _calcDCFBreakdown(fcffPs, bG1, bG2, bTg, bW, mos, ndPs);
    return { fv: b ? b.fairValue : null, p: bP };
  };
  const bear = read('bear');
  const bull = read('bull');
  const baseP = Math.max(0, _gv(`${tk}-dcf-base-p`));
  const base  = { fv: baseFV, p: baseP };

  const fmtFV = (fv) => (fv === null || fv === undefined) ? '—' : _fp(fv, cur);
  const set = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
  set(`res-${tk}-dcf-bear`, fmtFV(bear.fv));
  set(`res-${tk}-dcf-base`, fmtFV(base.fv));
  set(`res-${tk}-dcf-bull`, fmtFV(bull.fv));

  // Probability-weighted fair value (normalized if probs don't sum to 100)
  const totP = bear.p + base.p + bull.p;
  const sumEl = document.getElementById(`res-${tk}-dcf-pw-sum`);
  if (sumEl) {
    sumEl.textContent = `Σp=${totP.toFixed(0)}%`;
    sumEl.className = 'scn-pw-sum ' + (Math.abs(totP - 100) < 1 ? 'ok' : 'warn');
  }
  const pwEl = document.getElementById(`res-${tk}-dcf-pw`);
  if (!pwEl) return;
  if (totP <= 0 || (bear.fv === null && base.fv === null && bull.fv === null)) {
    pwEl.textContent = '—';
    return;
  }
  let weighted = 0, weightUsed = 0;
  for (const s of [bear, base, bull]) {
    if (s.fv !== null && s.fv !== undefined) {
      weighted  += s.fv * (s.p / totP);
      weightUsed += (s.p / totP);
    }
  }
  // Re-normalize if some scenarios failed
  if (weightUsed > 0) weighted = weighted / weightUsed;
  pwEl.textContent = _fp(r2(weighted), cur);
}

// ── B2: Reverse-DCF extras (implied-g curve + TV-share gauge) ────────────────

function _setReverseDCFExtras(tk, fcffPs, wacc, tg, price, ndPs, tvShare, cur) {
  const el = document.getElementById(`rdcf-extras-${tk}`); if (!el) return;
  if (!fcffPs || fcffPs <= 0 || !price || price <= 0) { el.innerHTML = ''; return; }

  // Implied-g curve: re-solve at WACC ± 2pp (5 points)
  const waccs = [-2, -1, 0, 1, 2].map(d => wacc + d/100);
  const rows  = waccs.map(w => {
    const r = _calcReverseDCF(fcffPs, w, tg, price, ndPs);
    const g = r ? r.g : null;
    const tv = r ? r.tvShare : null;
    const isCur = Math.abs(w - wacc) < 1e-6;
    let cls = 'impl-row' + (isCur ? ' impl-current' : '');
    let gCls = '';
    if (g !== null) {
      const pct = g * 100;
      if (pct > 25) gCls = 'red';
      else if (pct > 15) gCls = 'gold';
      else if (pct >= 0) gCls = '';
      else gCls = 'green';
    }
    const gTxt = g === null ? 'N/A' : `${(g*100).toFixed(1)}%`;
    const tvTxt = tv === null ? '—' : `${(tv*100).toFixed(0)}%`;
    return `<tr class="${cls}">
      <td>${(w*100).toFixed(1)}%</td>
      <td class="${gCls}"><strong>${gTxt}</strong></td>
      <td>${tvTxt}</td>
    </tr>`;
  }).join('');

  // TV-share gauge: 0–100% with shaded bar + warning at >80%
  const tvPct = tvShare !== null && tvShare !== undefined ? (tvShare * 100) : null;
  const tvGauge = tvPct === null ? '' : `
    <div class="val-tv-gauge">
      <div class="val-tv-label">
        <span>Terminal-Value Share of Intrinsic Value</span>
        <span class="val-tv-pct ${tvPct > 80 ? 'red' : tvPct > 60 ? 'gold' : 'green'}">${tvPct.toFixed(0)}%</span>
      </div>
      <div class="val-tv-bar">
        <div class="val-tv-fill ${tvPct > 80 ? 'red' : tvPct > 60 ? 'gold' : 'green'}" style="width:${Math.min(100,tvPct)}%"></div>
        <div class="val-tv-80line" title="80% threshold — priced-for-perfection zone"></div>
      </div>
      ${tvPct > 80
        ? `<div class="val-tv-warn">⚠ Over 80% of intrinsic value comes from the terminal value — highly sensitive to WACC &amp; terminal g. Reliable only if growth endures for decades.</div>`
        : tvPct > 60
          ? `<div class="val-tv-note">Most of the value is long-dated — verify the moat story.</div>`
          : `<div class="val-tv-note">Majority of value from near-term cash flows — less sensitive to terminal assumptions.</div>`
      }
    </div>`;

  el.innerHTML = `
    ${tvGauge}
    <div class="val-impl-wrap">
      <div class="val-impl-title">Implied Growth Curve (bisected across WACC ± 2pp)</div>
      <table class="val-impl-table">
        <thead><tr><th>WACC</th><th>Implied g</th><th>TV share</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="val-impl-note">
        Reverse DCF is most honest when read as a <em>curve</em>, not a point.
        A small change in WACC can swing the implied growth by several points.
      </div>
    </div>`;
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

function _setDCFWorkings(tk, fcfPs, g1, g2, tg, wacc, mos, result, cur, netDebtPerShare, price) {
  const el = document.getElementById(`wp-${tk}-dcf`); if (!el) return;
  if (!result) { el.innerHTML = '<div style="color:var(--muted)">Cannot compute — check inputs.</div>'; return; }
  const ndPs = netDebtPerShare || 0;
  const b = _calcDCFBreakdown(fcfPs, g1, g2, tg, wacc, mos, ndPs);
  if (!b) { el.innerHTML = '<div style="color:var(--muted)">Cannot compute — check inputs.</div>'; return; }
  const tvPct = (b.tvShare * 100);
  const tvWarn = tvPct > 80
    ? `<span class="val-warn-inline">⚠ ${tvPct.toFixed(0)}% of value from Terminal → priced for perfection</span>`
    : `<span style="color:var(--muted)">${tvPct.toFixed(0)}% of EV comes from Terminal Value</span>`;

  const stepsHTML = _steps([
    ['1', `Base FCFF/share = ${_fp(fcfPs, cur)}`, 'Free Cash Flow to Firm per share — before debt service'],
    ['2', `Year 1–5 FCFFs: ${b.yr5.map(v=>_fp(v,cur)).join(', ')}`, `Growing at ${(g1*100).toFixed(1)}% / yr → PV sum = ${_fp(b.pv5, cur)}`],
    ['3', `Year 6–10 FCFFs: ${b.yr10.map(v=>_fp(v,cur)).join(', ')}`, `Slowing to ${(g2*100).toFixed(1)}% / yr → PV sum = ${_fp(b.pv10, cur)}`],
    ['4', `Terminal Value (yr 10) = ${_fp(b.cf10,cur)} × (1+${(tg*100).toFixed(1)}%) ÷ (${(wacc*100).toFixed(1)}%−${(tg*100).toFixed(1)}%) = ${_fp(b.tv, cur)}`, `PV(TV) = ${_fp(b.pvTv, cur)} · ${tvWarn}`],
    ['5', `Enterprise Value / share = ${_fp(b.pv5,cur)} + ${_fp(b.pv10,cur)} + ${_fp(b.pvTv,cur)} = ${_fp(b.ev, cur)}`, 'Sum of discounted FCFFs + terminal value'],
    ['6', `Equity Value / share = EV − Net Debt/share = ${_fp(b.ev,cur)} − ${_fp(ndPs,cur)} = ${_fp(b.equityPs, cur)}`, 'EV → Equity bridge'],
    ['7', `After ${(mos*100).toFixed(0)}% margin of safety: ${_fp(b.equityPs,cur)} × ${(1-mos).toFixed(2)} = ${_fp(b.fairValue, cur)}`, 'Final DCF fair value'],
  ]);

  // 5×5 sensitivity grid: WACC rows × Terminal-g cols → fair value
  const waccSteps = [-2, -1, 0, 1, 2].map(d => wacc + d/100);
  const tgSteps   = [-1, -0.5, 0, 0.5, 1].map(d => Math.max(0, tg + d/100));
  const gridRows = waccSteps.map(w => {
    const cells = tgSteps.map(t => {
      const bb = _calcDCFBreakdown(fcfPs, g1, g2, t, w, mos, ndPs);
      const fv = bb ? bb.fairValue : null;
      if (fv === null || fv === undefined) return `<td class="val-sens-cell">—</td>`;
      // Colour relative to price: >20% above price = green, >20% below = red
      let cls = 'val-sens-cell';
      if (price && price > 0) {
        const ratio = fv / price;
        if (ratio >= 1.20) cls += ' sens-green';
        else if (ratio >= 1.05) cls += ' sens-pos';
        else if (ratio >= 0.95) cls += ' sens-neutral';
        else if (ratio >= 0.80) cls += ' sens-neg';
        else cls += ' sens-red';
      }
      const marker = (Math.abs(w - wacc) < 1e-6 && Math.abs(t - tg) < 1e-6) ? ' sens-current' : '';
      return `<td class="${cls}${marker}" title="WACC ${(w*100).toFixed(1)}% · Tg ${(t*100).toFixed(1)}% → ${_fp(fv,cur)}${price?' ('+((fv/price-1)*100).toFixed(0)+'% vs price)':''}">${_fp(fv, cur)}</td>`;
    }).join('');
    return `<tr><th class="val-sens-rowhdr">${(w*100).toFixed(1)}%</th>${cells}</tr>`;
  }).join('');
  const gridHTML = `
    <div class="val-sens-wrap">
      <div class="val-sens-title">Sensitivity: Fair Value (WACC × Terminal-g)</div>
      <table class="val-sens-table">
        <thead><tr><th class="val-sens-corner">WACC ↓ / Tg →</th>${tgSteps.map(t=>`<th>${(t*100).toFixed(1)}%</th>`).join('')}</tr></thead>
        <tbody>${gridRows}</tbody>
      </table>
      <div class="val-sens-legend">
        <span class="legend-sw sens-red"></span>&lt;−20% vs price
        <span class="legend-sw sens-neg"></span>−5 to −20%
        <span class="legend-sw sens-neutral"></span>±5%
        <span class="legend-sw sens-pos"></span>+5 to +20%
        <span class="legend-sw sens-green"></span>&gt;+20%
        · Bordered cell = current inputs
      </div>
    </div>`;

  el.innerHTML = stepsHTML + gridHTML;
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
    if (_vModelSettings[key] === false) continue;
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
// MODEL MINI CHARTS  (historical valuation multiples — TIKR-style)
// ══════════════════════════════════════════════════════════════════════════════

// Shared compact Plotly layout
function _mLayout(yTitle, showLegend) {
  return {
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    font:  {color: '#64748b', size: 9},
    margin: {t: 8, r: 10, b: 30, l: 46},
    xaxis: {
      gridcolor: '#1a2236', zerolinewidth: 0, fixedrange: true,
      tickfont: {size: 9, color: '#64748b'}, dtick: 1,
    },
    yaxis: {
      gridcolor: '#1a2236', zerolinewidth: 0, fixedrange: true,
      tickfont: {size: 9, color: '#64748b'},
      title: {text: yTitle, font: {size: 8, color: '#475569'}},
    },
    showlegend: !!showLegend,
    legend: {orientation: 'h', y: -0.32, x: 0.5, xanchor: 'center',
             font: {size: 8}, bgcolor: 'transparent'},
  };
}

const _mConf = {displayModeBar: false, responsive: true};

function _meanLine(pts, valKey, color) {
  if (pts.length < 2) return null;
  const avg = pts.reduce((s, r) => s + r[valKey], 0) / pts.length;
  const x0 = pts[0].year, x1 = pts[pts.length - 1].year;
  return {
    type: 'scatter', mode: 'lines',
    x: [x0, x1], y: [avg, avg],
    line: {color: color || '#f59e0b', width: 1.5, dash: 'dot'},
    name: `Avg ${avg.toFixed(1)}×`,
    hovertemplate: `Avg: ${avg.toFixed(1)}×<extra></extra>`,
  };
}

// Dual-axis layout: ratio on left (y1), price on right (y2).
function _mLayoutDual(yTitle, corr, highlight) {
  const base = _mLayout(yTitle, true);
  base.margin = {t: 22, r: 48, b: 32, l: 46};
  base.yaxis2 = {
    gridcolor: 'transparent',
    zerolinewidth: 0,
    fixedrange: true,
    tickfont: {size: 9, color: '#64748b'},
    title: {text: 'Price', font: {size: 8, color: '#475569'}},
    overlaying: 'y',
    side: 'right',
  };
  if (corr !== null && corr !== undefined) {
    const color = Math.abs(corr) >= 0.7 ? '#10b981'
                : Math.abs(corr) >= 0.4 ? '#f59e0b'
                : '#94a3b8';
    const prefix = highlight ? '★ ' : '';
    base.annotations = [{
      xref: 'paper', yref: 'paper', x: 0, y: 1.12, xanchor: 'left',
      text: `${prefix}Pearson r = <b>${corr.toFixed(2)}</b>`,
      showarrow: false,
      font: {size: 10, color: color, family: 'inherit'},
      bgcolor: 'rgba(0,0,0,0)',
    }];
  }
  return base;
}

// Dual-axis ratio + price overlay (used for P/E, EV/EBITDA, EV/EBIT, P/S).
function _renderDualAxisRatio(elId, history, ratioKey, ratioLabel, ratioColor, corr, highlight) {
  if (!history || history.length < 2) return;
  const el = document.getElementById(elId);
  if (!el) return;

  const traces = [
    {
      type: 'scatter', mode: 'lines+markers',
      x: history.map(r => r.year),
      y: history.map(r => r[ratioKey]),
      line: {color: ratioColor, width: 2.5},
      marker: {size: 5, color: ratioColor},
      name: ratioLabel,
      yaxis: 'y',
      hovertemplate: `%{x}: ${ratioLabel} %{y:.2f}×<extra></extra>`,
    },
    {
      type: 'scatter', mode: 'lines',
      x: history.map(r => r.year),
      y: history.map(r => r.price),
      line: {color: 'rgba(148,163,184,.7)', width: 2, dash: 'solid'},
      name: 'Price',
      yaxis: 'y2',
      hovertemplate: `%{x}: $%{y:.2f}<extra></extra>`,
    },
  ];
  const ml = _meanLine(history, ratioKey, '#f59e0b');
  if (ml) { ml.yaxis = 'y'; traces.push(ml); }

  Plotly.react(elId, traces, _mLayoutDual(`${ratioLabel} (×)`, corr, highlight), _mConf);
}

function _renderSparkline(tk, d) {
  const el = document.getElementById(`val-sparkline-${tk}`);
  const ph = d.price_history || [];
  if (!el || ph.length < 2) return;
  const dates = ph.map(p => p.date);
  const closes = ph.map(p => p.close);
  const up = closes[closes.length-1] >= closes[0];
  const col = up ? '#10b981' : '#ef4444';
  Plotly.react(el, [{
    type: 'scatter', mode: 'lines',
    x: dates, y: closes,
    line: {color: col, width: 2, shape: 'spline'},
    fill: 'tozeroy',
    fillcolor: up ? 'rgba(16,185,129,.08)' : 'rgba(239,68,68,.08)',
    hovertemplate: '%{x}<br>%{y:.2f}<extra></extra>',
  }], {
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    font: {color: '#64748b', size: 9},
    margin: {t: 4, r: 8, b: 20, l: 40},
    xaxis: {showgrid: false, zeroline: false, fixedrange: true,
            tickfont: {size: 8}, nticks: 5},
    yaxis: {showgrid: false, zeroline: false, fixedrange: true,
            tickfont: {size: 8}, tickprefix: d.currency === 'USD' ? '$' : ''},
    showlegend: false,
  }, {displayModeBar: false, responsive: true});
}

// ── AI Business Analysis ─────────────────────────────────────────────────────

const _aiCache = {};  // ticker → analysis result

async function _fetchAIAnalysis(tk, d) {
  const container = document.getElementById(`val-ai-${tk}`);
  if (!container) return;

  // Use cache if available
  if (_aiCache[tk]) {
    _renderAIAnalysis(container, tk, _aiCache[tk]);
    return;
  }

  try {
    const resp = await fetch('/api/valuation/analysis', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        ticker: tk,
        financials: {
          name: d.name, sector: d.sector, industry: d.industry,
          market_cap_fmt: d.market_cap_fmt, revenue_m: d.revenue_m,
          ebitda_m: d.ebitda_m, ebit_m: d.ebit_m, pe_ttm: d.pe_ttm,
          ev_ebitda_current: d.ev_ebitda_current, beta: d.beta,
          business_summary: (d.business_summary || '').slice(0, 500),
        },
      }),
    });
    const data = await resp.json();
    if (data.error) {
      container.style.display = 'none';
      return;
    }
    _aiCache[tk] = data;
    _renderAIAnalysis(container, tk, data);
  } catch (e) {
    container.style.display = 'none';
  }
}

function _renderAIAnalysis(container, tk, a) {
  const swot = a.swot || {};
  const bullets = arr => (arr || []).map(b => `<li>${b}</li>`).join('');

  const moatCls = (a.moat_rating || '').toLowerCase() === 'wide' ? 'green'
    : (a.moat_rating || '').toLowerCase() === 'narrow' ? 'gold' : 'red';
  const govCls = (a.governance_rating || '').toLowerCase() === 'strong' ? 'green'
    : (a.governance_rating || '').toLowerCase() === 'average' ? 'gold' : 'red';

  container.innerHTML = `
    <div class="val-ai-grid">
      <div class="val-ai-card">
        <div class="val-ai-card-hd">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
          Business Model
        </div>
        <div class="val-ai-card-body">${a.business_model || 'N/A'}</div>
      </div>
      <div class="val-ai-card">
        <div class="val-ai-card-hd">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          Revenue Segments
        </div>
        <div class="val-ai-card-body">${a.revenue_segments || 'N/A'}</div>
      </div>
      <div class="val-ai-card val-ai-card-wide">
        <div class="val-ai-card-hd">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18M3 12h18"/></svg>
          SWOT Analysis
        </div>
        <div class="val-swot-grid">
          <div class="val-swot-quad s"><div class="val-swot-title">Strengths</div><ul>${bullets(swot.strengths)}</ul></div>
          <div class="val-swot-quad w"><div class="val-swot-title">Weaknesses</div><ul>${bullets(swot.weaknesses)}</ul></div>
          <div class="val-swot-quad o"><div class="val-swot-title">Opportunities</div><ul>${bullets(swot.opportunities)}</ul></div>
          <div class="val-swot-quad t"><div class="val-swot-title">Threats</div><ul>${bullets(swot.threats)}</ul></div>
        </div>
      </div>
      <div class="val-ai-card">
        <div class="val-ai-card-hd">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          Economic Moat
          <span class="val-chip ${moatCls}" style="margin-left:auto;font-size:9px;">${a.moat_rating || '?'}</span>
        </div>
        <div class="val-ai-card-body">${a.moat || 'N/A'}</div>
      </div>
      <div class="val-ai-card">
        <div class="val-ai-card-hd">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          Governance
          <span class="val-chip ${govCls}" style="margin-left:auto;font-size:9px;">${a.governance_rating || '?'}</span>
        </div>
        <div class="val-ai-card-body">${a.governance || 'N/A'}</div>
      </div>
    </div>
    <div class="val-ai-disclaimer">AI-generated analysis via Gemini. Verify independently before making investment decisions.</div>
  `;
}

function _renderModelCharts(tk, d) {
  // ── DCF: FCF bar chart (last 4 years) ─────────────────────────────────
  const fcf = (d.historical_fcf || []).slice(0, 4).reverse();
  if (fcf.length >= 2 && document.getElementById(`mchart-${tk}-dcf`)) {
    const vals = fcf.map(r => r.fcf_m);
    Plotly.react(`mchart-${tk}-dcf`, [{
      type: 'bar', x: fcf.map(r => r.year), y: vals,
      marker: {
        color: vals.map(v => v >= 0 ? 'rgba(16,185,129,.75)' : 'rgba(239,68,68,.75)'),
        line: {width: 0},
      },
      hovertemplate: '%{x}: $%{y:.0f}M<extra></extra>',
    }], _mLayout('FCF ($M)'), _mConf);
  }

  // ── EPV: EBIT bar chart ───────────────────────────────────────────────
  const ebitH = d.ebit_annual || [];
  if (ebitH.length >= 2 && document.getElementById(`mchart-${tk}-epv`)) {
    Plotly.react(`mchart-${tk}-epv`, [{
      type: 'bar', x: ebitH.map(r => r.year), y: ebitH.map(r => r.ebit_m),
      marker: {color: 'rgba(99,102,241,.7)', line: {width: 0}},
      hovertemplate: '%{x}: $%{y:.0f}M<extra></extra>',
    }], _mLayout('EBIT ($M)'), _mConf);
  }

  // ── DDM: Dividend history bars ────────────────────────────────────────
  const divH = d.dividend_history || [];
  if (divH.length >= 2 && document.getElementById(`mchart-${tk}-ddm`)) {
    Plotly.react(`mchart-${tk}-ddm`, [{
      type: 'bar', x: divH.map(r => r.year), y: divH.map(r => r.dividend),
      marker: {color: 'rgba(245,158,11,.75)', line: {width: 0}},
      hovertemplate: '%{x}: $%{y:.2f}/share<extra></extra>',
    }], _mLayout('Div/Share ($)'), _mConf);
  }

  // ── P/E: dual-axis ratio + price overlay ──────────────────────────────
  const corrs = d.correlations || {};
  const best   = d.best_multiple;
  const peH = d.pe_history || [];
  if (peH.length >= 2) {
    _renderDualAxisRatio(`mchart-${tk}-pe`, peH, 'pe', 'TTM P/E',
      '#6366f1', corrs.pe, best === 'pe');
  }

  // ── EV/EBITDA: dual-axis ratio + price overlay ────────────────────────
  const evdaH = d.ev_ebitda_history || [];
  if (evdaH.length >= 2) {
    _renderDualAxisRatio(`mchart-${tk}-evda`, evdaH, 'ev_ebitda', 'EV/EBITDA',
      '#10b981', corrs.ev_ebitda, best === 'ev_ebitda');
  }

  // ── EV/EBIT: dual-axis ratio + price overlay ──────────────────────────
  const evebH = d.ev_ebit_history || [];
  if (evebH.length >= 2) {
    _renderDualAxisRatio(`mchart-${tk}-eveb`, evebH, 'ev_ebit', 'EV/EBIT',
      '#a78bfa', corrs.ev_ebit, best === 'ev_ebit');
  } else {
    // Fallback: EBITDA bars
    const ebitdaH = d.ebitda_annual || [];
    if (ebitdaH.length >= 2 && document.getElementById(`mchart-${tk}-eveb`)) {
      Plotly.react(`mchart-${tk}-eveb`, [{
        type: 'bar', x: ebitdaH.map(r => r.year), y: ebitdaH.map(r => r.ebitda_m),
        marker: {color: 'rgba(16,185,129,.6)', line: {width: 0}},
        hovertemplate: '%{x}: $%{y:.0f}M<extra></extra>',
      }], _mLayout('EBITDA ($M)'), _mConf);
    }
  }

  // ── P/S: dual-axis ratio + price overlay ──────────────────────────────
  const psH = d.ps_history || [];
  if (psH.length >= 2) {
    _renderDualAxisRatio(`mchart-${tk}-ps`, psH, 'ps', 'P/S',
      '#06b6d4', corrs.ps, best === 'ps');
  }

  // ── PEG: EPS history bars ─────────────────────────────────────────────
  const epsH = d.eps_history || [];
  if (epsH.length >= 2 && document.getElementById(`mchart-${tk}-peg`)) {
    Plotly.react(`mchart-${tk}-peg`, [{
      type: 'bar', x: epsH.map(r => r.year), y: epsH.map(r => r.eps),
      marker: {
        color: epsH.map(r => r.eps >= 0 ? 'rgba(99,102,241,.7)' : 'rgba(239,68,68,.7)'),
        line: {width: 0},
      },
      hovertemplate: '%{x}: $%{y:.2f} EPS<extra></extra>',
    }], _mLayout('EPS ($)'), _mConf);
  }

  // ── Graham: EPS + Book Value comparison bars ──────────────────────────
  if (document.getElementById(`mchart-${tk}-graham`)) {
    const eps  = d.eps_ttm;
    const bvps = d.book_value_ps;
    const price = d.current_price;
    if (eps > 0 && bvps > 0) {
      const graham = Math.sqrt(22.5 * eps * bvps);
      Plotly.react(`mchart-${tk}-graham`, [{
        type: 'bar',
        x: ['EPS (TTM)', 'Book Value/Share', 'Graham Value', 'Market Price'],
        y: [eps, bvps, graham, price],
        marker: {
          color: ['rgba(99,102,241,.7)', 'rgba(99,102,241,.7)',
                  graham >= price ? 'rgba(16,185,129,.8)' : 'rgba(239,68,68,.8)',
                  'rgba(148,163,184,.5)'],
          line: {width: 0},
        },
        hovertemplate: '%{x}: $%{y:.2f}<extra></extra>',
      }], {
        ..._mLayout('$'),
        xaxis: {..._mLayout('$').xaxis, dtick: undefined, tickangle: -20, tickfont: {size: 8}},
      }, _mConf);
    }
  }

  // ── NCAV: Current assets vs total liabilities waterfall ───────────────
  if (document.getElementById(`mchart-${tk}-ncav`)) {
    const ca  = d.current_assets_m;
    const tl  = d.total_liab_m;
    const net = ca - tl;
    if (ca || tl) {
      Plotly.react(`mchart-${tk}-ncav`, [{
        type: 'bar',
        x: ['Current Assets', 'Total Liabilities', 'NCAV'],
        y: [ca, tl, Math.max(0, net)],
        marker: {
          color: [
            'rgba(16,185,129,.7)',
            'rgba(239,68,68,.7)',
            net > 0 ? 'rgba(16,185,129,.85)' : 'rgba(239,68,68,.85)',
          ],
          line: {width: 0},
        },
        hovertemplate: '%{x}: $%{y:.0f}M<extra></extra>',
      }], {
        ..._mLayout('$M'),
        xaxis: {..._mLayout('$M').xaxis, dtick: undefined, tickangle: -15, tickfont: {size: 8}},
      }, _mConf);
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// INIT: load workspaces from server on page load
// ══════════════════════════════════════════════════════════════════════════════

async function valInit() {
  // Load settings and workspaces in parallel
  const [, wsRes] = await Promise.allSettled([
    _loadModelSettings(),
    fetch('/api/valuation/lists').then(r => r.ok ? r.json() : []),
  ]);
  const rows = wsRes.status === 'fulfilled' ? (wsRes.value || []) : [];
  _vWs = rows.map(_wsNormalize);

  valApplyModelSettings();

  if (!_vWs.length) {
    await valNewWorkspace('Workspace 1');
  } else {
    await _activateWorkspace(_vWs[0].id, true);
  }
  _renderWsTabs();
  _setSaveStatus('idle');
}

// ── (obsolete list rendering, kept as dead-code stub) ────────────────────────
function _renderLists_OBSOLETE() { /* removed */ }
/* DEAD_LIST_CODE_START
  if (!_vLists.length) {
    container.innerHTML = '<div class="val-lists-empty">No lists yet.<br/>Click <strong>New</strong> to create one,<br/>then add stocks to it.</div>';
    return;
  }

  container.innerHTML = _vLists.map(lst => {
    const tickers  = lst.tickers || [];
    const isActive = _vActiveListId === lst.id;
    const isOpen   = _vExpandedLists.has(lst.id);

    const tickerRows = tickers.length
      ? tickers.map(t => `
          <div class="val-list-ticker-row" onclick="valSwitchOrLoadTicker('${t.ticker}')">
            <span class="val-list-ticker-sym">${t.ticker}</span>
            <span class="val-list-ticker-price">${t.price ? _fp(t.price, 'USD') : ''}</span>
            <button class="val-list-ticker-del" title="Remove from list"
              onclick="event.stopPropagation();valRemoveFromList(${lst.id},'${t.ticker}')">×</button>
          </div>`).join('')
      : '<div class="val-list-tickers-empty">Empty — add a ticker above</div>';

    const convertBtn = tickers.length
      ? `<button class="val-list-btn convert" title="Convert to portfolio"
           onclick="event.stopPropagation();valConvertList(${lst.id})">
           <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
         </button>`
      : '';

    return `
    <div class="val-list-item" id="vlist-${lst.id}">
      <div class="val-list-row ${isOpen ? 'expanded' : ''} ${isActive ? 'active-list' : ''}"
           id="vlist-row-${lst.id}"
           onclick="_selectList(${lst.id})"
           ondblclick="event.stopPropagation();_startRenameList(${lst.id})">
        <span class="val-list-chevron">›</span>
        <span class="val-list-name" id="vlist-name-${lst.id}">${_escHtml(lst.name)}</span>
        ${isActive ? '<span class="val-list-active-dot" title="Active — new stocks go here">●</span>' : ''}
        <span class="val-list-count">${tickers.length}</span>
        <div class="val-list-actions">
          ${convertBtn}
          <button class="val-list-btn del" title="Delete list"
            onclick="event.stopPropagation();_valDeleteList(${lst.id})">×</button>
        </div>
      </div>
      <div class="val-list-tickers ${isOpen ? 'open' : ''}" id="vlist-tickers-${lst.id}">
        ${tickerRows}
      </div>
    </div>`;
  }).join('');
}

// ── Select list as active folder (click = select + expand; click again = collapse only) ──
function _selectList(id) {
  if (_vActiveListId === id) {
    // Already active: just toggle expand
    _vExpandedLists.has(id) ? _vExpandedLists.delete(id) : _vExpandedLists.add(id);
  } else {
    // New selection: activate and expand
    _vActiveListId = id;
    _vExpandedLists.add(id);
  }
  _renderLists();
}

// ── Toggle expand/collapse without changing active selection ──────────────────
function _toggleList(id) {
  _vExpandedLists.has(id) ? _vExpandedLists.delete(id) : _vExpandedLists.add(id);
  _renderLists();
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
    const res = await fetch('/api/valuation/lists', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name: 'New List'})
    });
    const lst = await res.json();
    _vLists.unshift(lst);
    // Auto-select and expand the new list
    _vActiveListId = lst.id;
    _vExpandedLists.add(lst.id);
    _renderLists();
    // Start rename so user names it right away
    setTimeout(() => _startRenameList(lst.id), 50);
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
  if (_vActiveListId === id) _vActiveListId = null;
  _vExpandedLists.delete(id);
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

DEAD_LIST_CODE_END */

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

// ══════════════════════════════════════════════════════════════════════════════
// MODEL SELECTION SETTINGS
// ══════════════════════════════════════════════════════════════════════════════

const _VAL_MODEL_LIST = [
  { id: 'dcf',    label: 'Discounted Cash Flow (DCF)', cat: 'Cash Flow' },
  { id: 'rdcf',   label: 'Reverse DCF (Implied Growth)', cat: 'Cash Flow' },
  { id: 'epv',    label: 'Earnings Power Value (EPV)', cat: 'Cash Flow' },
  { id: 'ddm',    label: 'Dividend Discount Model (DDM)', cat: 'Dividend' },
  { id: 'pe',     label: 'Price / Earnings (P/E)',     cat: 'Multiples' },
  { id: 'evda',   label: 'EV / EBITDA',                cat: 'Multiples' },
  { id: 'eveb',   label: 'EV / EBIT',                  cat: 'Multiples' },
  { id: 'ps',     label: 'Price / Sales (P/S)',         cat: 'Multiples' },
  { id: 'peg',    label: 'PEG Ratio',                  cat: 'Multiples' },
  { id: 'graham', label: 'Graham Number',              cat: 'Asset-Based' },
  { id: 'ncav',   label: 'Net Current Asset Value (NCAV)', cat: 'Asset-Based' },
];

let _vModelSettings = Object.fromEntries(_VAL_MODEL_LIST.map(m => [m.id, true]));
let _vSettingsSaveTimer = null;

async function _loadModelSettings() {
  try {
    const res = await fetch('/api/valuation/settings');
    if (res.ok) {
      const saved = await res.json();
      _VAL_MODEL_LIST.forEach(m => { if (m.id in saved) _vModelSettings[m.id] = !!saved[m.id]; });
    }
  } catch(_) {}
}

function _saveModelSettings() {
  clearTimeout(_vSettingsSaveTimer);
  _vSettingsSaveTimer = setTimeout(() => {
    fetch('/api/valuation/settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(_vModelSettings),
    }).catch(() => {});
  }, 500);
}

function valApplyModelSettings() {
  // Show/hide individual model cards across all rendered panels
  document.querySelectorAll('.val-card[data-model]').forEach(card => {
    card.style.display = _vModelSettings[card.dataset.model] !== false ? '' : 'none';
  });
  // Hide any category section where all its cards are hidden
  document.querySelectorAll('.val-category').forEach(cat => {
    const anyVisible = [...cat.querySelectorAll('.val-card')].some(c => c.style.display !== 'none');
    cat.style.display = anyVisible ? '' : 'none';
  });
}

function valToggleModel(modelId, enabled) {
  _vModelSettings[modelId] = enabled;
  _saveModelSettings();
  valApplyModelSettings();
  // Re-render comparison charts for all open stocks (disabled models excluded)
  for (const [ticker, stock] of Object.entries(_vStocks)) {
    if (stock.data) _recalcTicker(ticker);
  }
}

let _settingsOpen = false;

function valToggleSettings() {
  _settingsOpen ? valCloseSettings() : _openSettings();
}

function _openSettings() {
  _settingsOpen = true;
  _renderSettingsPanel();
  const panel = document.getElementById('val-settings-panel');
  const btn   = document.getElementById('val-settings-btn');
  panel.style.display = 'block';
  btn.classList.add('active');
  // Position below the button
  const rect = btn.getBoundingClientRect();
  const pw = 238;
  let left = rect.left;
  if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
  panel.style.left = `${Math.max(4, left)}px`;
  panel.style.top  = `${rect.bottom + 4}px`;
  setTimeout(() => {
    document.addEventListener('click', _settingsOutsideClick, {once: true, capture: true});
  }, 0);
}

function valCloseSettings() {
  _settingsOpen = false;
  const panel = document.getElementById('val-settings-panel');
  const btn   = document.getElementById('val-settings-btn');
  if (panel) panel.style.display = 'none';
  if (btn)   btn.classList.remove('active');
}

function _settingsOutsideClick(e) {
  const panel = document.getElementById('val-settings-panel');
  const btn   = document.getElementById('val-settings-btn');
  if (panel && !panel.contains(e.target) && btn && !btn.contains(e.target)) {
    valCloseSettings();
  } else {
    document.addEventListener('click', _settingsOutsideClick, {once: true, capture: true});
  }
}

function _renderSettingsPanel() {
  const body = document.getElementById('val-settings-body');
  if (!body) return;
  const cats = {};
  _VAL_MODEL_LIST.forEach(m => { (cats[m.cat] = cats[m.cat] || []).push(m); });
  body.innerHTML = Object.entries(cats).map(([cat, models]) => `
    <div class="val-settings-cat">${cat}</div>
    ${models.map(m => `
      <label class="val-settings-row">
        <input type="checkbox" ${_vModelSettings[m.id] ? 'checked' : ''}
               onchange="valToggleModel('${m.id}', this.checked)"/>
        <span>${m.label}</span>
      </label>`).join('')}
  `).join('');
}

// ── Bootstrap on load ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', valInit);
