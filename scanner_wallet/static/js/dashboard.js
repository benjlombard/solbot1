// script.js

class SolanaWalletDashboard {
    constructor() {
        this.walletAddress = '2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK';
        this.apiBaseUrl = '/api';
        this.refreshInterval = 30000; // 30 secondes
        this.autoRefreshEnabled = true;
        this.distributionChart = null;
        this.lastTransactionCount = 0;
        this.alertThreshold = 1; // SOL
        
        this.init();
    }

    async init() {
        console.log('🚀 Initialisation du dashboard Solana Wallet Monitor');
        
        // Afficher l'overlay de chargement
        this.showLoading();
        
        try {
            // Charger les données initiales
            await this.loadDashboardData();
            
            // Initialiser les event listeners
            this.setupEventListeners();
            
            // Démarrer l'auto-refresh
            this.startAutoRefresh();
            
            // Masquer l'overlay de chargement
            this.hideLoading();
            
            console.log('✅ Dashboard initialisé avec succès');
        } catch (error) {
            console.error('❌ Erreur lors de l\'initialisation:', error);
            this.showAlert('error', 'Erreur d\'initialisation', 'Impossible de charger les données du dashboard');
            this.hideLoading();
        }
    }

    setupEventListeners() {
        // Bouton de copie de l'adresse
        const copyBtn = document.querySelector('.copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => this.copyWalletAddress());
        }

        // Filtres
        const minAmountInput = document.getElementById('minAmount');
        const transactionLimitSelect = document.getElementById('transactionLimit');
        
        if (minAmountInput) {
            minAmountInput.addEventListener('change', () => this.applyFilters());
        }
        
        if (transactionLimitSelect) {
            transactionLimitSelect.addEventListener('change', () => this.applyFilters());
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
            // Charger les statistiques principales
            const statsResponse = await fetch(`${this.apiBaseUrl}/stats`);
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
            
            const response = await fetch(`${this.apiBaseUrl}/transactions?min_amount=${minAmount}&limit=${limit}`);
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
            
            // Déterminer le type de transaction
            let transactionType = 'neutral';
            let typeIcon = 'fas fa-exchange-alt';
            
            if (amount > 0) {
                transactionType = 'incoming';
                typeIcon = 'fas fa-arrow-down';
            } else if (amount < 0) {
                transactionType = 'outgoing';
                typeIcon = 'fas fa-arrow-up';
            }

            // Vérifier si c'est une grosse transaction
            const isLargeTransaction = Math.abs(amount) >= this.alertThreshold;
            const largeTransactionClass = isLargeTransaction ? 'large-transaction' : '';

            return `
                <div class="transaction-item ${largeTransactionClass}" data-signature="${tx.signature}">
                    <div class="transaction-type ${transactionType}">
                        <i class="${typeIcon}"></i>
                    </div>
                    <div class="transaction-details">
                        <div class="transaction-signature">
                            ${tx.signature}
                        </div>
                        <div class="transaction-meta">
                            <div class="transaction-time">
                                <i class="fas fa-clock"></i>
                                ${this.formatRelativeTime(date)}
                            </div>
                            <div class="transaction-status ${tx.status}">
                                ${tx.status === 'success' ? 'Succès' : 'Échec'}
                            </div>
                            ${isLargeTransaction ? '<span class="stat-pill warning">💰 Grosse transaction</span>' : ''}
                        </div>
                    </div>
                    <div class="transaction-amount">
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

    addTransactionEventListeners() {
        const transactionItems = document.querySelectorAll('.transaction-item');
        transactionItems.forEach(item => {
            item.addEventListener('click', () => {
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
        let positiveCount = 0;
        let negativeCount = 0;
        let neutralCount = 0;

        transactions.forEach(tx => {
            const amount = parseFloat(tx.amount);
            if (amount > 0) positiveCount++;
            else if (amount < 0) negativeCount++;
            else neutralCount++;
        });

        this.updateElement('positiveCount', `+${positiveCount}`);
        this.updateElement('negativeCount', `-${negativeCount}`);
        this.updateElement('neutralCount', `≈${neutralCount}`);
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
                        '#f39c12'
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
        const walletAddress = this.walletAddress;
        
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
            console.log(`⚡ Dashboard chargé en ${loadTime}ms`);
        }, 0);
    });
}




