/* static/js/app.js */

class SolanaAnalyzer {
    constructor() {
        this.loadingOverlay = document.getElementById('loadingOverlay');
        this.resultsSection = document.getElementById('analysisResults');
        this.resultsContent = document.getElementById('resultsContent');
        
        this.initEventListeners();
    }

    initEventListeners() {
        // Formulaire d'analyse de wallet
        const walletForm = document.getElementById('walletAnalysisForm');
        if (walletForm) {
            walletForm.addEventListener('submit', (e) => this.handleWalletAnalysis(e));
        }

        // Formulaire d'analyse de token creator
        const tokenForm = document.getElementById('tokenAnalysisForm');
        if (tokenForm) {
            tokenForm.addEventListener('submit', (e) => this.handleTokenAnalysis(e));
        }

        // Bouton fermer résultats
        const closeResults = document.getElementById('closeResults');
        if (closeResults) {
            closeResults.addEventListener('click', () => this.hideResults());
        }

        // Validation en temps réel des adresses
        this.setupAddressValidation();
    }

    setupAddressValidation() {
        const addressInputs = document.querySelectorAll('input[name="wallet_address"], input[name="token_address"]');
        
        addressInputs.forEach(input => {
            input.addEventListener('input', (e) => {
                this.validateSolanaAddress(e.target);
            });
        });
    }

    validateSolanaAddress(input) {
        const address = input.value.trim();
        const isValid = this.isValidSolanaAddress(address);
        
        // Supprimer les classes précédentes
        input.classList.remove('valid', 'invalid');
        
        if (address.length > 0) {
            if (isValid) {
                input.classList.add('valid');
                this.showInputMessage(input, '✅ Adresse valide', 'success');
            } else {
                input.classList.add('invalid');
                this.showInputMessage(input, '❌ Adresse invalide (44 caractères requis)', 'error');
            }
        } else {
            this.hideInputMessage(input);
        }
    }

    isValidSolanaAddress(address) {
        // Validation basique: 44 caractères Base58
        const base58Regex = /^[1-9A-HJ-NP-Za-km-z]{44}$/;
        return base58Regex.test(address);
    }

    showInputMessage(input, message, type) {
        this.hideInputMessage(input);
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `input-message ${type}`;
        messageDiv.textContent = message;
        
        input.parentNode.appendChild(messageDiv);
    }

    hideInputMessage(input) {
        const existingMessage = input.parentNode.querySelector('.input-message');
        if (existingMessage) {
            existingMessage.remove();
        }
    }

    async handleWalletAnalysis(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const data = {
            wallet_address: formData.get('wallet_address').trim(),
            token_address: formData.get('token_address').trim() || null,
            days_back: parseInt(formData.get('days_back')),
            force_refresh: formData.get('force_refresh') === 'on'
        };

        // Validation
        if (!this.isValidSolanaAddress(data.wallet_address)) {
            this.showNotification('Adresse de wallet invalide', 'error');
            return;
        }

        if (data.token_address && !this.isValidSolanaAddress(data.token_address)) {
            this.showNotification('Adresse de token invalide', 'error');
            return;
        }

        try {
            this.showLoading('Analyse du wallet en cours...');
            
            const response = await fetch('/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (result.success) {
                this.showAnalysisResult(result);
                this.showNotification('Analyse terminée avec succès!', 'success');
            } else {
                throw new Error(result.error || 'Erreur inconnue');
            }

        } catch (error) {
            console.error('Erreur analyse wallet:', error);
            this.showNotification(`Erreur: ${error.message}`, 'error');
        } finally {
            this.hideLoading();
        }
    }

    async handleTokenAnalysis(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const data = {
            token_address: formData.get('token_address').trim(),
            hours_back: parseInt(formData.get('hours_back')),
            exhaustive_search: formData.get('exhaustive_search') === 'on',
            force_refresh: formData.get('force_refresh') === 'on'
        };

        // Validation
        if (!this.isValidSolanaAddress(data.token_address)) {
            this.showNotification('Adresse de token invalide', 'error');
            return;
        }

        try {
            this.showLoading('Analyse du token creator en cours...');
            
            const response = await fetch('/analyze-token', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (result.success) {
                this.showAnalysisResult(result);
                this.showNotification('Analyse du token creator terminée!', 'success');
            } else {
                throw new Error(result.error || 'Erreur inconnue');
            }

        } catch (error) {
            console.error('Erreur analyse token:', error);
            this.showNotification(`Erreur: ${error.message}`, 'error');
        } finally {
            this.hideLoading();
        }
    }

    showLoading(message = 'Analyse en cours...') {
        if (this.loadingOverlay) {
            const loadingText = this.loadingOverlay.querySelector('p');
            if (loadingText) {
                loadingText.textContent = message;
            }
            this.loadingOverlay.style.display = 'flex';
        }
    }

    hideLoading() {
        if (this.loadingOverlay) {
            this.loadingOverlay.style.display = 'none';
        }
    }

    showAnalysisResult(result) {
        if (!this.resultsSection || !this.resultsContent) return;

        // Générer le contenu des résultats
        const resultHTML = this.generateResultHTML(result);
        this.resultsContent.innerHTML = resultHTML;
        
        // Afficher la section résultats
        this.resultsSection.style.display = 'block';
        
        // Scroll vers les résultats
        this.resultsSection.scrollIntoView({ 
            behavior: 'smooth',
            block: 'start'
        });
    }

    generateResultHTML(result) {
        const summary = result.analysis_summary;
        const reportId = result.report_id;
        
        return `
            <div class="result-summary">
                <div class="result-header">
                    <div class="result-title">
                        <h3>✅ Analyse terminée</h3>
                        <p>Rapport #${reportId} généré avec succès</p>
                    </div>
                    <div class="result-risk risk-${this.getRiskClass(summary.risk_level)}">
                        <div class="risk-score">${summary.risk_score}/100</div>
                        <div class="risk-label">${summary.risk_level}</div>
                    </div>
                </div>
                
                <div class="result-stats">
                    <div class="stat-card">
                        <i class="fas fa-wallet"></i>
                        <div class="stat-content">
                            <div class="stat-label">Balance SOL</div>
                            <div class="stat-value">${summary.sol_balance.toFixed(4)}</div>
                        </div>
                    </div>
                    
                    <div class="stat-card">
                        <i class="fas fa-coins"></i>
                        <div class="stat-content">
                            <div class="stat-label">Tokens</div>
                            <div class="stat-value">${summary.tokens_count}</div>
                        </div>
                    </div>
                    
                    <div class="stat-card">
                        <i class="fas fa-chart-line"></i>
                        <div class="stat-content">
                            <div class="stat-label">Activité</div>
                            <div class="stat-value">${summary.activity_level}</div>
                        </div>
                    </div>
                    
                    <div class="stat-card">
                        <i class="fas fa-clock"></i>
                        <div class="stat-content">
                            <div class="stat-label">Durée</div>
                            <div class="stat-value">${summary.analysis_duration.toFixed(1)}s</div>
                        </div>
                    </div>
                </div>
                
                <div class="result-wallet">
                    <div class="wallet-info">
                        <label>Wallet analysé:</label>
                        <code>${result.wallet_address}</code>
                    </div>
                    ${result.creator_address ? `
                    <div class="creator-info">
                        <label>Créateur identifié:</label>
                        <code>${result.creator_address}</code>
                    </div>
                    ` : ''}
                    ${result.token_address ? `
                    <div class="token-info">
                        <label>Token:</label>
                        <code>${result.token_address}</code>
                    </div>
                    ` : ''}
                </div>
                
                <div class="result-actions">
                    <a href="/report/${reportId}" class="btn-primary">
                        <i class="fas fa-file-alt"></i>
                        Voir le rapport complet
                    </a>
                    <button onclick="analyzer.shareResult(${reportId})" class="btn-secondary">
                        <i class="fas fa-share"></i>
                        Partager
                    </button>
                </div>
            </div>
        `;
    }

    getRiskClass(riskLevel) {
        const riskMap = {
            'CRITIQUE': 'critique',
            'TRÈS ÉLEVÉ': 'elevé',
            'ÉLEVÉ': 'elevé',
            'MODÉRÉ': 'modéré',
            'FAIBLE': 'faible'
        };
        return riskMap[riskLevel] || 'unknown';
    }

    hideResults() {
        if (this.resultsSection) {
            this.resultsSection.style.display = 'none';
        }
    }

    showNotification(message, type = 'info') {
        // Créer la notification
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        
        const icon = type === 'success' ? 'check-circle' : 
                    type === 'error' ? 'exclamation-triangle' : 
                    'info-circle';
        
        notification.innerHTML = `
            <div class="notification-content">
                <i class="fas fa-${icon}"></i>
                <span>${message}</span>
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        `;

        // Ajouter au DOM
        document.body.appendChild(notification);

        // Auto-supprimer après 5 secondes
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);

        // Animation d'entrée
        setTimeout(() => {
            notification.classList.add('show');
        }, 100);
    }

    async shareResult(reportId) {
        const url = `${window.location.origin}/report/${reportId}`;
        
        if (navigator.share) {
            try {
                await navigator.share({
                    title: `Rapport d'analyse Solana #${reportId}`,
                    text: 'Analyse complète de wallet Solana',
                    url: url
                });
            } catch (error) {
                console.log('Partage annulé');
            }
        } else {
            // Fallback: copier dans le presse-papiers
            try {
                await navigator.clipboard.writeText(url);
                this.showNotification('Lien copié dans le presse-papiers!', 'success');
            } catch (error) {
                this.showNotification('Impossible de copier le lien', 'error');
            }
        }
    }

    // Utilitaires
    formatSOL(value) {
        return parseFloat(value).toFixed(4);
    }

    formatAddress(address) {
        if (!address) return '';
        return `${address.slice(0, 8)}...${address.slice(-8)}`;
    }

    formatTimestamp(timestamp) {
        return new Date(timestamp).toLocaleString('fr-FR');
    }
}

// Classes utilitaires pour les animations et interactions
class UIUtils {
    static addRippleEffect(element) {
        element.addEventListener('click', function(e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;
            
            ripple.style.cssText = `
                position: absolute;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.3);
                width: ${size}px;
                height: ${size}px;
                left: ${x}px;
                top: ${y}px;
                transform: scale(0);
                animation: ripple 0.6s linear;
                pointer-events: none;
            `;
            
            ripple.className = 'ripple';
            this.style.position = 'relative';
            this.style.overflow = 'hidden';
            this.appendChild(ripple);
            
            setTimeout(() => {
                ripple.remove();
            }, 600);
        });
    }

    static animateValue(element, start, end, duration = 1000) {
        const startTime = performance.now();
        const startValue = parseInt(start) || 0;
        const endValue = parseInt(end) || 0;
        
        function update(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            
            // Easing function (ease-out)
            const easeOut = 1 - Math.pow(1 - progress, 3);
            const currentValue = Math.round(startValue + (endValue - startValue) * easeOut);
            
            element.textContent = currentValue;
            
            if (progress < 1) {
                requestAnimationFrame(update);
            }
        }
        
        requestAnimationFrame(update);
    }

    static typeWriter(element, text, speed = 50) {
        element.textContent = '';
        let i = 0;
        
        function type() {
            if (i < text.length) {
                element.textContent += text.charAt(i);
                i++;
                setTimeout(type, speed);
            }
        }
        
        type();
    }

    static observeIntersection(elements, callback, options = {}) {
        const defaultOptions = {
            threshold: 0.1,
            rootMargin: '0px 0px -50px 0px'
        };
        
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    callback(entry.target);
                    observer.unobserve(entry.target);
                }
            });
        }, { ...defaultOptions, ...options });
        
        elements.forEach(el => observer.observe(el));
    }

    static createLoadingSpinner(size = 'medium') {
        const spinner = document.createElement('div');
        spinner.className = `loading-spinner ${size}`;
        spinner.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        return spinner;
    }

    static debounce(func, wait, immediate = false) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                timeout = null;
                if (!immediate) func(...args);
            };
            const callNow = immediate && !timeout;
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
            if (callNow) func(...args);
        };
    }

    static throttle(func, limit) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }

    static copyToClipboard(text) {
        if (navigator.clipboard) {
            return navigator.clipboard.writeText(text);
        } else {
            // Fallback pour navigateurs plus anciens
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            
            return new Promise((resolve, reject) => {
                if (document.execCommand('copy')) {
                    resolve();
                } else {
                    reject(new Error('Impossible de copier'));
                }
                document.body.removeChild(textArea);
            });
        }
    }

    static formatNumber(num, decimals = 2) {
        if (num === null || num === undefined) return 'N/A';
        return new Intl.NumberFormat('fr-FR', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        }).format(num);
    }

    static formatCurrency(amount, currency = 'SOL') {
        if (amount === null || amount === undefined) return 'N/A';
        return `${UIUtils.formatNumber(amount, 4)} ${currency}`;
    }

    static formatPercentage(value, decimals = 1) {
        if (value === null || value === undefined) return 'N/A';
        return `${UIUtils.formatNumber(value, decimals)}%`;
    }

    static timeAgo(timestamp) {
        const now = new Date();
        const date = new Date(timestamp);
        const diffInSeconds = Math.floor((now - date) / 1000);
        
        if (diffInSeconds < 60) return `il y a ${diffInSeconds}s`;
        if (diffInSeconds < 3600) return `il y a ${Math.floor(diffInSeconds / 60)}min`;
        if (diffInSeconds < 86400) return `il y a ${Math.floor(diffInSeconds / 3600)}h`;
        if (diffInSeconds < 2592000) return `il y a ${Math.floor(diffInSeconds / 86400)}j`;
        
        return date.toLocaleDateString('fr-FR');
    }
}

// Gestionnaire de cache local (simulation localStorage sans localStorage)
class CacheManager {
    constructor() {
        this.cache = new Map();
        this.maxSize = 50;
        this.stats = {
            hits: 0,
            misses: 0,
            sets: 0
        };
    }

    set(key, value, ttl = 3600000) { // TTL par défaut: 1 heure
        if (this.cache.size >= this.maxSize) {
            // Supprimer le plus ancien
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }
        
        this.cache.set(key, {
            value,
            timestamp: Date.now(),
            ttl
        });
        
        this.stats.sets++;
    }

    get(key) {
        const item = this.cache.get(key);
        if (!item) {
            this.stats.misses++;
            return null;
        }
        
        if (Date.now() - item.timestamp > item.ttl) {
            this.cache.delete(key);
            this.stats.misses++;
            return null;
        }
        
        this.stats.hits++;
        return item.value;
    }

    has(key) {
        return this.get(key) !== null;
    }

    delete(key) {
        return this.cache.delete(key);
    }

    clear() {
        this.cache.clear();
        this.stats = { hits: 0, misses: 0, sets: 0 };
    }

    size() {
        return this.cache.size;
    }

    getStats() {
        const total = this.stats.hits + this.stats.misses;
        return {
            ...this.stats,
            hitRate: total > 0 ? (this.stats.hits / total * 100).toFixed(1) : '0',
            size: this.cache.size,
            maxSize: this.maxSize
        };
    }
}

// Gestionnaire de thème
class ThemeManager {
    constructor() {
        this.theme = this.getStoredTheme() || 'dark'; // Thème par défaut
        this.initTheme();
        this.createThemeToggle();
    }

    getStoredTheme() {
        // Simulation du localStorage avec une variable globale
        return window.themePreference || null;
    }

    setStoredTheme(theme) {
        window.themePreference = theme;
    }

    initTheme() {
        document.documentElement.setAttribute('data-theme', this.theme);
        this.updateThemeIcon();
    }

    toggle() {
        this.theme = this.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', this.theme);
        this.setStoredTheme(this.theme);
        this.updateThemeIcon();
        
        // Animation de transition
        document.body.style.transition = 'background-color 0.3s ease, color 0.3s ease';
        setTimeout(() => {
            document.body.style.transition = '';
        }, 300);
    }

    createThemeToggle() {
        const themeBtn = document.createElement('button');
        themeBtn.className = 'theme-toggle';
        themeBtn.setAttribute('aria-label', 'Changer de thème');
        themeBtn.innerHTML = '<i class="fas fa-moon"></i>';
        themeBtn.addEventListener('click', () => this.toggle());
        
        // Ajouter à la navbar si elle existe
        const navbar = document.querySelector('.nav-menu');
        if (navbar) {
            const li = document.createElement('li');
            li.appendChild(themeBtn);
            navbar.appendChild(li);
        }
    }

    updateThemeIcon() {
        const themeBtn = document.querySelector('.theme-toggle');
        if (themeBtn) {
            const icon = themeBtn.querySelector('i');
            if (icon) {
                icon.className = this.theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
            }
        }
    }
}

// Gestionnaire de statistiques en temps réel
class StatsManager {
    constructor() {
        this.stats = {
            totalAnalyses: 0,
            avgRiskScore: 0,
            totalRequests: 0,
            cacheHitRate: 0,
            activeUsers: 0,
            systemStatus: 'operational'
        };
        this.updateInterval = null;
        this.isVisible = true;
        
        this.initVisibilityHandler();
    }

    initVisibilityHandler() {
        document.addEventListener('visibilitychange', () => {
            this.isVisible = !document.hidden;
            if (this.isVisible) {
                this.resumeUpdates();
            } else {
                this.pauseUpdates();
            }
        });
    }

    async fetchStats() {
        if (!this.isVisible) return;
        
        try {
            const response = await fetch('/api/stats', {
                method: 'GET',
                headers: { 'Accept': 'application/json' }
            });
            
            if (response.ok) {
                const data = await response.json();
                this.updateStats(data);
            }
        } catch (error) {
            console.warn('Erreur récupération stats:', error);
            this.stats.systemStatus = 'degraded';
            this.displayStats();
        }
    }

    updateStats(newStats) {
        this.stats = { ...this.stats, ...newStats };
        this.displayStats();
    }

    displayStats() {
        // Mise à jour des éléments de stats si présents
        const elements = {
            totalAnalyses: document.querySelector('.stat-total-analyses'),
            avgRiskScore: document.querySelector('.stat-avg-risk'),
            totalRequests: document.querySelector('.stat-total-requests'),
            cacheHitRate: document.querySelector('.stat-cache-rate'),
            activeUsers: document.querySelector('.stat-active-users'),
            systemStatus: document.querySelector('.system-status')
        };

        Object.entries(elements).forEach(([key, element]) => {
            if (element) {
                const value = this.stats[key];
                if (typeof value === 'number' && key !== 'avgRiskScore') {
                    UIUtils.animateValue(element, 0, value);
                } else if (key === 'avgRiskScore') {
                    element.textContent = `${value}/100`;
                } else if (key === 'cacheHitRate') {
                    element.textContent = `${value}%`;
                } else if (key === 'systemStatus') {
                    element.textContent = value;
                    element.className = `system-status ${value}`;
                } else {
                    element.textContent = value;
                }
            }
        });
    }

    startUpdates(interval = 30000) {
        this.fetchStats(); // Première récupération immédiate
        this.updateInterval = setInterval(() => this.fetchStats(), interval);
    }

    pauseUpdates() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    }

    resumeUpdates() {
        if (!this.updateInterval) {
            this.startUpdates();
        }
    }

    destroy() {
        this.pauseUpdates();
    }
}

// Gestionnaire de validation de formulaires
class FormValidator {
    constructor() {
        this.rules = new Map();
        this.errors = new Map();
    }

    addRule(fieldName, validator, errorMessage) {
        if (!this.rules.has(fieldName)) {
            this.rules.set(fieldName, []);
        }
        this.rules.get(fieldName).push({ validator, errorMessage });
    }

    validate(formData) {
        this.errors.clear();
        let isValid = true;

        for (const [fieldName, rules] of this.rules) {
            const value = formData.get(fieldName);
            
            for (const rule of rules) {
                if (!rule.validator(value)) {
                    this.errors.set(fieldName, rule.errorMessage);
                    isValid = false;
                    break;
                }
            }
        }

        return isValid;
    }

    getErrors() {
        return Object.fromEntries(this.errors);
    }

    displayErrors(formElement) {
        // Nettoyer les erreurs précédentes
        formElement.querySelectorAll('.field-error').forEach(el => el.remove());

        // Afficher les nouvelles erreurs
        for (const [fieldName, errorMessage] of this.errors) {
            const field = formElement.querySelector(`[name="${fieldName}"]`);
            if (field) {
                const errorDiv = document.createElement('div');
                errorDiv.className = 'field-error';
                errorDiv.textContent = errorMessage;
                field.parentNode.appendChild(errorDiv);
                field.classList.add('error');
            }
        }
    }

    clearErrors(formElement) {
        formElement.querySelectorAll('.field-error').forEach(el => el.remove());
        formElement.querySelectorAll('.error').forEach(el => el.classList.remove('error'));
        this.errors.clear();
    }
}

// Gestionnaire de WebSocket pour les mises à jour en temps réel
class WebSocketManager {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.listeners = new Map();
    }

    connect() {
        try {
            this.ws = new WebSocket(this.url);
            
            this.ws.onopen = () => {
                console.log('WebSocket connecté');
                this.reconnectAttempts = 0;
                this.emit('connected');
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.emit(data.type, data.payload);
                } catch (error) {
                    console.error('Erreur parsing message WebSocket:', error);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket fermé');
                this.emit('disconnected');
                this.attemptReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('Erreur WebSocket:', error);
                this.emit('error', error);
            };

        } catch (error) {
            console.error('Erreur connexion WebSocket:', error);
            this.attemptReconnect();
        }
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Tentative de reconnexion ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);
            
            setTimeout(() => {
                this.connect();
            }, this.reconnectDelay * this.reconnectAttempts);
        }
    }

    send(type, payload) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, payload }));
        }
    }

    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    off(event, callback) {
        if (this.listeners.has(event)) {
            const callbacks = this.listeners.get(event);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        }
    }

    emit(event, data) {
        if (this.listeners.has(event)) {
            this.listeners.get(event).forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error('Erreur callback WebSocket:', error);
                }
            });
        }
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}

// Gestionnaire de notifications push
class NotificationManager {
    constructor() {
        this.permission = Notification.permission;
        this.queue = [];
        this.maxQueue = 10;
    }

    async requestPermission() {
        if ('Notification' in window) {
            this.permission = await Notification.requestPermission();
            return this.permission === 'granted';
        }
        return false;
    }

    show(title, options = {}) {
        const defaultOptions = {
            icon: '/static/images/icon-192.png',
            badge: '/static/images/badge-72.png',
            tag: 'solana-analyzer',
            renotify: false,
            requireInteraction: false,
            ...options
        };

        if (this.permission === 'granted') {
            const notification = new Notification(title, defaultOptions);
            
            notification.onclick = () => {
                window.focus();
                if (options.onclick) {
                    options.onclick();
                }
                notification.close();
            };

            // Auto-fermer après 5 secondes
            setTimeout(() => {
                notification.close();
            }, 5000);

            return notification;
        } else {
            // Fallback vers notification interne
            if (window.analyzer) {
                window.analyzer.showNotification(title, options.type || 'info');
            }
        }
    }

    showAnalysisComplete(reportId, walletAddress) {
        this.show('Analyse terminée', {
            body: `Le rapport d'analyse du wallet ${walletAddress.slice(0, 8)}... est prêt`,
            type: 'success',
            onclick: () => {
                window.location.href = `/report/${reportId}`;
            }
        });
    }

    showAnalysisError(error) {
        this.show('Erreur d\'analyse', {
            body: error.message || 'Erreur lors de l\'analyse',
            type: 'error'
        });
    }
}

// Initialisation au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Initialisation de Solana Analyzer...');

    // Instances principales
    window.analyzer = new SolanaAnalyzer();
    window.cache = new CacheManager();
    window.theme = new ThemeManager();
    window.stats = new StatsManager();
    window.notifications = new NotificationManager();

    // Validator pour les formulaires
    window.validator = new FormValidator();
    
    // Règles de validation
    window.validator.addRule('wallet_address', 
        (value) => value && /^[1-9A-HJ-NP-Za-km-z]{44}$/.test(value.trim()), 
        'Adresse de wallet invalide (44 caractères Base58 requis)'
    );
    
    window.validator.addRule('token_address', 
        (value) => !value || /^[1-9A-HJ-NP-Za-km-z]{44}$/.test(value.trim()), 
        'Adresse de token invalide (44 caractères Base58 requis)'
    );

    // Ajouter les effets ripple aux boutons
    const buttons = document.querySelectorAll('.btn-primary, .btn-secondary, .btn-view');
    buttons.forEach(button => {
        UIUtils.addRippleEffect(button);
    });

    // Observer les éléments pour les animations
    const animatedElements = document.querySelectorAll('.form-card, .report-section, .summary-card, .report-card');
    UIUtils.observeIntersection(animatedElements, (element) => {
        element.style.opacity = '0';
        element.style.transform = 'translateY(20px)';
        element.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        
        setTimeout(() => {
            element.style.opacity = '1';
            element.style.transform = 'translateY(0)';
        }, 100);
    });

    // Démarrer les stats si on est sur la page d'accueil
    if (window.location.pathname === '/' || window.location.pathname === '/cache-stats') {
        window.stats.startUpdates();
    }

    // Gestion des raccourcis clavier
    document.addEventListener('keydown', function(e) {
        // Ctrl/Cmd + K pour focus sur le premier input
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            const firstInput = document.querySelector('input[type="text"]');
            if (firstInput) {
                firstInput.focus();
                firstInput.select();
            }
        }
        
        // Escape pour fermer les résultats ou notifications
        if (e.key === 'Escape') {
            // Fermer les résultats d'analyse
            if (window.analyzer && window.analyzer.resultsSection && 
                window.analyzer.resultsSection.style.display !== 'none') {
                window.analyzer.hideResults();
            }
            
            // Fermer les notifications
            document.querySelectorAll('.notification').forEach(notification => {
                notification.remove();
            });
        }
        
        // Ctrl/Cmd + Enter pour soumettre le formulaire actif
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            const activeForm = document.querySelector('form:focus-within');
            if (activeForm) {
                const submitBtn = activeForm.querySelector('button[type="submit"]');
                if (submitBtn) {
                    submitBtn.click();
                }
            }
        }
    });

    // Gestion de la visibilité de la page pour optimiser les performances
    let isVisible = true;
    document.addEventListener('visibilitychange', function() {
        isVisible = !document.hidden;
        if (isVisible) {
            console.log('🔄 Page visible - reprise des activités');
            // Reprendre les animations et requêtes
            if (window.stats) {
                window.stats.resumeUpdates();
            }
        } else {
            console.log('⏸️ Page cachée - pause des activités');
            // Pauser les animations et requêtes non critiques
            if (window.stats) {
                window.stats.pauseUpdates();
            }
        }
    });

    // Gestion des erreurs globales
    window.addEventListener('error', function(e) {
        console.error('🚨 Erreur globale:', e.error);
        if (window.analyzer) {
            window.analyzer.showNotification(
                'Une erreur inattendue s\'est produite', 
                'error'
            );
        }
    });

    // Gestion des promesses rejetées
    window.addEventListener('unhandledrejection', function(e) {
        console.error('⚠️ Promise rejetée:', e.reason);
        if (window.analyzer) {
            window.analyzer.showNotification(
                'Erreur de connexion au serveur', 
                'error'
            );
        }
        e.preventDefault();
    });

    // Performance monitoring
    if ('performance' in window && 'getEntriesByType' in performance) {
        window.addEventListener('load', function() {
            setTimeout(() => {
                const perfData = performance.getEntriesByType('navigation')[0];
                if (perfData) {
                    const metrics = {
                        'DOM chargé': Math.round(perfData.domContentLoadedEventEnd - perfData.domContentLoadedEventStart),
                        'Page complète': Math.round(perfData.loadEventEnd - perfData.loadEventStart),
                        'TTFB': Math.round(perfData.responseStart - perfData.requestStart)
                    };
                    console.log('⚡ Performance:', metrics);
                    
                    // Envoyer les métriques si l'API est disponible
                    if (window.stats) {
                        window.stats.updateStats({ performanceMetrics: metrics });
                    }
                }
            }, 100);
        });
    }

    // Initialiser WebSocket si disponible
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
    
    // Test de connexion WebSocket (optionnel)
    if (window.location.pathname === '/') {
        setTimeout(() => {
            try {
                window.ws = new WebSocketManager(wsUrl);
                window.ws.on('analysis_update', (data) => {
                    console.log('📊 Mise à jour analyse:', data);
                    if (window.analyzer) {
                        window.analyzer.showNotification(
                            `Analyse ${data.status}`, 
                            data.status === 'completed' ? 'success' : 'info'
                        );
                    }
                });
                // window.ws.connect(); // Décommenter si WebSocket implémenté côté serveur
            } catch (error) {
                console.log('WebSocket non disponible');
            }
        }, 2000);
    }

    // Demander permission pour les notifications
    if ('Notification' in window && Notification.permission === 'default') {
        setTimeout(() => {
            window.notifications.requestPermission();
        }, 5000);
    }

    // Cleanup au déchargement de la page
    window.addEventListener('beforeunload', function() {
        if (window.stats) {
            window.stats.destroy();
        }
        if (window.ws) {
            window.ws.disconnect();
        }
    });

    console.log('✅ Solana Analyzer initialisé avec succès');
    console.log('🎯 Fonctionnalités disponibles:');
    console.log('   - Validation en temps réel');
    console.log('   - Cache intelligent');
    console.log('   - Animations fluides');
    console.log('   - Raccourcis clavier');
    console.log('   - Performance monitoring');
    console.log('   - Notifications push');
});