let data = [], filteredData = [], currentPage = 1, perPage = 10;
let refreshInterval = 30000;
let refreshTimer = null;
let isAutoRefreshEnabled = true;
let currentTab = 'base';
let activeFiltersCount = 0;

// Variables pour le filtre d'âge
let currentAgeMin = null;
let currentAgeMax = null;

// Variables whale
let whaleData = [];
let isWhaleAutoRefreshEnabled = true;
let whaleRefreshTimer = null;
let whaleRefreshInterval = 30000; // 30 secondes

let currentWhaleFilter = '';
let currentWhaleAmountMin = null;
let currentWhalePeriod = null;


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
  if (currentTab === 'whale') {
    updateWhaleActivity();
    // Forcer la mise à jour des indicateurs whale dans les tableaux
    setTimeout(() => {
      updateWhaleIndicators();
    }, 1000);
  } else if (currentTab === 'dexscreener') {
    // Forcer la mise à jour des indicateurs whale pour DexScreener
    setTimeout(() => {
      updateWhaleIndicators();
    }, 1000);
  }
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
      // Ajouter un deuxième appel au cas où le premier échoue
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

// Nouvelles fonctions pour le filtre d'âge
function setAgeFilter(minHours, maxHours, unit, btn) {
  currentAgeMin = minHours;
  currentAgeMax = maxHours;
  
  // Cibler spécifiquement les boutons d'âge, pas tous les boutons présets
  document.querySelectorAll('#dexscreener-content .age-presets .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyDexFilters();
}

function clearAgeFilter(btn) {
  currentAgeMin = null;
  currentAgeMax = null;
  
  // Cibler spécifiquement les boutons d'âge, pas tous les boutons présets
  document.querySelectorAll('#dexscreener-content .age-presets .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyDexFilters();
}


function setDexTimeFilter(value, unit, btn) {
  window.dexTimeValue = value;
  window.dexTimeUnit = unit;
  // Enlever 'active' de TOUS les boutons présets DexScreener (pas seulement les boutons de temps)
  document.querySelectorAll('#dexscreener-content .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyDexFilters();
}

function clearDexTimeFilter(btn) {
  window.dexTimeValue = null;
  window.dexTimeUnit = null;
  // Enlever 'active' de TOUS les boutons présets DexScreener
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
    const tokenAgeHours = parseFloat(row.age_hours) || 0;
    
    // Vérification du filtre d'âge des boutons présets
    let ageFilterPassed = true;
    if (currentAgeMin !== null || currentAgeMax !== null) {
      if (currentAgeMin !== null && tokenAgeHours < currentAgeMin) {
        ageFilterPassed = false;
      }
      if (currentAgeMax !== null && tokenAgeHours > currentAgeMax) {
        ageFilterPassed = false;
      }
    }
    
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
      isWithinTimeFilter(updatedAt, filters.timeValue, filters.timeUnit) &&
      ageFilterPassed
    );
  });

  highlightActiveFilters();
  updateFiltersIndicator();
  currentPage = 1;
  renderPage();
}

function applyDexFilters_old() {
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
    rugScoreMin: document.getElementById('dexFilterRugScoreMin').value ? parseFloat(document.getElementById('dexFilterRugScoreMin').value) : null, 
    rugScoreMax: document.getElementById('dexFilterRugScoreMax').value ? parseFloat(document.getElementById('dexFilterRugScoreMax').value) : null,
    hasData: document.getElementById('dexFilterHasData').value,
    buySellRatio1hMin: document.getElementById('dexFilterBuySellRatio1h').value ? parseFloat(document.getElementById('dexFilterBuySellRatio1h').value) : null,
    buySellRatio24hMin: document.getElementById('dexFilterBuySellRatio24h').value ? parseFloat(document.getElementById('dexFilterBuySellRatio24h').value) : null,
    priceChange1hMin: document.getElementById('dexFilterPriceChange1hMin').value ? parseFloat(document.getElementById('dexFilterPriceChange1hMin').value) : null,
    priceChange6hMin: document.getElementById('dexFilterPriceChange6hMin').value ? parseFloat(document.getElementById('dexFilterPriceChange6hMin').value) : null,
    priceChange24hMin: document.getElementById('dexFilterPriceChange24hMin').value ? parseFloat(document.getElementById('dexFilterPriceChange24hMin').value) : null,
    whaleActivity: document.getElementById('dexFilterWhaleActivity').value.toLowerCase().trim(),
    whaleAmountMin: document.getElementById('dexFilterWhaleAmountMin').value ? parseFloat(document.getElementById('dexFilterWhaleAmountMin').value) : null,
    whalePeriod: document.getElementById('dexFilterWhalePeriod').value,
  };

  filteredData = data.filter(row => {
    const hasDexData = (row.dexscreener_price_usd || 0) > 0;
    const lastDexUpdate = row.last_dexscreener_update || row.updated_at;
    const tokenAgeHours = parseFloat(row.age_hours) || 0;
    
    // Vérification du filtre d'âge des boutons présets
    let ageFilterPassed = true;
    if (currentAgeMin !== null || currentAgeMax !== null) {
      const pairCreatedAt = row.dexscreener_pair_created_at;
      if (pairCreatedAt) {
        const now = new Date();
        const creationTime = parseDateTime(pairCreatedAt);
        if (creationTime && !isNaN(creationTime.getTime())) {
          const ageHours = (now - creationTime) / (1000 * 60 * 60);
          
          if (currentAgeMin !== null && ageHours < currentAgeMin) {
            ageFilterPassed = false;
          }
          if (currentAgeMax !== null && ageHours > currentAgeMax) {
            ageFilterPassed = false;
          }
        } else {
          // Si pas de date de création de paire, exclure du filtre
          ageFilterPassed = false;
        }
      } else {
        // Si pas de date de création de paire, exclure du filtre
        ageFilterPassed = false;
      }
    }

    let whaleFilterPassed = true;
    if (dexFilters.whaleActivity) {
      // D'abord, vérifier si on a des données whale dans les colonnes de base de données
      const whaleActivity1h = row.whale_activity_1h || 0;
      const whaleActivity6h = row.whale_activity_6h || 0;
      const whaleActivity24h = row.whale_activity_24h || 0;
      const whaleMaxAmount1h = row.whale_max_amount_1h || 0;
      const whaleMaxAmount6h = row.whale_max_amount_6h || 0;
      const whaleMaxAmount24h = row.whale_max_amount_24h || 0;
      
      // Ensuite, chercher dans les données whale en temps réel (si disponibles)
      const whaleIndicatorElement = document.getElementById(`whale-activity-${row.address}`);
      let hasRealtimeWhaleActivity = false;
      let realtimeWhaleAmount = 0;
      
      if (whaleIndicatorElement) {
        const whaleText = whaleIndicatorElement.textContent || '';
        // Chercher des montants dans le texte de l'indicateur whale
        const amountMatch = whaleText.match(/\$(\d+(?:\.\d+)?)K/);
        if (amountMatch) {
          realtimeWhaleAmount = parseFloat(amountMatch[1]) * 1000;
          hasRealtimeWhaleActivity = realtimeWhaleAmount > 0;
        }
        // Vérifier aussi les emojis d'activité
        hasRealtimeWhaleActivity = hasRealtimeWhaleActivity || 
          whaleText.includes('🟢') || whaleText.includes('🔴') || 
          whaleText.includes('🟡') || whaleText.includes('⚡');
      }
      
      console.log(`Token ${row.symbol}: whale_activity_1h=${whaleActivity1h}, max_amount_1h=${whaleMaxAmount1h}, realtime=${hasRealtimeWhaleActivity}, amount=${realtimeWhaleAmount}`);
      
      switch (dexFilters.whaleActivity) {
        case 'has_whale':
          whaleFilterPassed = whaleActivity1h > 0 || whaleActivity6h > 0 || whaleActivity24h > 0 || hasRealtimeWhaleActivity;
          break;
        case 'no_whale':
          whaleFilterPassed = whaleActivity1h === 0 && whaleActivity6h === 0 && whaleActivity24h === 0 && !hasRealtimeWhaleActivity;
          break;
        case 'critical_whale':
          whaleFilterPassed = whaleMaxAmount1h >= 50000 || whaleMaxAmount6h >= 50000 || whaleMaxAmount24h >= 50000 || realtimeWhaleAmount >= 50000;
          break;
        case 'recent_whale':
          whaleFilterPassed = whaleActivity1h > 0 || hasRealtimeWhaleActivity;
          break;
      }
    }
    
    // Filtre par montant minimum
    if (dexFilters.whaleAmountMin !== null) {
      const whaleMaxAmount1h = row.whale_max_amount_1h || 0;
      const whaleMaxAmount6h = row.whale_max_amount_6h || 0;
      const whaleMaxAmount24h = row.whale_max_amount_24h || 0;
      
      // Chercher aussi dans les données temps réel
      const whaleIndicatorElement = document.getElementById(`whale-activity-${row.address}`);
      let realtimeWhaleAmount = 0;
      if (whaleIndicatorElement) {
        const whaleText = whaleIndicatorElement.textContent || '';
        const amountMatch = whaleText.match(/\$(\d+(?:\.\d+)?)K/);
        if (amountMatch) {
          realtimeWhaleAmount = parseFloat(amountMatch[1]) * 1000;
        }
      }
      
      const maxWhaleAmount = Math.max(whaleMaxAmount1h, whaleMaxAmount6h, whaleMaxAmount24h, realtimeWhaleAmount);
      if (maxWhaleAmount < dexFilters.whaleAmountMin) {
        whaleFilterPassed = false;
      }
    }

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
      (dexFilters.rugScoreMin === null || (row.rug_score || 50) >= dexFilters.rugScoreMin) && 
      (dexFilters.rugScoreMax === null || (row.rug_score || 50) <= dexFilters.rugScoreMax) &&
      (!dexFilters.hasData || (dexFilters.hasData === 'true' ? hasDexData : !hasDexData)) &&
      (!window.dexTimeValue || !window.dexTimeUnit || isWithinTimeFilter(lastDexUpdate, window.dexTimeValue, window.dexTimeUnit)) &&
      (dexFilters.buySellRatio1hMin === null || 
        ((row.dexscreener_sells_1h || 0) > 0 && 
        (row.dexscreener_buys_1h || 0) / (row.dexscreener_sells_1h || 1) >= dexFilters.buySellRatio1hMin)) &&
      (dexFilters.buySellRatio24hMin === null || 
        ((row.dexscreener_sells_24h || 0) > 0 && 
        (row.dexscreener_buys_24h || 0) / (row.dexscreener_sells_24h || 1) >= dexFilters.buySellRatio24hMin)) &&
      (dexFilters.priceChange1hMin === null || (row.dexscreener_price_change_1h || 0) >= dexFilters.priceChange1hMin) &&
      (dexFilters.priceChange6hMin === null || (row.dexscreener_price_change_6h || 0) >= dexFilters.priceChange6hMin) &&
      (dexFilters.priceChange24hMin === null || (row.dexscreener_price_change_h24 || 0) >= dexFilters.priceChange24hMin) &&
      ageFilterPassed && 
      whaleFilterPassed
    );
  });

  highlightActiveFilters();
  updateFiltersIndicator();
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
    rugScoreMin: document.getElementById('dexFilterRugScoreMin').value ? parseFloat(document.getElementById('dexFilterRugScoreMin').value) : null, 
    rugScoreMax: document.getElementById('dexFilterRugScoreMax').value ? parseFloat(document.getElementById('dexFilterRugScoreMax').value) : null,
    hasData: document.getElementById('dexFilterHasData').value,
    buySellRatio1hMin: document.getElementById('dexFilterBuySellRatio1h').value ? parseFloat(document.getElementById('dexFilterBuySellRatio1h').value) : null,
    buySellRatio24hMin: document.getElementById('dexFilterBuySellRatio24h').value ? parseFloat(document.getElementById('dexFilterBuySellRatio24h').value) : null,
    priceChange1hMin: document.getElementById('dexFilterPriceChange1hMin').value ? parseFloat(document.getElementById('dexFilterPriceChange1hMin').value) : null,
    priceChange6hMin: document.getElementById('dexFilterPriceChange6hMin').value ? parseFloat(document.getElementById('dexFilterPriceChange6hMin').value) : null,
    priceChange24hMin: document.getElementById('dexFilterPriceChange24hMin').value ? parseFloat(document.getElementById('dexFilterPriceChange24hMin').value) : null,
    
    // === UTILISER LES VARIABLES AU LIEU DES ÉLÉMENTS HTML ===
    whaleActivity: currentWhaleFilter.toLowerCase().trim(),
    whaleAmountMin: currentWhaleAmountMin,
    whalePeriod: currentWhalePeriod,
  };

  filteredData = data.filter(row => {
    const hasDexData = (row.dexscreener_price_usd || 0) > 0;
    const lastDexUpdate = row.last_dexscreener_update || row.updated_at;
    const tokenAgeHours = parseFloat(row.age_hours) || 0;
    
    // Vérification du filtre d'âge des boutons présets
    let ageFilterPassed = true;
    if (currentAgeMin !== null || currentAgeMax !== null) {
      const pairCreatedAt = row.dexscreener_pair_created_at;
      if (pairCreatedAt) {
        const now = new Date();
        const creationTime = parseDateTime(pairCreatedAt);
        if (creationTime && !isNaN(creationTime.getTime())) {
          const ageHours = (now - creationTime) / (1000 * 60 * 60);
          
          if (currentAgeMin !== null && ageHours < currentAgeMin) {
            ageFilterPassed = false;
          }
          if (currentAgeMax !== null && ageHours > currentAgeMax) {
            ageFilterPassed = false;
          }
        } else {
          ageFilterPassed = false;
        }
      } else {
        ageFilterPassed = false;
      }
    }

    let whaleFilterPassed = true;
    if (dexFilters.whaleActivity) {
      // Vérifier les données whale dans les colonnes de base de données
      const whaleActivity1h = row.whale_activity_1h || 0;
      const whaleActivity6h = row.whale_activity_6h || 0;
      const whaleActivity24h = row.whale_activity_24h || 0;
      const whaleMaxAmount1h = row.whale_max_amount_1h || 0;
      const whaleMaxAmount6h = row.whale_max_amount_6h || 0;
      const whaleMaxAmount24h = row.whale_max_amount_24h || 0;
      
      // Chercher dans les données whale en temps réel
      const whaleIndicatorElement = document.getElementById(`whale-activity-${row.address}`);
      let hasRealtimeWhaleActivity = false;
      let realtimeWhaleAmount = 0;
      
      if (whaleIndicatorElement) {
        const whaleText = whaleIndicatorElement.textContent || '';
        const amountMatch = whaleText.match(/\$(\d+(?:\.\d+)?)K/);
        if (amountMatch) {
          realtimeWhaleAmount = parseFloat(amountMatch[1]) * 1000;
          hasRealtimeWhaleActivity = realtimeWhaleAmount > 0;
        }
        hasRealtimeWhaleActivity = hasRealtimeWhaleActivity || 
          whaleText.includes('🟢') || whaleText.includes('🔴') || 
          whaleText.includes('🟡') || whaleText.includes('⚡');
      }
      
      // Debug temporaire - supprimez après test
      if (dexFilters.whaleActivity === 'has_whale' && (whaleActivity1h > 0 || hasRealtimeWhaleActivity)) {
        console.log(`Token ${row.symbol}: whale_activity_1h=${whaleActivity1h}, realtime=${hasRealtimeWhaleActivity}`);
      }
      
      switch (dexFilters.whaleActivity) {
        case 'has_whale':
          whaleFilterPassed = whaleActivity1h > 0 || whaleActivity6h > 0 || whaleActivity24h > 0 || hasRealtimeWhaleActivity;
          break;
        case 'no_whale':
          whaleFilterPassed = whaleActivity1h === 0 && whaleActivity6h === 0 && whaleActivity24h === 0 && !hasRealtimeWhaleActivity;
          break;
        case 'critical_whale':
          whaleFilterPassed = whaleMaxAmount1h >= 50000 || whaleMaxAmount6h >= 50000 || whaleMaxAmount24h >= 50000 || realtimeWhaleAmount >= 50000;
          break;
        case 'recent_whale':
          whaleFilterPassed = whaleActivity1h > 0 || hasRealtimeWhaleActivity;
          break;
      }
    }
    
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
      (dexFilters.rugScoreMin === null || (row.rug_score || 50) >= dexFilters.rugScoreMin) && 
      (dexFilters.rugScoreMax === null || (row.rug_score || 50) <= dexFilters.rugScoreMax) &&
      (!dexFilters.hasData || (dexFilters.hasData === 'true' ? hasDexData : !hasDexData)) &&
      (!window.dexTimeValue || !window.dexTimeUnit || isWithinTimeFilter(lastDexUpdate, window.dexTimeValue, window.dexTimeUnit)) &&
      (dexFilters.buySellRatio1hMin === null || 
        ((row.dexscreener_sells_1h || 0) > 0 && 
        (row.dexscreener_buys_1h || 0) / (row.dexscreener_sells_1h || 1) >= dexFilters.buySellRatio1hMin)) &&
      (dexFilters.buySellRatio24hMin === null || 
        ((row.dexscreener_sells_24h || 0) > 0 && 
        (row.dexscreener_buys_24h || 0) / (row.dexscreener_sells_24h || 1) >= dexFilters.buySellRatio24hMin)) &&
      (dexFilters.priceChange1hMin === null || (row.dexscreener_price_change_1h || 0) >= dexFilters.priceChange1hMin) &&
      (dexFilters.priceChange6hMin === null || (row.dexscreener_price_change_6h || 0) >= dexFilters.priceChange6hMin) &&
      (dexFilters.priceChange24hMin === null || (row.dexscreener_price_change_h24 || 0) >= dexFilters.priceChange24hMin) &&
      ageFilterPassed && 
      whaleFilterPassed
    );
  });

  // Debug temporaire
  if (currentWhaleFilter === 'has_whale') {
    console.log(`Filtre whale "has_whale" appliqué: ${filteredData.length} tokens trouvés`);
  }

  highlightActiveFilters();
  updateFiltersIndicator();
  currentPage = 1;
  renderPage();
}

function testWhaleButtonsComplete() {
  console.log('=== TEST COMPLET DES BOUTONS WHALE ===');
  
  // Vérifier que les boutons existent
  const whaleButtons = document.querySelectorAll('.whale-preset-btn');
  console.log(`Nombre de boutons whale trouvés: ${whaleButtons.length}`);
  
  // Tester chaque bouton
  whaleButtons.forEach((btn, index) => {
    console.log(`Bouton ${index}: ${btn.textContent} - onclick: ${btn.getAttribute('onclick')}`);
  });
  
  // Tester les variables globales
  console.log('Variables whale avant test:', {
    currentWhaleFilter,
    currentWhaleAmountMin,
    currentWhalePeriod
  });
  
  // Test programmatique complet
  console.log('\n=== TEST PROGRAMMATIQUE ===');
  if (whaleButtons.length > 0) {
    console.log('1. Test "Avec Whales"');
    setWhaleActivityFilter('has_whale', whaleButtons[0]);
    
    setTimeout(() => {
      console.log('2. Test "Tous tokens"');
      clearWhaleActivityFilter(whaleButtons[3]);
      
      console.log('Variables whale après test:', {
        currentWhaleFilter,
        currentWhaleAmountMin,
        currentWhalePeriod
      });
    }, 1000);
  }
}
// === NOUVELLES FONCTIONS ===

// Fonction pour mettre à jour l'indicateur de filtres
function updateFiltersIndicator() {
  let count = 0;
  
  // Compter les filtres de base actifs
  const baseInputs = [
    'filterSymbol', 'filterBondingStatus', 'filterProgressMin', 'filterProgressMax',
    'filterPriceMin', 'filterPriceMax', 'filterScoreMin', 'filterScoreMax',
    'filterLiquidityMin', 'filterLiquidityMax', 'filterVolumeMin', 'filterVolumeMax',
    'filterHoldersMin', 'filterHoldersMax', 'filterAgeMin', 'filterAgeMax',
    'filterRiskMin', 'filterRiskMax', 'filterDiscoveredAt', 'filterTimeValue',
    'dexFilterPriceChange1hMin', 'dexFilterPriceChange6hMin', 'dexFilterPriceChange24hMin',
    //'dexFilterWhaleActivity', 'dexFilterWhaleAmountMin', 'dexFilterWhalePeriod'
  ];
  
  baseInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el && el.value.trim() !== '') count++;
  });
  
  // Compter les filtres DexScreener actifs
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
  
  // Compter les filtres d'âge et temporels
  if (currentAgeMin !== null || currentAgeMax !== null) count++;
  if (window.dexTimeValue && window.dexTimeUnit) count++;
  
  if (currentWhaleFilter !== '') count++;
  if (currentWhaleAmountMin !== null) count++;
  if (currentWhalePeriod !== null) count++;

  activeFiltersCount = count;
  
  const indicator = document.getElementById('filtersIndicator');
  const filterCount = indicator.querySelector('.filter-count');
  
  if (count === 0) {
    filterCount.textContent = 'Aucun filtre actif';
    indicator.style.opacity = '0.6';
  } else {
    filterCount.textContent = `${count} filtre${count > 1 ? 's' : ''} actif${count > 1 ? 's' : ''}`;
    indicator.style.opacity = '1';
  }
}

// Fonction d'export des données
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
  // Définir les colonnes à exporter
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
      // Échapper les guillemets et virgules
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

// Fonction pour basculer entre les thèmes
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

// Charger le thème sauvegardé
function loadSavedTheme() {
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    document.getElementById('themeToggle').textContent = '🌙 Mode Sombre';
  }
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
      const rugScore = r.rug_score || 50; 
      const rugScoreClass = rugScore <= 30 ? 'rug-good' : rugScore <= 60 ? 'rug-medium' : 'rug-bad';
      const rugcheckUrl = `https://rugcheck.xyz/tokens/${r.address}`;
      const rugScoreDisplay = `
        <div style="display: flex; align-items: center; gap: 4px; justify-content: center;">
          <span class="rug-score ${rugScoreClass}" title="Score RugCheck: ${rugScore}/100 (plus bas = mieux)">${rugScore}</span>
          <a href="${rugcheckUrl}" target="_blank" style="color: #00d4ff; text-decoration: none; font-size: 0.8rem;" title="Vérifier sur RugCheck.xyz">
            🔍
          </a>
        </div>
      `;
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
          <td>${rugScoreDisplay}</td>
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
          <td id="whale-activity-${r.address}">
  <span class="whale-indicator-loading">⏳</span>
</td>
          <td>${dexUrlDisplay}</td>
          <td class="${pairCreatedTimeAgo.className}" title="${pairCreatedFull}">${pairCreatedTimeAgo.text}</td>
          <td class="${dexUpdateTimeAgo.className}" title="${dexUpdateFull}">${dexUpdateTimeAgo.text}</td>
        </tr>
      `;
    }).join('');
    
    rows.forEach(r => {
      setTimeout(() => checkTokenHistory(r.address), Math.random() * 1000);
      setTimeout(() => {
      console.log('Triggering whale indicators update after table render');
      updateWhaleIndicators();
    }, 1500);
    });
  }
}

function testWhaleIndicators() {
  console.log('=== TEST WHALE INDICATORS ===');
  console.log('Current tab:', currentTab);
  console.log('Filtered data:', filteredData.length, 'tokens');
  
  const whaleElements = document.querySelectorAll('[id^="whale-activity-"]');
  console.log('Whale elements found:', whaleElements.length);
  
  whaleElements.forEach(el => {
    console.log('Element:', el.id, 'Content:', el.innerHTML);
  });
  
  debugWhaleAPI();
  updateWhaleIndicators();
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
  currentAgeMin = null;
  currentAgeMax = null;
  currentWhaleFilter = '';
  currentWhaleAmountMin = null;
  currentWhalePeriod = null;
  filteredData = [...data];
  currentPage = 1;
  updateFiltersIndicator();
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



// === FONCTIONS WHALE ACTIVITY ===

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
    document.getElementById('whaleVolume1h').textContent = `$${(summary.total_volume_usd || 0).toLocaleString()}`;
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
    
    // Préparer les liens
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
    // Feedback visuel rapide
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
    
    // Essayer différentes structures de données
    const transactions = data.whale_transactions || data.transactions || data.data || [];
    
    // Indexer par token_address (sans logs)
    transactions.forEach(tx => {
      const tokenAddr = tx.token_address || tx.address;
      if (tokenAddr) {
        if (!whaleByToken[tokenAddr] || 
            new Date(tx.timestamp) > new Date(whaleByToken[tokenAddr].timestamp)) {
          whaleByToken[tokenAddr] = tx;
        }
      }
    });
    
    // Mettre à jour les indicateurs (sans logs individuels)
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
    
    // Log résumé seulement
    console.log(`Whale indicators updated: ${updatedCount} elements, ${foundCount} with activity, ${transactions.length} total transactions`);
    
  } catch (error) {
    console.error('Error updating whale indicators:', error);
    
    // En cas d'erreur, remplacer les sabliers par "Erreur" (sans logs)
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

async function debugWhaleAPI() {
  try {
    console.log('=== TESTING DIFFERENT WHALE PERIODS ===');
    
    // Tester 1h, 6h, 24h
    for (const hours of [1, 6, 24]) {
      const response = await fetch(`/api/whale-activity?hours=${hours}&limit=100`);
      const data = await response.json();
      console.log(`Period ${hours}h: ${data.whale_transactions?.length || 0} transactions`);
      
      if (data.whale_transactions?.length > 0) {
        console.log(`  Latest: ${data.whale_transactions[0].timestamp} - $${data.whale_transactions[0].amount_usd}`);
      }
    }
    
    return data;
  } catch (error) {
    console.error('Whale API error:', error);
  }
}

function generateWhaleIndicator(whaleActivity) {
  if (!whaleActivity) {
    return '<span class="whale-indicator-none">💤 No activity</span>';
  }
  
  const amount = whaleActivity.amount_usd || 0;
  const type = whaleActivity.transaction_type;
  const timeAgo = getTimeAgoExtended(whaleActivity.timestamp); // Nouvelle fonction
  
  if (amount >= 100000) {
    return `<span class="whale-indicator-critical">⚡ $${(amount/1000).toFixed(0)}K (${timeAgo})</span>`;
  } else if (amount >= 10000) {
    if (type === 'SELL' || type === 'sell') {
      return `<span class="whale-indicator-sell">🔴 -$${(amount/1000).toFixed(0)}K (${timeAgo})</span>`;
    } else {
      return `<span class="whale-indicator-buy">🟢 +$${(amount/1000).toFixed(0)}K (${timeAgo})</span>`;
    }
  } else if (amount >= 1000) {
    if (type === 'SELL' || type === 'sell') {
      return `<span class="whale-indicator-medium">🟠 -$${(amount/1000).toFixed(1)}K (${timeAgo})</span>`;
    } else {
      return `<span class="whale-indicator-medium">🟡 +$${(amount/1000).toFixed(1)}K (${timeAgo})</span>`;
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

function debugWhaleIndicators() {
  console.log('Current tab:', currentTab);
  console.log('Filtered data length:', filteredData.length);
  
  // Vérifier combien d'éléments whale-activity existent
  const whaleElements = document.querySelectorAll('[id^="whale-activity-"]');
  console.log('Found whale activity elements:', whaleElements.length);
  
  // Vérifier combien ont encore le sablier
  const loadingElements = document.querySelectorAll('[id^="whale-activity-"] .whale-indicator-loading');
  console.log('Elements still loading:', loadingElements.length);
  
  // Forcer la mise à jour immédiate
  updateWhaleIndicators();
}


function getTimeAgoShort(timestamp) {
  const now = new Date();
  const time = new Date(timestamp);
  const diffMinutes = Math.floor((now - time) / (1000 * 60));
  
  if (diffMinutes < 1) return 'now';
  if (diffMinutes < 60) return `${diffMinutes}m`;
  return `${Math.floor(diffMinutes/60)}h`;
}

//--------------------FIN FONCTIONS WHALES-----------------------------

function setWhaleActivityFilter_old(type, btn) {
  document.getElementById('dexFilterWhaleActivity').value = type;
  
  // Retirer active de tous les boutons whale
  document.querySelectorAll('.whale-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyDexFiltersWithWhaleUpdate();
}

function setWhaleActivityFilter(type, btn) {
  // Stocker la valeur dans une variable au lieu d'un élément HTML
  currentWhaleFilter = type;
  
  // Retirer active de tous les boutons whale
  document.querySelectorAll('.whale-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  // Appliquer directement le filtre
  applyDexFilters();
}


function debugWhaleFilters() {
  console.log('=== DEBUG WHALE FILTERS ===');
  
  // Compter les tokens avec activité whale
  let dbWhaleCount = 0;
  let indicatorWhaleCount = 0;
  
  data.forEach(token => {
    const whaleActivity1h = token.whale_activity_1h || 0;
    const whaleMaxAmount1h = token.whale_max_amount_1h || 0;
    
    if (whaleActivity1h > 0 || whaleMaxAmount1h > 0) {
      dbWhaleCount++;
    }
    
    const whaleIndicatorElement = document.getElementById(`whale-activity-${token.address}`);
    if (whaleIndicatorElement) {
      const whaleText = whaleIndicatorElement.textContent || '';
      if (!whaleText.includes('💤') && !whaleText.includes('⏳') && !whaleText.includes('❌')) {
        indicatorWhaleCount++;
      }
    }
  });
  
  console.log(`Tokens avec whale en DB: ${dbWhaleCount}`);
  console.log(`Tokens avec whale dans indicateurs: ${indicatorWhaleCount}`);
  console.log(`Total tokens: ${data.length}`);
  console.log(`Filtered tokens: ${filteredData.length}`);
  
  // Tester le filtre "has_whale" sans logs détaillés
  const currentFilter = document.getElementById('dexFilterWhaleActivity').value;
  console.log(`Filtre whale actuel: "${currentFilter}"`);
  
  if (currentFilter === 'has_whale') {
    console.log('Test du filtre "has_whale":');
    let passedCount = 0;
    
    data.forEach(row => {
      const whaleActivity1h = row.whale_activity_1h || 0;
      const whaleActivity6h = row.whale_activity_6h || 0; 
      const whaleActivity24h = row.whale_activity_24h || 0;
      
      const whaleIndicatorElement = document.getElementById(`whale-activity-${row.address}`);
      let hasRealtimeWhaleActivity = false;
      
      if (whaleIndicatorElement) {
        const whaleText = whaleIndicatorElement.textContent || '';
        hasRealtimeWhaleActivity = whaleText.includes('🟢') || whaleText.includes('🔴') || 
          whaleText.includes('🟡') || whaleText.includes('⚡') || whaleText.includes('K');
      }
      
      const hasWhale = whaleActivity1h > 0 || whaleActivity6h > 0 || whaleActivity24h > 0 || hasRealtimeWhaleActivity;
      if (hasWhale) passedCount++;
    });
    
    console.log(`Tokens qui passent le filtre "has_whale": ${passedCount}`);
  }
}

function quickWhaleTest() {
  console.log('=== QUICK WHALE TEST ===');
  
  // Vérifier les éléments whale visibles actuellement
  const whaleElements = document.querySelectorAll('[id^="whale-activity-"]');
  console.log(`Éléments whale dans le DOM: ${whaleElements.length}`);
  
  let activeElements = 0;
  let loadingElements = 0;
  let errorElements = 0;
  
  whaleElements.forEach(el => {
    const text = el.textContent || '';
    if (text.includes('⏳')) loadingElements++;
    else if (text.includes('❌')) errorElements++;
    else if (!text.includes('💤')) activeElements++;
  });
  
  console.log(`- En chargement: ${loadingElements}`);
  console.log(`- Avec activité: ${activeElements}`);
  console.log(`- En erreur: ${errorElements}`);
  console.log(`- Sans activité: ${whaleElements.length - loadingElements - activeElements - errorElements}`);
  
  // Forcer une mise à jour
  updateWhaleIndicators();
}

async function createTestWhaleDataAndTest() {
  console.log('=== CRÉATION DONNÉES WHALE DE TEST ===');
  
  try {
    // Créer des données de test
    const response = await fetch('/api/test-whale-data');
    const result = await response.json();
    console.log('Données whale créées:', result);
    
    // Attendre un peu puis recharger les données
    setTimeout(async () => {
      console.log('Rechargement des données...');
      await fetchData();
      
      setTimeout(() => {
        console.log('Test des colonnes whale après rechargement:');
        checkWhaleColumns();
        
        setTimeout(() => {
          console.log('Test du filtre has_whale:');
          testWhaleFilter('has_whale');
        }, 1000);
      }, 1000);
    }, 2000);
    
  } catch (error) {
    console.error('Erreur:', error);
  }
}

async function debugWhaleEndpoint() {
  try {
    const response = await fetch('/api/debug-whale-data');
    const data = await response.json();
    console.log('=== DEBUG WHALE ENDPOINT ===');
    console.log('Échantillon transactions whale:', data.whale_transactions_sample);
    console.log('Tokens qui matchent:', data.matching_tokens);
    console.log('Nombre de tokens avec whale activity:', data.tokens_with_whale_activity);
  } catch (error) {
    console.error('Erreur debug endpoint:', error);
  }
}


function testWhaleFilter(filterType) {
  console.log(`=== TEST FILTRE WHALE: ${filterType} ===`);
  
  // Simuler la sélection du filtre
  document.getElementById('dexFilterWhaleActivity').value = filterType;
  
  // Compter combien de tokens passeraient le filtre
  let passedCount = 0;
  
  data.forEach(row => {
    const whaleActivity1h = row.whale_activity_1h || 0;
    const whaleActivity6h = row.whale_activity_6h || 0;
    const whaleActivity24h = row.whale_activity_24h || 0;
    const whaleMaxAmount1h = row.whale_max_amount_1h || 0;
    const whaleMaxAmount6h = row.whale_max_amount_6h || 0;
    const whaleMaxAmount24h = row.whale_max_amount_24h || 0;
    
    const whaleIndicatorElement = document.getElementById(`whale-activity-${row.address}`);
    let hasRealtimeWhaleActivity = false;
    let realtimeWhaleAmount = 0;
    
    if (whaleIndicatorElement) {
      const whaleText = whaleIndicatorElement.textContent || '';
      const amountMatch = whaleText.match(/\$(\d+(?:\.\d+)?)K/);
      if (amountMatch) {
        realtimeWhaleAmount = parseFloat(amountMatch[1]) * 1000;
        hasRealtimeWhaleActivity = realtimeWhaleAmount > 0;
      }
      hasRealtimeWhaleActivity = hasRealtimeWhaleActivity || 
        whaleText.includes('🟢') || whaleText.includes('🔴') || 
        whaleText.includes('🟡') || whaleText.includes('⚡');
    }
    
    let passed = false;
    switch (filterType) {
      case 'has_whale':
        passed = whaleActivity1h > 0 || whaleActivity6h > 0 || whaleActivity24h > 0 || hasRealtimeWhaleActivity;
        break;
      case 'critical_whale':
        passed = whaleMaxAmount1h >= 50000 || whaleMaxAmount6h >= 50000 || whaleMaxAmount24h >= 50000 || realtimeWhaleAmount >= 50000;
        break;
      case 'recent_whale':
        passed = whaleActivity1h > 0 || hasRealtimeWhaleActivity;
        break;
    }
    
    if (passed) {
      passedCount++;
      if (passedCount <= 3) { // Afficher seulement les 3 premiers
        console.log(`✓ ${row.symbol}: DB(1h:${whaleActivity1h}, max:${whaleMaxAmount1h}) RT(${realtimeWhaleAmount})`);
      }
    }
  });
  
  console.log(`Total tokens qui passent le filtre "${filterType}": ${passedCount}`);
  
  // Remettre le filtre à vide
  document.getElementById('dexFilterWhaleActivity').value = '';
}

// === FONCTION POUR VÉRIFIER LES COLONNES WHALE DISPONIBLES ===
function checkWhaleColumns() {
  if (data.length === 0) {
    console.log('Aucune donnée disponible');
    return;
  }
  
  const firstToken = data[0];
  const whaleColumns = Object.keys(firstToken).filter(key => key.includes('whale'));
  console.log('=== COLONNES WHALE DISPONIBLES ===');
  console.log(whaleColumns);
  
  // Afficher seulement les tokens avec des données whale
  const tokensWithWhale = data.filter(token => 
    whaleColumns.some(col => token[col] && token[col] > 0)
  ).slice(0, 5); // Limiter à 5 tokens max
  
  console.log('\n=== ÉCHANTILLON TOKENS AVEC ACTIVITÉ WHALE ===');
  tokensWithWhale.forEach(token => {
    const whaleData = whaleColumns.reduce((obj, col) => {
      if (token[col] && token[col] > 0) obj[col] = token[col];
      return obj;
    }, {});
    if (Object.keys(whaleData).length > 0) {
      console.log(`${token.symbol}:`, whaleData);
    }
  });
}

async function applyDexFiltersWithWhaleUpdate() {
  // S'assurer que les indicateurs whale sont à jour avant le filtrage
  await updateWhaleIndicators();
  
  // Attendre un peu pour que les indicateurs se mettent à jour
  setTimeout(() => {
    applyDexFilters();
  }, 1000);
}

function clearWhaleActivityFilter_old(btn) {
  document.getElementById('dexFilterWhaleActivity').value = '';
  document.getElementById('dexFilterWhaleAmountMin').value = '';
  document.getElementById('dexFilterWhalePeriod').value = '';
  
  document.querySelectorAll('.whale-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyDexFilters();
}

function clearWhaleActivityFilter(btn) {
  // Réinitialiser toutes les variables whale
  currentWhaleFilter = '';
  currentWhaleAmountMin = null;
  currentWhalePeriod = null;
  
  document.querySelectorAll('.whale-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyDexFilters();
}

function highlightActiveFilters() {
  // Base filters
  const baseInputs = [
    'filterSymbol', 'filterBondingStatus', 'filterProgressMin', 'filterProgressMax',
    'filterPriceMin', 'filterPriceMax', 'filterScoreMin', 'filterScoreMax',
    'filterLiquidityMin', 'filterLiquidityMax', 'filterVolumeMin', 'filterVolumeMax',
    'filterHoldersMin', 'filterHoldersMax', 'filterAgeMin', 'filterAgeMax',
    'filterRiskMin', 'filterRiskMax', 'filterDiscoveredAt', 'filterTimeValue', 
    'filterTimeUnit', 'dexFilterRugScoreMin', 'dexFilterRugScoreMax',
    //'dexFilterWhaleActivity', 'dexFilterWhaleAmountMin', 'dexFilterWhalePeriod'
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
    'dexFilterBuys24hMin', 'dexFilterSells24hMax', 'dexFilterLiquidityQuoteMin', 'dexFilterHasData',
    //'dexFilterPriceChange1hMin', 'dexFilterPriceChange6hMin', 'dexFilterPriceChange24hMin'
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
  loadSavedTheme();
  fetchData();
  startAutoRefresh();
  updateRefreshStatus();
  updateFiltersIndicator();


  startWhaleAutoRefresh();

   setTimeout(() => {
    updateWhaleIndicators();
  }, 2000);
});