let data = [], filteredData = [], currentPage = 1, perPage = 10;
let refreshInterval = 30000;
let refreshTimer = null;
let isAutoRefreshEnabled = true;
let currentTab = 'base';

// === GESTION DES ONGLETS ===
function switchTab(tabName, button) {
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.remove('active');
  });
  
  document.querySelectorAll('.tab').forEach(tab => {
    tab.classList.remove('active');
  });
  
  document.getElementById(tabName + '-content').classList.add('active');
  button.classList.add('active');
  
  currentTab = tabName;
  renderPage();
}

// === FONCTIONS UTILITAIRES ===
function parseDateTime(dateString) {
  if (!dateString) return null;
  
  if (dateString.includes('T') || dateString.includes('Z')) {
    return new Date(dateString);
  } else {
    return new Date(dateString.replace(' ', 'T'));
  }
}

function formatLocalDateTime(dateString) {
  if (!dateString) return 'Inconnue';
  
  const date = parseDateTime(dateString);
  if (!date || isNaN(date.getTime())) return 'Invalide';
  
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function getTimeAgo(dateString) {
  if (!dateString) return { text: 'Inconnue', className: 'updated-old' };
  
  const now = new Date();
  const updateTime = parseDateTime(dateString);
  
  if (!updateTime || isNaN(updateTime.getTime())) {
    return { text: 'Invalide', className: 'updated-old' };
  }
  
  const diffMs = now - updateTime;
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  
  let text, className;
  
  if (diffMinutes < 1) {
    text = 'À l\'instant';
    className = 'updated-recent';
  } else if (diffMinutes < 60) {
    text = `${diffMinutes}min`;
    className = diffMinutes < 30 ? 'updated-recent' : 'updated-medium';
  } else if (diffHours < 24) {
    text = `${diffHours}h`;
    className = diffHours < 6 ? 'updated-medium' : 'updated-old';
  } else {
    text = `${diffDays}j`;
    className = 'updated-old';
  }
  
  return { text, className };
}

function formatPriceChange(value) {
  if (!value || value === 0) return { text: '0.00%', className: 'price-neutral' };
  
  const percentage = parseFloat(value).toFixed(2);
  const className = value > 0 ? 'price-positive' : 'price-negative';
  const prefix = value > 0 ? '+' : '';
  
  return { text: `${prefix}${percentage}%`, className };
}

// === FONCTIONS AUTO-REFRESH ===
function toggleAutoRefresh() {
    isAutoRefreshEnabled = !isAutoRefreshEnabled;
    const toggle = document.getElementById('autoRefreshToggle');
    const indicator = document.getElementById('refreshIndicator');
    
    if (isAutoRefreshEnabled) {
        toggle.classList.add('active');
        indicator.classList.remove('paused');
        indicator.classList.add('active');
        startAutoRefresh();
    } else {
        toggle.classList.remove('active');
        indicator.classList.remove('active');
        indicator.classList.add('paused');
        stopAutoRefresh();
    }
    
    updateRefreshStatus();
}

function updateRefreshInterval() {
    const select = document.getElementById('refreshInterval');
    refreshInterval = parseInt(select.value);
    
    if (isAutoRefreshEnabled) {
        stopAutoRefresh();
        startAutoRefresh();
    }
    
    updateRefreshStatus();
}

function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    
    if (isAutoRefreshEnabled) {
        refreshTimer = setInterval(() => {
            fetchData();
        }, refreshInterval);
    }
}

function stopAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
    }
}

function updateRefreshStatus() {
    const statusElement = document.getElementById('refreshStatus');
    const intervalText = refreshInterval >= 60000 ? 
        `${refreshInterval/60000}min` : 
        `${refreshInterval/1000}s`;
    
    if (isAutoRefreshEnabled) {
        statusElement.textContent = `Auto-refresh: ${intervalText}`;
    } else {
        statusElement.textContent = `Paused (${intervalText})`;
    }
}

function showRefreshIndicator(active) {
    const indicator = document.getElementById('refreshIndicator');
    if (!indicator) return;
    
    if (active && isAutoRefreshEnabled) {
        indicator.innerHTML = `
            <div class="spinner"></div>
            <span>Actualisation...</span>
        `;
    } else {
        const intervalText = refreshInterval >= 60000 ? 
            `${refreshInterval/60000}min` : 
            `${refreshInterval/1000}s`;
        
        const statusText = isAutoRefreshEnabled ? 
            `Auto-refresh: ${intervalText}` : 
            `Paused (${intervalText})`;
            
        indicator.innerHTML = `
            <span>${isAutoRefreshEnabled ? '🔄' : '⏸️'}</span>
            <span>${statusText}</span>
        `;
    }
}

// === FONCTIONS PROGRESSION BONDING CURVE ===
function getBondingProgressDisplay(status, progress) {
    if (!status || !['active', 'created'].includes(status.toLowerCase())) {
        return '<div class="no-progress">N/A</div>';
    }
    
    const progressValue = parseFloat(progress) || 0;
    
    if (progressValue <= 0) {
        return '<div class="no-progress">0%</div>';
    }
    
    let progressClass = '';
    if (progressValue >= 90) {
        progressClass = 'completed';
    } else if (progressValue < 30) {
        progressClass = 'low';
    }
    
    return `
        <div class="progress-container ${progressClass}" title="Progression: ${progressValue}%">
            <div class="progress-bar" style="width: ${Math.min(progressValue, 100)}%"></div>
            <div class="progress-text">${progressValue}%</div>
        </div>
    `;
}

function getBondingCurveDisplay(status) {
    if (!status) return '<span class="bonding-status bonding-unknown">Unknown</span>';
    
    const statusLower = String(status).toLowerCase().trim();
    const statusMap = {
        'created': '<span class="bonding-status bonding-created">Created</span>',
        'active': '<span class="bonding-status bonding-active">Active</span>',
        'completed': '<span class="bonding-status bonding-completed">Completed</span>',
        'migrated': '<span class="bonding-status bonding-migrated">Migrated</span>',
        'terminated': '<span class="bonding-status bonding-terminated">Terminated</span>'
    };
    
    return statusMap[statusLower] || 
           `<span class="bonding-status bonding-unknown">${status}</span>`;
}

// === FONCTIONS DE DONNÉES ===
async function fetchData() {
  if (!isAutoRefreshEnabled) {
    return;
  }
  
  showRefreshIndicator(true);
  try {
    const response = await fetch('/api/tokens-detail');
    if (!response.ok) throw new Error('Réponse API invalide');
    data = await response.json();
    filteredData = [...data];
    currentPage = 1;
    renderPage();
    
    if (currentTab === 'analysis') {
      updateAnalysis();
    }
  } catch (error) {
    console.error('Erreur lors du chargement des données:', error);
    const tbody = document.getElementById('baseTbody');
    if (tbody) {
      tbody.innerHTML = '<tr><td colspan="13">Erreur lors du chargement des données</td></tr>';
    }
  } finally {
    showRefreshIndicator(false);
  }
}

function isWithinTimeFilter(dateString, filterValue, filterUnit) {
  if (!dateString || !filterValue || !filterUnit) return true;
  
  const now = new Date();
  const updateTime = parseDateTime(dateString);
  
  if (!updateTime || isNaN(updateTime.getTime())) return false;
  
  const diffMs = now - updateTime;
  
  let thresholdMs;
  switch (filterUnit) {
    case 'minutes':
      thresholdMs = filterValue * 60 * 1000;
      break;
    case 'hours':
      thresholdMs = filterValue * 60 * 60 * 1000;
      break;
    case 'days':
      thresholdMs = filterValue * 24 * 60 * 60 * 1000;
      break;
    default:
      return true;
  }
  
  return diffMs <= thresholdMs;
}

// === FONCTIONS DE FILTRAGE ===
function setTimeFilter(value, unit, btn) {
  document.getElementById('filterTimeValue').value = value;
  document.getElementById('filterTimeUnit').value = unit;
  
  document.querySelectorAll('#base-content .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}

function clearTimeFilter(btn) {
  document.getElementById('filterTimeValue').value = '';
  document.getElementById('filterTimeUnit').value = '';
  
  document.querySelectorAll('#base-content .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}

function setDexTimeFilter(value, unit, btn) {
  window.dexTimeValue = value;
  window.dexTimeUnit = unit;
  document.querySelectorAll('#dexscreener-content .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyDexFilters();
}

function clearDexTimeFilter(btn) {
  window.dexTimeValue = null;
  window.dexTimeUnit = null;
  document.querySelectorAll('#dexscreener-content .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyDexFilters();
}

function applyFilters() {
  const filters = {
    symbol: document.getElementById('filterSymbol').value.toLowerCase().trim(),
    bondingStatus: document.getElementById('filterBondingStatus').value.toLowerCase().trim(),
    progressMin: document.getElementById('filterProgressMin').value ? parseFloat(document.getElementById('filterProgressMin').value) : null,
    progressMax: document.getElementById('filterProgressMax').value ? parseFloat(document.getElementById('filterProgressMax').value) : null,
    priceMin: document.getElementById('filterPriceMin').value ? parseFloat(document.getElementById('filterPriceMin').value) : null,
    priceMax: document.getElementById('filterPriceMax').value ? parseFloat(document.getElementById('filterPriceMax').value) : null,
    scoreMin: document.getElementById('filterScoreMin').value ? parseFloat(document.getElementById('filterScoreMin').value) : null,
    scoreMax: document.getElementById('filterScoreMax').value ? parseFloat(document.getElementById('filterScoreMax').value) : null,
    liquidityMin: document.getElementById('filterLiquidityMin').value ? parseFloat(document.getElementById('filterLiquidityMin').value) : null,
    liquidityMax: document.getElementById('filterLiquidityMax').value ? parseFloat(document.getElementById('filterLiquidityMax').value) : null,
    volumeMin: document.getElementById('filterVolumeMin').value ? parseFloat(document.getElementById('filterVolumeMin').value) : null,
    volumeMax: document.getElementById('filterVolumeMax').value ? parseFloat(document.getElementById('filterVolumeMax').value) : null,
    holdersMin: document.getElementById('filterHoldersMin').value ? parseInt(document.getElementById('filterHoldersMin').value) : null,
    holdersMax: document.getElementById('filterHoldersMax').value ? parseInt(document.getElementById('filterHoldersMax').value) : null,
    ageMin: document.getElementById('filterAgeMin').value ? parseFloat(document.getElementById('filterAgeMin').value) : null,
    ageMax: document.getElementById('filterAgeMax').value ? parseFloat(document.getElementById('filterAgeMax').value) : null,
    riskMin: document.getElementById('filterRiskMin').value ? parseInt(document.getElementById('filterRiskMin').value) : null,
    riskMax: document.getElementById('filterRiskMax').value ? parseInt(document.getElementById('filterRiskMax').value) : null,
    discoveredAt: document.getElementById('filterDiscoveredAt').value,
    timeValue: document.getElementById('filterTimeValue').value ? parseInt(document.getElementById('filterTimeValue').value) : null,
    timeUnit: document.getElementById('filterTimeUnit').value
  };

  filteredData = data.filter(row => {
    const riskValue = 100 - (row.rug_score || 50);
    const updatedAt = row.updated_at || row.first_discovered_at;
    const rowBondingStatus = (row.bonding_curve_status || '').toLowerCase();
    const progressValue = parseFloat(row.bonding_curve_progress) || 0;
    
    return (
      (!filters.symbol || row.symbol.toLowerCase().includes(filters.symbol)) &&
      (!filters.bondingStatus || rowBondingStatus === filters.bondingStatus) &&
      (filters.progressMin === null || progressValue >= filters.progressMin) &&
      (filters.progressMax === null || progressValue <= filters.progressMax) &&
      (filters.priceMin === null || row.price_usdc >= filters.priceMin) &&
      (filters.priceMax === null || row.price_usdc <= filters.priceMax) &&
      (filters.scoreMin === null || row.invest_score >= filters.scoreMin) &&
      (filters.scoreMax === null || row.invest_score <= filters.scoreMax) &&
      (filters.liquidityMin === null || row.liquidity_usd >= filters.liquidityMin) &&
      (filters.liquidityMax === null || row.liquidity_usd <= filters.liquidityMax) &&
      (filters.volumeMin === null || row.volume_24h >= filters.volumeMin) &&
      (filters.volumeMax === null || row.volume_24h <= filters.volumeMax) &&
      (filters.holdersMin === null || row.holders >= filters.holdersMin) &&
      (filters.holdersMax === null || row.holders <= filters.holdersMax) &&
      (filters.ageMin === null || row.age_hours >= filters.ageMin) &&
      (filters.ageMax === null || row.age_hours <= filters.ageMax) &&
      (filters.riskMin === null || riskValue >= filters.riskMin) &&
      (filters.riskMax === null || riskValue <= filters.riskMax) &&
      (!filters.discoveredAt || new Date(row.first_discovered_at).toISOString().startsWith(filters.discoveredAt)) &&
      isWithinTimeFilter(updatedAt, filters.timeValue, filters.timeUnit)
    );
  });

  highlightActiveFilters();
  currentPage = 1;
  renderPage();
}

function applyDexFilters() {
  const dexFilters = {
    symbol: document.getElementById('dexFilterSymbol').value.toLowerCase().trim(),
    status: document.getElementById('dexFilterStatus').value.toLowerCase().trim(),
    priceMin: document.getElementById('dexFilterPriceMin').value ? parseFloat(document.getElementById('dexFilterPriceMin').value) : null,
    priceMax: document.getElementById('dexFilterPriceMax').value ? parseFloat(document.getElementById('dexFilterPriceMax').value) : null,
    marketCapMin: document.getElementById('dexFilterMarketCapMin').value ? parseFloat(document.getElementById('dexFilterMarketCapMin').value) : null,
    marketCapMax: document.getElementById('dexFilterMarketCapMax').value ? parseFloat(document.getElementById('dexFilterMarketCapMax').value) : null,
    volume1hMin: document.getElementById('dexFilterVolume1hMin').value ? parseFloat(document.getElementById('dexFilterVolume1hMin').value) : null,
    volume6hMin: document.getElementById('dexFilterVolume6hMin').value ? parseFloat(document.getElementById('dexFilterVolume6hMin').value) : null,
    volume24hMin: document.getElementById('dexFilterVolume24hMin').value ? parseFloat(document.getElementById('dexFilterVolume24hMin').value) : null,
    txns24hMin: document.getElementById('dexFilterTxns24hMin').value ? parseFloat(document.getElementById('dexFilterTxns24hMin').value) : null,
    buys24hMin: document.getElementById('dexFilterBuys24hMin').value ? parseFloat(document.getElementById('dexFilterBuys24hMin').value) : null,
    sells24hMax: document.getElementById('dexFilterSells24hMax').value ? parseFloat(document.getElementById('dexFilterSells24hMax').value) : null,
    liquidityQuoteMin: document.getElementById('dexFilterLiquidityQuoteMin').value ? parseFloat(document.getElementById('dexFilterLiquidityQuoteMin').value) : null,
    hasData: document.getElementById('dexFilterHasData').value
  };

  filteredData = data.filter(row => {
    const hasDexData = (row.dexscreener_price_usd || 0) > 0;
    const lastDexUpdate = row.last_dexscreener_update || row.updated_at;
    
    return (
      (!dexFilters.symbol || row.symbol.toLowerCase().includes(dexFilters.symbol)) &&
      (!dexFilters.status || row.status.toLowerCase() === dexFilters.status) &&
      (dexFilters.priceMin === null || (row.dexscreener_price_usd || 0) >= dexFilters.priceMin) &&
      (dexFilters.priceMax === null || (row.dexscreener_price_usd || 0) <= dexFilters.priceMax) &&
      (dexFilters.marketCapMin === null || (row.dexscreener_market_cap || 0) >= dexFilters.marketCapMin) &&
      (dexFilters.marketCapMax === null || (row.dexscreener_market_cap || 0) <= dexFilters.marketCapMax) &&
      (dexFilters.volume1hMin === null || (row.dexscreener_volume_1h || 0) >= dexFilters.volume1hMin) &&
      (dexFilters.volume6hMin === null || (row.dexscreener_volume_6h || 0) >= dexFilters.volume6hMin) &&
      (dexFilters.volume24hMin === null || (row.dexscreener_volume_24h || 0) >= dexFilters.volume24hMin) &&
      (dexFilters.txns24hMin === null || (row.dexscreener_txns_24h || 0) >= dexFilters.txns24hMin) &&
      (dexFilters.buys24hMin === null || (row.dexscreener_buys_24h || 0) >= dexFilters.buys24hMin) &&
      (dexFilters.sells24hMax === null || (row.dexscreener_sells_24h || 0) <= dexFilters.sells24hMax) &&
      (dexFilters.liquidityQuoteMin === null || (row.dexscreener_liquidity_quote || 0) >= dexFilters.liquidityQuoteMin) &&
      (!dexFilters.hasData || (dexFilters.hasData === 'true' ? hasDexData : !hasDexData)) &&
      (!window.dexTimeValue || !window.dexTimeUnit || isWithinTimeFilter(lastDexUpdate, window.dexTimeValue, window.dexTimeUnit))
    );
  });

  highlightActiveFilters();
  currentPage = 1;
  renderPage();
}

// === FONCTIONS D'AFFICHAGE ===
function renderPage() {
  const start = (currentPage - 1) * perPage;
  const rows = filteredData.slice(start, start + perPage);
  
  if (currentTab === 'base') {
    renderBaseTable(rows);
  } else if (currentTab === 'dexscreener') {
    renderDexScreenerTable(rows);
  } else if (currentTab === 'analysis') {
    updateAnalysis();
  }
  
  updatePagination();
}

function renderBaseTable(rows) {
  const tbody = document.getElementById('baseTbody');
  
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="13" class="no-data">Aucune donnée ne correspond aux filtres</td></tr>';
  } else {
    tbody.innerHTML = rows.map(r => {
      const updatedAt = r.updated_at || r.first_discovered_at;
      const timeAgo = getTimeAgo(updatedAt);
      const discoveredAt = formatLocalDateTime(r.first_discovered_at);
      const fullUpdateTime = formatLocalDateTime(updatedAt);
      const bondingCurveDisplay = getBondingCurveDisplay(r.bonding_curve_status);
      const progressDisplay = getBondingProgressDisplay(r.bonding_curve_status, r.bonding_curve_progress);
      
      return `
        <tr>
          <td><span class="fav" onclick="toggleFav('${r.address}')">⭐</span></td>
          <td><a href="https://dexscreener.com/solana/${r.address}" target="_blank">${r.symbol}</a></td>
          <td class="price">${(+r.price_usdc || 0).toFixed(8)}</td>
          <td class="score">${(+r.invest_score || 0).toFixed(1)}</td>
          <td>${Math.round(r.liquidity_usd || 0).toLocaleString()}</td>
          <td>${Math.round(r.volume_24h || 0).toLocaleString()}</td>
          <td>${r.holders || 0}</td>
          <td>${(+r.age_hours || 0).toFixed(1)}</td>
          <td>${Math.round(100 - (r.rug_score || 50))}</td>
          <td>${bondingCurveDisplay}</td>
          <td>${progressDisplay}</td>
          <td class="${timeAgo.className}" title="${fullUpdateTime}">${timeAgo.text}</td>
          <td title="${discoveredAt}">${discoveredAt}</td>
        </tr>
      `;
    }).join('');
  }
}

function renderDexScreenerTable(rows) {
  const tbody = document.getElementById('dexscreenerTbody');
  
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="24" class="no-data">Aucune donnée ne correspond aux filtres</td></tr>';
  } else {
    tbody.innerHTML = rows.map(r => {
      const dexUrl = r.dexscreener_url || `https://dexscreener.com/solana/${r.address}`;
      const dexUrlDisplay = (r.dexscreener_price_usd || 0) > 0 ? 
        `<a href="${dexUrl}" target="_blank">🔗 Voir</a>` : 
        'N/A';
      
      // Nouvelles colonnes avec formatage temporel
      const pairCreatedAt = r.dexscreener_pair_created_at;
      const pairCreatedTimeAgo = getTimeAgo(pairCreatedAt);
      const pairCreatedFull = formatLocalDateTime(pairCreatedAt);
      
      const lastDexUpdate = r.last_dexscreener_update || r.updated_at;
      const dexUpdateTimeAgo = getTimeAgo(lastDexUpdate);
      const dexUpdateFull = formatLocalDateTime(lastDexUpdate);
      
      const priceChange1h = formatPriceChange(r.dexscreener_price_change_1h);
      const priceChange6h = formatPriceChange(r.dexscreener_price_change_6h);
      const priceChange24h = formatPriceChange(r.dexscreener_price_change_h24);
      
      // Ajout de la colonne Progress
      const progressDisplay = getBondingProgressDisplay(r.bonding_curve_status, r.bonding_curve_progress);
      
      return `
        <tr>
          <td><span class="fav" onclick="toggleFav('${r.address}')">⭐</span></td>
          <td>
            <strong>${r.symbol}</strong><br>
            <small>
              <span id="history-${r.address}" style="font-size: 0.7rem;">
                <span style="color: #888;">⏳ Vérification...</span>
              </span>
            </small>
          </td>
          <td>${getTokenStatusDisplay(r.status)}</td>
          <td class="price">${(r.dexscreener_price_usd || 0).toFixed(8)}</td>
          <td>${Math.round(r.dexscreener_market_cap || 0).toLocaleString()}</td>
          <td>${(r.dexscreener_liquidity_base || 0).toFixed(2)}</td>
          <td>${Math.round(r.dexscreener_liquidity_quote || 0).toLocaleString()}</td>
          <td>${Math.round(r.dexscreener_volume_1h || 0).toLocaleString()}</td>
          <td>${Math.round(r.dexscreener_volume_6h || 0).toLocaleString()}</td>
          <td>${Math.round(r.dexscreener_volume_24h || 0).toLocaleString()}</td>
          <td class="${priceChange1h.className}">${priceChange1h.text}</td>
          <td class="${priceChange6h.className}">${priceChange6h.text}</td>
          <td class="${priceChange24h.className}">${priceChange24h.text}</td>
          <td>${r.dexscreener_txns_1h || 0}</td>
          <td>${r.dexscreener_txns_6h || 0}</td>
          <td>${r.dexscreener_txns_24h || 0}</td>
          <td style="color: #00ff88">${r.dexscreener_buys_1h || 0}</td>
          <td style="color: #ff6b6b">${r.dexscreener_sells_1h || 0}</td>
          <td style="color: #00ff88">${r.dexscreener_buys_24h || 0}</td>
          <td style="color: #ff6b6b">${r.dexscreener_sells_24h || 0}</td>
          <td>${progressDisplay}</td>
          <td>${dexUrlDisplay}</td>
          <td class="${pairCreatedTimeAgo.className}" title="${pairCreatedFull}">${pairCreatedTimeAgo.text}</td>
          <td class="${dexUpdateTimeAgo.className}" title="${dexUpdateFull}">${dexUpdateTimeAgo.text}</td>
        </tr>
      `;
    }).join('');
    
    rows.forEach(r => {
      setTimeout(() => checkTokenHistory(r.address), Math.random() * 1000);
    });
  }
}

function getTokenStatusDisplay(status) { 
  if (!status) return '<span class="token-status status-unknown">Unknown</span>'; 
  const statusLower = String(status || '').toLowerCase().trim();
  const statusMap = { 
    'active': '<span class="token-status status-active">Active</span>', 
    'inactive': '<span class="token-status status-inactive">Inactive</span>', 
    'no_dex_data': '<span class="token-status status-no_dex_data">No Dex</span>', 
    'archived': '<span class="token-status status-archived">Archived</span>', 
    'blacklisted': '<span class="token-status status-blacklisted">Blacklisted</span>' 
  }; 
  return statusMap[statusLower] || `<span class="token-status status-unknown">${status}</span>`; 
}

function updateAnalysis() {
  const metricsContainer = document.getElementById('analysisMetrics');
  
  if (filteredData.length === 0) {
    metricsContainer.innerHTML = '<div class="metric-card"><div class="metric-title">Aucune donnée à analyser</div></div>';
    return;
  }

  const totalTokens = filteredData.length;
  const avgScore = filteredData.reduce((sum, token) => sum + (token.invest_score || 0), 0) / totalTokens;
  const avgLiquidity = filteredData.reduce((sum, token) => sum + (token.liquidity_usd || 0), 0) / totalTokens;
  const avgVolume = filteredData.reduce((sum, token) => sum + (token.volume_24h || 0), 0) / totalTokens;
  const avgHolders = filteredData.reduce((sum, token) => sum + (token.holders || 0), 0) / totalTokens;
  
  const highScoreTokens = filteredData.filter(token => (token.invest_score || 0) >= 80).length;
  const activeTokens = filteredData.filter(token => token.bonding_curve_status === 'active').length;
  const migratedTokens = filteredData.filter(token => token.bonding_curve_status === 'migrated').length;
  
  const tokensWithDexData = filteredData.filter(token => (token.dexscreener_price_usd || 0) > 0).length;
  const totalDexVolume = filteredData.reduce((sum, token) => sum + (token.dexscreener_volume_24h || 0), 0);
  const avgDexPrice = tokensWithDexData > 0 ? 
    filteredData.filter(token => (token.dexscreener_price_usd || 0) > 0)
      .reduce((sum, token) => sum + (token.dexscreener_price_usd || 0), 0) / tokensWithDexData : 0;
  
  const avgDexMarketCap = tokensWithDexData > 0 ?
    filteredData.filter(token => (token.dexscreener_market_cap || 0) > 0)
      .reduce((sum, token) => sum + (token.dexscreener_market_cap || 0), 0) / 
      filteredData.filter(token => (token.dexscreener_market_cap || 0) > 0).length : 0;
  
  const totalDexTxns24h = filteredData.reduce((sum, token) => sum + (token.dexscreener_txns_24h || 0), 0);
  const totalDexBuys24h = filteredData.reduce((sum, token) => sum + (token.dexscreener_buys_24h || 0), 0);
  const totalDexSells24h = filteredData.reduce((sum, token) => sum + (token.dexscreener_sells_24h || 0), 0);

  metricsContainer.innerHTML = `
    <div class="metric-card">
      <div class="metric-title">📊 Tokens Analysés</div>
      <div class="metric-value">${totalTokens}</div>
      <div class="metric-subtitle">Dans la sélection actuelle</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">⭐ Score Moyen</div>
      <div class="metric-value">${avgScore.toFixed(1)}</div>
      <div class="metric-subtitle">Score d'investissement</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">🏆 Tokens Premium</div>
      <div class="metric-value">${highScoreTokens}</div>
      <div class="metric-subtitle">${((highScoreTokens/totalTokens)*100).toFixed(1)}% avec score ≥80</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">📈 Avec Données DexScreener</div>
      <div class="metric-value">${tokensWithDexData}</div>
      <div class="metric-subtitle">${((tokensWithDexData/totalTokens)*100).toFixed(1)}% des tokens</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">💧 Liquidité Moyenne</div>
      <div class="metric-value">${(avgLiquidity/1000).toFixed(1)}K</div>
      <div class="metric-subtitle">Liquidité USD moyenne</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">📊 Volume DexScreener 24h</div>
      <div class="metric-value">${(totalDexVolume/1000000).toFixed(2)}M</div>
      <div class="metric-subtitle">Volume total DexScreener</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">💰 Prix Moyen DexScreener</div>
      <div class="metric-value">${avgDexPrice.toFixed(6)}</div>
      <div class="metric-subtitle">Prix moyen USD</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">🎯 Market Cap Moyen</div>
      <div class="metric-value">${(avgDexMarketCap/1000000).toFixed(2)}M</div>
      <div class="metric-subtitle">Market cap moyen DexScreener</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">🔄 Tokens Actifs</div>
      <div class="metric-value">${activeTokens}</div>
      <div class="metric-subtitle">${((activeTokens/totalTokens)*100).toFixed(1)}% en bonding curve</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">🚀 Tokens Migrés</div>
      <div class="metric-value">${migratedTokens}</div>
      <div class="metric-subtitle">${((migratedTokens/totalTokens)*100).toFixed(1)}% sur Raydium</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">📊 Transactions 24h</div>
      <div class="metric-value">${Math.round(totalDexTxns24h/1000)}K</div>
      <div class="metric-subtitle">Total transactions DexScreener</div>
    </div>
    
    <div class="metric-card">
      <div class="metric-title">💚 Ratio Buys/Sells 24h</div>
      <div class="metric-value">${totalDexSells24h > 0 ? (totalDexBuys24h/totalDexSells24h).toFixed(2) : '∞'}</div>
      <div class="metric-subtitle">${totalDexBuys24h} buys / ${totalDexSells24h} sells</div>
    </div>
  `;
}

function updatePagination() {
  document.getElementById("pageInfo").textContent = 
    `Page ${currentPage} / ${Math.ceil(filteredData.length / perPage)} (${filteredData.length} tokens)`;
  document.getElementById("prevBtn").disabled = currentPage === 1;
  document.getElementById("nextBtn").disabled = currentPage === Math.ceil(filteredData.length / perPage);
}

// === FONCTIONS DE PAGINATION ===
function changePerPage() {
  perPage = +document.getElementById("perPage").value;
  currentPage = 1;
  renderPage();
}

function prevPage() {
  if (currentPage > 1) {
    currentPage--;
    renderPage();
  }
}

function nextPage() {
  if (currentPage < Math.ceil(filteredData.length / perPage)) {
    currentPage++;
    renderPage();
  }
}

// === FONCTIONS DE CONTRÔLE ===
function reloadData() {
  fetchData();
  document.querySelectorAll('.filter-panel input').forEach(input => input.value = '');
  document.getElementById('filterTimeUnit').value = '';
  document.getElementById('filterBondingStatus').value = '';
  document.getElementById('dexFilterHasData').value = '';
  document.getElementById('dexFilterStatus').value = '';
  document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('active'));
  applyFilters();
}

function resetFilters() {
  document.querySelectorAll('.filter-panel input').forEach(input => input.value = '');
  document.getElementById('filterTimeUnit').value = '';
  document.getElementById('filterBondingStatus').value = '';
  document.getElementById('filterDiscoveredAt').value = '';
  document.getElementById('dexFilterHasData').value = '';
  document.getElementById('dexFilterStatus').value = '';
  document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('active'));
  window.dexTimeValue = null;
  window.dexTimeUnit = null;
  filteredData = [...data];
  currentPage = 1;
  renderPage();
}

// Vérifier l'historique de manière asynchrone
function checkTokenHistory(address) {
  fetch(`/api/token-has-history/${address}`)
    .then(response => response.json())
    .then(data => {
      const element = document.getElementById(`history-${address}`);
      if (element) {
        if (data.has_history && data.data_points > 0) {
          element.innerHTML = `
            <a href="/dashboard/history?address=${address}" target="_blank" style="color: #00d4ff;">
              📊 Historique (${data.data_points} pts)
            </a>
          `;
        } else {
          element.innerHTML = '<span style="color: #666;">📊 Pas d\'historique</span>';
        }
      }
    })
    .catch(() => {
      const element = document.getElementById(`history-${address}`);
      if (element) {
        element.innerHTML = '<span style="color: #666;">📊 Pas d\'historique</span>';
      }
    });
}

async function toggleFav(address) {
  await fetch(`/api/favorites/${address}`, { method: 'POST' });
  alert('Ajouté aux favoris !');
}

function highlightActiveFilters() {
  // Base filters
  const baseInputs = [
    'filterSymbol', 'filterBondingStatus', 'filterProgressMin', 'filterProgressMax',
    'filterPriceMin', 'filterPriceMax', 'filterScoreMin', 'filterScoreMax',
    'filterLiquidityMin', 'filterLiquidityMax', 'filterVolumeMin', 'filterVolumeMax',
    'filterHoldersMin', 'filterHoldersMax', 'filterAgeMin', 'filterAgeMax',
    'filterRiskMin', 'filterRiskMax', 'filterDiscoveredAt', 'filterTimeValue', 'filterTimeUnit'
  ];

  baseInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el && el.value.trim() !== '') {
      el.classList.add('filter-active');
    } else {
      el.classList.remove('filter-active');
    }
  });

  // Dex filters
  const dexInputs = [
    'dexFilterSymbol', 'dexFilterStatus', 'dexFilterPriceMin', 'dexFilterPriceMax',
    'dexFilterMarketCapMin', 'dexFilterMarketCapMax', 'dexFilterVolume1hMin',
    'dexFilterVolume6hMin', 'dexFilterVolume24hMin', 'dexFilterTxns24hMin',
    'dexFilterBuys24hMin', 'dexFilterSells24hMax', 'dexFilterLiquidityQuoteMin', 'dexFilterHasData'
  ];

  dexInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el && el.value.trim() !== '') {
      el.classList.add('filter-active');
    } else {
      el.classList.remove('filter-active');
    }
  });

  // Highlight preset buttons
  document.querySelectorAll('.preset-btn').forEach(btn => {
    if (btn.classList.contains('active')) {
      btn.classList.add('filter-active');
    } else {
      btn.classList.remove('filter-active');
    }
  });
}

// === ÉVÉNEMENTS ===
let debounceTimeout;

// Filtres onglet base
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('#base-content .filter-panel input, #base-content .filter-panel select').forEach(input => {
    input.addEventListener('input', () => {
      clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        applyFilters();
      }, 300);
    });
  });

  // Filtres onglet DexScreener
  document.querySelectorAll('#dexscreener-content .filter-panel input, #dexscreener-content .filter-panel select').forEach(input => { 
    input.addEventListener('input', () => { 
      clearTimeout(debounceTimeout); 
      debounceTimeout = setTimeout(() => { 
        applyDexFilters();
      }, 300);
    }); 
  });

  // === INITIALISATION ===
  fetchData();
  startAutoRefresh();
  updateRefreshStatus();
});