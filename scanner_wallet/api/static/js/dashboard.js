// ===== NOUVELLES FONCTIONS POUR LES THÈMES =====

// Variables pour les thèmes
let currentTheme = 'dark';

// Fonction pour restaurer le thème (appelée automatiquement)
function initializeTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    const body = document.body;
    
    body.dataset.theme = savedTheme;
    currentTheme = savedTheme;
    
    // Mettre à jour l'icône si elle existe
    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) {
        themeIcon.textContent = savedTheme === 'dark' ? '🌙' : '☀️';
    }
}

// Initialiser le thème dès que possible
initializeTheme();

// ===== VOTRE CODE JAVASCRIPT EXISTANT =====

// Variables globales du dashboard
let dashboardData = {};
let refreshTimer;
let lastUpdate = 0;
let portfolioPieChart = null;
let topTokensBarChart = null;
let tokenPriceHistoryChart = null;

// State for wallets list
let fullWalletsList = [];
let currentSort = { key: 'last_scan_time', order: 'desc' };
let currentFilter = '';
let currentPage = 1;
const WALLETS_PER_PAGE = 10;

// Configuration
const MAX_ACTIVITY_DISPLAY = 35;
const MAX_TOKENS_DISPLAY = 35;

// Initialisation du dashboard
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Initialisation du dashboard');
    
    // Initialiser le thème
    initializeTheme();
    
    // Charger les données du dashboard
    loadDashboardData();
    startAutoRefresh();
    
    // Mettre à jour la navigation active
    const navDashboard = document.getElementById('nav-dashboard');
    if (navDashboard) {
        navDashboard.classList.add('active');
    }
    // Add event listeners for new controls
    const searchInput = document.getElementById('wallet-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            currentFilter = e.target.value.toLowerCase();
            currentPage = 1; // Reset to first page on search
            renderWalletsList();
        });
    }

    const sortContainer = document.querySelector('.sort-container');
    if (sortContainer) {
        sortContainer.addEventListener('click', (e) => {
            if (e.target.tagName === 'BUTTON') {
                const sortKey = e.target.dataset.sort;
                if (currentSort.key === sortKey) {
                    // Toggle order if same key is clicked
                    currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
                } else {
                    currentSort.key = sortKey;
                    currentSort.order = 'desc'; // Default to descending for new sort key
                }
                currentPage = 1; // Reset to first page on sort
                
                // Update active button style
                sortContainer.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
                e.target.classList.add('active');

                renderWalletsList();
            }
        });
    }
});

function updateTopTokensChart() {
    const topTokens = dashboardData.top_tokens || [];
    const ctx = document.getElementById('top-tokens-bar-chart');
    const card = document.getElementById('top-tokens-volume-card');
    if (!ctx || !card) return;

    const displayTokens = topTokens.slice(0, 7).filter(t => t.sol_volume > 0);

    if (displayTokens.length === 0) {
        card.style.display = 'none';
        return;
    }
    
    card.style.display = 'block';

    const labels = displayTokens.map(t => t.symbol);
    const data = displayTokens.map(t => t.sol_volume);

    if (topTokensBarChart) {
        topTokensBarChart.destroy();
    }

    topTokensBarChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Volume (SOL)',
                data: data,
                backgroundColor: 'rgba(75, 192, 192, 0.7)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                title: { display: false }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    ticks: { color: getComputedStyle(document.body).getPropertyValue('--text-color') },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' }
                },
                y: {
                    ticks: { color: getComputedStyle(document.body).getPropertyValue('--text-color') },
                    grid: { display: false }
                }
            }
        }
    });
}

function updatePortfolioChart() {
    const wallets = dashboardData.wallets_overview || [];
    const ctx = document.getElementById('portfolio-pie-chart');
    const card = document.getElementById('portfolio-distribution-card');
    if (!ctx || !card) return;

    const walletsWithBalance = wallets.filter(w => w.usd_balance > 0);

    if (walletsWithBalance.length === 0) {
        card.style.display = 'none';
        return;
    }
    
    card.style.display = 'block';

    const labels = walletsWithBalance.map(w => w.wallet_short);
    const data = walletsWithBalance.map(w => w.usd_balance);
    const totalValue = data.reduce((a, b) => a + b, 0);

    if (portfolioPieChart) {
        portfolioPieChart.destroy();
    }

    portfolioPieChart = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                label: 'Portfolio Value (USD)',
                data: data,
                backgroundColor: [
                    'rgba(255, 99, 132, 0.7)', 'rgba(54, 162, 235, 0.7)',
                    'rgba(255, 206, 86, 0.7)', 'rgba(75, 192, 192, 0.7)',
                    'rgba(153, 102, 255, 0.7)', 'rgba(255, 159, 64, 0.7)',
                    'rgba(255, 99, 255, 0.7)', 'rgba(99, 255, 132, 0.7)'
                ],
                borderColor: 'rgba(40, 42, 54, 0.5)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: getComputedStyle(document.body).getPropertyValue('--text-color') || '#fff',
                        boxWidth: 20,
                        padding: 15
                    }
                },
                title: {
                    display: true,
                    text: `Total: $${totalValue.toFixed(2)} USD`,
                    color: getComputedStyle(document.body).getPropertyValue('--text-color') || '#fff',
                    font: { size: 16 }
                }
            }
        }
    });
}

// Fonction principale de chargement des données
async function loadDashboardData() {
    try {
        console.log('📡 Chargement des données depuis:', `${API_BASE}/dashboard/data`);
        
        const response = await apiCall('/dashboard/data');
        dashboardData = response.data;
        
        console.log('📊 Données chargées:', dashboardData);

        // Mettre à jour toutes les sections
        fullWalletsList = response.data.wallets_overview || [];
        updateStats();
        renderWalletsList(); // Use the new render function
        updateActivity();
        updateTopTokens();
        updatePortfolioChart();
        updateTopTokensChart();
        
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


function renderWalletsList() {
    const container = document.getElementById('wallets-list');
    const template = document.getElementById('wallet-item-template');
    if (!container || !template) return;

    // 1. Filtering
    let processedWallets = fullWalletsList.filter(wallet => {
        return wallet.wallet_address.toLowerCase().includes(currentFilter);
    });

    // 2. Sorting
    processedWallets.sort((a, b) => {
        const valA = a[currentSort.key];
        const valB = b[currentSort.key];
        
        let comparison = 0;
        if (valA > valB) {
            comparison = 1;
        } else if (valA < valB) {
            comparison = -1;
        }
        
        return currentSort.order === 'desc' ? comparison * -1 : comparison;
    });

    // 3. Pagination
    const totalPages = Math.ceil(processedWallets.length / WALLETS_PER_PAGE);
    currentPage = Math.min(currentPage, totalPages) || 1;
    const startIndex = (currentPage - 1) * WALLETS_PER_PAGE;
    const walletsToDisplay = processedWallets.slice(startIndex, startIndex + WALLETS_PER_PAGE);

    // 4. Rendering
    container.innerHTML = '';
    if (walletsToDisplay.length === 0) {
        setContainerState(container, 'empty', 'Aucun wallet ne correspond à vos critères.');
       
    } else {
        walletsToDisplay.forEach(wallet => {
        const clone = template.content.cloneNode(true);
        const walletItem = clone.querySelector('.wallet-item');
        
        walletItem.onclick = () => showWalletDetails(wallet.wallet_address);
        walletItem.dataset.address = wallet.wallet_address;
        
        clone.querySelector('.wallet-avatar').textContent = wallet.wallet_address ? wallet.wallet_address.substring(0, 2).toUpperCase() : 'WX';
        
        const link = clone.querySelector('.wallet-address-link');
        if (link) {
            link.href = wallet.solscan_url || '#';
        }
        clone.querySelector('.wallet-address').textContent = wallet.wallet_short || 'Unknown';

        const copyBtn = clone.querySelector('.copy-btn');
        if(copyBtn) {
            copyBtn.dataset.address = wallet.wallet_address;
        }
        
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
        clone.querySelector('[data-stat="total_scans"]').textContent = formatNumber(wallet.total_scans || 0);
        clone.querySelector('[data-stat="last_scan_time"]').textContent = formatTimeAgo(wallet.last_scan_time);

        const balance_text = `${formatNumber(wallet.sol_balance)} SOL ($${formatNumber(wallet.usd_balance)} / €${formatNumber(wallet.eur_balance)})`;
        clone.querySelector('[data-stat="balance"]').textContent = balance_text;

        container.appendChild(clone);
    });
    }

    renderPaginationControls(totalPages, processedWallets.length);
}

function renderPaginationControls(totalPages, totalItems) {
    const container = document.getElementById('wallets-pagination');
    if (!container) return;

    container.innerHTML = '';
    if (totalPages <= 1) return;

    const summary = document.createElement('span');
    summary.className = 'pagination-summary';
    summary.textContent = `Page ${currentPage} sur ${totalPages} (${totalItems} wallets)`;
    container.appendChild(summary);

    const buttonsWrapper = document.createElement('div');
    buttonsWrapper.className = 'pagination-buttons';

    // Previous button
    const prevButton = document.createElement('button');
    prevButton.textContent = '‹ Préc.';
    prevButton.className = 'btn btn-sm btn-secondary';
    prevButton.disabled = currentPage === 1;
    prevButton.onclick = () => {
        if (currentPage > 1) {
            currentPage--;
            renderWalletsList();
        }
    };
    buttonsWrapper.appendChild(prevButton);

    // Page buttons (simplified logic for now)
    // We can add more complex logic later (e.g., ellipsis for many pages)
    for (let i = 1; i <= totalPages; i++) {
        // Simple case: show all page numbers
        const button = document.createElement('button');
        button.textContent = i;
        button.className = 'btn btn-sm ' + (i === currentPage ? 'btn-primary' : 'btn-secondary');
        button.onclick = () => {
            if (i !== currentPage) {
                currentPage = i;
                renderWalletsList();
            }
        };
        buttonsWrapper.appendChild(button);
    }

    // Next button
    const nextButton = document.createElement('button');
    nextButton.textContent = 'Suiv. ›';
    nextButton.className = 'btn btn-sm btn-secondary';
    nextButton.disabled = currentPage === totalPages;
    nextButton.onclick = () => {
        if (currentPage < totalPages) {
            currentPage++;
            renderWalletsList();
        }
    };
    buttonsWrapper.appendChild(nextButton);

    container.appendChild(buttonsWrapper);
}


// Mise à jour de l'activité récente
function updateActivity() {
    const container = document.getElementById('activity-list');
    const template = document.getElementById('activity-item-template');
    if (!container || !template) return;

    try {
        const activities = dashboardData.recent_activity || [];
        
        if (!activities.length) {
            setContainerState(container, 'empty', 'Aucune activité récente');
            return;
        }

        container.innerHTML = ''; // Clear previous content
        const displayActivities = activities.slice(0, MAX_ACTIVITY_DISPLAY);

        displayActivities.forEach(activity => {
            const clone = template.content.cloneNode(true);
            const iconEl = clone.querySelector('.activity-icon');
            const linksEl = clone.querySelector('.activity-links');
            let icon, title, details, activityClass;

            // Générer l'URL Solscan pour le wallet
            const walletSolscanUrl = `https://solscan.io/account/${activity.wallet_address}`;
            const walletShort = activity.wallet_address.substring(0, 6) + '...';

            if (activity.type === 'transaction') {
                activityClass = activity.transaction_type === 'buy' ? 'buy' : 'sell';
                icon = activityClass === 'buy' ? '📈' : '📉';
                
                // Titre avec lien vers le wallet
                title = `${activity.token_symbol || 'Unknown'} - `;
                
                details = `${activity.transaction_type.toUpperCase()}: ${formatNumber(activity.token_amount)} for ${formatNumber(activity.sol_amount)} SOL`;
            } else { // discovery
                activityClass = 'discovery';
                icon = '🆕';
                
                // Titre avec lien vers le wallet
                title = `Nouveau Token: ${activity.token_symbol || 'Unknown'} - `;
                
                details = `Découvert | Balance: ${formatNumber(activity.initial_balance)}`;
            }
            
            iconEl.className = `activity-icon activity-${activityClass}`;
            iconEl.textContent = icon;
            
            // Construire le titre avec le lien wallet
            const titleElement = clone.querySelector('.activity-title');
            titleElement.innerHTML = `
                ${title}
                <a href="${walletSolscanUrl}" 
                   target="_blank" 
                   rel="noopener noreferrer"
                   class="wallet-link"
                   title="Voir le wallet sur Solscan">
                    ${walletShort}
                </a>
            `;
            
            clone.querySelector('.activity-details').textContent = details;
            clone.querySelector('.activity-time').textContent = formatTimeAgo(activity.timestamp);

            // Liens pour les transactions (token)
            if (activity.solscan_url) {
                linksEl.innerHTML = `
                    <a href="${activity.solscan_url}" target="_blank" rel="noopener noreferrer">TX Solscan</a>
                `;
                
                if (activity.dexscreener_url) {
                    linksEl.innerHTML += ` | <a href="${activity.dexscreener_url}" target="_blank" rel="noopener noreferrer">DexScreener</a>`;
                }
                
                if (activity.pumpfun_url) {
                    linksEl.innerHTML += ` | <a href="${activity.pumpfun_url}" target="_blank" rel="noopener noreferrer">Pump.fun</a>`;
                }
            }

            container.appendChild(clone);
        });

    } catch (error) {
        console.error('Erreur dans updateActivity:', error);
        setContainerState(container, 'error', error.message);
    }
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
        await loadDashboardData();
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

function copyAddress(button, event) {
    event.stopPropagation(); // Prevent the wallet detail modal from opening
    const address = button.dataset.address;
    if (!address) return;

    navigator.clipboard.writeText(address).then(() => {
        const copyIcon = button.querySelector('.copy-icon');
        const checkIcon = button.querySelector('.check-icon');
        
        if (copyIcon && checkIcon) {
            copyIcon.style.display = 'none';
            checkIcon.style.display = 'inline-block';
            
            // Revert after 2 seconds
            setTimeout(() => {
                copyIcon.style.display = 'inline-block';
                checkIcon.style.display = 'none';
            }, 2000);
        }
        
        // Assuming a showMessage function exists for user feedback
        if (typeof showMessage === 'function') {
            showMessage(`Adresse copiée: ${address.substring(0, 8)}...`, 'success', 2000);
        }
    }).catch(err => {
        console.error('Failed to copy address: ', err);
        if (typeof showMessage === 'function') {
            showMessage('Erreur de copie', 'error');
        }
    });
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
    const modalBody = document.getElementById('modal-body');
    if (!modalBody) return;
    
    try {
        // Fetch details and history in parallel
        const [detailsResponse, historyResponse] = await Promise.all([
            apiCall(`/dashboard/token/${tokenMint}`),
            apiCall(`/dashboard/token/${tokenMint}/history`)
        ]);
    
        const token = detailsResponse.data;
        const history = historyResponse.data;
        modalBody.innerHTML = `
            <div class="token-details">
                <div class="detail-section">
                    <h4>🪙 Informations Token</h4>
                    <div class="detail-grid">
                        <div class="detail-item"><span class="detail-label">Symbole:</span><span class="amount">${token.token_symbol}</span></div>
                        <div class="detail-item"><span class="detail-label">Nom:</span><span>${token.token_name}</span></div>
                        <div class="detail-item"><span class="detail-label">Mint:</span><span class="wallet-address">${token.mint_short}</span></div>
                    </div>
                </div>

                <div class="detail-section">
                    <h4>Prix (24h)</h4>
                    <div class="chart-container" style="height: 200px;">
                        <canvas id="token-price-history-chart"></canvas>
                    </div>
                </div>
                
                <div class="detail-section">
                    <h4>📈 Statistiques</h4>
                    <div class="stats-grid">
                        <div class="stat-item"><div class="stat-value">${token.global_stats?.holder_count || 0}</div><div class="stat-label">Détenteurs</div></div>
                        <div class="stat-item"><div class="stat-value">${token.global_stats?.total_transactions || 0}</div><div class="stat-label">Transactions</div></div>
                        <div class="stat-item"><div class="stat-value">${token.global_stats?.transactions_24h || 0}</div><div class="stat-label">TX 24h</div></div>
                        <div class="stat-item"><div class="stat-value">${formatNumber(token.global_stats?.net_flow || 0)}</div><div class="stat-label">Flux Net</div></div>
                    </div>
                </div>
                
                <div class="detail-actions">
                    <button class="btn btn-primary" onclick="navigateTo('/token/${token.token_mint}')">Voir Détails Complets</button>
                </div>
            </div>
        `;
    
        // Render the chart
        const ctx = document.getElementById('token-price-history-chart');
        if (tokenPriceHistoryChart) {
            tokenPriceHistoryChart.destroy();
        }
        if (ctx && history && history.length > 0) {
            tokenPriceHistoryChart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'Prix (USD)',
                        data: history,
                        borderColor: 'rgba(75, 192, 192, 1)',
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        fill: true,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            type: 'time',
                            time: { unit: 'hour' },
                            ticks: { color: getComputedStyle(document.body).getPropertyValue('--text-color') }
                        },
                        y: {
                            ticks: { 
                                color: getComputedStyle(document.body).getPropertyValue('--text-color'),
                                callback: function(value) { return '$' + value.toPrecision(4); }
                            }
                        }
                    },
                    plugins: { legend: { display: false } }
                }
            });
        } else if (ctx) {
            ctx.parentElement.innerHTML = '<div class="loading">Aucun historique de prix disponible.</div>';
        }
    
    } catch (error) {
        modalBody.innerHTML = `<div class="error-message">Erreur lors du chargement: ${error.message}</div>`;
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
document.addEventListener('DOMContentLoaded', function() {
    const detailsModal = document.getElementById('details-modal');
    if (detailsModal) {
        detailsModal.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                closeModal();
            }
        });
    }
});