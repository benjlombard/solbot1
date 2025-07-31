/**
 * 🚀 PUMP.FUN MODULE - JavaScript functions for Pump.fun tab
 * Fichier: static/js/pump_fun_module.js
 * VERSION CORRIGÉE
 */

// === VARIABLES GLOBALES PUMP.FUN ===
let currentPumpAgeMin = null;
let currentPumpAgeMax = null;
let pumpTimeValue = null;
let pumpTimeUnit = null;

// === FONCTIONS DE FILTRAGE PUMP.FUN ===

function setPumpAgeFilter(minHours, maxHours, btn) {
  currentPumpAgeMin = minHours;
  currentPumpAgeMax = maxHours;
  
  document.querySelectorAll('#pumpfun-content .pump-age-presets .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyPumpFilters();
}

function clearPumpAgeFilter(btn) {
  currentPumpAgeMin = null;
  currentPumpAgeMax = null;
  
  document.querySelectorAll('#pumpfun-content .pump-age-presets .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyPumpFilters();
}

function setPumpTimeFilter(value, unit, btn) {
  pumpTimeValue = value;
  pumpTimeUnit = unit;
  
  document.querySelectorAll('#pumpfun-content .preset-btn').forEach(b => {
    if (b.getAttribute('onclick')?.includes('setPumpTimeFilter') || b.getAttribute('onclick')?.includes('clearPumpTimeFilter')) {
      b.classList.remove('active');
    }
  });
  btn.classList.add('active');
  
  applyPumpFilters();
}

function clearPumpTimeFilter(btn) {
  pumpTimeValue = null;
  pumpTimeUnit = null;
  
  document.querySelectorAll('#pumpfun-content .preset-btn').forEach(b => {
    if (b.getAttribute('onclick')?.includes('setPumpTimeFilter') || b.getAttribute('onclick')?.includes('clearPumpTimeFilter')) {
      b.classList.remove('active');
    }
  });
  btn.classList.add('active');
  
  applyPumpFilters();
}

function applyPumpQuickFilter(filterType, btn) {
  // Réinitialiser tous les filtres d'abord
  resetPumpFilters();
  
  // Marquer le bouton comme actif
  document.querySelectorAll('.pump-quick-filters .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  // Appliquer les filtres selon le type
  switch (filterType) {
    case 'new_gems':
      // Tokens récents avec bonding curve active
      currentPumpAgeMin = 0;
      currentPumpAgeMax = 24;
      document.getElementById('pumpFilterStatus').value = 'active';
      document.getElementById('pumpFilterMarketCapMin').value = 1000;
      document.getElementById('pumpFilterMarketCapMax').value = 100000;
      break;
      
    case 'completed_ready':
      // Tokens avec bonding curve terminée prêts pour migration
      document.getElementById('pumpFilterStatus').value = 'complete';
      document.getElementById('pumpFilterMarketCapMin').value = 50000;
      break;
      
    case 'high_activity':
      // Tokens avec forte activité (réponses)
      document.getElementById('pumpFilterReplyCountMin').value = 10;
      document.getElementById('pumpFilterStatus').value = 'active';
      break;
      
    case 'early_stage':
      // Tokens en phase précoce avec faible market cap
      document.getElementById('pumpFilterStatus').value = 'active';
      document.getElementById('pumpFilterMarketCapMax').value = 10000;
      currentPumpAgeMin = 0;
      currentPumpAgeMax = 6;
      break;
      
    case 'social_verified':
      // Tokens avec réseaux sociaux vérifiés
      document.getElementById('pumpFilterSocial').value = 'has_any_social';
      document.getElementById('pumpFilterMarketCapMin').value = 5000;
      break;
  }
  
  setTimeout(() => {
    applyPumpFilters();
  }, 100);
}

function clearPumpFilters(btn) {
  resetPumpFilters();
  
  document.querySelectorAll('.pump-quick-filters .preset-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  applyPumpFilters();
}

function resetPumpFilters() {
  const pumpFilterIds = [
    'pumpFilterSymbol', 'pumpFilterStatus', 'pumpFilterNSFW', 'pumpFilterShowName',
    'pumpFilterMarketCapMin', 'pumpFilterMarketCapMax', 'pumpFilterMarketCapSolMin', 'pumpFilterMarketCapSolMax',
    'pumpFilterTotalSupplyMin', 'pumpFilterTotalSupplyMax', 'pumpFilterVirtualSolMin', 'pumpFilterVirtualSolMax',
    'pumpFilterVirtualTokenMin', 'pumpFilterVirtualTokenMax', 'pumpFilterCreator', 'pumpFilterUsername',
    'pumpFilterReplyCountMin', 'pumpFilterSocial'
  ];
  
  pumpFilterIds.forEach(id => {
    const element = document.getElementById(id);
    if (element) {
      element.value = '';
      element.classList.remove('filter-active');
    }
  });
  
  // Réinitialiser les variables spéciales
  currentPumpAgeMin = null;
  currentPumpAgeMax = null;
  pumpTimeValue = null;
  pumpTimeUnit = null;
  
  // Désactiver tous les boutons présets
  document.querySelectorAll('#pumpfun-content .preset-btn').forEach(btn => {
    btn.classList.remove('active');
  });
}

// ✅ FONCTION PRINCIPALE DE FILTRAGE CORRIGÉE
function applyPumpFilters() {
  const pumpFilters = {
    symbol: document.getElementById('pumpFilterSymbol').value.toLowerCase().trim(),
    status: document.getElementById('pumpFilterStatus').value.toLowerCase().trim(),
    nsfw: document.getElementById('pumpFilterNSFW').value,
    showName: document.getElementById('pumpFilterShowName').value,
    marketCapMin: document.getElementById('pumpFilterMarketCapMin').value ? parseFloat(document.getElementById('pumpFilterMarketCapMin').value) : null,
    marketCapMax: document.getElementById('pumpFilterMarketCapMax').value ? parseFloat(document.getElementById('pumpFilterMarketCapMax').value) : null,
    marketCapSolMin: document.getElementById('pumpFilterMarketCapSolMin').value ? parseFloat(document.getElementById('pumpFilterMarketCapSolMin').value) : null,
    marketCapSolMax: document.getElementById('pumpFilterMarketCapSolMax').value ? parseFloat(document.getElementById('pumpFilterMarketCapSolMax').value) : null,
    totalSupplyMin: document.getElementById('pumpFilterTotalSupplyMin').value ? parseFloat(document.getElementById('pumpFilterTotalSupplyMin').value) : null,
    totalSupplyMax: document.getElementById('pumpFilterTotalSupplyMax').value ? parseFloat(document.getElementById('pumpFilterTotalSupplyMax').value) : null,
    virtualSolMin: document.getElementById('pumpFilterVirtualSolMin').value ? parseFloat(document.getElementById('pumpFilterVirtualSolMin').value) : null,
    virtualSolMax: document.getElementById('pumpFilterVirtualSolMax').value ? parseFloat(document.getElementById('pumpFilterVirtualSolMax').value) : null,
    virtualTokenMin: document.getElementById('pumpFilterVirtualTokenMin').value ? parseFloat(document.getElementById('pumpFilterVirtualTokenMin').value) : null,
    virtualTokenMax: document.getElementById('pumpFilterVirtualTokenMax').value ? parseFloat(document.getElementById('pumpFilterVirtualTokenMax').value) : null,
    creator: document.getElementById('pumpFilterCreator').value.toLowerCase().trim(),
    username: document.getElementById('pumpFilterUsername').value.toLowerCase().trim(),
    replyCountMin: document.getElementById('pumpFilterReplyCountMin').value ? parseInt(document.getElementById('pumpFilterReplyCountMin').value) : null,
    social: document.getElementById('pumpFilterSocial').value.toLowerCase().trim()
  };

  console.log('🔍 Pump filters applied:', pumpFilters);
  console.log('📊 Total data before filtering:', data.length);

  // ✅ FILTRAGE CORRIGÉ avec logs de debug
  filteredData = data.filter(row => {
    // Debug pour le premier token
    if (row === data[0]) {
      console.log('🐛 DEBUG Premier token:', {
        address: row.address,
        symbol: row.symbol,
        pump_fun_symbol: row.pump_fun_symbol,
        exists_on_pump: row.exists_on_pump,
        pump_fun_usd_market_cap: row.pump_fun_usd_market_cap,
        pump_fun_complete: row.pump_fun_complete
      });
    }

    // Vérifier si le token existe sur Pump.fun
    const existsOnPump = row.exists_on_pump === 1 || row.exists_on_pump === true;
    const lastPumpUpdate = row.pump_fun_last_pump_update;
    
    // ✅ CORRECTION: Filtre symbole - chercher dans pump_fun_symbol ET symbol
    if (pumpFilters.symbol) {
      const symbol = (row.pump_fun_symbol || row.symbol || '').toLowerCase();
      if (!symbol.includes(pumpFilters.symbol)) {
        return false;
      }
    }
    
    // Filtre status
    if (pumpFilters.status) {
      switch (pumpFilters.status) {
        case 'exists':
          if (!existsOnPump) return false;
          break;
        case 'not_exists':
          if (existsOnPump) return false;
          break;
        case 'complete':
          if (!row.pump_fun_complete) return false;
          break;
        case 'active':
          if (!existsOnPump || row.pump_fun_complete) return false;
          break;
        case 'migrated':
          if (!row.pump_fun_raydium_pool) return false;
          break;
      }
    }
    
    // Filtre NSFW
    if (pumpFilters.nsfw) {
      const isNSFW = row.pump_fun_nsfw === 1 || row.pump_fun_nsfw === true;
      if (pumpFilters.nsfw === 'true' && !isNSFW) return false;
      if (pumpFilters.nsfw === 'false' && isNSFW) return false;
    }
    
    // Filtre show name
    if (pumpFilters.showName) {
      const showName = row.pump_fun_show_name === 1 || row.pump_fun_show_name === true;
      if (pumpFilters.showName === 'true' && !showName) return false;
      if (pumpFilters.showName === 'false' && showName) return false;
    }
    
    // ✅ CORRECTION: Filtres financiers avec valeurs correctes
    if (pumpFilters.marketCapMin !== null && (row.pump_fun_usd_market_cap || 0) < pumpFilters.marketCapMin) return false;
    if (pumpFilters.marketCapMax !== null && (row.pump_fun_usd_market_cap || 0) > pumpFilters.marketCapMax) return false;
    if (pumpFilters.marketCapSolMin !== null && (row.pump_fun_market_cap || 0) < pumpFilters.marketCapSolMin) return false;
    if (pumpFilters.marketCapSolMax !== null && (row.pump_fun_market_cap || 0) > pumpFilters.marketCapSolMax) return false;
    if (pumpFilters.totalSupplyMin !== null && (row.pump_fun_total_supply || 0) < pumpFilters.totalSupplyMin) return false;
    if (pumpFilters.totalSupplyMax !== null && (row.pump_fun_total_supply || 0) > pumpFilters.totalSupplyMax) return false;
    
    // Filtres réserves
    if (pumpFilters.virtualSolMin !== null && (row.pump_fun_virtual_sol_reserves || 0) < pumpFilters.virtualSolMin) return false;
    if (pumpFilters.virtualSolMax !== null && (row.pump_fun_virtual_sol_reserves || 0) > pumpFilters.virtualSolMax) return false;
    if (pumpFilters.virtualTokenMin !== null && (row.pump_fun_virtual_token_reserves || 0) < pumpFilters.virtualTokenMin) return false;
    if (pumpFilters.virtualTokenMax !== null && (row.pump_fun_virtual_token_reserves || 0) > pumpFilters.virtualTokenMax) return false;
    
    // Filtres créateur
    if (pumpFilters.creator && !(row.pump_fun_creator || '').toLowerCase().includes(pumpFilters.creator)) return false;
    if (pumpFilters.username && !(row.pump_fun_username || '').toLowerCase().includes(pumpFilters.username)) return false;
    if (pumpFilters.replyCountMin !== null && (row.pump_fun_reply_count || 0) < pumpFilters.replyCountMin) return false;
    
    // Filtre réseaux sociaux
    if (pumpFilters.social) {
      const hasTwitter = !!row.pump_fun_twitter;
      const hasTelegram = !!row.pump_fun_telegram;
      const hasWebsite = !!row.pump_fun_website;
      
      switch (pumpFilters.social) {
        case 'has_twitter':
          if (!hasTwitter) return false;
          break;
        case 'has_telegram':
          if (!hasTelegram) return false;
          break;
        case 'has_website':
          if (!hasWebsite) return false;
          break;
        case 'has_any_social':
          if (!hasTwitter && !hasTelegram && !hasWebsite) return false;
          break;
        case 'no_social':
          if (hasTwitter || hasTelegram || hasWebsite) return false;
          break;
      }
    }
    
    // Filtre âge
    if (currentPumpAgeMin !== null || currentPumpAgeMax !== null) {
      if (row.pump_fun_created_timestamp) {
        const now = new Date();
        let createdDate;
        const timestamp = row.pump_fun_created_timestamp;
        
        // Détecter le format du timestamp (même logique que dans getPumpCreatedDisplay)
        try {
          if (timestamp > 1e12) {
            // Si > 1e12, c'est probablement en millisecondes
            createdDate = new Date(timestamp);
          } else {
            // Si < 1e12, c'est probablement en secondes, multiplier par 1000
            createdDate = new Date(timestamp * 1000);
          }
          
          // Vérifier si la date est valide et raisonnable (entre 2020 et 2030)
          const year = createdDate.getFullYear();
          if (year < 2020 || year > 2030) {
            // Essayer l'autre format
            if (timestamp > 1e12) {
              createdDate = new Date(timestamp / 1000);
            } else {
              createdDate = new Date(timestamp);
            }
          }
          
          // Vérification finale de la validité
          if (isNaN(createdDate.getTime()) || createdDate.getFullYear() < 2020 || createdDate.getFullYear() > 2030) {
            return false; // Date invalide, exclure du filtre
          }
          
          // Calculer l'âge en heures
          const ageHours = (now - createdDate) / (1000 * 60 * 60);
          
          // Debug pour les premiers tokens
          if (row === data[0]) {
            console.log('🐛 DEBUG Age Filter:', {
              address: row.address,
              timestamp: timestamp,
              createdDate: createdDate.toISOString(),
              ageHours: ageHours.toFixed(2),
              currentPumpAgeMin,
              currentPumpAgeMax
            });
          }
          
          // Appliquer les filtres d'âge
          if (currentPumpAgeMin !== null && ageHours < currentPumpAgeMin) {
            return false;
          }
          if (currentPumpAgeMax !== null && ageHours > currentPumpAgeMax) {
            return false;
          }
          
        } catch (error) {
          console.error(`Error parsing date for age filter on token ${row.address}:`, error);
          return false; // En cas d'erreur, exclure du filtre
        }
      } else {
        // Pas de timestamp de création, exclure du filtre d'âge
        return false;
      }
    }
    
    // Filtre temps de mise à jour
    if (pumpTimeValue && pumpTimeUnit && lastPumpUpdate) {
      if (!isWithinTimeFilter(lastPumpUpdate, pumpTimeValue, pumpTimeUnit)) return false;
    }
    
    return true;
  });

  console.log('📊 Filtered data result:', filteredData.length);
  console.log('✅ Sample filtered tokens:', filteredData.slice(0, 3).map(t => ({
    symbol: t.pump_fun_symbol || t.symbol,
    exists_on_pump: t.exists_on_pump,
    market_cap: t.pump_fun_usd_market_cap
  })));

  // Appeler les fonctions du fichier principal
  highlightActiveFilters();
  updateFiltersIndicator();
  currentPage = 1;
  renderPage();
}

// === FONCTIONS D'AFFICHAGE PUMP.FUN ===

// ✅ FONCTION DE RENDU CORRIGÉE
function renderPumpFunTable(rows) {
  const tbody = document.getElementById('pumpfunTbody');
  
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="16" class="no-data">Aucune donnée ne correspond aux filtres</td></tr>';
    return;
  }
  
  tbody.innerHTML = rows.map(r => {
    const existsOnPump = r.exists_on_pump === 1 || r.exists_on_pump === true;
    
    // ✅ CORRECTION: Utiliser les vrais champs Pump.fun
    const symbol = r.pump_fun_symbol || r.symbol || 'UNKNOWN';
    const name = r.pump_fun_name || r.name || 'No name';
    const description = r.pump_fun_description || '';
    
    const pumpStatus = getPumpStatusDisplay(r);
    const imageDisplay = getPumpImageDisplay(r);
    const marketCapDisplay = getPumpMarketCapDisplay(r);
    const progressDisplay = getPumpProgressDisplay(r);
    const creatorDisplay = getPumpCreatorDisplay(r);
    const socialLinks = getPumpSocialLinks(r);
    const createdDisplay = getPumpCreatedDisplay(r);
    const pumpUrl = getPumpUrlDisplay(r);
    const lastUpdateDisplay = getPumpUpdateDisplay(r);
    const replyDisplay = getPumpReplyDisplay(r);
    
    // Classes pour highlighting
    let rowClass = '';
    if (!existsOnPump) rowClass += ' pump-not-found';
    else if (r.pump_fun_complete) rowClass += ' pump-completed-token';
    else if (r.pump_fun_raydium_pool) rowClass += ' pump-migrated-token';
    else if ((r.pump_fun_reply_count || 0) > 10) rowClass += ' pump-high-activity';
    else if (isNewPumpToken(r)) rowClass += ' pump-new-token';
    
    return `
      <tr class="${rowClass}">
        <td><span class="fav" onclick="toggleFav('${r.address}')">⭐</span></td>
        <td>
          <div class="pump-token-info">
            <div class="pump-token-symbol">${symbol}</div>
            <div class="pump-token-name" title="${name}">${name}</div>
            ${description ? `<div class="pump-token-description" title="${description}">${description.substring(0, 50)}${description.length > 50 ? '...' : ''}</div>` : ''}
          </div>
        </td>
        <td>${pumpStatus}</td>
        <td>${imageDisplay}</td>
        <td>${marketCapDisplay}</td>
        <td class="price">${(r.pump_fun_market_cap || 0).toFixed(2)} SOL</td>
        <td>${Math.round(r.pump_fun_total_supply || 0).toLocaleString()}</td>
        <td>${progressDisplay}</td>
        <td>${(r.pump_fun_virtual_sol_reserves || 0).toFixed(2)}</td>
        <td>${Math.round(r.pump_fun_virtual_token_reserves || 0).toLocaleString()}</td>
        <td>${creatorDisplay}</td>
        <td>${replyDisplay}</td>
        <td>${socialLinks}</td>
        <td>${createdDisplay}</td>
        <td>${pumpUrl}</td>
        <td>${lastUpdateDisplay}</td>
      </tr>
    `;
  }).join('');
}

// === FONCTIONS UTILITAIRES PUMP.FUN ===

function getPumpStatusDisplay(token) {
  const existsOnPump = token.exists_on_pump === 1 || token.exists_on_pump === true;
  
  if (!existsOnPump) {
    return '<span class="pump-status pump-not-found">Not Found</span>';
  }
  
  if (token.pump_fun_complete) {
    return '<span class="pump-status pump-complete">Complete</span>';
  }
  
  if (token.pump_fun_raydium_pool) {
    return '<span class="pump-status pump-migrated">Migrated</span>';
  }
  
  if (token.pump_fun_nsfw) {
    return '<span class="pump-status pump-nsfw">NSFW Active</span>';
  }
  
  return '<span class="pump-status pump-active">Active</span>';
}

function getPumpImageDisplay(token) {
  if (token.pump_fun_image_uri) {
    return `<img src="${token.pump_fun_image_uri}" alt="Token image" class="pump-image-preview" onclick="window.open('${token.pump_fun_image_uri}', '_blank')">`;
  }
  return '<div class="pump-image-placeholder">No Image</div>';
}

// ✅ FONCTION CORRIGÉE
function getPumpMarketCapDisplay(token) {
  const usdCap = token.pump_fun_usd_market_cap || 0;
  const solCap = token.pump_fun_market_cap || 0;
  
  return `
    <div class="pump-market-cap-display">
      <div class="pump-market-cap-usd">${Math.round(usdCap).toLocaleString()}</div>
      <div class="pump-market-cap-sol">${solCap.toFixed(2)} SOL</div>
    </div>
  `;
}

// ✅ FONCTION CORRIGÉE
function getPumpProgressDisplay(token) {
  const progress = parseFloat(token.bonding_curve_progress) || 0;
  
  if (progress <= 0) {
    return '<div class="no-progress">0%</div>';
  }
  
  return `
    <div class="pump-progress-container">
      <div class="pump-progress-bar" style="width: ${Math.min(progress, 100)}%"></div>
      <div class="pump-progress-text">${progress.toFixed(1)}%</div>
    </div>
  `;
}

function getPumpReservesDisplay(token) {
  const solReserves = token.pump_fun_virtual_sol_reserves || 0;
  const tokenReserves = token.pump_fun_virtual_token_reserves || 0;
  
  return `
    <div class="pump-reserves-display">
      <div class="pump-reserves-sol">${solReserves.toFixed(2)} SOL</div>
      <div class="pump-reserves-token">${tokenReserves.toLocaleString()}</div>
    </div>
  `;
}

function getPumpCreatorDisplay(token) {
  const creator = token.pump_fun_creator;
  const username = token.pump_fun_username;
  const profileImage = token.pump_fun_profile_image;
  
  if (!creator && !username) {
    return '<div style="color: #666;">Unknown</div>';
  }
  
  return `
    <div class="pump-creator-info">
      ${profileImage ? `<img src="${profileImage}" alt="Avatar" class="pump-creator-avatar">` : ''}
      ${username ? `<div class="pump-creator-username">${username}</div>` : ''}
      ${creator ? `<div class="pump-creator-address" onclick="copyToClipboard('${creator}')" title="${creator}">${creator.substring(0, 8)}...${creator.substring(creator.length - 4)}</div>` : ''}
    </div>
  `;
}

function getPumpSocialLinks(token) {
  const links = [];
  
  if (token.pump_fun_twitter) {
    links.push(`<a href="${token.pump_fun_twitter}" target="_blank" class="pump-social-link pump-social-twitter">🐦 Twitter</a>`);
  }
  
  if (token.pump_fun_telegram) {
    links.push(`<a href="${token.pump_fun_telegram}" target="_blank" class="pump-social-link pump-social-telegram">📱 Telegram</a>`);
  }
  
  if (token.pump_fun_website) {
    links.push(`<a href="${token.pump_fun_website}" target="_blank" class="pump-social-link pump-social-website">🌐 Website</a>`);
  }
  
  if (links.length === 0) {
    return '<div style="color: #666;">No socials</div>';
  }
  
  return `<div class="pump-social-links">${links.join('')}</div>`;
}

function getPumpCreatedDisplay(token) {
  if (!token.pump_fun_created_timestamp) {
    return '<div style="color: #666;">Unknown</div>';
  }
  
  // ✅ CORRECTION: Le timestamp est probablement en millisecondes, pas en secondes
  let createdDate;
  const timestamp = token.pump_fun_created_timestamp;
  
  try {
    // Détecter si le timestamp est en secondes ou millisecondes
    if (timestamp > 1e12) {
      // Si > 1e12, c'est probablement en millisecondes
      createdDate = new Date(timestamp);
    } else {
      // Si < 1e12, c'est probablement en secondes, multiplier par 1000
      createdDate = new Date(timestamp * 1000);
    }
    
    // Vérifier si la date est valide et raisonnable (entre 2020 et 2030)
    const year = createdDate.getFullYear();
    if (year < 2020 || year > 2030) {
      // Essayer l'autre format
      if (timestamp > 1e12) {
        createdDate = new Date(timestamp / 1000);
      } else {
        createdDate = new Date(timestamp);
      }
    }
    
    // Double vérification
    if (isNaN(createdDate.getTime()) || createdDate.getFullYear() < 2020 || createdDate.getFullYear() > 2030) {
      console.warn(`Invalid date for token ${token.address}: timestamp=${timestamp}, parsed=${createdDate}`);
      return '<div style="color: #666;">Invalid date</div>';
    }
    
    const timeAgo = getTimeAgo(createdDate.toISOString());
    const formattedDate = createdDate.toLocaleString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
    
    return `
      <div class="pump-timestamp-display">
        <div class="pump-timestamp-main">${formattedDate}</div>
        <div class="pump-timestamp-ago ${timeAgo.className}">${timeAgo.text}</div>
      </div>
    `;
    
  } catch (error) {
    console.error(`Error parsing date for token ${token.address}:`, error, 'timestamp:', timestamp);
    return '<div style="color: #666;">Date error</div>';
  }
}

function getPumpUrlDisplay(token) {
  const existsOnPump = token.exists_on_pump === 1 || token.exists_on_pump === true;
  
  if (!existsOnPump) {
    return '<div style="color: #666;">N/A</div>';
  }
  
  const pumpUrl = `https://pump.fun/coin/${token.address}`;
  return `<a href="${pumpUrl}" target="_blank" class="pump-url-link">🚀 View on Pump</a>`;
}

function getPumpUpdateDisplay(token) {
  const lastUpdate = token.pump_fun_last_pump_update;
  
  if (!lastUpdate) {
    return '<div style="color: #666;">Never updated</div>';
  }
  
  const timeAgo = getTimeAgo(lastUpdate);
  const fullTime = formatLocalDateTime(lastUpdate);
  
  return `
    <div class="pump-timestamp-display">
      <div class="pump-timestamp-main" title="${fullTime}">${timeAgo.text}</div>
    </div>
  `;
}

function getPumpReplyDisplay(token) {
  const replyCount = token.pump_fun_reply_count || 0;
  
  if (replyCount === 0) {
    return '<div style="color: #666;">0</div>';
  }
  
  const badgeClass = replyCount > 50 ? 'high-activity' : '';
  
  return `<div class="pump-reply-badge ${badgeClass}">💬 ${replyCount}</div>`;
}

function isNewPumpToken(token) {
  if (!token.pump_fun_created_timestamp) return false;
  
  const createdDate = new Date(token.pump_fun_created_timestamp * 1000);
  const now = new Date();
  const ageHours = (now - createdDate) / (1000 * 60 * 60);
  
  return ageHours < 24; // Moins de 24h = nouveau
}

// === FONCTIONS DE DEBUG ===

function debugPumpFunData() {
  console.log('=== DEBUG PUMP.FUN DATA ===');
  
  const pumpTokens = data.filter(t => t.exists_on_pump === 1);
  console.log(`🎯 Tokens existant sur Pump.fun: ${pumpTokens.length}/${data.length}`);
  
  const tokensWithUSDCap = data.filter(t => (t.pump_fun_usd_market_cap || 0) > 0);
  console.log(`💰 Tokens avec USD market cap: ${tokensWithUSDCap.length}`);
  
  const tokensWithSymbol = data.filter(t => t.pump_fun_symbol);
  console.log(`🏷️ Tokens avec symbole Pump.fun: ${tokensWithSymbol.length}`);
  
  // Afficher quelques exemples
  console.log('📊 Exemples de tokens Pump.fun:');
  pumpTokens.slice(0, 5).forEach((token, i) => {
    console.log(`  ${i+1}. ${token.pump_fun_symbol || token.symbol} - ${token.pump_fun_usd_market_cap || 0} - ${token.pump_fun_name || 'No name'}`);
  });
  
  console.log('=== END DEBUG ===');
}

function testPumpFilters() {
  console.log('🧪 Test des filtres Pump.fun');
  
  // Test filtre symbole
  document.getElementById('pumpFilterSymbol').value = 'PEPE';
  applyPumpFilters();
  console.log(`Résultat filtre PEPE: ${filteredData.length} tokens`);
  
  // Reset
  document.getElementById('pumpFilterSymbol').value = '';
  
  // Test filtre status
  document.getElementById('pumpFilterStatus').value = 'exists';
  applyPumpFilters();
  console.log(`Résultat filtre exists: ${filteredData.length} tokens`);
  
  // Reset
  document.getElementById('pumpFilterStatus').value = '';
  applyPumpFilters();
}

// === FONCTION D'INITIALISATION ===

function setupPumpFiltersEventListeners() {
  document.querySelectorAll('#pumpfun-content .filter-panel input, #pumpfun-content .filter-panel select').forEach(input => {
    input.addEventListener('input', () => {
      clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        applyPumpFilters();
      }, 300);
    });
  });
}

// === EXPORT DES FONCTIONS (pour les rendre accessibles globalement) ===
window.setPumpAgeFilter = setPumpAgeFilter;
window.clearPumpAgeFilter = clearPumpAgeFilter;
window.setPumpTimeFilter = setPumpTimeFilter;
window.clearPumpTimeFilter = clearPumpTimeFilter;
window.applyPumpQuickFilter = applyPumpQuickFilter;
window.clearPumpFilters = clearPumpFilters;
window.resetPumpFilters = resetPumpFilters;
window.applyPumpFilters = applyPumpFilters;
window.renderPumpFunTable = renderPumpFunTable;
window.setupPumpFiltersEventListeners = setupPumpFiltersEventListeners;
window.debugPumpFunData = debugPumpFunData;
window.testPumpFilters = testPumpFilters;