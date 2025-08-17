// =============================================================================
// DASHBOARD OPTIMISÉ - Réduction utilisation mémoire/CPU
// =============================================================================

// Configuration optimisée
const OPTIMIZED_CONFIG = {
    maxActivityItems: 20,        // Réduire de 35 à 20
    maxWalletsDisplay: 10,       // Réduire de 50 à 10
    refreshInterval: 45000,      // Augmenter à 45s au lieu de 30s
    autoRefreshInterval: 30000,  // Auto-refresh moins fréquent
    maxCacheSize: 50,           // Limiter le cache
    debounceDelay: 300          // Délai pour éviter trop d'appels
};

// Variables globales optimisées
let dashboardData = null;
let lastUpdateTime = 0;
let refreshTimers = new Map();
let isUpdating = false;
let updateQueue = [];

// Cache léger
const lightCache = new Map();

// =============================================================================
// FONCTIONS D'OPTIMISATION
// =============================================================================

// Debounce pour éviter trop d'appels API
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Throttle pour limiter les appels
function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    }
}

// Nettoyer les timers inutiles
function cleanupTimers() {
    refreshTimers.forEach((timer, key) => {
        if (timer) {
            clearTimeout(timer);
            clearInterval(timer);
        }
    });
    refreshTimers.clear();
}

// Limiter la taille du cache
function manageCacheSize() {
    if (lightCache.size > OPTIMIZED_CONFIG.maxCacheSize) {
        const keys = Array.from(lightCache.keys());
        // Supprimer les plus anciens
        for (let i = 0; i < 10; i++) {
            lightCache.delete(keys[i]);
        }
    }
}

// =============================================================================
// CHARGEMENT DE DONNÉES OPTIMISÉ
// =============================================================================

const optimizedLoadDashboardData = debounce(async function() {
    if (isUpdating) {
        console.log("🔄 Mise à jour déjà en cours, ignoré");
        return;
    }
    
    isUpdating = true;
    
    try {
        console.log("📡 Chargement optimisé des données...");
        
        const response = await fetch(`${API_BASE}/dashboard/data`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const result = await response.json();
        if (!result.success) {
            throw new Error(result.message || 'Erreur API');
        }
        
        dashboardData = result.data;
        lastUpdateTime = Date.now();
        
        // Mettre à jour l'interface de façon optimisée
        await updateUIOptimized();
        
        console.log("✅ Données chargées et interface mise à jour");
        
    } catch (error) {
        console.error("❌ Erreur chargement:", error);
        showOptimizedMessage(`Erreur: ${error.message}`, 'error');
    } finally {
        isUpdating = false;
        // Traiter la queue si nécessaire
        if (updateQueue.length > 0) {
            updateQueue = []; // Vider la queue
        }
    }
}, OPTIMIZED_CONFIG.debounceDelay);

// =============================================================================
// MISE À JOUR INTERFACE OPTIMISÉE
// =============================================================================

async function updateUIOptimized() {
    if (!dashboardData) return;
    
    try {
        // Mettre à jour par petits chunks pour éviter de bloquer l'UI
        await updateActivityTableOptimized();
        await new Promise(resolve => setTimeout(resolve, 10)); // Petit délai
        
        await updateWalletsTableOptimized();
        await new Promise(resolve => setTimeout(resolve, 10));
        
        // updateStats(); // Commenté car moins critique
        
        console.log("🎯 Interface mise à jour de façon optimisée");
        
    } catch (error) {
        console.error("❌ Erreur mise à jour UI:", error);
    }
}

// Optimisation de la table d'activité
async function updateActivityTableOptimized() {
    const tableBody = document.getElementById('activity-table-body');
    if (!tableBody || !dashboardData.recent_activity) return;
    
    try {
        // Prendre seulement les éléments les plus récents
        const activities = dashboardData.recent_activity.slice(0, OPTIMIZED_CONFIG.maxActivityItems);
        
        // Construire le HTML en une seule fois pour éviter les reflows multiples
        const htmlRows = activities.map(activity => {
            const tokenShort = `${activity.token_mint.substring(0, 4)}...${activity.token_mint.substring(activity.token_mint.length - 4)}`;
            const walletShort = `${activity.wallet_address.substring(0, 4)}...${activity.wallet_address.substring(activity.wallet_address.length - 4)}`;
            
            return `
                <tr>
                    <td>
                        <div class="address-container">
                            <a href="https://solscan.io/account/${activity.wallet_address}" target="_blank" title="${activity.wallet_address}">
                                ${walletShort}
                            </a>
                            <button class="copy-btn-small" onclick="copyToClipboard('${activity.wallet_address}', 'Adresse wallet copiée')">📋</button>
                        </div>
                    </td>
                    <td>${activity.token_symbol || 'UNKNOWN'}</td>
                    <td>
                        <div class="address-container">
                            <span>${tokenShort}</span>
                            <button class="copy-btn-small" onclick="copyToClipboard('${activity.token_mint}', 'Adresse token copiée')">📋</button>
                        </div>
                    </td>
                    <td>${activity.ata_pubkey ? `${activity.ata_pubkey.substring(0, 4)}...${activity.ata_pubkey.substring(activity.ata_pubkey.length - 4)}` : 'N/A'}</td>
                    <td>
                        <span class="type-${activity.transaction_type}">${activity.transaction_type}</span>
                        <div style="font-size: 11px; color: var(--text-muted);">${formatTimeAgo(activity.timestamp)}</div>
                    </td>
                    <td>
                        <div class="amount-sol">${formatNumber(activity.sol_amount || 0)} SOL</div>
                        <div class="amount-usd">$${formatNumber(activity.usd_amount || 0, 2)}</div>
                    </td>
                    <td>
                        <div class="action-buttons">
                            <button class="btn btn-sm btn-buy" onclick="buyToken('${activity.token_mint}')" title="Acheter">💰</button>
                            <button class="btn btn-sm btn-sell" onclick="sellToken('${activity.token_mint}')" title="Vendre">💸</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
        
        // Une seule modification du DOM
        tableBody.innerHTML = htmlRows;
        
    } catch (error) {
        console.error("Erreur updateActivityTableOptimized:", error);
        tableBody.innerHTML = '<tr><td colspan="7" class="error">Erreur de chargement</td></tr>';
    }
}

// Optimisation de la table des wallets
async function updateWalletsTableOptimized() {
    const tableBody = document.getElementById('wallets-table-body');
    if (!tableBody || !dashboardData.wallets_overview) return;
    
    try {
        // Prendre seulement les premiers wallets
        const wallets = dashboardData.wallets_overview.slice(0, OPTIMIZED_CONFIG.maxWalletsDisplay);
        
        const htmlRows = wallets.map(wallet => {
            const priorityCategory = getPriorityCategory(wallet.priority_score);
            const statusClass = getWalletStatusClass(wallet);
            const statusText = getWalletStatusText(wallet);
            
            return `
                <tr>
                    <td>
                        <div class="wallet-cell" onclick="showWalletDetails('${wallet.wallet_address}')" data-address="${wallet.wallet_address}">
                            <div class="wallet-avatar-small">${wallet.wallet_address.substring(0, 2).toUpperCase()}</div>
                            <div class="wallet-info-small">
                                <div class="wallet-address-small" title="${wallet.wallet_address}">${wallet.wallet_short}</div>
                                <div class="wallet-status-small">
                                    <div class="status-dot-tiny ${statusClass}"></div>
                                    <span class="status-text">${statusText}</span>
                                </div>
                            </div>
                        </div>
                    </td>
                    <td><span class="priority-badge-small priority-${priorityCategory}-small">${priorityCategory.toUpperCase()}</span></td>
                    <td>${formatNumber(wallet.total_token_accounts || 0)}</td>
                    <td>${formatNumber(wallet.transactions_24h || 0)}</td>
                    <td><span class="balance-amount">${formatNumber(wallet.sol_balance || 0)} SOL</span></td>
                    <td><span class="scan-time">${formatTimeAgo(wallet.last_scan_time) || 'N/A'}</span></td>
                    <td>
                        <div class="wallet-actions">
                            <button class="wallet-action-btn copy-btn" data-address="${wallet.wallet_address}" onclick="copyAddress(this, event)">📋</button>
                            <button class="wallet-action-btn view-btn" onclick="showWalletDetails('${wallet.wallet_address}')">👁️</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
        
        tableBody.innerHTML = htmlRows;
        
    } catch (error) {
        console.error("Erreur updateWalletsTableOptimized:", error);
        tableBody.innerHTML = '<tr><td colspan="7" class="error">Erreur de chargement</td></tr>';
    }
}

// =============================================================================
// FONCTIONS DE RAFRAÎCHISSEMENT OPTIMISÉES
// =============================================================================

const optimizedRefreshActivity = throttle(async function() {
    const button = event?.target?.closest('button');
    if (button) {
        const originalText = button.innerHTML;
        button.innerHTML = '<div class="spinner"></div>';
        button.disabled = true;
        
        try {
            await optimizedLoadDashboardData();
            showOptimizedMessage('Activité mise à jour', 'success');
        } catch (error) {
            showOptimizedMessage('Erreur de mise à jour', 'error');
        } finally {
            if (button) {
                button.innerHTML = originalText;
                button.disabled = false;
            }
        }
    }
}, 3000); // Limiter à une fois toutes les 3 secondes

const optimizedRefreshWallets = throttle(async function() {
    const button = event?.target?.closest('button');
    if (button) {
        const originalText = button.innerHTML;
        button.innerHTML = '<div class="spinner"></div>';
        button.disabled = true;
        
        try {
            await optimizedLoadDashboardData();
            showOptimizedMessage('Wallets mis à jour', 'success');
        } catch (error) {
            showOptimizedMessage('Erreur de mise à jour', 'error');
        } finally {
            if (button) {
                button.innerHTML = originalText;
                button.disabled = false;
            }
        }
    }
}, 3000);

// =============================================================================
// AUTO-REFRESH OPTIMISÉ
// =============================================================================

let autoRefreshState = {
    activity: false,
    wallets: false
};

function toggleAutoRefresh(section) {
    const isActive = autoRefreshState[section];
    
    if (isActive) {
        stopAutoRefresh(section);
    } else {
        startAutoRefresh(section);
    }
}

function startAutoRefresh(section) {
    const control = document.getElementById(`auto-refresh-${section}`);
    if (!control) return;
    
    autoRefreshState[section] = true;
    control.classList.add('active');
    
    // Timer plus long pour économiser les ressources
    const intervalId = setInterval(() => {
        if (autoRefreshState[section]) {
            if (section === 'activity' || section === 'wallets') {
                optimizedLoadDashboardData();
            }
        }
    }, OPTIMIZED_CONFIG.autoRefreshInterval);
    
    refreshTimers.set(`auto-${section}`, intervalId);
    
    console.log(`🔄 Auto-refresh ${section} activé (${OPTIMIZED_CONFIG.autoRefreshInterval/1000}s)`);
}

function stopAutoRefresh(section) {
    const control = document.getElementById(`auto-refresh-${section}`);
    if (!control) return;
    
    autoRefreshState[section] = false;
    control.classList.remove('active');
    
    const timerId = refreshTimers.get(`auto-${section}`);
    if (timerId) {
        clearInterval(timerId);
        refreshTimers.delete(`auto-${section}`);
    }
    
    console.log(`⏸️ Auto-refresh ${section} arrêté`);
}

// =============================================================================
// FONCTIONS UTILITAIRES OPTIMISÉES
// =============================================================================

// Message optimisé sans DOM complexe
function showOptimizedMessage(message, type = 'info', duration = 3000) {
    // Supprimer les messages existants
    const existing = document.querySelectorAll('.optimized-message');
    existing.forEach(el => el.remove());
    
    const messageEl = document.createElement('div');
    messageEl.className = 'optimized-message';
    messageEl.textContent = message;
    
    // Style minimal
    Object.assign(messageEl.style, {
        position: 'fixed',
        top: '20px',
        right: '20px',
        padding: '12px 20px',
        borderRadius: '8px',
        zIndex: '10001',
        fontSize: '14px',
        fontWeight: '500',
        color: 'white',
        background: type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#6b7280',
        animation: 'slideInRight 0.3s ease'
    });
    
    document.body.appendChild(messageEl);
    
    setTimeout(() => {
        if (messageEl.parentNode) {
            messageEl.remove();
        }
    }, duration);
}

// Optimisation des fonctions utilitaires
function formatNumber(num, decimals = 6) {
    if (typeof num !== 'number' || isNaN(num)) return '0';
    
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    } else if (num < 0.001 && num > 0) {
        return num.toExponential(2);
    } else {
        return Number(num.toFixed(decimals));
    }
}

function formatTimeAgo(timestamp) {
    if (!timestamp) return 'Jamais';
    
    const now = Date.now() / 1000;
    const diff = now - timestamp;
    
    if (diff < 60) return `${Math.floor(diff)}s`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}j`;
}

function getPriorityCategory(score) {
    if (score >= 4.0) return "high";
    if (score >= 2.0) return "medium";
    return "low";
}

function getWalletStatusClass(wallet) {
    if (!wallet || !wallet.seconds_since_scan) return 'error';
    if (wallet.seconds_since_scan <= 300) return '';
    if (wallet.seconds_since_scan <= 900) return 'warning';
    return 'error';
}

function getWalletStatusText(wallet) {
    const minutesAgo = Math.floor((wallet.seconds_since_scan || 0) / 60);
    if (minutesAgo < 5) return 'Récent';
    if (minutesAgo < 30) return 'Normal';
    return 'En retard';
}

// =============================================================================
// FONCTIONS DE COPIE ET MODAL OPTIMISÉES
// =============================================================================

function copyToClipboard(text, message) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        showOptimizedMessage(message, 'success', 2000);
    }).catch(err => {
        console.error('Failed to copy: ', err);
        showOptimizedMessage('Erreur de copie', 'error');
    });
}

function copyAddress(button, event) {
    event.stopPropagation();
    const address = button.dataset.address;
    if (!address) return;

    navigator.clipboard.writeText(address).then(() => {
        button.textContent = '✅';
        showOptimizedMessage(`Adresse copiée: ${address.substring(0, 8)}...`, 'success', 2000);
        
        setTimeout(() => {
            button.textContent = '📋';
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy address: ', err);
        showOptimizedMessage('Erreur de copie', 'error');
    });
}

// Modal simplifiée pour les détails
function showWalletDetails(walletAddress) {
    console.log('👛 Affichage détails wallet:', walletAddress);
    
    // Modal très simple pour éviter la surcharge
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.8); z-index: 10000;
        display: flex; align-items: center; justify-content: center;
    `;
    
    modal.innerHTML = `
        <div style="
            background: var(--glass-bg); padding: 24px; border-radius: 12px;
            max-width: 400px; color: var(--text-primary);
        ">
            <h3 style="margin: 0 0 16px 0;">Détails Wallet</h3>
            <p style="font-family: monospace; word-break: break-all; margin: 0 0 16px 0;">
                ${walletAddress}
            </p>
            <div style="display: flex; gap: 12px;">
                <button onclick="window.open('https://solscan.io/account/${walletAddress}', '_blank')" 
                        style="flex: 1; padding: 8px; border: none; border-radius: 6px; background: var(--solana-green); color: white; cursor: pointer;">
                    Voir sur Solscan
                </button>
                <button onclick="this.closest('.modal-simple').remove()" 
                        style="flex: 1; padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: transparent; color: var(--text-primary); cursor: pointer;">
                    Fermer
                </button>
            </div>
        </div>
    `;
    
    modal.className = 'modal-simple';
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });
    
    document.body.appendChild(modal);
}

// =============================================================================
// INITIALISATION OPTIMISÉE
// =============================================================================

// Nettoyage des event listeners inutiles
function optimizedInit() {
    console.log('🚀 Initialisation dashboard optimisée');
    
    // Nettoyer les anciens timers
    cleanupTimers();
    
    // Charger les données initiales
    optimizedLoadDashboardData();
    
    // Configuration des event listeners optimisés
    setupOptimizedEventListeners();
    
    // Auto-refresh avec intervalle plus long
    const globalRefreshTimer = setInterval(() => {
        // Seulement si pas d'auto-refresh actif
        if (!autoRefreshState.activity && !autoRefreshState.wallets) {
            optimizedLoadDashboardData();
        }
    }, OPTIMIZED_CONFIG.refreshInterval);
    
    refreshTimers.set('global', globalRefreshTimer);
    
    console.log('✅ Dashboard optimisé initialisé');
}

function setupOptimizedEventListeners() {
    // Event listeners avec delegation pour éviter trop d'event listeners
    document.addEventListener('click', function(e) {
        // Gestion centralisée des clics
        if (e.target.matches('[onclick*="refreshActivity"]')) {
            e.preventDefault();
            optimizedRefreshActivity();
        } else if (e.target.matches('[onclick*="refreshWallets"]')) {
            e.preventDefault();
            optimizedRefreshWallets();
        } else if (e.target.matches('[onclick*="toggleAutoRefresh"]')) {
            const section = e.target.getAttribute('onclick').match(/toggleAutoRefresh\('(\w+)'\)/)?.[1];
            if (section) {
                e.preventDefault();
                toggleAutoRefresh(section);
            }
        }
    });
}

// =============================================================================
// NETTOYAGE ET OPTIMISATION MÉMOIRE
// =============================================================================

// Nettoyage périodique de la mémoire
function performMemoryCleanup() {
    // Nettoyer le cache
    manageCacheSize();
    
    // Nettoyer les variables globales inutiles
    if (dashboardData && Object.keys(dashboardData).length > 10) {
        // Garder seulement les données essentielles
        const essential = {
            recent_activity: dashboardData.recent_activity?.slice(0, OPTIMIZED_CONFIG.maxActivityItems),
            wallets_overview: dashboardData.wallets_overview?.slice(0, OPTIMIZED_CONFIG.maxWalletsDisplay),
            timestamp: dashboardData.timestamp
        };
        dashboardData = essential;
    }
    
    // Nettoyer les éléments DOM orphelins
    const orphans = document.querySelectorAll('.optimized-message, .modal-simple');
    orphans.forEach(el => {
        if (el.parentNode && Date.now() - parseInt(el.dataset.created || 0) > 60000) {
            el.remove();
        }
    });
    
    console.log('🧹 Nettoyage mémoire effectué');
}

// Nettoyage toutes les 2 minutes
setInterval(performMemoryCleanup, 120000);

// Nettoyage à la fermeture de la page
window.addEventListener('beforeunload', () => {
    cleanupTimers();
    autoRefreshState.activity = false;
    autoRefreshState.wallets = false;
});

// =============================================================================
// EXPORT ET INITIALISATION
// =============================================================================

// Remplacer les anciennes fonctions par les optimisées
window.refreshActivity = optimizedRefreshActivity;
window.refreshWallets = optimizedRefreshWallets;
window.toggleAutoRefresh = toggleAutoRefresh;
window.showWalletDetails = showWalletDetails;
window.copyToClipboard = copyToClipboard;
window.copyAddress = copyAddress;

// Initialisation quand le DOM est prêt
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', optimizedInit);
} else {
    optimizedInit();
}

console.log("✅ Dashboard optimisé chargé - Utilisation mémoire/CPU réduite");