// dashboard_refactor.js
// Version avec flatten auto et logs détaillés

const API_BASE = window.location.origin + '/api';
const CONFIG = {
  refreshInterval: 45_000,
  autoRefreshInterval: 30_000,
  maxActivityItems: 20,
  maxWalletsDisplay: 10,
  debounceDelay: 250
};

let dashboardData = { recent_activity: [], wallets_overview: [] };
let prevDataHash = { activities: new Map(), wallets: new Map() };
let isUpdating = false;
let abortController = null;
let globalTimer = null;
let autoRefresh = { activity: false, wallets: false };

const activityRows = new Map();
const walletRows = new Map();

function idForActivity(a){ return `${a.wallet_address}|${a.token_mint}|${a.timestamp}`; }
function idForWallet(w){ return w.wallet_address; }

function debounce(fn, wait){
  let t; return (...args)=>{ clearTimeout(t); t = setTimeout(()=>fn(...args), wait); };
}

async function safeFetch(url, opts = {}){
  if (abortController) {
    console.warn('[safeFetch] Aborting previous fetch');
    abortController.abort();
  }
  abortController = new AbortController();
  opts.signal = abortController.signal;
  try{
    console.log('[safeFetch] Fetching:', url);
    const res = await fetch(url, opts);
    console.log('[safeFetch] Status:', res.status);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    console.log('[safeFetch] JSON received:', json);
    return json;
  } catch (err){
    if (err.name === 'AbortError') {
      console.warn('[safeFetch] Fetch aborted:', url);
      throw err;
    }
    console.error('[safeFetch] Fetch error', err);
    throw err;
  } finally {
    abortController = null;
  }
}

async function loadDashboardData(){
  if (isUpdating) {
    console.log('[loadDashboardData] Update already running, skipping');
    return;
  }
  isUpdating = true;
  console.log('[loadDashboardData] Starting fetch...');

  try {
    const json = await safeFetch(`${API_BASE}/dashboard/data`);

    // Flatten automatique
    let dataObj = json;
    if (dataObj.data && typeof dataObj.data === 'object') {
      dataObj = dataObj.data;
    }
    if (dataObj.data && typeof dataObj.data === 'object') {
      // Cas API avec double "data"
      dataObj = dataObj.data;
    }

    dashboardData = dataObj;
    console.log('[loadDashboardData] Dashboard data flattened:', dashboardData);

    if (!dashboardData.recent_activity || !dashboardData.wallets_overview) {
      console.warn('[loadDashboardData] Missing expected keys in dashboardData');
    }

    applyDiffAndRender();
    console.log(`[loadDashboardData] Render completed (${dashboardData.recent_activity?.length || 0} activities, ${dashboardData.wallets_overview?.length || 0} wallets)`);

  } catch (err) {
    if (err.name !== 'AbortError') {
      console.error('[loadDashboardData] Failed to load dashboard data', err);
    }
  } finally {
    isUpdating = false;
    console.log('[loadDashboardData] Finished');
  }
}

function applyDiffAndRender(){
  console.log('[applyDiffAndRender] Updating activity table...');
  try { updateActivityDiff(); } catch (e) {
    console.error('[applyDiffAndRender] Error in updateActivityDiff', e);
  }
  console.log('[applyDiffAndRender] Updating wallets table...');
  try { updateWalletsDiff(); } catch (e) {
    console.error('[applyDiffAndRender] Error in updateWalletsDiff', e);
  }
}

function updateActivityDiff(){
  const list = (dashboardData.recent_activity || []);
  console.log('[updateActivityDiff] Received list length:', list.length);
  const newKeys = new Set();
  const tbody = document.getElementById('activity-table-body');
  if (!tbody) { console.warn('[updateActivityDiff] No tbody found'); return; }

  if (!activityRows.size) tbody.innerHTML = '';

  const fragment = document.createDocumentFragment();
  for (const a of list.slice(0, CONFIG.maxActivityItems)){
    const key = idForActivity(a);
    newKeys.add(key);

    let tr = activityRows.get(key);
    if (!tr){
      tr = document.createElement('tr');
      tr.dataset.key = key;
      tr.innerHTML = `
        <td class="wallet-col"></td>
        <td class="token-col"></td>
        <td class="token-addr-col"></td>
        <td class="ata-col"></td>
        <td class="type-col"></td>
        <td class="amount-col"></td>
        <td class="actions-col"></td>
      `;
      activityRows.set(key, tr);
      populateActivityRow(tr, a);
      fragment.appendChild(tr);
    } else {
      const prevHash = prevDataHash.activities.get(key);
      const curHash = `${a.sol_amount}|${a.usd_amount}|${a.transaction_type}`;
      if (prevHash !== curHash){
        populateActivityRow(tr, a);
      }
    }
    prevDataHash.activities.set(key, `${a.sol_amount}|${a.usd_amount}|${a.transaction_type}`);
  }

  for (const [k, node] of activityRows){
    if (!newKeys.has(k)){
      node.remove();
      activityRows.delete(k);
      prevDataHash.activities.delete(k);
    }
  }

  if (fragment.childNodes.length) tbody.append(fragment);
}

function populateActivityRow(tr, a){
  try {
    const walletShort = `${a.wallet_address?.slice(0,4)}...${a.wallet_address?.slice(-4)}`;
    const tokenShort = `${a.token_mint?.slice(0,4)}...${a.token_mint?.slice(-4)}`;
    tr.querySelector('.wallet-col').innerHTML = `
      <div class="address-container">
        <a href="https://solscan.io/account/${a.wallet_address}" target="_blank" title="${a.wallet_address}">${walletShort}</a>
        <button class="copy-btn-small" data-copy="${a.wallet_address}">📋</button>
      </div>`;
    tr.querySelector('.token-col').textContent = a.token_symbol || 'UNKNOWN';
    tr.querySelector('.token-addr-col').innerHTML = `
      <div class="address-container">
        <span>${tokenShort}</span>
        <button class="copy-btn-small" data-copy="${a.token_mint}">📋</button>
      </div>`;
    tr.querySelector('.ata-col').textContent = a.ata_pubkey ? `${a.ata_pubkey.slice(0,4)}...${a.ata_pubkey.slice(-4)}` : 'N/A';
    tr.querySelector('.type-col').innerHTML = `<span class="type-${a.transaction_type}">${a.transaction_type}</span>
      <div style="font-size:11px;color:var(--text-muted)">${formatTimeAgo(a.timestamp)}</div>`;
    tr.querySelector('.amount-col').innerHTML = `<div class="amount-sol">${formatNumber(a.sol_amount||0)} SOL</div>
      <div class="amount-usd">$${formatNumber(a.usd_amount||0,2)}</div>`;
    tr.querySelector('.actions-col').innerHTML = `
      <div class="action-buttons">
        <button class="btn btn-sm btn-buy" data-buy="${a.token_mint}">💰</button>
        <button class="btn btn-sm btn-sell" data-sell="${a.token_mint}">💸</button>
      </div>`;
  } catch (e) {
    console.error('[populateActivityRow] Error', e, a);
  }
}

function updateWalletsDiff(){
  const list = (dashboardData.wallets_overview || []);
  console.log('[updateWalletsDiff] Received list length:', list.length);
  const newKeys = new Set();
  const tbody = document.getElementById('wallets-table-body');
  if (!tbody) { console.warn('[updateWalletsDiff] No tbody found'); return; }

  if (!walletRows.size) tbody.innerHTML = '';

  const fragment = document.createDocumentFragment();
  for (const w of list.slice(0, CONFIG.maxWalletsDisplay)){
    const key = idForWallet(w);
    newKeys.add(key);

    let tr = walletRows.get(key);
    if (!tr){
      tr = document.createElement('tr');
      tr.dataset.key = key;
      tr.innerHTML = `
        <td class="wallet-col"></td>
        <td class="priority-col"></td>
        <td class="tokens-col"></td>
        <td class="tx24-col"></td>
        <td class="balance-col"></td>
        <td class="lastscan-col"></td>
        <td class="actions-col"></td>
      `;
      walletRows.set(key, tr);
      populateWalletRow(tr, w);
      fragment.appendChild(tr);
    } else {
      const prev = prevDataHash.wallets.get(key);
      const cur = `${w.priority_score}|${w.transactions_24h}|${w.sol_balance}`;
      if (prev !== cur){
        populateWalletRow(tr, w);
      }
    }
    prevDataHash.wallets.set(key, `${w.priority_score}|${w.transactions_24h}|${w.sol_balance}`);
  }

  for (const [k, node] of walletRows){
    if (!newKeys.has(k)){
      node.remove();
      walletRows.delete(k);
      prevDataHash.wallets.delete(k);
    }
  }

  if (fragment.childNodes.length) tbody.append(fragment);
}

function populateWalletRow(tr, w){
  try {
    const address = w.wallet_address;
    const short = `${address?.slice(0,6)}...${address?.slice(-6)}`;
    const statusClass = getWalletStatusClass(w);
    const priority = getPriorityCategory(w.priority_score);

    tr.querySelector('.wallet-col').innerHTML = `
      <div class="wallet-cell" data-address="${address}">
        <div class="wallet-avatar-small">${address?.slice(0,2).toUpperCase()}</div>
        <div class="wallet-info-small">
          <div class="wallet-address-small" title="${address}">${short}</div>
          <div class="wallet-status-small"><div class="status-dot-tiny ${statusClass}"></div><span class="status-text">${getWalletStatusText(w)}</span></div>
        </div>
      </div>`;
    tr.querySelector('.priority-col').innerHTML = `<span class="priority-badge-small priority-${priority}-small">${priority.toUpperCase()}</span>`;
    tr.querySelector('.tokens-col').textContent = formatNumber(w.total_token_accounts||0);
    tr.querySelector('.tx24-col').textContent = formatNumber(w.transactions_24h||0);
    tr.querySelector('.balance-col').innerHTML = `<span class="balance-amount">${formatNumber(w.sol_balance||0)} SOL</span>`;
    tr.querySelector('.lastscan-col').innerHTML = `<span class="scan-time">${formatTimeAgo(w.last_scan_time) || 'N/A'}</span>`;
    tr.querySelector('.actions-col').innerHTML = `<div class="wallet-actions">
        <button class="wallet-action-btn copy-btn" data-address="${address}">📋</button>
        <button class="wallet-action-btn view-btn" data-view="${address}">👁️</button>
      </div>`;
  } catch (e) {
    console.error('[populateWalletRow] Error', e, w);
  }
}

// --- Scheduler
function startScheduler(){
  if (globalTimer) clearInterval(globalTimer);
  globalTimer = setInterval(() => {
    if (!autoRefresh.activity && !autoRefresh.wallets){
      loadDashboardData();
    }
  }, CONFIG.refreshInterval);
  loadDashboardData();
}

document.addEventListener('DOMContentLoaded', ()=>{
  console.log('[DOMContentLoaded] Starting scheduler');
  startScheduler();
});
