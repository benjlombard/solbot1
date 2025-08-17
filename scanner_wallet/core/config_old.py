
#!/usr/bin/env python3
"""
Configuration centralisée pour le Solana Wallet Monitor v2.0
Système de configuration hiérarchique avec validation, environnements multiples et extensibilité
"""

import os
import json
import threading
from typing import List, Dict, Any, Optional, Union, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import logging


def validate_wallet_address(addr: str) -> bool:
    """
    Validation d'adresse Solana avec fallback robuste
    """
    if not isinstance(addr, str):
        return False
    
    # Validation de base : longueur
    if len(addr) < 32 or len(addr) > 44:
        return False
    
    # Validation base58 (caractères autorisés)
    base58_alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    if not all(c in base58_alphabet for c in addr):
        return False
    
    # Tentative de validation avec base58 si disponible
    try:
        import base58
        try:
            decoded = base58.b58decode(addr)
            return len(decoded) == 32  # Les clés publiques Solana font 32 bytes
        except Exception:
            return False
    except ImportError:
        # Fallback sans base58 : validation basique
        return len(addr) >= 32 and len(addr) <= 44 and addr.isalnum()

def sanitize_filename(name: str) -> str:
    """Sanitise un nom de fichier"""
    if not isinstance(name, str):
        return "unnamed"
    return "".join(c for c in name if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()

# Constantes par défaut
DEFAULT_RPC_ENDPOINTS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana.public-rpc.com"
]

SOLANA_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_TOKEN_DECIMALS = 9

class ConfigurationError(Exception):
    """Exception levée lors d'erreurs de configuration"""
    pass

# Import des utilitaires (avec fallbacks)
# try:
#     from utils.helpers import sanitize_filename
#     from utils.validators import quick_validate_address as validate_wallet_address
#     from utils.constants import (
#         DEFAULT_RPC_ENDPOINTS, SOLANA_TOKEN_PROGRAM_ID, 
#         LAMPORTS_PER_SOL, DEFAULT_TOKEN_DECIMALS
#     )
#     from core.exceptions import ConfigurationError
# except ImportError:
#     # Fallbacks si les modules ne sont pas encore disponibles
#     import logging
#     def validate_wallet_address(addr):
#         logging.getLogger('config').warning("Using fallback address validator for %s", addr)
#         if not isinstance(addr, str):
#             return False
#         # Validation Solana plus stricte
#         if len(addr) < 32 or len(addr) > 44:
#             return False
#         # Vérifier que c'est une base58 valide
#         try:
#             import base58
#             base58.b58decode(addr)
#             return True
#         except:
#             # Fallback basique si base58 pas disponible
#             return addr.isalnum() and len(addr) >= 32
    
#     def sanitize_filename(name):
#         return "".join(c for c in name if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    
    # DEFAULT_RPC_ENDPOINTS = [
    #     "https://api.mainnet-beta.solana.com",
    #     "https://rpc.ankr.com/solana",
    #     "https://solana.public-rpc.com"
    # ]
    
    # class ConfigurationError(Exception):
    #     pass


# =============================================================================
# ENUMS ET CONSTANTES DE CONFIGURATION
# =============================================================================

class Environment(Enum):
    """Environnements supportés"""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"
    STAGING = "staging"


class WalletSelectionMode(Enum):
    """Modes de sélection des wallets"""
    PRIORITY = "priority"
    RANDOM = "random"
    ROUND_ROBIN = "round_robin"
    WEIGHTED_RANDOM = "weighted_random"


class LogLevel(Enum):
    """Niveaux de logging"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# =============================================================================
# DATACLASSES DE CONFIGURATION
# =============================================================================

@dataclass
class WalletConfig:
    """Configuration des wallets à surveiller"""
    addresses: List[str] = field(default_factory=list)
    primary_address: Optional[str] = None
    selection_mode: WalletSelectionMode = WalletSelectionMode.PRIORITY
    random_selection_weight_by_priority: bool = False
    min_interval_between_scans: int = 45
    random_selection_cooldown: int = 300
    max_wallets_per_instance: int = 1000
    
    def __post_init__(self):
        """Validation et initialisation post-création"""
        if not self.addresses:
            raise ConfigurationError("Au moins une adresse de wallet est requise")
            
        if not all(isinstance(addr, str) for addr in self.addresses):
            raise ConfigurationError("Toutes les adresses doivent être des strings")
        
        # Valider toutes les adresses
        invalid_addresses = [addr for addr in self.addresses if not validate_wallet_address(addr)]
        if invalid_addresses:
            raise ConfigurationError(f"Adresses de wallet invalides: {invalid_addresses}")
        
        # Définir l'adresse primaire si non spécifiée
        if not self.primary_address:
            self.primary_address = self.addresses[0]
        
        # Valider l'adresse primaire
        if self.primary_address not in self.addresses:
            raise ConfigurationError("L'adresse primaire doit être dans la liste des adresses")


@dataclass
class RPCConfig:
    """Configuration des endpoints RPC"""
    quicknode_endpoint: Optional[str] = None
    quicknode_api_key: Optional[str] = None
    fallback_endpoints: List[str] = field(default_factory=lambda: DEFAULT_RPC_ENDPOINTS.copy())
    timeout: int = 20
    connection_timeout: int = 10
    max_retries: int = 3
    retry_delay: int = 2
    requests_per_minute: int = 100
    error_backoff_multiplier: float = 1.2
    pool_connections: int = 10      # Nombre de pools de connexions
    pool_maxsize: int = 20         # Taille max de chaque pool
    session_timeout: float = 30.0  # Timeout par défaut des sessions
    keep_alive: bool = True        # Forcer keep-alive
    
    def get_all_endpoints(self) -> List[str]:
        """Retourne tous les endpoints dans l'ordre de priorité"""
        endpoints = []
        if self.quicknode_endpoint:
            endpoints.append(self.quicknode_endpoint)
        endpoints.extend(self.fallback_endpoints)
        return list(dict.fromkeys(endpoints))  # Supprimer les doublons en gardant l'ordre
    
    def get_headers(self) -> Dict[str, str]:
        """Retourne les headers pour les requêtes RPC"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'SolanaWalletMonitor/2.0-Modular',
            'Accept': 'application/json',
        }
        
        if self.quicknode_api_key:
            headers['Authorization'] = f'Bearer {self.quicknode_api_key}'
        
        return headers


@dataclass
class BatchingConfig:
    """Configuration du système de batching RPC"""
    enabled: bool = True
    adaptive_sizing: bool = True
    min_delay_between_batches: float = 0.3
    max_concurrent_batches: int = 1
    batch_timeout: int = 25
    
    # Tailles de batch par méthode
    batch_sizes: Dict[str, int] = field(default_factory=lambda: {
        'getMultipleAccounts': 8,
        'token_metadata': 5,
        'signatures_batch': 12,
        'transactions_batch': 6
    })
    
    # Monitoring des performances
    track_response_times: bool = True
    max_acceptable_response_time: int = 8000  # ms
    reduce_batch_size_threshold: int = 5000   # ms
    emergency_fallback_threshold: int = 15000 # ms


@dataclass
class MonitoringConfig:
    """Configuration du monitoring et scanning"""
    update_interval: int = 45
    full_scan_interval_hours: int = 6
    rate_limit_delay: float = 0.2
    token_discovery_batch_size: int = 50
    pause_between_tx_details: float = 0.1
    max_consecutive_errors: int = 3
    large_transaction_threshold: float = 1.0
    default_transaction_limit: int = 35
    max_transaction_limit: int = 100


@dataclass
class DatabaseConfig:
    """Configuration de la base de données"""
    name: str = "solana_wallet.db"
    path: Optional[str] = None
    timeout: float = 30.0
    max_connections: int = 10
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    cleanup_old_data_days: int = 30
    
    def get_full_path(self) -> str:
        """Retourne le chemin complet de la base de données"""
        if self.path:
            return str(Path(self.path) / self.name)
        return self.name


@dataclass
class LoggingConfig:
    """Configuration du système de logging"""
    level: LogLevel = LogLevel.INFO
    file_path: str = "wallet_monitor.log"
    console_output: bool = True
    json_output: bool = False
    max_file_size_mb: int = 10
    backup_count: int = 5
    max_age_days: int = 7
    rate_limit_enabled: bool = True
    rate_limit_max_per_minute: int = 120


@dataclass
class FlaskConfig:
    """Configuration du serveur Flask/API"""
    host: str = '127.0.0.1'
    port: int = 5000
    debug: bool = True
    cors_enabled: bool = True
    cors_origins: List[str] = field(default_factory=lambda: ['http://localhost:3000', 'http://127.0.0.1:5000'])
    api_rate_limit_enabled: bool = True
    api_rate_limit_per_minute: int = 1000
    api_rate_limit_per_hour: int = 10000


@dataclass
class AlertingConfig:
    """Configuration du système d'alertes"""
    enabled: bool = False
    slack_webhook_url: Optional[str] = None
    email_enabled: bool = False
    email_smtp_server: Optional[str] = None
    email_smtp_port: int = 587
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    email_recipients: List[str] = field(default_factory=list)
    alert_thresholds: Dict[str, Union[int, float]] = field(default_factory=lambda: {
        'large_transaction_sol': 10.0,
        'large_transaction_tokens': 100000,
        'high_activity_tx_per_hour': 50,
        'error_rate_critical': 25,  # %
        'response_time_critical': 30000  # ms
    })


# =============================================================================
# CLASSE PRINCIPALE DE CONFIGURATION
# =============================================================================

class SolanaWalletConfig:
    """Configuration principale du Solana Wallet Monitor"""
    
    def __init__(self, environment: Union[Environment, str] = Environment.DEVELOPMENT):
        self.environment = Environment(environment) if isinstance(environment, str) else environment
        
        # Initialiser les sous-configurations
        self.wallet = self._load_wallet_config()
        self.rpc = self._load_rpc_config()
        self.batching = self._load_batching_config()
        self.monitoring = self._load_monitoring_config()
        self.database = self._load_database_config()
        self.logging = self._load_logging_config()
        self.flask = self._load_flask_config()
        self.alerting = self._load_alerting_config()
        
        # Appliquer les ajustements spécifiques à l'environnement
        self._apply_environment_overrides()
        
        # Validation finale
        self._validate_configuration()
    
    def _load_wallet_config(self) -> WalletConfig:
        """Charge la configuration des wallets"""
        # Récupérer les adresses depuis les variables d'environnement
        addresses = self._get_wallet_addresses()
        
        return WalletConfig(
            addresses=addresses,
            selection_mode=WalletSelectionMode(os.getenv('WALLET_SELECTION_MODE', 'priority')),
            random_selection_weight_by_priority=self._get_bool_env('RANDOM_SELECTION_WEIGHT_BY_PRIORITY', False),
            min_interval_between_scans=int(os.getenv('MIN_INTERVAL_BETWEEN_SCANS', 30)),
            random_selection_cooldown=int(os.getenv('RANDOM_SELECTION_COOLDOWN', 300))
        )
    
    def _get_wallet_addresses(self) -> List[str]:
        """Récupère et valide la liste des adresses de wallets"""
        # Mode test
        if self._get_bool_env('TEST_MODE', False):
            test_wallet = os.getenv('TEST_WALLET')
            if test_wallet and validate_wallet_address(test_wallet):
                print(f"🧪 MODE TEST activé - Wallet: {test_wallet[:8]}...{test_wallet[-8:]}")
                return [test_wallet]
        
        # Wallet par défaut
        default_wallet = 'AVAZvHLR2PcWpDf8BXY4rVxNHYRBytycHkcB5z5QNXYm'
        
        # Récupérer depuis les variables d'environnement
        wallets_str = os.getenv('WALLET_ADDRESSES', default_wallet)
        
        if not wallets_str:
            return [default_wallet]
        
        try:
            # Traitement de la chaîne
            wallets = [wallet.strip() for wallet in wallets_str.split(',') if wallet.strip()]
            
            # Validation des adresses
            valid_wallets = []
            for wallet in wallets:
                if validate_wallet_address(wallet):
                    valid_wallets.append(wallet)
                else:
                    print(f"⚠️ Wallet invalide ignoré: {wallet}")
            
            if valid_wallets:
                print(f"✅ {len(valid_wallets)} wallet(s) chargé(s)")
                for i, wallet in enumerate(valid_wallets):
                    print(f"   {i+1}. {wallet[:8]}...{wallet[-8:]}")
                return valid_wallets
            else:
                print("⚠️ Aucun wallet valide trouvé, utilisation du wallet par défaut")
                return [default_wallet]
        
        except Exception as e:
            print(f"❌ Erreur traitement WALLET_ADDRESSES: {e}")
            return [default_wallet]
    
    def _load_rpc_config(self) -> RPCConfig:
        """Charge la configuration RPC"""
        return RPCConfig(
            quicknode_endpoint=os.getenv('QUICKNODE_ENDPOINT'),
            quicknode_api_key=os.getenv('QUICKNODE_API_KEY'),
            timeout=int(os.getenv('RPC_TIMEOUT', 20)),
            connection_timeout=int(os.getenv('CONNECTION_TIMEOUT', 10)),
            max_retries=int(os.getenv('MAX_RETRIES', 3)),
            retry_delay=int(os.getenv('RETRY_DELAY', 2)),
            requests_per_minute=int(os.getenv('REQUESTS_PER_MINUTE', 100))
        )
    
    def _load_batching_config(self) -> BatchingConfig:
        """Charge la configuration du batching"""
        # Charger les tailles de batch personnalisées si disponibles
        batch_sizes = {}
        for method in ['getMultipleAccounts', 'token_metadata', 'signatures_batch', 'transactions_batch']:
            env_key = f'BATCH_SIZE_{method.upper()}'
            if os.getenv(env_key):
                try:
                    batch_sizes[method] = int(os.getenv(env_key))
                except ValueError:
                    pass
        
        config = BatchingConfig(
            enabled=self._get_bool_env('ENABLE_RPC_BATCHING', True),
            adaptive_sizing=self._get_bool_env('BATCH_ADAPTIVE_SIZING', True),
            min_delay_between_batches=float(os.getenv('MIN_DELAY_BETWEEN_BATCHES', 0.3)),
            batch_timeout=int(os.getenv('BATCH_TIMEOUT', 25))
        )
        
        # Appliquer les tailles personnalisées
        if batch_sizes:
            config.batch_sizes.update(batch_sizes)
        
        return config
    
    def _load_monitoring_config(self) -> MonitoringConfig:
        """Charge la configuration du monitoring"""
        return MonitoringConfig(
            update_interval=int(os.getenv('UPDATE_INTERVAL', 45)),
            full_scan_interval_hours=int(os.getenv('FULL_SCAN_INTERVAL_HOURS', 6)),
            rate_limit_delay=float(os.getenv('RATE_LIMIT_DELAY', 0.2)),
            token_discovery_batch_size=int(os.getenv('TOKEN_DISCOVERY_BATCH_SIZE', 50)),
            max_consecutive_errors=int(os.getenv('MAX_CONSECUTIVE_ERRORS', 3)),
            large_transaction_threshold=float(os.getenv('ALERT_THRESHOLD', 1.0)),
            default_transaction_limit=int(os.getenv('DEFAULT_TRANSACTION_LIMIT', 35)),
            max_transaction_limit=int(os.getenv('MAX_TRANSACTION_LIMIT', 100))
        )
    
    def _load_database_config(self) -> DatabaseConfig:
        """Charge la configuration de la base de données"""
        return DatabaseConfig(
            name=os.getenv('DB_NAME', 'solana_wallet.db'),
            path=os.getenv('DB_PATH'),
            timeout=float(os.getenv('DB_TIMEOUT', 30.0)),
            backup_enabled=self._get_bool_env('DB_BACKUP_ENABLED', True),
            backup_interval_hours=int(os.getenv('DB_BACKUP_INTERVAL_HOURS', 24)),
            cleanup_old_data_days=int(os.getenv('DB_CLEANUP_OLD_DATA_DAYS', 30))
        )
    
    def _load_logging_config(self) -> LoggingConfig:
        """Charge la configuration du logging"""
        return LoggingConfig(
            level=LogLevel(os.getenv('LOG_LEVEL', 'INFO')),
            file_path=os.getenv('LOG_FILE', 'wallet_monitor.log'),
            console_output=self._get_bool_env('LOG_CONSOLE_OUTPUT', True),
            json_output=self._get_bool_env('LOG_JSON_OUTPUT', False),
            max_file_size_mb=int(os.getenv('LOG_MAX_FILE_SIZE_MB', 10)),
            backup_count=int(os.getenv('LOG_BACKUP_COUNT', 5)),
            max_age_days=int(os.getenv('LOG_MAX_AGE_DAYS', 7))
        )
    
    def _load_flask_config(self) -> FlaskConfig:
        """Charge la configuration Flask"""
        cors_origins = os.getenv('FLASK_CORS_ORIGINS', 'http://localhost:3000,http://127.0.0.1:5000')
        origins_list = [origin.strip() for origin in cors_origins.split(',') if origin.strip()]
        
        return FlaskConfig(
            host=os.getenv('FLASK_HOST', '127.0.0.1'),
            port=int(os.getenv('FLASK_PORT', 5000)),
            debug=self._get_bool_env('FLASK_DEBUG', True),
            cors_enabled=self._get_bool_env('FLASK_CORS_ENABLED', True),
            cors_origins=origins_list,
            api_rate_limit_enabled=self._get_bool_env('API_RATE_LIMIT_ENABLED', True),
            api_rate_limit_per_minute=int(os.getenv('API_RATE_LIMIT_PER_MINUTE', 1000))
        )
    
    def _load_alerting_config(self) -> AlertingConfig:
        """Charge la configuration des alertes"""
        # Parser les destinataires email
        email_recipients = os.getenv('ALERT_EMAIL_RECIPIENTS', '')
        recipients_list = [email.strip() for email in email_recipients.split(',') if email.strip()]
        
        # Parser les seuils d'alerte personnalisés
        alert_thresholds = {}
        threshold_keys = [
            'ALERT_LARGE_TRANSACTION_SOL', 'ALERT_LARGE_TRANSACTION_TOKENS',
            'ALERT_HIGH_ACTIVITY_TX_PER_HOUR', 'ALERT_ERROR_RATE_CRITICAL',
            'ALERT_RESPONSE_TIME_CRITICAL'
        ]
        
        for key in threshold_keys:
            if os.getenv(key):
                try:
                    threshold_name = key.replace('ALERT_', '').lower()
                    alert_thresholds[threshold_name] = float(os.getenv(key))
                except ValueError:
                    pass
        
        config = AlertingConfig(
            enabled=self._get_bool_env('ALERTING_ENABLED', False),
            slack_webhook_url=os.getenv('SLACK_WEBHOOK_URL'),
            email_enabled=self._get_bool_env('ALERT_EMAIL_ENABLED', False),
            email_smtp_server=os.getenv('ALERT_EMAIL_SMTP_SERVER'),
            email_smtp_port=int(os.getenv('ALERT_EMAIL_SMTP_PORT', 587)),
            email_username=os.getenv('ALERT_EMAIL_USERNAME'),
            email_password=os.getenv('ALERT_EMAIL_PASSWORD'),
            email_recipients=recipients_list
        )
        
        # Appliquer les seuils personnalisés
        if alert_thresholds:
            config.alert_thresholds.update(alert_thresholds)
        
        return config
    
    def _apply_environment_overrides(self):
        """Applique les ajustements spécifiques à l'environnement"""
        if self.environment == Environment.DEVELOPMENT:
            self._apply_development_overrides()
        elif self.environment == Environment.PRODUCTION:
            self._apply_production_overrides()
        elif self.environment == Environment.TESTING:
            self._apply_testing_overrides()
        elif self.environment == Environment.STAGING:
            self._apply_staging_overrides()
    
    def _apply_development_overrides(self):
        """Ajustements pour l'environnement de développement"""
        self.flask.debug = True
        self.logging.level = LogLevel.DEBUG
        self.logging.console_output = True
        self.monitoring.rate_limit_delay = 0.3  # Plus lent pour éviter les rate limits
        self.monitoring.full_scan_interval_hours = 2  # Scans plus fréquents
        self.database.backup_enabled = False  # Pas de backup en dev
        self.batching.batch_sizes = {k: max(2, v // 2) for k, v in self.batching.batch_sizes.items()}  # Batches plus petits
    
    def _apply_production_overrides(self):
        """Ajustements pour l'environnement de production"""
        self.flask.debug = False
        self.flask.host = '0.0.0.0'
        self.logging.level = LogLevel.INFO
        self.logging.console_output = False
        self.logging.json_output = True  # JSON pour les systèmes de monitoring
        self.monitoring.update_interval = 60
        self.monitoring.default_transaction_limit = 25
        self.monitoring.max_transaction_limit = 200
        self.database.backup_enabled = True
        self.alerting.enabled = True  # Activer les alertes en production
    
    def _apply_testing_overrides(self):
        """Ajustements pour l'environnement de test"""
        self.flask.debug = False
        self.logging.level = LogLevel.WARNING
        self.logging.console_output = False
        self.logging.file_path = "test_wallet_monitor.log"
        self.database.name = "test_solana_wallet.db"
        self.monitoring.update_interval = 10  # Tests plus rapides
        self.monitoring.max_consecutive_errors = 1  # Fail fast en test
        self.batching.enabled = False  # Simplifier pour les tests
        self.alerting.enabled = False
    
    def _apply_staging_overrides(self):
        """Ajustements pour l'environnement de staging"""
        self.flask.debug = False
        self.logging.level = LogLevel.INFO
        self.logging.json_output = True
        self.database.name = "staging_solana_wallet.db"
        self.monitoring.update_interval = 45
        self.alerting.enabled = True
    
    def _validate_configuration(self):
        """Valide la cohérence de toute la configuration"""
        errors = []
        warnings = []
        
        # Validation des wallets
        if not self.wallet.addresses:
            errors.append("Aucune adresse de wallet configurée")
        
        # Validation RPC
        if not self.rpc.get_all_endpoints():
            errors.append("Aucun endpoint RPC configuré")
        
        if self.rpc.timeout <= 0:
            errors.append("Timeout RPC doit être positif")
        
        # Validation monitoring
        if self.monitoring.update_interval < 10:
            warnings.append("UPDATE_INTERVAL très faible - risque de rate limiting")
        
        if self.monitoring.rate_limit_delay < 0.05:
            warnings.append("RATE_LIMIT_DELAY très faible - risque de rate limiting")
        
        if self.monitoring.token_discovery_batch_size > 200:
            warnings.append("TOKEN_DISCOVERY_BATCH_SIZE élevé - peut ralentir les scans")
        
        # Validation batching
        if self.batching.enabled:
            for method, size in self.batching.batch_sizes.items():
                if size <= 0:
                    errors.append(f"Taille de batch invalide pour {method}: {size}")
                elif size > 100:
                    warnings.append(f"Taille de batch élevée pour {method}: {size}")
        
        # Validation Flask
        if not (1024 <= self.flask.port <= 65535):
            errors.append(f"Port Flask invalide: {self.flask.port}")
        
        # Validation base de données
        db_path = Path(self.database.get_full_path())
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Impossible de créer le répertoire de base de données: {e}")
        
        # Validation logging
        log_path = Path(self.logging.file_path)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            warnings.append(f"Impossible de créer le répertoire de logs: {e}")
        
        # Validation alerting
        if self.alerting.enabled:
            if not self.alerting.slack_webhook_url and not self.alerting.email_enabled:
                warnings.append("Alertes activées mais aucun canal configuré")
            
            if self.alerting.email_enabled:
                if not self.alerting.email_smtp_server:
                    errors.append("Email activé mais serveur SMTP non configuré")
                if not self.alerting.email_recipients:
                    warnings.append("Email activé mais aucun destinataire configuré")
        
        # Lever les erreurs critiques
        if errors:
            raise ConfigurationError(f"Erreurs de configuration: {'; '.join(errors)}")
        
        # Stocker les avertissements
        self._warnings = warnings
    
    def _get_bool_env(self, key: str, default: bool = False) -> bool:
        """Récupère une variable d'environnement booléenne"""
        value = os.getenv(key, str(default)).lower()
        return value in ('true', '1', 'yes', 'on', 'enabled')
    
    def get_warnings(self) -> List[str]:
        """Retourne les avertissements de configuration"""
        return getattr(self, '_warnings', [])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit la configuration en dictionnaire"""
        return {
            'environment': self.environment.value,
            'wallet': {
                'addresses': self.wallet.addresses,
                'primary_address': self.wallet.primary_address,
                'selection_mode': self.wallet.selection_mode.value,
                'random_selection_weight_by_priority': self.wallet.random_selection_weight_by_priority,
                'min_interval_between_scans': self.wallet.min_interval_between_scans
            },
            'rpc': {
                'endpoints': self.rpc.get_all_endpoints(),
                'timeout': self.rpc.timeout,
                'max_retries': self.rpc.max_retries,
                'requests_per_minute': self.rpc.requests_per_minute
            },
            'batching': {
                'enabled': self.batching.enabled,
                'batch_sizes': self.batching.batch_sizes,
                'adaptive_sizing': self.batching.adaptive_sizing
            },
            'monitoring': {
                'update_interval': self.monitoring.update_interval,
                'full_scan_interval_hours': self.monitoring.full_scan_interval_hours,
                'rate_limit_delay': self.monitoring.rate_limit_delay,
                'large_transaction_threshold': self.monitoring.large_transaction_threshold
            },
            'database': {
                'path': self.database.get_full_path(),
                'timeout': self.database.timeout,
                'backup_enabled': self.database.backup_enabled
            },
            'logging': {
                'level': self.logging.level.value,
                'file_path': self.logging.file_path,
                'console_output': self.logging.console_output,
                'json_output': self.logging.json_output
            },
            'flask': {
                'host': self.flask.host,
                'port': self.flask.port,
                'debug': self.flask.debug,
                'cors_enabled': self.flask.cors_enabled
            },
            'alerting': {
                'enabled': self.alerting.enabled,
                'slack_webhook_configured': bool(self.alerting.slack_webhook_url),
                'email_enabled': self.alerting.email_enabled,
                'alert_thresholds': self.alerting.alert_thresholds
            }
        }
    
    def save_to_file(self, file_path: str):
        """Sauvegarde la configuration dans un fichier JSON"""
        try:
            config_dict = self.to_dict()
            # Masquer les informations sensibles
            if 'rpc' in config_dict and 'quicknode_api_key' in config_dict['rpc']:
                del config_dict['rpc']['quicknode_api_key']
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Configuration sauvegardée dans {file_path}")
        except Exception as e:
            print(f"❌ Erreur sauvegarde configuration: {e}")
    
    def get_summary(self) -> str:
        """Retourne un résumé de la configuration"""
        summary_lines = [
            f"🔧 Configuration Solana Wallet Monitor v2.0",
            f"   Environnement: {self.environment.value.upper()}",
            f"   Wallets: {len(self.wallet.addresses)} configurés",
            f"   Wallet principal: {self.wallet.primary_address[:8]}...{self.wallet.primary_address[-8:]}",
            f"   Mode sélection: {self.wallet.selection_mode.value}",
            f"   Endpoints RPC: {len(self.rpc.get_all_endpoints())} disponibles",
            f"   Batching RPC: {'✅ Activé' if self.batching.enabled else '❌ Désactivé'}",
            f"   Intervalle monitoring: {self.monitoring.update_interval}s",
            f"   Base de données: {self.database.get_full_path()}",
            f"   Logging: {self.logging.level.value} vers {self.logging.file_path}",
            f"   API Flask: {self.flask.host}:{self.flask.port}",
            f"   Alertes: {'✅ Activées' if self.alerting.enabled else '❌ Désactivées'}"
        ]
        
        if self.get_warnings():
            summary_lines.append("⚠️ Avertissements:")
            for warning in self.get_warnings():
                summary_lines.append(f"   - {warning}")
        
        return "\n".join(summary_lines)

  # =============================================================================
# FONCTIONS D'INITIALISATION ET HELPERS
# =============================================================================

def load_config_from_file(file_path: str) -> Dict[str, Any]:
   """Charge une configuration depuis un fichier JSON"""
   try:
       with open(file_path, 'r', encoding='utf-8') as f:
           return json.load(f)
   except FileNotFoundError:
       print(f"⚠️ Fichier de configuration non trouvé: {file_path}")
       return {}
   except json.JSONDecodeError as e:
       print(f"❌ Erreur parsing JSON dans {file_path}: {e}")
       return {}
   except Exception as e:
       print(f"❌ Erreur lecture configuration {file_path}: {e}")
       return {}

def load_config_from_env_file(env_file_path: str = ".env"):
    """
    Charge les variables d'environnement depuis un fichier .env
    Gestion robuste avec validation et reporting d'erreurs détaillé
    """
    env_path = Path(env_file_path)
    if not env_path.exists():
        return
    
    loaded_vars = 0
    skipped_lines = 0
    errors = []
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                original_line = line
                line = line.strip()
                
                # Ignorer les commentaires et lignes vides
                if not line or line.startswith('#'):
                    continue
                
                # Vérifier la présence du séparateur =
                if '=' not in line:
                    errors.append(f"Ligne {line_num}: Format invalide (pas de '=') - {line[:50]}")
                    skipped_lines += 1
                    continue
                
                try:
                    # Parser KEY=VALUE
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Validation de la clé
                    if not key:
                        errors.append(f"Ligne {line_num}: Clé vide")
                        skipped_lines += 1
                        continue
                    
                    # Vérifier que la clé est un identifiant valide
                    if not key.replace('_', '').replace('-', '').isalnum():
                        errors.append(f"Ligne {line_num}: Clé invalide '{key}' (caractères non autorisés)")
                        skipped_lines += 1
                        continue
                    
                    # Supprimer les commentaires inline (après #)
                    if '#' in value:
                        comment_pos = value.find('#')
                        # Vérifier que ce n'est pas un # entre guillemets
                        in_quotes = False
                        quote_char = None
                        
                        for i, char in enumerate(value):
                            if char in ('"', "'") and (i == 0 or value[i-1] != '\\'):
                                if not in_quotes:
                                    in_quotes = True
                                    quote_char = char
                                elif char == quote_char:
                                    in_quotes = False
                                    quote_char = None
                            elif char == '#' and not in_quotes:
                                value = value[:i].strip()
                                break
                    
                    # Supprimer les guillemets optionnels
                    if len(value) >= 2:
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            # Vérifier que les guillemets sont bien appariés
                            quote_char = value[0]
                            if value.count(quote_char) >= 2:
                                value = value[1:-1]
                                # Gérer les échappements dans les guillemets
                                value = value.replace(f'\\{quote_char}', quote_char)
                                value = value.replace('\\\\', '\\')
                                value = value.replace('\\n', '\n')
                                value = value.replace('\\t', '\t')
                    
                    # Définir la variable d'environnement si elle n'existe pas déjà
                    if key not in os.environ:
                        os.environ[key] = value
                        loaded_vars += 1
                    else:
                        # Optionnel: Logger que la variable existe déjà
                        pass
                    
                except ValueError as e:
                    errors.append(f"Ligne {line_num}: Erreur de parsing - {e}")
                    skipped_lines += 1
                    continue
                
                except Exception as e:
                    errors.append(f"Ligne {line_num}: Erreur inattendue - {e}")
                    skipped_lines += 1
                    continue
        
        # Reporting des résultats
        if loaded_vars > 0:
            print(f"✅ Variables d'environnement chargées depuis {env_file_path}: {loaded_vars}")
        
        if skipped_lines > 0:
            print(f"⚠️ {skipped_lines} ligne(s) ignorée(s) dans {env_file_path}")
        
        # Afficher les erreurs (limitées pour éviter le spam)
        if errors:
            print(f"❌ Erreurs dans {env_file_path}:")
            for error in errors[:5]:  # Limiter à 5 erreurs pour éviter le spam
                print(f"   - {error}")
            if len(errors) > 5:
                print(f"   ... et {len(errors) - 5} autres erreurs")
        
        return {
            'loaded_vars': loaded_vars,
            'skipped_lines': skipped_lines,
            'errors': errors
        }
        
    except FileNotFoundError:
        # Déjà géré par la vérification env_path.exists()
        return None
        
    except PermissionError:
        print(f"❌ Pas de permission de lecture pour {env_file_path}")
        return None
        
    except UnicodeDecodeError as e:
        print(f"❌ Erreur d'encodage dans {env_file_path}: {e}")
        print("💡 Vérifiez que le fichier est en UTF-8")
        return None
        
    except Exception as e:
        print(f"❌ Erreur lecture fichier .env {env_file_path}: {e}")
        return None


# Fonction helper pour valider un fichier .env
def validate_env_file(env_file_path: str = ".env") -> Dict[str, Any]:
    """
    Valide un fichier .env sans charger les variables
    Retourne un rapport détaillé de validation
    """
    env_path = Path(env_file_path)
    
    if not env_path.exists():
        return {
            'valid': False,
            'error': 'File not found',
            'suggestions': [f"Créer le fichier {env_file_path}"]
        }
    
    validation_report = {
        'valid': True,
        'total_lines': 0,
        'valid_vars': 0,
        'comments': 0,
        'empty_lines': 0,
        'errors': [],
        'warnings': [],
        'suggestions': []
    }
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                validation_report['total_lines'] += 1
                original_line = line
                line = line.strip()
                
                # Ligne vide
                if not line:
                    validation_report['empty_lines'] += 1
                    continue
                
                # Commentaire
                if line.startswith('#'):
                    validation_report['comments'] += 1
                    continue
                
                # Validation variable
                if '=' not in line:
                    validation_report['errors'].append(f"Ligne {line_num}: Format invalide - {line}")
                    validation_report['valid'] = False
                    continue
                
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Validation clé
                if not key:
                    validation_report['errors'].append(f"Ligne {line_num}: Clé vide")
                    validation_report['valid'] = False
                    continue
                
                if not key.replace('_', '').replace('-', '').isalnum():
                    validation_report['errors'].append(f"Ligne {line_num}: Clé invalide '{key}'")
                    validation_report['valid'] = False
                    continue
                
                # Avertissements
                if key.lower() != key and key.upper() != key:
                    validation_report['warnings'].append(f"Ligne {line_num}: Clé '{key}' avec casse mixte")
                
                if len(value) == 0:
                    validation_report['warnings'].append(f"Ligne {line_num}: Valeur vide pour '{key}'")
                
                # Suggestions
                if key.startswith('password') or key.startswith('secret') or key.startswith('key'):
                    if len(value) < 8:
                        validation_report['suggestions'].append(f"'{key}': Valeur suspecte (trop courte)")
                
                validation_report['valid_vars'] += 1
        
        # Suggestions générales
        if validation_report['valid_vars'] == 0:
            validation_report['suggestions'].append("Aucune variable trouvée, fichier peut être vide")
        
        if validation_report['total_lines'] > 100:
            validation_report['suggestions'].append("Fichier .env volumineux, considérer le découpage")
        
    except Exception as e:
        validation_report['valid'] = False
        validation_report['error'] = str(e)
    
    return validation_report



def get_environment_from_args_or_env() -> Environment:
   """Détermine l'environnement depuis les arguments ou variables d'environnement"""
   import sys
   
   # Vérifier les arguments de ligne de commande
   for arg in sys.argv[1:]:
       if arg.startswith('--env='):
           env_name = arg.split('=', 1)[1]
           try:
               return Environment(env_name.lower())
           except ValueError:
               print(f"⚠️ Environnement invalide: {env_name}")
       elif arg in ['--dev', '--development']:
           return Environment.DEVELOPMENT
       elif arg in ['--prod', '--production']:
           return Environment.PRODUCTION
       elif arg in ['--test', '--testing']:
           return Environment.TESTING
       elif arg in ['--staging']:
           return Environment.STAGING
   
   # Vérifier la variable d'environnement
   env_name = os.getenv('ENVIRONMENT', 'development').lower()
   try:
       return Environment(env_name)
   except ValueError:
       print(f"⚠️ ENVIRONMENT invalide: {env_name}, utilisation de 'development'")
       return Environment.DEVELOPMENT


def create_config(environment: Optional[Union[Environment, str]] = None,
                config_file: Optional[str] = None,
                env_file: Optional[str] = ".env") -> SolanaWalletConfig:
   """
   Crée une instance de configuration avec chargement intelligent
   
   Args:
       environment: Environnement cible (auto-détecté si None)
       config_file: Fichier de configuration JSON (optionnel)
       env_file: Fichier .env à charger (optionnel)
   
   Returns:
       Instance de configuration configurée
   """
   # Charger le fichier .env si spécifié
   if env_file:
       load_config_from_env_file(env_file)
   
   # Déterminer l'environnement
   if environment is None:
       environment = get_environment_from_args_or_env()
   
   # Charger la configuration depuis un fichier si spécifié
   file_config = {}
   if config_file:
       file_config = load_config_from_file(config_file)
   
   # Créer l'instance de configuration
   config = SolanaWalletConfig(environment)
   
   # Appliquer les overrides du fichier si disponibles
   if file_config:
       apply_config_overrides(config, file_config)
   
   return config


def apply_config_overrides(config: SolanaWalletConfig, overrides: Dict[str, Any]):
   """Applique des overrides de configuration depuis un dictionnaire"""
   try:
       # Overrides wallet
       if 'wallet' in overrides:
           wallet_overrides = overrides['wallet']
           if 'addresses' in wallet_overrides:
               config.wallet.addresses = wallet_overrides['addresses']
           if 'selection_mode' in wallet_overrides:
               config.wallet.selection_mode = WalletSelectionMode(wallet_overrides['selection_mode'])
       
       # Overrides RPC
       if 'rpc' in overrides:
           rpc_overrides = overrides['rpc']
           if 'timeout' in rpc_overrides:
               config.rpc.timeout = rpc_overrides['timeout']
           if 'max_retries' in rpc_overrides:
               config.rpc.max_retries = rpc_overrides['max_retries']
       
       # Overrides batching
       if 'batching' in overrides:
           batching_overrides = overrides['batching']
           if 'enabled' in batching_overrides:
               config.batching.enabled = batching_overrides['enabled']
           if 'batch_sizes' in batching_overrides:
               config.batching.batch_sizes.update(batching_overrides['batch_sizes'])
       
       # Overrides monitoring
       if 'monitoring' in overrides:
           monitoring_overrides = overrides['monitoring']
           if 'update_interval' in monitoring_overrides:
               config.monitoring.update_interval = monitoring_overrides['update_interval']
       
       # Overrides logging
       if 'logging' in overrides:
           logging_overrides = overrides['logging']
           if 'level' in logging_overrides:
               config.logging.level = LogLevel(logging_overrides['level'])
       
       print("✅ Overrides de configuration appliqués")
   except Exception as e:
       print(f"⚠️ Erreur application overrides: {e}")


# =============================================================================
# HELPERS DE VALIDATION AVANCÉS
# =============================================================================

class ConfigValidator:
   """Validateur avancé de configuration avec règles personnalisables"""
   
   def __init__(self, config: SolanaWalletConfig):
       self.config = config
       self.errors = []
       self.warnings = []
       self.recommendations = []
   
   def validate_all(self) -> Tuple[List[str], List[str], List[str]]:
       """Effectue une validation complète"""
       self.errors.clear()
       self.warnings.clear()
       self.recommendations.clear()
       
       self._validate_wallet_config()
       self._validate_rpc_config()
       self._validate_batching_config()
       self._validate_monitoring_config()
       self._validate_database_config()
       self._validate_logging_config()
       self._validate_flask_config()
       self._validate_alerting_config()
       self._validate_cross_dependencies()
       self._generate_recommendations()
       
       return self.errors.copy(), self.warnings.copy(), self.recommendations.copy()
   
   def _validate_wallet_config(self):
       """Valide la configuration des wallets"""
       if len(self.config.wallet.addresses) > 100:
           self.warnings.append(f"Beaucoup de wallets configurés ({len(self.config.wallet.addresses)})")
       
       if len(self.config.wallet.addresses) > 1000:
           self.errors.append("Trop de wallets (>1000), performances dégradées")
       
       # Vérifier les doublons
       unique_addresses = set(self.config.wallet.addresses)
       if len(unique_addresses) != len(self.config.wallet.addresses):
           duplicates = len(self.config.wallet.addresses) - len(unique_addresses)
           self.warnings.append(f"{duplicates} adresses de wallet dupliquées")
       
       # Vérifier la cohérence du mode de sélection
       if (self.config.wallet.selection_mode == WalletSelectionMode.RANDOM and 
           len(self.config.wallet.addresses) == 1):
           self.warnings.append("Mode aléatoire avec un seul wallet n'a pas de sens")
   
   def _validate_rpc_config(self):
       """Valide la configuration RPC"""
       endpoints = self.config.rpc.get_all_endpoints()
       
       if len(endpoints) < 2:
           self.warnings.append("Un seul endpoint RPC configuré, pas de fallback")
       
       if self.config.rpc.timeout > 60:
           self.warnings.append("Timeout RPC très élevé, peut ralentir les scans")
       
       if self.config.rpc.requests_per_minute > 500:
           self.warnings.append("Limite RPC élevée, risque de rate limiting")
       
       # Vérifier la validité des URLs
       for endpoint in endpoints:
           if not endpoint.startswith(('http://', 'https://')):
               self.errors.append(f"Endpoint RPC invalide: {endpoint}")
   
   def _validate_batching_config(self):
       """Valide la configuration du batching"""
       if not self.config.batching.enabled:
           self.recommendations.append("Batching désactivé, performances sous-optimales")
           return
       
       # Vérifier les tailles de batch
       for method, size in self.config.batching.batch_sizes.items():
           if size > 50:
               self.warnings.append(f"Taille de batch élevée pour {method}: {size}")
           elif size < 2:
               self.warnings.append(f"Taille de batch très faible pour {method}: {size}")
       
       # Vérifier la cohérence des délais
       if self.config.batching.min_delay_between_batches > 2.0:
           self.warnings.append("Délai entre batches très élevé, ralentit les scans")
       
       if self.config.batching.batch_timeout < 10:
           self.warnings.append("Timeout batch faible, risque d'interruption")
   
   def _validate_monitoring_config(self):
       """Valide la configuration du monitoring"""
       # Vérifier les intervalles
       if self.config.monitoring.update_interval < 5:
           self.errors.append("Intervalle de mise à jour trop faible (<5s)")
       elif self.config.monitoring.update_interval < 30:
           self.warnings.append("Intervalle de mise à jour faible, risque de rate limiting")
       
       # Vérifier la cohérence des seuils
       if (self.config.monitoring.default_transaction_limit > 
           self.config.monitoring.max_transaction_limit):
           self.errors.append("Limite par défaut > limite maximum pour les transactions")
       
       # Vérifier les seuils d'alerte
       if self.config.monitoring.large_transaction_threshold <= 0:
           self.warnings.append("Seuil de transaction importante <= 0")
   
   def _validate_database_config(self):
       """Valide la configuration de la base de données"""
       db_path = Path(self.config.database.get_full_path())
       
       # Vérifier l'espace disque (approximatif)
       try:
           free_space = db_path.parent.stat().st_size if db_path.exists() else 0
           if free_space > 0 and free_space < 100 * 1024 * 1024:  # <100MB
               self.warnings.append("Espace disque faible pour la base de données")
       except:
           pass
       
       # Vérifier les paramètres de backup
       if self.config.database.backup_enabled and self.config.database.backup_interval_hours < 1:
           self.warnings.append("Intervalle de backup très fréquent")
       
       if self.config.database.cleanup_old_data_days < 7:
           self.warnings.append("Nettoyage des données très fréquent, perte d'historique")
   
   def _validate_logging_config(self):
       """Valide la configuration du logging"""
       log_path = Path(self.config.logging.file_path)
       
       # Vérifier les permissions d'écriture
       try:
           log_path.parent.mkdir(parents=True, exist_ok=True)
           test_file = log_path.parent / "test_write.tmp"
           test_file.touch()
           test_file.unlink()
       except Exception:
           self.errors.append(f"Pas de permission d'écriture pour les logs: {log_path.parent}")
       
       # Vérifier les paramètres de rotation
       if self.config.logging.max_file_size_mb > 100:
           self.warnings.append("Taille maximum de log élevée")
       
       if self.config.logging.backup_count < 2:
           self.warnings.append("Peu de fichiers de backup de logs")
   
   def _validate_flask_config(self):
       """Valide la configuration Flask"""
       # Vérifier la sécurité
       if (self.config.environment == Environment.PRODUCTION and 
           self.config.flask.debug):
           self.errors.append("Mode debug activé en production - SÉCURITÉ")
       
       if (self.config.environment == Environment.PRODUCTION and 
           self.config.flask.host == '0.0.0.0' and 
           not self.config.flask.cors_enabled):
           self.warnings.append("API exposée sans CORS en production")
       
       # Vérifier les limites API
       if not self.config.flask.api_rate_limit_enabled:
           self.warnings.append("Rate limiting API désactivé")
   
   def _validate_alerting_config(self):
       """Valide la configuration des alertes"""
       if not self.config.alerting.enabled:
           self.recommendations.append("Alertes désactivées, surveillance limitée")
           return
       
       # Vérifier la configuration Slack
       if (self.config.alerting.slack_webhook_url and 
           not self.config.alerting.slack_webhook_url.startswith('https://hooks.slack.com')):
           self.warnings.append("URL webhook Slack suspecte")
       
       # Vérifier la configuration email
       if self.config.alerting.email_enabled:
           if not self.config.alerting.email_recipients:
               self.errors.append("Email activé mais aucun destinataire")
           
           if '@' not in str(self.config.alerting.email_username or ''):
               self.warnings.append("Username email semble invalide")
       
       # Vérifier les seuils
       thresholds = self.config.alerting.alert_thresholds
       if thresholds.get('error_rate_critical', 0) > 50:
           self.warnings.append("Seuil d'erreur critique très élevé")
   
   def _validate_cross_dependencies(self):
       """Valide les dépendances croisées entre configurations"""
       # Cohérence batching/monitoring
       if (self.config.batching.enabled and 
           self.config.monitoring.rate_limit_delay < self.config.batching.min_delay_between_batches):
           self.warnings.append("Rate limit monitoring < délai batching")
       
       # Cohérence wallet/monitoring
       if (len(self.config.wallet.addresses) > 10 and 
           self.config.monitoring.update_interval < 60):
           self.warnings.append("Beaucoup de wallets + intervalle court = surcharge")
       
       # Cohérence logging/monitoring
       if (self.config.logging.level == LogLevel.DEBUG and 
           self.config.environment == Environment.PRODUCTION):
           self.warnings.append("Logs DEBUG en production, impact performance")
   
   def _generate_recommendations(self):
       """Génère des recommandations d'optimisation"""
       # Recommandations environnement
       if self.config.environment == Environment.DEVELOPMENT:
           self.recommendations.append("Env dev: considérer des intervalles plus longs pour économiser les APIs")
       
       # Recommandations performance
       if len(self.config.wallet.addresses) > 50:
           self.recommendations.append("Beaucoup de wallets: activer le batching et ajuster les intervalles")
       
       if not self.config.batching.enabled:
           self.recommendations.append("Activer le batching RPC pour de meilleures performances")
       
       # Recommandations sécurité
       if not self.config.alerting.enabled:
           self.recommendations.append("Activer les alertes pour un monitoring proactif")
       
       # Recommandations maintenance
       if not self.config.database.backup_enabled:
           self.recommendations.append("Activer les backups de base de données")


# =============================================================================
# MIGRATION ET COMPATIBILITÉ
# =============================================================================

def migrate_from_legacy_config(legacy_config_dict: Dict[str, Any]) -> SolanaWalletConfig:
   """Migre une ancienne configuration vers le nouveau format"""
   print("🔄 Migration de l'ancienne configuration...")
   
   # Mapping des anciens noms vers les nouvelles variables d'environnement
   legacy_mappings = {
       'WALLET_ADDRESS': 'WALLET_ADDRESSES',
       'QUICKNODE_ENDPOINT': 'QUICKNODE_ENDPOINT',
       'UPDATE_INTERVAL': 'UPDATE_INTERVAL',
       'DB_NAME': 'DB_NAME',
       'LOG_LEVEL': 'LOG_LEVEL',
       'LOG_FILE': 'LOG_FILE',
       'FLASK_HOST': 'FLASK_HOST',
       'FLASK_PORT': 'FLASK_PORT',
       'FLASK_DEBUG': 'FLASK_DEBUG'
   }
   
   # Appliquer les mappings
   for old_key, new_key in legacy_mappings.items():
       if old_key in legacy_config_dict and new_key not in os.environ:
           os.environ[new_key] = str(legacy_config_dict[old_key])
   
   # Traitement spécial pour WALLET_ADDRESS -> WALLET_ADDRESSES
   if 'WALLET_ADDRESS' in legacy_config_dict and 'WALLET_ADDRESSES' not in os.environ:
       os.environ['WALLET_ADDRESSES'] = legacy_config_dict['WALLET_ADDRESS']
   
   # Créer la nouvelle configuration
   config = SolanaWalletConfig()
   
   print("✅ Migration terminée")
   return config


def export_to_env_file(config: SolanaWalletConfig, file_path: str = ".env.generated"):
   """Exporte la configuration vers un fichier .env"""
   try:
       env_lines = [
           "# Configuration générée automatiquement pour Solana Wallet Monitor v2.0",
           f"# Générée le: {datetime.now().isoformat()}",
           "",
           "# Environnement",
           f"ENVIRONMENT={config.environment.value}",
           "",
           "# Wallets",
           f"WALLET_ADDRESSES={','.join(config.wallet.addresses)}",
           f"WALLET_SELECTION_MODE={config.wallet.selection_mode.value}",
           f"MIN_INTERVAL_BETWEEN_SCANS={config.wallet.min_interval_between_scans}",
           "",
           "# RPC Configuration",
       ]
       
       if config.rpc.quicknode_endpoint:
           env_lines.append(f"QUICKNODE_ENDPOINT={config.rpc.quicknode_endpoint}")
       
       env_lines.extend([
           f"RPC_TIMEOUT={config.rpc.timeout}",
           f"MAX_RETRIES={config.rpc.max_retries}",
           f"RETRY_DELAY={config.rpc.retry_delay}",
           "",
           "# Monitoring",
           f"UPDATE_INTERVAL={config.monitoring.update_interval}",
           f"FULL_SCAN_INTERVAL_HOURS={config.monitoring.full_scan_interval_hours}",
           f"RATE_LIMIT_DELAY={config.monitoring.rate_limit_delay}",
           f"TOKEN_DISCOVERY_BATCH_SIZE={config.monitoring.token_discovery_batch_size}",
           "",
           "# Batching",
           f"ENABLE_RPC_BATCHING={str(config.batching.enabled).lower()}",
           f"BATCH_ADAPTIVE_SIZING={str(config.batching.adaptive_sizing).lower()}",
           f"MIN_DELAY_BETWEEN_BATCHES={config.batching.min_delay_between_batches}",
           "",
           "# Database",
           f"DB_NAME={config.database.name}",
           f"DB_TIMEOUT={config.database.timeout}",
           "",
           "# Logging",
           f"LOG_LEVEL={config.logging.level.value}",
           f"LOG_FILE={config.logging.file_path}",
           f"LOG_CONSOLE_OUTPUT={str(config.logging.console_output).lower()}",
           f"LOG_JSON_OUTPUT={str(config.logging.json_output).lower()}",
           "",
           "# Flask/API",
           f"FLASK_HOST={config.flask.host}",
           f"FLASK_PORT={config.flask.port}",
           f"FLASK_DEBUG={str(config.flask.debug).lower()}",
           "",
           "# Alerting",
           f"ALERTING_ENABLED={str(config.alerting.enabled).lower()}",
       ])
       
       if config.alerting.slack_webhook_url:
           env_lines.append(f"SLACK_WEBHOOK_URL={config.alerting.slack_webhook_url}")
       
       # Écrire le fichier
       with open(file_path, 'w', encoding='utf-8') as f:
           f.write('\n'.join(env_lines))
       
       print(f"✅ Configuration exportée vers {file_path}")
   except Exception as e:
       print(f"❌ Erreur export .env: {e}")


# =============================================================================
# INSTANCE GLOBALE ET INITIALISATION
# =============================================================================

# Instance globale de configuration (sera initialisée lors du premier accès)
_global_config: Optional[SolanaWalletConfig] = None
_config_lock = threading.Lock()


def get_config() -> SolanaWalletConfig:
   """Retourne l'instance globale de configuration (thread-safe)"""
   global _global_config
   
   if _global_config is None:
       with _config_lock:
           if _global_config is None:
               _global_config = create_config()
   
   return _global_config


def set_global_config(config: SolanaWalletConfig):
   """Définit l'instance globale de configuration"""
   global _global_config
   with _config_lock:
       _global_config = config


def reload_config():
   """Recharge la configuration globale"""
   global _global_config
   with _config_lock:
       _global_config = None
       _global_config = create_config()
   return get_config()


# =============================================================================
# CLASSE DE COMPATIBILITÉ LEGACY
# =============================================================================

class Config:
   """Classe de compatibilité avec l'ancienne interface de configuration"""
   
   def __init__(self):
       self._config = get_config()
   
   @property
   def WALLET_ADDRESSES(self) -> List[str]:
       return self._config.wallet.addresses
   
   @property
   def WALLET_ADDRESS(self) -> str:
       return self._config.wallet.primary_address
   
   @property
   def QUICKNODE_ENDPOINT(self) -> str:
       return self._config.rpc.quicknode_endpoint or ""
   
   @property
   def UPDATE_INTERVAL(self) -> int:
       return self._config.monitoring.update_interval
   
   @property
   def MAX_RETRIES(self) -> int:
       return self._config.rpc.max_retries
   
   @property
   def RETRY_DELAY(self) -> int:
       return self._config.rpc.retry_delay
   
   @property
   def DB_NAME(self) -> str:
       return self._config.database.get_full_path()
   
   @property
   def FLASK_HOST(self) -> str:
       return self._config.flask.host
   
   @property
   def FLASK_PORT(self) -> int:
       return self._config.flask.port
   
   @property
   def FLASK_DEBUG(self) -> bool:
       return self._config.flask.debug
   
   @property
   def LOG_LEVEL(self) -> str:
       return self._config.logging.level.value
   
   @property
   def LOG_FILE(self) -> str:
       return self._config.logging.file_path
   
   @property
   def ENABLE_RPC_BATCHING(self) -> bool:
       return self._config.batching.enabled
   
   @property
   def BATCH_SIZES(self) -> Dict[str, int]:
       return self._config.batching.batch_sizes
   
   @property
   def RATE_LIMIT_DELAY(self) -> float:
       return self._config.monitoring.rate_limit_delay
   
   def get_rpc_endpoints(self) -> List[str]:
       return self._config.rpc.get_all_endpoints()
   
   def get_rpc_headers(self) -> Dict[str, str]:
       return self._config.rpc.get_headers()
   
   def validate_config(self) -> List[str]:
       validator = ConfigValidator(self._config)
       errors, warnings, recommendations = validator.validate_all()
       return warnings  # Retourner les warnings pour compatibilité


# Instances de compatibilité
DefaultConfig = Config()
DevelopmentConfig = Config()  # Pour compatibilité, mais utilise la même instance
ProductionConfig = Config()   # Pour compatibilité, mais utilise la même instance


# =============================================================================
# INITIALISATION AUTOMATIQUE
# =============================================================================

def init_config():
   """Initialise la configuration au chargement du module"""
   try:
       # Charger le fichier .env s'il existe
       load_config_from_env_file()
       
       # Créer l'instance globale
       config = get_config()
       
       # Afficher le résumé
       print(config.get_summary())
       
       # Validation
       validator = ConfigValidator(config)
       errors, warnings, recommendations = validator.validate_all()
       
       if warnings:
           print("\n⚠️ Avertissements de configuration:")
           for warning in warnings:
               print(f"   - {warning}")
       
       if recommendations:
           print("\n💡 Recommandations:")
           for recommendation in recommendations[:3]:  # Limiter à 3 pour éviter le spam
               print(f"   - {recommendation}")
       
       if errors:
           print("\n❌ Erreurs critiques:")
           for error in errors:
               print(f"   - {error}")
           raise ConfigurationError(f"Erreurs de configuration: {errors}")
       
       return config
       
   except Exception as e:
       print(f"❌ Erreur initialisation configuration: {e}")
       print("💡 Vérifiez vos variables d'environnement et fichiers de config")
       raise


# =============================================================================
# EXPORT DES CLASSES ET FONCTIONS PRINCIPALES
# =============================================================================

__all__ = [
   # Enums
   'Environment', 'WalletSelectionMode', 'LogLevel',
   
   # Dataclasses de configuration
   'WalletConfig', 'RPCConfig', 'BatchingConfig', 'MonitoringConfig',
   'DatabaseConfig', 'LoggingConfig', 'FlaskConfig', 'AlertingConfig',
   
   # Classe principale
   'SolanaWalletConfig',
   
   # Fonctions d'initialisation
   'create_config', 'get_config', 'set_global_config', 'reload_config',
   
   # Utilitaires
   'load_config_from_file', 'load_config_from_env_file', 'ConfigValidator',
   'migrate_from_legacy_config', 'export_to_env_file',
   
   # Compatibilité legacy
   'Config', 'DefaultConfig', 'DevelopmentConfig', 'ProductionConfig',
   
   # Exceptions
   'ConfigurationError'
]

# Mode test/développement
if __name__ == "__main__":
   print("🧪 Test du système de configuration")
   
   # Test de création de configuration
   config = create_config(Environment.DEVELOPMENT)
   print("\n" + "="*80)
   print(config.get_summary())
   
   # Test de validation
   validator = ConfigValidator(config)
   errors, warnings, recommendations = validator.validate_all()
   
   print(f"\n📊 Résultats de validation:")
   print(f"   Erreurs: {len(errors)}")
   print(f"   Avertissements: {len(warnings)}")
   print(f"   Recommandations: {len(recommendations)}")
   
   # Test d'export
   config.save_to_file("test_config.json")
   export_to_env_file(config, "test_config.env")
   
   print("\n✅ Tests de configuration terminés")

