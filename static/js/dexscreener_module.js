// =============================================================================
// MODULE DEXSCREENER - Gestion des filtres et affichage de l'onglet DexScreener
// =============================================================================

// Variables globales pour les filtres DexScreener
let currentAgeMin = null;
let currentAgeMax = null;
let currentHoldersMin = null;
let currentHoldersMax = null;
let currentHoldersCategory = '';
let currentWhaleFilter = '';
let currentWhaleAmountMin = null;
let currentWhalePeriod = null;
let currentStrategy = null;

// Définition des stratégies de trading
const strategies = {
  momentum: {
    name: "🚀 Momentum",
    filters: {
      dexFilterPriceChange1hMin: 10,
      dexFilterPriceChange6hMin: 20,
      dexFilterVolume24hMin: 50000,
      dexFilterTxns24hMin: 100,
      dexFilterBuySellRatio24h: 1.5,
      dexFilterHoldersMin: 200
    }
  },
  early: {
    name: "💎 Early Gems", 
    filters: {
      ageMin: 0,
      ageMax: 6,
      dexFilterRugScoreMax: 30,
      dexFilterLiquidityQuoteMin: 10000,
      dexFilterMarketCapMax: 100000,
      dexFilterHasData: 'true',
      dexFilterHoldersMin: 50,
      dexFilterHoldersMax: 500
    }
  },
  whale: {
    name: "🐋 Whale Magnet",
    filters: {
      whaleActivity: 'has_whale',
      dexFilterVolume1hMin: 5000,
      dexFilterTxns24hMin: 50,
      dexFilterLiquidityQuoteMin: 25000,
      dexFilterHoldersMin: 300
    }
  },
  breakout: {
    name: "⚡ Breakout",
    filters: {
      dexFilterPriceChange24hMin: 50,
      dexFilterVolume24hMin: 100000,
      dexFilterBuySellRatio1h: 2.0,
      dexFilterMarketCapMin: 500000,
      dexFilterTxns24hMin: 200
    }
  },
  safe: {
    name: "🛡️ Safe Growth",
    filters: {
      dexFilterRugScoreMax: 20,
      dexFilterPriceChange24hMin: 5,
      dexFilterPriceChange24hMax: 30,
      ageMin: 24,
      ageMax: 168,
      dexFilterLiquidityQuoteMin: 50000,
      dexFilterBuySellRatio24h: 1.2,
      dexFilterHoldersMin: 1000,
      dexFilterHoldersDistribution: 'good'
    }
  }
};

// =============================================================================
// FONCTIONS DE FILTRAGE HOLDERS
// =============================================================================

function setHoldersFilter(category, btn) {
  currentHoldersCategory = category;
  
  const ranges = {
    'microcap': { min: 0, max: 100 },
    'small': { min: 100, max: 500 },
    'medium': { min: 500, max: 2000 },
    'large': { min: 2000, max: 10000 },
    'mega': { min: 10000, max: null }
  };
  
  const range = ranges[category];
  if (range) {
    currentHoldersMin = range.min;
    currentHoldersMax = range.max;
    
    const minElement = document.getElementById('dexFilterHoldersMin');
    const maxElement = document.getElementById('dexFilterHoldersMax');
    
    if (minElement) minElement.value = range.min || '';
    if (maxElement) maxElement.value = range.max || '';
  }

  document.querySelectorAll('.holders-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  console.log(`🎯 Filtre holders appliqué: ${category} (${currentHoldersMin}-${currentHoldersMax})`);
  applyDexFilters();
}

function clearHoldersFilter(btn) {
  currentHoldersMin = null;
  currentHoldersMax = null;
  currentHoldersCategory = '';
  
  const elementsToReset = [
    'dexFilterHoldersMin', 'dexFilterHoldersMax', 
    'dexFilterHoldersGrowth', 'dexFilterHoldersDistribution'
  ];
  
  elementsToReset.forEach(id => {
    const element = document.getElementById(id);
    if (element) {
      element.value = '';
      element.classList.remove('filter-active');
    }
  });
  
  document.querySelectorAll('.holders-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  console.log('🧹 Filtres holders réinitialisés');
  applyDexFilters();
}

function getHoldersDisplay(holders, holderDistribution) {
  if (!holders || holders === 0) {
    return '<span class="holders-indicator holders-micro">0</span>';
  }
  
  let category, categoryClass;
  if (holders < 100) {
    category = 'MICRO';
    categoryClass = 'holders-micro';
  } else if (holders < 500) {
    category = 'SMALL';
    categoryClass = 'holders-small';
  } else if (holders < 2000) {
    category = 'MED';
    categoryClass = 'holders-medium';
  } else if (holders < 10000) {
    category = 'LARGE';
    categoryClass = 'holders-large';
  } else {
    category = 'MEGA';
    categoryClass = 'holders-mega';
  }
  
  const distributionInfo = holderDistribution && holderDistribution !== 'Unknown' ? 
    `<br><small style="color: #888; font-size: 0.65rem;" title="${holderDistribution}">${holderDistribution.substring(0, 20)}...</small>` : '';
  
  return `
    <div style="text-align: center;">
      <span class="holders-indicator ${categoryClass}" title="${holders} holders (${category})">${holders.toLocaleString()}</span>
      ${distributionInfo}
    </div>
  `;
}

// =============================================================================
// FONCTIONS DE STRATÉGIES DE TRADING
// =============================================================================

function applyStrategy(strategyName, btn) {
  resetDexFilters();
  
  currentStrategy = strategyName;
  
  document.querySelectorAll('.strategy-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  const strategy = strategies[strategyName];
  if (strategy && strategy.filters) {
    applyStrategyFilters(strategy.filters);
  }
  
  console.log(`📊 Stratégie appliquée: ${strategy.name}`);
  
  setTimeout(() => {
    applyDexFilters();
  }, 100);
}

function applyStrategyFilters(filters) {
  Object.keys(filters).forEach(filterKey => {
    const value = filters[filterKey];
    
    if (filterKey === 'ageMin') {
      currentAgeMin = value;
      return;
    }
    if (filterKey === 'ageMax') {
      currentAgeMax = value;
      return;
    }
    if (filterKey === 'whaleActivity') {
      currentWhaleFilter = value;
      return;
    }
    if (filterKey === 'dexFilterHoldersMin') {
      currentHoldersMin = value;
      const element = document.getElementById('dexFilterHoldersMin');
      if (element) element.value = value;
      return;
    }
    if (filterKey === 'dexFilterHoldersMax') {
      currentHoldersMax = value;
      const element = document.getElementById('dexFilterHoldersMax');
      if (element) element.value = value;
      return;
    }
    
    const element = document.getElementById(filterKey);
    if (element) {
      element.value = value;
      element.classList.add('filter-active');
    }
  });
}

function resetDexFilters() {
  const dexFilterIds = [
    'dexFilterSymbol', 'dexFilterStatus', 'dexFilterPriceMin', 'dexFilterPriceMax',
    'dexFilterMarketCapMin', 'dexFilterMarketCapMax', 'dexFilterVolume1hMin',
    'dexFilterVolume6hMin', 'dexFilterVolume24hMin', 'dexFilterTxns24hMin',
    'dexFilterBuys24hMin', 'dexFilterSells24hMax', 'dexFilterLiquidityQuoteMin',
    'dexFilterHasData', 'dexFilterBuySellRatio1h', 'dexFilterBuySellRatio24h',
    'dexFilterRugScoreMin', 'dexFilterRugScoreMax', 'dexFilterPriceChange1hMin',
    'dexFilterPriceChange6hMin', 'dexFilterPriceChange24hMin', 'dexFilterPriceChange24hMax',
    'dexFilterHoldersMin', 'dexFilterHoldersMax', 
    'dexFilterHoldersGrowth', 'dexFilterHoldersDistribution'
  ];
  
  dexFilterIds.forEach(id => {
    const element = document.getElementById(id);
    if (element) {
      element.value = '';
      element.classList.remove('filter-active');
    }
  });
  
  // Réinitialiser les variables spéciales
  currentAgeMin = null;
  currentAgeMax = null;
  currentWhaleFilter = '';
  currentWhaleAmountMin = null;
  currentWhalePeriod = null;
  window.dexTimeValue = null;
  window.dexTimeUnit = null;
  currentHoldersMin = null;
  currentHoldersMax = null;
  currentHoldersCategory = '';
  
  // Désactiver tous les boutons présets
  document.querySelectorAll('#dexscreener-content .preset-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelectorAll('.holders-preset-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelectorAll('.whale-preset-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  
  currentStrategy = null;
}

// =============================================================================
// FONCTIONS DE FILTRAGE PAR ÂGE
// =============================================================================

function setAgeFilter(minHours, maxHours, unit, btn) {
  currentAgeMin = minHours;
  currentAgeMax = maxHours;
  
  document.querySelectorAll('#dexscreener-content .age-presets .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyDexFilters();
}

function clearAgeFilter(btn) {
  currentAgeMin = null;
  currentAgeMax = null;
  
  document.querySelectorAll('#dexscreener-content .age-presets .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyDexFilters();
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

// =============================================================================
// FONCTIONS DE FILTRAGE WHALE
// =============================================================================

function setWhaleActivityFilter(type, btn) {
  currentWhaleFilter = type;
  
  document.querySelectorAll('.whale-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyDexFilters();
}

function clearWhaleActivityFilter(btn) {
  currentWhaleFilter = '';
  currentWhaleAmountMin = null;
  currentWhalePeriod = null;
  
  document.querySelectorAll('.whale-preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyDexFilters();
}

// =============================================================================
// FONCTION PRINCIPALE DE FILTRAGE DEXSCREENER
// =============================================================================

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
    priceChange24hMax: document.getElementById('dexFilterPriceChange24hMax').value ? parseFloat(document.getElementById('dexFilterPriceChange24hMax').value) : null,
    whaleActivity: currentWhaleFilter.toLowerCase().trim(),
    whaleAmountMin: currentWhaleAmountMin,
    whalePeriod: currentWhalePeriod,
  };

  // Utiliser la variable globale `data` et `filteredData` du fichier principal
  window.filteredData = window.data.filter(row => {
    const hasDexData = (row.dexscreener_price_usd || 0) > 0;
    const lastDexUpdate = row.last_dexscreener_update || row.updated_at;
    
    // Vérification du filtre d'âge des boutons présets
    let ageFilterPassed = true;
    if (currentAgeMin !== null || currentAgeMax !== null) {
      const pairCreatedAt = row.dexscreener_pair_created_at;
      if (pairCreatedAt) {
        const now = new Date();
        const creationTime = window.parseDateTime(pairCreatedAt);
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
      (!window.dexTimeValue || !window.dexTimeUnit || window.isWithinTimeFilter(lastDexUpdate, window.dexTimeValue, window.dexTimeUnit)) &&
      (dexFilters.buySellRatio1hMin === null || 
        ((row.dexscreener_sells_1h || 0) > 0 && 
        (row.dexscreener_buys_1h || 0) / (row.dexscreener_sells_1h || 1) >= dexFilters.buySellRatio1hMin)) &&
      (dexFilters.buySellRatio24hMin === null || 
        ((row.dexscreener_sells_24h || 0) > 0 && 
        (row.dexscreener_buys_24h || 0) / (row.dexscreener_sells_24h || 1) >= dexFilters.buySellRatio24hMin)) &&
      (dexFilters.priceChange1hMin === null || (row.dexscreener_price_change_1h || 0) >= dexFilters.priceChange1hMin) &&
      (dexFilters.priceChange6hMin === null || (row.dexscreener_price_change_6h || 0) >= dexFilters.priceChange6hMin) &&
      (dexFilters.priceChange24hMin === null || (row.dexscreener_price_change_h24 || 0) >= dexFilters.priceChange24hMin) &&
      (dexFilters.priceChange24hMax === null || (row.dexscreener_price_change_h24 || 0) <= dexFilters.priceChange24hMax) &&
      ageFilterPassed && 
      whaleFilterPassed
    );
  });

  // Appeler les fonctions du fichier principal
  window.highlightActiveFilters();
  window.updateFiltersIndicator();
  window.currentPage = 1;
  window.renderPage();
}

// =============================================================================
// FONCTION DE RENDU DU TABLEAU DEXSCREENER
// =============================================================================

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
      
      const pairCreatedAt = r.dexscreener_pair_created_at;
      const pairCreatedTimeAgo = window.getTimeAgo(pairCreatedAt);
      const pairCreatedFull = window.formatLocalDateTime(pairCreatedAt);
      
      const lastDexUpdate = r.last_dexscreener_update || r.updated_at;
      const dexUpdateTimeAgo = window.getTimeAgo(lastDexUpdate);
      const dexUpdateFull = window.formatLocalDateTime(lastDexUpdate);
      
      const priceChange1h = window.formatPriceChange(r.dexscreener_price_change_1h);
      const priceChange6h = window.formatPriceChange(r.dexscreener_price_change_6h);
      const priceChange24h = window.formatPriceChange(r.dexscreener_price_change_h24);
      
      const progressDisplay = window.getBondingProgressDisplay(r.bonding_curve_status, r.bonding_curve_progress);
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
      const holdersDisplay = getHoldersDisplay(r.holders, r.holder_distribution);
      
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
          <td>${window.getTokenStatusDisplay(r.status)}</td>
          <td class="price">${(r.dexscreener_price_usd || 0).toFixed(8)}</td>
          <td>${Math.round(r.dexscreener_market_cap || 0).toLocaleString()}</td>
          <td>${holdersDisplay}</td>
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
    
    // Vérifier l'historique des tokens et mettre à jour les indicateurs whale
    rows.forEach(r => {
      setTimeout(() => window.checkTokenHistory(r.address), Math.random() * 1000);
    });
    
    setTimeout(() => {
      console.log('Triggering whale indicators update after table render');
      window.updateWhaleIndicators();
    }, 1500);
  }
}

// =============================================================================
// FONCTION DE STATUT DES TOKENS
// =============================================================================

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

// =============================================================================
// SETUP DES EVENT LISTENERS
// =============================================================================

function setupDexFiltersEventListeners() {
  const allDexFilterSelectors = [
    '#dexscreener-content .filter-panel input',
    '#dexscreener-content .filter-panel select'
  ];
  
  allDexFilterSelectors.forEach(selector => {
    document.querySelectorAll(selector).forEach(input => { 
      input.removeEventListener('input', dexFilterHandler);
      input.addEventListener('input', dexFilterHandler);
    }); 
  });
}

function dexFilterHandler() {
  clearTimeout(window.debounceTimeout); 
  window.debounceTimeout = setTimeout(() => { 
    applyDexFilters();
  }, 300);
}

// =============================================================================
// FONCTIONS DE DEBUG ET TEST
// =============================================================================

function testStrategy(strategyName) {
  console.log(`🧪 Test de la stratégie: ${strategyName}`);
  const strategy = strategies[strategyName];
  console.log('Filtres à appliquer:', strategy.filters);
  
  applyStrategy(strategyName, document.querySelector(`.strategy-${strategyName}`));
  
  setTimeout(() => {
    console.log(`Résultats: ${window.filteredData.length} tokens trouvés`);
  }, 500);
}

function debugWhaleFilters() {
  console.log('=== DEBUG WHALE FILTERS ===');
  
  let dbWhaleCount = 0;
  let indicatorWhaleCount = 0;
  
  window.data.forEach(token => {
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
  console.log(`Total tokens: ${window.data.length}`);
  console.log(`Filtered tokens: ${window.filteredData.length}`);
  
  if (currentWhaleFilter === 'has_whale') {
    console.log('Test du filtre "has_whale":');
    let passedCount = 0;
    
    window.data.forEach(row => {
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

// =============================================================================
// EXPORTS POUR LE FICHIER PRINCIPAL
// =============================================================================

// Exposer les fonctions nécessaires au niveau global
window.setHoldersFilter = setHoldersFilter;
window.clearHoldersFilter = clearHoldersFilter;
window.getHoldersDisplay = getHoldersDisplay;
window.applyStrategy = applyStrategy;
window.resetDexFilters = resetDexFilters;
window.setAgeFilter = setAgeFilter;
window.clearAgeFilter = clearAgeFilter;
window.setDexTimeFilter = setDexTimeFilter;
window.clearDexTimeFilter = clearDexTimeFilter;
window.setWhaleActivityFilter = setWhaleActivityFilter;
window.clearWhaleActivityFilter = clearWhaleActivityFilter;
window.applyDexFilters = applyDexFilters;
window.renderDexScreenerTable = renderDexScreenerTable;
window.getTokenStatusDisplay = getTokenStatusDisplay;
window.setupDexFiltersEventListeners = setupDexFiltersEventListeners;
window.testStrategy = testStrategy;
window.debugWhaleFilters = debugWhaleFilters;

