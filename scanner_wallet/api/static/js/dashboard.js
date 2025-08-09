// Variables globales du dashboard
let dashboardData = {};
let refreshTimer;
let lastUpdate = 0;

// Configuration
const MAX_WALLETS_DISPLAY = 10;
const MAX_ACTIVITY_DISPLAY = 15;
const MAX_TOKENS_DISPLAY = 8;

// Initialisation du dashboard
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Initialisation du dashboard');
    loadDashboardData();
    startAutoRefresh();
    
    // Mettre à jour la navigation active
    const navDashboard = document.getElementById('nav-dashboard');
    if (navDashboard) {
        navDashboard.classList.add('active');
    }
});

// Fonction principale de chargement des données
async function loadDashboardData() {
    try {
        console.log('📡 Chargement des données depuis:', `${API_BASE}/dashboard/data`);
        
        const response = await apiCall('/dashboard/data');
        dashboardData = response.data;
        
        console.log('📊 Données chargées:', dashboardData);

        // Mettre à jour toutes les sections
        updateStats();
        updateWalletsList();
        updateActivity();
        updateTopTokens();
        
        lastUpdate = Date.now();
        updateConnectionStatus(true);

    } catch (error) {
        console.error('❌ Erreur chargement dashboard:', error);
        showMessage('Erreur de chargement des données: ' + error.message, 'error');
        updateConnectionStatus(false);
    }
}

// Mise à jour des statistiques principales
function updateStats() {
    const stats = dashboardData.stats || {};
    const walletMetrics = dashboardData.wallet_metrics || {};
    const performanceMetrics = dashboardData.performance_metrics || {};
    
    // Total wallets
    const totalWalletsEl = document.getElementById('total-wallets');
    const walletsSubtitleEl = document.getElementById('wallets-subtitle');
    if (totalWalletsEl) totalWalletsEl.textContent = formatNumber(walletMetrics.total_wallets || 0);
    if (walletsSubtitleEl) walletsSubtitleEl.textContent = `${walletMetrics.high_priority || 0} haute priorité`;
    
    // Tokens découverts
    const activeTokensEl = document.getElementById('active-tokens');
    const tokensSubtitleEl = document.getElementById('tokens-subtitle');
    if (activeTokensEl) activeTokensEl.textContent = formatNumber(stats.total_unique_tokens || 0);
    if (tokensSubtitleEl) tokensSubtitleEl.textContent = `${performanceMetrics.discoveries_24h || 0} nouvelles découvertes`;
    
    // Activité 1h
    const changes1hEl = document.getElementById('changes-1h');
    const activitySubtitleEl = document.getElementById('activity-subtitle');
    if (changes1hEl) changes1hEl.textContent = formatNumber(stats.balance_changes_1h || 0);
    if (activitySubtitleEl) activitySubtitleEl.textContent = `${stats.large_transactions_24h || 0} transactions importantes`;
    
    // Dernier scan
    const lastScanEl = document.getElementById('last-scan');
    const scanSubtitleEl = document.getElementById('scan-subtitle');
    if (stats.last_scan_time) {
        const minutesAgo = Math.floor((Date.now() / 1000 - stats.last_scan_time) / 60);
        if (lastScanEl) lastScanEl.textContent = minutesAgo < 1 ? 'Maintenant' : `${minutesAgo}min`;
        if (scanSubtitleEl) scanSubtitleEl.textContent = `Efficacité: ${performanceMetrics.avg_efficiency || 0}%`;
    } else {
        if (lastScanEl) lastScanEl.textContent = 'N/A';
        if (scanSubtitleEl) scanSubtitleEl.textContent = 'Aucun scan récent';
    }

    // Mettre à jour les compteurs dans la sidebar
    const walletsCount = document.getElementById('wallets-count');
    if (walletsCount) {
        walletsCount.textContent = formatNumber(walletMetrics.total_wallets || 0);
    }
}

// Helper pour afficher les états (loading, error, empty)
function setContainerState(container, state, message = '') {
    if (!container) return;
    const states = {
        loading: '<div class="loading"><div class="spinner"></div>Chargement...</div>',
        error: `<div class="error-message">Erreur: ${message}</div>`,
        empty: '<div class="loading">Aucune donnée à afficher.</div>'
    };
    container.innerHTML = states[state] || '';
}

// Mise à jour de la liste des wallets
function updateWalletsList() {
    const container = document.getElementById('wallets-list');
    const template = document.getElementById('wallet-item-template');
    if (!container || !template) return;

    try {
        const wallets = dashboardData.wallets_overview || [];
        
        if (!wallets.length) {
            setContainerState(container, 'empty');
            return;
        }

        container.innerHTML = ''; // Clear previous content
        const displayWallets = wallets.slice(0, MAX_WALLETS_DISPLAY);

        displayWallets.forEach(wallet => {
            const clone = template.content.cloneNode(true);
            const walletItem = clone.querySelector('.wallet-item');
            
            walletItem.onclick = () => showWalletDetails(wallet.wallet_address);
            clone.querySelector('.wallet-avatar').textContent = wallet.wallet_address ? wallet.wallet_address.substring(0, 2).toUpperCase() : 'WX';
            clone.querySelector('.wallet-address').textContent = wallet.wallet_short || 'Unknown';
            
            const statusDot = clone.querySelector('.status-dot-small');
            statusDot.className = 'status-dot-small ' + getWalletStatusClass(wallet);
            clone.querySelector('.wallet-status span').textContent = getWalletStatusText(wallet);

            const priorityEl = clone.querySelector('.wallet-priority');
            const priorityCategory = getPriorityCategory(wallet.priority_score);
            priorityEl.className = 'wallet-priority ' + `priority-${priorityCategory}`;
            priorityEl.textContent = priorityCategory;

            clone.querySelector('[data-stat="priority_score"]').textContent = formatNumber(wallet.priority_score || 0);
            clone.querySelector('[data-stat="total_token_accounts"]').textContent = formatNumber(wallet.total_token_accounts || 0);
            clone.querySelector('[data-stat="transactions_24h"]').textContent = formatNumber(wallet.transactions_24h || 0);
            clone.querySelector('[data-stat="last_scan_time"]').textContent = formatTimeAgo(wallet.last_scan_time);

            container.appendChild(clone);
        });

    } catch (error) {
        console.error('Erreur dans updateWalletsList:', error);
        setContainerState(container, 'error', error.message);
    }
}

// Mise à jour de l'activité récente
function updateActivity() {
    const container = document.getElementById('activity-list');
    if (!container) return;
    
    const topTokens = dashboardData.top_tokens || [];
    const newGems = dashboardData.new_gems || [];
    const volumeAlerts = dashboardData.volume_alerts || [];
    
    // Combiner différents types d'activité
    let activities = [];
    
    // Ajouter les tokens actifs
    topTokens.slice(0, 5).forEach(token => {
        activities.push({
            type: token.net_position > 0 ? 'buy' : 'sell',
            icon: token.net_position > 0 ? '📈' : '📉',
            title: `${token.symbol} - ${token.wallet_short}`,
            details: `${token.transaction_count} TX • ${token.sol_volume} SOL`,
            time: `${token.hours_ago}h`,
            value: token.activity_score
        });
    });
    
    // Ajouter les nouvelles découvertes
    newGems.forEach(gem => {
        activities.push({
            type: 'discovery',
            icon: '🆕',
            title: `Nouveau token: ${gem.symbol}`,
            details: `${gem.wallet_short} • Confiance: ${gem.confidence}`,
            time: `${gem.hours_ago}h`,
            value: 100
        });
    });
    
    // Ajouter les alertes de volume
    volumeAlerts.forEach(alert => {
        activities.push({
            type: 'transfer',
            icon: '🔥',
            title: `Volume élevé: ${alert.symbol}`,
            details: `${alert.sol_volume} SOL • ${alert.alert_level}`,
            time: `${alert.hours_ago}h`,
            value: alert.sol_volume
        });
    });
    
    // Trier par temps et limiter
    activities = activities
        .sort((a, b) => parseFloat(a.time) - parseFloat(b.time))
        .slice(0, MAX_ACTIVITY_DISPLAY);
    
    if (!activities.length) {
        container.innerHTML = '<div class="loading">Aucune activité récente</div>';
        return;
    }

    container.innerHTML = activities.map(activity => `
        <div class="activity-item fade-in-up">
            <div class="activity-icon activity-${activity.type}">
                ${activity.icon}
            </div>
            <div class="activity-content">
                <div class="activity-title">${activity.title}</div>
                <div class="activity-details">${activity.details}</div>
            </div>
            <div class="activity-time">${activity.time} ago</div>
        </div>
    `).join('');
}

// Mise à jour des tokens populaires
function updateTopTokens() {
    const container = document.getElementById('tokens-grid');
    if (!container) return;
    
    const topTokens = dashboardData.top_tokens || [];
    
    if (!topTokens.length) {
        container.innerHTML = '<div class="loading">Aucun token actif</div>';
        return;
    }

    const displayTokens = topTokens.slice(0, MAX_TOKENS_DISPLAY);

    container.innerHTML = displayTokens.map(token => {
        const activityPercent = Math.min(100, (token.activity_score / 100) * 100);
        const logoText = token.symbol ? token.symbol.charAt(0) : 'T';
        
        return `
            <div class="token-card fade-in-up" onclick="showTokenDetails('${token.mint}')">
                <div class="token-header">
                    <div class="token-logo">${logoText}</div>
                    <div class="token-info">
                        <h3>${token.symbol || 'UNKNOWN'}</h3>
                        <div class="token-symbol">${token.mint_short || 'Unknown'}</div>
                    </div>
                </div>
                
                <div class="token-metrics">
                    <div class="token-metric">
                        <div class="token-metric-value">${formatNumber(token.transaction_count || 0)}</div>
                        <div class="token-metric-label">Transactions</div>
                    </div>
                    <div class="token-metric">
                        <div class="token-metric-value">${formatNumber(token.sol_volume || 0)}</div>
                        <div class="token-metric-label">Volume SOL</div>
                    </div>
                </div>
                
                <div class="token-activity">
                    <div class="token-activity-score">
                        <span>Activité:</span>
                        <div class="activity-bar">
                            <div class="activity-bar-fill" style="width: ${activityPercent}%"></div>
                        </div>
                        <span>${token.activity_score || 0}/100</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Fonctions utilitaires pour les wallets
function getWalletStatusClass(wallet) {
    if (!wallet || !wallet.seconds_since_scan) return 'error';
    if (wallet.seconds_since_scan <= 300) return ''; // 5 minutes
    if (wallet.seconds_since_scan <= 900) return 'warning'; // 15 minutes
    return 'error';
}

function getPriorityCategory(score) {
    if (score >= 4.0) return "high";
    if (score >= 2.0) return "medium";
    return "low";
}

function getWalletStatusText(wallet) {
    const minutesAgo = Math.floor((wallet.seconds_since_scan || 0) / 60);
    if (minutesAgo < 5) return 'Récent';
    if (minutesAgo < 30) return 'Normal';
    return 'En retard';
}

// Fonctions de rafraîchissement
async function refreshWallets() {
    const button = event.target.closest('button');
    const originalText = button.innerHTML;
    
    button.innerHTML = '<div class="spinner"></div>';
    button.disabled = true;
    
    try {
        await updateWalletsList();
        showMessage('Wallets mis à jour', 'success', 2000);
    } catch (error) {
        showMessage('Erreur lors de la mise à jour', 'error');
    } finally {
        button.innerHTML = originalText;
        button.disabled = false;
    }
}

async function refreshActivity() {
    const button = event.target.closest('button');
    const originalText = button.innerHTML;
    
    button.innerHTML = '<div class="spinner"></div>';
    button.disabled = true;
    
    try {
        await loadDashboardData();
        showMessage('Activité mise à jour', 'success', 2000);
    } catch (error) {
        showMessage('Erreur lors de la mise à jour', 'error');
    } finally {
        button.innerHTML = originalText;
        button.disabled = false;
    }
}

async function refreshTokens() {
    const button = event.target.closest('button');
    const originalText = button.innerHTML;
    
    button.innerHTML = '<div class="spinner"></div>';
    button.disabled = true;
    
    try {
        await loadDashboardData();
        showMessage('Tokens mis à jour', 'success', 2000);
    } catch (error) {
        showMessage('Erreur lors de la mise à jour', 'error');
    } finally {
        button.innerHTML = originalText;
        button.disabled = false;
    }
}

// Fonction pour démarrer le rafraîchissement automatique
function startAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }
    
    refreshTimer = setInterval(async () => {
        try {
            await loadDashboardData();
            console.log('🔄 Données rafraîchies automatiquement');
        } catch (error) {
            console.error('❌ Erreur rafraîchissement auto:', error);
        }
    }, REFRESH_INTERVAL);
    
    console.log(`⏰ Rafraîchissement automatique démarré (${REFRESH_INTERVAL/1000}s)`);
}

// Fonction pour arrêter le rafraîchissement automatique
function stopAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
        console.log('⏸️ Rafraîchissement automatique arrêté');
    }
}

// Fonctions pour afficher les détails
function showWalletDetails(walletAddress) {
    console.log('👛 Affichage détails wallet:', walletAddress);
    
    const modal = document.getElementById('details-modal');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    
    if (!modal || !title || !body) {
        console.error('Elements modal manquants');
        return;
    }
    
    title.textContent = `Détails du Wallet`;
    body.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            Chargement des détails...
        </div>
    `;
    
    modal.classList.add('show');
    
    // Charger les détails via API
    loadWalletDetails(walletAddress);
}

function showTokenDetails(tokenMint) {
    console.log('🪙 Affichage détails token:', tokenMint);
    
    const modal = document.getElementById('details-modal');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    
    if (!modal || !title || !body) {
        console.error('Elements modal manquants');
        return;
    }
    
    title.textContent = `Détails du Token`;
    body.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            Chargement des détails...
        </div>
    `;
    
    modal.classList.add('show');
    
    // Charger les détails via API
    loadTokenDetails(tokenMint);
}

async function loadWalletDetails(walletAddress) {
    try {
        const response = await apiCall(`/dashboard/wallet/${walletAddress}`);
        const wallet = response.data;
        
        const modalBody = document.getElementById('modal-body');
        if (!modalBody) return;
        
        modalBody.innerHTML = `
            <div class="wallet-details">
                <div class="detail-section">
                    <h4>🔍 Informations Générales</h4>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">Adresse:</span>
                            <span class="wallet-address">${wallet.wallet_address}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Score de Priorité:</span>
                            <span class="amount">${wallet.priority_info?.priority_score || 'N/A'}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Catégorie:</span>
                            <span class="priority-${wallet.priority_info?.priority_category || 'unknown'}">${(wallet.priority_info?.priority_category || 'unknown').toUpperCase()}</span>
                        </div>
                    </div>
                </div>
                
                <div class="detail-section">
                    <h4>📊 Statistiques</h4>
                    <div class="stats-grid">
                        <div class="stat-item">
                            <div class="stat-value">${wallet.account_stats?.total_accounts || 0}</div>
                            <div class="stat-label">Comptes Token</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">${wallet.transaction_stats?.total_transactions || 0}</div>
                            <div class="stat-label">Transactions</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">${wallet.transaction_stats?.transactions_24h || 0}</div>
                            <div class="stat-label">TX 24h</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">${wallet.transaction_stats?.total_volume_sol || 0}</div>
                            <div class="stat-label">Volume SOL</div>
                        </div>
                    </div>
                </div>
                
                <div class="detail-section">
                    <h4>🏆 Top Tokens</h4>
                    <div class="top-tokens-list">
                        ${(wallet.top_tokens || []).slice(0, 5).map(token => `
                            <div class="token-item">
                                <div class="token-symbol">${token.token_symbol}</div>
                                <div class="token-balance">${formatNumber(token.display_balance)}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                
                <div class="detail-actions">
                    <button class="btn btn-primary" onclick="navigateTo('/wallet/${wallet.wallet_address}')">
                        Voir Détails Complets
                    </button>
                </div>
            </div>
        `;
        
    } catch (error) {
        const modalBody = document.getElementById('modal-body');
        if (modalBody) {
            modalBody.innerHTML = `
                <div class="error-message">
                    Erreur lors du chargement: ${error.message}
                </div>
            `;
        }
    }
}

async function loadTokenDetails(tokenMint) {
    try {
        const response = await apiCall(`/dashboard/token/${tokenMint}`);
        const token = response.data;
        
        const modalBody = document.getElementById('modal-body');
        if (!modalBody) return;
        
        modalBody.innerHTML = `
            <div class="token-details">
                <div class="detail-section">
                    <h4>🪙 Informations Token</h4>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">Symbole:</span>
                            <span class="amount">${token.token_symbol}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Nom:</span>
                            <span>${token.token_name}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Mint:</span>
                            <span class="wallet-address">${token.mint_short}</span>
                        </div>
                    </div>
                </div>
                
                <div class="detail-section">
                    <h4>📈 Statistiques</h4>
                    <div class="stats-grid">
                        <div class="stat-item">
                            <div class="stat-value">${token.global_stats?.holder_count || 0}</div>
                            <div class="stat-label">Détenteurs</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">${token.global_stats?.total_transactions || 0}</div>
                            <div class="stat-label">Transactions</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">${token.global_stats?.transactions_24h || 0}</div>
                            <div class="stat-label">TX 24h</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">${formatNumber(token.global_stats?.net_flow || 0)}</div>
                            <div class="stat-label">Flux Net</div>
                        </div>
                    </div>
                </div>
                
                <div class="detail-section">
                    <h4>👥 Distribution</h4>
                    <div class="wallet-distribution">
                        ${(token.wallet_distribution || []).slice(0, 3).map(wallet => `
                            <div class="wallet-item">
                                <div class="wallet-address">${wallet.wallet_short}</div>
                                <div class="wallet-balance">${formatNumber(wallet.net_position)}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                
                <div class="detail-actions">
                    <button class="btn btn-primary" onclick="navigateTo('/token/${token.token_mint}')">
                        Voir Détails Complets
                    </button>
                </div>
            </div>
        `;
        
    } catch (error) {
        const modalBody = document.getElementById('modal-body');
        if (modalBody) {
            modalBody.innerHTML = `
                <div class="error-message">
                    Erreur lors du chargement: ${error.message}
                </div>
            `;
        }
    }
}

function closeModal() {
    const modal = document.getElementById('details-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

// Fonctions pour les modals d'ajout
function showWalletModal() {
    const modal = document.getElementById('details-modal');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    
    if (!modal || !title || !body) {
        console.error('Elements modal manquants pour showWalletModal');
        return;
    }
    
    title.textContent = 'Ajouter un Wallet';
    body.innerHTML = `
        <div class="add-wallet-form">
            <div class="form-group">
                <label for="wallet-address-input">Adresse du Wallet:</label>
                <input type="text" id="wallet-address-input" class="form-input" 
                       placeholder="Ex: 4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
                       maxlength="44">
                <div class="form-help">Entrez une adresse Solana valide (44 caractères)</div>
            </div>
            
            <div class="form-group">
                <label for="priority-input">Priorité Initiale:</label>
                <select id="priority-input" class="form-select">
                    <option value="5.0">Normal (5.0)</option>
                    <option value="7.0">Élevée (7.0)</option>
                    <option value="9.0">Critique (9.0)</option>
                    <option value="2.0">Basse (2.0)</option>
                </select>
            </div>
            
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Annuler</button>
                <button class="btn btn-primary" onclick="addWallet()">Ajouter</button>
            </div>
        </div>
    `;
    
    modal.classList.add('show');
}

async function addWallet() {
    const addressInput = document.getElementById('wallet-address-input');
    const priorityInput = document.getElementById('priority-input');
    
    if (!addressInput || !priorityInput) {
        showMessage('Erreur: éléments du formulaire manquants', 'error');
        return;
    }
    
    const address = addressInput.value.trim();
    const priority = parseFloat(priorityInput.value);
    
    if (!address || address.length !== 44) {
        showMessage('Adresse de wallet invalide', 'error');
        return;
    }
    
    try {
        await apiCall('/admin/wallet/add', {
            method: 'POST',
            body: JSON.stringify({
                wallet_address: address,
                priority_score: priority
            })
        });
        
        showMessage('Wallet ajouté avec succès', 'success');
        closeModal();
        await loadDashboardData();
        
    } catch (error) {
        showMessage('Erreur lors de l\'ajout: ' + error.message, 'error');
    }
}

// Nettoyage à la fermeture
window.addEventListener('beforeunload', () => {
    stopAutoRefresh();
});

// Fermeture de modal avec Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal();
    }
});

// Fermeture de modal en cliquant à l'extérieur
const detailsModal = document.getElementById('details-modal');
if (detailsModal) {
    detailsModal.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) {
            closeModal();
        }
    });
}

// Style supplémentaire pour les modals et formulaires
const additionalStyles = `
    <style>
    .detail-section {
        margin-bottom: 24px;
        padding-bottom: 20px;
        border-bottom: 1px solid var(--border);
    }
    
    .detail-section:last-child {
        border-bottom: none;
    }
    
    .detail-section h4 {
        color: var(--text-primary);
        margin-bottom: 16px;
        font-size: 16px;
        font-weight: 600;
    }
    
    .detail-grid {
        display: grid;
        gap: 12px;
    }
    
    .detail-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;
    }
    
    .detail-label {
        color: var(--text-secondary);
        font-weight: 500;
    }
    
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 16px;
    }
    
    .stat-item {
        text-align: center;
        padding: 16px;
        background: var(--surface);
        border-radius: 8px;
        border: 1px solid var(--border);
    }
    
    .stat-value {
        font-size: 20px;
        font-weight: 600;
        color: var(--primary);
        margin-bottom: 4px;
    }
    
    .stat-label {
        font-size: 12px;
        color: var(--text-muted);
        text-transform: uppercase;
    }
    
    .detail-actions {
        margin-top: 24px;
        display: flex;
        gap: 12px;
        justify-content: flex-end;
    }
    
    .top-tokens-list, .wallet-distribution {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    
    .token-item, .wallet-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 12px;
        background: var(--surface);
        border-radius: 6px;
        border: 1px solid var(--border);
    }
    
    .form-group {
        margin-bottom: 20px;
    }
    
    .form-group label {
        display: block;
        margin-bottom: 8px;
        color: var(--text-primary);
        font-weight: 500;
    }
    
    .form-input, .form-select {
        width: 100%;
        padding: 12px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        color: var(--text-primary);
        font-size: 14px;
    }
    
    .form-input:focus, .form-select:focus {
        outline: none;
        border-color: var(--primary);
    }
    
    .form-help {
        margin-top: 4px;
        font-size: 12px;
        color: var(--text-muted);
    }
    
    .form-actions {
        display: flex;
        gap: 12px;
        justify-content: flex-end;
        margin-top: 24px;
    }
    </style>
`;

// Injecter les styles seulement si pas déjà présents
if (!document.getElementById('dashboard-styles')) {
    const styleElement = document.createElement('div');
    styleElement.id = 'dashboard-styles';
    styleElement.innerHTML = additionalStyles;
    document.head.appendChild(styleElement);
}
