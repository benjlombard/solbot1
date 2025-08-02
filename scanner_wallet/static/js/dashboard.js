class SolanaWalletDashboard {
    constructor() {
        this.walletAddresses = [];
        this.currentWallet = 'all';
        this.apiBaseUrl = '/api';
        this.refreshInterval = 30000; // 30 seconds
        this.autoRefreshEnabled = true;
        this.distributionChart = null;
        this.lastTransactionCount = 0;
        this.alertThreshold = 1; // SOL
        this.tokenCache = new Map();
        this.apiCache = new Map();
        this.tokenSummaryData = [];
        this.tokenSummaryLoaded = false;
        
        this.init();
    }

    async init() {
        console.log('🚀 Initializing Solana Multi-Wallet Dashboard');
        
        this.showLoading();
        
        try {
            await this.loadWallets();
            this.loadFilters();
            await this.loadDashboardData();
            await this.fetchSolPrice();
            setInterval(() => this.fetchSolPrice(), 60000); // Update SOL price every minute
            this.setupEventListeners();
            this.startAutoRefresh();
            
            console.log('✅ Dashboard initialized successfully');
        } catch (error) {
            console.error('❌ Initialization error:', error);
            this.showAlert('error', 'Initialization Error', 'Unable to load dashboard data');
        } finally {
            this.hideLoading();
        }
    }

    async loadWallets() {
        try {
            const response = await this.fetchWithRetry(`${this.apiBaseUrl}/wallets`);
            const data = await response.json();
            this.walletAddresses = data.wallets || [];
        } catch (error) {
            console.error('Error loading wallets:', error);
            this.walletAddresses = ['2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK'];
        }
        this.updateWalletSelector();
        this.updateWalletTabs();
    }

    async loadTokenSummary() {
    const loadingEl = document.getElementById('tokenLoading');
    const emptyEl = document.getElementById('tokenEmpty');
    const tableBody = document.getElementById('tokenSummaryTableBody');
    
    if (loadingEl) loadingEl.style.display = 'block';
    if (emptyEl) emptyEl.style.display = 'none';
    if (tableBody) tableBody.innerHTML = '';

    try {
        const period = document.getElementById('tokenPeriod')?.value || '30';
        const sortBy = document.getElementById('tokenSortBy')?.value || 'total_value';
        const minValue = document.getElementById('tokenMinValue')?.value || '0.1';
        const wallet = this.currentWallet;

        const response = await this.fetchWithRetry(`${this.apiBaseUrl}/token-summary?period=${period}&sort_by=${sortBy}&min_value=${minValue}&wallet=${wallet}`);
        const data = await response.json();

        if (loadingEl) loadingEl.style.display = 'none';

        if (data.error) {
            console.error('Error loading token summary:', data.error);
            if (emptyEl) {
                emptyEl.style.display = 'block';
                emptyEl.innerHTML = `
                    <i class="fas fa-exclamation-triangle" style="font-size: 48px; color: #e74c3c; margin-bottom: 15px;"></i>
                    <p>Error loading token data: ${data.error}</p>
                `;
            }
            return;
        }

        this.tokenSummaryData = data.tokens || [];
        this.updateTokenSummaryStats(data.summary || {});
        this.displayTokenSummaryTable(this.tokenSummaryData);

        if (this.tokenSummaryData.length === 0) {
            if (emptyEl) emptyEl.style.display = 'block';
        } else {
            this.tokenSummaryLoaded = true;
        }

    } catch (error) {
        console.error('Error loading token summary:', error);
        if (loadingEl) loadingEl.style.display = 'none';
        if (emptyEl) {
            emptyEl.style.display = 'block';
            emptyEl.innerHTML = `
                <i class="fas fa-exclamation-triangle" style="font-size: 48px; color: #e74c3c; margin-bottom: 15px;"></i>
                <p>Failed to load token data. Please try again.</p>
            `;
        }
    }
}

    updateTokenSummaryStats(summary) {
        const elements = {
            'totalTokensTracked': summary.total_tokens || 0,
            'profitableTokens': summary.profitable_tokens || 0,
            'lossTokens': summary.loss_tokens || 0,
            'hotTokens': summary.hot_tokens_count || 0
        };

        Object.entries(elements).forEach(([id, value]) => {
            const element = document.getElementById(id);
            if (element) element.textContent = value;
        });
    }

    displayTokenSummaryTable(tokens) {
        const tableBody = document.getElementById('tokenSummaryTableBody');
        if (!tableBody) return;

        if (tokens.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="8" style="text-align: center; padding: 40px; color: #666;">
                        No tokens found with current filters
                    </td>
                </tr>
            `;
            return;
        }

        const rows = tokens.map(token => {
            const stats = token.trading_stats;
            const performance = token.performance;
            const timing = token.timing;
            const metadata = token.metadata;

            // Format numbers
            const formatLargeNumber = (num) => {
                if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
                if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
                return num.toFixed(2);
            };

            const formatSOL = (num) => {
                if (num >= 100) return num.toFixed(1);
                if (num >= 1) return num.toFixed(2);
                return num.toFixed(4);
            };

            // Token badges
            let badges = '';
            if (metadata.is_hot) badges += '<span class="token-badge hot">🔥 HOT</span>';
            if (timing.is_recent_activity) badges += '<span class="token-badge new">NEW</span>';
            if (metadata.position_size === 'large') badges += '<span class="token-badge large-position">LARGE</span>';

            // Position status
            const netPosition = stats.net_position;
            let positionClass = 'neutral';
            let positionPrefix = '';
            if (netPosition > 0) {
                positionClass = 'positive';
                positionPrefix = '+';
            } else if (netPosition < 0) {
                positionClass = 'negative';
                positionPrefix = '';
            }

            // P&L formatting
            const pnlClass = performance.is_profitable ? 'positive' : 'negative';
            const pnlPrefix = performance.estimated_pnl_sol >= 0 ? '+' : '';

            // Last activity
            const lastActivityTime = timing.last_transaction;
            const timeDiff = Math.floor((Date.now() / 1000) - lastActivityTime);
            let activityText = 'Unknown';
            let activityClass = '';
            
            if (timeDiff < 3600) {
                activityText = `${Math.floor(timeDiff / 60)}m ago`;
                activityClass = 'activity-recent';
            } else if (timeDiff < 86400) {
                activityText = `${Math.floor(timeDiff / 3600)}h ago`;
                activityClass = 'activity-recent';
            } else {
                activityText = `${Math.floor(timeDiff / 86400)}d ago`;
            }

            return `
                <tr data-token="${token.token_mint}">
                    <td class="token-col">
                        <div class="token-info">
                            <div class="token-logo">
                                ${this.getTokenLogo(token.symbol, token.token_mint)}
                            </div>
                            <div class="token-details">
                                <div class="token-symbol">${token.symbol}</div>
                                <div class="token-name" title="${token.name}">${token.name}</div>
                                <div class="token-badges">${badges}</div>
                            </div>
                        </div>
                    </td>
                    <td class="buys-col">
                        <div class="trading-stats buys-stats">
                            <span class="stat-primary">${stats.total_buys} buys</span>
                            <span class="stat-secondary">${formatSOL(stats.total_sol_spent)} SOL</span>
                        </div>
                    </td>
                    <td class="sells-col">
                        <div class="trading-stats sells-stats">
                            <span class="stat-primary">${stats.total_sells} sells</span>
                            <span class="stat-secondary">${formatSOL(stats.total_sol_received)} SOL</span>
                        </div>
                    </td>
                    <td class="position-col">
                        <div class="position-value ${positionClass}">
                            ${positionPrefix}${formatLargeNumber(Math.abs(netPosition))}
                        </div>
                        <div class="position-details">
                            ${stats.unique_wallets} wallet${stats.unique_wallets > 1 ? 's' : ''}
                        </div>
                    </td>
                    <td class="price-col">
                        <div class="price-info">
                            ${stats.avg_buy_price > 0 ? `<div class="buy-price">Buy: ${stats.avg_buy_price.toFixed(8)}</div>` : ''}
                            ${stats.avg_sell_price > 0 ? `<div class="sell-price">Sell: ${stats.avg_sell_price.toFixed(8)}</div>` : ''}
                            ${stats.avg_buy_price === 0 && stats.avg_sell_price === 0 ? '<span class="stat-secondary">No price data</span>' : ''}
                        </div>
                    </td>
                    <td class="pnl-col">
                        <div class="pnl-value ${pnlClass}">
                            ${pnlPrefix}${formatSOL(Math.abs(performance.estimated_pnl_sol))} SOL
                            <span class="pnl-percentage">(${pnlPrefix}${Math.abs(performance.pnl_percentage).toFixed(1)}%)</span>
                        </div>
                    </td>
                    <td class="activity-col">
                        <div class="activity-time ${activityClass}">
                            ${activityText}
                        </div>
                        <div class="wallet-count">
                            ${stats.total_transactions} tx
                        </div>
                    </td>
                    <td class="actions-col">
                        <div class="token-actions">
                            <a href="${token.links.dexscreener}" target="_blank" class="token-action-btn btn-charts" title="View charts">
                                📊
                            </a>
                            <a href="${token.links.jupiter}" target="_blank" class="token-action-btn btn-buy" title="Trade on Jupiter">
                                🚀
                            </a>
                            <button class="token-action-btn btn-copy" onclick="copyTokenInfo('${token.token_mint}', '${token.symbol}')" title="Copy token info">
                                📋
                            </button>
                            <button class="token-action-btn btn-details" onclick="showTokenDetails('${token.token_mint}')" title="View details">
                                ℹ️
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

        tableBody.innerHTML = rows;
    }

    copyTokenInfo(tokenMint, symbol) {
        const tokenData = this.tokenSummaryData.find(t => t.token_mint === tokenMint);
        if (!tokenData) return;

        const info = `Token: ${symbol}
        Mint: ${tokenMint}
        Buys: ${tokenData.trading_stats.total_buys}
        Sells: ${tokenData.trading_stats.total_sells}
        Net Position: ${tokenData.trading_stats.net_position.toFixed(2)}
        P&L: ${tokenData.performance.estimated_pnl_sol.toFixed(4)} SOL (${tokenData.performance.pnl_percentage.toFixed(1)}%)

        Links:
        Jupiter: ${tokenData.links.jupiter}
        DexScreener: ${tokenData.links.dexscreener}`;

        if (navigator.clipboard) {
            navigator.clipboard.writeText(info).then(() => {
                this.showAlert('success', 'Copied!', `${symbol} token info copied to clipboard`);
            }).catch(() => {
                this.showAlert('error', 'Error', 'Failed to copy token info');
            });
        } else {
            this.showAlert('info', 'Token Info', info);
        }
    }

    async showTokenDetails(tokenMint) {
        try {
            const response = await this.fetchWithRetry(`${this.apiBaseUrl}/token-details/${tokenMint}`);
            const data = await response.json();
            
            if (data.error) {
                this.showAlert('error', 'Error', 'Failed to load token details');
                return;
            }

            const tokenData = this.tokenSummaryData.find(t => t.token_mint === tokenMint);
            const symbol = tokenData ? tokenData.symbol : 'Token';
            
            console.log(`${symbol} Details:`, data);
            this.showAlert('info', `${symbol} Details`, `Total Transactions: ${data.total_transactions}\nRecent transactions logged to console.`);
            
        } catch (error) {
            console.error('Error loading token details:', error);
            this.showAlert('error', 'Error', 'Failed to load token details');
        }
    }

    updateWalletSelector() {
        const selector = document.getElementById('walletSelect');
        if (!selector) return;

        selector.innerHTML = '<option value="all">All wallets</option>';
        
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

        const allTab = document.createElement('div');
        allTab.className = `wallet-tab ${this.currentWallet === 'all' ? 'active' : ''}`;
        allTab.innerHTML = `
            <i class="fas fa-layer-group"></i>
            <span>All</span>
        `;
        allTab.addEventListener('click', () => this.switchWallet('all'));
        allTab.setAttribute('tabindex', '0');
        allTab.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                this.switchWallet('all');
            }
        });
        tabsContainer.appendChild(allTab);

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
            tab.setAttribute('tabindex', '0');
            tab.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    this.switchWallet(address);
                }
            });
            tabsContainer.appendChild(tab);
        });
    }

    async switchWallet(walletAddress) {
        this.currentWallet = walletAddress;
        this.updateWalletTabs();
        
        const walletAddressElement = document.getElementById('walletAddress');
        if (walletAddressElement) {
            walletAddressElement.textContent = walletAddress === 'all' ? 'All wallets' : walletAddress;
            walletAddressElement.setAttribute('aria-label', `Current wallet: ${walletAddressElement.textContent}`);
        }

        await this.loadDashboardData();
    }

    setupEventListeners() {
        const walletSelector = document.getElementById('walletSelect');
        if (walletSelector) {
            walletSelector.addEventListener('change', (e) => this.switchWallet(e.target.value));
        }

        const copyBtn = document.querySelector('.copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => this.copyWalletAddress());
        }

        const minAmountInput = document.getElementById('minAmount');
        const transactionLimitSelect = document.getElementById('transactionLimit');
        const transactionTypeSelect = document.getElementById('transactionType');
        const alertThresholdInput = document.getElementById('alertThreshold');
        const searchInput = document.getElementById('transactionSearch');
        
        if (minAmountInput) {
            minAmountInput.addEventListener('change', () => this.applyFilters());
        }
        
        if (transactionLimitSelect) {
            transactionLimitSelect.addEventListener('change', () => this.applyFilters());
        }

        if (transactionTypeSelect) {
            transactionTypeSelect.addEventListener('change', () => this.applyFilters());
        }

        if (alertThresholdInput) {
            alertThresholdInput.addEventListener('change', () => {
                this.alertThreshold = parseFloat(alertThresholdInput.value) || 1;
                this.applyFilters();
            });
        }

        if (searchInput) {
            searchInput.addEventListener('input', this.debounce(() => this.searchTransactions(), 300));
        }

        const tokenPeriod = document.getElementById('tokenPeriod');
        const tokenSortBy = document.getElementById('tokenSortBy');
        const tokenMinValue = document.getElementById('tokenMinValue');

        if (tokenPeriod) {
            tokenPeriod.addEventListener('change', () => this.loadTokenSummary());
        }
        if (tokenSortBy) {
            tokenSortBy.addEventListener('change', () => this.loadTokenSummary());
        }
        if (tokenMinValue) {
            tokenMinValue.addEventListener('change', this.debounce(() => this.loadTokenSummary(), 500));
        }

        window.addEventListener('focus', () => {
            if (this.autoRefreshEnabled) {
                this.refreshData();
            }
        });

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
            let statsUrl = `${this.apiBaseUrl}/stats`;
            if (this.currentWallet !== 'all') {
                statsUrl += `/${this.currentWallet}`;
            }

            const statsResponse = await this.fetchWithRetry(statsUrl);
            const statsData = await statsResponse.json();
            
            this.updateStatsDisplay(statsData);
            this.createDistributionChart(statsData.transaction_distribution);
            await this.loadTransactions();
            await this.loadTokenSummary();
            
        } catch (error) {
            console.error('Error loading dashboard data:', error);
            this.showAlert('error', 'Data Error', 'Unable to load dashboard data');
        }
    }

    async fetchSolPrice() {
        try {
            const response = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd,eur');
            if (response.ok) {
                const data = await response.json();
                const usdPrice = data.solana.usd;
                const eurPrice = data.solana.eur;
                this.updateElement('solPrice', `SOL Price: $${this.formatNumber(usdPrice, 2)} / €${this.formatNumber(eurPrice, 2)}`);
            }
        } catch (error) {
            console.error('Error fetching SOL price:', error);
            this.updateElement('solPrice', 'SOL Price: Unavailable');
        }
    }

    async fetchWithRetry(url, retries = 3, delay = 1000) {
        const cacheKey = url;
        if (this.apiCache.has(cacheKey)) {
            const cached = this.apiCache.get(cacheKey);
            if (Date.now() - cached.timestamp < 30000) {
                return new Response(JSON.stringify(cached.data), { status: 200 });
            }
        }

        for (let i = 0; i < retries; i++) {
            try {
                const response = await fetch(url);
                if (response.ok) {
                    const data = await response.clone().json();
                    this.apiCache.set(cacheKey, { data, timestamp: Date.now() });
                    return response;
                }
                throw new Error(`HTTP Error: ${response.status}`);
            } catch (error) {
                if (i === retries - 1) throw error;
                await new Promise(resolve => setTimeout(resolve, delay));
            }
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
        
        const balanceElement = document.getElementById('balance');
        if (balanceElement) {
            balanceElement.innerHTML = `${this.formatNumber(stats.balance_sol, 4)} SOL`;
            balanceElement.setAttribute('aria-label', `Current balance: ${this.formatNumber(stats.balance_sol, 4)} SOL`);
        }
        this.updateElement('balanceUsd', this.formatCurrency(stats.balance_usd, 'USD'));
        this.updateElement('balanceEur', this.formatCurrency(stats.balance_eur, 'EUR'));
        
        this.updateElement('totalTransactions', stats.total_transactions);
        
        this.updateElement('totalVolume', `${this.formatNumber(stats.total_volume, 2)} SOL`);
        this.updateElement('totalVolumeUsd', this.formatCurrency(stats.total_volume_usd, 'USD'));
        this.updateElement('totalVolumeEur', this.formatCurrency(stats.total_volume_eur, 'EUR'));
        
        const pnlElement = document.getElementById('pnl');
        if (pnlElement) {
            pnlElement.innerHTML = `
                ${stats.pnl >= 0 ? '+' : ''}${this.formatNumber(stats.pnl, 4)} SOL<br>
                <small>${this.formatCurrency(stats.pnl_usd, 'USD')} / ${this.formatCurrency(stats.pnl_eur, 'EUR')}</small>
            `;
            pnlElement.className = `stat-value ${stats.pnl >= 0 ? 'positive' : 'negative'}`;
            pnlElement.setAttribute('aria-label', `Net P&L: ${stats.pnl >= 0 ? '+' : ''}${this.formatNumber(stats.pnl, 4)} SOL`);
        }
        
        const largestElement = document.getElementById('largestTransaction');
        if (largestElement) {
            largestElement.innerHTML = `
                ${this.formatNumber(stats.largest_transaction, 4)} SOL<br>
                <small>${this.formatCurrency(stats.largest_transaction_usd, 'USD')}</small>
            `;
            largestElement.setAttribute('aria-label', `Largest transaction: ${this.formatNumber(stats.largest_transaction, 4)} SOL`);
        }
        
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
            
            const response = await this.fetchWithRetry(transactionsUrl);
            const transactions = await response.json();
            this.displayTransactions(transactions);
            this.updateTransactionStats(transactions);
            
        } catch (error) {
            console.error('Error loading transactions:', error);
            this.showAlert('error', 'Error', 'Unable to load transactions');
        }
    }

    displayTransactions(transactions) {
        const transactionsList = document.getElementById('transactionsList');
        if (!transactionsList) return;

        if (transactions.length === 0) {
            transactionsList.innerHTML = `
                <div class="text-center" style="padding: 40px;">
                    <i class="fas fa-search" style="font-size: 48px; color: #ccc; margin-bottom: 15px;"></i>
                    <p style="color: #666;">No transactions found with current filters</p>
                </div>
            `;
            return;
        }

        const transactionsHTML = transactions.map(tx => {
            const date = new Date(tx.block_time * 1000);
            const amount = parseFloat(tx.amount);
            const fee = parseFloat(tx.fee);
            
            const tokenSymbol = tx.token_symbol || 'SOL';
            const tokenName = tx.token_name || 'Solana';
            const tokenAmount = tx.token_amount || Math.abs(amount);
            const transactionType = tx.transaction_type || 'other';
            const pricePerToken = tx.price_per_token || 0;
            const tokenMint = tx.token_mint;
            const isLargeTokenAmount = tx.is_large_token_amount || false;
            
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

            const isLargeTransaction = isLargeTokenAmount || Math.abs(amount) >= this.alertThreshold;

            let estimatedValueUSD = 0;
            if (pricePerToken > 0 && tokenAmount > 0) {
                const solPrice = 100; // Approximate SOL price
                estimatedValueUSD = tokenAmount * pricePerToken * solPrice;
            }

            const links = this.generateImprovedTransactionLinks(tx.signature, tokenMint, tokenSymbol, transactionType);

            return `
                <div class="transaction-item lazy-load ${isLargeTransaction ? 'large-transaction' : ''}" data-signature="${tx.signature}" tabindex="0">
                    <div class="transaction-type ${typeClass}">
                        <i class="${typeIcon}"></i>
                        ${isLargeTransaction ? '<div class="large-indicator">🔥</div>' : ''}
                    </div>
                    <div class="transaction-details">
                        ${tx.is_token_transaction && tokenMint ? `
                            <div class="token-info">
                                <div class="token-logo">
                                    ${this.getTokenLogo(tokenSymbol, tokenMint)}
                                </div>
                                <div class="token-details">
                                    <div class="token-symbol">${tokenSymbol}</div>
                                    <div class="token-name">${tokenName}</div>
                                    ${tokenMint ? `<div class="token-mint">${tokenMint.substring(0, 8)}...${tokenMint.substring(-4)}</div>` : ''}
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
                                ${tx.status === 'success' ? 'Success' : 'Failed'}
                            </div>
                            
                            ${isLargeTransaction ? `
                                <span class="large-transaction-indicator">
                                    ${isLargeTokenAmount ? '🚀 LARGE QUANTITY' : '💰 LARGE TRANSACTION'}
                                </span>
                            ` : ''}

                            ${tx.wallet_address ? `
                                <span class="wallet-indicator">
                                    <i class="fas fa-wallet"></i>
                                    ${tx.wallet_address.substring(0, 6)}...
                                </span>
                            ` : ''}
                        </div>
                        
                        ${links}
                    </div>
                    
                    <div class="transaction-amount">
                        ${tx.is_token_transaction && tokenAmount > 0 ? `
                            <div class="token-amount-display ${isLargeTokenAmount ? 'large-amount' : ''}">
                                <div class="token-amount-value">
                                    ${transactionType === 'sell' ? '-' : '+'}${this.formatNumber(tokenAmount, tokenAmount > 1000000 ? 0 : 2)} ${tokenSymbol}
                                </div>
                                ${pricePerToken > 0 ? `
                                    <div class="price-per-token">
                                        ${this.formatNumber(pricePerToken, 8)} SOL/token
                                    </div>
                                ` : ''}
                                ${estimatedValueUSD > 0.01 ? `
                                    <div class="estimated-value">
                                        ≈ ${this.formatCurrency(estimatedValueUSD, 'USD')}
                                    </div>
                                ` : ''}
                            </div>
                        ` : ''}
                        
                        <div class="amount-value ${amount >= 0 ? 'positive' : amount < 0 ? 'negative' : 'neutral'}">
                            ${amount >= 0 ? '+' : ''}${this.formatNumber(amount, 4)} SOL
                        </div>
                        
                        <div class="fee-value">
                            Fee: ${this.formatNumber(fee, 6)} SOL
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        transactionsList.innerHTML = transactionsHTML;

        this.addTransactionEventListeners();

        const observer = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.remove('lazy-load');
                    observer.unobserve(entry.target);
                }
            });
        }, { rootMargin: '100px' });

        document.querySelectorAll('.lazy-load').forEach(item => observer.observe(item));
    }

    getTransactionTypeLabel(type) {
        const labels = {
            'buy': '📈 BUY',
            'sell': '📉 SELL',
            'transfer': '🔄 TRANSFER',
            'sol_transfer': '⚡ SOL',
            'other': '🔹 OTHER'
        };
        return labels[type] || labels.other;
    }

    generateImprovedTransactionLinks(signature, tokenMint, tokenSymbol, transactionType) {
        let links = `
            <div class="transaction-links">
                <a href="https://solscan.io/tx/${signature}" target="_blank" class="link-solscan">
                    <i class="fas fa-external-link-alt"></i> Solscan
                </a>
        `;

        if (tokenMint && tokenMint !== 'SOL') {
            if (transactionType === 'buy' || transactionType === 'sell') {
                links += `
                    <a href="https://pump.fun/${tokenMint}" target="_blank" class="link-pumpfun">
                        <i class="fas fa-rocket"></i> Pump.fun
                    </a>
                `;
            }

            links += `
                <a href="https://dexscreener.com/solana/${tokenMint}" target="_blank" class="link-dexscreener">
                    <i class="fas fa-chart-line"></i> Price & Charts
                </a>
                <a href="https://solscan.io/token/${tokenMint}" target="_blank" class="link-token">
                    <i class="fas fa-info-circle"></i> Token Info
                </a>
                <a href="https://birdeye.so/token/${tokenMint}?chain=solana" target="_blank" class="link-birdeye">
                    <i class="fas fa-eye"></i> Birdeye
                </a>
            `;

            if (transactionType === 'buy' || transactionType === 'sell') {
                links += `
                    <a href="https://jup.ag/swap/SOL-${tokenMint}" target="_blank" class="link-jupiter">
                        <i class="fas fa-exchange-alt"></i> Swap Jupiter
                    </a>
                `;
            }
        }

        links += '</div>';
        return links;
    }

    getTokenLogo(tokenSymbol, tokenMint) {
        if (tokenMint && this.tokenCache.has(tokenMint)) {
            const cached = this.tokenCache.get(tokenMint);
            if (cached.logo_uri) {
                return `<img src="${cached.logo_uri}" alt="${tokenSymbol}" onerror="this.style.display='none'; this.nextSibling.style.display='block';">
                        <span style="display:none;">${tokenSymbol.substring(0, 3)}</span>`;
            }
        }
        return tokenSymbol.substring(0, 3);
    }

    addTransactionEventListeners() {
        const transactionItems = document.querySelectorAll('.transaction-item');
        transactionItems.forEach(item => {
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.transaction-links a')) {
                    const signature = item.dataset.signature;
                    this.openTransactionDetails(signature);
                }
            });
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    const signature = item.dataset.signature;
                    this.openTransactionDetails(signature);
                }
            });
        });
    }

    openTransactionDetails(signature) {
        window.open(`https://solscan.io/tx/${signature}`, '_blank');
    }

    updateTransactionStats(transactions) {
        let buyCount = 0, sellCount = 0, transferCount = 0, otherCount = 0;

        transactions.forEach(tx => {
            switch (tx.transaction_type) {
                case 'buy': buyCount++; break;
                case 'sell': sellCount++; break;
                case 'transfer': transferCount++; break;
                default: otherCount++;
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
                    backgroundColor: ['#27ae60', '#e74c3c', '#3498db', '#f39c12', '#9b59b6'],
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
                        labels: { padding: 20, usePointStyle: true }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => [
                                `${context.label}: ${context.parsed} transactions`,
                                `Volume: ${this.formatNumber(volumes[context.dataIndex], 2)} SOL`
                            ]
                        }
                    }
                }
            }
        });
    }

    copyWalletAddress() {
        const walletAddress = this.currentWallet === 'all' ? 'All wallets' : this.currentWallet;
        
        if (this.currentWallet === 'all') {
            this.showAlert('info', 'Info', 'Cannot copy "All wallets"');
            return;
        }
        
        if (navigator.clipboard) {
            navigator.clipboard.writeText(walletAddress).then(() => {
                this.showAlert('success', 'Copied!', 'Wallet address copied to clipboard');
            }).catch(err => {
                console.error('Copy error:', err);
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
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        
        try {
            document.execCommand('copy');
            this.showAlert('success', 'Copied!', 'Wallet address copied to clipboard');
        } catch (err) {
            console.error('Fallback copy error:', err);
            this.showAlert('error', 'Error', 'Unable to copy address');
        }
        
        document.body.removeChild(textArea);
    }

    async applyFilters() {
        this.showLoading();
        try {
            await this.loadTransactions();
        } catch (error) {
            console.error('Error applying filters:', error);
            this.showAlert('error', 'Error', 'Unable to apply filters');
        } finally {
            this.hideLoading();
        }
    }

    saveFilters() {
        const filters = {
            minAmount: document.getElementById('minAmount')?.value || 0,
            transactionLimit: document.getElementById('transactionLimit')?.value || 50,
            transactionType: document.getElementById('transactionType')?.value || 'all',
            alertThreshold: document.getElementById('alertThreshold')?.value || 1
        };
        localStorage.setItem('walletFilters', JSON.stringify(filters));
        this.showAlert('success', 'Filters Saved', 'Filter preferences have been saved.');
    }

    loadFilters() {
        const savedFilters = localStorage.getItem('walletFilters');
        if (savedFilters) {
            const filters = JSON.parse(savedFilters);
            document.getElementById('minAmount').value = filters.minAmount;
            document.getElementById('transactionLimit').value = filters.transactionLimit;
            document.getElementById('transactionType').value = filters.transactionType;
            document.getElementById('alertThreshold').value = filters.alertThreshold;
            this.alertThreshold = parseFloat(filters.alertThreshold) || 1;
        }
    }

    searchTransactions() {
        const searchInput = document.getElementById('transactionSearch')?.value.toLowerCase();
        if (!searchInput) {
            this.applyFilters();
            return;
        }

        const transactionItems = document.querySelectorAll('.transaction-item');
        transactionItems.forEach(item => {
            const signature = item.dataset.signature.toLowerCase();
            const tokenSymbol = item.querySelector('.token-symbol')?.textContent.toLowerCase() || '';
            const wallet = item.querySelector('.wallet-indicator')?.textContent.toLowerCase() || '';
            const matches = signature.includes(searchInput) || tokenSymbol.includes(searchInput) || wallet.includes(searchInput);
            item.style.display = matches ? '' : 'none';
        });
    }

    debounce(func, wait) {
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

    async refreshData() {
        console.log('🔄 Refreshing data...');
        try {
            await this.loadDashboardData();
            this.showAlert('success', 'Refreshed', 'Data updated successfully');
        } catch (error) {
            console.error('Refresh error:', error);
            this.showAlert('error', 'Error', 'Unable to refresh data');
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
        if (overlay) overlay.classList.add('show');
    }

    hideLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) overlay.classList.remove('show');
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
            <div class="alert ${type}" id="${alertId}" role="alert">
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

        setTimeout(() => {
            const alert = document.getElementById(alertId);
            if (alert) {
                alert.style.opacity = '0';
                alert.style.transform = 'translateX(-100%)';
                setTimeout(() => alert.remove(), 300);
            }
        }, 5000);
    }

    updateElement(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
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

        if (diffInSeconds < 60) return 'Just now';
        if (diffInSeconds < 3600) {
            const minutes = Math.floor(diffInSeconds / 60);
            return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
        }
        if (diffInSeconds < 86400) {
            const hours = Math.floor(diffInSeconds / 3600);
            return `${hours} hour${hours > 1 ? 's' : ''} ago`;
        }
        const days = Math.floor(diffInSeconds / 86400);
        if (days === 1) return 'Yesterday';
        if (days < 7) return `${days} days ago`;
        return date.toLocaleDateString('fr-FR');
    }
}

function copyWalletAddress() {
    if (window.dashboard) window.dashboard.copyWalletAddress();
}

function applyFilters() {
    if (window.dashboard) window.dashboard.applyFilters();
}

function refreshData() {
    if (window.dashboard) window.dashboard.refreshData();
}

function switchWallet(walletAddress) {
    if (window.dashboard) window.dashboard.switchWallet(walletAddress);
}

function setTransactionType(type) {
    document.getElementById('transactionType').value = type;
    applyFilters();
}

function saveFilters() {
    if (window.dashboard) window.dashboard.saveFilters();
}

function searchTransactions() {
    if (window.dashboard) window.dashboard.searchTransactions();
}

function toggleTheme() {
    const dark = document.body.classList.toggle('dark-mode');
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    document.getElementById('themeToggle').setAttribute('aria-checked', dark);
}

function toggleSection(sectionId) {
    const content = document.getElementById(sectionId);
    const toggleIcon = content.parentElement.querySelector('.toggle-icon');
    if (content.classList.contains('collapsed')) {
        content.classList.remove('collapsed');
        content.style.maxHeight = content.scrollHeight + 'px';
        toggleIcon.classList.remove('collapsed');
        content.setAttribute('aria-expanded', 'true');
    } else {
        content.classList.add('collapsed');
        content.style.maxHeight = '0';
        toggleIcon.classList.add('collapsed');
        content.setAttribute('aria-expanded', 'false');
    }
}

function exportCSV() {
    const transactions = document.querySelectorAll('.transaction-item');
    let csvContent = 'data:text/csv;charset=utf-8,';
    csvContent += 'Signature,Type,Amount SOL,Token Amount,Token Symbol,Fee,Wallet,Date,Status\n';

    transactions.forEach(tx => {
        const sig = tx.getAttribute('data-signature');
        const type = tx.querySelector('.transaction-type-badge')?.textContent.trim() || '';
        const amount = tx.querySelector('.amount-value')?.textContent.trim().replace(' SOL', '') || '';
        const tokenAmount = tx.querySelector('.token-amount-value')?.textContent.trim().split(' ')[0] || '';
        const tokenSymbol = tx.querySelector('.token-symbol')?.textContent.trim() || 'SOL';
        const fee = tx.querySelector('.fee-value')?.textContent.trim().replace('Fee: ', '').replace(' SOL', '') || '';
        const wallet = tx.querySelector('.wallet-indicator')?.textContent.trim() || '';
        const date = tx.querySelector('.transaction-time')?.textContent.trim().replace(' ago', '') || '';
        const status = tx.querySelector('.transaction-status')?.textContent.trim() || '';
        csvContent += `"${sig}","${type}","${amount}","${tokenAmount}","${tokenSymbol}","${fee}","${wallet}","${date}","${status}"\n`;
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `transactions_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function loadTokenSummary() {
    if (window.dashboard) window.dashboard.loadTokenSummary();
}

function copyTokenInfo(tokenMint, symbol) {
    if (window.dashboard) window.dashboard.copyTokenInfo(tokenMint, symbol);
}

function showTokenDetails(tokenMint) {
    if (window.dashboard) window.dashboard.showTokenDetails(tokenMint);
}

function formatTransaction(tx) {
    const date = new Date(tx.block_time * 1000).toLocaleString();
    const isTokenTx = tx.is_token_transaction;
    const isBalanceChange = tx.token_symbol && tx.token_symbol.startsWith('TOKEN_');
    
    let typeClass = 'neutral';
    let typeIcon = '⚡';
    let typeLabel = tx.transaction_type;
    
    if (tx.transaction_type === 'buy') {
        typeClass = 'buy';
        typeIcon = '📈';
        typeLabel = 'Buy';
    } else if (tx.transaction_type === 'sell') {
        typeClass = 'sell';
        typeIcon = '📉';
        typeLabel = 'Sell';
    } else if (tx.transaction_type === 'transfer') {
        typeClass = 'transfer';
        typeIcon = '🔄';
        typeLabel = 'Transfer';
    }
    
    // Badge spécial pour balance changes
    const balanceChangeBadge = isBalanceChange ? 
        '<span class="badge balance-change" title="Détecté via Balance Change">BC</span>' : '';
    
    // Affichage du montant principal
    let amountDisplay = '';
    if (isTokenTx && tx.token_amount > 0) {
        const tokenSymbol = tx.token_symbol || 'UNKNOWN';
        amountDisplay = `
            <div class="token-amount">${formatNumber(tx.token_amount)} ${tokenSymbol}</div>
            ${tx.amount !== 0 ? `<div class="sol-amount">${formatSOL(tx.amount)} SOL</div>` : ''}
        `;
    } else {
        amountDisplay = `<div class="sol-amount">${formatSOL(tx.amount)} SOL</div>`;
    }
    
    return `
        <div class="transaction-item ${typeClass}" data-signature="${tx.signature}">
            <div class="transaction-icon">
                ${typeIcon}
            </div>
            <div class="transaction-content">
                <div class="transaction-header">
                    <span class="transaction-type">${typeLabel}</span>
                    ${balanceChangeBadge}
                    <span class="transaction-date">${date}</span>
                </div>
                <div class="transaction-details">
                    <div class="transaction-amounts">
                        ${amountDisplay}
                    </div>
                    <div class="transaction-meta">
                        <span class="signature" title="${tx.signature}">
                            ${tx.signature.substring(0, 8)}...
                        </span>
                        <span class="fee">Fee: ${formatSOL(tx.fee)}</span>
                        <span class="status ${tx.status}">${tx.status}</span>
                        ${tx.wallet_address ? `<span class="wallet" title="${tx.wallet_address}">
                            ${tx.wallet_address.substring(0, 6)}...
                        </span>` : ''}
                    </div>
                </div>
            </div>
            <div class="transaction-actions">
                <button onclick="copyToClipboard('${tx.signature}')" title="Copy signature">
                    <i class="fas fa-copy"></i>
                </button>
                <a href="https://solscan.io/tx/${tx.signature}" target="_blank" title="View on Solscan">
                    <i class="fas fa-external-link-alt"></i>
                </a>
            </div>
        </div>
    `;
}

// CSS pour le badge balance change
const balanceChangeCSS = `
.badge.balance-change {
    background: linear-gradient(45deg, #4ade80, #22c55e);
    color: white;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 10px;
    font-weight: bold;
    margin-left: 8px;
}

.token-amount {
    font-weight: bold;
    color: var(--primary-color);
}

.sol-amount {
    font-size: 0.9em;
    color: var(--text-secondary);
}
`;

if (!document.querySelector('#balance-change-styles')) {
    const style = document.createElement('style');
    style.id = 'balance-change-styles';
    style.textContent = balanceChangeCSS;
    document.head.appendChild(style);
}

// Initialize the dashboard
window.dashboard = new SolanaWalletDashboard();