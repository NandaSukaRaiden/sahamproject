/* ============================================================
   app.js — AI Trading Bot Saham Indonesia
   Frontend Logic: API calls, Charts, UI rendering
   ============================================================ */

const API = 'http://localhost:5000/api';
let currentTicker   = '';
let currentAnalysis = null;
let currentChart    = null;
let allHistory      = [];
let currentAI       = null;        // data.ai_analysis.data terakhir
let currentScoreMode = 'ai';       // 'ai' | 'raw' — skor yang ditampilkan

// ─── SSE Realtime Stream ──────────────────────────────────────
let _sseSource = null;

function startSSEStream() {
  if (_sseSource && _sseSource.readyState !== EventSource.CLOSED) return;

  _sseSource = new EventSource(`${API}/stream`);

  const badge = document.getElementById('sse-status-badge');
  const badgeTxt = document.getElementById('sse-status-text');

  _sseSource.onopen = () => {
    if (badge) badge.classList.remove('offline');
    if (badgeTxt) badgeTxt.textContent = 'LIVE';
  };

  _sseSource.onerror = () => {
    if (badge) badge.classList.add('offline');
    if (badgeTxt) badgeTxt.textContent = 'RECONNECT';
    setTimeout(startSSEStream, 5000);
  };
  _sseSource.addEventListener('ping', () => {}); // keepalive, abaikan

  _sseSource.addEventListener('portfolio', e => {
    try {
      const d = JSON.parse(e.data);
      if (d.error) return;
      _updatePortfolioNumbers(d);
    } catch(_) {}
  });

  // ── trade: notifikasi order masuk instan ──
  _sseSource.addEventListener('trade', e => {
    try {
      const d = JSON.parse(e.data);
      _onTradeEvent(d);
    } catch(_) {}
  });

  // ── flow: dana keluar/masuk watchlist ──
  _sseSource.addEventListener('flow', e => {
    try {
      const d = JSON.parse(e.data);
      _updateFlowTicker(d);
    } catch(_) {}
  });

  // ── prices: harga posisi aktif ──
  _sseSource.addEventListener('prices', e => {
    try {
      const d = JSON.parse(e.data);
      _updatePositionPrices(d.prices || {});
    } catch(_) {}
  });

  _sseSource.onerror = () => {
    // Auto-reconnect setelah 5 detik
    setTimeout(startSSEStream, 5000);
  };
}

/** Update angka portfolio di semua halaman tanpa render ulang */
function _updatePortfolioNumbers(d) {
  // ── Dashboard stats ──
  const pnlColor = d.total_pnl_rp >= 0 ? 'var(--green)' : 'var(--red)';
  const totalEl = document.getElementById('stat-total');
  if (totalEl) totalEl.textContent = `Rp ${formatNum(d.total_portfolio_value, 0)}`;

  const pnlEl = document.getElementById('stat-pnl');
  if (pnlEl) pnlEl.innerHTML =
    `<span style="color:${pnlColor}">${d.total_pnl_rp >= 0 ? '+' : ''}Rp ${formatNum(d.total_pnl_rp, 0)} (${d.total_pnl_pct >= 0 ? '+' : ''}${d.total_pnl_pct.toFixed(2)}%)</span>`;

  const cashEl = document.getElementById('stat-cash');
  if (cashEl) cashEl.textContent = `Rp ${formatNum(d.cash, 0)}`;

  // ── Live Portfolio Panel (khusus di page portfolio) ──
  const livePanel = document.getElementById('rt-portfolio-panel');
  if (livePanel) _renderLivePortfolio(d, livePanel);

  // Timestamp
  const tsEl = document.getElementById('rt-port-timestamp');
  if (tsEl) tsEl.textContent = new Date().toLocaleTimeString('id-ID', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Jakarta'
  }) + ' WIB';

  // ── Live Flow Panel ──
  const flowPanel = document.getElementById('rt-flow-panel');
  if (flowPanel && (!flowPanel.children.length || flowPanel.querySelector('.empty-msg'))) {
    flowPanel.innerHTML = '';
  }

  // ── Update posisi di dashboard ──
  if (d.positions) renderDashboardPositions(d.positions);

  // ── Update recent orders di Trade page ──
  if (d.last_trades) _renderLiveTrades(d.last_trades);
}

/** Flash animasi saat nilai berubah */
function _flashEl(el, color) {
  if (!el) return;
  el.style.transition = 'background 0.1s';
  el.style.background = color + '30';
  setTimeout(() => { el.style.background = ''; }, 600);
}

/** Render live portfolio di panel realtime */
function _renderLivePortfolio(d, container) {
  const pnlColor = d.total_pnl_rp >= 0 ? 'var(--green)' : 'var(--red)';
  let html = `
    <div class="rt-summary">
      <div class="rt-stat">
        <div class="rt-label">Total Portfolio</div>
        <div class="rt-value">Rp ${formatNum(d.total_portfolio_value, 0)}</div>
      </div>
      <div class="rt-stat">
        <div class="rt-label">Cash</div>
        <div class="rt-value">Rp ${formatNum(d.cash, 0)}</div>
      </div>
      <div class="rt-stat">
        <div class="rt-label">P&L Total</div>
        <div class="rt-value" style="color:${pnlColor}">
          ${d.total_pnl_rp >= 0 ? '+' : ''}Rp ${formatNum(d.total_pnl_rp, 0)}<br>
          <span style="font-size:11px">${d.total_pnl_pct >= 0 ? '+' : ''}${d.total_pnl_pct.toFixed(2)}%</span>
        </div>
      </div>
    </div>
    <div class="rt-positions">`;

  if (!d.positions || !d.positions.length) {
    html += '<p class="empty-msg" style="padding:10px 14px;font-size:12px">Belum ada posisi aktif</p>';
  } else {
    (d.positions || []).forEach(p => {
      const c = p.pnl_rp >= 0 ? 'var(--green)' : 'var(--red)';
      html += `
        <div class="rt-pos-row">
          <div class="rt-pos-ticker" onclick="analyzeStock('${p.ticker}')" style="cursor:pointer">${p.ticker}</div>
          <div class="rt-pos-price">Rp ${formatNum(p.current_price, 0)}</div>
          <div class="rt-pos-lot">${p.lots} lot</div>
          <div class="rt-pos-pnl" style="color:${c}">
            ${p.pnl_rp >= 0 ? '+' : ''}Rp ${formatNum(p.pnl_rp, 0)}<br>
            <span style="font-size:10px">${p.pnl_pct >= 0 ? '+' : ''}${p.pnl_pct.toFixed(2)}%</span>
          </div>
          <div style="padding-right:8px">
            <button onclick="quickSell('${p.ticker}',${p.current_price},${p.lots})"
              style="padding:3px 10px;background:#F6465D18;border:1px solid #F6465D60;color:#F6465D;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer">
              Jual
            </button>
          </div>
        </div>`;
    });
  }

  html += '</div>';
  container.innerHTML = html;
}

/** Render live fund flow ticker */
function _updateFlowTicker(d) {
  const dirColor = d.flow_direction === 'MASUK' ? 'var(--green)' : 'var(--red)';
  const dirIcon  = d.flow_direction === 'MASUK' ? '↑' : '↓';

  // Update di watchlist row jika ada
  const row = document.querySelector(`#watchlist-tbody tr[data-ticker="${d.ticker}"]`);
  if (row) {
    const priceCell = row.querySelector('.price-cell');
    const chgCell   = row.querySelector('.chg-cell');
    if (priceCell && d.price) {
      priceCell.textContent = `Rp ${formatNum(d.price, 0)}`;
      _flashEl(priceCell, d.change_pct >= 0 ? '#0ECB81' : '#F6465D');
    }
    if (chgCell && d.change_pct !== undefined) {
      chgCell.textContent  = `${d.change_pct >= 0 ? '+' : ''}${d.change_pct.toFixed(2)}%`;
      chgCell.className    = `chg-cell ${d.change_pct >= 0 ? 'change-up' : 'change-down'}`;
    }
  }

  // Update live flow panel
  const flowPanel = document.getElementById('rt-flow-panel');
  if (!flowPanel) return;
  let existing = flowPanel.querySelector(`[data-flow-ticker="${d.ticker}"]`);
  if (!existing) {
    existing = document.createElement('div');
    existing.dataset.flowTicker = d.ticker;
    existing.className = 'rt-flow-row';
    flowPanel.appendChild(existing);
  }
  existing.innerHTML = `
    <span class="rt-flow-ticker">${d.ticker}</span>
    <span class="rt-flow-price">Rp ${formatNum(d.price || 0, 0)}</span>
    <span class="rt-flow-chg" style="color:${d.change_pct >= 0 ? 'var(--green)' : 'var(--red)'}">
      ${d.change_pct >= 0 ? '+' : ''}${(d.change_pct || 0).toFixed(2)}%
    </span>
    <span class="rt-flow-dir" style="color:${dirColor};font-weight:700">${dirIcon} ${d.flow_direction}</span>
    <span class="rt-flow-vol" style="color:var(--text-muted)">${formatVolume(d.volume || 0)}</span>
    <span class="rt-flow-time" style="color:var(--text-muted);font-size:10px">
      ${new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Jakarta' })}
    </span>`;
  _flashEl(existing, d.flow_direction === 'MASUK' ? '#0ECB81' : '#F6465D');
}

/** Update harga posisi di tabel portfolio */
function _updatePositionPrices(prices) {
  // Di portfolio table
  document.querySelectorAll('#portfolio-full-content .port-positions-table tbody tr').forEach(row => {
    const tickerEl = row.querySelector('.ticker-cell');
    if (!tickerEl) return;
    const ticker = tickerEl.textContent.trim();
    const p = prices[ticker];
    if (!p || !p.price) return;
    const cells = row.querySelectorAll('.price-cell');
    if (cells[1]) { // current price column
      const old = cells[1].textContent;
      cells[1].textContent = `Rp ${formatNum(p.price, 0)}`;
      if (old !== cells[1].textContent) _flashEl(cells[1], p.change_pct >= 0 ? '#0ECB81' : '#F6465D');
    }
  });
}

/** Render live trade feed */
function _renderLiveTrades(trades) {
  const el = document.getElementById('rt-trades-feed');
  if (!el) return;
  if (!trades || !trades.length) {
    el.innerHTML = '<p class="empty-msg" style="font-size:11px;padding:8px">Belum ada order</p>';
    return;
  }
  el.innerHTML = trades.map(t => `
    <div class="rt-trade-row ${t.type === 'BUY' ? 'rt-buy' : 'rt-sell'}">
      <span class="rt-trade-type">${t.type === 'BUY' ? '▲' : '▼'} ${t.type}</span>
      <strong>${t.ticker}</strong>
      <span>Rp ${formatNum(t.price, 0)}</span>
      <span>${t.lots} lot</span>
      ${t.pnl_rp != null ? `<span style="color:${t.pnl_rp >= 0 ? 'var(--green)' : 'var(--red)'};font-size:10px">${t.pnl_rp >= 0 ? '+' : ''}Rp ${formatNum(t.pnl_rp, 0)}</span>` : ''}
      <span style="font-size:10px;color:var(--text-muted)">${(t.timestamp || '').substring(11, 19)}</span>
    </div>`).join('');
}

/** Notifikasi instan saat trade terjadi */
function _onTradeEvent(d) {
  const icon  = d.action === 'BUY' ? '▲' : '▼';
  const color = d.action === 'BUY' ? 'success' : 'info';
  showToast(`${icon} ${d.action} ${d.lots} lot ${d.ticker} @ Rp ${formatNum(d.price, 0)}`, color);

  // Refresh panels langsung
  loadPortfolioStats();
  loadRecentOrders();
  if (document.getElementById('page-portfolio')?.classList.contains('active')) {
    loadPortfolioFull();
  }
}

// ─── Init ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  updateClock();
  setInterval(updateClock, 1000);
  checkMarketStatus();
  setInterval(checkMarketStatus, 60000);
  loadPortfolioStats();
  loadWatchlist();
  loadMarketOutlook();
  loadPortfolioFull();
  loadHistory();
  checkServerHealth();
  loadRecentOrders();
  loadIHSG();

  // ── Mulai SSE realtime stream ──
  startSSEStream();

  // Auto-refresh IHSG di topbar setiap 30 detik
  setInterval(loadIHSG, 30000);

  // Auto-refresh harga watchlist (hanya harga, bukan full reload) setiap 30 detik
  setInterval(refreshWatchlistPrices, 30000);

  // Full watchlist reload (termasuk skor fundamental) setiap 5 menit
  setInterval(loadWatchlist, 5 * 60000);

  // Inisialisasi Fast Trade (keyboard shortcuts)
  document.addEventListener('keydown', ftHotkey);
});

// ─── Clock & Market Status ────────────────────────────────────
function updateClock() {
  const now = new Date();
  const opts = { timeZone: 'Asia/Jakarta', hour12: false,
    hour: '2-digit', minute: '2-digit', second: '2-digit' };
  document.getElementById('sidebar-time').textContent =
    now.toLocaleTimeString('id-ID', opts) + ' WIB';
}

function checkMarketStatus() {
  const now = new Date();
  const wib = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Jakarta' }));
  const h = wib.getHours(), m = wib.getMinutes();
  const day = wib.getDay(); // 0=Sun, 6=Sat
  const isWeekday = day >= 1 && day <= 5;
  const totalMin = h * 60 + m;
  const isOpen = isWeekday && totalMin >= 9 * 60 && totalMin <= 16 * 60;

  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  if (isOpen) {
    dot.classList.remove('closed'); text.textContent = 'Pasar Buka';
  } else {
    dot.classList.add('closed'); text.textContent = 'Pasar Tutup';
  }
}

// ─── Navigation ───────────────────────────────────────────────
let autotradeLogPoller = null;

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`page-${name}`)?.classList.add('active');
  document.getElementById(`nav-${name}`)?.classList.add('active');

  // Stop real-time chart & news polling if leaving the analyze page
  if (name !== 'analyze') {
    stopRealtimeChart();
  }

  // Stop auto-trading logs polling if leaving the page
  if (name !== 'autotrade' && autotradeLogPoller) {
    clearInterval(autotradeLogPoller);
    autotradeLogPoller = null;
  }

  if (name === 'portfolio')  loadPortfolioFull();
  if (name === 'history')    loadHistory();
  if (name === 'trade')      { loadRecentOrders(); ftLoadAlertStatus(); }
  if (name === 'settings')   { checkServerHealth(); loadAlertConfigToSettings(); }
  if (name === 'dashboard')  loadPortfolioStats();
  
  if (name === 'autotrade') {
    loadAutoTradeStatus();
    loadAutoTradeLogs();
    // Poll logs and status every 4 seconds
    autotradeLogPoller = setInterval(() => {
      loadAutoTradeStatus();
      loadAutoTradeLogs();
    }, 4000);
  }
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// ─── IHSG ─────────────────────────────────────────────────────
async function loadIHSG() {
  try {
    const res  = await fetch(`${API}/ihsg`);
    const data = await res.json();
    if (data.success && data.data?.length) {
      const last  = data.data[data.data.length - 1];
      const prev  = data.data[data.data.length - 2];
      const price = last.close;
      const chg   = prev ? ((price - prev.close) / prev.close * 100) : 0;
      document.getElementById('ihsg-price').textContent = formatNum(price, 0);
      const changeEl = document.getElementById('ihsg-change');
      changeEl.textContent = `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`;
      changeEl.className   = chg >= 0 ? 'change-up' : 'change-down';

      // Flash badge to signal refresh
      const badge = document.getElementById('ihsg-badge');
      if (badge) {
        badge.style.transition = 'opacity 0.2s';
        badge.style.opacity = '0.5';
        setTimeout(() => { badge.style.opacity = '1'; }, 200);
      }
    }
  } catch(e) {}
}

// ─── Quick Search ─────────────────────────────────────────────
function quickSearch() {
  const q = document.getElementById('search-input').value.trim().toUpperCase();
  if (!q) return;
  analyzeStock(q);
  document.getElementById('search-input').value = '';
}

// ─── Portfolio Stats (Dashboard) ──────────────────────────────
async function loadPortfolioStats() {
  try {
    const res  = await fetch(`${API}/portfolio`);
    const data = await res.json();
    if (!data.success) return;
    const d = data.data;

    const pnlColor = d.total_pnl_rp >= 0 ? 'var(--green)' : 'var(--red)';
    const unrealColor = d.unrealized_pnl >= 0 ? 'var(--green)' : 'var(--red)';

    document.getElementById('stat-total').textContent = `Rp ${formatNum(d.total_portfolio_value, 0)}`;
    document.getElementById('stat-pnl').innerHTML =
      `<span style="color:${pnlColor}">${d.total_pnl_rp >= 0 ? '+' : ''}Rp ${formatNum(d.total_pnl_rp, 0)} (${d.total_pnl_pct >= 0 ? '+' : ''}${d.total_pnl_pct.toFixed(2)}%)</span>`;
    document.getElementById('stat-cash').textContent = `Rp ${formatNum(d.cash, 0)}`;
    document.getElementById('stat-cash-ratio').textContent = `${d.cash_ratio_pct}% dari total`;
    document.getElementById('stat-unrealized').innerHTML =
      `<span style="color:${unrealColor}">${d.unrealized_pnl >= 0 ? '+' : ''}Rp ${formatNum(d.unrealized_pnl, 0)}</span>`;
    document.getElementById('stat-winrate').textContent =
      d.trade_stats.sell_trades > 0 ? `${d.trade_stats.win_rate_pct}%` : 'N/A';
    document.getElementById('stat-trades').textContent =
      `${d.trade_stats.win_trades}W / ${d.trade_stats.loss_trades}L`;

    // Positions on dashboard
    renderDashboardPositions(d.positions);
  } catch(e) {
    console.warn('[portfolio stats]', e);
  }
}

function renderDashboardPositions(positions) {
  const el = document.getElementById('positions-content');
  if (!positions || !positions.length) {
    el.innerHTML = `<p class="empty-msg">Belum ada posisi aktif.</p>`;
    return;
  }
  el.innerHTML = `<div class="positions-grid">${positions.map(p => `
    <div class="position-card" onclick="analyzeStock('${p.ticker}')">
      <div class="pos-header">
        <span class="pos-ticker">${p.ticker}</span>
        <span class="signal-pill ${p.pnl_pct >= 0 ? 'signal-BUY' : 'signal-SELL'}">
          ${p.pnl_pct >= 0 ? '+' : ''}${p.pnl_pct.toFixed(2)}%
        </span>
      </div>
      <div class="pos-metric"><span class="pos-label">Lots</span><span class="pos-value">${p.lots}</span></div>
      <div class="pos-metric"><span class="pos-label">Avg Price</span><span class="pos-value">Rp ${formatNum(p.avg_price, 0)}</span></div>
      <div class="pos-metric"><span class="pos-label">Mkt Value</span><span class="pos-value">Rp ${formatNum(p.market_value, 0)}</span></div>
      <div class="pos-metric">
        <span class="pos-label">P&L</span>
        <span class="pos-value" style="color: ${p.pnl_rp >= 0 ? 'var(--green)' : 'var(--red)'}">
          ${p.pnl_rp >= 0 ? '+' : ''}Rp ${formatNum(p.pnl_rp, 0)}
        </span>
      </div>
    </div>`).join('')}</div>`;
}

// ─── Watchlist ────────────────────────────────────────────────
async function loadWatchlist() {
  const tbody = document.getElementById('watchlist-tbody');
  tbody.innerHTML = `<tr><td colspan="7" class="loading-row"><div class="loading-spinner"><div class="spinner"></div> Memuat watchlist...</div></td></tr>`;
  try {
    const res  = await fetch(`${API}/watchlist`);
    const data = await res.json();
    if (!data.success || !data.data?.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="loading-row">Gagal memuat data</td></tr>`;
      return;
    }
    tbody.innerHTML = data.data.map(s => {
      const chgClass = s.change_pct >= 0 ? 'change-up' : 'change-down';
      const signal   = (s.fundamental_signal || 'HOLD').replace(/ /g, '-');
      return `
      <tr data-ticker="${s.ticker}">
        <td><span class="ticker-cell">${s.ticker}</span><br><span style="font-size:10px;color:var(--text-muted)">${(s.name||'').substring(0,20)}</span></td>
        <td class="price-cell">Rp ${formatNum(s.price, 0)}</td>
        <td class="chg-cell ${chgClass}">${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%</td>
        <td>${formatVolume(s.volume)}</td>
        <td>
          <div style="display:flex;align-items:center;gap:6px;">
            <div style="flex:1;height:4px;background:var(--bg-600);border-radius:2px;overflow:hidden;">
              <div style="width:${s.fundamental_score}%;height:100%;background:${scoreColor(s.fundamental_score)};border-radius:2px;"></div>
            </div>
            <span style="font-size:11px;font-family:'JetBrains Mono',monospace">${Math.round(s.fundamental_score)}</span>
          </div>
        </td>
        <td><span class="signal-pill signal-${signal}">${s.fundamental_signal}</span></td>
        <td><button class="btn-analyze-row" onclick="analyzeStock('${s.ticker}')">Analisis</button></td>
      </tr>`;
    }).join('');
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-row">Error: ${e.message}</td></tr>`;
  }
}

// ─── Watchlist Price Auto-Refresh (lightweight) ───────────────
async function refreshWatchlistPrices() {
  // Ambil baris yang ada di tabel watchlist lalu update hanya kolom harga & change
  const rows = document.querySelectorAll('#watchlist-tbody tr[data-ticker]');
  if (!rows.length) return; // tabel belum dirender, skip

  const tickers = Array.from(rows).map(r => r.dataset.ticker).join(',');
  try {
    const res  = await fetch(`${API}/market/prices?tickers=${tickers}`);
    const data = await res.json();
    if (!data.success) return;

    rows.forEach(row => {
      const ticker = row.dataset.ticker;
      const p = data.prices?.[ticker];
      if (!p || !p.success) return;

      const priceCell = row.querySelector('.price-cell');
      const chgCell   = row.querySelector('.chg-cell');
      if (priceCell) priceCell.textContent = `Rp ${formatNum(p.price, 0)}`;
      if (chgCell) {
        chgCell.textContent = `${p.change_pct >= 0 ? '+' : ''}${p.change_pct.toFixed(2)}%`;
        chgCell.className   = `chg-cell ${p.change_pct >= 0 ? 'change-up' : 'change-down'}`;
      }
    });

    // Flash the watchlist header jika update sukses
    const panel = document.querySelector('#watchlist-tbody')?.closest('.panel');
    if (panel) {
      const hdr = panel.querySelector('.panel-header');
      if (hdr) {
        const now = new Date();
        const t   = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta' });
        const existingTime = hdr.querySelector('.watchlist-refresh-time');
        if (existingTime) {
          existingTime.textContent = `↻ ${t}`;
        } else {
          const span = document.createElement('span');
          span.className = 'watchlist-refresh-time';
          span.style.cssText = 'font-size:10px;color:var(--text-muted);margin-left:8px;font-family:"JetBrains Mono",monospace';
          span.textContent = `↻ ${t}`;
          hdr.querySelector('h3')?.appendChild(span);
        }
      }
    }
  } catch (e) {
    console.warn('[watchlist price refresh]', e);
  }
}

// ─── Market Outlook ───────────────────────────────────────────
async function loadMarketOutlook() {
  const el = document.getElementById('market-outlook-content');
  el.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><span>AI menganalisis pasar...</span></div>`;
  try {
    const res  = await fetch(`${API}/market/outlook`);
    const data = await res.json();
    if (!data.success || !data.data) {
      el.innerHTML = `<p class="empty-msg">Gagal memuat outlook. Pastikan Gemini API key sudah diset.</p>`;
      return;
    }
    const d = data.data;
    const sentClass = d.market_sentiment;
    el.innerHTML = `
      <div class="outlook-sentiment ${sentClass}">
        <div class="sentiment-label">${sentimentEmoji(sentClass)} ${d.market_sentiment}</div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:6px">${d.ihsg_outlook || ''}</div>
      </div>
      <div style="padding:8px 0">
        <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Top Picks AI</div>
        <div class="outlook-picks">${(d.top_picks||[]).map(t => `<span class="pick-badge" onclick="analyzeStock('${t}')">${t}</span>`).join('')}</div>
      </div>
      ${d.weekly_theme ? `<div style="font-size:12px;color:var(--text-secondary);margin-top:10px;padding:10px;background:var(--bg-700);border-radius:8px;"><strong>Tema Minggu Ini:</strong> ${d.weekly_theme}</div>` : ''}
      <div style="font-size:12px;color:var(--text-secondary);margin-top:10px">${d.summary || ''}</div>`;
  } catch(e) {
    el.innerHTML = `<p class="empty-msg">Error memuat outlook: ${e.message}</p>`;
  }
}

// ─── ANALYSIS ─────────────────────────────────────────────────
function startAnalysis() {
  const ticker = document.getElementById('analyze-ticker').value.trim().toUpperCase();
  if (!ticker) { showToast('Masukkan kode saham!', 'error'); return; }
  analyzeStock(ticker);
}

async function analyzeStock(ticker) {
  ticker = ticker.toUpperCase();
  document.getElementById('analyze-ticker').value = ticker;
  showPage('analyze');

  // Reset UI
  document.getElementById('analyze-results').classList.add('hidden');
  document.getElementById('analyze-loading').classList.remove('hidden');
  document.getElementById('analyze-btn').disabled = true;
  currentTicker = ticker;
  if (currentChart) { currentChart = null; }

  // Animate progress steps
  const steps = ['step-data','step-fund','step-tech','step-news','step-flow','step-ai'];
  steps.forEach(s => { const el = document.getElementById(s); el.className = 'step'; el.textContent = el.textContent.replace(/^[✓›•]?\s?/,'• '); });

  const stepDelay = (id, delay, label) => setTimeout(() => {
    steps.forEach(s => document.getElementById(s).className = 'step');
    const el = document.getElementById(id);
    el.className = 'step active';
    el.textContent = label;
    // Mark previous as done
    const idx = steps.indexOf(id);
    for (let i = 0; i < idx; i++) {
      const prev = document.getElementById(steps[i]);
      if (!prev.className.includes('active')) { prev.className = 'step done'; }
    }
  }, delay);

  stepDelay('step-data',  100,  'Mengambil data saham...');
  stepDelay('step-fund',  1200, 'Analisis fundamental...');
  stepDelay('step-tech',  2400, 'Analisis teknikal (RSI, MACD, BB)...');
  stepDelay('step-news',  3600, 'Fetch berita & sentimen...');
  stepDelay('step-flow',  5000, 'Analisis aliran dana...');
  stepDelay('step-ai',    6500, 'Gemini AI memproses semua data...');

  try {
    const res  = await fetch(`${API}/analyze/${ticker}?ai=true`);
    const data = await res.json();

    // Mark all done
    steps.forEach(s => { const el = document.getElementById(s); el.className = 'step done'; });

    if (!data.success) {
      document.getElementById('analyze-loading').classList.add('hidden');
      showToast(`Error: ${data.error}`, 'error');
      document.getElementById('analyze-btn').disabled = false;
      return;
    }

    currentAnalysis = data;
    renderAnalysis(data);

    document.getElementById('analyze-loading').classList.add('hidden');
    document.getElementById('analyze-results').classList.remove('hidden');
    document.getElementById('analyze-btn').disabled = false;

    // Load chart and start realtime updates
    await loadChart(ticker, '6mo');
    startRealtimeChart(ticker);

  } catch(e) {
    document.getElementById('analyze-loading').classList.add('hidden');
    document.getElementById('analyze-btn').disabled = false;
    showToast(`Gagal analisis: ${e.message}`, 'error');
  }
}

function renderAnalysis(data) {
  const info   = data.stock_info?.data || {};
  const fund   = data.fundamental || {};
  const tech   = data.technical || {};
  const news   = data.news || {};
  const flow   = data.flow || {};
  const ai     = data.ai_analysis?.data || null;
  const scores = data.scores || {};
  const as     = ai?.analysis_summary || {};

  currentAI        = ai;
  currentScoreMode = (ai ? 'ai' : 'raw');

  // ── Stock Header ──
  const chgColor = (info.change_pct||0) >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('stock-header').innerHTML = `
    <div class="stock-header-left">
      <div class="stock-ticker-big">${data.ticker}</div>
      <div class="stock-name-big">${info.company_name || data.ticker}</div>
      <div class="stock-sector-badge">${info.sector || 'N/A'} · ${info.industry || ''}</div>
      <div class="stock-header-meta">
        <div class="meta-item"><span class="meta-label">Market Cap</span><span class="meta-value">${formatCap(info.market_cap)}</span></div>
        <div class="meta-item"><span class="meta-label">Volume</span><span class="meta-value">${formatVolume(info.volume)}</span></div>
        <div class="meta-item"><span class="meta-label">52W High</span><span class="meta-value" style="color:var(--green)">Rp ${formatNum(info.week52_high,0)}</span></div>
        <div class="meta-item"><span class="meta-label">52W Low</span><span class="meta-value" style="color:var(--red)">Rp ${formatNum(info.week52_low,0)}</span></div>
        <div class="meta-item"><span class="meta-label">Beta</span><span class="meta-value">${(info.beta||1).toFixed(2)}</span></div>
      </div>
    </div>
    <div class="stock-header-price">
      <div class="price-big" style="color:var(--text-primary)">Rp ${formatNum(info.current_price,0)}</div>
      <div class="price-change-big" style="color:${chgColor}">
        ${(info.change_pct||0) >= 0 ? '+' : ''}${(info.change_pct||0).toFixed(2)}% 
        (${(info.change||0) >= 0 ? '+' : ''}Rp ${formatNum(info.change||0, 0)})
      </div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:6px">Prev Close: Rp ${formatNum(info.prev_close,0)}</div>
      <div style="font-size:11px;color:var(--text-muted)">Bid: Rp ${formatNum(info.bid,0)} · Ask: Rp ${formatNum(info.ask,0)}</div>
    </div>`;

  // ── Scores Overview ──
  renderScoreCards(data);
  refreshPanelBadges(data);

  // ── AI Recommendation Banner ──
  if (ai) {
    const rec   = ai.recommendation || 'HOLD';
    const conf  = ai.confidence || 50;
    const riskL = ai.risk_level || 'MEDIUM';
    const [bgColor, bdColor] = recColors(rec);
    document.getElementById('ai-recommendation').style.background = bgColor;
    document.getElementById('ai-recommendation').style.borderColor = bdColor;
    document.getElementById('ai-recommendation').innerHTML = `
      <div class="ai-rec-header">
        <div>
          <div class="ai-rec-label">Rekomendasi Gemini AI</div>
          <div class="ai-rec-signal" style="color:${bdColor}">${rec}</div>
        </div>
        <div style="text-align:right">
          <div class="ai-rec-confidence" style="color:${bdColor}">Confidence: <strong>${conf}%</strong></div>
          <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">Risk: ${riskL}</div>
        </div>
      </div>
      <div class="ai-rec-meta">
        <div class="ai-rec-meta-item">
          <span class="ai-rec-meta-label">Time Horizon</span>
          <span class="ai-rec-meta-value">${ai.time_horizon || 'N/A'}</span>
        </div>
        <div class="ai-rec-meta-item">
          <span class="ai-rec-meta-label">Entry Zone</span>
          <span class="ai-rec-meta-value">Rp ${formatNum(ai.entry_strategy?.entry_zone_low,0)} — Rp ${formatNum(ai.entry_strategy?.entry_zone_high,0)}</span>
        </div>
        <div class="ai-rec-meta-item">
          <span class="ai-rec-meta-label">Stop Loss</span>
          <span class="ai-rec-meta-value" style="color:var(--red)">Rp ${formatNum(ai.entry_strategy?.stop_loss,0)}</span>
        </div>
        <div class="ai-rec-meta-item">
          <span class="ai-rec-meta-label">Target 1</span>
          <span class="ai-rec-meta-value" style="color:var(--green)">Rp ${formatNum(ai.entry_strategy?.take_profit_1,0)}</span>
        </div>
        <div class="ai-rec-meta-item">
          <span class="ai-rec-meta-label">Risk/Reward</span>
          <span class="ai-rec-meta-value" style="color:var(--yellow)">1 : ${(ai.entry_strategy?.risk_reward_ratio||0).toFixed(1)}</span>
        </div>
      </div>`;
  } else {
    document.getElementById('ai-recommendation').innerHTML =
      `<p class="empty-msg">Set GEMINI_API_KEY untuk mendapatkan rekomendasi AI</p>`;
    document.getElementById('ai-recommendation').style.cssText = 'border:1px solid var(--panel-border);background:var(--panel-bg)';
  }

  // ── Fundamental Panel ──
  const fm = fund.metrics || {};
  const fk = fund.key_metrics || {};
  document.getElementById('fund-score-badge').textContent = `${Math.round(fund.composite_score||50)}/100`;
  document.getElementById('fund-score-badge').style.color = scoreColor(fund.composite_score||50);
  document.getElementById('fundamental-content').innerHTML = `
    ${as.fundamental_verdict ? `<div class="ai-verdict"><strong>AI</strong> · ${as.fundamental_verdict}</div>` : ''}
    <div class="metric-grid">
      ${metricRow('PER', `${(info.pe_ratio||0).toFixed(1)}x`, fm.pe)}
      ${metricRow('PBV', `${(info.pb_ratio||0).toFixed(1)}x`, fm.pbv)}
      ${metricRow('ROE', `${((info.roe||0)*100).toFixed(1)}%`, fm.roe)}
      ${metricRow('ROA', `${(fk.roa_pct||0).toFixed(1)}%`)}
      ${metricRow('Net Margin', `${(fk.profit_margin_pct||0).toFixed(1)}%`)}
      ${metricRow('Rev. Growth', `${(fm.growth?.revenue_growth_pct||0).toFixed(1)}%`, fm.growth)}
      ${metricRow('EPS', `Rp ${formatNum(fk.eps,1)}`)}
      ${metricRow('Div. Yield', `${(fm.dividend?.yield_pct||0).toFixed(1)}%`, fm.dividend)}
      ${metricRow('DER', `${(info.debt_to_equity||0).toFixed(1)}x`, fm.leverage)}
      ${metricRow('Curr. Ratio', `${(info.current_ratio||0).toFixed(2)}x`, fm.liquidity)}
    </div>
    ${fund.analyst?.analyst_count > 0 ? `
    <div style="padding:10px 18px;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--panel-border)">
      Target Analis (${fund.analyst.analyst_count} analis): 
      <strong style="color:var(--brand-1)">Rp ${formatNum(fund.analyst.target_mean,0)}</strong> 
      (<span style="color:var(--green)">H: ${formatNum(fund.analyst.target_high,0)}</span> / 
      <span style="color:var(--red)">L: ${formatNum(fund.analyst.target_low,0)}</span>) — 
      ${fund.analyst.recommendation?.toUpperCase()}
    </div>` : ''}`;

  // ── Technical Panel ──
  const inds = tech.indicators || {};
  document.getElementById('tech-score-badge').textContent = `${Math.round(tech.composite_score||50)}/100`;
  document.getElementById('tech-score-badge').style.color = scoreColor(tech.composite_score||50);
  document.getElementById('technical-content').innerHTML = `
    ${as.technical_verdict ? `<div class="ai-verdict"><strong>AI</strong> · ${as.technical_verdict}</div>` : ''}
    <div>
      ${indicatorBar('RSI', inds.rsi?.score||50, `${(inds.rsi?.value||50).toFixed(1) || ''}`, inds.rsi?.signal || '')}
      ${indicatorBar('MACD', inds.macd?.score||50, '', inds.macd?.signal || '')}
      ${indicatorBar('Bollinger', inds.bollinger?.score||50, '', inds.bollinger?.signal || '')}
      ${indicatorBar('MA Trend', inds.ma?.score||50, '', inds.ma?.signal || '')}
      ${indicatorBar('Volume', inds.volume?.score||50, `${inds.volume?.ratio||0}x`, inds.volume?.signal || '')}
      ${indicatorBar('Stochastic', inds.stochastic?.score||50, `K:${inds.stochastic?.k||0}`, inds.stochastic?.signal || '')}
    </div>
    ${tech.candlestick_patterns?.length ? `
    <div style="padding:10px 18px;font-size:12px;border-top:1px solid var(--panel-border)">
      🕯️ <strong>Pola Candlestick:</strong><br>
      ${tech.candlestick_patterns.map(p => `<span style="color:var(--text-secondary)">• ${p}</span>`).join('<br>')}
    </div>` : ''}
    ${tech.suggested_trade ? `
    <div style="padding:10px 18px;border-top:1px solid var(--panel-border)">
      <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">ATR-Based Trade Setup</div>
      <div style="display:flex;gap:12px;font-size:11px;font-family:'JetBrains Mono',monospace">
        <span style="color:var(--brand-1)">E: Rp ${formatNum(tech.suggested_trade.entry,0)}</span>
        <span style="color:var(--red)">SL: Rp ${formatNum(tech.suggested_trade.stop_loss,0)}</span>
        <span style="color:var(--green)">TP: Rp ${formatNum(tech.suggested_trade.take_profit,0)}</span>
        <span style="color:var(--yellow)">RR: 1:${tech.suggested_trade.risk_reward}</span>
      </div>
    </div>` : ''}`;

  // ── News Panel ──
  const ns = news.sentiment_summary || {};
  document.getElementById('news-score-badge').textContent = `${Math.round(ns.score||50)}/100`;
  document.getElementById('news-score-badge').style.color = scoreColor(ns.score||50);
  document.getElementById('news-content').innerHTML = `
    ${as.news_verdict ? `<div class="ai-verdict"><strong>AI</strong> · ${as.news_verdict}</div>` : ''}
    ${renderNewsHTML(news)}`;

  // ── Flow Panel ──
  const fi = flow.indicators || {};
  const fw = flow.whale || {};
  document.getElementById('flow-score-badge').textContent = `${Math.round(flow.composite_score||50)}/100`;
  document.getElementById('flow-score-badge').style.color = scoreColor(flow.composite_score||50);

  // Whale Volume Signals in flow panel
  let whaleVolumeHtml = '';
  if (fw.detected && (fw.signals||[]).length > 0) {
    const alertColor = fw.alert_level === 'HIGH' ? 'var(--red)' : fw.alert_level === 'MEDIUM' ? 'var(--yellow)' : 'var(--brand-1)';
    whaleVolumeHtml = `
      <div style="padding:12px 18px;border-top:1px solid var(--panel-border);background:#1a0a0a">
        <div style="font-size:11px;font-weight:700;color:${alertColor};text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">
          Sinyal Volume Whale — ${fw.alert_level}
        </div>
        ${(fw.signals||[]).map(s => `
          <div style="display:flex;gap:8px;margin-bottom:8px;font-size:12px;padding:8px;background:var(--bg-700);border-radius:6px;border-left:3px solid ${s.severity==='CRITICAL'?'var(--red)':s.severity==='HIGH'?'var(--yellow)':'var(--brand-1)'}">
            <span style="font-size:16px">${s.icon}</span>
            <div>
              <div style="font-weight:700;color:var(--text-primary)">${s.label}</div>
              <div style="color:var(--text-secondary);margin-top:2px">${s.message}</div>
            </div>
          </div>`).join('')}
      </div>`;
  }

  document.getElementById('flow-content').innerHTML = `
    ${as.flow_verdict ? `<div class="ai-verdict"><strong>AI</strong> · ${as.flow_verdict}</div>` : ''}
    <div style="padding:14px 18px;border-bottom:1px solid var(--panel-border)">
      <div style="font-size:18px;font-weight:800;color:${scoreColor(flow.composite_score||50)}">${flow.signal||'N/A'}</div>
      <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">${flow.description||''}</div>
    </div>
    <div>
      ${indicatorBar('MFI', fi.mfi?.value||50, `${fi.mfi?.value||0}`, fi.mfi?.signal||'')}
      ${indicatorBar('OBV Trend', (flow.weekly_score||50), '', fi.obv?.signal||'')}
      ${indicatorBar('Volume Ratio', fi.volume_ratio?.value > 1 ? 70 : 40, `${fi.volume_ratio?.value||0}x`, fi.volume_ratio?.signal||'')}
    </div>
    <div style="padding:10px 18px;font-size:11px;color:var(--text-muted);border-top:1px solid var(--panel-border)">
      5D Score: ${flow.recent_5d_score||0}/100 · 20D: ${flow.weekly_score||0}/100 · 60D: ${flow.quarterly_score||0}/100
    </div>
    ${whaleVolumeHtml}
    ${flow.institutional?.institutional_holders?.length ? `
    <div style="padding:10px 18px;border-top:1px solid var(--panel-border)">
      <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Pemegang Institusional</div>
      ${flow.institutional.institutional_holders.slice(0,3).map(h => `
        <div style="display:flex;justify-content:space-between;font-size:11px;padding:3px 0">
          <span style="color:var(--text-secondary)">${h.holder}</span>
          <span style="font-family:'JetBrains Mono',monospace;color:var(--brand-1)">${(h.pct_out*100||0).toFixed(1)}%</span>
        </div>`).join('')}
    </div>` : ''}`;

  // ── AI Detail Panel ──
  if (ai) {
    const as   = ai.analysis_summary || {};
    const es   = ai.entry_strategy || {};
    const pt   = ai.price_targets || {};
    const mon  = ai.monitoring || {};
    const aiSc = ai.scores || {};
    document.getElementById('ai-analysis-content').innerHTML = `
      <div class="ai-content-grid">
        <!-- Price Targets -->
        <div class="ai-section">
          <h4>Target Harga (3 Bulan)</h4>
          <div class="target-grid">
            <div class="target-card bull">
              <div class="target-label">BULL</div>
              <div class="target-price" style="color:var(--green)">Rp ${formatNum(pt.bull_case,0)}</div>
              <div class="target-pct" style="color:var(--green)">+${(pt.upside_from_current||0).toFixed(1)}%</div>
            </div>
            <div class="target-card base">
              <div class="target-label">BASE</div>
              <div class="target-price" style="color:var(--yellow)">Rp ${formatNum(pt.base_case,0)}</div>
              <div class="target-pct" style="color:var(--yellow)">Skenario Normal</div>
            </div>
            <div class="target-card bear">
              <div class="target-label">BEAR</div>
              <div class="target-price" style="color:var(--red)">Rp ${formatNum(pt.bear_case,0)}</div>
              <div class="target-pct" style="color:var(--red)">${(pt.downside_from_current||0).toFixed(1)}%</div>
            </div>
          </div>
        </div>

        <!-- Entry Strategy -->
        <div class="ai-section">
          <h4>Strategi Entry</h4>
          <div class="entry-table">
            <div class="entry-row"><span class="entry-label">Entry Ideal</span><span class="entry-value entry">Rp ${formatNum(es.recommended_entry,0)}</span></div>
            <div class="entry-row"><span class="entry-label">Zona Beli</span><span class="entry-value entry">Rp ${formatNum(es.entry_zone_low,0)} — ${formatNum(es.entry_zone_high,0)}</span></div>
            <div class="entry-row"><span class="entry-label">Stop Loss</span><span class="entry-value sl">Rp ${formatNum(es.stop_loss,0)} (${(es.max_loss_pct||0).toFixed(1)}%)</span></div>
            <div class="entry-row"><span class="entry-label">Take Profit 1</span><span class="entry-value tp1">Rp ${formatNum(es.take_profit_1,0)}</span></div>
            <div class="entry-row"><span class="entry-label">Take Profit 2</span><span class="entry-value tp2">Rp ${formatNum(es.take_profit_2,0)}</span></div>
            <div class="entry-row"><span class="entry-label">Take Profit 3</span><span class="entry-value tp3">Rp ${formatNum(es.take_profit_3,0)}</span></div>
            <div class="entry-row"><span class="entry-label">Risk/Reward</span><span class="entry-value rr">1 : ${(es.risk_reward_ratio||0).toFixed(1)}</span></div>
            <div class="entry-row"><span class="entry-label">Saran Lot</span><span class="entry-value entry">${es.lot_suggestion||'—'}</span></div>
          </div>
        </div>

        <!-- Katalis & Risiko -->
        <div class="ai-section">
          <h4>Katalis Utama</h4>
          <ul class="catalyst-list">${(as.key_catalysts||[]).map(c => `<li>${c}</li>`).join('')}</ul>
          <h4 style="margin-top:12px">Risiko Utama</h4>
          <ul class="risk-list">${(as.key_risks||[]).map(r => `<li>${r}</li>`).join('')}</ul>
        </div>

        <!-- Monitoring -->
        <div class="ai-section">
          <h4>👀 Monitoring</h4>
          <div style="font-size:12px;color:var(--text-secondary);">
            <div style="margin-bottom:8px"><strong style="color:var(--text-primary)">Level Penting:</strong><br>${(mon.key_levels_to_watch||[]).join(', ')}</div>
            <div style="margin-bottom:8px"><strong style="color:var(--text-primary)">Katalis Berikutnya:</strong><br>${mon.next_catalyst_date||'—'}</div>
            <div style="margin-bottom:8px"><strong style="color:var(--text-primary)">Kondisi Exit:</strong><br>${mon.exit_conditions||'—'}</div>
            <div><strong style="color:var(--text-primary)">Review:</strong><br>${mon.review_schedule||'—'}</div>
          </div>
        </div>
      </div>

      <!-- Order Instructions -->
      <div class="order-instructions-box">
        <div class="order-inst-header">📢 Instruksi Order Broker</div>
        <div style="font-size:12px;color:var(--text-secondary);line-height:1.7">${ai.order_instructions?.broker_instruction||'—'}</div>
        <div style="font-size:12px;color:var(--brand-1);margin-top:8px">⏰ Waktu Terbaik: ${ai.order_instructions?.timing||'—'}</div>
      </div>

      <!-- Narrative -->
      <div class="ai-narrative">
        <h4 style="font-size:13px;color:var(--text-primary);margin-bottom:12px">Analisis Lengkap AI</h4>
        ${(as.overall_narrative||'Analisis tidak tersedia').split('\n').filter(p=>p.trim()).map(p => `<p>${p}</p>`).join('')}
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:16px;font-size:12px">
          <div><strong style="color:var(--text-secondary)">Fundamental:</strong> ${as.fundamental_verdict||''}</div>
          <div><strong style="color:var(--text-secondary)">Teknikal:</strong> ${as.technical_verdict||''}</div>
          <div><strong style="color:var(--text-secondary)">Sentimen:</strong> ${as.news_verdict||''}</div>
          <div><strong style="color:var(--text-secondary)">Aliran Dana:</strong> ${as.flow_verdict||''}</div>
        </div>
      </div>`;
  } else {
    document.getElementById('ai-detail-panel').innerHTML = `
      <div class="panel-header"><h3>Analisis Lengkap Gemini AI</h3></div>
      <div style="padding:32px;text-align:center;color:var(--text-muted)">
        <div style="font-size:34px;margin-bottom:12px;color:var(--text-secondary)">AI</div>
        <div>Set GEMINI_API_KEY di file <code>.env</code> untuk mendapatkan analisis AI penuh</div>
      </div>`;
  }

  // ── Rencana Trading AI (harga entry/SL/TP dari AI) ──
  renderAITradePlan(data);
}

// ─── AI-Adjusted Scores ────────────────────────────────────────
function renderScoreCards(data) {
  const fund   = data.fundamental || {};
  const tech   = data.technical || {};
  const news   = data.news || {};
  const flow   = data.flow || {};
  const aiAvail = !!(data.ai_analysis?.success && data.ai_analysis?.data);
  const adj    = data.adjusted || {};
  const raw    = data.scores || {};
  const useAI  = currentScoreMode === 'ai' && aiAvail;
  const s      = useAI ? (adj.scores || {}) : raw;
  const overallScore = useAI ? (adj.overall_score ?? data.overall_score) : data.overall_score;

  const toggleEl = document.getElementById('score-mode-toggle');
  if (toggleEl) {
    toggleEl.innerHTML = `
      <button class="${currentScoreMode==='ai'?'active':''}" ${aiAvail?'':'disabled'} onclick="setScoreMode('ai')">AI</button>
      <button class="${currentScoreMode==='raw'?'active':''}" onclick="setScoreMode('raw')">RAW</button>`;
  }

  const delta = (key) => {
    if (!useAI) return '';
    const r = raw[key], a = adj.scores?.[key];
    if (r == null || a == null || r === a) return '';
    const diff = a - r;
    return `<div class="score-delta ${diff>=0?'up':'down'}">${diff>=0?'▲':'▼'} ${Math.abs(diff).toFixed(0)} vs RAW</div>`;
  };

  const cards = [
    { key:'fundamental', label: 'FUNDAMENTAL', score: s.fundamental, signal: fund.signal },
    { key:'technical',   label: 'TEKNIKAL',    score: s.technical,   signal: tech.signal },
    { key:'sentiment',   label: 'SENTIMEN',    score: s.sentiment,   signal: news.sentiment_summary?.signal },
    { key:'flow',        label: 'FLOW DANA',   score: s.flow,        signal: flow.signal },
    { key:'overall',     label: 'OVERALL',     score: overallScore,  signal: overallSignal(overallScore||50), big: true },
  ];

  document.getElementById('scores-overview').innerHTML = cards.map(c => `
    <div class="score-card${c.big ? ' glow-green' : ''}">
      <div class="score-label">${c.label}</div>
      <div class="score-circle" style="border-color:${scoreColor(c.score||50)};background:${scoreColor(c.score||50)}18">
        <span style="color:${scoreColor(c.score||50)}">${Math.round(c.score||50)}</span>
      </div>
      ${delta(c.key)}
      <div class="score-signal" style="color:${scoreColor(c.score||50)}">${c.signal || 'N/A'}</div>
    </div>`).join('');
}

function refreshPanelBadges(data) {
  const aiAvail = !!(data.ai_analysis?.success && data.ai_analysis?.data);
  const useAI   = currentScoreMode === 'ai' && aiAvail;
  const adj     = data.adjusted || {};
  const raw     = data.scores || {};
  const s       = useAI ? (adj.scores || {}) : raw;

  const badges = [
    ['fund-score-badge', s.fundamental],
    ['tech-score-badge', s.technical],
    ['news-score-badge', s.sentiment],
    ['flow-score-badge', s.flow],
  ];
  badges.forEach(([id, score]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = `${Math.round(score||50)}/100`;
    el.style.color = scoreColor(score||50);
  });
}

function setScoreMode(mode) {
  if (!currentAnalysis) return;
  const aiAvail = !!(currentAnalysis.ai_analysis?.success && currentAnalysis.ai_analysis?.data);
  if (mode === 'raw' || (mode === 'ai' && aiAvail)) {
    currentScoreMode = mode;
  }
  renderScoreCards(currentAnalysis);
  refreshPanelBadges(currentAnalysis);
}

// ─── Rencana Trading AI ────────────────────────────────────────
function renderAITradePlan(data) {
  const panel  = document.getElementById('ai-trade-plan');
  const content = document.getElementById('ai-trade-plan-content');
  if (!panel || !content) return;
  const ai  = data.ai_analysis?.data;
  const es  = ai?.entry_strategy;
  if (!ai || !es || !es.recommended_entry) { panel.style.display = 'none'; return; }

  const entry  = es.recommended_entry || 0;
  const slPct  = es.stop_loss  ? Math.abs((entry - es.stop_loss) / entry * 100).toFixed(1) : '';
  panel.style.display = '';
  content.innerHTML = `
    <div class="ai-plan-grid">
      <div class="ai-plan-cell">
        <div class="ai-plan-label">Entry Ideal</div>
        <div class="ai-plan-price entry">Rp ${formatNum(es.recommended_entry,0)}</div>
        <div class="ai-plan-sub">Zona: Rp ${formatNum(es.entry_zone_low,0)} — ${formatNum(es.entry_zone_high,0)}</div>
      </div>
      <div class="ai-plan-cell">
        <div class="ai-plan-label">Stop Loss</div>
        <div class="ai-plan-price sl">Rp ${formatNum(es.stop_loss,0)}</div>
        <div class="ai-plan-sub">${slPct ? '(−' + slPct + '%)' : 'Maks kerugian'}</div>
      </div>
      <div class="ai-plan-cell">
        <div class="ai-plan-label">Take Profit 1</div>
        <div class="ai-plan-price tp">Rp ${formatNum(es.take_profit_1,0)}</div>
        <div class="ai-plan-sub">TP2: Rp ${formatNum(es.take_profit_2,0)} · TP3: Rp ${formatNum(es.take_profit_3,0)}</div>
      </div>
      <div class="ai-plan-cell">
        <div class="ai-plan-label">Saran Lot</div>
        <div class="ai-plan-price lot">${es.lot_suggestion || '—'}</div>
        <div class="ai-plan-sub">R/R 1 : ${(es.risk_reward_ratio||0).toFixed(1)} · ${ai.time_horizon || ''}</div>
      </div>
    </div>
    <div class="ai-plan-actions">
      <button class="ai-plan-btn buy" onclick="applyAITradePlan('BUY')">BUY di Entry AI</button>
      <button class="ai-plan-btn sell" onclick="applyAITradePlan('SELL')">SELL di Target AI</button>
    </div>`;
}

async function applyAITradePlan(action) {
  const ai = currentAI;
  if (!ai) { showToast('Analisis AI belum tersedia — jalankan analisis dulu', 'error'); return; }
  const es = ai.entry_strategy || {};
  const info = currentAnalysis?.stock_info?.data || {};
  const ticker = currentTicker || info.company_name || '';
  const current = info.current_price || 0;

  const priceInput = document.getElementById('ft-price-input');
  if (!priceInput) { showPage('trade'); setTimeout(() => applyAITradePlan(action), 250); return; }

  document.getElementById('ft-ticker').value = ticker;
  const slEl  = document.getElementById('ft-sl');
  const tpEl  = document.getElementById('ft-tp');
  const lotEl = document.getElementById('ft-lots');

  if (action === 'BUY') {
    const entry = es.recommended_entry || es.entry_zone_low || current;
    priceInput.value = entry;
    ftCurrentPrice   = entry;
    if (slEl)  slEl.value = es.stop_loss || Math.round(entry * 0.95);
    if (tpEl)  tpEl.value = es.take_profit_1 || Math.round(entry * 1.10);
    const m = (es.lot_suggestion || '').match(/(\d+)/);
    if (lotEl && m) lotEl.value = parseInt(m[1], 10) || 1;
    showToast(`Form BUY diisi AI: entry Rp ${formatNum(entry,0)} · SL Rp ${formatNum(es.stop_loss||0,0)} · TP Rp ${formatNum(es.take_profit_1||0,0)}`, 'success');
  } else {
    const sellPrice = es.take_profit_1 || current;
    priceInput.value = sellPrice;
    ftCurrentPrice   = sellPrice;
    if (slEl) slEl.value = '';
    if (tpEl) tpEl.value = '';
    try {
      const res  = await fetch(`${API}/portfolio`);
      const data = await res.json();
      const pos  = (data.data?.positions || []).find(p => p.ticker === ticker);
      if (lotEl && pos) lotEl.value = pos.lots;
    } catch(_) {}
    showToast(`Form SELL diisi AI: exit Rp ${formatNum(sellPrice,0)} (target AI)`, 'success');
  }

  document.querySelectorAll('.ft-lev-btn').forEach(b => b.classList.toggle('active', b.dataset.lev === '1'));
  ftLeverage = 1;
  ftUpdateCalc();
  showPage('trade');
}

// ─── Chart ────────────────────────────────────────────────────
// Peta period → interval yang benar untuk BEI / yfinance
// yfinance limitasi: 1m hanya 7 hari terakhir, 1h hanya 730 hari
const PERIOD_CONFIG = {
  '1d':  { interval: '1m',  label: '1 Hari',   intraday: true  },
  '5d':  { interval: '15m', label: '5 Hari',   intraday: true  },
  '1mo': { interval: '1h',  label: '1 Bulan',  intraday: true  },
  '3mo': { interval: '1d',  label: '3 Bulan',  intraday: false },
  '6mo': { interval: '1d',  label: '6 Bulan',  intraday: false },
  '1y':  { interval: '1d',  label: '1 Tahun',  intraday: false },
};

let currentChartPeriod = '6mo'; // track active period

async function loadChart(ticker, period) {
  currentChartPeriod = period;
  const cfg = PERIOD_CONFIG[period] || { interval: '1d', intraday: false };
  const container = document.getElementById('price-chart');

  // Show loading spinner in chart area
  container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:380px;color:var(--text-muted);gap:10px">
    <div class="spinner"></div><span>Memuat chart ${cfg.label}...</span>
  </div>`;

  // Destroy old chart instance
  if (currentChart) {
    try { currentChart.remove(); } catch(_) {}
    currentChart = null;
  }

  try {
    const res  = await fetch(`${API}/stock/${ticker}/history?period=${period}&interval=${cfg.interval}`);
    const data = await res.json();

    if (!data.success || !data.data?.length) {
      container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:380px;color:var(--text-muted)">
        Tidak ada data chart untuk periode ini</div>`;
      return;
    }

    container.innerHTML = '';

    const chart = LightweightCharts.createChart(container, {
      width:  container.clientWidth,
      height: 380,
      layout: {
        background: { type: LightweightCharts.ColorType.Solid, color: '#080b12' },
        textColor:  '#8899bb',
      },
      grid: {
        vertLines: { color: '#1e2d4740' },
        horzLines: { color: '#1e2d4740' },
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1e2d47' },
      timeScale: {
        borderColor:    '#1e2d47',
        timeVisible:    cfg.intraday,
        secondsVisible: false,
        // Tampilkan waktu dalam WIB (UTC+7)
        timezone: 'Asia/Jakarta',
      },
      localization: {
        // Format harga dalam Rupiah tanpa desimal
        priceFormatter: p => 'Rp ' + Math.round(p).toLocaleString('id-ID'),
        // Format waktu di tooltip sesuai WIB
        timeFormatter: ts => {
          if (!cfg.intraday) return ts; // string date, return as-is
          const d = new Date(ts * 1000);
          return d.toLocaleString('id-ID', {
            timeZone: 'Asia/Jakarta',
            day: '2-digit', month: '2-digit',
            hour: '2-digit', minute: '2-digit',
          });
        },
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor:        '#0ECB81', downColor:       '#F6465D',
      borderUpColor:  '#0ECB81', borderDownColor: '#F6465D',
      wickUpColor:    '#0ECB81', wickDownColor:   '#F6465D',
    });

    const volSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    // MA hanya relevan untuk daily candles (bukan intraday pendek)
    let ma20Series = null, ma50Series = null;
    if (!cfg.intraday || period === '1mo') {
      ma20Series = chart.addLineSeries({ color: '#ffffff88', lineWidth: 1, title: 'MA20', priceScaleId: 'right' });
      ma50Series = chart.addLineSeries({ color: '#9a9aa488', lineWidth: 1, title: 'MA50', priceScaleId: 'right' });
    }

    const candles = [], vols = [];

    data.data.forEach(d => {
      // Timestamp dari server: "YYYY-MM-DD" atau "YYYY-MM-DD HH:MM:SS"
      // LightweightCharts butuh Unix timestamp (detik) untuk UTCTimestamp mode
      // Atau string "YYYY-MM-DD" untuk BusinessDay mode
      let t;
      if (cfg.intraday) {
        // Intraday: server kirim string timestamp local WIB, konversi ke UTC unix
        // yfinance data sudah tz-naive setelah tz_localize(None) di server
        // Kita parse sebagai WIB (UTC+7) lalu konversi ke UTC untuk LightweightCharts
        const raw = d.timestamp; // "2026-08-03 09:01:00"
        const wibDate = new Date(raw.replace(' ', 'T') + '+07:00');
        t = Math.floor(wibDate.getTime() / 1000);
      } else {
        // Daily: gunakan string date langsung — lebih stabil untuk business day
        t = d.timestamp; // "2026-08-03"
      }

      if (!t) return;
      const o = d.open, h = d.high, l = d.low, c = d.close;
      if (!o && !c) return; // skip baris kosong

      candles.push({ time: t, open: o, high: h, low: l, close: c });
      vols.push({
        time:  t,
        value: d.volume,
        color: c >= o ? '#0ECB8140' : '#F6465D40',
      });
    });

    // Sort kronologis
    candles.sort((a, b) => {
      const ta = typeof a.time === 'string' ? a.time : a.time;
      const tb = typeof b.time === 'string' ? b.time : b.time;
      return ta > tb ? 1 : ta < tb ? -1 : 0;
    });
    vols.sort((a, b) => {
      return a.time > b.time ? 1 : a.time < b.time ? -1 : 0;
    });

    // Deduplicate timestamps (yfinance kadang kirim duplikat)
    const dedupedCandles = [], seen = new Set();
    candles.forEach(c => {
      const key = String(c.time);
      if (!seen.has(key)) { seen.add(key); dedupedCandles.push(c); }
    });
    const dedupedVols = [], seenV = new Set();
    vols.forEach(v => {
      const key = String(v.time);
      if (!seenV.has(key)) { seenV.add(key); dedupedVols.push(v); }
    });

    candleSeries.setData(dedupedCandles);
    volSeries.setData(dedupedVols);

    // Hitung MA
    if (ma20Series || ma50Series) {
      const calcSMA = (data, n) => {
        const res = [];
        for (let i = n - 1; i < data.length; i++) {
          let sum = 0;
          for (let j = 0; j < n; j++) sum += data[i - j].close;
          res.push({ time: data[i].time, value: sum / n });
        }
        return res;
      };
      if (ma20Series) { const m = calcSMA(dedupedCandles, 20); if (m.length) ma20Series.setData(m); }
      if (ma50Series) { const m = calcSMA(dedupedCandles, 50); if (m.length) ma50Series.setData(m); }
    }

    chart.timeScale().fitContent();
    currentChart = chart;

    // Resize observer
    new ResizeObserver(() => {
      if (currentChart) currentChart.applyOptions({ width: container.clientWidth });
    }).observe(container);

    // Update chart title dengan info timeframe
    const chartTitle = document.querySelector('.chart-panel .panel-header h3');
    if (chartTitle) {
      chartTitle.textContent = `Chart ${ticker} — ${cfg.label} (${cfg.interval.toUpperCase()})`;
    }

  } catch(e) {
    container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:380px;color:var(--red)">
      Gagal memuat chart: ${e.message}</div>`;
    console.error('[chart]', e);
  }
}

function renderNewsHTML(news) {
  const ns = news.sentiment_summary || {};
  const ws = news.whale_summary || {};
  const articles = news.articles || [];
  const now = new Date();

  // ── Helper: hitung selisih waktu artikel ──
  function articleAge(published) {
    if (!published) return { label: '', urgent: false, hours: 999 };
    try {
      // Format dari server: "2026-08-03 08:10" — anggap WIB
      const dt = new Date(published.replace(' ', 'T') + '+07:00');
      const diffMs = now - dt;
      const diffH  = diffMs / 3600000;
      const diffM  = diffMs / 60000;
      if (diffM < 60)  return { label: `${Math.round(diffM)}m lalu`, urgent: diffM < 30, hours: diffH };
      if (diffH < 24)  return { label: `${Math.round(diffH)}j lalu`,  urgent: diffH < 3,  hours: diffH };
      const diffD = Math.round(diffH / 24);
      return { label: `${diffD}h lalu`, urgent: false, hours: diffH };
    } catch { return { label: '', urgent: false, hours: 999 }; }
  }

  // Sort artikel: whale dulu, lalu berdasarkan usia (terbaru paling atas)
  const sortedArticles = [...articles].sort((a, b) => {
    const aW = a.whale?.is_whale ? 1 : 0;
    const bW = b.whale?.is_whale ? 1 : 0;
    if (aW !== bW) return bW - aW;
    const aH = articleAge(a.published).hours;
    const bH = articleAge(b.published).hours;
    return aH - bH;
  });

  // ── Whale Alert Banner ──
  let whaleBanner = '';
  if (ws.detected) {
    const wDir    = ws.overall_direction;
    const wLevel  = ws.alert_level;
    const wColor  = wDir === 'MASUK' ? '#0ECB81' : wDir === 'KELUAR' ? '#F6465D' : '#F0B90B';
    const wBg     = wDir === 'MASUK' ? '#0ECB8112' : wDir === 'KELUAR' ? '#F6465D12' : '#F0B90B12';
    const wBorder = wDir === 'MASUK' ? '#0ECB8140' : wDir === 'KELUAR' ? '#F6465D40' : '#F0B90B40';
    const wIcon   = wDir === 'MASUK' ? '▲' : wDir === 'KELUAR' ? '▼' : '◆';
    whaleBanner = `
      <div style="margin:0 0 12px 0;padding:14px 18px;background:${wBg};border:1px solid ${wBorder};border-radius:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <div style="font-weight:800;font-size:14px;color:${wColor}">${wIcon} WHALE ALERT — ${wDir}</div>
          <div class="signal-pill" style="background:${wColor}22;color:${wColor};border:1px solid ${wColor}44;font-weight:700">${wLevel}</div>
        </div>
        <div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">
          ${ws.buy_count} sinyal MASUK · ${ws.sell_count} sinyal KELUAR · ${ws.total_signals} total
        </div>
        ${(ws.alerts||[]).slice(0,4).map(a => {
          const age = articleAge(a.published);
          return `
          <div style="display:flex;gap:8px;padding:8px 0;border-top:1px solid ${wBorder};font-size:12px;align-items:flex-start">
            <span style="font-size:16px;flex-shrink:0">${a.icon||'●'}</span>
            <div style="flex:1">
              <div style="font-weight:600;color:${a.direction==='MASUK'?'var(--green)':a.direction==='KELUAR'?'var(--red)':'var(--yellow)'}">${a.label||a.direction}</div>
              <div style="color:var(--text-secondary);margin-top:2px">${(a.title||'').substring(0,90)}...</div>
              <div style="color:var(--text-muted);font-size:11px;margin-top:3px;display:flex;gap:8px">
                <span>${a.source||''}</span>
                <span style="color:${age.urgent?'var(--brand-1)':'var(--text-muted)'}">${age.label}</span>
              </div>
            </div>
          </div>`;
        }).join('')}
      </div>`;
  }

  // ── Update timestamp ──
  const fetchedAt = news.fetched_at ? new Date(news.fetched_at) : null;
  const fetchLabel = fetchedAt
    ? fetchedAt.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta' }) + ' WIB'
    : '';

  return `
    ${whaleBanner}
    <div style="padding:10px 18px;border-bottom:1px solid var(--panel-border);display:flex;justify-content:space-between;align-items:center">
      <div style="display:flex;gap:12px;font-size:12px">
        <span style="color:var(--green)">▲ ${ns.positive_articles||0} Positif</span>
        <span style="color:var(--red)">▼ ${ns.negative_articles||0} Negatif</span>
        <span style="color:var(--text-muted)">● ${ns.neutral_articles||0} Netral</span>
      </div>
      ${fetchLabel ? `<span style="font-size:10px;color:var(--text-muted);font-family:'JetBrains Mono',monospace">↻ ${fetchLabel}</span>` : ''}
    </div>
    <div class="news-list">
      ${sortedArticles.length ? sortedArticles.slice(0, 10).map(a => {
        const age = articleAge(a.published);
        const isRecent = age.hours < 6;
        const ageColor = age.urgent ? 'var(--brand-1)' : isRecent ? 'var(--text-secondary)' : 'var(--text-muted)';
        return `
        <div class="news-item${a.whale?.is_whale ? ' whale-article' : ''}"
             onclick="window.open('${a.link}','_blank')"
             style="${isRecent ? 'border-left:2px solid var(--panel-border)' : 'opacity:0.8'}">
          ${a.whale?.is_whale ? `
            <div style="font-size:11px;font-weight:700;color:${
              a.whale.direction==='MASUK'?'var(--green)':a.whale.direction==='KELUAR'?'var(--red)':'var(--yellow)'
            };margin-bottom:4px">${a.whale.icon||'●'} ${a.whale.alert_message||''}</div>` : ''}
          <div class="news-title">${a.title}</div>
          <div class="news-meta">
            <span style="display:flex;gap:6px;align-items:center">
              <span style="color:var(--text-muted)">${a.source}</span>
              <span style="color:${ageColor};font-size:10px;font-weight:${age.urgent?700:400}">${age.label || a.published}</span>
            </span>
            <div style="display:flex;gap:6px;align-items:center">
              <span class="signal-pill ${a.relevance==='SAHAM INI'?'signal-BUY':'signal-HOLD'}" style="font-size:9px">${a.relevance}</span>
              <span class="news-sentiment news-sent-${(a.sentiment?.label||'NETRAL').replace(/ /g,'-')}">${a.sentiment?.label||'NETRAL'}</span>
            </div>
          </div>
        </div>`;
      }).join('') : '<p class="empty-msg">Tidak ada berita tersedia</p>'}
    </div>`;
}

async function updateRealtimeNews(ticker) {
  try {
    const res = await fetch(`${API}/stock/${ticker}/news`);
    const data = await res.json();
    if (!data.success) return;

    const ns = data.sentiment_summary || {};
    const badge = document.getElementById('news-score-badge');
    if (badge) {
      badge.textContent = `${Math.round(ns.score||50)}/100`;
      badge.style.color = scoreColor(ns.score||50);
    }

    const contentEl = document.getElementById('news-content');
    if (contentEl) {
      contentEl.innerHTML = renderNewsHTML(data);
    }

    // Update "last refreshed" stamp on news badge
    const newsBadge = document.getElementById('rt-news-badge');
    if (newsBadge) {
      const now = new Date();
      const t   = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Jakarta' });
      newsBadge.title = `Terakhir diperbarui: ${t} WIB`;
    }
  } catch (e) {
    console.warn('[news realtime update]', e);
  }
}

async function changePeriod(period, btn) {
  document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentChartPeriod = period;

  // Stop chart poller — keep news poller running
  _stopChartPollOnly();

  if (!currentTicker) return;
  await loadChart(currentTicker, period);

  // Re-start chart price poller
  updateRealtimeBar(currentTicker);
  _realtimeInterval = setInterval(() => updateRealtimeBar(currentTicker), RT_INTERVAL_MS);

  // Re-add LIVE badge jika hilang
  const chartControls = document.querySelector('.chart-controls');
  if (chartControls && !document.getElementById('rt-live-badge')) {
    const badge = document.createElement('div');
    badge.id = 'rt-live-badge';
    badge.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:3px 10px;background:#0ECB8118;border:1px solid #0ECB8140;border-radius:20px;font-size:11px;font-weight:700;color:#0ECB81;margin-left:8px;cursor:default';
    badge.innerHTML = `<span style="width:7px;height:7px;border-radius:50%;background:#0ECB81;display:inline-block;animation:rtPulse 1.4s infinite"></span>LIVE`;
    chartControls.appendChild(badge);
  }
}

// ─── Realtime Chart & News ────────────────────────────────────
let _realtimeInterval   = null;
let _realtimeNewsInterval = null;
let _realtimeSeries     = null;
let _realtimeVolSeries  = null;
let _realtimeTicker     = null;
const RT_INTERVAL_MS    = 15000; // poll chart every 15s
const RT_NEWS_MS        = 60000; // poll news every 60s

/** Stop only the 1m chart series + price poller (used when switching periods) */
function _stopChartPollOnly() {
  if (_realtimeInterval) {
    clearInterval(_realtimeInterval);
    _realtimeInterval = null;
  }
  _realtimeSeries    = null;
  _realtimeVolSeries = null;
  _realtimeTicker    = null;
  const badge = document.getElementById('rt-live-badge');
  if (badge) badge.remove();
}

/** Stop everything — chart poller + news poller (used when leaving the analyze page) */
function stopRealtimeChart() {
  _stopChartPollOnly();
  if (_realtimeNewsInterval) {
    clearInterval(_realtimeNewsInterval);
    _realtimeNewsInterval = null;
  }
  const newsBadge = document.getElementById('rt-news-badge');
  if (newsBadge) newsBadge.remove();
}

function startRealtimeChart(ticker) {
  stopRealtimeChart();
  _realtimeTicker = ticker;

  // Inject keyframes if not present
  if (!document.getElementById('rt-pulse-style')) {
    const s = document.createElement('style');
    s.id = 'rt-pulse-style';
    s.textContent = `@keyframes rtPulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(1.4)} }`;
    document.head.appendChild(s);
  }

  // Add LIVE badge to chart controls
  const chartControls = document.querySelector('.chart-controls');
  if (chartControls && !document.getElementById('rt-live-badge')) {
    const badge = document.createElement('div');
    badge.id = 'rt-live-badge';
    badge.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:3px 10px;background:#0ECB8118;border:1px solid #0ECB8140;border-radius:20px;font-size:11px;font-weight:700;color:#0ECB81;margin-left:8px;cursor:default';
    badge.innerHTML = `<span style="width:7px;height:7px;border-radius:50%;background:#0ECB81;display:inline-block;animation:rtPulse 1.4s infinite"></span>LIVE`;
    chartControls.appendChild(badge);
  }

  // Add AUTO badge to news panel header
  const newsPanelHeader = document.querySelector('#news-content')?.closest('.analysis-panel')?.querySelector('.panel-header');
  if (newsPanelHeader && !document.getElementById('rt-news-badge')) {
    const newsBadge = document.createElement('span');
    newsBadge.id = 'rt-news-badge';
    newsBadge.style.cssText = 'display:inline-flex;align-items:center;gap:4px;padding:2px 8px;background:#9ca3af18;border:1px solid #9ca3af40;border-radius:20px;font-size:10px;font-weight:700;color:#9ca3af;margin-left:8px';
    newsBadge.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:#9ca3af;display:inline-block;animation:rtPulse 2s infinite"></span>AUTO`;
    newsPanelHeader.appendChild(newsBadge);
  }

  // ── Chart: poll harga setiap 15s ──
  // (update bar kalau lagi di 1d, atau hanya harga header untuk periode lain)
  updateRealtimeBar(ticker);
  _realtimeInterval = setInterval(() => updateRealtimeBar(ticker), RT_INTERVAL_MS);

  // ── News: fetch ulang setiap 60s ──
  updateRealtimeNews(ticker);
  _realtimeNewsInterval = setInterval(() => updateRealtimeNews(ticker), RT_NEWS_MS);
}

async function updateRealtimeBar(ticker) {
  if (!currentChart) return;
  try {
    const res  = await fetch(`${API}/stock/${ticker}/realtime`);
    const data = await res.json();
    if (!data.success || !data.bars?.length) return;

    const bars = data.bars; // sudah berupa Unix timestamp dari server

    if (currentChartPeriod === '1d') {
      // ── Mode intraday 1m: update/replace chart dengan data terbaru ──
      if (_realtimeSeries && _realtimeTicker === ticker) {
        // Update bar terakhir saja
        const lastBar = bars[bars.length - 1];
        try {
          _realtimeSeries.update({
            time:  lastBar.time,
            open:  lastBar.open,
            high:  lastBar.high,
            low:   lastBar.low,
            close: lastBar.close,
          });
          if (_realtimeVolSeries) {
            _realtimeVolSeries.update({
              time:  lastBar.time,
              value: lastBar.volume,
              color: lastBar.close >= lastBar.open ? '#0ECB8140' : '#F6465D40',
            });
          }
        } catch (seriesErr) {
          // Series mungkin sudah invalid — reset
          _realtimeSeries = null;
          _realtimeVolSeries = null;
        }
      } else if (currentChart && bars.length >= 2) {
        // Pertama kali masuk realtime mode — set full data ke series yang sudah ada
        // Cari candlestick series di chart yang ada
        try {
          _realtimeSeries = currentChart.addCandlestickSeries({
            upColor:       '#0ECB81', downColor:       '#F6465D',
            borderUpColor: '#0ECB81', borderDownColor: '#F6465D',
            wickUpColor:   '#0ECB81', wickDownColor:   '#F6465D',
          });
          _realtimeVolSeries = currentChart.addHistogramSeries({
            priceFormat: { type: 'volume' },
            priceScaleId: 'vol_rt',
            scaleMargins: { top: 0.82, bottom: 0 },
          });
          _realtimeSeries.setData(bars.map(b => ({
            time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
          })));
          _realtimeVolSeries.setData(bars.map(b => ({
            time: b.time, value: b.volume,
            color: b.close >= b.open ? '#0ECB8140' : '#F6465D40',
          })));
          currentChart.timeScale().fitContent();
          _realtimeTicker = ticker;
        } catch (addErr) {
          console.warn('[realtime] series add error:', addErr.message);
        }
      }
    }
    // Untuk period selain 1d (3mo, 6mo, dll): tidak update chart series,
    // hanya update harga di header — chart historis tetap utuh

    // ── Update price header ──
    const lastBar  = bars[bars.length - 1];
    const chgColor = (data.change_pct || 0) >= 0 ? 'var(--green)' : 'var(--red)';
    const priceEl  = document.querySelector('#stock-header .price-big');
    const chgEl    = document.querySelector('#stock-header .price-change-big');
    if (priceEl) {
      priceEl.textContent = `Rp ${formatNum(data.last_price, 0)}`;
      priceEl.style.transition = 'color 0.3s';
      priceEl.style.color = chgColor;
      setTimeout(() => { priceEl.style.color = 'var(--text-primary)'; }, 400);
    }
    if (chgEl) {
      chgEl.style.color = chgColor;
      chgEl.textContent = `${data.change_pct >= 0 ? '+' : ''}${(data.change_pct||0).toFixed(2)}%`;
    }

    // Update LIVE badge tooltip
    const liveBadge = document.getElementById('rt-live-badge');
    if (liveBadge) {
      const now = new Date();
      const t   = now.toLocaleTimeString('id-ID', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Jakarta'
      });
      liveBadge.title = `Diperbarui: ${t} WIB`;
    }

  } catch(e) {
    console.warn('[realtime]', e.message);
  }
}

// ─── Portfolio Full Page ──────────────────────────────────────
async function loadPortfolioFull() {
  const el = document.getElementById('portfolio-full-content');
  try {
    const res  = await fetch(`${API}/portfolio`);
    const data = await res.json();
    if (!data.success) { el.innerHTML = `<p class="empty-msg">Error memuat portfolio</p>`; return; }
    const d = data.data;
    const risk = d.risk_metrics || {};
    const pnlColor = d.total_pnl_rp >= 0 ? 'var(--green)' : 'var(--red)';

    el.innerHTML = `
      <!-- Summary Cards -->
      <div class="portfolio-summary-cards">
        <div class="port-stat">
          <div class="port-stat-label">Total Portfolio</div>
          <div class="port-stat-value">Rp ${formatNum(d.total_portfolio_value, 0)}</div>
          <div style="color:${pnlColor};font-size:13px">${d.total_pnl_rp>=0?'+':''}Rp ${formatNum(d.total_pnl_rp,0)} (${d.total_pnl_pct>=0?'+':''}${d.total_pnl_pct.toFixed(2)}%)</div>
        </div>
        <div class="port-stat">
          <div class="port-stat-label">Saldo Tunai</div>
          <div class="port-stat-value">Rp ${formatNum(d.cash,0)}</div>
          <div style="color:var(--text-secondary);font-size:13px">${d.cash_ratio_pct}% dari total</div>
        </div>
        <div class="port-stat">
          <div class="port-stat-label">Realized P&L</div>
          <div class="port-stat-value" style="color:${d.realized_pnl>=0?'var(--green)':'var(--red)'}">
            ${d.realized_pnl>=0?'+':''}Rp ${formatNum(d.realized_pnl,0)}
          </div>
          <div style="color:var(--text-secondary);font-size:13px">Win Rate: ${d.trade_stats.win_rate_pct}%</div>
        </div>
      </div>

      <!-- Risk Metrics -->
      <div class="panel" style="margin-bottom:16px">
        <div class="panel-header"><h3>Risk Metrics</h3></div>
        <div style="padding:14px 18px;display:flex;gap:20px;flex-wrap:wrap;font-size:13px">
          <div><span style="color:var(--text-muted)">Risk Level:</span> <strong style="color:${riskColor(risk.risk_level)}">${risk.risk_level||'N/A'}</strong></div>
          <div><span style="color:var(--text-muted)">Max Pos:</span> <strong>${risk.max_position_pct||0}%</strong></div>
          <div><span style="color:var(--text-muted)">Cash Buffer:</span> <strong>${risk.cash_buffer_pct||0}%</strong></div>
          <div><span style="color:var(--text-muted)">Drawdown:</span> <strong style="color:${risk.current_drawdown_pct>10?'var(--red)':'var(--text-primary)'}">${risk.current_drawdown_pct||0}%</strong></div>
          ${risk.kelly ? `<div style="color:var(--text-muted)">${risk.kelly.note}</div>` : ''}
        </div>
      </div>

      <!-- Positions Table -->
      <div class="panel">
        <div class="panel-header">
          <h3>Posisi Aktif (${d.positions.length})</h3>
          <button class="btn-sm" onclick="loadPortfolioFull()">↻ Refresh</button>
        </div>
        ${d.positions.length ? `
        <div class="positions-card-list">
          ${d.positions.map(p => `
          <div class="pos-card-row">
            <div class="pos-card-left">
              <div class="pos-card-ticker">${p.ticker}</div>
              <div class="pos-card-meta">${p.lots} lot &nbsp;·&nbsp; Avg Rp ${formatNum(p.avg_price,0)}</div>
            </div>
            <div class="pos-card-mid">
              <div class="pos-card-price">Rp ${formatNum(p.current_price,0)}</div>
              <div class="pos-card-mktval">Nilai: Rp ${formatNum(p.market_value,0)}</div>
            </div>
            <div class="pos-card-pnl" style="color:${p.pnl_rp>=0?'var(--green)':'var(--red)'}">
              <div>${p.pnl_rp>=0?'+':''}Rp ${formatNum(p.pnl_rp,0)}</div>
              <div style="font-size:11px">${p.pnl_pct>=0?'+':''}${p.pnl_pct.toFixed(2)}%</div>
            </div>
            <div class="pos-card-actions">
              <button class="pos-btn-analyze" onclick="analyzeStock('${p.ticker}')">Analisis</button>
              <button class="pos-btn-sell" onclick="openSellDrawer('${p.ticker}',${p.current_price},${p.lots},${p.avg_price})">Jual</button>
            </div>
          </div>`).join('')}
        </div>` : '<p class="empty-msg">Belum ada posisi aktif</p>'}
      </div>`;
  } catch(e) {
    el.innerHTML = `<p class="empty-msg">Error: ${e.message}</p>`;
  }
}

// ══════════════════════════════════════════════════════════════
//  FAST TRADE CENTER
// ══════════════════════════════════════════════════════════════
let ftMode      = 'paper';   // 'paper' | 'signal'
let ftLeverage  = 1;
let ftCash      = 0;
let ftCurrentPrice = 0;

// ── Inisialisasi halaman trade ────────────────────────────────
function ftHotkey(e) {
  // Hanya aktif saat halaman trade terbuka dan fokus bukan di input
  if (!document.getElementById('page-trade')?.classList.contains('active')) return;
  if (['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)) return;
  if (e.key === 'b' || e.key === 'B') ftExecute('BUY');
  if (e.key === 's' || e.key === 'S') ftExecute('SELL');
  if (e.key === 'r' || e.key === 'R') ftFetchPrice();
}

// ── Mode Toggle ───────────────────────────────────────────────
function setTradeMode(mode) {
  ftMode = mode;
  document.getElementById('ft-mode-paper').classList.toggle('active', mode === 'paper');
  document.getElementById('ft-mode-signal').classList.toggle('active', mode === 'signal');
  const info = document.getElementById('ft-mode-info');
  if (info) info.textContent = mode === 'paper'
    ? 'Mode simulasi — order masuk ke portfolio virtual'
    : 'Mode sinyal — hanya kirim notifikasi ke Telegram, tidak eksekusi';
  ftUpdateCalc();
}

// ── Quick Pick Ticker ─────────────────────────────────────────
function ftQuickPick(ticker) {
  document.getElementById('ft-ticker').value = ticker;
  ftFetchPrice();
}

// ── Fetch Harga ───────────────────────────────────────────────
async function ftFetchPrice() {
  const ticker = document.getElementById('ft-ticker').value.trim().toUpperCase();
  if (!ticker) { showToast('Masukkan kode saham', 'error'); return; }
  const nameEl  = document.getElementById('ft-company-name');
  const priceEl = document.getElementById('ft-price-val');
  const chgEl   = document.getElementById('ft-price-chg');
  nameEl.textContent  = 'Mengambil data...';
  priceEl.textContent = '...';
  try {
    const res  = await fetch(`${API}/stock/${ticker}`);
    const data = await res.json();
    if (!data.success) { showToast(`${ticker} tidak ditemukan`, 'error'); return; }
    const d = data.data;
    ftCurrentPrice = d.current_price;
    priceEl.textContent = `Rp ${formatNum(d.current_price, 0)}`;
    const chgColor = d.change_pct >= 0 ? 'var(--green)' : 'var(--red)';
    chgEl.textContent  = `${d.change_pct >= 0 ? '+' : ''}${d.change_pct.toFixed(2)}%`;
    chgEl.style.color  = chgColor;
    nameEl.textContent = d.company_name;
    // Auto-isi harga input
    document.getElementById('ft-price-input').value = d.current_price;
    // Auto-set SL/TP default (5% & 10%)
    if (!document.getElementById('ft-sl').value) {
      document.getElementById('ft-sl').value = Math.round(d.current_price * 0.95);
    }
    if (!document.getElementById('ft-tp').value) {
      document.getElementById('ft-tp').value = Math.round(d.current_price * 1.10);
    }
    ftLoadPosition(ticker);
    ftUpdateCalc();
  } catch(e) { showToast('Gagal fetch harga', 'error'); }
}

// ── Leverage Selector ─────────────────────────────────────────
function ftSetLeverage(lev, btn) {
  ftLeverage = lev;
  document.querySelectorAll('.ft-lev-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  ftUpdateCalc();
}

// ── Lot Controls ──────────────────────────────────────────────
function ftChangeLot(delta) {
  const inp = document.getElementById('ft-lots');
  inp.value = Math.max(1, (parseInt(inp.value) || 1) + delta);
  ftUpdateCalc();
}

function ftSetLot(n) {
  document.getElementById('ft-lots').value = n;
  ftUpdateCalc();
}

async function ftSetMaxLot() {
  const price = parseFloat(document.getElementById('ft-price-input').value) || ftCurrentPrice;
  if (!price) { showToast('Cek harga dulu', 'error'); return; }
  try {
    const res  = await fetch(`${API}/portfolio`);
    const data = await res.json();
    if (!data.success) return;
    const cash        = data.data.cash;
    const costPerLot  = price * 100 * (1 + 0.0019) / ftLeverage;
    const maxLots     = Math.max(1, Math.floor(cash / costPerLot));
    document.getElementById('ft-lots').value = maxLots;
    ftUpdateCalc();
  } catch(e) {}
}

// ── Update Kalkulasi & Summary ────────────────────────────────
async function ftUpdateCalc() {
  const ticker = document.getElementById('ft-ticker').value.trim().toUpperCase();
  const price  = parseFloat(document.getElementById('ft-price-input').value) || 0;
  const lots   = parseInt(document.getElementById('ft-lots').value) || 1;
  const sl     = parseFloat(document.getElementById('ft-sl').value) || 0;
  const tp     = parseFloat(document.getElementById('ft-tp').value) || 0;

  // Update BUY/SELL sub-labels
  const buySub  = document.getElementById('ft-buy-sub');
  const sellSub = document.getElementById('ft-sell-sub');
  if (price && lots) {
    const gross = price * lots * 100;
    const fee   = gross * 0.0019;
    const total = gross + fee;
    if (buySub)  buySub.textContent  = `Rp ${formatNum(total, 0)}`;
    if (sellSub) sellSub.textContent = `Rp ${formatNum(gross * (1 - 0.0029), 0)}`;
  }

  // Summary box
  const sumBody = document.getElementById('ft-summary-body');
  if (!price || !lots || !ticker) {
    if (sumBody) sumBody.innerHTML = '<div style="color:var(--text-muted);font-size:12px">Isi form untuk melihat ringkasan</div>';
    return;
  }

  // Leverage calc dari server
  try {
    const res  = await fetch(`${API}/trade/leverage-calc`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, price, lots, leverage: ftLeverage }),
    });
    const data = await res.json();
    if (!data.success) return;
    const s    = data.selected;
    ftCash     = data.cash;

    // Leverage detail panel
    const levDetail = document.getElementById('ft-lev-detail');
    if (levDetail) {
      const liqLine = s.leverage > 1
        ? `<div class="ft-lev-row"><span class="ft-lev-label">Liquidation</span><span class="ft-lev-value" style="color:var(--red)">Rp ${formatNum(s.liquidation_price,0)}</span></div>`
        : '';
      const intLine = s.leverage > 1
        ? `<div class="ft-lev-row"><span class="ft-lev-label">Bunga/Hari</span><span class="ft-lev-value" style="color:var(--yellow)">Rp ${formatNum(s.interest_daily_rp,0)}</span></div>`
        : '';
      levDetail.innerHTML = `
        <div class="ft-lev-row"><span class="ft-lev-label">Nilai Posisi</span><span class="ft-lev-value">Rp ${formatNum(s.full_value,0)}</span></div>
        <div class="ft-lev-row"><span class="ft-lev-label">Modal Diperlukan</span><span class="ft-lev-value" style="color:${s.can_afford?'var(--green)':'var(--red)'}">Rp ${formatNum(s.total_modal,0)}</span></div>
        ${s.leverage > 1 ? `<div class="ft-lev-row"><span class="ft-lev-label">Pinjaman</span><span class="ft-lev-value">Rp ${formatNum(s.pinjaman,0)}</span></div>` : ''}
        ${liqLine}${intLine}
        <div class="ft-lev-row"><span class="ft-lev-label">Risk Level</span><span class="ft-lev-value" style="color:${s.color}">${s.risk_level}</span></div>`;
    }

    // Order summary panel
    const isBuy = true;
    const rr    = sl && tp ? ((tp - price) / (price - sl)).toFixed(2) : null;
    const riskRp = sl ? Math.abs(price - sl) * lots * 100 : null;
    const canAfford = s.can_afford;
    if (sumBody) {
      sumBody.innerHTML = `
        <div class="ft-sum-row"><span class="ft-sum-label">Nilai Transaksi</span><span class="ft-sum-value">Rp ${formatNum(s.full_value,0)}</span></div>
        <div class="ft-sum-row"><span class="ft-sum-label">Fee (0.19%)</span><span class="ft-sum-value" style="color:var(--red)">Rp ${formatNum(s.fee_buy,0)}</span></div>
        ${s.leverage > 1 ? `<div class="ft-sum-row"><span class="ft-sum-label">Leverage</span><span class="ft-sum-value" style="color:${s.color}">${s.leverage}x — ${s.label}</span></div>` : ''}
        <div class="ft-sum-row ft-sum-total">
          <span class="ft-sum-label">Modal Diperlukan</span>
          <span class="ft-sum-value" style="color:${canAfford?'var(--green)':'var(--red)'}">
            Rp ${formatNum(s.total_modal,0)} ${canAfford ? '✓' : '✕ Saldo Kurang'}
          </span>
        </div>
        <div class="ft-sum-row"><span class="ft-sum-label">Saldo Tersedia</span><span class="ft-sum-value">Rp ${formatNum(ftCash,0)}</span></div>
        ${sl ? `<div class="ft-sum-row"><span class="ft-sum-label" style="color:var(--red)">Stop Loss</span><span class="ft-sum-value" style="color:var(--red)">Rp ${formatNum(sl,0)} (-${((price-sl)/price*100).toFixed(1)}%)</span></div>` : ''}
        ${tp ? `<div class="ft-sum-row"><span class="ft-sum-label" style="color:var(--green)">Take Profit</span><span class="ft-sum-value" style="color:var(--green)">Rp ${formatNum(tp,0)} (+${((tp-price)/price*100).toFixed(1)}%)</span></div>` : ''}
        ${rr ? `<div class="ft-sum-row"><span class="ft-sum-label">Risk/Reward</span><span class="ft-sum-value" style="color:var(--yellow)">1 : ${rr}</span></div>` : ''}
        ${riskRp ? `<div class="ft-sum-row"><span class="ft-sum-label">Max Rugi</span><span class="ft-sum-value" style="color:var(--red)">Rp ${formatNum(riskRp,0)}</span></div>` : ''}`;
    }

    // Risk panel (kanan)
    ftUpdateRiskPanel(s, sl, tp, price, lots);

    // Update button state
    document.getElementById('ft-btn-buy').disabled  = !canAfford;
    document.getElementById('ft-btn-sell').disabled = false;

  } catch(e) {
    console.warn('[ft calc]', e.message);
  }
}

function ftUpdateRiskPanel(s, sl, tp, price, lots) {
  const el = document.getElementById('ft-risk-content');
  if (!el) return;
  if (!sl) {
    el.innerHTML = '<p class="empty-msg">Isi Stop Loss untuk kalkulasi risiko</p>';
    return;
  }
  const riskRp  = Math.abs(price - sl) * lots * 100;
  const riskPct = (riskRp / ftCash * 100).toFixed(2);
  const gainRp  = tp ? Math.abs(tp - price) * lots * 100 : 0;
  const rr      = gainRp && riskRp ? (gainRp / riskRp).toFixed(2) : '—';
  el.innerHTML = `
    <div style="padding:14px 16px">
      <div class="ft-risk-row"><span class="ft-risk-label">Max Kerugian (SL)</span><span class="ft-risk-value" style="color:var(--red)">Rp ${formatNum(riskRp,0)}</span></div>
      <div class="ft-risk-row"><span class="ft-risk-label">% dari Modal</span><span class="ft-risk-value" style="color:${parseFloat(riskPct)>2?'var(--red)':parseFloat(riskPct)>1?'var(--yellow)':'var(--green)'}">${riskPct}%</span></div>
      ${gainRp ? `<div class="ft-risk-row"><span class="ft-risk-label">Potensi Gain (TP)</span><span class="ft-risk-value" style="color:var(--green)">Rp ${formatNum(gainRp,0)}</span></div>` : ''}
      <div class="ft-risk-row"><span class="ft-risk-label">Risk/Reward Ratio</span><span class="ft-risk-value" style="color:var(--yellow)">1 : ${rr}</span></div>
      ${s.leverage > 1 ? `<div class="ft-risk-row"><span class="ft-risk-label">Bunga/Bulan</span><span class="ft-risk-value" style="color:var(--yellow)">Rp ${formatNum(s.interest_monthly_rp,0)}</span></div>` : ''}
      <div style="margin-top:10px;padding:8px;background:${parseFloat(riskPct)>2?'#F6465D15':parseFloat(riskPct)>1?'#F0B90B15':'#0ECB8115'};border-radius:6px;font-size:11px;color:var(--text-secondary)">
        ${parseFloat(riskPct) > 3 ? 'Risiko TINGGI — lebih dari 3% modal' : parseFloat(riskPct) > 1 ? 'Risiko SEDANG — 1-3% modal' : 'Risiko RENDAH — di bawah 1% modal'}
      </div>
    </div>`;
}

// ── Load Position ─────────────────────────────────────────────
async function ftLoadPosition(ticker) {
  ticker = ticker || document.getElementById('ft-ticker').value.trim().toUpperCase();
  const el = document.getElementById('ft-position-content');
  if (!ticker || !el) return;
  try {
    const res  = await fetch(`${API}/portfolio`);
    const data = await res.json();
    if (!data.success) return;
    const pos = data.data.positions.find(p => p.ticker === ticker);
    if (!pos) {
      el.innerHTML = `<p class="empty-msg" style="padding:14px">Tidak ada posisi ${ticker}</p>`;
      return;
    }
    const pnlColor = pos.pnl_rp >= 0 ? 'var(--green)' : 'var(--red)';
    el.innerHTML = `
      <div style="padding:14px 16px;font-size:13px">
        <div style="font-size:16px;font-weight:800;color:var(--brand-1);margin-bottom:10px">${pos.ticker}</div>
        <div class="ft-risk-row"><span class="ft-risk-label">Lot Dimiliki</span><span class="ft-risk-value">${pos.lots} lot</span></div>
        <div class="ft-risk-row"><span class="ft-risk-label">Avg Buy Price</span><span class="ft-risk-value">Rp ${formatNum(pos.avg_price,0)}</span></div>
        <div class="ft-risk-row"><span class="ft-risk-label">Harga Saat Ini</span><span class="ft-risk-value">Rp ${formatNum(pos.current_price,0)}</span></div>
        <div class="ft-risk-row"><span class="ft-risk-label">Market Value</span><span class="ft-risk-value">Rp ${formatNum(pos.market_value,0)}</span></div>
        <div class="ft-risk-row"><span class="ft-risk-label">P&L</span>
          <span class="ft-risk-value" style="color:${pnlColor}">${pos.pnl_rp>=0?'+':''}Rp ${formatNum(pos.pnl_rp,0)} (${pos.pnl_pct>=0?'+':''}${pos.pnl_pct.toFixed(2)}%)</span>
        </div>
        <button class="btn-danger" style="width:100%;margin-top:10px;font-size:12px" onclick="ftSellAll('${pos.ticker}',${pos.current_price},${pos.lots})">
          Jual Semua ${pos.lots} Lot
        </button>
      </div>`;
  } catch(e) {}
}

function ftSellAll(ticker, price, lots) {
  document.getElementById('ft-ticker').value       = ticker;
  document.getElementById('ft-price-input').value  = price;
  document.getElementById('ft-lots').value         = lots;
  ftCurrentPrice = price;
  ftUpdateCalc();
  ftExecute('SELL');
}

// ── Alert Status ──────────────────────────────────────────────
async function ftLoadAlertStatus() {
  const el = document.getElementById('ft-alert-status');
  if (!el) return;
  try {
    const res  = await fetch(`${API}/alert/config`);
    const data = await res.json();
    if (!data.success) return;
    const cfg = data.config;
    const on  = cfg.telegram_enabled && cfg.telegram_bot_token_set;
    el.innerHTML = `
      <div class="ft-alert-row">
        <div class="ft-alert-dot ${on?'on':'off'}"></div>
        <div style="flex:1">
          <div style="font-size:13px;font-weight:600">${on?'Telegram Aktif':'Telegram Nonaktif'}</div>
          <div style="font-size:11px;color:var(--text-muted)">${on?`Broker: ${cfg.broker_name||'—'}  · App: ${cfg.broker_app_name||'—'}`:'Set token di Pengaturan → Telegram Alert'}</div>
        </div>
        <button class="btn-sm" onclick="showPage('settings')">${on?'Edit':'Setup'}</button>
      </div>`;
  } catch(e) {}
}

// ── Eksekusi Order ────────────────────────────────────────────
async function ftExecute(action) {
  const ticker = document.getElementById('ft-ticker').value.trim().toUpperCase();
  const price  = parseFloat(document.getElementById('ft-price-input').value) || 0;
  const lots   = parseInt(document.getElementById('ft-lots').value) || 0;
  const sl     = parseFloat(document.getElementById('ft-sl').value) || 0;
  const tp     = parseFloat(document.getElementById('ft-tp').value) || 0;
  const note   = document.getElementById('ft-note').value || `${action} via Fast Trade`;

  if (!ticker || price <= 0 || lots <= 0) {
    showToast('Lengkapi: ticker, harga, dan lot!', 'error'); return;
  }

  const gross = price * lots * 100;
  const fee   = gross * (action === 'BUY' ? 0.0019 : 0.0029);
  const total = action === 'BUY' ? gross + fee : gross - fee;
  const levLabel = ftLeverage > 1 ? ` [${ftLeverage}x Leverage]` : '';

  const modeLabel = ftMode === 'paper' ? 'Paper Trade' : 'Kirim Sinyal';
  const confBody  = `
    <div style="margin-bottom:14px">
      <strong style="font-size:20px;color:${action==='BUY'?'var(--green)':'var(--red)'}">${action==='BUY'?'BUY':'SELL'} ${lots} lot ${ticker}${levLabel}</strong>
    </div>
    <div style="font-size:13px;line-height:2;background:var(--bg-700);padding:12px;border-radius:8px">
      Harga   : <strong>Rp ${formatNum(price,0)}</strong><br>
      Lot     : <strong>${lots} lot</strong> (${lots*100} lembar)<br>
      Nilai   : Rp ${formatNum(gross,0)}<br>
      Fee     : Rp ${formatNum(fee,0)}<br>
      <strong>${action==='BUY'?'Total Bayar':'Net Terima'}: Rp ${formatNum(total,0)}</strong>
      ${sl ? `<br>Stop Loss  : <span style="color:var(--red)">Rp ${formatNum(sl,0)}</span>` : ''}
      ${tp ? `<br>Take Profit: <span style="color:var(--green)">Rp ${formatNum(tp,0)}</span>` : ''}
    </div>
    <div style="margin-top:12px;font-size:12px;color:var(--text-muted)">Mode: ${modeLabel}</div>`;

  showModal(
    `Konfirmasi ${action}`,
    confBody,
    () => ftDoExecute(action, ticker, price, lots, sl, tp, note),
    `Eksekusi ${action}`,
    action === 'SELL'
  );
}

async function ftDoExecute(action, ticker, price, lots, sl, tp, note) {
  const btnBuy  = document.getElementById('ft-btn-buy');
  const btnSell = document.getElementById('ft-btn-sell');
  if (btnBuy)  btnBuy.disabled  = true;
  if (btnSell) btnSell.disabled = true;

  try {
    let result;
    if (ftMode === 'paper') {
      // Paper trade — eksekusi + kirim alert jika Telegram aktif
      const endpoint = action === 'BUY' ? 'fast-buy' : 'fast-sell';
      const res = await fetch(`${API}/trade/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, price, lots, leverage: ftLeverage, stop_loss: sl, take_profit: tp, note }),
      });
      result = await res.json();
    } else {
      // Signal only — tidak eksekusi portfolio
      const res = await fetch(`${API}/trade/signal`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ticker, price, lots, leverage: ftLeverage, stop_loss: sl, take_profit: tp, note }),
      });
      result = await res.json();
    }

    if (result.success) {
      const alertOk = result.alert?.channels?.telegram?.success;
      const alertMsg = alertOk ? ' · Terkirim ke Telegram' : '';
      showToast((result.message || `${action} berhasil`) + alertMsg, 'success');
      // Refresh
      loadPortfolioStats();
      loadRecentOrders();
      ftLoadPosition(ticker);
      ftUpdateCalc();
    } else {
      showToast(`Error: ${result.error}`, 'error');
    }
  } catch(e) {
    showToast(`Gagal: ${e.message}`, 'error');
  } finally {
    if (btnBuy)  btnBuy.disabled  = false;
    if (btnSell) btnSell.disabled = false;
  }
}

// ── quickSell → buka sell drawer ─────────────────────────────
function quickSell(ticker, price, lots) {
  openSellDrawer(ticker, price, lots, 0);
}

// ── Sell Drawer ───────────────────────────────────────────────
let _sdTicker = '', _sdMaxLots = 1, _sdAvg = 0;

function openSellDrawer(ticker, currentPrice, maxLots, avgPrice) {
  _sdTicker  = ticker;
  _sdMaxLots = maxLots;
  _sdAvg     = avgPrice;

  document.getElementById('sd-ticker').textContent    = ticker;
  document.getElementById('sd-price').textContent     = 'Rp ' + formatNum(currentPrice, 0);
  document.getElementById('sd-lots-max').textContent  = maxLots;
  document.getElementById('sd-avg-price').textContent = 'Rp ' + formatNum(avgPrice, 0);

  const pnlPct = avgPrice ? ((currentPrice - avgPrice) / avgPrice * 100) : 0;
  const pnlEl  = document.getElementById('sd-pnl');
  pnlEl.textContent = (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%';
  pnlEl.style.color = pnlPct >= 0 ? 'var(--green)' : 'var(--red)';

  const slider = document.getElementById('sd-lots-slider');
  slider.max   = maxLots;
  slider.value = maxLots;
  document.getElementById('sd-lots-input').value  = maxLots;
  document.getElementById('sd-sell-price').value  = currentPrice;

  sdUpdateCalc();

  document.getElementById('sell-drawer-overlay').classList.remove('hidden');
  document.getElementById('sell-drawer').classList.add('open');
}

function closeSellDrawer() {
  document.getElementById('sell-drawer-overlay').classList.add('hidden');
  document.getElementById('sell-drawer').classList.remove('open');
}

function sdSetLots(val) {
  const v = Math.max(1, Math.min(_sdMaxLots, parseInt(val) || 1));
  document.getElementById('sd-lots-input').value  = v;
  document.getElementById('sd-lots-slider').value = v;
  sdUpdateCalc();
}

function sdSetPercent(pct) {
  sdSetLots(Math.max(1, Math.round(_sdMaxLots * pct / 100)));
}

function sdUpdateCalc() {
  const price  = parseFloat(document.getElementById('sd-sell-price').value) || 0;
  const lots   = parseInt(document.getElementById('sd-lots-input').value) || 1;
  const shares = lots * 100;
  const gross  = price * shares;
  const fee    = gross * 0.0029;
  const net    = gross - fee;
  const pnl    = _sdAvg ? (net - _sdAvg * shares) : 0;
  const pnlPct = _sdAvg ? (pnl / (_sdAvg * shares) * 100) : 0;

  document.getElementById('sd-calc-gross').textContent = 'Rp ' + formatNum(gross, 0);
  document.getElementById('sd-calc-fee').textContent   = 'Rp ' + formatNum(fee, 0);
  document.getElementById('sd-calc-net').textContent   = 'Rp ' + formatNum(net, 0);

  const pnlEl = document.getElementById('sd-calc-pnl');
  pnlEl.textContent = (pnl >= 0 ? '+' : '') + 'Rp ' + formatNum(pnl, 0) + ' (' + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%)';
  pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
}

async function executeSellDrawer() {
  const ticker = _sdTicker;
  const price  = parseFloat(document.getElementById('sd-sell-price').value) || 0;
  const lots   = parseInt(document.getElementById('sd-lots-input').value) || 0;
  if (!ticker || price <= 0 || lots <= 0) { showToast('Lengkapi harga dan lot', 'error'); return; }

  const btn = document.getElementById('sd-exec-btn');
  btn.disabled = true; btn.textContent = 'Memproses...';

  try {
    const res  = await fetch(API + '/trade/fast-sell', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, price, lots, note: 'Jual dari Portfolio' }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || ('Jual ' + lots + ' lot ' + ticker + ' berhasil'), 'success');
      closeSellDrawer();
      loadPortfolioFull(); loadPortfolioStats(); loadRecentOrders();
    } else {
      showToast('Gagal: ' + data.error, 'error');
    }
  } catch(e) {
    showToast('Error: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Konfirmasi Jual';
  }
}

async function prepareOrder(action) {
  if (!currentAnalysis) { showPage('trade'); return; }

  // Jika ada analisis AI → isi form sesuai harga yang ditentukan AI
  if (currentAI) { applyAITradePlan(action); return; }

  // Tanpa AI → fallback ke harga pasar + SL/TP default
  const info  = currentAnalysis.stock_info?.data || {};
  const price = info.current_price || 0;
  document.getElementById('ft-ticker').value      = currentTicker;
  document.getElementById('ft-price-input').value = price;
  document.getElementById('ft-sl').value          = Math.round(price * 0.95);
  document.getElementById('ft-tp').value          = Math.round(price * 1.10);
  document.getElementById('ft-lots').value        = 1;
  ftCurrentPrice = price;
  ftUpdateCalc();
  showPage('trade');
}

// ─── History ──────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res  = await fetch(`${API}/portfolio/history`);
    const data = await res.json();
    allHistory = data.data || [];
    renderHistory(allHistory);
  } catch(e) {}
}

function filterHistory(type, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const filtered = type === 'all' ? allHistory : allHistory.filter(t => t.type === type);
  renderHistory(filtered);
}

function renderHistory(history) {
  const el = document.getElementById('history-table-content');
  if (!history.length) {
    el.innerHTML = `<p class="empty-msg">Belum ada transaksi</p>`; return;
  }
  el.innerHTML = `
    <table class="history-table">
      <thead><tr><th>#</th><th>Tipe</th><th>Saham</th><th>Harga</th><th>Lot</th><th>Nilai</th><th>Fee</th><th>P&L</th><th>Catatan</th><th>Waktu</th></tr></thead>
      <tbody>
        ${[...history].reverse().map(t => `
        <tr>
          <td style="color:var(--text-muted)">${t.id}</td>
          <td class="trade-type-${t.type.toLowerCase()}">${t.type}</td>
          <td><strong class="ticker-cell">${t.ticker}</strong></td>
          <td class="price-cell">Rp ${formatNum(t.price,0)}</td>
          <td>${t.lots}</td>
          <td class="price-cell">Rp ${formatNum(t.gross_value||0,0)}</td>
          <td class="price-cell" style="color:var(--red)">Rp ${formatNum(t.fee||0,0)}</td>
          <td class="price-cell" style="color:${t.pnl_rp>=0?'var(--green)':'var(--red)'}">
            ${t.pnl_rp!=null ? `${t.pnl_rp>=0?'+':''}Rp ${formatNum(t.pnl_rp,0)} (${t.pnl_pct>=0?'+':''}${t.pnl_pct?.toFixed(2)}%)` : '—'}
          </td>
          <td style="font-size:11px;color:var(--text-muted)">${t.note||'—'}</td>
          <td style="font-size:11px;color:var(--text-muted);white-space:nowrap">${t.timestamp?.substring(0,16)||'—'}</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
}

async function loadRecentOrders() {
  try {
    const res  = await fetch(`${API}/portfolio/history`);
    const data = await res.json();
    const history = (data.data || []).slice(-5).reverse();
    const el = document.getElementById('recent-orders-content');
    if (!history.length) { el.innerHTML = `<p class="empty-msg">Belum ada order</p>`; return; }
    el.innerHTML = history.map(t => `
      <div style="padding:8px 0;border-bottom:1px solid #202026;font-size:12px">
        <div style="display:flex;justify-content:space-between">
          <span class="trade-type-${t.type.toLowerCase()}">${t.type}</span>
          <strong class="ticker-cell">${t.ticker}</strong>
          <span style="font-family:'JetBrains Mono',monospace">Rp ${formatNum(t.price,0)}</span>
          <span>${t.lots} lot</span>
        </div>
        <div style="color:var(--text-muted);font-size:10px;margin-top:2px">${t.timestamp?.substring(0,16)}</div>
      </div>`).join('');
  } catch(e) {}
}

// ─── Settings ─────────────────────────────────────────────────
async function loadAlertConfigToSettings() {
  const el = document.getElementById('alert-config-content');
  if (!el) return;
  try {
    const res  = await fetch(`${API}/alert/config`);
    const data = await res.json();
    if (!data.success) return;
    const cfg = data.config;
    el.innerHTML = `
      <div class="alert-config-panel">
        <div class="alert-toggle-row">
          <div>
            <div class="setting-label">Aktifkan Notifikasi Telegram</div>
            <div class="setting-desc">Kirim sinyal buy/sell ke Telegram bot kamu</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="tg-enabled" ${cfg.telegram_enabled?'checked':''} onchange="saveAlertToggle()"/>
            <span class="slider round"></span>
          </label>
        </div>
        <div class="alert-field">
          <label>Bot Token</label>
          <input type="text" id="tg-token" class="form-input" placeholder="1234567890:ABCdefGHI..."
            value="${cfg.telegram_bot_token_set ? '••••••••••••••••' : ''}" />
          <div class="setting-desc" style="margin-top:4px">Dapatkan dari <a href="https://t.me/BotFather" target="_blank">@BotFather</a> di Telegram</div>
        </div>
        <div class="alert-field">
          <label>Chat ID</label>
          <input type="text" id="tg-chatid" class="form-input" placeholder="-100123456789 atau @username"
            value="${cfg.telegram_chat_id||''}" />
          <div class="setting-desc" style="margin-top:4px">Kirim pesan ke bot, lalu cek: <code>api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code></div>
        </div>
        <div class="alert-field">
          <label>Nama Broker</label>
          <input type="text" id="tg-broker" class="form-input" placeholder="Mirae Asset" value="${cfg.broker_name||'Mirae Asset'}" />
        </div>
        <div class="alert-field">
          <label>Nama Aplikasi Broker</label>
          <input type="text" id="tg-app" class="form-input" placeholder="Neo HOTS" value="${cfg.broker_app_name||'Neo HOTS'}" />
        </div>
        <div class="alert-field" style="display:flex;gap:10px">
          <button class="btn-execute" style="flex:1" onclick="saveAlertConfig()">Simpan Konfigurasi</button>
          <button class="btn-neutral" style="flex:1" onclick="testAlertConfig()">Test Kirim</button>
        </div>
        <div id="alert-save-result" style="font-size:12px;margin-top:8px;color:var(--text-secondary)"></div>
      </div>`;
  } catch(e) {}
}

async function saveAlertToggle() {
  const enabled = document.getElementById('tg-enabled').checked;
  await fetch(`${API}/alert/config`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ telegram_enabled: enabled }),
  });
}

async function saveAlertConfig() {
  const token   = document.getElementById('tg-token')?.value.trim();
  const chatid  = document.getElementById('tg-chatid')?.value.trim();
  const broker  = document.getElementById('tg-broker')?.value.trim();
  const app     = document.getElementById('tg-app')?.value.trim();
  const enabled = document.getElementById('tg-enabled')?.checked;
  const result  = document.getElementById('alert-save-result');
  if (result) result.textContent = 'Menyimpan...';
  try {
    const payload = { telegram_enabled: enabled, broker_name: broker, broker_app_name: app };
    // Hanya kirim token jika bukan placeholder
    if (token && !token.includes('•')) payload.telegram_bot_token = token;
    if (chatid) payload.telegram_chat_id = chatid;
    const res  = await fetch(`${API}/alert/config`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (result) result.innerHTML = data.success
      ? '<span style="color:var(--green)">Konfigurasi disimpan</span>'
      : `<span style="color:var(--red)">Error: ${data.error}</span>`;
    ftLoadAlertStatus();
  } catch(e) {
    if (result) result.innerHTML = `<span style="color:var(--red)">Gagal: ${e.message}</span>`;
  }
}

async function testAlertConfig() {
  const result = document.getElementById('alert-save-result');
  if (result) result.textContent = 'Mengirim test...';
  try {
    const token  = document.getElementById('tg-token')?.value.trim();
    const chatid = document.getElementById('tg-chatid')?.value.trim();
    const payload = {};
    if (token && !token.includes('•')) payload.telegram_bot_token = token;
    if (chatid) payload.telegram_chat_id = chatid;
    const res  = await fetch(`${API}/alert/test`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (result) result.innerHTML = data.success
      ? '<span style="color:var(--green)">Pesan test berhasil dikirim! Cek Telegram kamu.</span>'
      : `<span style="color:var(--red)">Gagal: ${data.error}</span>`;
  } catch(e) {
    if (result) result.innerHTML = `<span style="color:var(--red)">Gagal: ${e.message}</span>`;
  }
}

async function checkServerHealth() {
  try {
    const res  = await fetch(`${API}/health`);
    const data = await res.json();
    document.getElementById('api-health').innerHTML =
      `<span style="color:var(--green)">Online</span> — v${data.version} | ${data.time?.substring(0,10)}`;
  } catch(e) {
    document.getElementById('api-health').innerHTML = `<span style="color:var(--red)">Offline — Jalankan: python server.py</span>`;
  }
}

function resetPortfolioConfirm() {
  showModal('Reset Portfolio',
    `<p>Apakah Anda yakin ingin mereset portfolio?</p>
     <p style="color:var(--red);margin-top:8px"><strong>Semua posisi dan riwayat transaksi akan dihapus!</strong></p>
     <p style="color:var(--text-muted);font-size:12px;margin-top:8px">Modal akan kembali ke Rp 100.000.000</p>`,
    async () => {
      try {
        const res  = await fetch(`${API}/portfolio/reset`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm: true }),
        });
        const data = await res.json();
        if (data.success) {
          showToast('Portfolio direset!', 'success');
          loadPortfolioStats(); loadPortfolioFull(); loadHistory();
        }
      } catch(e) { showToast('Gagal reset', 'error'); }
    },
    'Reset Portfolio', true
  );
}

// ─── Modal ────────────────────────────────────────────────────
function showModal(title, body, onConfirm, confirmText = 'Konfirmasi', isDanger = false) {
  document.getElementById('modal-header').textContent  = title;
  document.getElementById('modal-body').innerHTML      = body;
  document.getElementById('modal-overlay').classList.remove('hidden');
  const btn = document.getElementById('modal-confirm-btn');
  btn.textContent = confirmText;
  btn.className = `btn-confirm${isDanger ? ' danger' : ''}`;
  btn.onclick = () => { closeModal(); onConfirm(); };
}
function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

// ─── Toast ────────────────────────────────────────────────────
let toastTimer;
function showToast(msg, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className   = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 4000);
}

// ─── Helpers ──────────────────────────────────────────────────
function formatNum(n, decimals = 0) {
  if (!n || isNaN(n)) return '0';
  return Number(n).toLocaleString('id-ID', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function formatVolume(v) {
  if (!v) return '0';
  if (v >= 1e9) return (v/1e9).toFixed(1) + 'B';
  if (v >= 1e6) return (v/1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v/1e3).toFixed(1) + 'K';
  return String(v);
}

function formatCap(n) {
  if (!n) return 'N/A';
  if (n >= 1e15) return `Rp ${(n/1e15).toFixed(1)}Q`;
  if (n >= 1e12) return `Rp ${(n/1e12).toFixed(1)}T`;
  if (n >= 1e9)  return `Rp ${(n/1e9).toFixed(1)}B`;
  if (n >= 1e6)  return `Rp ${(n/1e6).toFixed(1)}M`;
  return `Rp ${formatNum(n,0)}`;
}

function scoreColor(s) {
  if (s >= 75) return 'var(--green)';
  if (s >= 60) return '#0ECB81';
  if (s >= 45) return 'var(--yellow)';
  if (s >= 30) return '#e58e26';
  return 'var(--red)';
}

function riskColor(r) {
  if (!r) return 'var(--text-muted)';
  if (r.includes('LOW'))  return 'var(--green)';
  if (r === 'MEDIUM')     return 'var(--yellow)';
  return 'var(--red)';
}

function overallSignal(s) {
  if (s >= 75) return 'STRONG BUY';
  if (s >= 60) return 'BUY';
  if (s >= 45) return 'HOLD';
  if (s >= 30) return 'SELL';
  return 'STRONG SELL';
}

function sentimentEmoji(s) {
  if (s === 'BULLISH') return '▲';
  if (s === 'BEARISH') return '▼';
  return '●';
}

function recColors(rec) {
  const map = {
    'STRONG BUY': ['#0ECB8110', '#0ECB81'],
    'BUY':        ['#0ECB8110', '#0ECB81'],
    'HOLD':       ['#F0B90B10', '#F0B90B'],
    'SELL':       ['#e58e2610', '#e58e26'],
    'STRONG SELL':['#F6465D10', '#F6465D'],
  };
  return map[rec] || ['#1e2d4710', '#1e2d47'];
}

function metricRow(label, value, scoreObj = null) {
  const color = scoreObj ? scoreColor(scoreObj.score || 50) : 'var(--text-primary)';
  const signal = scoreObj?.signal || '';
  return `
    <div class="metric-row">
      <span class="metric-name">${label}</span>
      <div style="display:flex;align-items:center;gap:8px">
        <span class="metric-val">${value}</span>
        ${signal ? `<span class="metric-signal-sm" style="color:${color};background:${color}18">${signal}</span>` : ''}
      </div>
    </div>`;
}

function indicatorBar(name, score, value, signal) {
  score = Math.max(0, Math.min(100, score || 50));
  const color = scoreColor(score);
  return `
    <div class="indicator-bar">
      <span class="ind-name">${name}</span>
      <div class="ind-bar-wrap">
        <div class="ind-bar-fill" style="width:${score}%;background:${color}"></div>
      </div>
      <span class="ind-value">${value}</span>
      <span class="ind-signal" style="color:${color}">${signal}</span>
    </div>`;
}

// ─── Auto Trading Actions ─────────────────────────────────────
async function loadAutoTradeStatus() {
  try {
    const res  = await fetch(`${API}/autotrade/status`);
    const data = await res.json();
    if (!data.success) return;

    const config = data.config;
    
    // Toggle switch
    const cb = document.getElementById('autotrade-toggle-checkbox');
    if (cb && cb.checked !== config.enabled) {
      cb.checked = config.enabled;
    }

    // Status Badge
    const badge = document.getElementById('engine-status-badge');
    if (badge) {
      if (data.is_scanning) {
        badge.className = 'engine-badge scanning';
        badge.textContent = 'SCANNING';
      } else if (config.enabled) {
        badge.className = 'engine-badge online';
        badge.textContent = 'ACTIVE';
      } else {
        badge.className = 'engine-badge offline';
        badge.textContent = 'OFFLINE';
      }
    }

    // Last Scan Time
    const lastScanEl = document.getElementById('engine-last-scan');
    if (lastScanEl) {
      if (data.last_scan_time) {
        const d = new Date(data.last_scan_time);
        lastScanEl.textContent = d.toLocaleTimeString('id-ID') + ' WIB';
      } else {
        lastScanEl.textContent = 'Belum pernah';
      }
    }

    // Set configuration input fields if they are not active/focused
    const intervalInp = document.getElementById('autotrade-interval');
    if (intervalInp && document.activeElement !== intervalInp) {
      intervalInp.value = config.interval_minutes;
    }
    const maxAllocInp = document.getElementById('autotrade-max-alloc');
    if (maxAllocInp && document.activeElement !== maxAllocInp) {
      maxAllocInp.value = config.max_allocation_pct;
    }
    const riskInp = document.getElementById('autotrade-risk');
    if (riskInp && document.activeElement !== riskInp) {
      riskInp.value = config.risk_per_trade_pct;
    }
    const minConfInp = document.getElementById('autotrade-min-conf');
    if (minConfInp && document.activeElement !== minConfInp) {
      minConfInp.value = config.min_confidence_pct;
    }
    const enableSlInp = document.getElementById('autotrade-enable-sl');
    if (enableSlInp) {
      enableSlInp.checked = config.enable_stop_loss_monitor !== false;
    }
    const trailingStopInp = document.getElementById('autotrade-trailing-stop');
    if (trailingStopInp && document.activeElement !== trailingStopInp) {
      trailingStopInp.value = config.trailing_stop_pct || 5.0;
    }

  } catch (e) {
    console.error('[autotrade status]', e);
  }
}

async function toggleAutoTrade() {
  const cb = document.getElementById('autotrade-toggle-checkbox');
  const enabled = cb ? cb.checked : false;
  try {
    const res = await fetch(`${API}/autotrade/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Auto Trading ${enabled ? 'diaktifkan' : 'dinonaktifkan'}`, 'info');
      loadAutoTradeStatus();
      setTimeout(loadAutoTradeLogs, 500);
    }
  } catch (e) {
    showToast('Gagal mengubah mode Auto-Trading', 'error');
  }
}

async function saveAutoTradeSettings() {
  const interval_minutes = parseInt(document.getElementById('autotrade-interval').value) || 10;
  const max_allocation_pct = parseFloat(document.getElementById('autotrade-max-alloc').value) || 20;
  const risk_per_trade_pct = parseFloat(document.getElementById('autotrade-risk').value) || 1.0;
  const min_confidence_pct = parseInt(document.getElementById('autotrade-min-conf').value) || 80;
  const enable_stop_loss_monitor = document.getElementById('autotrade-enable-sl').checked;
  const trailing_stop_pct = parseFloat(document.getElementById('autotrade-trailing-stop').value) || 5.0;

  try {
    const res = await fetch(`${API}/autotrade/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interval_minutes,
        max_allocation_pct,
        risk_per_trade_pct,
        min_confidence_pct,
        enable_stop_loss_monitor,
        trailing_stop_pct
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast('Konfigurasi auto-trading berhasil disimpan!', 'success');
      loadAutoTradeStatus();
    }
  } catch (e) {
    showToast('Gagal menyimpan konfigurasi', 'error');
  }
}

async function loadAutoTradeLogs() {
  const el = document.getElementById('console-logs');
  if (!el) return;
  try {
    const res = await fetch(`${API}/autotrade/logs`);
    const data = await res.json();
    if (!data.success || !data.data) return;

    if (data.data.length === 0) {
      el.innerHTML = `<div class="console-line system" style="color:var(--text-muted)">[SYSTEM] Console kosong. Menunggu log dari server...</div>`;
      return;
    }

    const html = data.data.map(log => {
      const typeClass = log.type.toLowerCase();
      const timeStr   = log.timestamp ? log.timestamp.substring(11, 19) : '';
      return `<div class="console-line ${typeClass}">[${timeStr}] [${log.type}] ${log.message}</div>`;
    }).join('');

    // Check if scrolled to bottom before updating
    const isAtBottom = el.scrollHeight - el.clientHeight <= el.scrollTop + 50;
    
    el.innerHTML = html;
    
    // Auto scroll to bottom
    if (isAtBottom) {
      el.scrollTop = el.scrollHeight;
    }
  } catch (e) {
    console.error('[autotrade logs]', e);
  }
}

async function clearConsoleLogs() {
  try {
    const res = await fetch(`${API}/autotrade/logs/clear`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      const el = document.getElementById('console-logs');
      if (el) el.innerHTML = `<div class="console-line system" style="color:var(--text-muted)">[SYSTEM] Log dihapus.</div>`;
      showToast('Log dibersihkan', 'info');
    }
  } catch (e) {}
}

async function triggerAutoScan() {
  const btn = document.getElementById('btn-trigger-scan');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API}/autotrade/trigger`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('Scan watchlist otomatis berhasil dipicu!', 'success');
      loadAutoTradeStatus();
      setTimeout(loadAutoTradeLogs, 500);
    } else {
      showToast(data.error || 'Gagal memicu scan', 'error');
    }
  } catch (e) {
    showToast('Gagal memicu scan', 'error');
  } finally {
    if (btn) {
      setTimeout(() => { btn.disabled = false; }, 3000);
    }
  }
}
