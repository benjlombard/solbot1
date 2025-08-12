(function () {
  console.log('🚀 [INIT] Dashboard script started, API_BASE:', API_BASE);

  const CONFIG = {
    refreshInterval: 15_000, // Réduit à 15 secondes pour plus de réactivité
    maxActivityItems: 20,
    maxWalletsDisplay: 10,
    debounceDelay: 250
  };

  let dashboardData = { recent_activity: [], wallets_overview: [] };
  let prevDataHash = { activities: new Map(), wallets: new Map() };
  let isUpdating = false;
  let abortController = null;
  let globalTimer = null;
  let autoRefresh = { activity: true, wallets: true }; // Activé par défaut

  const activityRows = new Map();
  const walletRows = new Map();

  function formatNumber(num, decimals = 6) {
    if (typeof num !== 'number' || isNaN(num)) return '0';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    if (num < 0.001 && num > 0) return num.toExponential(2);
    return Number(num.toFixed(decimals));
  }

  function formatTimeAgo(timestamp) {
    if (!timestamp) return 'Jamais';
    const diff = Date.now() / 1000 - timestamp;
    if (diff < 60) return `${Math.floor(diff)}s`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}j`;
  }

  function getPriorityCategory(score) {
    if (score >= 4.0) return 'high';
    if (score >= 2.0) return 'medium';
    return 'low';
  }

  function getWalletStatusClass(wallet) {
    if (!wallet?.seconds_since_scan) return 'error';
    if (wallet.seconds_since_scan <= 300) return '';
    if (wallet.seconds_since_scan <= 900) return 'warning';
    return 'error';
  }

  function getWalletStatusText(wallet) {
    const minutes = Math.floor((wallet.seconds_since_scan || 0) / 60);
    if (minutes < 5) return 'Récent';
    if (minutes < 30) return 'Normal';
    return 'En retard';
  }

  function showMessage(msg, type) {
    console.log(`${type.toUpperCase()}: ${msg}`);
    const toast = document.getElementById('transaction-toast');
    if (toast) {
      const toastMessage = toast.querySelector('.toast-message');
      const toastIcon = toast.querySelector('.toast-icon');
      toastMessage.textContent = msg;
      toastIcon.innerHTML = `<i class="fas fa-${type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>`;
      toast.classList.add('show', type);
      setTimeout(() => {
        toast.classList.remove('show', type);
      }, 3000);
    } else {
      console.warn('⚠️ [MESSAGE] Transaction toast element not found');
      alert(`${type.toUpperCase()}: ${msg}`);
    }
  }

  function idForActivity(a) {
    return `${a.wallet_address}|${a.token_mint}|${a.timestamp}`;
  }

  function idForWallet(w) {
    return w.wallet_address;
  }

  function debounce(fn, wait) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), wait);
    };
  }

  async function safeFetch(url, opts = {}) {
    console.log('🌐 [FETCH] Starting request to:', url);

    if (abortController) {
      console.warn('⚠️ [FETCH] Aborting previous fetch');
      abortController.abort();
    }
    abortController = new AbortController();
    opts.signal = abortController.signal;

    if (!opts.method) {
      opts.method = 'GET';
    }

    console.log('📤 [FETCH] Request details:', {
      url,
      method: opts.method,
      headers: opts.headers
    });

    try {
      const res = await fetch(url, opts);
      console.log('📥 [FETCH] Response received:', {
        status: res.status,
        statusText: res.statusText,
        ok: res.ok,
        headers: Object.fromEntries(res.headers.entries())
      });

      if (!res.ok) {
        const errorText = await res.text();
        console.error('❌ [FETCH] Error response body:', errorText);
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const json = await res.json();
      console.log('✅ [FETCH] JSON parsed successfully:', {
        success: json.success,
        dataKeys: Object.keys(json.data || {}),
        dataType: typeof json.data
      });

      return json;
    } catch (err) {
      if (err.name === 'AbortError') {
        console.warn('🛑 [FETCH] Fetch aborted:', url);
        throw err;
      }
      console.error('💥 [FETCH] Fetch error:', {
        error: err.message,
        stack: err.stack,
        url
      });
      throw err;
    } finally {
      abortController = null;
    }
  }

  async function loadDashboardData(btn = null) {
    if (isUpdating) {
      console.log('⏳ [LOAD] Update already running, skipping');
      return;
    }
    isUpdating = true;
    console.log('🔄 [LOAD] Starting dashboard data fetch...');
    if (btn) btn.classList.add('spinning');

    // Mettre à jour le timestamp de dernière mise à jour
    updateLastRefreshTime();

    try {
      const url = `${API_BASE}/dashboard/data`;
      console.log('🎯 [LOAD] Fetching from URL:', url);

      const json = await safeFetch(url, {
        method: 'GET',
        cache: 'no-cache', // Prevent browser caching
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        }
      });

      console.log('📊 [LOAD] Raw response structure:', {
        topLevelKeys: Object.keys(json),
        success: json.success,
        message: json.message,
        hasData: !!json.data,
        dataType: typeof json.data
      });

      let dataObj = json;
      if (dataObj.data && typeof dataObj.data === 'object') {
        console.log('🔧 [LOAD] Flattening: found data object');
        dataObj = dataObj.data;
      }
      if (dataObj.data && typeof dataObj.data === 'object') {
        console.log('🔧 [LOAD] Flattening: found nested data object');
        dataObj = dataObj.data;
      }

      console.log('📋 [LOAD] Final data structure:', {
        keys: Object.keys(dataObj),
        hasActivity: !!dataObj.recent_activity,
        hasWallets: !!dataObj.wallets_overview,
        activityLength: dataObj.recent_activity?.length || 0,
        walletsLength: dataObj.wallets_overview?.length || 0
      });

      dashboardData = dataObj;

      if (!dashboardData.recent_activity) {
        console.error('❌ [LOAD] Missing recent_activity in data');
        showErrorInTable('activity-table-body', 'Données d\'activité manquantes');
      }

      if (!dashboardData.wallets_overview) {
        console.error('❌ [LOAD] Missing wallets_overview in data');
        showErrorInTable('wallets-table-body', 'Données de wallets manquantes');
      }

      if (dashboardData.recent_activity && dashboardData.wallets_overview) {
        console.log('✅ [LOAD] Both datasets available, rendering...');
        applyDiffAndRender();
      } else {
        console.warn('⚠️ [LOAD] Missing data, showing partial results');
        applyDiffAndRender();
      }

      console.log(`✅ [LOAD] Render completed: ${dashboardData.recent_activity?.length || 0} activities, ${dashboardData.wallets_overview?.length || 0} wallets`);
      
      // Afficher un message de succès temporaire
      showMessage('Données mises à jour', 'success');
      
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('💥 [LOAD] Failed to load dashboard data:', {
          error: err.message,
          stack: err.stack
        });
        showErrorInTable('activity-table-body', `Erreur: ${err.message}`);
        showErrorInTable('wallets-table-body', `Erreur: ${err.message}`);
        showMessage(`Erreur de chargement: ${err.message}`, 'error');
      }
    } finally {
      isUpdating = false;
      if (btn) btn.classList.remove('spinning');
      console.log('🏁 [LOAD] Load process finished');
    }
  }

  function updateLastRefreshTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('fr-FR', { 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit' 
    });
    console.log(`🕒 [REFRESH] Last refresh: ${timeString}`);
    
    // Optionnel : mettre à jour un élément UI pour montrer l'heure de dernière MAJ
    const refreshButtons = document.querySelectorAll('.refresh-btn-modern');
    refreshButtons.forEach(btn => {
      btn.setAttribute('title', `Actualiser (dernière MAJ: ${timeString})`);
    });
  }

  function showErrorInTable(tableBodyId, message) {
    const tbody = document.getElementById(tableBodyId);
    if (tbody) {
      const colCount = tableBodyId === 'activity-table-body' ? 8 : 7;
      tbody.innerHTML = `<tr><td colspan="${colCount}" style="text-align:center;color:var(--error);padding:20px;">❌ ${message}</td></tr>`;
    }
  }

  function applyDiffAndRender() {
    console.log('🎨 [RENDER] Starting render process...');

    try {
      console.log('🎯 [RENDER] Updating activity table...');
      updateActivityDiff();
    } catch (e) {
      console.error('💥 [RENDER] Error in updateActivityDiff:', e);
    }

    try {
      console.log('🎯 [RENDER] Updating wallets table...');
      updateWalletsDiff();
    } catch (e) {
      console.error('💥 [RENDER] Error in updateWalletsDiff:', e);
    }

    console.log('✅ [RENDER] Render process completed');
  }

  function updateActivityDiff() {
    const list = (dashboardData.recent_activity || []);
    console.log(`📊 [ACTIVITY] Processing ${list.length} activities`);

    const newKeys = new Set();
    const tbody = document.getElementById('activity-table-body');
    if (!tbody) {
      console.error('❌ [ACTIVITY] Table body not found: activity-table-body');
      return;
    }

    if (!activityRows.size) {
      console.log('🧹 [ACTIVITY] Clearing table body');
      tbody.innerHTML = '';
    }

    if (list.length === 0) {
      console.log('📭 [ACTIVITY] No activities to display');
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:20px;">Aucune activité récente</td></tr>';
      return;
    }

    const fragment = document.createDocumentFragment();
    let processedCount = 0;

    for (const a of list.slice(0, CONFIG.maxActivityItems)) {
      try {
        const key = idForActivity(a);
        newKeys.add(key);

        let tr = activityRows.get(key);
        if (!tr) {
          tr = document.createElement('tr');
          tr.dataset.key = key;
          tr.innerHTML = `
            <td class="wallet-col"></td>
            <td class="token-col"></td>
            <td class="token-addr-col"></td>
            <td class="ata-col"></td>
            <td class="type-col"></td>
            <td class="amount-col"></td>
            <td class="links-col"></td>
            <td class="actions-col"></td>
          `;
          activityRows.set(key, tr);
          populateActivityRow(tr, a);
          fragment.appendChild(tr);
          processedCount++;
        } else {
          const prevHash = prevDataHash.activities.get(key);
          const curHash = `${a.sol_amount}|${a.usd_amount}|${a.transaction_type}`;
          if (prevHash !== curHash) {
            populateActivityRow(tr, a);
            processedCount++;
          }
        }
        prevDataHash.activities.set(key, `${a.sol_amount}|${a.usd_amount}|${a.transaction_type}`);
      } catch (e) {
        console.error('💥 [ACTIVITY] Error processing activity item:', e, a);
      }
    }

    // Nettoyer les anciennes entrées
    for (const [k, node] of activityRows) {
      if (!newKeys.has(k)) {
        node.remove();
        activityRows.delete(k);
        prevDataHash.activities.delete(k);
      }
    }

    if (fragment.childNodes.length) {
      tbody.appendChild(fragment);
    }

    console.log(`✅ [ACTIVITY] Processed ${processedCount} activities, ${fragment.childNodes.length} new rows`);
  }

  function populateActivityRow(tr, a) {
    if (!a.wallet_address || !a.token_mint || !a.transaction_type) {
      console.warn('⚠️ [ACTIVITY] Skipping invalid activity item:', a);
      return;
    }
    try {
      const walletShort = `${a.wallet_address?.slice(0, 4)}...${a.wallet_address?.slice(-4)}`;
      const tokenShort = `${a.token_mint?.slice(0, 4)}...${a.token_mint?.slice(-4)}`;

      tr.querySelector('.wallet-col').innerHTML = `
        <div class="address-container">
          <a href="https://solscan.io/account/${a.wallet_address}" target="_blank" title="${a.wallet_address}">${walletShort}</a>
          <button class="wallet-action-btn copy-btn" data-copy="${a.wallet_address}" title="Copy Address"><i class="far fa-copy"></i></button>
        </div>`;
      tr.querySelector('.token-col').textContent = a.token_symbol || 'UNKNOWN';
      tr.querySelector('.token-addr-col').innerHTML = `
        <div class="address-container">
          <span>${tokenShort}</span>
          <button class="wallet-action-btn copy-btn" data-copy="${a.token_mint}" title="Copy Token Address"><i class="far fa-copy"></i></button>
        </div>`;
      tr.querySelector('.ata-col').textContent = a.ata_pubkey ? `${a.ata_pubkey.slice(0, 4)}...${a.ata_pubkey.slice(-4)}` : 'N/A';
      tr.querySelector('.type-col').innerHTML = `<span class="type-${a.transaction_type}">${a.transaction_type}</span>
        <div style="font-size:11px;color:var(--text-muted)">${formatTimeAgo(a.timestamp)}</div>`;
      tr.querySelector('.amount-col').innerHTML = `<div class="amount-sol">${formatNumber(a.sol_amount || 0)} SOL</div>
        <div class="amount-usd">$${formatNumber(a.usd_amount || 0, 2)}</div>`;
      tr.querySelector('.links-col').innerHTML = `
        <div class="link-group">
          <a href="https://dexscreener.com/solana/${a.token_mint}" target="_blank" title="DexScreener">D</a>
          <a href="https://pump.fun/${a.token_mint}" target="_blank" title="Pump.fun">P</a>
          <a href="https://gmgn.ai/sol/${a.token_mint}" target="_blank" title="GMGN.ai">G</a>
        </div>`;
      tr.querySelector('.actions-col').innerHTML = `
        <div class="action-buttons">
          <button class="btn btn-sm btn-buy" data-buy="${a.token_mint}">💰</button>
          <button class="btn btn-sm btn-sell" data-sell="${a.token_mint}">💸</button>
        </div>`;
    } catch (e) {
      console.error('💥 [ACTIVITY] Error populating row:', e, a);
    }
  }

  function updateWalletsDiff() {
    const list = (dashboardData.wallets_overview || []);
    console.log(`👛 [WALLETS] Processing ${list.length} wallets`);

    const newKeys = new Set();
    const tbody = document.getElementById('wallets-table-body');
    if (!tbody) {
      console.error('❌ [WALLETS] Table body not found: wallets-table-body');
      return;
    }

    if (!walletRows.size) {
      console.log('🧹 [WALLETS] Clearing table body');
      tbody.innerHTML = '';
    }

    if (list.length === 0) {
      console.log('📭 [WALLETS] No wallets to display');
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:20px;">Aucun wallet surveillé</td></tr>';
      return;
    }

    const fragment = document.createDocumentFragment();
    let processedCount = 0;

    for (const w of list.slice(0, CONFIG.maxWalletsDisplay)) {
      try {
        const key = idForWallet(w);
        newKeys.add(key);

        let tr = walletRows.get(key);
        if (!tr) {
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
          processedCount++;
        } else {
          const prev = prevDataHash.wallets.get(key);
          const cur = `${w.priority_score}|${w.transactions_24h}|${w.sol_balance}`;
          if (prev !== cur) {
            populateWalletRow(tr, w);
            processedCount++;
          }
        }
        prevDataHash.wallets.set(key, `${w.priority_score}|${w.transactions_24h}|${w.sol_balance}`);
      } catch (e) {
        console.error('💥 [WALLETS] Error processing wallet item:', e, w);
      }
    }

    for (const [k, node] of walletRows) {
      if (!newKeys.has(k)) {
        node.remove();
        walletRows.delete(k);
        prevDataHash.wallets.delete(k);
      }
    }

    if (fragment.childNodes.length) {
      tbody.appendChild(fragment);
    }

    console.log(`✅ [WALLETS] Processed ${processedCount} wallets, ${fragment.childNodes.length} new rows`);
  }

  function populateWalletRow(tr, w) {
    if (!w.wallet_address) {
      console.warn('⚠️ [WALLETS] Skipping invalid wallet item:', w);
      return;
    }
    try {
      const address = w.wallet_address;
      const short = `${address?.slice(0, 6)}...${address?.slice(-6)}`;
      const statusClass = getWalletStatusClass(w);
      const priority = getPriorityCategory(w.priority_score);

      tr.querySelector('.wallet-col').innerHTML = `
        <div class="wallet-cell" data-address="${address}">
          <div class="wallet-avatar-small">${address?.slice(0, 2).toUpperCase()}</div>
          <div class="wallet-info-small">
            <div class="wallet-address-small" title="${address}">${short}</div>
            <div class="wallet-status-small"><div class="status-dot-tiny ${statusClass}"></div><span class="status-text">${getWalletStatusText(w)}</span></div>
          </div>
        </div>`;
      tr.querySelector('.priority-col').innerHTML = `<span class="priority-badge-small priority-${priority}-small">${priority.toUpperCase()}</span>`;
      tr.querySelector('.tokens-col').textContent = formatNumber(w.total_token_accounts || 0);
      tr.querySelector('.tx24-col').textContent = formatNumber(w.transactions_24h || 0);
      tr.querySelector('.balance-col').innerHTML = `<span class="balance-amount">${formatNumber(w.sol_balance || 0)} SOL</span>`;
      tr.querySelector('.lastscan-col').innerHTML = `<span class="scan-time">${formatTimeAgo(w.last_scan_time) || 'N/A'}</span>`;
      tr.querySelector('.actions-col').innerHTML = `<div class="wallet-actions">
          <button class="wallet-action-btn copy-btn" data-copy="${address}" title="Copy Address"><i class="far fa-copy"></i></button>
          <button class="wallet-action-btn view-btn" data-view="${address}" title="View Details"><i class="far fa-eye"></i></button>
        </div>`;
    } catch (e) {
      console.error('💥 [WALLETS] Error populating row:', e, w);
    }
  }

  function setupCopyButtonListeners() {
    console.log('🎯 [INIT] Setting up copy button listeners');
    document.addEventListener('click', (e) => {
      const button = e.target.closest('.wallet-action-btn.copy-btn');
      if (!button) return;

      const valueToCopy = button.getAttribute('data-copy');
      if (valueToCopy) {
        console.log('📋 [COPY] Copying address:', valueToCopy);
        
        // Correction de l'API clipboard
        navigator.clipboard.writeText(valueToCopy).then(() => {
          button.classList.add('copied');
          setTimeout(() => button.classList.remove('copied'), 1000);

          const toast = document.getElementById('transaction-toast');
          if (toast) {
            const toastMessage = toast.querySelector('.toast-message');
            const toastIcon = toast.querySelector('.toast-icon');
            toastMessage.textContent = 'Adresse copiée !';
            toastIcon.innerHTML = '<i class="fas fa-check"></i>';
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
          } else {
            console.warn('⚠️ [COPY] Transaction toast element not found');
          }
        }).catch(err => {
          console.error('💥 [COPY] Error copying address:', err);
          showMessage('Erreur lors de la copie de l\'adresse', 'error');
        });
      }
    });
  }

  // Fonctions publiques corrigées
  function refreshActivity() {
    console.log('🔄 [UI] Manual refresh triggered for Activity');
    // Trouver le bon bouton de refresh dans la section Activity
    const activitySection = document.querySelector('#activity-search').closest('.dashboard-section');
    const btn = activitySection.querySelector('.refresh-btn-modern');
    loadDashboardData(btn);
  }

  function toggleAutoRefresh(type) {
    console.log('🔄 [UI] Toggle auto-refresh for:', type);
    if (type === 'activity') {
      autoRefresh.activity = !autoRefresh.activity;
      updateAutoRefreshUI('activity', autoRefresh.activity);
    } else if (type === 'wallets') {
      autoRefresh.wallets = !autoRefresh.wallets;
      updateAutoRefreshUI('wallets', autoRefresh.wallets);
    }
  }

  function updateAutoRefreshUI(type, isActive) {
    const control = document.getElementById(`auto-refresh-${type}`);
    if (control) {
      const dot = control.querySelector('.status-dot');
      const text = control.querySelector('.auto-refresh-text');
      
      if (isActive) {
        control.classList.add('active');
        dot.style.backgroundColor = '#10b981'; // vert
        text.textContent = 'Auto ON';
      } else {
        control.classList.remove('active');
        dot.style.backgroundColor = '#6b7280'; // gris
        text.textContent = 'Auto OFF';
      }
    }
  }

  function startScheduler() {
    console.log('⏰ [SCHEDULER] Starting scheduler...');
    if (globalTimer) {
      clearInterval(globalTimer);
      console.log('⏰ [SCHEDULER] Cleared existing timer');
    }

    // Initialiser l'UI des auto-refresh
    updateAutoRefreshUI('activity', autoRefresh.activity);
    updateAutoRefreshUI('wallets', autoRefresh.wallets);

    globalTimer = setInterval(() => {
      if (autoRefresh.activity || autoRefresh.wallets) {
        console.log('⏰ [SCHEDULER] Auto-refresh triggered');
        loadDashboardData();
      }
    }, CONFIG.refreshInterval);

    console.log('⏰ [SCHEDULER] Timer set, triggering first load...');
    loadDashboardData();
  }

  function testDOM() {
    console.log('🧪 [TEST] Testing DOM elements...');
    const activityTable = document.getElementById('activity-table-body');
    const walletsTable = document.getElementById('wallets-table-body');

    console.log('🧪 [TEST] Activity table found:', !!activityTable);
    console.log('🧪 [TEST] Wallets table found:', !!walletsTable);

    if (activityTable) {
      console.log('🧪 [TEST] Activity table HTML:', activityTable.outerHTML.substring(0, 100));
    }
    if (walletsTable) {
      console.log('🧪 [TEST] Wallets table HTML:', walletsTable.outerHTML.substring(0, 100));
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    console.log('🎯 [INIT] DOM Content Loaded');
    testDOM();
    setupCopyButtonListeners();
    console.log('🎯 [INIT] Starting scheduler...');
    startScheduler();
  });

  window.onerror = function (message, source, lineno, colno, error) {
    console.error('💥 [GLOBAL ERROR] Uncaught error:', {
      message,
      source,
      lineno,
      colno,
      error: error && error.stack ? error.stack : error
    });
  };

  window.addEventListener('unhandledrejection', function (event) {
    console.error('💥 [GLOBAL ERROR] Unhandled promise rejection:', {
      reason: event.reason,
      stack: event.reason && event.reason.stack ? event.reason.stack : undefined
    });
  });

  // API publique
  window.dashboard = {
    refreshActivity,
    toggleAutoRefresh,
    loadDashboardData: () => loadDashboardData(),
    getConfig: () => CONFIG,
    getAutoRefreshStatus: () => autoRefresh,
    forceRefresh: () => {
      console.log('🔥 [FORCE] Force refresh triggered');
      loadDashboardData();
    }
  };
})();