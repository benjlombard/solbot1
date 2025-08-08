
#!/usr/bin/env python3
"""
Constantes globales pour le Solana Wallet Monitor
Centralise toutes les constantes hardcodées et les valeurs par défaut
"""

from typing import Dict, List, Tuple
import re

# =============================================================================
# CONSTANTES SOLANA BLOCKCHAIN
# =============================================================================

# Programme IDs Solana officiels
SOLANA_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SOLANA_ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SOLANA_SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
SOLANA_SYSVAR_RENT_ID = "SysvarRent111111111111111111111111111111111"

# Adresses spéciales
SOLANA_NATIVE_MINT = "So11111111111111111111111111111111111111112"  # Wrapped SOL
SOLANA_NULL_ADDRESS = "11111111111111111111111111111111111111111111"

# Tailles et formats
SOLANA_ADDRESS_LENGTH = 44  # Longueur standard d'une adresse Solana en base58
SOLANA_SIGNATURE_LENGTH = 88  # Longueur d'une signature de transaction
SOLANA_PUBKEY_BYTES = 32  # Taille d'une clé publique en bytes

# Valeurs blockchain
LAMPORTS_PER_SOL = 1_000_000_000  # 1 SOL = 1 milliard de lamports
DEFAULT_TOKEN_DECIMALS = 9
MIN_RENT_EXEMPT_BALANCE = 0.00203928  # SOL minimum pour exemption de loyer

# Seuils de détection
SOL_CHANGE_THRESHOLD = 0.001  # Seuil minimum pour détecter un changement SOL significatif
MIN_TOKEN_BALANCE_THRESHOLD = 0.000001  # Balance minimum pour considérer un token comme actif
DUST_THRESHOLD = 0.0000001  # Seuil en-dessous duquel on ignore les montants


# =============================================================================
# CONSTANTES RÉSEAU ET RPC
# =============================================================================

# Endpoints RPC publics par défaut (fallback)
DEFAULT_RPC_ENDPOINTS = [
    "https://api.mainnet-beta.solana.com",
    "https://rpc.ankr.com/solana", 
    "https://solana.public-rpc.com",
    "https://solana-api.projectserum.com"
]

# Configuration timeouts
DEFAULT_RPC_TIMEOUT = 15  # secondes
DEFAULT_CONNECTION_TIMEOUT = 10  # secondes
BATCH_RPC_TIMEOUT = 25  # secondes pour les requêtes batch
CRITICAL_RPC_TIMEOUT = 30  # timeout pour les requêtes critiques

# Rate limiting
DEFAULT_REQUESTS_PER_SECOND = 5
QUICKNODE_FREE_RPS_LIMIT = 100  # Limite théorique QuickNode free
BURST_REQUESTS_LIMIT = 20  # Nombre max de requêtes en burst
COOLDOWN_AFTER_RATE_LIMIT = 60  # Attente après rate limit (secondes)

# Retry configuration
MAX_RPC_RETRIES = 3
RETRY_EXPONENTIAL_BASE = 2
RETRY_MAX_DELAY = 30  # secondes
RETRY_JITTER_MAX = 2  # secondes de jitter aléatoire


# =============================================================================
# CONSTANTES BATCHING ET PERFORMANCE
# =============================================================================

# Tailles de batch optimales par méthode
OPTIMAL_BATCH_SIZES = {
    'getMultipleAccounts': 100,  # Taille max théorique
    'getSignaturesForAddress': 20,  # Limite Solana native
    'getTransaction': 10,  # Requêtes lourdes
    'getTokenAccountsByOwner': 1,  # Pas de batching supporté
    'token_metadata': 15,  # API externes
    'custom_batch': 50  # Batches personnalisés
}

# Tailles conservatrices pour plans gratuits
CONSERVATIVE_BATCH_SIZES = {
    'getMultipleAccounts': 8,
    'getSignaturesForAddress': 12,
    'getTransaction': 6,
    'token_metadata': 5,
    'custom_batch': 20
}

# Seuils de performance
PERFORMANCE_THRESHOLDS = {
    'response_time_good': 1000,  # ms
    'response_time_warning': 5000,  # ms
    'response_time_critical': 15000,  # ms
    'success_rate_good': 95,  # %
    'success_rate_warning': 80,  # %
    'success_rate_critical': 60,  # %
    'efficiency_good': 0.5,  # découvertes/requête
    'efficiency_warning': 0.2,
    'efficiency_critical': 0.1
}

# Intervalles adaptatifs
ADAPTIVE_INTERVALS = {
    'high_activity': 30,  # secondes entre scans si haute activité
    'medium_activity': 90,
    'low_activity': 180,
    'no_activity': 300,
    'error_recovery': 120
}


# =============================================================================
# CONSTANTES DÉTECTION ET CLASSIFICATION
# =============================================================================

# Classification des montants de tokens
LARGE_TOKEN_AMOUNT_THRESHOLDS = {
    'high_decimals': {  # Tokens avec 9+ decimals
        'threshold': 100_000,
        'mega_threshold': 1_000_000
    },
    'medium_decimals': {  # Tokens avec 6-8 decimals  
        'threshold': 1_000,
        'mega_threshold': 10_000
    },
    'low_decimals': {  # Tokens avec 0-5 decimals
        'threshold': 10,
        'mega_threshold': 100
    }
}

# Classification des types de transaction
TRANSACTION_TYPES = {
    'BUY': 'buy',
    'SELL': 'sell', 
    'TRANSFER_IN': 'transfer_in',
    'TRANSFER_OUT': 'transfer_out',
    'SWAP': 'swap',
    'STAKE': 'stake',
    'UNSTAKE': 'unstake',
    'LIQUIDITY_ADD': 'liquidity_add',
    'LIQUIDITY_REMOVE': 'liquidity_remove',
    'OTHER': 'other',
    'UNKNOWN': 'unknown'
}

# Statuts de transaction
TRANSACTION_STATUSES = {
    'SUCCESS': 'success',
    'FAILED': 'failed',
    'PENDING': 'pending',
    'TIMEOUT': 'timeout',
    'CANCELLED': 'cancelled'
}

# Priorités de scan des comptes
SCAN_PRIORITIES = {
    'NEVER_SCANNED': 5,  # Jamais scanné = priorité max
    'NEW_ACCOUNT': 4,    # Nouveau compte
    'HIGH_ACTIVITY': 3,   # Activité récente détectée
    'NORMAL': 2,         # Scan normal
    'LOW': 1,            # Priorité basse
    'INACTIVE': 0        # Compte inactif
}


# =============================================================================
# CONSTANTES MÉTADONNÉES ET CACHE
# =============================================================================

# URLs des APIs de métadonnées
METADATA_PROVIDERS = {
    'jupiter': {
        'url': 'https://token.jup.ag/all',
        'timeout': 10,
        'cache_ttl': 3600,  # 1 heure
        'retry_count': 2
    },
    'solana_token_list': {
        'url': 'https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json',
        'timeout': 15,
        'cache_ttl': 7200,  # 2 heures
        'retry_count': 3
    }
}

# Configuration cache
CACHE_SETTINGS = {
    'token_metadata': {
        'ttl': 3600,  # 1 heure
        'max_size': 10000,
        'cleanup_interval': 1800  # 30 minutes
    },
    'wallet_stats': {
        'ttl': 300,   # 5 minutes
        'max_size': 1000,
        'cleanup_interval': 600
    },
    'rpc_responses': {
        'ttl': 60,    # 1 minute pour les réponses RPC
        'max_size': 5000,
        'cleanup_interval': 300
    }
}

# Fallback token info
DEFAULT_TOKEN_INFO = {
    'symbol': 'UNKNOWN',
    'name': 'Unknown Token',
    'decimals': 9,
    'logo_uri': None,
    'coingecko_id': None,
    'price_usd': 0.0
}

# Format des symboles de fallback
FALLBACK_TOKEN_SYMBOL_FORMAT = "TOKEN_{mint_short}"  # TOKEN_ABC123
FALLBACK_TOKEN_NAME_FORMAT = "Token {mint_short}"    # Token ABC123


# =============================================================================
# CONSTANTES BASE DE DONNÉES
# =============================================================================

# Configuration SQLite
SQLITE_SETTINGS = {
    'timeout': 30.0,
    'check_same_thread': False,
    'journal_mode': 'WAL',
    'synchronous': 'NORMAL',
    'busy_timeout': 30000,
    'cache_size': -64000,  # 64MB
    'page_size': 4096
}

# Limites de requêtes
DB_QUERY_LIMITS = {
    'transactions': 1000,
    'token_accounts': 500,
    'scan_history': 100,
    'wallet_priorities': 50,
    'default': 100
}

# Intervalles de nettoyage
CLEANUP_INTERVALS = {
    'old_transactions': 30,  # jours
    'old_scan_history': 7,   # jours
    'old_metrics': 7,        # jours
    'old_logs': 14,          # jours
    'cache_cleanup': 1800    # secondes (30min)
}

# Index de performance critiques
CRITICAL_INDEXES = [
    "idx_transactions_wallet_time",
    "idx_token_accounts_wallet", 
    "idx_wallet_priorities_score",
    "idx_scan_history_wallet"
]


# =============================================================================
# CONSTANTES LOGGING ET MONITORING
# =============================================================================

# Emojis et icônes pour les logs
LOG_ICONS = {
    # États généraux
    'success': '✅',
    'error': '❌', 
    'warning': '⚠️',
    'info': 'ℹ️',
    'debug': '🔍',
    'critical': '🚨',
    
    # Activités spécifiques
    'scan': '🔍',
    'discovery': '🆕',
    'transaction': '💰',
    'batch': '📦',
    'priority': '🎯',
    'wallet': '👛',
    'token': '🪙',
    'rpc': '🔌',
    'database': '💾',
    'cache': '🗄️',
    
    # Performance
    'fast': '⚡',
    'slow': '🐌',
    'optimization': '🚀',
    'monitoring': '📊',
    
    # Système
    'start': '🎬',
    'stop': '🛑',
    'pause': '⏸️',
    'restart': '🔄',
    'config': '🔧',
    'security': '🔒',
    
    # Résultats
    'profit': '📈',
    'loss': '📉',
    'neutral': '➡️',
    'large': '🔥',
    'empty': '🔵'
}

# Formats de log standardisés
LOG_FORMATS = {
    'cycle_start': "🧠 CYCLE INTELLIGENT #{cycle} - {timestamp}",
    'cycle_end': "✅ CYCLE #{cycle} TERMINÉ - Durée: {duration}s",
    'wallet_selected': "🎯 WALLET SÉLECTIONNÉ: {wallet_short}",
    'discovery_result': "📊 Découverte: {total} comptes ({new} nouveaux)",
    'balance_change': "💰 Balance change: {type} {amount} {symbol}",
    'priority_update': "{icon} Priorité: {old} → {new} ({change:+.2f})",
    'batch_result': "📦 Batch {method}: {count} items en {duration:.2f}s",
    'rpc_error': "❌ Erreur RPC {method}: {error}",
    'performance': "📊 Performance - RPS: {rps:.1f}, Succès: {success_rate:.1f}%"
}

# Niveaux de log personnalisés
CUSTOM_LOG_LEVELS = {
    'DISCOVERY': 25,  # Entre INFO(20) et WARNING(30)
    'TRANSACTION': 25,
    'PERFORMANCE': 35,  # Entre WARNING(30) et ERROR(40)
    'BATCH': 15        # Entre DEBUG(10) et INFO(20)
}


# =============================================================================
# CONSTANTES VALIDATION ET SÉCURITÉ
# =============================================================================

# Patterns de validation
VALIDATION_PATTERNS = {
    'solana_address': re.compile(r'^[1-9A-HJ-NP-Za-km-z]{44}$'),  # Base58, 44 chars
    'solana_signature': re.compile(r'^[1-9A-HJ-NP-Za-km-z]{88}$'),  # Base58, 88 chars
    'token_symbol': re.compile(r'^[A-Z][A-Z0-9_]{1,10}$'),  # Symbole token valide
    'cycle_id': re.compile(r'^cycle_\d+_\d+$'),  # Format cycle_123_timestamp
}

# Limites de sécurité
SECURITY_LIMITS = {
    'max_wallets_per_instance': 1000,
    'max_tokens_per_wallet': 50000,
    'max_transactions_per_scan': 10000,
    'max_batch_size': 100,
    'max_concurrent_scans': 5,
    'max_memory_usage_mb': 2048,
    'max_log_file_size_mb': 100
}

# Blacklists et filtres
SECURITY_FILTERS = {
    'blocked_token_mints': [
        # Ajouter ici les mints de tokens malicieux connus
    ],
    'blocked_program_ids': [
        # Ajouter ici les program IDs suspects
    ],
    'suspicious_patterns': [
        'honeypot',
        'scam',
        'fake',
        'rug'
    ]
}


# =============================================================================
# CONSTANTES API ET DASHBOARD
# =============================================================================

# Configuration CORS
CORS_SETTINGS = {
    'origins': ['http://localhost:3000', 'http://127.0.0.1:5000'],
    'methods': ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    'allow_headers': ['Content-Type', 'Authorization', 'X-Requested-With']
}

# Limites API
API_LIMITS = {
    'requests_per_minute': 1000,
    'requests_per_hour': 10000,
    'max_page_size': 500,
    'default_page_size': 50,
    'max_concurrent_requests': 10
}

# Statuts HTTP personnalisés
CUSTOM_HTTP_STATUS = {
    'WALLET_NOT_FOUND': 404,
    'INVALID_WALLET_ADDRESS': 400,
    'RPC_ERROR': 502,
    'RATE_LIMIT_EXCEEDED': 429,
    'MAINTENANCE_MODE': 503
}

# Headers de réponse standardisés
RESPONSE_HEADERS = {
    'X-Monitor-Version': '2.0.0',
    'X-RateLimit-Remaining': 'X-RateLimit-Remaining',
    'X-RateLimit-Reset': 'X-RateLimit-Reset',
    'X-Response-Time': 'X-Response-Time'
}


# =============================================================================
# CONSTANTES ALERTES ET NOTIFICATIONS
# =============================================================================

# Types d'alertes
ALERT_TYPES = {
    'NEW_LARGE_TRANSACTION': 'new_large_transaction',
    'NEW_TOKEN_DISCOVERED': 'new_token_discovered', 
    'WALLET_HIGH_ACTIVITY': 'wallet_high_activity',
    'SYSTEM_ERROR': 'system_error',
    'PERFORMANCE_DEGRADATION': 'performance_degradation',
    'RPC_ENDPOINT_DOWN': 'rpc_endpoint_down'
}

# Seuils d'alerte
ALERT_THRESHOLDS = {
    'large_transaction_sol': 10.0,
    'large_transaction_tokens': 100000,
    'high_activity_tx_per_hour': 50,
    'performance_degradation_pct': 50,  # 50% de dégradation
    'error_rate_critical': 25,  # 25% d'erreurs
    'response_time_critical': 30000  # 30 secondes
}

# Niveaux de priorité des alertes
ALERT_PRIORITIES = {
    'LOW': 1,
    'MEDIUM': 2, 
    'HIGH': 3,
    'CRITICAL': 4,
    'EMERGENCY': 5
}


# =============================================================================
# CONSTANTES TESTS ET DÉVELOPPEMENT
# =============================================================================

# Configuration test
TEST_SETTINGS = {
    'mock_rpc_responses': True,
    'mock_delay_ms': 100,
    'test_wallet_addresses': [
        '4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh',  # Test wallet 1
        'AVAZvHLR2PcWpDf8BXY4rVxNHYRBytycHkcB5z5QNXYm'   # Test wallet 2
    ],
    'test_token_mints': [
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
        'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'   # USDT
    ]
}

# Données de test
MOCK_DATA = {
    'sample_transaction': {
        'signature': '5VhKQ3a4j1pK6xWyVSCpXs7TnK4Q8M2pHqF8jE5rXoZ3kYpWnQ7dL6hFcKtN8rVmEwP2zQ5dMqS9tYpL3rVkXqW',
        'slot': 123456789,
        'block_time': 1640995200,
        'fee': 0.000005,
        'status': 'success'
    },
    'sample_token': {
        'mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
        'symbol': 'USDC',
        'name': 'USD Coin',
        'decimals': 6,
        'price_usd': 1.0
    }
}


# =============================================================================
# HELPERS ET FONCTIONS UTILITAIRES
# =============================================================================

def get_icon_for_log_type(log_type: str) -> str:
    """Retourne l'icône appropriée pour un type de log"""
    return LOG_ICONS.get(log_type, LOG_ICONS['info'])


def format_wallet_address(address: str, length: int = 8) -> str:
    """Formate une adresse de wallet pour l'affichage"""
    if not address or len(address) < length * 2:
        return address
    return f"{address[:length]}...{address[-length:]}"


def format_token_mint(mint: str, length: int = 6) -> str:
    """Formate une adresse de mint pour l'affichage"""
    if not mint or len(mint) < length * 2:
        return mint
    return f"{mint[:length]}...{mint[-length:]}"


def format_signature(signature: str, length: int = 16) -> str:
    """Formate une signature de transaction pour l'affichage"""
    if not signature or len(signature) < length:
        return signature
    return f"{signature[:length]}..."


def get_fallback_token_symbol(mint_address: str) -> str:
    """Génère un symbole de token de fallback"""
    if not mint_address:
        return "UNKNOWN"
    return FALLBACK_TOKEN_SYMBOL_FORMAT.format(mint_short=mint_address[:6].upper())


def get_fallback_token_name(mint_address: str) -> str:
    """Génère un nom de token de fallback"""
    if not mint_address:
        return "Unknown Token" 
    return FALLBACK_TOKEN_NAME_FORMAT.format(mint_short=mint_address[:6].upper())


def is_large_token_amount(amount: float, decimals: int) -> bool:
    """Détermine si un montant de token est considéré comme important"""
    if decimals >= 9:
        threshold_config = LARGE_TOKEN_AMOUNT_THRESHOLDS['high_decimals']
    elif decimals >= 6:
        threshold_config = LARGE_TOKEN_AMOUNT_THRESHOLDS['medium_decimals']
    else:
        threshold_config = LARGE_TOKEN_AMOUNT_THRESHOLDS['low_decimals']
    
    return amount >= threshold_config['threshold']


def get_scan_priority_name(priority_level: int) -> str:
    """Retourne le nom d'un niveau de priorité de scan"""
    for name, level in SCAN_PRIORITIES.items():
        if level == priority_level:
            return name.lower().replace('_', ' ')
    return f"custom_{priority_level}"

def get_adaptive_interval(activity_level: str) -> int:
    """Retourne l'intervalle adaptatif selon le niveau d'activité"""
    return ADAPTIVE_INTERVALS.get(activity_level, ADAPTIVE_INTERVALS['no_activity'])


def get_performance_status(metric_name: str, value: float) -> str:
    """Détermine le statut de performance d'une métrique"""
    thresholds = PERFORMANCE_THRESHOLDS
    
    if metric_name == 'response_time':
        if value <= thresholds['response_time_good']:
            return 'good'
        elif value <= thresholds['response_time_warning']:
            return 'warning'
        else:
            return 'critical'
    elif metric_name == 'success_rate':
        if value >= thresholds['success_rate_good']:
            return 'good'
        elif value >= thresholds['success_rate_warning']:
            return 'warning'
        else:
            return 'critical'
    elif metric_name == 'efficiency':
        if value >= thresholds['efficiency_good']:
            return 'good'
        elif value >= thresholds['efficiency_warning']:
            return 'warning'
        else:
            return 'critical'
    
    return 'unknown'


# Version et informations système
SYSTEM_INFO = {
    'version': '2.0.0',
    'codename': 'BatchOptimized',
    'build_date': '2024-01-15',
    'author': 'Solana Wallet Monitor Team',
    'license': 'MIT',
    'min_python_version': '3.8.0',
    'supported_platforms': ['linux', 'darwin', 'win32']
}

# Export des constantes principales pour faciliter l'import
__all__ = [
    # Blockchain
    'SOLANA_TOKEN_PROGRAM_ID', 'LAMPORTS_PER_SOL', 'DEFAULT_TOKEN_DECIMALS',
    'SOL_CHANGE_THRESHOLD', 'MIN_TOKEN_BALANCE_THRESHOLD',
    
    # RPC et réseau
    'DEFAULT_RPC_ENDPOINTS', 'DEFAULT_RPC_TIMEOUT', 'MAX_RPC_RETRIES',
    'QUICKNODE_FREE_RPS_LIMIT',
    
    # Batching
    'OPTIMAL_BATCH_SIZES', 'CONSERVATIVE_BATCH_SIZES', 'PERFORMANCE_THRESHOLDS',
    
    # Classification
    'TRANSACTION_TYPES', 'TRANSACTION_STATUSES', 'SCAN_PRIORITIES',
    
    # Logging
    'LOG_ICONS', 'LOG_FORMATS', 'CUSTOM_LOG_LEVELS',
    
    # Validation
    'VALIDATION_PATTERNS', 'SECURITY_LIMITS',
    
    # API
    'API_LIMITS', 'CUSTOM_HTTP_STATUS',
    
    # Helpers
    'format_wallet_address', 'format_token_mint',
    'is_large_token_amount', 'get_performance_status', 'get_icon_for_log_type'
]
