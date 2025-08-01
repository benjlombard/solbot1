// script.js

class SolanaWalletDashboard {
    constructor() {
        this.walletAddresses = [];
        this.currentWallet = 'all';
        this.apiBaseUrl = '/api';
        this.refreshInterval = 30000; // 30 secondes
        this.autoRefreshEnabled = true;
        this.distributionChart = null;
        this.lastTransactionCount = 0;
        this.alertThreshold = 1; // SOL
        this.tokenCache = new Map();
        
        this.init();
    }

    async init() {
        console.log('🚀 Initialisation du dashboard Multi-Wallet Solana');
        
        // Afficher l'overlay de chargement
        this.showLoading();
        
        try {
            // Charger la liste des wallets
            await this.loadWallets();
            
            // Charger les données initiales
            await this.loadDashboardData();
            
            // Initialiser les event listeners
            this.setupEventListeners();
            
            // Démarrer l'auto-refresh
            this.startAutoRefresh();
            
            // Masquer l'overlay de chargement
            this.hideLoading();
            
            console.log('✅ Dashboard multi-wallet initialisé avec succès');
        } catch (error) {
            console.error('❌ Erreur lors de l\'initialisation:', error);
            this.showAlert('error', 'Erreur d\'initialisation', 'Impossible de charger les données du dashboard');
            this.hideLoading();
        }
    }

    async loadWallets() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/wallets`);
            if (response.ok) {
                const data = await response.json();
                this.walletAddresses = data.wallets || [];
            } else {
                // Fallback vers l'ancienne méthode si l'API n'existe pas encore
                this.walletAddresses = ['2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK'];
            }
            
            this.updateWalletSelector();
            this.updateWalletTabs();
            
        } catch (error) {
            console.error('Erreur lors du chargement des wallets:', error);
            // Fallback
            this.walletAddresses = ['2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK'];
            this.updateWalletSelector();
            this.updateWalletTabs();
        }
    }

    updateWalletSelector() {
        const selector = document.getElementById('walletSelect');
        if (!selector) return;

        selector.innerHTML = '<option value="all">Tous les wallets</option>';
        
        this.walletAddresses.forEach(address => {
            const option = document.createElement('option');
            option.value = address;
            option.textContent = `${address.substring(0, 8)}...${address.substring(-8)}`;
            selector.appendChild(option);
        });
    }

    updateWalletTabs() {
        const tabsContainer = document.getElementById('walletTabs');
        if (!tabsContainer) return;

        tabsContainer.innerHTML = '';

        // Tab pour tous les wallets
        const allTab = document.createElement('div');
        allTab.className = `wallet-tab ${this.currentWallet === 'all' ? 'active' : ''}`;
        allTab.innerHTML = `
            <i class="fas fa-layer-group"></i>
            <span>Tous</span>
        `;
        allTab.addEventListener('click', () => this.switchWallet('all'));
        tabsContainer.appendChild(allTab);

        // Tabs individuels
        this.walletAddresses.forEach(address => {
            const tab = document.createElement('div');
            tab.className = `wallet-tab ${this.currentWallet === address ? 'active' : ''}`;
            tab.innerHTML = `
                <i class="fas fa-wallet"></i>
                <div>
                    <div>${address.substring(0, 6)}...</div>
                    <div class="wallet-tab-address">${address.substring(-6)}</div>
                </div>
            `;
            tab.addEventListener('click', () => this.switchWallet(address));
            tabsContainer.appendChild(tab);
        });
    }

    async switchWallet(walletAddress) {
        this.currentWallet = walletAddress;
        this.updateWalletTabs();
        
        // Mettre à jour l'affichage de l'adresse
        const walletAddressElement = document.getElementById('walletAddress');
        if (walletAddressElement) {
            if (walletAddress === 'all') {
                walletAddressElement.textContent = 'Tous les wallets';
            } else {
                walletAddressElement.textContent = walletAddress;
            }
        }

        // Recharger les données
        await this.loadDashboardData();
    }

    setupEventListeners() {
        // Sélecteur de wallet
        const walletSelector = document.getElementById('walletSelect');
        if (walletSelector) {
            walletSelector.addEventListener('change', (e) => {
                this.switchWallet(e.target.value);
            });
        }

        // Bouton de copie de l'adresse
        const copyBtn = document.querySelector('.copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => this.copyWalletAddress());
        }

        // Filtres
        const minAmountInput = document.getElementById('minAmount');
        const transactionLimitSelect = document.getElementById('transactionLimit');
        const transactionTypeSelect = document.getElementById('transactionType');
        
        if (minAmountInput) {
            minAmountInput.addEventListener('change', () => this.applyFilters());
        }
        
        if (transactionLimitSelect) {
            transactionLimitSelect.addEventListener('change', () => this.applyFilters());
        }

        if (transactionTypeSelect) {
            transactionTypeSelect.addEventListener('change', () => this.applyFilters());
        }

        // Auto-refresh au focus de la fenêtre
        window.addEventListener('focus', () => {
            if (this.autoRefreshEnabled) {
                this.refreshData();
            }
        });

        // Gestion des raccourcis clavier
        document.addEventListener('keydown', (event) => {
            if (event.ctrlKey || event.metaKey) {
                switch (event.key) {
                    case 'r':
                        event.preventDefault();
                        this.refreshData();
                        break;
                    case 'c':
                        if (event.target.closest('.wallet-address')) {
                            event.preventDefault();
                            this.copyWalletAddress();
                        }
                        break;
                }
            }
        });
    }

    async loadDashboardData() {
        try {
            // Construire l'URL avec le wallet sélectionné
            let statsUrl = `${this.apiBaseUrl}/stats`;
            if (this.currentWallet !== 'all') {
                statsUrl += `/${this.currentWallet}`;
            }

            // Charger les statistiques principales
            const statsResponse = await fetch(statsUrl);
            if (!statsResponse.ok) {
                throw new Error(`Erreur HTTP: ${statsResponse.status}`);
            }
            const statsData = await statsResponse.json();
            
            // Mettre à jour l'interface avec les stats
            this.updateStatsDisplay(statsData);
            
            // Créer le graphique de distribution
            this.createDistributionChart(statsData.transaction_distribution);
            
            // Charger les transactions
            await this.loadTransactions();
            
        } catch (error) {
            console.error('Erreur lors du chargement des données:', error);
            throw error;
        }
    }

    formatCurrency(amount, currency = 'USD') {
        return new Intl.NumberFormat('fr-FR', {
            style: 'currency',
            currency: currency
        }).format(amount);
    }

    updateStatsDisplay(data) {
        const stats = data.stats;
        
        // Solde avec devises
        this.updateElement('balance', `${this.formatNumber(stats.balance_sol, 4)} SOL`);
        this.updateElement('balanceUsd', this.formatCurrency(stats.balance_usd, 'USD'));
        this.updateElement('balanceEur', this.formatCurrency(stats.balance_eur, 'EUR'));
        
        // Transactions en entier
        this.updateElement('totalTransactions', stats.total_transactions);
        
        // Volume avec devises
        this.updateElement('totalVolume', `${this.formatNumber(stats.total_volume, 2)} SOL`);
        this.updateElement('totalVolumeUsd', this.formatCurrency(stats.total_volume_usd, 'USD'));
        this.updateElement('totalVolumeEur', this.formatCurrency(stats.total_volume_eur, 'EUR'));
        
        // P&L avec devises et couleur
        const pnlElement = document.getElementById('pnl');
        if (pnlElement) {
            pnlElement.innerHTML = `
                ${stats.pnl >= 0 ? '+' : ''}${this.formatNumber(stats.pnl, 4)} SOL<br>
                <small>${this.formatCurrency(stats.pnl_usd, 'USD')} / ${this.formatCurrency(stats.pnl_eur, 'EUR')}</small>
            `;
            pnlElement.className = `stat-value ${stats.pnl >= 0 ? 'positive' : 'negative'}`;
        }
        
        // Plus grosse transaction avec devises
        const largestElement = document.getElementById('largestTransaction');
        if (largestElement) {
            largestElement.innerHTML = `
                ${this.formatNumber(stats.largest_transaction, 4)} SOL<br>
                <small>${this.formatCurrency(stats.largest_transaction_usd, 'USD')}</small>
            `;
        }
        
        // Dernière mise à jour
        this.updateElement('lastUpdate', stats.last_update);
    }

    async loadTransactions() {
        try {
            const minAmount = document.getElementById('minAmount')?.value || 0;
            const limit = document.getElementById('transactionLimit')?.value || 50;
            const transactionType = document.getElementById('transactionType')?.value || 'all';
            
            let transactionsUrl = `${this.apiBaseUrl}/transactions?min_amount=${minAmount}&limit=${limit}`;
            
            if (this.currentWallet !== 'all') {
                transactionsUrl += `&wallet=${this.currentWallet}`;
            }
            
            if (transactionType !== 'all') {
                transactionsUrl += `&type=${transactionType}`;
            }
            
            const response = await fetch(transactionsUrl);
            if (!response.ok) {
                throw new Error(`Erreur HTTP: ${response.status}`);
            }
            
            const transactions = await response.json();
            this.displayTransactions(transactions);
            this.updateTransactionStats(transactions);
            
        } catch (error) {
            console.error('Erreur lors du chargement des transactions:', error);
            this.showAlert('error', 'Erreur', 'Impossible de charger les transactions');
        }
    }

    displayTransactions(transactions) {
        const transactionsList = document.getElementById('transactionsList');
        if (!transactionsList) return;

        if (transactions.length === 0) {
            transactionsList.innerHTML = `
                <div class="text-center" style="padding: 40px;">
                    <i class="fas fa-search" style="font-size: 48px; color: #ccc; margin-bottom: 15px;"></i>
                    <p style="color: #666;">Aucune transaction trouvée avec les filtres actuels</p>
                </div>
            `;
            return;
        }

        const transactionsHTML = transactions.map(tx => {
            const date = new Date(tx.block_time * 1000);
            const amount = parseFloat(tx.amount);
            const fee = parseFloat(tx.fee);
            
            // Informations du token
            const tokenSymbol = tx.token_symbol || 'SOL';
            const tokenName = tx.token_name || 'Solana';
            const tokenAmount = tx.token_amount || Math.abs(amount);
            const transactionType = tx.transaction_type || 'other';
            const pricePerToken = tx.price_per_token || 0;
            const tokenMint = tx.token_mint;
            
            // Déterminer l'icône du type
            let typeIcon = 'fas fa-exchange-alt';
            let typeClass = transactionType;
            
            switch (transactionType) {
                case 'buy':
                    typeIcon = 'fas fa-arrow-trend-up';
                    break;
                case 'sell':
                    typeIcon = 'fas fa-arrow-trend-down';
                    break;
                case 'transfer':
                    typeIcon = 'fas fa-arrow-right-arrow-left';
                    break;
                case 'sol_transfer':
                    typeIcon = 'fas fa-coins';
                    break;
                default:
                    if (amount > 0) {
                        typeIcon = 'fas fa-arrow-down';
                        typeClass = 'incoming';
                    } else if (amount < 0) {
                        typeIcon = 'fas fa-arrow-up';
                        typeClass = 'outgoing';
                    } else {
                        typeClass = 'neutral';
                    }
            }

            // Vérifier si c'est une grosse transaction
            const isLargeTransaction = Math.abs(amount) >= this.alertThreshold;

            // Générer les liens
            const links = this.generateTransactionLinks(tx.signature, tokenMint);

            return `
                <div class="transaction-item" data-signature="${tx.signature}">
                    <div class="transaction-type ${typeClass}">
                        <i class="${typeIcon}"></i>
                    </div>
                    <div class="transaction-details">
                        ${tx.is_token_transaction && tokenMint ? `
                            <div class="token-info">
                                <div class="token-logo">
                                    ${tokenSymbol.substring(0, 3)}
                                </div>
                                <div class="token-details">
                                    <div class="token-symbol">${tokenSymbol}</div>
                                    <div class="token-name">${tokenName}</div>
                                </div>
                            </div>
                        ` : ''}
                        
                        <div class="transaction-signature">
                            ${tx.signature}
                        </div>
                        
                        <div class="transaction-meta-extended">
                            <span class="transaction-type-badge ${transactionType}">
                                ${this.getTransactionTypeLabel(transactionType)}
                            </span>
                            
                            <div class="transaction-time">
                                <i class="fas fa-clock"></i>
                                ${this.formatRelativeTime(date)}
                            </div>
                            
                            <div class="transaction-status ${tx.status}">
                                ${tx.status === 'success' ? 'Succès' : 'Échec'}
                            </div>
                            
                            ${isLargeTransaction ? '<span class="large-transaction-indicator">💰 Grosse transaction</span>' : ''}
                        </div>
                        
                        ${links}
                    </div>
                    
                    <div class="transaction-amount">
                        ${tx.is_token_transaction && tokenAmount > 0 ? `
                            <div class="token-amount-display">
                                <div class="token-amount-value">
                                    ${transactionType === 'sell' ? '-' : '+'}${this.formatNumber(tokenAmount, 4)} ${tokenSymbol}
                                </div>
                                ${pricePerToken > 0 ? `
                                    <div class="price-per-token">
                                        ${this.formatNumber(pricePerToken, 6)} SOL/token
                                    </div>
                                ` : ''}
                            </div>
                        ` : ''}
                        
                        <div class="amount-value ${amount >= 0 ? 'positive' : amount < 0 ? 'negative' : 'neutral'}">
                            ${amount >= 0 ? '+' : ''}${this.formatNumber(amount, 4)} SOL
                        </div>
                        
                        <div class="fee-value">
                            Frais: ${this.formatNumber(fee, 6)} SOL
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        transactionsList.innerHTML = transactionsHTML;

        // Ajouter les event listeners pour les transactions
        this.addTransactionEventListeners();
    }

    getTransactionTypeLabel(type) {
        const labels = {
            'buy': '📈 ACHAT',
            'sell': '📉 VENTE',
            'transfer': '🔄 TRANSFERT',
            'sol_transfer': '⚡ SOL',
            'other': '🔹 AUTRE'
        };
        return labels[type] || labels.other;
    }

    generateTransactionLinks(signature, tokenMint) {
        let links = `
            <div class="transaction-links">
                <a href="https://solscan.io/tx/${signature}" target="_blank">
                    <i class="fas fa-external-link-alt"></i> Solscan
                </a>
        `;

        if (tokenMint && tokenMint !== 'SOL') {
            links += `
                <a href="https://pump.fun/${tokenMint}" target="_blank">
                    <i class="fas fa-rocket"></i> Pump.fun
                </a>
                <a href="https://dexscreener.com/solana/${tokenMint}" target="_blank">
                    <i class="fas fa-chart-line"></i> DexScreener
                </a>
                <a href="https://jup.ag/swap/SOL-${tokenMint}" target="_blank">
                    <i class="fas fa-exchange-alt"></i> Jupiter
                </a>
            `;
        }

        links += '</div>';
        return links;
    }

    addTransactionEventListeners() {
        const transactionItems = document.querySelectorAll('.transaction-item');
        transactionItems.forEach(item => {
            item.addEventListener('click', (e) => {
                // Ne pas déclencher si on clique sur un lien
                if (e.target.closest('.transaction-links a')) {
                    return;
                }
                const signature = item.dataset.signature;
                this.openTransactionDetails(signature);
            });
        });
    }

    openTransactionDetails(signature) {
        const url = `https://solscan.io/tx/${signature}`;
        window.open(url, '_blank');
    }

    updateTransactionStats(transactions) {
        let buyCount = 0;
        let sellCount = 0;
        let transferCount = 0;
        let otherCount = 0;

        transactions.forEach(tx => {
            switch (tx.transaction_type) {
                case 'buy':
                    buyCount++;
                    break;
                case 'sell':
                    sellCount++;
                    break;
                case 'transfer':
                    transferCount++;
                    break;
                default:
                    otherCount++;
            }
        });

        this.updateElement('buyCount', `📈 ${buyCount}`);
        this.updateElement('sellCount', `📉 ${sellCount}`);
        this.updateElement('transferCount', `🔄 ${transferCount}`);
        this.updateElement('otherCount', `⚡ ${otherCount}`);
    }

    createDistributionChart(distributionData) {
        const ctx = document.getElementById('distributionChart');
        if (!ctx || !distributionData || distributionData.length === 0) return;

        // Détruire le graphique existant
        if (this.distributionChart) {
            this.distributionChart.destroy();
        }

        const labels = distributionData.map(item => item.type);
        const data = distributionData.map(item => item.count);
        const volumes = distributionData.map(item => item.volume);

        this.distributionChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: [
                        '#27ae60',
                        '#e74c3c',
                        '#3498db',
                        '#f39c12',
                        '#9b59b6'
                    ],
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const label = context.label;
                                const count = context.parsed;
                                const volume = volumes[context.dataIndex];
                                return [
                                    `${label}: ${count} transactions`,
                                    `Volume: ${this.formatNumber(volume, 2)} SOL`
                                ];
                            }
                        }
                    }
                }
            }
        });
    }

    copyWalletAddress() {
        const walletAddress = this.currentWallet === 'all' ? 'Tous les wallets' : this.currentWallet;
        
        if (this.currentWallet === 'all') {
            this.showAlert('info', 'Info', 'Impossible de copier "Tous les wallets"');
            return;
        }
        
        if (navigator.clipboard) {
            navigator.clipboard.writeText(walletAddress).then(() => {
                this.showAlert('success', 'Copié !', 'Adresse du wallet copiée dans le presse-papiers');
            }).catch(err => {
                console.error('Erreur lors de la copie:', err);
                this.fallbackCopyTextToClipboard(walletAddress);
            });
        } else {
            this.fallbackCopyTextToClipboard(walletAddress);
        }
    }

    fallbackCopyTextToClipboard(text) {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        
        try {
            const successful = document.execCommand('copy');
            if (successful) {
                this.showAlert('success', 'Copié !', 'Adresse du wallet copiée dans le presse-papiers');
            } else {
                this.showAlert('error', 'Erreur', 'Impossible de copier l\'adresse');
            }
        } catch (err) {
            console.error('Erreur lors de la copie:', err);
            this.showAlert('error', 'Erreur', 'Impossible de copier l\'adresse');
        }
        
        document.body.removeChild(textArea);
    }

    async applyFilters() {
        this.showLoading();
        try {
            await this.loadTransactions();
        } catch (error) {
            console.error('Erreur lors de l\'application des filtres:', error);
        } finally {
            this.hideLoading();
        }
    }

    async refreshData() {
        console.log('🔄 Actualisation des données...');
        try {
            await this.loadDashboardData();
            this.showAlert('success', 'Actualisé', 'Données mises à jour avec succès');
        } catch (error) {
            console.error('Erreur lors de l\'actualisation:', error);
            this.showAlert('error', 'Erreur', 'Impossible d\'actualiser les données');
        }
    }

    startAutoRefresh() {
        setInterval(() => {
            if (this.autoRefreshEnabled && !document.hidden) {
                this.refreshData();
            }
        }, this.refreshInterval);
    }

    showLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.add('show');
        }
    }

    hideLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.remove('show');
        }
    }

    showAlert(type, title, message) {
        const alertContainer = document.getElementById('alertContainer');
        if (!alertContainer) return;

        const alertId = `alert-${Date.now()}`;
        const icons = {
            success: 'fas fa-check-circle',
            error: 'fas fa-exclamation-circle',
            warning: 'fas fa-exclamation-triangle',
            info: 'fas fa-info-circle'
        };

        const alertHTML = `
            <div class="alert ${type}" id="${alertId}">
                <div class="alert-icon">
                    <i class="${icons[type] || icons.info}"></i>
                </div>
                <div class="alert-content">
                    <div class="alert-title">${title}</div>
                    <div class="alert-message">${message}</div>
                </div>
            </div>
        `;

        alertContainer.insertAdjacentHTML('beforeend', alertHTML);

        // Auto-dismiss après 5 secondes
        setTimeout(() => {
            const alert = document.getElementById(alertId);
            if (alert) {
                alert.style.opacity = '0';
                alert.style.transform = 'translateX(-100%)';
                setTimeout(() => {
                    alert.remove();
                }, 300);
            }
        }, 5000);
    }

    updateElement(id, value) {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
        }
    }

    formatNumber(number, decimals = 2) {
        if (typeof number !== 'number') return '0';
        
        return new Intl.NumberFormat('fr-FR', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        }).format(number);
    }

    formatRelativeTime(date) {
        const now = new Date();
        const diffInSeconds = Math.floor((now - date) / 1000);

        if (diffInSeconds < 60) {
            return 'Il y a quelques secondes';
        } else if (diffInSeconds < 3600) {
            const minutes = Math.floor(diffInSeconds / 60);
            return `Il y a ${minutes} minute${minutes > 1 ? 's' : ''}`;
        } else if (diffInSeconds < 86400) {
            const hours = Math.floor(diffInSeconds / 3600);
            return `Il y a ${hours} heure${hours > 1 ? 's' : ''}`;
        } else {
            const days = Math.floor(diffInSeconds / 86400);
            if (days === 1) {
                return 'Hier';
            } else if (days < 7) {
                return `Il y a ${days} jours`;
            } else {
                return date.toLocaleDateString('fr-FR');
            }
        }
    }
}

// Fonctions globales pour l'interface
function copyWalletAddress() {
    if (window.dashboard) {
        window.dashboard.copyWalletAddress();
    }
}

function applyFilters() {
    if (window.dashboard) {
        window.dashboard.applyFilters();
    }
}

function refreshData() {
    if (window.dashboard) {
        window.dashboard.refreshData();
    }
}

function switchWallet(walletAddress) {
    if (window.dashboard) {
        window.dashboard.switchWallet(walletAddress);
    }
}

// Initialisation quand le DOM est prêt
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new SolanaWalletDashboard();
});

// Gestion des erreurs globales
window.addEventListener('error', (event) => {
    console.error('Erreur globale:', event.error);
    if (window.dashboard) {
        window.dashboard.showAlert('error', 'Erreur', 'Une erreur inattendue s\'est produite');
    }
});

// Performance monitoring
if ('performance' in window) {
    window.addEventListener('load', () => {
        setTimeout(() => {
            const perfData = performance.getEntriesByType('navigation')[0];
            const loadTime = perfData.loadEventEnd - perfData.loadEventStart;
            console.log(`⚡ Dashboard multi-wallet chargé en ${loadTime}ms`);
        }, 0);
    });
}