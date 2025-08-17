// search-theme.js
// Fonctionnalités de recherche et gestion des thèmes

class DashboardFeatures {
    constructor() {
        this.currentTheme = this.getStoredTheme() || 'dark';
        this.searchTerms = { activity: '', wallets: '' };
        this.searchResults = { activity: 0, wallets: 0 };
        this.debounceTimeout = null;
        
        this.init();
    }

    init() {
        console.log('🚀 [FEATURES] Initializing search and theme features...');
        this.applyTheme(this.currentTheme);
        this.setupThemeToggle();
        this.setupSearchInputs();
        this.setupKeyboardShortcuts();
        console.log('✅ [FEATURES] Features initialized');
    }

    // === GESTION DES THÈMES ===
    
    getStoredTheme() {
        try {
            return localStorage.getItem('dashboard-theme');
        } catch (e) {
            console.warn('⚠️ [THEME] LocalStorage not available, using default theme');
            return null;
        }
    }

    setStoredTheme(theme) {
        try {
            localStorage.setItem('dashboard-theme', theme);
        } catch (e) {
            console.warn('⚠️ [THEME] Could not save theme preference');
        }
    }

    applyTheme(theme) {
        console.log(`🎨 [THEME] Applying theme: ${theme}`);
        
        document.documentElement.setAttribute('data-theme', theme);
        this.currentTheme = theme;
        this.setStoredTheme(theme);
        
        // Mettre à jour l'icône du toggle
        this.updateThemeToggleIcon(theme);
        
        // Déclencher un événement personnalisé pour d'autres composants
        window.dispatchEvent(new CustomEvent('themeChanged', { 
            detail: { theme } 
        }));
    }

    toggleTheme() {
        const newTheme = this.currentTheme === 'dark' ? 'light' : 'dark';
        console.log(`🔄 [THEME] Toggling theme: ${this.currentTheme} → ${newTheme}`);
        
        // Animation de transition
        document.body.style.transition = 'all 0.3s ease';
        
        this.applyTheme(newTheme);
        
        // Feedback visuel
        this.showThemeChangedNotification(newTheme);
        
        setTimeout(() => {
            document.body.style.transition = '';
        }, 300);
    }

    updateThemeToggleIcon(theme) {
        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            const icon = toggle.querySelector('#theme-icon');
            if (icon) {
                icon.textContent = theme === 'dark' ? '☀️' : '🌙';
            }
            toggle.className = `theme-toggle ${theme}`;
            toggle.title = `Passer au thème ${theme === 'dark' ? 'clair' : 'sombre'}`;
        }
    }

    setupThemeToggle() {
        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            toggle.addEventListener('click', () => this.toggleTheme());
            console.log('🎨 [THEME] Theme toggle setup complete');
        }
    }

    showThemeChangedNotification(theme) {
        // Créer une notification temporaire
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 80px;
            right: 20px;
            background: var(--theme-glass-bg);
            backdrop-filter: blur(10px);
            border: 1px solid var(--theme-glass-border);
            border-radius: 12px;
            padding: 12px 16px;
            color: var(--theme-text-primary);
            font-size: 14px;
            font-weight: 500;
            z-index: 9999;
            opacity: 0;
            transform: translateX(100px);
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        `;
        
        notification.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span>${theme === 'dark' ? '🌙' : '☀️'}</span>
                <span>Thème ${theme === 'dark' ? 'sombre' : 'clair'} activé</span>
            </div>
        `;
        
        document.body.appendChild(notification);
        
        // Animation d'entrée
        setTimeout(() => {
            notification.style.opacity = '1';
            notification.style.transform = 'translateX(0)';
        }, 100);
        
        // Suppression automatique
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transform = 'translateX(100px)';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 2000);
    }

    // === GESTION DE LA RECHERCHE ===

    setupSearchInputs() {
        // Recherche pour les activités
        const activitySearch = document.getElementById('activity-search');
        if (activitySearch) {
            activitySearch.addEventListener('input', (e) => {
                this.handleSearch('activity', e.target.value);
            });
            
            // Bouton clear
            const activityClear = activitySearch.parentNode.querySelector('.search-clear');
            if (activityClear) {
                activityClear.addEventListener('click', () => {
                    activitySearch.value = '';
                    this.handleSearch('activity', '');
                    activitySearch.focus();
                });
            }
        }

        // Recherche pour les wallets
        const walletsSearch = document.getElementById('wallets-search');
        if (walletsSearch) {
            walletsSearch.addEventListener('input', (e) => {
                this.handleSearch('wallets', e.target.value);
            });
            
            // Bouton clear
            const walletsClear = walletsSearch.parentNode.querySelector('.search-clear');
            if (walletsClear) {
                walletsClear.addEventListener('click', () => {
                    walletsSearch.value = '';
                    this.handleSearch('wallets', '');
                    walletsSearch.focus();
                });
            }
        }

        console.log('🔍 [SEARCH] Search inputs setup complete');
    }

    handleSearch(tableType, searchTerm) {
        // Debounce pour éviter trop de recherches
        clearTimeout(this.debounceTimeout);
        this.debounceTimeout = setTimeout(() => {
            this.performSearch(tableType, searchTerm);
        }, 150);
    }

    performSearch(tableType, searchTerm) {
        console.log(`🔍 [SEARCH] Searching in ${tableType} for: "${searchTerm}"`);
        
        this.searchTerms[tableType] = searchTerm.toLowerCase().trim();
        
        if (tableType === 'activity') {
            this.searchInActivityTable(this.searchTerms[tableType]);
        } else if (tableType === 'wallets') {
            this.searchInWalletsTable(this.searchTerms[tableType]);
        }
        
        this.updateSearchResults(tableType);
    }

    searchInActivityTable(searchTerm) {
        const tbody = document.getElementById('activity-table-body');
        if (!tbody) return;

        const rows = tbody.querySelectorAll('tr');
        let visibleCount = 0;

        rows.forEach(row => {
            if (row.querySelector('td[colspan]')) {
                // Ligne de message (loading, error, etc.)
                row.style.display = '';
                return;
            }

            let matchFound = false;
            
            if (!searchTerm) {
                matchFound = true;
            } else {
                const searchableText = this.getActivityRowSearchableText(row);
                matchFound = searchableText.includes(searchTerm);
                
                if (matchFound) {
                    this.highlightSearchTerms(row, searchTerm);
                    row.classList.add('search-match');
                    setTimeout(() => row.classList.remove('search-match'), 500);
                } else {
                    this.removeHighlights(row);
                }
            }

            if (matchFound) {
                row.classList.remove('search-hidden');
                visibleCount++;
            } else {
                row.classList.add('search-hidden');
            }
        });

        this.searchResults.activity = visibleCount;
        console.log(`🔍 [SEARCH] Activity search complete: ${visibleCount} results`);
    }

    searchInWalletsTable(searchTerm) {
        const tbody = document.getElementById('wallets-table-body');
        if (!tbody) return;

        const rows = tbody.querySelectorAll('tr');
        let visibleCount = 0;

        rows.forEach(row => {
            if (row.querySelector('td[colspan]')) {
                // Ligne de message (loading, error, etc.)
                row.style.display = '';
                return;
            }

            let matchFound = false;
            
            if (!searchTerm) {
                matchFound = true;
            } else {
                const searchableText = this.getWalletRowSearchableText(row);
                matchFound = searchableText.includes(searchTerm);
                
                if (matchFound) {
                    this.highlightSearchTerms(row, searchTerm);
                    row.classList.add('search-match');
                    setTimeout(() => row.classList.remove('search-match'), 500);
                } else {
                    this.removeHighlights(row);
                }
            }

            if (matchFound) {
                row.classList.remove('search-hidden');
                visibleCount++;
            } else {
                row.classList.add('search-hidden');
            }
        });

        this.searchResults.wallets = visibleCount;
        console.log(`🔍 [SEARCH] Wallets search complete: ${visibleCount} results`);
    }

    getActivityRowSearchableText(row) {
        const walletCol = row.querySelector('.wallet-col a')?.title || '';
        const tokenCol = row.querySelector('.token-col')?.textContent || '';
        const tokenAddrCol = row.querySelector('.token-addr-col button')?.dataset.copy || '';
        const typeCol = row.querySelector('.type-col span')?.textContent || '';
        
        return `${walletCol} ${tokenCol} ${tokenAddrCol} ${typeCol}`.toLowerCase();
    }

    getWalletRowSearchableText(row) {
        const walletCell = row.querySelector('.wallet-cell');
        const walletAddr = walletCell?.dataset.address || '';
        const walletShort = row.querySelector('.wallet-address-small')?.textContent || '';
        
        return `${walletAddr} ${walletShort}`.toLowerCase();
    }

    highlightSearchTerms(row, searchTerm) {
        if (!searchTerm) return;

        const textNodes = this.getTextNodes(row);
        textNodes.forEach(node => {
            const text = node.textContent;
            const regex = new RegExp(`(${this.escapeRegex(searchTerm)})`, 'gi');
            
            if (regex.test(text)) {
                const highlightedText = text.replace(regex, '<span class="search-highlight">$1</span>');
                const wrapper = document.createElement('span');
                wrapper.innerHTML = highlightedText;
                node.parentNode.replaceChild(wrapper, node);
            }
        });
    }

    removeHighlights(row) {
        const highlights = row.querySelectorAll('.search-highlight');
        highlights.forEach(highlight => {
            const parent = highlight.parentNode;
            parent.replaceChild(document.createTextNode(highlight.textContent), highlight);
            parent.normalize();
        });
    }

    getTextNodes(element) {
        const textNodes = [];
        const walker = document.createTreeWalker(
            element,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: (node) => {
                    // Ignorer les nœuds dans les éléments interactifs
                    const parent = node.parentElement;
                    if (parent && (parent.tagName === 'BUTTON' || parent.tagName === 'A')) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    return node.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
                }
            }
        );

        let node;
        while (node = walker.nextNode()) {
            textNodes.push(node);
        }
        return textNodes;
    }

    escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    updateSearchResults(tableType) {
        const resultsElement = document.getElementById(`${tableType}-search-results`);
        if (resultsElement) {
            const count = this.searchResults[tableType];
            const term = this.searchTerms[tableType];
            
            if (term) {
                resultsElement.textContent = `${count} résultat${count !== 1 ? 's' : ''}`;
                resultsElement.style.display = 'block';
            } else {
                resultsElement.style.display = 'none';
            }
        }
    }

    // === RACCOURCIS CLAVIER ===

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + K pour ouvrir la recherche
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                this.focusFirstSearchInput();
            }
            
            // Ctrl/Cmd + Shift + T pour toggle le thème
            if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'T') {
                e.preventDefault();
                this.toggleTheme();
            }
            
            // Escape pour clear la recherche active
            if (e.key === 'Escape') {
                const activeSearch = document.activeElement;
                if (activeSearch && activeSearch.classList.contains('search-input')) {
                    activeSearch.value = '';
                    const tableType = activeSearch.id.includes('activity') ? 'activity' : 'wallets';
                    this.handleSearch(tableType, '');
                    activeSearch.blur();
                }
            }
        });

        console.log('⌨️ [SHORTCUTS] Keyboard shortcuts setup complete');
        console.log('⌨️ [SHORTCUTS] Available shortcuts:');
        console.log('   • Ctrl+K: Focus search');
        console.log('   • Ctrl+Shift+T: Toggle theme');
        console.log('   • Escape: Clear active search');
    }

    focusFirstSearchInput() {
        const firstSearch = document.querySelector('.search-input');
        if (firstSearch) {
            firstSearch.focus();
            firstSearch.select();
        }
    }

    // === MÉTHODES PUBLIQUES ===

    clearAllSearches() {
        ['activity', 'wallets'].forEach(tableType => {
            const input = document.getElementById(`${tableType}-search`);
            if (input) {
                input.value = '';
                this.handleSearch(tableType, '');
            }
        });
        console.log('🧹 [SEARCH] All searches cleared');
    }

    getCurrentTheme() {
        return this.currentTheme;
    }

    getSearchStats() {
        return {
            terms: this.searchTerms,
            results: this.searchResults
        };
    }
}

// Initialiser les fonctionnalités quand le DOM est prêt
let dashboardFeatures = null;

document.addEventListener('DOMContentLoaded', () => {
    // Attendre un peu pour que les autres scripts se chargent
    setTimeout(() => {
        dashboardFeatures = new DashboardFeatures();
        
        // Exposer globalement pour le debug
        window.dashboardFeatures = dashboardFeatures;
        
        console.log('✅ [FEATURES] Dashboard features ready');
    }, 100);
});

// Exposer certaines fonctions globalement pour l'usage dans le HTML
window.toggleTheme = () => dashboardFeatures?.toggleTheme();
window.clearAllSearches = () => dashboardFeatures?.clearAllSearches();