function loadActivityData() {
    const activityList = document.getElementById('activity-list');
    const loading = document.getElementById('activity-list-loading');
    const template = document.getElementById('activity-item-template');
    
    if (!activityList || !template) return;
    
    // Cacher le loading
    if (loading) loading.style.display = 'none';
    
    // Générer des données d'exemple
    const sampleData = generateSampleActivityData();
    
    // Vider la liste actuelle
    activityList.innerHTML = '';
    
    // Ajouter chaque élément d'activité
    sampleData.forEach((activity, index) => {
        const clone = template.content.cloneNode(true);
        const item = clone.querySelector('.modern-activity-item');
        
        // Configurer l'icône et le badge
        const icon = item.querySelector('.activity-icon');
        const badge = item.querySelector('.activity-type-badge');
        icon.classList.add(activity.type);
        badge.classList.add(activity.type);
        badge.textContent = activity.type.toUpperCase();
        
        // Remplir les données avec adresses complètes pour les fonctions
        item.querySelector('.activity-title').textContent = activity.title;
        item.querySelector('.activity-time').textContent = activity.time;
        item.querySelector('.wallet-address').textContent = activity.walletShort;
        item.querySelector('.token-symbol').textContent = activity.tokenSymbol;
        item.querySelector('.token-address').textContent = activity.tokenShort;
        item.querySelector('.activity-amount').textContent = activity.amount;
        
        // Stocker les adresses complètes comme attributs data pour les fonctions
        item.querySelector('.wallet-address').setAttribute('data-full-address', activity.wallet);
        item.querySelector('.token-address').setAttribute('data-full-address', activity.tokenAddress);
        
        // Ajouter classe pour montant négatif
        const amountElement = item.querySelector('.activity-amount');
        if (activity.amount.startsWith('-')) {
            amountElement.classList.add('negative');
        }
        
        // Ajouter avec animation retardée
        setTimeout(() => {
            activityList.appendChild(item);
        }, index * 100);
    });
}

function loadWalletsData() {
    const walletsTableBody = document.getElementById('wallets-table-body');
    const loading = document.getElementById('wallets-loading');
    const template = document.getElementById('wallet-row-template');
    
    console.log('=== CHARGEMENT WALLETS ===');
    console.log('Elements trouvés:', { 
        walletsTableBody: !!walletsTableBody, 
        loading: !!loading, 
        template: !!template 
    });
    
    if (!walletsTableBody || !template) {
        console.error('Éléments manquants pour les wallets!');
        return;
    }
    
    // Cacher le loading
    if (loading) {
        loading.style.display = 'none';
        console.log('Loading caché');
    }
    
    // Générer des données d'exemple
    const walletsData = generateSampleWalletsData();
    console.log('Données wallets générées:', walletsData.length, 'wallets');
    
    // Vider le tableau actuel
    walletsTableBody.innerHTML = '';
    console.log('Tableau vidé');
    
    // Ajouter chaque wallet
    walletsData.forEach((wallet, index) => {
        console.log(`Processing wallet ${index + 1}:`, wallet.addressShort);
        
        const clone = template.content.cloneNode(true);
        const row = clone.querySelector('.wallet-row');
        
        if (!row) {
            console.error('Template wallet-row non trouvé!');
            return;
        }
        
        // Colonne 1: Wallet (Avatar + Adresse + Statut)
        const avatar = row.querySelector('.wallet-avatar-small');
        const addressElement = row.querySelector('.wallet-address-small');
        const statusText = row.querySelector('.status-text');
        const statusDot = row.querySelector('.status-dot-tiny');
        
        if (avatar) avatar.textContent = wallet.addressShort.slice(0, 2).toUpperCase();
        if (addressElement) addressElement.textContent = wallet.addressShort;
        if (statusText) statusText.textContent = wallet.status === 'active' ? 'Actif' : 'Attention';
        if (statusDot && wallet.status === 'warning') {
            statusDot.style.background = '#f59e0b';
        }
        
        // Colonne 2: Priorité
        const priorityBadge = row.querySelector('.priority-badge-small');
        if (priorityBadge) {
            priorityBadge.textContent = wallet.priorityText;
            priorityBadge.classList.add(`priority-${wallet.priority}-small`);
        }
        
        // Colonne 3: Tokens
        const tokensElement = row.querySelector('.tokens-count');
        if (tokensElement) tokensElement.textContent = wallet.tokens;
        
        // Colonne 4: TX 24h
        const txElement = row.querySelector('.tx-count');
        if (txElement) txElement.textContent = wallet.transactions24h;
        
        // Colonne 5: Balance SOL
        const balanceElement = row.querySelector('.balance-amount');
        if (balanceElement) balanceElement.textContent = `${wallet.balanceSOL} SOL`;
        
        // Colonne 6: Dernier Scan
        const scanElement = row.querySelector('.scan-time');
        if (scanElement) scanElement.textContent = wallet.lastScan;
        
        // Stocker l'adresse complète pour les actions
        row.setAttribute('data-wallet-address', wallet.address);
        
        // Ajouter au tableau
        walletsTableBody.appendChild(row);
        console.log(`Wallet ${index + 1} ajouté avec succès`);
    });
    
    console.log('=== WALLETS CHARGÉS ===');
    console.log('Nombre de lignes dans le tableau:', walletsTableBody.children.length);
    console.log('Contenu du tableau:', walletsTableBody.innerHTML.length > 0 ? 'Présent' : 'Vide');
}

// Fonctions pour les actions des wallets
function viewWalletDetails(button) {
    const row = button.closest('.wallet-row');
    const walletAddress = row.getAttribute('data-wallet-address');
    
    if (walletAddress) {
        const solscanUrl = `https://solscan.io/account/${walletAddress}`;
        window.open(solscanUrl, '_blank');
    }
}

function copyWalletAddress(button) {
    const row = button.closest('.wallet-row');
    const walletAddress = row.getAttribute('data-wallet-address');
    
    if (walletAddress) {
        navigator.clipboard.writeText(walletAddress).then(() => {
            // Animation de succès
            const originalIcon = button.innerHTML;
            button.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            `;
            button.style.color = 'var(--solana-green)';
            
            showNotification('Adresse wallet copiée !', 'success');
            
            setTimeout(() => {
                button.innerHTML = originalIcon;
                button.style.color = '';
            }, 1500);
        }).catch(err => {
            console.error('Erreur copie:', err);
            showNotification('Erreur lors de la copie', 'error');
        });
    }
}// phantom-integration.js
// Intégration complète avec Phantom Wallet et gestion du dashboard

// Theme Toggle - NOUVELLE FONCTIONNALITÉ
function toggleTheme() {
    const body = document.body;
    const themeIcon = document.getElementById('theme-icon');
    
    if (body.dataset.theme === 'dark') {
        body.dataset.theme = 'light';
        themeIcon.textContent = '☀️';
        localStorage.setItem('theme', 'light');
    } else {
        body.dataset.theme = 'dark';
        themeIcon.textContent = '🌙';
        localStorage.setItem('theme', 'dark');
    }
}

// Restore theme au chargement
function restoreTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    const body = document.body;
    const themeIcon = document.getElementById('theme-icon');
    
    body.dataset.theme = savedTheme;
    themeIcon.textContent = savedTheme === 'dark' ? '🌙' : '☀️';
}

// Phantom Wallet Integration
let phantomWallet = null;

async function connectPhantomWallet() {
    const walletStatus = document.getElementById('wallet-status');
    const connectBtn = document.querySelector('.wallet-connect-btn');
    
    try {
        // Vérifier si Phantom est installé
        if (!window.phantom || !window.phantom.solana) {
            // Ouvrir la page d'installation de Phantom
            window.open('https://phantom.app/', '_blank');
            walletStatus.textContent = 'Installer Phantom';
            return;
        }
        
        // Se connecter à Phantom
        const response = await window.phantom.solana.connect();
        phantomWallet = response.publicKey.toString();
        
        // Mettre à jour l'interface
        walletStatus.textContent = `${phantomWallet.slice(0, 4)}...${phantomWallet.slice(-4)}`;
        connectBtn.classList.add('connected');
        
        console.log('Phantom Wallet connecté:', phantomWallet);
        
        // Sauvegarder la connexion
        localStorage.setItem('phantomConnected', 'true');
        localStorage.setItem('phantomAddress', phantomWallet);
        
    } catch (error) {
        console.error('Erreur de connexion Phantom:', error);
        walletStatus.textContent = 'Erreur connexion';
        
        // Réessayer après 2 secondes
        setTimeout(() => {
            walletStatus.textContent = 'Connecter';
        }, 2000);
    }
}

async function checkPhantomConnection() {
    const walletStatus = document.getElementById('wallet-status');
    const connectBtn = document.querySelector('.wallet-connect-btn');
    
    // Vérifier si Phantom était déjà connecté
    const wasConnected = localStorage.getItem('phantomConnected');
    const savedAddress = localStorage.getItem('phantomAddress');
    
    if (wasConnected && savedAddress && window.phantom && window.phantom.solana) {
        try {
            // Vérifier si toujours connecté
            if (window.phantom.solana.isConnected) {
                phantomWallet = savedAddress;
                walletStatus.textContent = `${phantomWallet.slice(0, 4)}...${phantomWallet.slice(-4)}`;
                connectBtn.classList.add('connected');
            }
        } catch (error) {
            console.log('Phantom non connecté');
        }
    }
}

function openPhantomBuy(button) {
    if (!phantomWallet) {
        connectPhantomWallet();
        return;
    }
    
    // Récupérer les informations du token depuis l'élément parent
    const activityItem = button.closest('.modern-activity-item');
    const tokenAddressElement = activityItem.querySelector('.token-address');
    const tokenAddress = tokenAddressElement.getAttribute('data-full-address');
    
    if (tokenAddress) {
        // Construire l'URL pour acheter le token sur des DEX populaires
        const jupiterUrl = `https://jup.ag/swap/SOL-${tokenAddress}`;
        const raydiumUrl = `https://raydium.io/swap/?inputCurrency=sol&outputCurrency=${tokenAddress}`;
        
        // Créer un modal de choix élégant
        showDexChoiceModal('buy', tokenAddress, jupiterUrl, raydiumUrl);
    } else {
        showNotification('Adresse du token non disponible', 'error');
    }
}

function openPhantomSell(button) {
    if (!phantomWallet) {
        connectPhantomWallet();
        return;
    }
    
    // Récupérer les informations du token depuis l'élément parent
    const activityItem = button.closest('.modern-activity-item');
    const tokenAddressElement = activityItem.querySelector('.token-address');
    const tokenAddress = tokenAddressElement.getAttribute('data-full-address');
    
    if (tokenAddress) {
        // Construire l'URL pour vendre le token (swap vers SOL)
        const jupiterUrl = `https://jup.ag/swap/${tokenAddress}-SOL`;
        const raydiumUrl = `https://raydium.io/swap/?inputCurrency=${tokenAddress}&outputCurrency=sol`;
        
        // Créer un modal de choix élégant
        showDexChoiceModal('sell', tokenAddress, jupiterUrl, raydiumUrl);
    } else {
        showNotification('Adresse du token non disponible', 'error');
    }
}

function showDexChoiceModal(action, tokenAddress, jupiterUrl, raydiumUrl) {
    // Créer un modal moderne pour choisir le DEX
    const modal = document.createElement('div');
    modal.className = 'dex-choice-modal';
    modal.innerHTML = `
        <div class="dex-choice-content">
            <h3>Choisir un DEX pour ${action === 'buy' ? 'acheter' : 'vendre'}</h3>
            <p>Token: ${tokenAddress}</p>
            <div class="dex-buttons">
                <button class="dex-btn jupiter-btn" onclick="window.open('${jupiterUrl}', '_blank'); closeDexModal()">
                    <div class="dex-logo">🪐</div>
                    <div class="dex-info">
                        <h4>Jupiter</h4>
                        <p>Meilleur prix garanti</p>
                    </div>
                </button>
                <button class="dex-btn raydium-btn" onclick="window.open('${raydiumUrl}', '_blank'); closeDexModal()">
                    <div class="dex-logo">💫</div>
                    <div class="dex-info">
                        <h4>Raydium</h4>
                        <p>AMM populaire</p>
                    </div>
                </button>
            </div>
            <button class="close-modal-btn" onclick="closeDexModal()">Annuler</button>
        </div>
    `;
    
    // Ajouter les styles CSS inline
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.8);
        backdrop-filter: blur(8px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        animation: fadeIn 0.3s ease;
    `;
    
    document.body.appendChild(modal);
}

function closeDexModal() {
    const modal = document.querySelector('.dex-choice-modal');
    if (modal) {
        modal.remove();
    }
}

function copyToClipboard(button) {
    const addressElement = button.parentElement.querySelector('.wallet-address, .token-address');
    const address = addressElement.getAttribute('data-full-address') || addressElement.textContent;
    
    navigator.clipboard.writeText(address).then(() => {
        // Animation de succès
        const originalIcon = button.innerHTML;
        button.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
        `;
        button.style.color = 'var(--solana-green)';
        
        showNotification('Adresse copiée !', 'success');
        
        setTimeout(() => {
            button.innerHTML = originalIcon;
            button.style.color = '';
        }, 1500);
    }).catch(err => {
        console.error('Erreur copie:', err);
        showNotification('Erreur lors de la copie', 'error');
    });
}

function showActivityDetails(button) {
    const activityItem = button.closest('.modern-activity-item');
    const walletAddressElement = activityItem.querySelector('.wallet-address');
    const walletAddress = walletAddressElement.getAttribute('data-full-address');
    
    // Ouvrir Solscan pour plus de détails
    if (walletAddress) {
        const solscanUrl = `https://solscan.io/account/${walletAddress}`;
        window.open(solscanUrl, '_blank');
    }
}

function showNotification(message, type = 'info') {
    // Créer une notification moderne
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    notification.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        padding: 12px 20px;
        background: var(--glass-bg);
        backdrop-filter: var(--blur-md);
        border: 1px solid var(--glass-border);
        border-radius: 12px;
        color: var(--text-primary);
        font-weight: 600;
        z-index: 10001;
        animation: slideIn 0.3s ease;
        box-shadow: var(--shadow-lg);
    `;
    
    if (type === 'success') {
        notification.style.borderColor = 'var(--solana-green)';
        notification.style.color = 'var(--solana-green)';
    } else if (type === 'error') {
        notification.style.borderColor = '#ef4444';
        notification.style.color = '#ef4444';
    }
    
    document.body.appendChild(notification);
    
    // Supprimer après 3 secondes
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Fonction pour générer des données d'exemple avec adresses complètes
function generateSampleActivityData() {
    const sampleData = [
        {
            type: 'buy',
            title: 'Achat de Token',
            wallet: '7xKHB9k3L2nR8vF4mP9qW6tE5sA1bC3dH8jK9mL2nR8v',
            walletShort: '7xKHB...9k3L',
            tokenSymbol: 'BONK',
            tokenAddress: 'DezXAZ2ko7xsNqdu8g6AFSCp22yz1tv18P18XjJL2PLz',
            tokenShort: 'DezXA...z8wQ',
            amount: '+1,250,000 BONK',
            time: 'Il y a 5 min'
        },
        {
            type: 'sell',
            title: 'Vente de Token',
            wallet: 'C7r9M2nR8vF4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP',
            walletShort: 'C7r9M...2nR8',
            tokenSymbol: 'RAY',
            tokenAddress: '4k3Dosi7DgdoQNxiJLLXhTGaY3dMoixw4gf4WQGHpump',
            tokenShort: '4k3Dz...Vb2M',
            amount: '-150.5 RAY',
            time: 'Il y a 12 min'
        },
        {
            type: 'discovery',
            title: 'Nouveau Token Découvert',
            wallet: 'A4nZx8k7PvF4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP',
            walletShort: 'A4nZx...8k7P',
            tokenSymbol: 'COPE',
            tokenAddress: '8HGyAAB1yoM1ttS7pXjHMa3dukTFGQggnFFH3hJZgzQh',
            tokenShort: '8HGy...3kL9',
            amount: '+50,000 COPE',
            time: 'Il y a 18 min'
        },
        {
            type: 'transfer',
            title: 'Transfert de Token',
            wallet: 'B8mK25vX9F4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP9',
            walletShort: 'B8mK2...5vX9',
            tokenSymbol: 'ORCA',
            tokenAddress: 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',
            tokenShort: 'orcaE...tZE',
            amount: '+75.25 ORCA',
            time: 'Il y a 25 min'
        },
        {
            type: 'buy',
            title: 'Achat Important',
            wallet: 'D9wF37mH2F4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP9',
            walletShort: 'D9wF3...7mH2',
            tokenSymbol: 'JUP',
            tokenAddress: 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
            tokenShort: 'JUPyi...vCN',
            amount: '+2,500 JUP',
            time: 'Il y a 32 min'
        }
    ];
    
    return sampleData;
}

// Fonction pour générer des données d'exemple pour les wallets
function generateSampleWalletsData() {
    const walletsData = [
        {
            address: '7xKHB9k3L2nR8vF4mP9qW6tE5sA1bC3dH8jK9mL2nR8v',
            addressShort: '7xKHB...9k3L',
            priority: 'high',
            priorityText: 'HAUTE',
            tokens: 23,
            transactions24h: 45,
            balanceSOL: 12.84,
            lastScan: 'Il y a 2 min',
            status: 'active'
        },
        {
            address: 'C7r9M2nR8vF4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP',
            addressShort: 'C7r9M...2nR8',
            priority: 'medium',
            priorityText: 'MOYENNE',
            tokens: 18,
            transactions24h: 12,
            balanceSOL: 8.92,
            lastScan: 'Il y a 5 min',
            status: 'active'
        },
        {
            address: 'A4nZx8k7PvF4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP',
            addressShort: 'A4nZx...8k7P',
            priority: 'high',
            priorityText: 'HAUTE',
            tokens: 31,
            transactions24h: 67,
            balanceSOL: 25.47,
            lastScan: 'Il y a 1 min',
            status: 'active'
        },
        {
            address: 'B8mK25vX9F4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP9',
            addressShort: 'B8mK2...5vX9',
            priority: 'low',
            priorityText: 'BASSE',
            tokens: 7,
            transactions24h: 3,
            balanceSOL: 2.15,
            lastScan: 'Il y a 8 min',
            status: 'warning'
        },
        {
            address: 'D9wF37mH2F4mP9qW6tE5sA1bC3dH8jK9mL2nR8vF4mP9',
            addressShort: 'D9wF3...7mH2',
            priority: 'medium',
            priorityText: 'MOYENNE',
            tokens: 15,
            transactions24h: 28,
            balanceSOL: 6.73,
            lastScan: 'Il y a 3 min',
            status: 'active'
        }
    ];
    
    return walletsData;
}

function loadActivityData() {
    const activityList = document.getElementById('activity-list');
    const loading = document.getElementById('activity-list-loading');
    const template = document.getElementById('activity-item-template');
    
    if (!activityList || !template) return;
    
    // Cacher le loading
    if (loading) loading.style.display = 'none';
    
    // Générer des données d'exemple
    const sampleData = generateSampleActivityData();
    
    // Vider la liste actuelle
    activityList.innerHTML = '';
    
    // Ajouter chaque élément d'activité
    sampleData.forEach((activity, index) => {
        const clone = template.content.cloneNode(true);
        const item = clone.querySelector('.modern-activity-item');
        
        // Configurer l'icône et le badge
        const icon = item.querySelector('.activity-icon');
        const badge = item.querySelector('.activity-type-badge');
        icon.classList.add(activity.type);
        badge.classList.add(activity.type);
        badge.textContent = activity.type.toUpperCase();
        
        // Remplir les données avec adresses courtes pour l'affichage
        item.querySelector('.activity-title').textContent = activity.title;
        item.querySelector('.activity-time').textContent = activity.time;
        item.querySelector('.wallet-address').textContent = activity.walletShort;
        item.querySelector('.token-symbol').textContent = activity.tokenSymbol;
        item.querySelector('.token-address').textContent = activity.tokenShort;
        item.querySelector('.activity-amount').textContent = activity.amount;
        
        // Stocker les adresses complètes comme attributs data pour les fonctions
        item.querySelector('.wallet-address').setAttribute('data-full-address', activity.wallet);
        item.querySelector('.token-address').setAttribute('data-full-address', activity.tokenAddress);
        
        // Ajouter classe pour montant négatif
        const amountElement = item.querySelector('.activity-amount');
        if (activity.amount.startsWith('-')) {
            amountElement.classList.add('negative');
        }
        
        // Ajouter avec animation retardée
        setTimeout(() => {
            activityList.appendChild(item);
        }, index * 100);
    });
}

// Fonctions utilitaires pour l'interface
function refreshActivity() {
    const loading = document.getElementById('activity-list-loading');
    const activityList = document.getElementById('activity-list');
    
    if (loading) loading.style.display = 'flex';
    if (activityList) activityList.innerHTML = '';
    
    showNotification('Actualisation de l\'activité...', 'info');
    
    // Simuler un délai de chargement
    setTimeout(() => {
        loadActivityData();
        showNotification('Activité mise à jour !', 'success');
    }, 1000);
}

function refreshWallets() {
    const loading = document.getElementById('wallets-loading');
    const walletsTableBody = document.getElementById('wallets-table-body');
    
    if (loading) loading.style.display = 'flex';
    if (walletsTableBody) walletsTableBody.innerHTML = '';
    
    showNotification('Actualisation des wallets...', 'info');
    
    // Simuler un délai de chargement
    setTimeout(() => {
        loadWalletsData();
        showNotification('Wallets mis à jour !', 'success');
    }, 1000);
}

function refreshTokens() {
    showNotification('Actualisation des tokens...', 'info');
    console.log('Actualisation des tokens...');
    // Cette fonction sera implémentée selon votre logique backend
}

function showWalletModal() {
    console.log('Ouverture du modal wallet...');
    // Cette fonction sera implémentée selon votre logique de modal
}

function navigateTo(path) {
    console.log('Navigation vers:', path);
    // Cette fonction sera implémentée selon votre système de navigation
}

function closeModal() {
    const modal = document.getElementById('details-modal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('show');
    }
}

// Ajouter les styles CSS pour les modals et notifications
function addCustomStyles() {
    const style = document.createElement('style');
    style.textContent = `
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        @keyframes slideIn {
            from { 
                opacity: 0;
                transform: translateX(100%);
            }
            to { 
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        .dex-choice-content {
            background: var(--glass-bg);
            backdrop-filter: var(--blur-md);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 32px;
            max-width: 500px;
            width: 90%;
            color: var(--text-primary);
            text-align: center;
        }
        
        .dex-choice-content h3 {
            margin: 0 0 16px 0;
            font-size: 24px;
            font-weight: 700;
            color: var(--text-primary);
        }
        
        .dex-choice-content p {
            margin: 0 0 32px 0;
            color: var(--text-secondary);
            font-family: 'Monaco', 'Courier New', monospace;
            background: var(--glass-bg);
            padding: 8px 16px;
            border-radius: 8px;
            border: 1px solid var(--glass-border);
        }
        
        .dex-buttons {
            display: flex;
            gap: 20px;
            margin-bottom: 24px;
        }
        
        .dex-btn {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 20px;
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            cursor: pointer;
            transition: var(--transition-fast);
            text-align: left;
        }
        
        .dex-btn:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-lg);
            border-color: var(--solana-green);
        }
        
        .dex-logo {
            font-size: 32px;
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, var(--solana-green), var(--solana-purple));
            border-radius: 12px;
            flex-shrink: 0;
        }
        
        .dex-info h4 {
            margin: 0 0 4px 0;
            font-size: 18px;
            font-weight: 700;
            color: var(--text-primary);
        }
        
        .dex-info p {
            margin: 0;
            font-size: 14px;
            color: var(--text-muted);
            background: none;
            padding: 0;
            border: none;
            font-family: inherit;
        }
        
        .close-modal-btn {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 12px 24px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: var(--transition-fast);
        }
        
        .close-modal-btn:hover {
            background: var(--bg-tertiary);
            color: var(--text-primary);
        }
        
        @media (max-width: 768px) {
            .dex-buttons {
                flex-direction: column;
            }
            
            .dex-choice-content {
                padding: 24px;
            }
        }
    `;
    document.head.appendChild(style);
}

// Fonction de debug pour vérifier les éléments
function debugElements() {
    console.log('=== DEBUG ELEMENTS ===');
    console.log('wallets-table-body:', document.getElementById('wallets-table-body'));
    console.log('wallets-loading:', document.getElementById('wallets-loading'));
    console.log('wallet-row-template:', document.getElementById('wallet-row-template'));
    console.log('activity-list:', document.getElementById('activity-list'));
    console.log('activity-item-template:', document.getElementById('activity-item-template'));
}

// Initialiser l'application au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM chargé, initialisation...');
    
    // Debug des éléments
    debugElements();
    
    restoreTheme();
    checkPhantomConnection();
    
    // Petite pause pour s'assurer que tout est prêt
    setTimeout(() => {
        loadActivityData();
        loadWalletsData();
    }, 100);
    
    addCustomStyles();
    
    // Écouter les événements de Phantom Wallet
    if (window.phantom && window.phantom.solana) {
        window.phantom.solana.on('disconnect', () => {
            const walletStatus = document.getElementById('wallet-status');
            const connectBtn = document.querySelector('.wallet-connect-btn');
            
            phantomWallet = null;
            walletStatus.textContent = 'Connecter';
            connectBtn.classList.remove('connected');
            
            localStorage.removeItem('phantomConnected');
            localStorage.removeItem('phantomAddress');
            
            showNotification('Wallet déconnecté', 'info');
        });
        
        window.phantom.solana.on('connect', () => {
            showNotification('Wallet connecté !', 'success');
        });
    }
});