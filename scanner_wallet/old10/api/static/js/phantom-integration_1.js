// =============================================================================
// CORRECTION TRADING PHANTOM - Version optimisée
// =============================================================================

// Variables globales simplifiées
let phantomWallet = null;
let isPhantomConnected = false;
let connectionInProgress = false;

// Configuration simplifiée
const SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com";
const SOL_MINT = "So11111111111111111111111111111111111111112";

// =============================================================================
// DÉTECTION ET CONNEXION PHANTOM
// =============================================================================

async function detectPhantomWallet() {
    console.log("🔍 Détection de Phantom Wallet...");
    
    // Vérifier si Phantom est disponible
    if (typeof window.solana === 'undefined') {
        console.log("❌ Phantom Wallet non détecté");
        return false;
    }
    
    if (!window.solana.isPhantom) {
        console.log("❌ Extension trouvée mais ce n'est pas Phantom");
        return false;
    }
    
    console.log("✅ Phantom Wallet détecté");
    return true;
}

async function connectPhantomWallet() {
    if (connectionInProgress) {
        console.log("⏳ Connexion déjà en cours...");
        return false;
    }
    
    connectionInProgress = true;
    
    try {
        // Vérifier d'abord que Phantom est disponible
        const phantomDetected = await detectPhantomWallet();
        
        if (!phantomDetected) {
            // Rediriger vers l'installation
            showPhantomInstallModal();
            return false;
        }
        
        console.log("🔗 Tentative de connexion à Phantom...");
        
        // Demander la connexion
        const response = await window.solana.connect({ onlyIfTrusted: false });
        
        if (response && response.publicKey) {
            phantomWallet = response.publicKey.toString();
            isPhantomConnected = true;
            
            // Mettre à jour l'interface
            updateWalletUI(true);
            
            // Écouter les déconnexions
            window.solana.on('disconnect', handlePhantomDisconnect);
            
            showNotification("✅ Phantom Wallet connecté!", "success");
            console.log("✅ Phantom connecté:", phantomWallet);
            
            return true;
        } else {
            throw new Error("Réponse invalide de Phantom");
        }
        
    } catch (error) {
        console.error("❌ Erreur connexion Phantom:", error);
        
        if (error.code === 4001) {
            showNotification("❌ Connexion refusée par l'utilisateur", "warning");
        } else if (error.message.includes("User rejected")) {
            showNotification("❌ Connexion annulée", "warning");
        } else {
            showNotification("❌ Erreur de connexion: " + error.message, "error");
        }
        
        return false;
    } finally {
        connectionInProgress = false;
    }
}

function handlePhantomDisconnect() {
    phantomWallet = null;
    isPhantomConnected = false;
    updateWalletUI(false);
    showNotification("👻 Phantom Wallet déconnecté", "info");
    console.log("👻 Phantom déconnecté");
}

function updateWalletUI(connected) {
    const connectBtn = document.querySelector('.wallet-connect-btn');
    const walletStatus = document.getElementById('wallet-status');
    const walletInfo = document.getElementById('wallet-info');
    
    if (connected && phantomWallet) {
        // Cacher le bouton de connexion
        if (connectBtn) connectBtn.style.display = 'none';
        
        // Afficher les infos du wallet
        if (walletInfo) {
            walletInfo.style.display = 'flex';
            const addressSpan = walletInfo.querySelector('#wallet-address');
            if (addressSpan) {
                addressSpan.textContent = `${phantomWallet.substring(0, 4)}...${phantomWallet.substring(phantomWallet.length - 4)}`;
            }
        }
        
        // Mettre à jour le statut dans la sidebar
        updatePhantomSidebarStatus(true, phantomWallet);
        
    } else {
        // Afficher le bouton de connexion
        if (connectBtn) connectBtn.style.display = 'flex';
        
        // Cacher les infos du wallet
        if (walletInfo) walletInfo.style.display = 'none';
        
        // Mettre à jour la sidebar
        updatePhantomSidebarStatus(false);
    }
}

function updatePhantomSidebarStatus(connected, address = null) {
    const phantomStatus = document.getElementById('phantom-status');
    const phantomIcon = document.getElementById('phantom-icon');
    const phantomText = document.getElementById('phantom-text');
    
    if (phantomStatus && phantomIcon && phantomText) {
        if (connected && address) {
            phantomStatus.classList.add('connected');
            phantomIcon.textContent = '👻✅';
            phantomText.textContent = `Phantom: ${address.substring(0, 6)}...`;
        } else {
            phantomStatus.classList.remove('connected');
            phantomIcon.textContent = '👻';
            phantomText.textContent = 'Phantom: Déconnecté';
        }
    }
}

function showPhantomInstallModal() {
    const modal = document.createElement('div');
    modal.className = 'phantom-install-modal';
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
    `;
    
    modal.innerHTML = `
        <div style="
            background: var(--glass-bg);
            backdrop-filter: var(--blur-md);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 32px;
            max-width: 400px;
            text-align: center;
            color: var(--text-primary);
        ">
            <div style="font-size: 64px; margin-bottom: 16px;">👻</div>
            <h3 style="margin: 0 0 16px 0; font-size: 24px; font-weight: 700;">
                Phantom Wallet requis
            </h3>
            <p style="margin: 0 0 24px 0; color: var(--text-secondary); line-height: 1.5;">
                Pour trader des tokens, vous devez installer l'extension Phantom Wallet.
            </p>
            <div style="display: flex; gap: 12px; justify-content: center;">
                <button onclick="window.open('https://phantom.app/', '_blank'); closePhantomModal()" 
                        style="
                            background: linear-gradient(135deg, var(--solana-green), var(--solana-purple));
                            color: white;
                            border: none;
                            padding: 12px 24px;
                            border-radius: 12px;
                            font-weight: 600;
                            cursor: pointer;
                        ">
                    Installer Phantom
                </button>
                <button onclick="closePhantomModal()" 
                        style="
                            background: var(--glass-bg);
                            color: var(--text-primary);
                            border: 1px solid var(--glass-border);
                            padding: 12px 24px;
                            border-radius: 12px;
                            font-weight: 600;
                            cursor: pointer;
                        ">
                    Annuler
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Écouter les clics pour fermer
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closePhantomModal();
    });
    
    window.closePhantomModal = () => modal.remove();
}

// =============================================================================
// FONCTIONS DE TRADING SIMPLIFIÉES
// =============================================================================

async function buyToken(tokenMint) {
    console.log("🛒 Achat de token:", tokenMint);
    
    // Vérifier la connexion
    if (!isPhantomConnected || !phantomWallet) {
        const connected = await connectPhantomWallet();
        if (!connected) return;
    }
    
    // Ouvrir Jupiter avec les paramètres pré-remplis
    const jupiterUrl = `https://jup.ag/swap/${SOL_MINT}-${tokenMint}?amount=1`;
    
    showTradingConfirmation({
        action: "Acheter",
        tokenMint: tokenMint,
        dexUrl: jupiterUrl,
        wallet: phantomWallet
    });
}

async function sellToken(tokenMint) {
    console.log("💰 Vente de token:", tokenMint);
    
    // Vérifier la connexion
    if (!isPhantomConnected || !phantomWallet) {
        const connected = await connectPhantomWallet();
        if (!connected) return;
    }
    
    // Ouvrir Jupiter pour vendre
    const jupiterUrl = `https://jup.ag/swap/${tokenMint}-${SOL_MINT}`;
    
    showTradingConfirmation({
        action: "Vendre",
        tokenMint: tokenMint,
        dexUrl: jupiterUrl,
        wallet: phantomWallet
    });
}

function showTradingConfirmation({ action, tokenMint, dexUrl, wallet }) {
    const modal = document.createElement('div');
    modal.className = 'trading-confirmation-modal';
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
    
    const shortMint = `${tokenMint.substring(0, 6)}...${tokenMint.substring(tokenMint.length - 6)}`;
    const shortWallet = `${wallet.substring(0, 6)}...${wallet.substring(wallet.length - 6)}`;
    
    modal.innerHTML = `
        <div style="
            background: var(--glass-bg);
            backdrop-filter: var(--blur-md);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 32px;
            max-width: 500px;
            color: var(--text-primary);
        ">
            <h3 style="margin: 0 0 20px 0; font-size: 24px; font-weight: 700; text-align: center;">
                ${action} Token
            </h3>
            
            <div style="background: var(--bg-tertiary); padding: 20px; border-radius: 12px; margin-bottom: 24px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                    <span style="color: var(--text-secondary);">Token:</span>
                    <span style="font-family: monospace; color: var(--text-primary);">${shortMint}</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                    <span style="color: var(--text-secondary);">Wallet:</span>
                    <span style="font-family: monospace; color: var(--text-primary);">${shortWallet}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: var(--text-secondary);">DEX:</span>
                    <span style="color: var(--solana-green);">Jupiter</span>
                </div>
            </div>
            
            <p style="margin: 0 0 24px 0; color: var(--text-secondary); text-align: center; line-height: 1.5;">
                Vous allez être redirigé vers Jupiter pour effectuer le trade avec votre wallet Phantom connecté.
            </p>
            
            <div style="display: flex; gap: 12px; justify-content: center;">
                <button onclick="executeTrade('${dexUrl}'); closeTradingModal()" 
                        style="
                            background: linear-gradient(135deg, var(--solana-green), var(--solana-purple));
                            color: white;
                            border: none;
                            padding: 14px 28px;
                            border-radius: 12px;
                            font-weight: 600;
                            cursor: pointer;
                            font-size: 16px;
                        ">
                    🚀 ${action} sur Jupiter
                </button>
                <button onclick="closeTradingModal()" 
                        style="
                            background: var(--glass-bg);
                            color: var(--text-primary);
                            border: 1px solid var(--glass-border);
                            padding: 14px 28px;
                            border-radius: 12px;
                            font-weight: 600;
                            cursor: pointer;
                            font-size: 16px;
                        ">
                    Annuler
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Écouter les clics pour fermer
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeTradingModal();
    });
    
    window.closeTradingModal = () => modal.remove();
    window.executeTrade = (url) => {
        window.open(url, '_blank', 'noopener,noreferrer');
        showNotification(`🚀 Trading ouvert sur Jupiter`, "success");
    };
}

// =============================================================================
// FONCTIONS UTILITAIRES OPTIMISÉES
// =============================================================================

function disconnectWallet() {
    if (window.solana && window.solana.disconnect) {
        window.solana.disconnect();
    }
    handlePhantomDisconnect();
}

// Optimisation: Simplifier les notifications
function showNotification(message, type = 'info', duration = 3000) {
    // Supprimer les notifications existantes
    const existingNotifs = document.querySelectorAll('.simple-notification');
    existingNotifs.forEach(notif => notif.remove());
    
    const notification = document.createElement('div');
    notification.className = 'simple-notification';
    notification.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        background: var(--glass-bg);
        backdrop-filter: var(--blur-md);
        border: 1px solid var(--glass-border);
        color: var(--text-primary);
        padding: 12px 20px;
        border-radius: 12px;
        z-index: 10001;
        animation: slideInRight 0.3s ease;
        font-weight: 500;
        max-width: 350px;
        box-shadow: var(--shadow-lg);
    `;
    
    // Couleurs selon le type
    if (type === 'success') {
        notification.style.borderColor = 'var(--solana-green)';
        notification.style.color = 'var(--solana-green)';
    } else if (type === 'error') {
        notification.style.borderColor = '#ef4444';
        notification.style.color = '#ef4444';
    } else if (type === 'warning') {
        notification.style.borderColor = '#f59e0b';
        notification.style.color = '#f59e0b';
    }
    
    notification.textContent = message;
    document.body.appendChild(notification);
    
    // Supprimer automatiquement
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, duration);
}

// =============================================================================
// INITIALISATION OPTIMISÉE
// =============================================================================

// Vérifier la connexion existante au chargement
async function checkExistingConnection() {
    try {
        if (window.solana && window.solana.isConnected && window.solana.publicKey) {
            phantomWallet = window.solana.publicKey.toString();
            isPhantomConnected = true;
            updateWalletUI(true);
            
            // Écouter les déconnexions
            window.solana.on('disconnect', handlePhantomDisconnect);
            
            console.log("✅ Connexion Phantom existante détectée:", phantomWallet);
        }
    } catch (error) {
        console.log("ℹ️ Aucune connexion Phantom existante");
    }
}

// Initialisation simplifiée
document.addEventListener('DOMContentLoaded', function() {
    console.log("🚀 Initialisation Phantom Trading (version optimisée)");
    
    // Vérifier connexion existante avec délai
    setTimeout(checkExistingConnection, 1000);
    
    // Ajouter les styles CSS manquants
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideInRight {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        .simple-notification {
            transition: all 0.3s ease;
        }
        
        #phantom-status.connected {
            color: var(--solana-green) !important;
        }
    `;
    document.head.appendChild(style);
});

// Export des fonctions principales
window.buyToken = buyToken;
window.sellToken = sellToken;
window.connectPhantomWallet = connectPhantomWallet;
window.disconnectWallet = disconnectWallet;

console.log("✅ Module Phantom Trading (optimisé) chargé");