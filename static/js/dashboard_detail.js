// =============================================================================
// DASHBOARD DETAIL - Fichier principal allégé
// =============================================================================

// Variables globales principales
let data = [], filteredData = [], currentPage = 1, perPage = 10;
let refreshInterval = 30000;
let refreshTimer = null;
let isAutoRefreshEnabled = true;
let currentTab = 'base';
let activeFiltersCount = 0;

// Variables whale
let whaleData = [];
let isWhaleAutoRefreshEnabled = true;
let whaleRefreshTimer = null;
let whaleRefreshInterval = 30000;

// Variables pour le debounce
let debounceTimeout;

// =============================================================================
// FONCTIONS UTILITAIRES
// =============================================================================

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

// =============================================================================
// FONCTIONS BONDING CURVE
// =============================================================================

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

// =============================================================================
// GESTION DES ONGLETS
// =============================================================================

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
  
  if (currentTab === 'whale') {
    updateWhaleActivity();
    setTimeout(() => {
      updateWhaleIndicators();
    }, 1000);
  } else if (currentTab === 'dexscreener' || currentTab === 'pumpfun') {
    setTimeout(() => {
      updateWhaleIndicators();
    }, 1000);
  }
}

// =============================================================================
// FONCTIONS AUTO-REFRESH
// =============================================================================

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

// =============================================================================
// FONCTIONS DE DONNÉES
// =============================================================================

async function fetchData() {
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
    if (currentTab === 'whale') {
      updateWhaleActivity();
    }
    setTimeout(() => {
      updateWhaleIndicators();
      setTimeout(() => {
        updateWhaleIndicators();
      }, 2000);
    }, 1000);

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

// =============================================================================
// FONCTIONS DE FILTRAGE (ONGLET BASE)
// =============================================================================

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
    const tokenAgeHours = parseFloat(row.age_hours) || 0;
    
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
      (filters.ageMin === null || tokenAgeHours >= filters.ageMin) &&
      (filters.ageMax === null || tokenAgeHours <= filters.ageMax) &&
      (filters.riskMin === null || riskValue >= filters.riskMin) &&
      (filters.riskMax === null || riskValue <= filters.riskMax) &&
      (!filters.discoveredAt || new Date(row.first_discovered_at).toISOString().startsWith(filters.discoveredAt)) &&
      isWithinTimeFilter(updatedAt, filters.timeValue, filters.timeUnit)
    );
  });

  highlightActiveFilters();
  updateFiltersIndicator();
  currentPage = 1;
  renderPage();
}

// =============================================================================
// FONCTIONS D'AFFICHAGE
// =============================================================================

function renderPage() {
  const start = (currentPage - 1) * perPage;
  const rows = filteredData.slice(start, start + perPage);
  
  if (currentTab === 'base') {
    renderBaseTable(rows);
  } else if (currentTab === 'dexscreener') {
    renderDexScreenerTable(rows);
  } else if (currentTab === 'pumpfun') {
    renderPumpFunTable(rows);
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
  
  const highScoreTokens = filteredData.filter(token => (token.invest_score || 0) >= 80).length;
  const activeTokens = filteredData.filter(token => token.bonding_curve_status === 'active').length;
  const migratedTokens = filteredData.filter(token => token.bonding_curve_status === 'migrated').length;
  
  const tokensWithDexData = filteredData.filter(token => (token.dexscreener_price_usd || 0) > 0).length;
  const totalDexVolume = filteredData.reduce((sum, token) => sum + (token.dexscreener_volume_24h || 0), 0);
  
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

// =============================================================================
// FONCTIONS DE PAGINATION
// =============================================================================

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

// =============================================================================
// FONCTIONS DE CONTRÔLE
// =============================================================================

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
  document.querySelectorAll('.strategy-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('active'));
  window.dexTimeValue = null;
  window.dexTimeUnit = null;
  filteredData = [...data];
  currentPage = 1;
  updateFiltersIndicator();
  renderPage();
}

// =============================================================================
// FONCTIONS D'EXPORT
// =============================================================================

function exportData(format) {
  if (filteredData.length === 0) {
    alert('Aucune donnée à exporter avec les filtres actuels');
    return;
  }
  
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
  const filename = `tokens_export_${timestamp}`;
  
  if (format === 'csv') {
    exportToCSV(filteredData, filename);
  } else if (format === 'json') {
    exportToJSON(filteredData, filename);
  }
}

function exportToCSV(data, filename) {
  const columns = [
    'symbol', 'address', 'price_usdc', 'invest_score', 'liquidity_usd', 'volume_24h',
    'holders', 'age_hours', 'rug_score', 'bonding_curve_status', 'bonding_curve_progress',
    'dexscreener_price_usd', 'dexscreener_market_cap', 'dexscreener_volume_24h',
    'dexscreener_txns_24h', 'status', 'first_discovered_at', 'updated_at'
  ];
  
  const headers = [
    'Symbol', 'Address', 'Price USD', 'Score', 'Liquidity USD', 'Volume 24h',
    'Holders', 'Age Hours', 'Rug Score', 'Bonding Status', 'Progress %',
    'Dex Price USD', 'Dex Market Cap', 'Dex Volume 24h',
    'Dex Txns 24h', 'Status', 'Discovered At', 'Updated At'
  ];
  
  let csvContent = headers.join(',') + '\n';
  
  data.forEach(row => {
    const values = columns.map(col => {
      let value = row[col] || '';
      if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
        value = '"' + value.replace(/"/g, '""') + '"';
      }
      return value;
    });
    csvContent += values.join(',') + '\n';
  });
  
  downloadFile(csvContent, `${filename}.csv`, 'text/csv');
}

function exportToJSON(data, filename) {
  const jsonContent = JSON.stringify(data, null, 2);
  downloadFile(jsonContent, `${filename}.json`, 'application/json');
}

function downloadFile(content, filename, contentType) {
  const blob = new Blob([content], { type: contentType });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}

// =============================================================================
// FONCTIONS DE THÈME
// =============================================================================

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme');
  const newTheme = currentTheme === 'light' ? null : 'light';
  
  document.documentElement.setAttribute('data-theme', newTheme || 'dark');
  
  const themeButton = document.getElementById('themeToggle');
  if (newTheme === 'light') {
    themeButton.textContent = '🌙 Mode Sombre';
    localStorage.setItem('theme', 'light');
  } else {
    themeButton.textContent = '☀️ Mode Clair';
    localStorage.setItem('theme', 'dark');
  }
}

function loadSavedTheme() {
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    document.getElementById('themeToggle').textContent = '🌙 Mode Sombre';
  }
}

// =============================================================================
// FONCTIONS WHALE ACTIVITY
// =============================================================================

async function updateWhaleActivity() {
  try {
    await Promise.all([
      fetchWhaleSummary(),
      fetchWhaleFeed()
    ]);
  } catch (error) {
    console.error('Error updating whale activity:', error);
  }
}

async function fetchWhaleSummary() {
  try {
    const response = await fetch('/api/whale-summary');
    if (!response.ok) throw new Error('Failed to fetch whale summary');
    
    const summary = await response.json();
    
    document.getElementById('whaleTransactions1h').textContent = summary.total_transactions || 0;
    document.getElementById('whaleVolume1h').textContent = `${(summary.total_volume_usd || 0).toLocaleString()}`;
    document.getElementById('whaleUniqueTokens').textContent = summary.unique_tokens || 0;
    document.getElementById('whaleUniqueWallets').textContent = summary.unique_wallets || 0;
    
  } catch (error) {
    console.error('Error fetching whale summary:', error);
  }
}

async function fetchWhaleFeed() {
  const period = document.getElementById('whaleFeedPeriod').value;
  
  try {
    const response = await fetch(`/api/whale-feed?hours=${period}&limit=20`);
    if (!response.ok) throw new Error('Failed to fetch whale feed');
    
    const data = await response.json();
    renderWhaleFeed(data.feed_items || []);
    
  } catch (error) {
    console.error('Error fetching whale feed:', error);
    document.getElementById('whaleFeedContent').innerHTML = 
      '<div class="error">Erreur lors du chargement du feed whale</div>';
  }
}

function renderWhaleFeed(feedItems) {
  const container = document.getElementById('whaleFeedContent');
  
  if (feedItems.length === 0) {
    container.innerHTML = '<div class="no-data">🐋 Aucune activité whale récente</div>';
    return;
  }
  
  const feedHtml = feedItems.map(item => {
    const emoji = getWhaleEmoji(item.type, item.amount_usd);
    const itemClass = item.is_critical ? 'whale-feed-critical' : 
                     item.is_in_database ? '' : 'whale-feed-new';
    
    const links = [];
    if (item.dexscreener_url) {
      links.push(`<a href="${item.dexscreener_url}" target="_blank" class="whale-feed-link whale-feed-link-dex" title="Voir sur DexScreener">📊 DEX</a>`);
    }
    if (item.pump_fun_url && item.token_status !== 'migrated') {
      links.push(`<a href="${item.pump_fun_url}" target="_blank" class="whale-feed-link whale-feed-link-pump" title="Voir sur Pump.fun">🚀 PUMP</a>`);
    }
    if (item.solscan_url) {
      links.push(`<a href="${item.solscan_url}" target="_blank" class="whale-feed-link whale-feed-link-solscan" title="Voir transaction">🔍 TX</a>`);
    }

    return `
      <div class="whale-feed-item ${itemClass}">
        <div class="whale-feed-time-full" title="${item.timestamp_full}">
          ${item.timestamp_formatted}
        </div>
        
        <div class="whale-feed-emoji">${emoji}</div>
        
        <div class="whale-feed-type">${item.type}</div>
        
        <div class="whale-feed-amount-detailed">
          <div class="whale-feed-amount-main">${item.amount_formatted}</div>
          <div class="whale-feed-amount-precise" title="Montant exact">${item.amount_detailed}</div>
        </div>
        
        <div class="whale-feed-token-info">
          <div style="display: flex; align-items: center; gap: 0.3rem;">
            <span class="whale-feed-token-symbol">${item.token_symbol}</span>
            <span class="whale-token-status whale-token-status-${item.token_status}">${item.token_status}</span>
          </div>
          <div class="whale-feed-token-name" title="${item.token_name}">${item.token_name}</div>
          <div class="whale-feed-token-address" 
               title="${item.token_full}" 
               onclick="copyToClipboard('${item.token_full}')">
            ${item.token_short}
          </div>
        </div>
        
        <div class="whale-feed-wallet-info">
          <div class="whale-feed-wallet-label">${item.wallet_label}</div>
          <div class="whale-feed-wallet-address" 
               title="${item.wallet_address}"
               onclick="copyToClipboard('${item.wallet_address}')">
            ${item.wallet_short}
          </div>
        </div>
        
        <div class="whale-feed-links">
          ${links.join('')}
          ${item.is_in_database ? '' : '<span class="whale-feed-new-badge">⭐ NEW</span>'}
        </div>
      </div>
    `;
  }).join('');
  
  container.innerHTML = feedHtml;
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    const notification = document.createElement('div');
    notification.textContent = 'Copié!';
    notification.style.cssText = `
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      background: var(--text-accent);
      color: var(--bg-primary);
      padding: 0.5rem 1rem;
      border-radius: 4px;
      z-index: 10000;
      font-weight: bold;
    `;
    document.body.appendChild(notification);
    
    setTimeout(() => {
      document.body.removeChild(notification);
    }, 1000);
  }).catch(err => {
    console.error('Erreur copie:', err);
  });
}

function getWhaleEmoji(type, amount) {
  if (amount >= 100000) return "⚡";
  if (type === 'SELL') return "🔴";
  if (type === 'BUY') return "🟢";
  return "🔄";
}

function refreshWhaleFeed() {
  fetchWhaleFeed();
}

function toggleWhaleAutoRefresh() {
  const checkbox = document.getElementById('whaleAutoRefresh');
  isWhaleAutoRefreshEnabled = checkbox.checked;
  
  if (isWhaleAutoRefreshEnabled) {
    startWhaleAutoRefresh();
  } else {
    stopWhaleAutoRefresh();
  }
}

function startWhaleAutoRefresh() {
  if (whaleRefreshTimer) clearInterval(whaleRefreshTimer);
  
  if (isWhaleAutoRefreshEnabled) {
    whaleRefreshTimer = setInterval(() => {
      if (currentTab === 'whale') {
        updateWhaleActivity();
      }
      updateWhaleIndicators();
    }, whaleRefreshInterval);
  }
}

function stopWhaleAutoRefresh() {
  if (whaleRefreshTimer) {
    clearInterval(whaleRefreshTimer);
    whaleRefreshTimer = null;
  }
}

async function updateWhaleIndicators() {
  if (currentTab !== 'dexscreener' && currentTab !== 'whale') return;
  
  try {
    const selectedPeriod = document.getElementById('whalePeriodSelector')?.value || 24;
    const response = await fetch(`/api/whale-activity?hours=${selectedPeriod}&limit=100`);
    if (!response.ok) {
      console.error('Whale API response not OK:', response.status);
      return;
    }
    
    const data = await response.json();
    const whaleByToken = {};
    
    const transactions = data.whale_transactions || data.transactions || data.data || [];
    
    transactions.forEach(tx => {
      const tokenAddr = tx.token_address || tx.address;
      if (tokenAddr) {
        if (!whaleByToken[tokenAddr] || 
            new Date(tx.timestamp) > new Date(whaleByToken[tokenAddr].timestamp)) {
          whaleByToken[tokenAddr] = tx;
        }
      }
    });
    
    let updatedCount = 0;
    let foundCount = 0;
    
    filteredData.forEach(token => {
      const whaleActivity = whaleByToken[token.address];
      const indicator = generateWhaleIndicator(whaleActivity);
      
      const element = document.getElementById(`whale-activity-${token.address}`);
      if (element) {
        element.innerHTML = indicator;
        updatedCount++;
        if (whaleActivity) foundCount++;
      }
    });
    
    console.log(`Whale indicators updated: ${updatedCount} elements, ${foundCount} with activity, ${transactions.length} total transactions`);
    
  } catch (error) {
    console.error('Error updating whale indicators:', error);
    
    filteredData.forEach(token => {
      const element = document.getElementById(`whale-activity-${token.address}`);
      if (element && element.innerHTML.includes('⏳')) {
        element.innerHTML = '<span class="whale-indicator-error">❌ Erreur</span>';
      }
    });
  }
}

function changeWhalePeriod() {
  updateWhaleIndicators();
}

function generateWhaleIndicator(whaleActivity) {
  if (!whaleActivity) {
    return '<span class="whale-indicator-none">💤 No activity</span>';
  }
  
  const amount = whaleActivity.amount_usd || 0;
  const type = whaleActivity.transaction_type;
  const timeAgo = getTimeAgoExtended(whaleActivity.timestamp);
  
  if (amount >= 100000) {
    return `<span class="whale-indicator-critical">⚡ ${(amount/1000).toFixed(0)}K (${timeAgo})</span>`;
  } else if (amount >= 10000) {
    if (type === 'SELL' || type === 'sell') {
      return `<span class="whale-indicator-sell">🔴 -${(amount/1000).toFixed(0)}K (${timeAgo})</span>`;
    } else {
      return `<span class="whale-indicator-buy">🟢 +${(amount/1000).toFixed(0)}K (${timeAgo})</span>`;
    }
  } else if (amount >= 1000) {
    if (type === 'SELL' || type === 'sell') {
      return `<span class="whale-indicator-medium">🟠 -${(amount/1000).toFixed(1)}K (${timeAgo})</span>`;
    } else {
      return `<span class="whale-indicator-medium">🟡 +${(amount/1000).toFixed(1)}K (${timeAgo})</span>`;
    }
  } else {
    return '<span class="whale-indicator-none">💤 No activity</span>';
  }
}

function getTimeAgoExtended(timestamp) {
  const now = new Date();
  const time = new Date(timestamp);
  const diffMinutes = Math.floor((now - time) / (1000 * 60));
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffMinutes < 1) return 'now';
  if (diffMinutes < 60) return `${diffMinutes}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  return `${Math.floor(diffDays/7)}w`;
}

// =============================================================================
// FONCTIONS UTILITAIRES
// =============================================================================

function updateFiltersIndicator() {
  let count = 0;
  
  const baseInputs = [
    'filterSymbol', 'filterBondingStatus', 'filterProgressMin', 'filterProgressMax',
    'filterPriceMin', 'filterPriceMax', 'filterScoreMin', 'filterScoreMax',
    'filterLiquidityMin', 'filterLiquidityMax', 'filterVolumeMin', 'filterVolumeMax',
    'filterHoldersMin', 'filterHoldersMax', 'filterAgeMin', 'filterAgeMax',
    'filterRiskMin', 'filterRiskMax', 'filterDiscoveredAt', 'filterTimeValue'
  ];
  
  baseInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el && el.value.trim() !== '') count++;
  });
  
  const dexInputs = [
    'dexFilterSymbol', 'dexFilterStatus', 'dexFilterPriceMin', 'dexFilterPriceMax',
    'dexFilterMarketCapMin', 'dexFilterMarketCapMax', 'dexFilterVolume1hMin',
    'dexFilterVolume6hMin', 'dexFilterVolume24hMin', 'dexFilterTxns24hMin',
    'dexFilterBuys24hMin', 'dexFilterSells24hMax', 'dexFilterLiquidityQuoteMin', 'dexFilterHasData',
    'dexFilterBuySellRatio1h', 'dexFilterBuySellRatio24h', 'dexFilterRugScoreMin', 'dexFilterRugScoreMax'
  ];

  dexInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el && el.value.trim() !== '') count++;
  });

  activeFiltersCount = count;
  
  const indicator = document.getElementById('filtersIndicator');
  if (indicator) {
    const filterCount = indicator.querySelector('.filter-count');
    if (filterCount) {
      if (count === 0) {
        filterCount.textContent = 'Aucun filtre actif';
        indicator.style.opacity = '0.6';
      } else {
        filterCount.textContent = `${count} filtre${count > 1 ? 's' : ''} actif${count > 1 ? 's' : ''}`;
        indicator.style.opacity = '1';
      }
    }
  }
}

function highlightActiveFilters() {
  const baseInputs = [
    'filterSymbol', 'filterBondingStatus', 'filterProgressMin', 'filterProgressMax',
    'filterPriceMin', 'filterPriceMax', 'filterScoreMin', 'filterScoreMax',
    'filterLiquidityMin', 'filterLiquidityMax', 'filterVolumeMin', 'filterVolumeMax',
    'filterHoldersMin', 'filterHoldersMax', 'filterAgeMin', 'filterAgeMax',
    'filterRiskMin', 'filterRiskMax', 'filterDiscoveredAt', 'filterTimeValue', 
    'filterTimeUnit', 'dexFilterRugScoreMin', 'dexFilterRugScoreMax'
  ];

  baseInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el && el.value.trim() !== '') {
      el.classList.add('filter-active');
    } else {
      el.classList.remove('filter-active');
    }
  });

  const dexInputs = [
    'dexFilterSymbol', 'dexFilterStatus', 'dexFilterPriceMin', 'dexFilterPriceMax',
    'dexFilterMarketCapMin', 'dexFilterMarketCapMax', 'dexFilterVolume1hMin',
    'dexFilterVolume6hMin', 'dexFilterVolume24hMin', 'dexFilterTxns24hMin',
    'dexFilterBuys24hMin', 'dexFilterSells24hMax', 'dexFilterLiquidityQuoteMin', 'dexFilterHasData',
    'dexFilterHoldersMin', 'dexFilterHoldersMax', 'dexFilterHoldersGrowth', 'dexFilterHoldersDistribution'
  ];

  dexInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el && el.value.trim() !== '') {
      el.classList.add('filter-active');
    } else {
      el.classList.remove('filter-active');
    }
  });

  document.querySelectorAll('.preset-btn').forEach(btn => {
    if (btn.classList.contains('active')) {
      btn.classList.add('filter-active');
    } else {
      btn.classList.remove('filter-active');
    }
  });
}

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

// =============================================================================
// INITIALISATION
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation du dashboard...');
  
  // Filtres onglet base
  document.querySelectorAll('#base-content .filter-panel input, #base-content .filter-panel select').forEach(input => {
    input.addEventListener('input', () => {
      clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        applyFilters();
      }, 300);
    });
  });

  // Setup des listeners DexScreener et PumpFun
  if (typeof setupDexFiltersEventListeners === 'function') {
    setupDexFiltersEventListeners();
  }
  if (typeof setupPumpFiltersEventListeners === 'function') {
    setupPumpFiltersEventListeners();
  }

  // Initialisation
  loadSavedTheme();
  fetchData();
  startAutoRefresh();
  updateRefreshStatus();
  updateFiltersIndicator();
  startWhaleAutoRefresh();

  setTimeout(() => {
    updateWhaleIndicators();
  }, 2000);

  console.log('✅ Dashboard initialisé');
});