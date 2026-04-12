// ═══════════════════════════════════════════════════════════════════ CONSTANTS
const COLORS = ["#3b82f6","#06b6d4","#10b981","#f59e0b","#8b5cf6","#ef4444","#ec4899","#14b8a6","#f97316","#a855f7","#64748b","#22d3ee"];
const METHODS = {
  max_sharpe:      "Maximises Sharpe ratio — best risk-adjusted return. Classic Markowitz mean-variance optimum.",
  min_volatility:  "Finds the portfolio with the lowest possible annualised volatility, regardless of return.",
  black_litterman: "Blends CAPM market equilibrium with your forward-looking views. More stable, diversified weights.",
  risk_parity:     "Each asset contributes equally to total portfolio risk. Reduces concentration in high-vol assets.",
  hrp:             "Hierarchical Risk Parity uses graph theory and clustering to group correlated assets, preventing concentrated risk without needing inversion of the covariance matrix.",
  equal_weight:    "1/N equal weighting. A simple benchmark that is often surprisingly hard to beat.",
  max_return:      "Maximises expected return subject to weight constraints. Typically highly concentrated.",
  custom:          "Manually specify allocation percentages yourself.",
};

// ═══════════════════════════════════════════════════════════════════ PROJECT STATE
let projects = [];
let activeId = null;

function makeProject(name) {
  return {
    id: Date.now() + Math.random(),
    name: name || "Portfolio",
    tickers: {},
    stockData: {},
    overrides: {},
    blViews: {},
    customWeights: {},
    settings: {
      startDate: defaultStart(),
      endDate:   today(),
      method:    "max_sharpe",
      rfr:       4.0,
      minW:      0,
      maxW:      100,
      blLambda:  2.5,
      blTau:     0.05,
    },
    results: null,
  };
}

function today()        { return new Date().toISOString().slice(0,10); }
function defaultStart() { const d = new Date(); d.setFullYear(d.getFullYear()-3); return d.toISOString().slice(0,10); }

function saveProjects() {
  const slim = projects.map(p => {
    const sd = {};
    Object.keys(p.stockData).forEach(s => { sd[s] = {...p.stockData[s], sparkline: undefined}; });
    return {...p, stockData: sd, results: p.results ? {performance: p.results.performance, weights: p.results.weights} : null};
  });
  try { localStorage.setItem("portopt_v2", JSON.stringify(slim)); } catch(e) {}
}

function loadProjects() {
  try {
    const raw = JSON.parse(localStorage.getItem("portopt_v2") || "null");
    if (raw && Array.isArray(raw) && raw.length) {
      projects = raw.map(p => ({...makeProject(), ...p}));
      return;
    }
  } catch(e) {}
  projects = [makeProject("Portfolio 1")];
}

function activeProject() { return projects.find(p => p.id === activeId); }

// ═══════════════════════════════════════════════════════════════════ TAB RENDERING
function renderTabs() {
  const c = document.getElementById("tabs-container");
  c.innerHTML = projects.map(p => `
    <button class="tab${p.id===activeId?" active":""}${p.results?" has-results":""}"
            onclick="switchProject(${p.id})" data-id="${p.id}">
      <span class="tab-dot"></span>
      <span class="tab-name"
            ondblclick="renameTab(event,${p.id})"
            contenteditable="false"
            onblur="finishRename(event,${p.id})"
            onkeydown="if(event.key==='Enter'){event.preventDefault();this.blur();}"
            id="tab-name-${p.id}">${escHtml(p.name)}</span>
      ${projects.length>1 ? `<span class="tab-close" onclick="event.stopPropagation();deleteProject(${p.id})">×</span>` : ""}
    </button>`).join("");
}

function escHtml(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

function renameTab(e, id) {
  e.stopPropagation();
  const el = document.getElementById("tab-name-" + id);
  el.contentEditable = "true";
  el.focus();
  const range = document.createRange();
  range.selectNodeContents(el);
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(range);
}

function finishRename(e, id) {
  const el = e.target;
  el.contentEditable = "false";
  const p = projects.find(x => x.id === id);
  if (p) { p.name = el.textContent.trim() || p.name; saveProjects(); }
}

function newProject() {
  saveCurrentUIToProject();
  const p = makeProject(`Portfolio ${projects.length + 1}`);
  projects.push(p);
  switchProject(p.id);
}

function deleteProject(id) {
  if (projects.length <= 1) return;
  if (!confirm("Delete this project?")) return;
  projects = projects.filter(p => p.id !== id);
  if (activeId === id) {
    activeId = projects[projects.length-1].id;
    loadProjectIntoUI(activeProject());
  }
  renderTabs();
  saveProjects();
}

function switchProject(id) {
  saveCurrentUIToProject();
  activeId = id;
  loadProjectIntoUI(activeProject());
  renderTabs();
  saveProjects();
}

// ═══════════════════════════════════════════════════════════════════ UI ↔ PROJECT SYNC
function saveCurrentUIToProject() {
  const p = activeProject();
  if (!p) return;
  p.settings = {
    startDate: document.getElementById("start-date").value,
    endDate:   document.getElementById("end-date").value,
    method:    document.getElementById("method").value,
    rfr:       parseFloat(document.getElementById("rfr").value),
    minW:      parseFloat(document.getElementById("min-w").value),
    maxW:      parseFloat(document.getElementById("max-w").value),
    blLambda:  parseFloat(document.getElementById("bl-lambda").value),
    blTau:     parseFloat(document.getElementById("bl-tau").value),
  };
  Object.keys(p.tickers).forEach(sym => {
    const en  = document.getElementById("bl-en-"+sym);
    const ret = document.getElementById("bl-ret-"+sym);
    const cf  = document.getElementById("bl-conf-"+sym);
    if (en) p.blViews[sym] = {enabled:en.checked, return:parseFloat(ret?.value||10)/100, confidence:parseFloat(cf?.value||50)/100};
    const ri = document.getElementById("ov-ret-"+sym);
    const vi = document.getElementById("ov-vol-"+sym);
    if (!p.overrides[sym]) p.overrides[sym] = {};
    if (ri) p.overrides[sym].retVal = ri.value;
    if (vi) p.overrides[sym].volVal = vi.value;
  });
}

function loadProjectIntoUI(p) {
  if (!p) return;
  document.getElementById("start-date").value = p.settings.startDate || defaultStart();
  document.getElementById("end-date").value   = p.settings.endDate   || today();
  document.getElementById("method").value     = p.settings.method    || "max_sharpe";
  document.getElementById("rfr").value        = p.settings.rfr       ?? 4.0;
  document.getElementById("min-w").value      = p.settings.minW      ?? 0;
  document.getElementById("max-w").value      = p.settings.maxW      ?? 100;
  document.getElementById("bl-lambda").value  = p.settings.blLambda  ?? 2.5;
  document.getElementById("bl-tau").value     = p.settings.blTau     ?? 0.05;
  onMethodChange();
  renderStockList();
  renderBLViews();
  if (p.results) {
    showState("results");
    renderResults(p.results, p.settings.method);
  } else {
    showState("empty");
  }
}

// ═══════════════════════════════════════════════════════════════════ STOCK MANAGEMENT
document.getElementById("ticker-input").addEventListener("keydown", e => { if(e.key==="Enter") addTicker(); });

async function addTicker() {
  const inp = document.getElementById("ticker-input");
  const sym = inp.value.trim().toUpperCase().replace(/[^A-Z0-9.]/g,"");
  if (!sym) return;
  const p = activeProject();
  if (p.tickers[sym]) { setStatus(`${sym} already added`, "var(--gold)"); return; }
  if (Object.keys(p.tickers).length >= 20) { setStatus("Max 20 tickers", "var(--red)"); return; }

  const addBtn = document.getElementById("add-btn");
  addBtn.disabled = true; addBtn.textContent = "…";
  setStatus("Validating…", "var(--muted2)");

  try {
    const res  = await fetch("/api/validate_ticker", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ticker:sym})});
    const data = await res.json();
    if (data.valid) {
      p.tickers[sym] = {name:data.name, price:data.price, sector:data.sector||"N/A", market_cap:data.market_cap||0};
      p.overrides[sym] = {retVal:"", volVal:""};
      p.blViews[sym]   = {enabled:false, return:0.10, confidence:0.5};
      p.customWeights[sym] = 0;
      inp.value = "";
      setStatus(`✓ Added ${data.name}`, "var(--green)");
      renderStockList();
      renderBLViews();
      saveProjects();
      fetchStockData([sym]);
    } else {
      setStatus(`✗ ${data.error||"Not found"}`, "var(--red)");
    }
  } catch(e) { setStatus("Network error", "var(--red)"); }
  finally    { addBtn.disabled=false; addBtn.textContent="Add"; }
}

function removeTicker(sym) {
  const p = activeProject();
  delete p.tickers[sym];
  delete p.stockData[sym];
  delete p.overrides[sym];
  delete p.blViews[sym];
  delete p.customWeights[sym];
  renderStockList();
  renderBLViews();
  saveProjects();
}

function setStatus(msg, color) {
  const el = document.getElementById("ticker-status");
  el.textContent = msg; el.style.color = color;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.textContent="", 4000);
}

// ── Sparkline SVG ─────────────────────────────────────────────────────────────
function sparkline(vals, w=72, h=22) {
  if (!vals || vals.length < 2) return "";
  const min = Math.min(...vals), max = Math.max(...vals), range = max-min||0.001;
  const n = vals.length;
  const pts = vals.map((v,i) => `${(i/(n-1)*w).toFixed(1)},${(h-(v-min)/range*(h-2)-1).toFixed(1)}`).join(" ");
  const up  = vals[n-1] >= vals[0];
  const c   = up ? "#10b981" : "#ef4444";
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="overflow:visible;">
    <polyline points="${pts}" fill="none" stroke="${c}" stroke-width="1.5" stroke-linejoin="round"/>
  </svg>`;
}

// ── Stock list rendering ──────────────────────────────────────────────────────
function renderStockList() {
  const p      = activeProject();
  const syms   = Object.keys(p.tickers);
  const list   = document.getElementById("stock-list");
  const empty  = document.getElementById("stock-empty");
  empty.style.display = syms.length ? "none" : "block";

  list.innerHTML = syms.map((sym, i) => {
    const t     = p.tickers[sym];
    const sd    = p.stockData[sym];
    const ov    = p.overrides[sym] || {};
    const color = COLORS[i % COLORS.length];
    const spark = sd ? sparkline(sd.sparkline) : "";
    const retColor = sd && sd.ann_return >= 0 ? "green" : "red";
    const totColor = sd && sd.total_return >= 0 ? "green" : "red";

    let bodyHtml = `<div class="sc-loading" id="sc-loading-${sym}">Loading data…</div>`;
    if (sd) {
      const retOv = ov.retVal ? `<input class="sc-override-inp active" id="ov-ret-${sym}" type="number" value="${ov.retVal}" placeholder="${sd.ann_return}" step="0.1" onchange="saveOverride('${sym}')" title="Override expected return"/>`
                               : `<input class="sc-override-inp" id="ov-ret-${sym}" type="number" placeholder="${sd.ann_return}%" step="0.1" onchange="saveOverride('${sym}')" title="Override expected return"/>`;
      const volOv = ov.volVal ? `<input class="sc-override-inp active" id="ov-vol-${sym}" type="number" value="${ov.volVal}" placeholder="${sd.ann_vol}" step="0.1" onchange="saveOverride('${sym}')" title="Override volatility"/>`
                               : `<input class="sc-override-inp" id="ov-vol-${sym}" type="number" placeholder="${sd.ann_vol}%" step="0.1" onchange="saveOverride('${sym}')" title="Override volatility"/>`;
      bodyHtml = `
        <div class="sc-stats">
          <div class="sc-stat">
            <div class="sc-stat-label">Ann. Return</div>
            <div class="sc-stat-main ${retColor}">${sd.ann_return >= 0 ? "+" : ""}${sd.ann_return}%</div>
            <div class="sc-override-row">
              <span class="sc-override-lbl">Override:</span>
              ${retOv}
              <span class="sc-override-unit">%/yr</span>
              <button class="sc-override-clear" onclick="clearOverride('${sym}','ret')" title="Reset">↺</button>
            </div>
          </div>
          <div class="sc-stat">
            <div class="sc-stat-label">Ann. Volatility</div>
            <div class="sc-stat-main">${sd.ann_vol}%</div>
            <div class="sc-override-row">
              <span class="sc-override-lbl">Override:</span>
              ${volOv}
              <span class="sc-override-unit">%/yr</span>
              <button class="sc-override-clear" onclick="clearOverride('${sym}','vol')" title="Reset">↺</button>
            </div>
          </div>
          <div class="sc-stat-full">
            <div>Total: <span class="${totColor}">${sd.total_return >= 0 ? "+" : ""}${sd.total_return}%</span></div>
            <div>Sharpe: <span>${sd.sharpe}</span></div>
            <div>${sd.n_days} days</div>
          </div>
        </div>`;
    }

    return `
    <div class="stock-card" id="scard-${sym}">
      <div class="sc-header" onclick="toggleCard('${sym}')">
        <div class="sc-dot" style="background:${color};"></div>
        <div class="sc-names">
          <span class="sc-sym" style="color:${color};">${sym}</span>
          <span class="sc-fullname">${t.name}</span>
        </div>
        <div class="sc-spark">${spark}</div>
        <span class="sc-price">$${t.price.toFixed(2)}</span>
        <button class="sc-remove" onclick="event.stopPropagation();removeTicker('${sym}')" title="Remove">×</button>
        <span class="sc-chevron" id="chev-${sym}">▾</span>
      </div>
      <div class="sc-body" id="scbody-${sym}">${bodyHtml}</div>
    </div>`;
  }).join("");
}

function toggleCard(sym) {
  const body = document.getElementById("scbody-" + sym);
  const chev = document.getElementById("chev-" + sym);
  const open = body.classList.toggle("open");
  chev.classList.toggle("open", open);
}

function saveOverride(sym) {
  const p  = activeProject();
  const ri = document.getElementById("ov-ret-" + sym);
  const vi = document.getElementById("ov-vol-" + sym);
  if (!p.overrides[sym]) p.overrides[sym] = {};
  if (ri) { p.overrides[sym].retVal = ri.value; ri.classList.toggle("active", !!ri.value); }
  if (vi) { p.overrides[sym].volVal = vi.value; vi.classList.toggle("active", !!vi.value); }
  saveProjects();
}

function clearOverride(sym, type) {
  const p = activeProject();
  if (!p.overrides[sym]) p.overrides[sym] = {};
  if (type === "ret") {
    p.overrides[sym].retVal = "";
    const el = document.getElementById("ov-ret-" + sym);
    if (el) { el.value = ""; el.classList.remove("active"); }
  } else {
    p.overrides[sym].volVal = "";
    const el = document.getElementById("ov-vol-" + sym);
    if (el) { el.value = ""; el.classList.remove("active"); }
  }
  saveProjects();
}

// ── Fetch stock data ──────────────────────────────────────────────────────────
let dataFetchTimer = null;
function onDateChange() {
  document.getElementById("refresh-btn").style.display =
    Object.keys(activeProject().tickers).length ? "inline-flex" : "none";
}

function refreshStockData() {
  const syms = Object.keys(activeProject().tickers);
  if (syms.length) fetchStockData(syms);
}

async function fetchStockData(syms) {
  const p = activeProject();
  const start = document.getElementById("start-date").value;
  const end   = document.getElementById("end-date").value;
  try {
    const res  = await fetch("/api/stock_data", {method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({tickers:syms, start_date:start, end_date:end})});
    const data = await res.json();
    if (data.data) {
      Object.assign(p.stockData, data.data);
      saveProjects();
      renderStockList();
      renderBLViews();
    }
  } catch(e) { /* silent — non-critical background fetch */ }
}

// ═══════════════════════════════════════════════════════════════════ DATE HELPERS
function setRange(years) {
  const e = new Date(), s = new Date();
  s.setFullYear(e.getFullYear() - years);
  document.getElementById("end-date").value   = e.toISOString().slice(0,10);
  document.getElementById("start-date").value = s.toISOString().slice(0,10);
  const syms = Object.keys(activeProject().tickers);
  if (syms.length) { clearTimeout(dataFetchTimer); dataFetchTimer = setTimeout(() => fetchStockData(syms), 400); }
}

// ═══════════════════════════════════════════════════════════════════ METHOD
function onMethodChange() {
  const m = document.getElementById("method").value;
  document.getElementById("method-desc").textContent = METHODS[m] || "";
  document.getElementById("bl-panel").style.display = m === "black_litterman" ? "block" : "none";
  document.getElementById("custom-panel").style.display = m === "custom" ? "block" : "none";
  if (m === "custom") renderCustomWeights();
}

function renderCustomWeights() {
  const p = activeProject();
  const syms = Object.keys(p.tickers);
  const c = document.getElementById("custom-weights-grid");
  if (!syms.length) { c.innerHTML = `<div style="color:var(--muted);font-size:11px;">Add stocks above.</div>`; return; }
  if (!p.customWeights) p.customWeights = {};
  c.innerHTML = syms.map(sym => {
    const cw = p.customWeights[sym] || 0;
    return `<div style="display:flex;align-items:center;gap:8px;">
      <span style="font-weight:700;color:var(--accent);width:45px;">${sym}</span>
      <input type="number" id="cw-${sym}" value="${cw.toFixed(2)}" step="0.1" min="0" max="100" style="flex:1;" onchange="saveCustomWeights()"/>
      <span style="font-size:11px;color:var(--muted);">%</span>
    </div>`;
  }).join("");
}

function saveCustomWeights() {
  const p = activeProject();
  if (!p.customWeights) p.customWeights = {};
  Object.keys(p.tickers).forEach(sym => {
    const el = document.getElementById("cw-"+sym);
    if(el) p.customWeights[sym] = parseFloat(el.value)||0;
  });
  saveProjects();
}

// ═══════════════════════════════════════════════════════════════════ COLLAPSE
function toggleColl(id) {
  document.getElementById(id+"-body").classList.toggle("open");
  document.getElementById(id+"-arrow").classList.toggle("open");
}

// ═══════════════════════════════════════════════════════════════════ BL VIEWS
function renderBLViews() {
  const p    = activeProject();
  const syms = Object.keys(p.tickers);
  const c    = document.getElementById("bl-views");
  if (!syms.length) { c.innerHTML = `<div style="color:var(--muted);font-size:11px;">Add stocks above.</div>`; return; }
  c.innerHTML = `
    <div style="display:grid;grid-template-columns:16px 1fr 70px 90px;gap:4px 6px;font-size:10px;color:var(--muted);font-weight:600;padding-bottom:3px;">
      <div></div><div>Ticker</div><div>Return %/yr</div><div>Confidence</div>
    </div>` + syms.map(sym => {
      const v = p.blViews[sym] || {};
      return `<div class="bl-view-row">
        <input type="checkbox" id="bl-en-${sym}" ${v.enabled?"checked":""}/>
        <span class="bl-view-sym">${sym}</span>
        <input type="number" id="bl-ret-${sym}" value="${((v.return||0.10)*100).toFixed(1)}" min="-50" max="200" step="0.5" style="padding:3px 5px;font-size:11px;"/>
        <div class="conf-wrap">
          <input type="range" id="bl-conf-${sym}" min="1" max="99" value="${Math.round((v.confidence||0.5)*100)}"
                 oninput="document.getElementById('bl-lbl-${sym}').textContent=this.value+'%'"/>
          <span class="conf-lbl" id="bl-lbl-${sym}">${Math.round((v.confidence||0.5)*100)}%</span>
        </div>
      </div>`;
    }).join("");
}

function getBLViews() {
  const p = activeProject();
  const views = {};
  Object.keys(p.tickers).forEach(sym => {
    const en  = document.getElementById("bl-en-"+sym);
    const ret = document.getElementById("bl-ret-"+sym);
    const cf  = document.getElementById("bl-conf-"+sym);
    views[sym] = {
      enabled:    en?.checked || false,
      return:     parseFloat(ret?.value||10)/100,
      confidence: parseFloat(cf?.value||50)/100,
    };
  });
  return views;
}

// ═══════════════════════════════════════════════════════════════════ OPTIMIZE
async function runOptimization() {
  const p = activeProject();
  const tickers = Object.keys(p.tickers);
  if (tickers.length < 2) { alert("Please add at least 2 stocks."); return; }

  saveCurrentUIToProject();
  showState("loading");
  document.getElementById("opt-btn").disabled = true;
  document.getElementById("loading-msg").textContent = "Fetching market data…";

  const method = document.getElementById("method").value;
  const rfr    = parseFloat(document.getElementById("rfr").value) / 100;
  const min_w  = parseFloat(document.getElementById("min-w").value) / 100;
  const max_w  = parseFloat(document.getElementById("max-w").value) / 100;
  const start  = document.getElementById("start-date").value;
  const end    = document.getElementById("end-date").value;

  if (method === "custom") {
    const cw_raw = {};
    tickers.forEach(sym => { cw_raw[sym] = parseFloat(document.getElementById("cw-"+sym)?.value || 0) / 100; });
    setTimeout(() => {
      if (document.getElementById("state-loading").style.display !== "none")
        document.getElementById("loading-msg").textContent = "Running custom analysis…";
    }, 1500);
    const pl = { weights: cw_raw, start_date:start, end_date:end, risk_free_rate: rfr };
    try {
      const res  = await fetch("/api/analyze", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(pl)});
      const data = await res.json();
      if (data.error) {
        showState("error");
        document.getElementById("error-msg").innerHTML = `<strong>Error:</strong> ${data.error}`;
      } else {
        const finalData = { weights: data.weights, analytics: data.analytics, frontier: null };
        p.results = finalData;
        saveProjects();
        showState("results");
        renderResults(finalData, method);
        renderTabs();
      }
    } catch(e) {
      showState("error");
      document.getElementById("error-msg").textContent = "Network error: " + e.message;
    } finally {
      document.getElementById("opt-btn").disabled = false;
    }
    return;
  }

  const retOv = {}, volOv = {};
  tickers.forEach(sym => {
    const ov = p.overrides[sym] || {};
    if (ov.retVal) retOv[sym] = parseFloat(ov.retVal);
    if (ov.volVal) volOv[sym] = parseFloat(ov.volVal);
  });

  const mcaps = {};
  tickers.forEach(sym => { mcaps[sym] = p.tickers[sym].market_cap || 1; });

  const payload = {
    tickers, start_date:start, end_date:end, method,
    risk_free_rate: rfr, min_weight: min_w, max_weight: max_w,
    market_caps: mcaps,
    views: getBLViews(),
    return_overrides: retOv,
    vol_overrides: volOv,
    tau:           parseFloat(document.getElementById("bl-tau").value),
    risk_aversion: parseFloat(document.getElementById("bl-lambda").value),
  };

  setTimeout(() => {
    if (document.getElementById("state-loading").style.display !== "none")
      document.getElementById("loading-msg").textContent = "Running optimization…";
  }, 1500);

  try {
    const res  = await fetch("/api/optimize", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const data = await res.json();
    if (data.error) {
      showState("error");
      document.getElementById("error-msg").innerHTML = `<strong>Error:</strong> ${data.error}`;
    } else {
      p.results = data;
      saveProjects();
      showState("results");
      renderResults(data, method);
      renderTabs();
    }
  } catch(e) {
    showState("error");
    document.getElementById("error-msg").textContent = "Network error: " + e.message;
  } finally {
    document.getElementById("opt-btn").disabled = false;
  }
}

// ═══════════════════════════════════════════════════════════════════ SHOW STATE
function showState(s) {
  ["empty","loading","error","results"].forEach(n =>
    document.getElementById("state-"+n).style.display = s===n ? "block" : "none");
}

// ═══════════════════════════════════════════════════════════════════ RENDER RESULTS
function renderResults(data, method) {
  const perf = data.analytics.metrics;
  document.getElementById("m-ret").textContent    = perf.expected_return.toFixed(2) + "%";
  document.getElementById("m-vol").textContent    = perf.volatility.toFixed(2) + "%";
  document.getElementById("m-sharpe").textContent = perf.sharpe_ratio.toFixed(3);

  const frontierCard = document.getElementById("frontier-card");
  if (method === "custom" || method === "hrp") {
    frontierCard.style.display = "none";
  } else {
    frontierCard.style.display = "block";
    renderFrontierChart(data.frontier, perf, data.frontier_bl);
  }

  renderReturnsChart(data.analytics.cumulative_returns);
  renderDrawdownChart(data.analytics.drawdown_series);
  renderRollingChart(data.analytics.rolling_metrics, _currentRollingWindow);
  renderCorrChart(data.analytics.correlation);
  renderMetricsDetail(perf);
  renderAllocChart(data.weights);
  renderWeightsTable(data.weights);

  document.getElementById("mc-stats-bar").style.display = "none";
  Plotly.purge("chart-montecarlo");
  document.getElementById("chart-montecarlo").innerHTML =
    `<div style="height:100%;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:12px;">Configure horizon &amp; runs above, then click Run Simulation.</div>`;
  document.getElementById("stress-results").innerHTML =
    `<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px 0;">Click Run Stress Test to simulate how this portfolio would have performed in past crises.</div>`;

  const blCard = document.getElementById("academic-bl-results");
  if (method === "black_litterman" && data.bl_info) {
    blCard.style.display = "block";
    renderBLAcademicPlots(data.bl_info, data.weights);
  } else {
    blCard.style.display = "none";
  }

  const hrpCard = document.getElementById("academic-hrp-results");
  if (method === "hrp" && data.hrp_info) {
    hrpCard.style.display = "block";
    renderHRPAcademicPlots(data.hrp_info);
  } else {
    hrpCard.style.display = "none";
  }
}

function renderAllocChart(weights) {
  const syms = Object.keys(weights).filter(k => weights[k] > 0.001);
  const vals = syms.map(s => weights[s]);
  Plotly.react("chart-alloc", [{
    type:"pie", hole:.44, labels:syms, values:vals,
    textinfo:"label+percent", textfont:{size:11,color:"#e2e8f0"},
    hovertemplate:"<b>%{label}</b><br>%{percent}<extra></extra>",
    marker:{colors:COLORS.slice(0,syms.length), line:{color:"#0b1120",width:2}},
  }], {
    paper_bgcolor:"transparent",plot_bgcolor:"transparent",
    margin:{l:8,r:8,t:8,b:8},showlegend:false,font:{color:"#94a3b8"},
  }, {responsive:true,displayModeBar:false});
}

function renderFrontierChart(frontier, perf, frontierBL) {
  const traces = [];
  if (frontier?.volatilities?.length) {
    traces.push({
      x:frontier.volatilities.map(v=>v*100), y:frontier.returns.map(r=>r*100),
      mode:"lines", name:"Efficient Frontier",
      line:{color:"#3b82f6",width:2.5},
      hovertemplate:"σ: %{x:.2f}%  μ: %{y:.2f}%<extra>Frontier</extra>",
    });
  }
  if (frontierBL?.volatilities?.length) {
    traces.push({
      x:frontierBL.volatilities.map(v=>v*100), y:frontierBL.returns.map(r=>r*100),
      mode:"lines", name:"BL Frontier",
      line:{color:"#8b5cf6",width:2,dash:"dot"},
      hovertemplate:"σ: %{x:.2f}%  μ: %{y:.2f}%<extra>BL Frontier</extra>",
    });
  }
  const rfr   = parseFloat(document.getElementById("rfr").value)/100;
  const slope = perf.sharpe_ratio;
  const volFraction = perf.volatility / 100;
  const cv    = [0, volFraction*1.8];
  traces.push({
    x:cv.map(v=>v*100), y:cv.map(v=>(rfr+slope*v)*100),
    mode:"lines", name:"CAL",
    line:{color:"#10b981",width:1.5,dash:"dash"},
    hovertemplate:"CAL<extra></extra>",
  });
  traces.push({
    x:[perf.volatility], y:[perf.expected_return],
    mode:"markers", name:"Optimal",
    marker:{color:"#f59e0b",size:11,symbol:"star",line:{color:"#fff",width:1.5}},
    hovertemplate:`σ: ${perf.volatility.toFixed(2)}%<br>μ: ${perf.expected_return.toFixed(2)}%<br>Sharpe: ${perf.sharpe_ratio.toFixed(3)}<extra>Optimal</extra>`,
  });
  Plotly.react("chart-frontier", traces, {
    paper_bgcolor:"transparent", plot_bgcolor:"#0a1020",
    xaxis:{title:"Volatility (%)",color:"#94a3b8",gridcolor:"#1e2d45",zeroline:false},
    yaxis:{title:"Expected Return (%)",color:"#94a3b8",gridcolor:"#1e2d45",zeroline:false},
    legend:{font:{color:"#94a3b8"},bgcolor:"transparent"},
    margin:{l:50,r:12,t:12,b:48},font:{color:"#94a3b8"},hovermode:"closest",
  }, {responsive:true,displayModeBar:false});
}

function renderWeightsTable(weights) {
  const p    = activeProject();
  const tbody= document.getElementById("wtable-body");
  const sorted = Object.entries(weights).sort((a,b)=>b[1]-a[1]);
  tbody.innerHTML = sorted.map(([sym,w],i) => {
    const t   = p.tickers[sym] || {};
    const sd  = p.stockData[sym] || {};
    const ov  = p.overrides[sym] || {};
    const pct = (w*100).toFixed(2);
    const bar = Math.min(100, Math.round(w*100));
    const c   = COLORS[i%COLORS.length];
    const dispRet = ov.retVal ? `<span style="color:var(--gold);">${parseFloat(ov.retVal).toFixed(1)}% ✎</span>`
                              : (sd.ann_return !== undefined ? `${sd.ann_return >= 0 ? "+" : ""}${sd.ann_return}%` : "—");
    const dispVol = ov.volVal ? `<span style="color:var(--gold);">${parseFloat(ov.volVal).toFixed(1)}% ✎</span>`
                              : (sd.ann_vol !== undefined ? `${sd.ann_vol}%` : "—");
    return `<tr>
      <td><span style="color:${c};font-weight:700;">${sym}</span><br><span style="font-size:10px;color:var(--muted);">${t.sector||"—"}</span></td>
      <td style="font-weight:600;">${pct}%</td>
      <td><div class="wbar-wrap"><div class="wbar" style="width:${bar}%;background:${c};"></div></div></td>
      <td>${dispRet}</td>
      <td>${dispVol}</td>
    </tr>`;
  }).join("");
}

function renderReturnsChart(returns_data) {
  const special = ["__PORTFOLIO__", "__SPY__"];
  const stockSyms = Object.keys(returns_data).filter(k => !special.includes(k));
  const traces = [];
  stockSyms.forEach((sym, i) => {
    traces.push({
      x: returns_data[sym].dates,
      y: returns_data[sym].values.map(v => (v - 1) * 100),
      mode: "lines", name: sym,
      line: {color: COLORS[i % COLORS.length], width: 1.2},
      opacity: 0.7,
      hovertemplate: `${sym}: %{y:.2f}%<extra></extra>`,
    });
  });
  if (returns_data["__SPY__"]) {
    const d = returns_data["__SPY__"];
    traces.push({
      x: d.dates, y: d.values.map(v => (v - 1) * 100),
      mode: "lines", name: "SPY (Benchmark)",
      line: {color: "#64748b", width: 1.8, dash: "dot"},
      hovertemplate: "SPY: %{y:.2f}%<extra></extra>",
    });
  }
  if (returns_data["__PORTFOLIO__"]) {
    const d = returns_data["__PORTFOLIO__"];
    traces.push({
      x: d.dates, y: d.values.map(v => (v - 1) * 100),
      mode: "lines", name: "Portfolio",
      line: {color: "#ffffff", width: 2.5},
      hovertemplate: "Portfolio: %{y:.2f}%<extra></extra>",
    });
  }
  Plotly.react("chart-returns", traces, {
    paper_bgcolor: "transparent", plot_bgcolor: "#0a1020",
    xaxis: {color: "#94a3b8", gridcolor: "#1e2d45", zeroline: false},
    yaxis: {title: "Cumulative Return (%)", color: "#94a3b8", gridcolor: "#1e2d45", zeroline: false},
    legend: {font: {color: "#94a3b8"}, bgcolor: "transparent", orientation: "h", y: -0.18},
    margin: {l: 55, r: 12, t: 12, b: 65}, font: {color: "#94a3b8"}, hovermode: "x unified",
  }, {responsive: true, displayModeBar: false});
}

function renderDrawdownChart(dd_series) {
  Plotly.react("chart-drawdown", [{
    x: dd_series.dates, y: dd_series.values,
    mode: "lines", fill: "tozeroy",
    fillcolor: "rgba(239,68,68,0.15)",
    line: {color: "#ef4444", width: 1.2},
    hovertemplate: "%{x}: %{y:.2f}%<extra>Drawdown</extra>",
  }], {
    paper_bgcolor: "transparent", plot_bgcolor: "#0a1020",
    xaxis: {color: "#94a3b8", gridcolor: "#1e2d45", zeroline: false},
    yaxis: {title: "Drawdown (%)", color: "#94a3b8", gridcolor: "#1e2d45", zeroline: true, zerolinecolor: "#334155"},
    margin: {l: 55, r: 12, t: 8, b: 40}, font: {color: "#94a3b8"}, hovermode: "x unified",
    shapes: [{type:"line", x0:dd_series.dates[0], x1:dd_series.dates[dd_series.dates.length-1],
      y0:0, y1:0, line:{color:"#475569", width:1}}],
  }, {responsive: true, displayModeBar: false});
}

let _currentRollingWindow = 60;
let _lastRollingData = null;

function setRollingWindow(win) {
  _currentRollingWindow = win;
  document.querySelectorAll("#rolling-win-btns .win-btn").forEach(b => {
    b.classList.toggle("active", parseInt(b.textContent) === win);
  });
  if (_lastRollingData) renderRollingChart(_lastRollingData, win);
}

function renderRollingChart(rolling_metrics, win) {
  _lastRollingData = rolling_metrics;
  const key = String(win || _currentRollingWindow);
  const d = rolling_metrics?.[key];
  if (!d) {
    document.getElementById("chart-rolling").innerHTML =
      `<div style="color:var(--muted);text-align:center;padding-top:60px;font-size:12px;">Not enough data for a ${key}-day rolling window.</div>`;
    return;
  }
  const traces = [
    {x: d.dates, y: d.volatility, name: "Rolling Vol (%)",
     mode: "lines", line: {color: "#06b6d4", width: 1.5}, yaxis: "y",
     hovertemplate: "Vol: %{y:.2f}%<extra></extra>"},
    {x: d.dates, y: d.sharpe, name: "Rolling Sharpe",
     mode: "lines", line: {color: "#f59e0b", width: 1.8}, yaxis: "y2",
     hovertemplate: "Sharpe: %{y:.3f}<extra></extra>"},
  ];
  if (d.beta) {
    traces.push({x: d.dates, y: d.beta, name: "Rolling Beta",
      mode: "lines", line: {color: "#8b5cf6", width: 1.5, dash: "dot"}, yaxis: "y2",
      hovertemplate: "Beta: %{y:.3f}<extra></extra>"});
  }
  traces.push({x:[d.dates[0],d.dates[d.dates.length-1]], y:[0,0],
    mode:"lines", line:{color:"#334155",width:1}, yaxis:"y2",
    showlegend:false, hoverinfo:"skip"});
  Plotly.react("chart-rolling", traces, {
    paper_bgcolor: "transparent", plot_bgcolor: "#0a1020",
    xaxis: {color: "#94a3b8", gridcolor: "#1e2d45", zeroline: false},
    yaxis: {title: "Volatility (%)", color: "#06b6d4", gridcolor: "#1e2d45", zeroline: false},
    yaxis2: {title: "Sharpe / Beta", color: "#f59e0b", overlaying: "y", side: "right", zeroline: false, gridcolor: "transparent"},
    legend: {font: {color: "#94a3b8"}, bgcolor: "transparent", orientation: "h", y: -0.22},
    margin: {l: 55, r: 55, t: 8, b: 60}, font: {color: "#94a3b8"}, hovermode: "x unified",
  }, {responsive: true, displayModeBar: false});
}

function renderCorrChart(corr) {
  const syms = Object.keys(corr);
  const z    = syms.map(r => syms.map(c => corr[r][c]));
  Plotly.react("chart-corr", [{
    type:"heatmap", z, x:syms, y:syms,
    text:z.map(row=>row.map(v=>v.toFixed(2))), texttemplate:"%{text}",
    colorscale:[[0,"#7f1d1d"],[0.5,"#1e2d45"],[1,"#052e16"]],
    zmin:-1, zmax:1, showscale:true,
    hovertemplate:"%{y} / %{x}: %{z:.3f}<extra></extra>",
    colorbar:{tickfont:{color:"#94a3b8"},outlinewidth:0},
  }], {
    paper_bgcolor:"transparent", plot_bgcolor:"transparent",
    xaxis:{color:"#94a3b8"}, yaxis:{color:"#94a3b8",autorange:"reversed"},
    margin:{l:55,r:12,t:12,b:55}, font:{color:"#94a3b8",size:11},
  }, {responsive:true,displayModeBar:false});
}

function renderBLAcademicPlots(bl, weights) {
  const syms = Object.keys(bl.prior_returns);
  const layoutTpl = { paper_bgcolor:"transparent", plot_bgcolor:"#0a1020", font:{color:"#94a3b8",size:10}, legend:{bgcolor:"transparent",orientation:"h",y:-0.15}, margin:{l:45,r:12,t:12,b:50} };

  Plotly.react("chart-bl-step1", [
    { name:"Market Weight", x:syms, y:syms.map(s=>bl.market_weights[s]*100), type:"bar", marker:{color:"#3b82f6"}, yaxis:"y", hovertemplate:"%{x}: %{y:.1f}%<extra>Market Weight</extra>" },
    { name:"Implied Return (Π)", x:syms, y:syms.map(s=>bl.prior_returns[s]*100), type:"scatter", mode:"lines+markers", marker:{color:"#f59e0b",size:8}, line:{width:2}, yaxis:"y2", hovertemplate:"%{x}: %{y:.2f}%<extra>Implied Return</extra>" }
  ], {
    ...layoutTpl,
    xaxis:{color:"#94a3b8",gridcolor:"transparent"},
    yaxis:{title:"Weight (%)",color:"#3b82f6",gridcolor:"#1e2d45"},
    yaxis2:{title:"Implied Return (%)",color:"#f59e0b",overlaying:"y",side:"right",gridcolor:"transparent"}
  }, {responsive:true,displayModeBar:false});

  const viewSyms = Object.keys(bl.views);
  if (viewSyms.length > 0) {
    Plotly.react("chart-bl-step34", [
      { name:"View Return", x:viewSyms, y:viewSyms.map(s=>bl.views[s]*100), type:"bar", marker:{color:"#10b981"}, yaxis:"y", hovertemplate:"%{x}: %{y:.1f}%<extra>View Return</extra>" },
      { name:"Confidence", x:viewSyms, y:viewSyms.map(s=>(bl.confidences[s]||0)*100), type:"scatter", mode:"lines+markers", marker:{color:"#8b5cf6",size:8}, line:{width:2}, yaxis:"y2", hovertemplate:"%{x}: %{y:.0f}%<extra>Confidence</extra>" }
    ], {
      ...layoutTpl,
      xaxis:{color:"#94a3b8",gridcolor:"transparent"},
      yaxis:{title:"View Expected Return (%)",color:"#10b981",gridcolor:"#1e2d45"},
      yaxis2:{title:"Confidence Level (%)",color:"#8b5cf6",overlaying:"y",side:"right",gridcolor:"transparent",range:[0,105]}
    }, {responsive:true,displayModeBar:false});
  } else {
    document.getElementById("chart-bl-step34").innerHTML = `<div style="color:var(--muted);text-align:center;padding-top:40px;">No investor views defined.</div>`;
  }

  Plotly.react("chart-bl-step5", [
    { name:"Implied Prior", x:syms, y:syms.map(s=>bl.prior_returns[s]*100), type:"bar", marker:{color:"#3b82f6",opacity:0.7}, hovertemplate:"%{x}: %{y:.2f}%<extra>Prior</extra>" },
    { name:"Blended Posterior", x:syms, y:syms.map(s=>bl.posterior_returns[s]*100), type:"bar", marker:{color:"#8b5cf6"}, hovertemplate:"%{x}: %{y:.2f}%<extra>Posterior</extra>" }
  ], {
    ...layoutTpl, barmode:"group",
    xaxis:{color:"#94a3b8",gridcolor:"transparent"},
    yaxis:{title:"Annual Expected Return (%)",color:"#94a3b8",gridcolor:"#1e2d45"}
  }, {responsive:true,displayModeBar:false});

  const activeW = syms.map(s => ((weights[s]||0) - (bl.market_weights[s]||0)) * 100);
  const activeColors = activeW.map(v => v >= 0 ? "#10b981" : "#ef4444");
  Plotly.react("chart-bl-step6", [{
    x:syms, y:activeW, type:"bar", marker:{color:activeColors}, hovertemplate:"%{x}: %{y:.2f}%<extra>Active Weight</extra>"
  }], {
    ...layoutTpl, showlegend:false,
    xaxis:{color:"#94a3b8",gridcolor:"transparent"},
    yaxis:{title:"Deviation from Market (%)",color:"#94a3b8",gridcolor:"#1e2d45",zeroline:true,zerolinecolor:"#94a3b8"}
  }, {responsive:true,displayModeBar:false});

  if (bl.sensitivity && Object.keys(bl.sensitivity).length > 0) {
    const s_syms = Object.keys(bl.sensitivity);
    Plotly.react("chart-bl-step7", [
      { name:"Low Conviction (-50%)", x:s_syms, y:s_syms.map(s=>bl.sensitivity[s].low*100), type:"bar", marker:{color:"#0ea5e9"} },
      { name:"Baseline Conviction", x:s_syms, y:s_syms.map(s=>bl.sensitivity[s].base*100), type:"bar", marker:{color:"#6366f1"} },
      { name:"High Conviction (+50%)", x:s_syms, y:s_syms.map(s=>bl.sensitivity[s].high*100), type:"bar", marker:{color:"#d946ef"} }
    ], {
      ...layoutTpl, barmode:"group",
      xaxis:{color:"#94a3b8",gridcolor:"transparent"},
      yaxis:{title:"Allocated Weight (%)",color:"#94a3b8",gridcolor:"#1e2d45"}
    }, {responsive:true,displayModeBar:false});
  } else {
    document.getElementById("chart-bl-step7").innerHTML = `<div style="color:var(--muted);text-align:center;padding-top:40px;">No sensitivity data generated.</div>`;
  }
}

function renderHRPAcademicPlots(hrp) {
  const t_raw = hrp.tickers;
  const t_sorted = hrp.sorted_tickers;
  const layoutTpl = { paper_bgcolor:"transparent", plot_bgcolor:"#0a1020", font:{color:"#94a3b8",size:10}, margin:{l:45,r:12,t:35,b:50} };

  Plotly.react("chart-hrp-step1", [{
    z: hrp.distance_matrix, x: t_raw, y: t_raw,
    type: "heatmap", colorscale: [[0,"#0a1020"],[1,"#3b82f6"]], showscale:false,
    hovertemplate: "%{x} - %{y}<br>Distance: %{z:.3f}<extra></extra>"
  }], {
    ...layoutTpl, title: {text: "Based on √0.5*(1-ρ)", font:{size:11,color:"#64748b"}},
    xaxis:{tickangle:-45,color:"#94a3b8"}, yaxis:{autorange:"reversed",color:"#94a3b8"}
  }, {responsive:true,displayModeBar:false});

  Plotly.react("chart-hrp-step2", [{
    z: hrp.qd_correlation, x: t_sorted, y: t_sorted,
    type: "heatmap", colorscale: [[0,"#ef4444"],[0.5,"#0a1020"],[1,"#10b981"]], zmin:-1, zmax:1, showscale:false,
    hovertemplate: "%{x} - %{y}<br>Correlation: %{z:.3f}<extra></extra>"
  }], {
    ...layoutTpl, title: {text: "Ordered by Hierarchical Clustering", font:{size:11,color:"#64748b"}},
    xaxis:{tickangle:-45,color:"#94a3b8"}, yaxis:{autorange:"reversed",color:"#94a3b8"}
  }, {responsive:true,displayModeBar:false});

  const rc = t_sorted.map(s => hrp.risk_contributions[s]);
  Plotly.react("chart-hrp-step3", [{
    x: t_sorted, y: rc, type: "bar", marker:{color:"#8b5cf6"},
    hovertemplate: "%{x}: %{y:.2f}% risk contribution<extra></extra>"
  }], {
    ...layoutTpl,
    xaxis:{color:"#94a3b8",gridcolor:"transparent"},
    yaxis:{title:"Risk Contribution (%)",color:"#94a3b8",gridcolor:"#1e2d45"}
  }, {responsive:true,displayModeBar:false});
}

// ═══════════════════════════════════════════════════════════════════ METRICS DETAIL
function renderMetricsDetail(m) {
  const fmt  = (v, dec=2, suffix="%") => v != null ? `${v >= 0 ? "+" : ""}${v.toFixed(dec)}${suffix}` : "—";
  const fmtN = (v, dec=2)            => v != null ? v.toFixed(dec) : "—";
  const cls  = v => v > 0 ? "pos" : v < 0 ? "neg" : "neu";

  const groups = [
    { title: "Performance", rows: [
      ["Expected Return",  fmt(m.expected_return), cls(m.expected_return)],
      ["Volatility",       fmt(m.volatility), "neu"],
      ["Sharpe Ratio",     fmtN(m.sharpe_ratio, 3), cls(m.sharpe_ratio)],
      ["Sortino Ratio",    fmtN(m.sortino_ratio, 3), cls(m.sortino_ratio)],
      ["Calmar Ratio",     fmtN(m.calmar_ratio, 3), cls(m.calmar_ratio)],
      ["Win Rate",         fmt(m.win_rate), cls(m.win_rate - 50)],
      ["Gain/Loss Ratio",  fmtN(m.gain_loss_ratio, 3), cls(m.gain_loss_ratio - 1)],
    ]},
    { title: "Drawdown & Tail", rows: [
      ["Max Drawdown",     fmt(m.max_drawdown), cls(m.max_drawdown)],
      ["Avg Drawdown",     fmt(m.avg_drawdown), cls(m.avg_drawdown)],
      ["Max DD Duration",  `${m.max_dd_duration} days`, "neu"],
      ["Avg DD Duration",  `${m.avg_dd_duration} days`, "neu"],
      ["Worst Day",        fmt(m.worst_day), cls(m.worst_day)],
      ["Best Day",         fmt(m.best_day), cls(m.best_day)],
      ["Worst Month",      fmt(m.worst_month), cls(m.worst_month)],
      ["Best Month",       fmt(m.best_month), cls(m.best_month)],
    ]},
    { title: "Value at Risk", rows: [
      ["VaR 95% (daily)",     fmt(m.var_95_daily), "neg"],
      ["VaR 99% (daily)",     fmt(m.var_99_daily), "neg"],
      ["CVaR 95% (daily)",    fmt(m.cvar_95_daily), "neg"],
      ["CVaR 99% (daily)",    fmt(m.cvar_99_daily), "neg"],
      ["Param VaR 95% (ann)", fmt(m.param_var_95_ann), "neg"],
      ["Param VaR 99% (ann)", fmt(m.param_var_99_ann), "neg"],
    ]},
    { title: "Benchmark vs SPY", rows: [
      ["Beta",           fmtN(m.beta, 3), "neu"],
      ["Alpha",          fmt(m.alpha), cls(m.alpha)],
      ["Treynor Ratio",  fmtN(m.treynor_ratio, 3), cls(m.treynor_ratio)],
      ["Tracking Error", fmt(m.tracking_error), "neu"],
      ["Info Ratio",     fmtN(m.info_ratio, 3), cls(m.info_ratio)],
      ["R²",             fmtN(m.r_squared, 4), "neu"],
      ["Skewness",       fmtN(m.skewness, 3), cls(-m.skewness)],
      ["Kurtosis",       fmtN(m.kurtosis, 3), "neu"],
    ]},
  ];

  document.getElementById("metrics-detail").innerHTML = `
    <div class="mdetail">
      ${groups.map(g => `
        <div class="mdetail-group">
          <div class="mdetail-group-title">${g.title}</div>
          ${g.rows.map(([lbl,val,c]) => `
            <div class="mdetail-row">
              <span class="mdetail-label">${lbl}</span>
              <span class="mdetail-val ${c}">${val}</span>
            </div>`).join("")}
        </div>`).join("")}
    </div>
    <div style="margin-top:6px;font-size:10px;color:var(--muted);text-align:right;">
      Based on ${m.n_days} trading days
    </div>`;
}

// ═══════════════════════════════════════════════════════════════════ MONTE CARLO
async function runMonteCarlo() {
  const p = activeProject();
  if (!p?.results) return;
  const btn = document.getElementById("mc-btn");
  btn.disabled = true; btn.textContent = "Running…";

  try {
    const res = await fetch("/api/montecarlo", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        weights:    p.results.weights,
        start_date: p.settings.startDate,
        end_date:   p.settings.endDate,
        horizon:    parseInt(document.getElementById("mc-horizon").value),
        n_sims:     parseInt(document.getElementById("mc-nsims").value),
      }),
    });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }
    renderMonteCarloChart(data);
  } catch(e) { alert("Error: " + e.message); }
  finally { btn.disabled = false; btn.textContent = "▶ Run Simulation"; }
}

function renderMonteCarloChart(mc) {
  const statsBar = document.getElementById("mc-stats-bar");
  statsBar.style.display = "flex";
  const pRetColor = mc.final_median >= 0 ? "var(--green)" : "var(--red)";
  statsBar.innerHTML = [
    ["Prob. Profit",    `${mc.prob_profit}%`,    mc.prob_profit >= 50 ? "var(--green)" : "var(--red)"],
    ["Median Return",   `${mc.final_median >= 0 ? "+" : ""}${mc.final_median}%`, pRetColor],
    ["5th Percentile",  `${mc.final_p5}%`,       "var(--red)"],
    ["95th Percentile", `+${mc.final_p95}%`,     "var(--green)"],
    ["Prob. Loss >20%", `${mc.prob_loss_20pct}%`,mc.prob_loss_20pct > 20 ? "var(--red)" : "var(--muted2)"],
  ].map(([lbl,val,clr]) => `<div class="mc-stat">
    <div class="mc-stat-label">${lbl}</div>
    <div class="mc-stat-val" style="color:${clr};">${val}</div>
  </div>`).join("");

  const mcEl = document.getElementById("chart-montecarlo");
  mcEl.innerHTML = "";

  const days = Array.from({length: mc.horizon}, (_, i) => i + 1);
  const traces = [];
  mc.sample_paths.forEach(path => traces.push({
    x: days, y: path, mode: "lines",
    line: {color: "rgba(59,130,246,0.07)", width: 1},
    showlegend: false, hoverinfo: "skip",
  }));
  traces.push({
    x: [...days, ...days.slice().reverse()],
    y: [...mc.percentiles.p95, ...mc.percentiles.p5.slice().reverse()],
    fill: "toself", fillcolor: "rgba(59,130,246,0.12)",
    line: {color: "transparent"}, name: "90% CI", hoverinfo: "skip",
  });
  traces.push({x: days, y: mc.percentiles.p5,  name: "5th %ile",  mode: "lines", line: {color:"#ef4444",width:1.5,dash:"dash"}, hovertemplate:"Day %{x}: %{y:.2f}%<extra>5th %ile</extra>"});
  traces.push({x: days, y: mc.percentiles.p50, name: "Median",    mode: "lines", line: {color:"#10b981",width:2},               hovertemplate:"Day %{x}: %{y:.2f}%<extra>Median</extra>"});
  traces.push({x: days, y: mc.percentiles.p95, name: "95th %ile", mode: "lines", line: {color:"#3b82f6",width:1.5,dash:"dash"}, hovertemplate:"Day %{x}: %{y:.2f}%<extra>95th %ile</extra>"});
  traces.push({x: [1, mc.horizon], y: [0, 0], mode: "lines", line:{color:"#475569",width:1,dash:"dot"}, showlegend:false, hoverinfo:"skip"});

  Plotly.react("chart-montecarlo", traces, {
    paper_bgcolor:"transparent", plot_bgcolor:"#0a1020",
    xaxis:{title:"Trading Days", color:"#94a3b8", gridcolor:"#1e2d45"},
    yaxis:{title:"Return (%)",   color:"#94a3b8", gridcolor:"#1e2d45", zeroline:false},
    legend:{font:{color:"#94a3b8"},bgcolor:"transparent",orientation:"h",y:-0.22},
    margin:{l:55,r:12,t:8,b:60}, font:{color:"#94a3b8"}, hovermode:"x unified",
  }, {responsive:true, displayModeBar:false});
}

// ═══════════════════════════════════════════════════════════════════ STRESS TEST
async function runStressTest() {
  const p = activeProject();
  if (!p?.results) return;
  const btn = document.getElementById("stress-btn");
  btn.disabled = true; btn.textContent = "Running…";

  try {
    const res = await fetch("/api/stress", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({weights: p.results.weights}),
    });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }
    renderStressResults(data.scenarios);
  } catch(e) { alert("Error: " + e.message); }
  finally { btn.disabled = false; btn.textContent = "▶ Run Stress Test"; }
}

function renderStressResults(scenarios) {
  const rows = Object.entries(scenarios).map(([, sc]) => {
    if (sc.error) return `<tr>
      <td><strong>${sc.name}</strong><br><span style="font-size:10px;color:var(--muted);">${sc.period}</span></td>
      <td colspan="3" style="color:var(--muted);font-size:11px;">No price data for this period</td></tr>`;

    const pr = sc.portfolio_return;
    const sr = sc.spy_return;
    const vs = sr != null ? (pr - sr) : null;
    const c  = v => v >= 0 ? "var(--green)" : "var(--red)";
    const sg = v => v >= 0 ? "+" : "";
    const pills = Object.entries(sc.asset_returns || {})
      .filter(([,v]) => v != null)
      .map(([sym,v]) => `<span class="stress-pill" style="background:${v>=0?"rgba(16,185,129,.15)":"rgba(239,68,68,.15)"};color:${v>=0?"var(--green)":"var(--red)"};">${sym}: ${sg(v)}${v}%</span>`)
      .join("");
    return `<tr>
      <td>
        <strong>${sc.name}</strong><br>
        <span style="font-size:10px;color:var(--muted);">${sc.period}</span><br>
        <div class="stress-asset-pills">${pills}</div>
      </td>
      <td style="font-weight:700;color:${c(pr)};font-size:13px;">${sg(pr)}${pr}%</td>
      <td style="color:${sr!=null?c(sr):"var(--muted)"};">${sr!=null?sg(sr)+sr+"%":"—"}</td>
      <td style="font-weight:600;color:${vs!=null?c(vs):"var(--muted)"};">${vs!=null?sg(vs)+vs.toFixed(2)+"%":"—"}</td>
    </tr>`;
  }).join("");
  document.getElementById("stress-results").innerHTML = `
    <table class="wtable">
      <thead><tr><th>Scenario</th><th>Portfolio</th><th>SPY</th><th>vs SPY</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ═══════════════════════════════════════════════════════════════════ EXPORT CSV
function exportCSV() {
  const p = activeProject();
  if (!p?.results) return;
  const { weights, analytics } = p.results;
  const m = analytics.metrics;
  const contrib = analytics.contributions || {};

  let csv = `"${p.name} — Portfolio Export"\n\nWeights\nTicker,Weight (%),Ann Return (%),Volatility (%),Risk Contrib (%)\n`;
  Object.entries(weights).sort((a,b) => b[1]-a[1]).forEach(([sym, w]) => {
    const c = contrib[sym] || {};
    csv += `${sym},${(w*100).toFixed(4)},${c.ann_return??""}, ${c.ann_vol??""},${c.risk_contrib_pct??""}\n`;
  });
  csv += `\nMetrics\nMetric,Value\n`;
  const metricMap = [
    ["Expected Return (%)", m.expected_return], ["Volatility (%)", m.volatility],
    ["Sharpe Ratio", m.sharpe_ratio],           ["Sortino Ratio", m.sortino_ratio],
    ["Calmar Ratio", m.calmar_ratio],           ["Max Drawdown (%)", m.max_drawdown],
    ["Avg Drawdown (%)", m.avg_drawdown],       ["Max DD Duration (days)", m.max_dd_duration],
    ["Win Rate (%)", m.win_rate],               ["Gain/Loss Ratio", m.gain_loss_ratio],
    ["VaR 95% Daily (%)", m.var_95_daily],      ["CVaR 95% Daily (%)", m.cvar_95_daily],
    ["Beta", m.beta],                           ["Alpha (%)", m.alpha],
    ["Tracking Error (%)", m.tracking_error],   ["Info Ratio", m.info_ratio],
    ["Skewness", m.skewness],                   ["Kurtosis", m.kurtosis],
    ["Best Day (%)", m.best_day],               ["Worst Day (%)", m.worst_day],
    ["Trading Days", m.n_days],
  ];
  metricMap.forEach(([label, val]) => { csv += `${label},${val ?? ""}\n`; });

  const blob = new Blob([csv], {type: "text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${p.name.replace(/\s+/g, "_")}_portfolio.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ═══════════════════════════════════════════════════════════════════ DOWNLOAD NOTEBOOK
function downloadNotebook() {
  const p = activeProject();
  if (!p?.results) return;
  const { weights, analytics } = p.results;
  const m = analytics.metrics;
  const contrib = analytics.contributions || {};
  const cum = analytics.cumulative_returns || {};
  const dd  = analytics.drawdown_series   || {};
  const corr = analytics.correlation      || {};

  const weightsJson = JSON.stringify(weights, null, 2);
  const metricsJson = JSON.stringify(m, null, 2);
  const contribJson = JSON.stringify(contrib, null, 2);
  const cumJson     = JSON.stringify(cum, null, 2);
  const ddJson      = JSON.stringify(dd, null, 2);
  const corrJson    = JSON.stringify(corr, null, 2);
  const tickers     = Object.keys(weights).filter(k => weights[k] > 0.001);

  const cells = [
    { cell_type:"markdown", source:[`# ${p.name} — Portfolio Analysis\n\nGenerated by PortOpt on ${new Date().toLocaleDateString()}.\n\n**Period:** ${p.settings.startDate} → ${p.settings.endDate}  |  **Method:** ${p.settings.method}  |  **Risk-free rate:** ${p.settings.rfr}%`] },
    { cell_type:"code", source:[
      "import json, pandas as pd, numpy as np, matplotlib.pyplot as plt, matplotlib.ticker as mticker\n",
      "from matplotlib.gridspec import GridSpec\n",
      "plt.style.use('dark_background')\n",
      "COLORS = ['#3b82f6','#06b6d4','#10b981','#f59e0b','#8b5cf6','#ef4444','#ec4899','#14b8a6','#f97316','#a855f7']\n\n",
      `weights = ${weightsJson}\n`,
      `metrics = ${metricsJson}\n`,
      `contributions = ${contribJson}\n`,
      `cumulative_returns = ${cumJson}\n`,
      `drawdown_series = ${ddJson}\n`,
      `correlation = ${corrJson}\n`,
      `tickers = ${JSON.stringify(tickers)}\n`,
    ]},
    { cell_type:"markdown", source:["## Portfolio Metrics Summary\n\nKey risk and performance indicators for the optimized portfolio."] },
    { cell_type:"code", source:[
      "summary = {\n",
      "    'Expected Return (%)': metrics['expected_return'],\n",
      "    'Volatility (%)':       metrics['volatility'],\n",
      "    'Sharpe Ratio':         metrics['sharpe_ratio'],\n",
      "    'Sortino Ratio':        metrics['sortino_ratio'],\n",
      "    'Max Drawdown (%)':     metrics['max_drawdown'],\n",
      "    'Beta vs SPY':          metrics['beta'],\n",
      "    'Alpha (%)':            metrics['alpha'],\n",
      "    'VaR 95% Daily (%)':    metrics['var_95_daily'],\n",
      "    'CVaR 95% Daily (%)':   metrics['cvar_95_daily'],\n",
      "    'Win Rate (%)':         metrics['win_rate'],\n",
      "}\n",
      "pd.Series(summary).to_frame('Value').round(4)\n",
    ]},
    { cell_type:"markdown", source:["## Portfolio Weights\n\nOptimized allocation with per-asset risk and return contribution."] },
    { cell_type:"code", source:[
      "rows = []\n",
      "for sym, w in sorted(weights.items(), key=lambda x: -x[1]):\n",
      "    c = contributions.get(sym, {})\n",
      "    rows.append({'Ticker': sym, 'Weight (%)': round(w*100,2),\n",
      "                 'Ann Return (%)': c.get('ann_return'), 'Ann Vol (%)': c.get('ann_vol'),\n",
      "                 'Risk Contrib (%)': c.get('risk_contrib_pct')})\n",
      "df_w = pd.DataFrame(rows).set_index('Ticker')\n",
      "print(df_w.to_string())\n",
      "\n",
      "fig, ax = plt.subplots(figsize=(8,4))\n",
      "bars = ax.barh(df_w.index[::-1], df_w['Weight (%)'][::-1], color=COLORS[:len(df_w)])\n",
      "ax.set_xlabel('Weight (%)')\n",
      "ax.set_title('Portfolio Weights')\n",
      "plt.tight_layout()\nplt.show()\n",
    ]},
    { cell_type:"markdown", source:["## Cumulative Returns\n\nHistorical growth of $1 invested in each asset and the blended portfolio vs SPY."] },
    { cell_type:"code", source:[
      "fig, ax = plt.subplots(figsize=(12,5))\n",
      "special = ['__PORTFOLIO__','__SPY__']\n",
      "for i, (sym, d) in enumerate(cumulative_returns.items()):\n",
      "    if sym in special: continue\n",
      "    ax.plot(pd.to_datetime(d['dates']), [(v-1)*100 for v in d['values']],\n",
      "            label=sym, linewidth=1.2, alpha=0.7, color=COLORS[i % len(COLORS)])\n",
      "if '__SPY__' in cumulative_returns:\n",
      "    d = cumulative_returns['__SPY__']\n",
      "    ax.plot(pd.to_datetime(d['dates']), [(v-1)*100 for v in d['values']],\n",
      "            label='SPY', linewidth=1.5, linestyle='--', color='#64748b')\n",
      "if '__PORTFOLIO__' in cumulative_returns:\n",
      "    d = cumulative_returns['__PORTFOLIO__']\n",
      "    ax.plot(pd.to_datetime(d['dates']), [(v-1)*100 for v in d['values']],\n",
      "            label='Portfolio', linewidth=2.5, color='white')\n",
      "ax.set_ylabel('Cumulative Return (%)')\n",
      "ax.set_title('Historical Cumulative Returns')\n",
      "ax.legend(fontsize=8, ncol=4)\n",
      "plt.tight_layout()\nplt.show()\n",
    ]},
    { cell_type:"markdown", source:["## Portfolio Drawdown\n\nPercentage decline from the most recent peak at each point in time."] },
    { cell_type:"code", source:[
      "dates = pd.to_datetime(drawdown_series['dates'])\n",
      "vals  = drawdown_series['values']\n",
      "fig, ax = plt.subplots(figsize=(12,3))\n",
      "ax.fill_between(dates, vals, 0, alpha=0.3, color='#ef4444')\n",
      "ax.plot(dates, vals, color='#ef4444', linewidth=1.2)\n",
      "ax.axhline(0, color='#475569', linewidth=1)\n",
      "ax.set_ylabel('Drawdown (%)')\n",
      "ax.set_title('Portfolio Drawdown')\n",
      "plt.tight_layout()\nplt.show()\n",
    ]},
    { cell_type:"markdown", source:["## Correlation Matrix\n\nPairwise correlation of daily returns. Values close to −1 offer the best diversification benefit."] },
    { cell_type:"code", source:[
      "import seaborn as sns\n",
      "syms = list(correlation.keys())\n",
      "mat  = [[correlation[r][c] for c in syms] for r in syms]\n",
      "df_corr = pd.DataFrame(mat, index=syms, columns=syms)\n",
      "fig, ax = plt.subplots(figsize=(max(6,len(syms)), max(5,len(syms)-1)))\n",
      "sns.heatmap(df_corr, annot=True, fmt='.2f', cmap='RdYlGn', vmin=-1, vmax=1,\n",
      "            linewidths=0.5, ax=ax, annot_kws={'size':9})\n",
      "ax.set_title('Correlation Matrix')\n",
      "plt.tight_layout()\nplt.show()\n",
    ]},
    { cell_type:"markdown", source:["---\n*Generated by PortOpt. Data from Yahoo Finance via yfinance.*"] },
  ];

  const ipynb = {
    nbformat: 4, nbformat_minor: 5,
    metadata: { kernelspec: { display_name:"Python 3", language:"python", name:"python3" }, language_info: { name:"python" } },
    cells: cells.map((c,i) => ({
      ...c,
      id: `cell-${i}`,
      metadata: {},
      outputs: c.cell_type === "code" ? [] : undefined,
      execution_count: c.cell_type === "code" ? null : undefined,
    })),
  };

  const blob = new Blob([JSON.stringify(ipynb, null, 1)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${p.name.replace(/\s+/g,"_")}_portfolio.ipynb`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ═══════════════════════════════════════════════════════════════════ DOWNLOAD PDF
function downloadPDF() {
  const p = activeProject();
  if (!p?.results) return;
  const prev = document.title;
  document.title = p.name + " — PortOpt Report";
  window.print();
  document.title = prev;
}

// ═══════════════════════════════════════════════════════════════════ INIT
loadProjects();
if (!projects.length) projects = [makeProject("Portfolio 1")];
activeId = projects[0].id;
renderTabs();
loadProjectIntoUI(activeProject());
onMethodChange();
