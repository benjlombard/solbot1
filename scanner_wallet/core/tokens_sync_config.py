#!/usr/bin/env python3
"""
Token Sync Configuration
Configuration spécialisée pour le système de synchronisation des tokens
"""

import os
import time
import logging
from typing import List, Dict, Optional, Union
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

# Import des utilitaires depuis le fichier de config principal
try:
    from .config import get_config as get_main_config, validate_wallet_address, sanitize_filename
    from .config import Environment, ConfigurationError
except ImportError:
    # Fallbacks si pas disponible
    class Environment(Enum):
        DEVELOPMENT = "development"
        PRODUCTION = "production"
        TESTING = "testing"
        STAGING = "staging"
    
    class ConfigurationError(Exception):
        pass
    
    def validate_wallet_address(addr: str) -> bool:
        if not isinstance(addr, str) or len(addr) < 32 or len(addr) > 44:
            return False
        base58_alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        return all(c in base58_alphabet for c in addr)
    
    def sanitize_filename(name: str) -> str:
        if not isinstance(name, str):
            return "unnamed"
        return "".join(c for c in name if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
    
    def get_main_config():
        return None


# =============================================================================
# CONFIGURATION SPÉCIALISÉE POUR TOKEN SYNC
# =============================================================================

@dataclass
class TokenSyncDatabaseConfig:
    """Configuration de base de données pour Token Sync"""
    name: str = "tokens_sync.db"
    path: Optional[str] = None
    base_dir: str = "database/tokens_sync"
    data_subdir: str = "data"
    timeout: float = 30.0
    max_connections: int = 10
    backup_enabled: bool = True
    backup_interval_hours: int = 12
    cleanup_old_data_days: int = 30
    wal_mode: bool = True
    
    def get_full_path(self) -> str:
        """Retourne le chemin complet de la base de données"""
        if self.path:
            return str(Path(self.path) / self.name)
        
        db_dir = Path(self.base_dir) / self.data_subdir
        db_dir.mkdir(parents=True, exist_ok=True)
        return str(db_dir / self.name)
    
    def get_backup_dir(self) -> str:
        """Retourne le répertoire de backup"""
        if self.path:
            backup_dir = Path(self.path).parent / "backups"
        else:
            backup_dir = Path(self.base_dir) / "backups"
        
        backup_dir.mkdir(parents=True, exist_ok=True)
        return str(backup_dir)


@dataclass
class TokenSyncAPIConfig:
    """Configuration des APIs pour Token Sync"""
    dexscreener_enabled: bool = True
    pumpfun_enabled: bool = True
    rugcheck_enabled: bool = True
    solanatracker_enabled: bool = False
    
    # Rate limits spécifiques
    dexscreener_rate_limit: int = 60  # calls per minute
    pumpfun_rate_limit: int = 30
    rugcheck_rate_limit: int = 40
    solanatracker_rate_limit: int = 60
    
    # Timeouts
    api_timeout_seconds: float = 30.0
    fallback_timeout_seconds: float = 15.0
    
    # Retry configuration
    max_retries: int = 3
    retry_delay_base: float = 1.0
    retry_delay_multiplier: float = 2.0
    
    # Batch sizes
    dexscreener_batch_size: int = 30
    pumpfun_batch_size: int = 1  # No batch API
    rugcheck_batch_size: int = 1  # No batch API
    solanatracker_batch_size: int = 1
    
    def get_enabled_apis(self) -> List[str]:
        """Retourne la liste des APIs activées"""
        enabled = []
        if self.dexscreener_enabled:
            enabled.append('dexscreener')
        if self.pumpfun_enabled:
            enabled.append('pumpfun')
        if self.rugcheck_enabled:
            enabled.append('rugcheck')
        if self.solanatracker_enabled:
            enabled.append('solanatracker')
        return enabled


@dataclass
class TokenSyncProcessingConfig:
    """Configuration du traitement des tokens"""
    # Intervalles de traitement
    enrichment_interval_seconds: int = 300  # 5 minutes
    price_update_interval_seconds: int = 600  # 10 minutes
    historization_interval_seconds: int = 3600  # 1 heure
    dead_token_check_interval_seconds: int = 86400  # 24 heures
    
    # Limites de traitement
    batch_size_new_tokens: int = 100
    batch_size_price_updates: int = 150
    batch_size_historization: int = 50
    max_concurrent_batches: int = 3
    
    # Gestion des échecs
    max_failed_attempts: int = 5
    retry_failed_after_hours: int = 24
    
    # Rate limiting
    rate_limit_delay: float = 0.2
    api_calls_per_minute: int = 100
    
    # Token prioritization
    priority_tokens_enabled: bool = True
    high_volume_threshold: float = 100000.0  # $100K
    high_volatility_threshold: float = 20.0  # 20%
    
    def validate(self) -> List[str]:
        """Valide la configuration et retourne les erreurs"""
        errors = []
        
        if self.enrichment_interval_seconds < 60:
            errors.append("Enrichment interval too low (minimum 60 seconds)")
        
        if self.batch_size_new_tokens > 1000:
            errors.append("Batch size for new tokens too large (maximum 1000)")
        
        if self.rate_limit_delay < 0.1:
            errors.append("Rate limit delay too low (minimum 0.1 seconds)")
        
        return errors


@dataclass
class TokenSyncHistorizationConfig:
    """Configuration de l'historisation"""
    enabled: bool = True
    
    # Intervalles d'historisation
    default_interval_hours: int = 1
    priority_interval_minutes: int = 15
    
    # Critères de priorité
    priority_volume_threshold: float = 50000.0
    priority_price_change_threshold: float = 15.0
    priority_holder_count_threshold: int = 1000
    
    # Rétention des données
    retention_days: int = 30
    cleanup_interval_hours: int = 6
    
    # Analysis configuration
    analysis_enabled: bool = True
    trend_analysis_enabled: bool = True
    momentum_analysis_enabled: bool = True
    
    # Batch processing
    max_tokens_per_batch: int = 100
    max_concurrent_historizations: int = 5
    
    def get_priority_criteria(self) -> Dict[str, float]:
        """Retourne les critères de priorité"""
        return {
            'volume_threshold': self.priority_volume_threshold,
            'price_change_threshold': self.priority_price_change_threshold,
            'holder_count_threshold': self.priority_holder_count_threshold
        }


@dataclass
class TokenSyncMonitoringConfig:
    """Configuration du monitoring pour Token Sync"""
    # Performance monitoring
    performance_monitoring_enabled: bool = True
    performance_metrics_interval_seconds: int = 30
    performance_retention_days: int = 7
    
    # API monitoring
    api_monitoring_enabled: bool = True
    api_metrics_retention_days: int = 3
    slow_api_threshold_seconds: float = 5.0
    failed_api_threshold_percent: float = 10.0
    
    # Cycle monitoring
    cycle_logging_enabled: bool = True
    cycle_history_max_size: int = 100
    
    # Alerting thresholds
    alert_on_consecutive_failures: int = 5
    alert_on_high_error_rate: float = 20.0  # %
    alert_on_slow_processing: float = 300.0  # seconds per cycle
    
    # Statistics
    calculate_trends: bool = True
    export_metrics: bool = False
    metrics_export_interval_hours: int = 24


@dataclass
class TokenSyncLoggingConfig:
    """Configuration de logging pour Token Sync"""
    # Niveaux de log
    level: str = "INFO"
    console_output: bool = True
    file_output: bool = True
    
    # Fichiers de log
    log_file: str = "tokens_sync.log"
    error_log_file: str = "tokens_sync_errors.log"
    api_log_file: str = "tokens_sync_api.log"
    
    # Répertoires
    log_dir: str = "logs/tokens_sync"
    archive_dir: str = "logs/tokens_sync/archive"
    
    # Rotation
    max_file_size_mb: int = 50
    backup_count: int = 10
    max_age_days: int = 14
    
    # Format
    json_format: bool = False
    include_timestamps: bool = True
    include_thread_info: bool = True
    
    # Rate limiting pour éviter le spam
    rate_limit_enabled: bool = True
    rate_limit_max_per_minute: int = 100
    
    def get_log_paths(self) -> Dict[str, str]:
        """Retourne les chemins des fichiers de log"""
        log_path = Path(self.log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        return {
            'main': str(log_path / self.log_file),
            'error': str(log_path / self.error_log_file),
            'api': str(log_path / self.api_log_file),
            'archive_dir': str(Path(self.archive_dir))
        }


@dataclass
class TokenSyncQueueConfig:
    """Configuration de la queue de traitement"""
    enabled: bool = True
    
    # Paramètres de queue
    max_queue_size: int = 10000
    batch_processing_size: int = 100
    
    # Retry logic
    max_retries: int = 3
    retry_delay_base_seconds: int = 300  # 5 minutes
    retry_delay_multiplier: float = 2.0
    
    # Timeouts
    processing_timeout_minutes: int = 30
    queue_cleanup_interval_hours: int = 1
    
    # Priorités
    priority_levels: int = 5
    priority_boost_for_errors: bool = True
    
    # Rétention
    completed_items_retention_hours: int = 24
    failed_items_retention_days: int = 7
    
    def get_retry_delay(self, attempt: int) -> int:
        """Calcule le délai avant retry"""
        return int(self.retry_delay_base_seconds * (self.retry_delay_multiplier ** attempt))


# =============================================================================
# CONFIGURATION PRINCIPALE POUR TOKEN SYNC
# =============================================================================

class TokenSyncConfig:
    """Configuration principale pour le système Token Sync"""
    
    def __init__(self, environment: Optional[Union[Environment, str]] = None):
        self.environment = Environment(environment) if isinstance(environment, str) else (environment or Environment.DEVELOPMENT)
        
        # Charger la configuration principale si disponible
        self.main_config = get_main_config()
        
        # Initialiser les sous-configurations
        self.database = self._load_database_config()
        self.apis = self._load_api_config()
        self.processing = self._load_processing_config()
        self.historization = self._load_historization_config()
        self.monitoring = self._load_monitoring_config()
        self.logging = self._load_logging_config()
        self.queue = self._load_queue_config()
        
        # Appliquer les ajustements d'environnement
        self._apply_environment_overrides()
        
        # Validation
        self._validate_configuration()
    
    def _load_database_config(self) -> TokenSyncDatabaseConfig:
        """Charge la configuration de base de données"""
        return TokenSyncDatabaseConfig(
            name=os.getenv('TOKENS_SYNC_DB_NAME', 'tokens_sync.db'),
            path=os.getenv('TOKENS_SYNC_DB_PATH'),
            base_dir=os.getenv('TOKENS_SYNC_DB_BASE_DIR', 'database/tokens_sync'),
            timeout=float(os.getenv('TOKENS_SYNC_DB_TIMEOUT', '30.0')),
            backup_enabled=self._get_bool_env('TOKENS_SYNC_DB_BACKUP_ENABLED', True),
            backup_interval_hours=int(os.getenv('TOKENS_SYNC_DB_BACKUP_INTERVAL_HOURS', '12')),
            cleanup_old_data_days=int(os.getenv('TOKENS_SYNC_DB_CLEANUP_DAYS', '30'))
        )
    
    def _load_api_config(self) -> TokenSyncAPIConfig:
        """Charge la configuration des APIs"""
        return TokenSyncAPIConfig(
            dexscreener_enabled=self._get_bool_env('TOKENS_SYNC_DEXSCREENER_ENABLED', True),
            pumpfun_enabled=self._get_bool_env('TOKENS_SYNC_PUMPFUN_ENABLED', True),
            rugcheck_enabled=self._get_bool_env('TOKENS_SYNC_RUGCHECK_ENABLED', True),
            solanatracker_enabled=self._get_bool_env('TOKENS_SYNC_SOLANATRACKER_ENABLED', False),
            
            dexscreener_rate_limit=int(os.getenv('TOKENS_SYNC_DEXSCREENER_RATE_LIMIT', '60')),
            pumpfun_rate_limit=int(os.getenv('TOKENS_SYNC_PUMPFUN_RATE_LIMIT', '30')),
            rugcheck_rate_limit=int(os.getenv('TOKENS_SYNC_RUGCHECK_RATE_LIMIT', '40')),
            
            api_timeout_seconds=float(os.getenv('TOKENS_SYNC_API_TIMEOUT', '30.0')),
            max_retries=int(os.getenv('TOKENS_SYNC_API_MAX_RETRIES', '3')),
            
            dexscreener_batch_size=int(os.getenv('TOKENS_SYNC_DEXSCREENER_BATCH_SIZE', '30'))
        )
    
    def _load_processing_config(self) -> TokenSyncProcessingConfig:
        """Charge la configuration de traitement"""
        return TokenSyncProcessingConfig(
            enrichment_interval_seconds=int(os.getenv('TOKENS_SYNC_ENRICHMENT_INTERVAL', '300')),
            price_update_interval_seconds=int(os.getenv('TOKENS_SYNC_PRICE_UPDATE_INTERVAL', '600')),
            historization_interval_seconds=int(os.getenv('TOKENS_SYNC_HISTORIZATION_INTERVAL', '3600')),
            
            batch_size_new_tokens=int(os.getenv('TOKENS_SYNC_BATCH_SIZE_NEW', '100')),
            batch_size_price_updates=int(os.getenv('TOKENS_SYNC_BATCH_SIZE_UPDATES', '150')),
            batch_size_historization=int(os.getenv('TOKENS_SYNC_BATCH_SIZE_HISTORY', '50')),
            
            max_failed_attempts=int(os.getenv('TOKENS_SYNC_MAX_FAILED_ATTEMPTS', '5')),
            retry_failed_after_hours=int(os.getenv('TOKENS_SYNC_RETRY_AFTER_HOURS', '24')),
            
            rate_limit_delay=float(os.getenv('TOKENS_SYNC_RATE_LIMIT_DELAY', '0.2')),
            
            priority_tokens_enabled=self._get_bool_env('TOKENS_SYNC_PRIORITY_ENABLED', True),
            high_volume_threshold=float(os.getenv('TOKENS_SYNC_HIGH_VOLUME_THRESHOLD', '100000.0'))
        )
    
    def _load_historization_config(self) -> TokenSyncHistorizationConfig:
        """Charge la configuration d'historisation"""
        return TokenSyncHistorizationConfig(
            enabled=self._get_bool_env('TOKENS_SYNC_HISTORIZATION_ENABLED', True),
            default_interval_hours=int(os.getenv('TOKENS_SYNC_HISTORIZATION_DEFAULT_INTERVAL_HOURS', '1')),
            priority_interval_minutes=int(os.getenv('TOKENS_SYNC_HISTORIZATION_PRIORITY_INTERVAL_MINUTES', '15')),
            
            priority_volume_threshold=float(os.getenv('TOKENS_SYNC_PRIORITY_VOLUME_THRESHOLD', '50000.0')),
            priority_price_change_threshold=float(os.getenv('TOKENS_SYNC_PRIORITY_PRICE_CHANGE_THRESHOLD', '15.0')),
            priority_holder_count_threshold=int(os.getenv('TOKENS_SYNC_PRIORITY_HOLDER_COUNT_THRESHOLD', '1000')),
            
            retention_days=int(os.getenv('TOKENS_SYNC_HISTORIZATION_RETENTION_DAYS', '30')),
            analysis_enabled=self._get_bool_env('TOKENS_SYNC_ANALYSIS_ENABLED', True),
            trend_analysis_enabled=self._get_bool_env('TOKENS_SYNC_TREND_ANALYSIS_ENABLED', True)
        )
    
    def _load_monitoring_config(self) -> TokenSyncMonitoringConfig:
        """Charge la configuration de monitoring"""
        return TokenSyncMonitoringConfig(
            performance_monitoring_enabled=self._get_bool_env('TOKENS_SYNC_PERFORMANCE_MONITORING', True),
            performance_metrics_interval_seconds=int(os.getenv('TOKENS_SYNC_PERFORMANCE_INTERVAL', '30')),
            performance_retention_days=int(os.getenv('TOKENS_SYNC_PERFORMANCE_RETENTION_DAYS', '7')),
            
            api_monitoring_enabled=self._get_bool_env('TOKENS_SYNC_API_MONITORING', True),
            api_metrics_retention_days=int(os.getenv('TOKENS_SYNC_API_RETENTION_DAYS', '3')),
            slow_api_threshold_seconds=float(os.getenv('TOKENS_SYNC_SLOW_API_THRESHOLD', '5.0')),
            
            cycle_logging_enabled=self._get_bool_env('TOKENS_SYNC_CYCLE_LOGGING', True),
            cycle_history_max_size=int(os.getenv('TOKENS_SYNC_CYCLE_HISTORY_SIZE', '100')),
            
            alert_on_consecutive_failures=int(os.getenv('TOKENS_SYNC_ALERT_CONSECUTIVE_FAILURES', '5')),
            alert_on_high_error_rate=float(os.getenv('TOKENS_SYNC_ALERT_ERROR_RATE', '20.0')),
            
            calculate_trends=self._get_bool_env('TOKENS_SYNC_CALCULATE_TRENDS', True)
        )
    
    def _load_logging_config(self) -> TokenSyncLoggingConfig:
        """Charge la configuration de logging"""
        return TokenSyncLoggingConfig(
            level=os.getenv('TOKENS_SYNC_LOG_LEVEL', 'INFO'),
            console_output=self._get_bool_env('TOKENS_SYNC_LOG_CONSOLE', True),
            file_output=self._get_bool_env('TOKENS_SYNC_LOG_FILE', True),
            
            log_file=os.getenv('TOKENS_SYNC_LOG_FILE_NAME', 'tokens_sync.log'),
            error_log_file=os.getenv('TOKENS_SYNC_ERROR_LOG_FILE', 'tokens_sync_errors.log'),
            api_log_file=os.getenv('TOKENS_SYNC_API_LOG_FILE', 'tokens_sync_api.log'),
            
            log_dir=os.getenv('TOKENS_SYNC_LOG_DIR', 'logs/tokens_sync'),
            
            max_file_size_mb=int(os.getenv('TOKENS_SYNC_LOG_MAX_SIZE_MB', '50')),
            backup_count=int(os.getenv('TOKENS_SYNC_LOG_BACKUP_COUNT', '10')),
            max_age_days=int(os.getenv('TOKENS_SYNC_LOG_MAX_AGE_DAYS', '14')),
            
            json_format=self._get_bool_env('TOKENS_SYNC_LOG_JSON', False),
            rate_limit_enabled=self._get_bool_env('TOKENS_SYNC_LOG_RATE_LIMIT', True)
        )
    
    def _load_queue_config(self) -> TokenSyncQueueConfig:
        """Charge la configuration de queue"""
        return TokenSyncQueueConfig(
            enabled=self._get_bool_env('TOKENS_SYNC_QUEUE_ENABLED', True),
            max_queue_size=int(os.getenv('TOKENS_SYNC_QUEUE_MAX_SIZE', '10000')),
            batch_processing_size=int(os.getenv('TOKENS_SYNC_QUEUE_BATCH_SIZE', '100')),
            
            max_retries=int(os.getenv('TOKENS_SYNC_QUEUE_MAX_RETRIES', '3')),
            retry_delay_base_seconds=int(os.getenv('TOKENS_SYNC_QUEUE_RETRY_DELAY', '300')),
            
            processing_timeout_minutes=int(os.getenv('TOKENS_SYNC_QUEUE_TIMEOUT_MINUTES', '30')),
            queue_cleanup_interval_hours=int(os.getenv('TOKENS_SYNC_QUEUE_CLEANUP_INTERVAL', '1')),
            
            completed_items_retention_hours=int(os.getenv('TOKENS_SYNC_QUEUE_COMPLETED_RETENTION', '24')),
            failed_items_retention_days=int(os.getenv('TOKENS_SYNC_QUEUE_FAILED_RETENTION_DAYS', '7'))
        )
    
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
        # Intervalles plus courts pour le développement
        self.processing.enrichment_interval_seconds = max(60, self.processing.enrichment_interval_seconds)
        self.processing.price_update_interval_seconds = max(120, self.processing.price_update_interval_seconds)
        
        # Batches plus petits
        self.processing.batch_size_new_tokens = min(50, self.processing.batch_size_new_tokens)
        self.processing.batch_size_price_updates = min(75, self.processing.batch_size_price_updates)
        
        # Logging plus verbeux
        self.logging.level = "DEBUG"
        self.logging.console_output = True
        
        # Monitoring détaillé
        self.monitoring.performance_metrics_interval_seconds = 15
        self.monitoring.api_monitoring_enabled = True
        
        # Pas de backup en dev
        self.database.backup_enabled = False
        
        # Rate limiting plus conservateur
        self.processing.rate_limit_delay = max(0.5, self.processing.rate_limit_delay)
    
    def _apply_production_overrides(self):
        """Ajustements pour l'environnement de production"""
        # Intervalles optimisés pour la production
        self.processing.enrichment_interval_seconds = max(300, self.processing.enrichment_interval_seconds)
        
        # Batches plus gros pour l'efficacité
        self.processing.batch_size_new_tokens = min(200, max(100, self.processing.batch_size_new_tokens))
        self.processing.batch_size_price_updates = min(300, max(150, self.processing.batch_size_price_updates))
        
        # Logging optimisé
        self.logging.level = "INFO"
        self.logging.console_output = False
        self.logging.json_format = True
        
        # Monitoring moins fréquent
        self.monitoring.performance_metrics_interval_seconds = 60
        
        # Backup activé
        self.database.backup_enabled = True
        self.database.backup_interval_hours = 6
        
        # Rétention réduite
        self.monitoring.performance_retention_days = 3
        self.monitoring.api_metrics_retention_days = 1
        
        # Rate limiting optimisé
        self.processing.rate_limit_delay = 0.1
    
    def _apply_testing_overrides(self):
        """Ajustements pour l'environnement de test"""
        # Base de données de test
        self.database.name = "tokens_sync_test.db"
        self.database.base_dir = "test_data/tokens_sync"
        
        # Logs de test
        self.logging.log_dir = "test_logs/tokens_sync"
        self.logging.level = "WARNING"
        self.logging.console_output = False
        
        # Intervalles rapides pour les tests
        self.processing.enrichment_interval_seconds = 30
        self.processing.price_update_interval_seconds = 60
        
        # Batches réduits
        self.processing.batch_size_new_tokens = 10
        self.processing.batch_size_price_updates = 15
        
        # Pas de backup
        self.database.backup_enabled = False
        
        # Monitoring minimal
        self.monitoring.performance_monitoring_enabled = False
        self.monitoring.api_monitoring_enabled = False
        
        # Rétention très courte
        self.historization.retention_days = 1
        self.monitoring.performance_retention_days = 1
    
    def _apply_staging_overrides(self):
        """Ajustements pour l'environnement de staging"""
        # Configuration proche de la production mais avec plus de logging
        self.logging.level = "DEBUG"
        self.logging.console_output = True
        
        # Base de données de staging
        self.database.name = "tokens_sync_staging.db"
        
        # Monitoring détaillé
        self.monitoring.performance_monitoring_enabled = True
        self.monitoring.api_monitoring_enabled = True
        
        # Backup activé mais moins fréquent
        self.database.backup_enabled = True
        self.database.backup_interval_hours = 12
    
    def _validate_configuration(self):
        """Valide la cohérence de la configuration"""
        errors = []
        warnings = []
        
        # Validation du processing
        processing_errors = self.processing.validate()
        errors.extend(processing_errors)
        
        # Validation des intervalles
        if self.processing.enrichment_interval_seconds < 60:
            warnings.append("Enrichment interval très court, risque de rate limiting")
        
        if self.processing.price_update_interval_seconds < self.processing.enrichment_interval_seconds:
            warnings.append("Price update interval plus court que enrichment interval")
        
        # Validation des batches
        total_batch_size = (self.processing.batch_size_new_tokens + 
                           self.processing.batch_size_price_updates)
        if total_batch_size > 500:
            warnings.append("Taille totale des batches très élevée")
        
        # Validation de la base de données
        if self.database.timeout < 10:
            warnings.append("Timeout de base de données très court")
        
        # Validation APIs
        enabled_apis = self.apis.get_enabled_apis()
        if not enabled_apis:
            errors.append("Aucune API activée")
        elif len(enabled_apis) < 2:
            warnings.append("Une seule API activée, pas de fallback")
        
        # Validation historisation
        if (self.historization.enabled and 
            self.historization.retention_days < 7):
            warnings.append("Rétention d'historisation très courte")
        
        # Validation monitoring
        if (self.monitoring.performance_metrics_interval_seconds > 
            self.processing.enrichment_interval_seconds):
            warnings.append("Intervalle de monitoring plus long que le cycle")
        
        # Validation logging
        try:
            log_paths = self.logging.get_log_paths()
            for path_type, path in log_paths.items():
                log_dir = Path(path).parent if path_type != 'archive_dir' else Path(path)
                if not log_dir.exists():
                    log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            warnings.append(f"Problème avec les répertoires de log: {e}")
        
        # Lever les erreurs critiques
        if errors:
            raise ConfigurationError(f"Erreurs de configuration Token Sync: {'; '.join(errors)}")
        
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
            'database': {
                'path': self.database.get_full_path(),
                'backup_enabled': self.database.backup_enabled,
                'backup_dir': self.database.get_backup_dir(),
                'timeout': self.database.timeout,
                'cleanup_days': self.database.cleanup_old_data_days
            },
            'apis': {
                'enabled': self.apis.get_enabled_apis(),
                'dexscreener_batch_size': self.apis.dexscreener_batch_size,
                'api_timeout': self.apis.api_timeout_seconds,
                'max_retries': self.apis.max_retries
            },
            'processing': {
                'enrichment_interval': self.processing.enrichment_interval_seconds,
                'price_update_interval': self.processing.price_update_interval_seconds,
                'historization_interval': self.processing.historization_interval_seconds,
                'batch_size_new': self.processing.batch_size_new_tokens,
                'batch_size_updates': self.processing.batch_size_price_updates,
                'batch_size_history': self.processing.batch_size_historization,
                'rate_limit_delay': self.processing.rate_limit_delay,
                'priority_enabled': self.processing.priority_tokens_enabled
            },
            'historization': {
                'enabled': self.historization.enabled,
                'default_interval_hours': self.historization.default_interval_hours,
                'priority_interval_minutes': self.historization.priority_interval_minutes,
                'retention_days': self.historization.retention_days,
                'analysis_enabled': self.historization.analysis_enabled,
                'priority_criteria': self.historization.get_priority_criteria()
            },
            'monitoring': {
                'performance_enabled': self.monitoring.performance_monitoring_enabled,
                'api_monitoring_enabled': self.monitoring.api_monitoring_enabled,
                'cycle_logging_enabled': self.monitoring.cycle_logging_enabled,
                'performance_interval': self.monitoring.performance_metrics_interval_seconds,
                'retention_days': self.monitoring.performance_retention_days,
                'alert_thresholds': {
                    'consecutive_failures': self.monitoring.alert_on_consecutive_failures,
                    'error_rate': self.monitoring.alert_on_high_error_rate,
                    'slow_processing': self.monitoring.alert_on_slow_processing
                }
            },
            'logging': {
                'level': self.logging.level,
                'console_output': self.logging.console_output,
                'file_output': self.logging.file_output,
                'log_paths': self.logging.get_log_paths(),
                'json_format': self.logging.json_format,
                'max_file_size_mb': self.logging.max_file_size_mb,
                'retention_days': self.logging.max_age_days
            },
            'queue': {
                'enabled': self.queue.enabled,
                'max_size': self.queue.max_queue_size,
                'batch_size': self.queue.batch_processing_size,
                'max_retries': self.queue.max_retries,
                'timeout_minutes': self.queue.processing_timeout_minutes,
                'retention_hours': self.queue.completed_items_retention_hours
            }
        }
    
    def save_to_file(self, file_path: str):
        """Sauvegarde la configuration dans un fichier JSON"""
        import json
        
        try:
            config_dict = self.to_dict()
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Token Sync configuration sauvegardée dans {file_path}")
        except Exception as e:
            print(f"❌ Erreur sauvegarde configuration Token Sync: {e}")
    
    def get_summary(self) -> str:
        """Retourne un résumé de la configuration"""
        enabled_apis = ', '.join(self.apis.get_enabled_apis())
        
        summary_lines = [
            f"🔧 Configuration Token Sync System",
            f"   Environnement: {self.environment.value.upper()}",
            f"   Base de données: {self.database.get_full_path()}",
            f"   APIs activées: {enabled_apis}",
            f"   Intervalles (sec): Enrichment={self.processing.enrichment_interval_seconds}, "
            f"Prix={self.processing.price_update_interval_seconds}, "
            f"Historisation={self.processing.historization_interval_seconds}",
            f"   Tailles de batch: New={self.processing.batch_size_new_tokens}, "
            f"Updates={self.processing.batch_size_price_updates}, "
            f"History={self.processing.batch_size_historization}",
            f"   Rate limit delay: {self.processing.rate_limit_delay}s",
            f"   Historisation: {'✅ Activée' if self.historization.enabled else '❌ Désactivée'}",
            f"   Rétention historique: {self.historization.retention_days} jours",
            f"   Monitoring: {'✅ Activé' if self.monitoring.performance_monitoring_enabled else '❌ Désactivé'}",
            f"   Queue: {'✅ Activée' if self.queue.enabled else '❌ Désactivée'}",
            f"   Logs: {self.logging.level} vers {self.logging.get_log_paths()['main']}",
            f"   Backup DB: {'✅ Activé' if self.database.backup_enabled else '❌ Désactivé'}"
        ]
        
        if self.get_warnings():
            summary_lines.append("⚠️ Avertissements:")
            for warning in self.get_warnings():
                summary_lines.append(f"   - {warning}")
        
        return "\n".join(summary_lines)
    
    def export_env_template(self, file_path: str = "tokens_sync.env.template"):
        """Exporte un template de fichier .env pour Token Sync"""
        template_lines = [
            "# =============================================================================",
            "# CONFIGURATION TOKEN SYNC SYSTEM",
            "# Template de variables d'environnement",
            "# =============================================================================",
            "",
            "# Environnement",
            "# Valeurs possibles: development, production, testing, staging",
            "ENVIRONMENT=development",
            "",
            "# =============================================================================",
            "# BASE DE DONNÉES",
            "# =============================================================================",
            "",
            "# Nom de la base de données",
            "TOKENS_SYNC_DB_NAME=tokens_sync.db",
            "",
            "# Chemin personnalisé (optionnel)",
            "# TOKENS_SYNC_DB_PATH=/custom/path",
            "",
            "# Répertoire de base",
            "TOKENS_SYNC_DB_BASE_DIR=database/tokens_sync",
            "",
            "# Timeout de connexion (secondes)",
            "TOKENS_SYNC_DB_TIMEOUT=30.0",
            "",
            "# Backup automatique",
            "TOKENS_SYNC_DB_BACKUP_ENABLED=true",
            "TOKENS_SYNC_DB_BACKUP_INTERVAL_HOURS=12",
            "",
            "# Nettoyage des données anciennes (jours)",
            "TOKENS_SYNC_DB_CLEANUP_DAYS=30",
            "",
            "# =============================================================================",
            "# APIS",
            "# =============================================================================",
            "",
            "# Activation des APIs",
            "TOKENS_SYNC_DEXSCREENER_ENABLED=true",
            "TOKENS_SYNC_PUMPFUN_ENABLED=true",
            "TOKENS_SYNC_RUGCHECK_ENABLED=true",
            "TOKENS_SYNC_SOLANATRACKER_ENABLED=false",
            "",
            "# Rate limits (appels par minute)",
            "TOKENS_SYNC_DEXSCREENER_RATE_LIMIT=60",
            "TOKENS_SYNC_PUMPFUN_RATE_LIMIT=30",
            "TOKENS_SYNC_RUGCHECK_RATE_LIMIT=40",
            "",
            "# Timeouts",
            "TOKENS_SYNC_API_TIMEOUT=30.0",
            "TOKENS_SYNC_API_MAX_RETRIES=3",
            "",
            "# Tailles de batch",
            "TOKENS_SYNC_DEXSCREENER_BATCH_SIZE=30",
            "",
            "# =============================================================================",
            "# TRAITEMENT",
            "# =============================================================================",
            "",
            "# Intervalles de traitement (secondes)",
            "TOKENS_SYNC_ENRICHMENT_INTERVAL=300",
            "TOKENS_SYNC_PRICE_UPDATE_INTERVAL=600",
            "TOKENS_SYNC_HISTORIZATION_INTERVAL=3600",
            "",
            "# Tailles de batch",
            "TOKENS_SYNC_BATCH_SIZE_NEW=100",
            "TOKENS_SYNC_BATCH_SIZE_UPDATES=150",
            "TOKENS_SYNC_BATCH_SIZE_HISTORY=50",
            "",
            "# Gestion des échecs",
            "TOKENS_SYNC_MAX_FAILED_ATTEMPTS=5",
            "TOKENS_SYNC_RETRY_AFTER_HOURS=24",
            "",
            "# Rate limiting",
            "TOKENS_SYNC_RATE_LIMIT_DELAY=0.2",
            "",
            "# Priorisation des tokens",
            "TOKENS_SYNC_PRIORITY_ENABLED=true",
            "TOKENS_SYNC_HIGH_VOLUME_THRESHOLD=100000.0",
            "",
            "# =============================================================================",
            "# HISTORISATION",
            "# =============================================================================",
            "",
            "# Activation",
            "TOKENS_SYNC_HISTORIZATION_ENABLED=true",
            "",
            "# Intervalles",
            "TOKENS_SYNC_HISTORIZATION_DEFAULT_INTERVAL_HOURS=1",
            "TOKENS_SYNC_HISTORIZATION_PRIORITY_INTERVAL_MINUTES=15",
            "",
            "# Critères de priorité",
            "TOKENS_SYNC_PRIORITY_VOLUME_THRESHOLD=50000.0",
            "TOKENS_SYNC_PRIORITY_PRICE_CHANGE_THRESHOLD=15.0",
            "TOKENS_SYNC_PRIORITY_HOLDER_COUNT_THRESHOLD=1000",
            "",
            "# Rétention",
            "TOKENS_SYNC_HISTORIZATION_RETENTION_DAYS=30",
            "",
            "# Analyse",
            "TOKENS_SYNC_ANALYSIS_ENABLED=true",
            "TOKENS_SYNC_TREND_ANALYSIS_ENABLED=true",
            "",
            "# =============================================================================",
            "# MONITORING",
            "# =============================================================================",
            "",
            "# Activation du monitoring",
            "TOKENS_SYNC_PERFORMANCE_MONITORING=true",
            "TOKENS_SYNC_API_MONITORING=true",
            "TOKENS_SYNC_CYCLE_LOGGING=true",
            "",
            "# Intervalles et rétention",
            "TOKENS_SYNC_PERFORMANCE_INTERVAL=30",
            "TOKENS_SYNC_PERFORMANCE_RETENTION_DAYS=7",
            "TOKENS_SYNC_API_RETENTION_DAYS=3",
            "",
            "# Seuils d'alerte",
            "TOKENS_SYNC_SLOW_API_THRESHOLD=5.0",
            "TOKENS_SYNC_ALERT_CONSECUTIVE_FAILURES=5",
            "TOKENS_SYNC_ALERT_ERROR_RATE=20.0",
            "",
            "# Historique des cycles",
            "TOKENS_SYNC_CYCLE_HISTORY_SIZE=100",
            "",
            "# Calculs de tendances",
            "TOKENS_SYNC_CALCULATE_TRENDS=true",
            "",
            "# =============================================================================",
            "# LOGGING",
            "# =============================================================================",
            "",
            "# Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
            "TOKENS_SYNC_LOG_LEVEL=INFO",
            "",
            "# Sorties",
            "TOKENS_SYNC_LOG_CONSOLE=true",
            "TOKENS_SYNC_LOG_FILE=true",
            "",
            "# Fichiers de log",
            "TOKENS_SYNC_LOG_FILE_NAME=tokens_sync.log",
            "TOKENS_SYNC_ERROR_LOG_FILE=tokens_sync_errors.log",
            "TOKENS_SYNC_API_LOG_FILE=tokens_sync_api.log",
            "",
            "# Répertoires",
            "TOKENS_SYNC_LOG_DIR=logs/tokens_sync",
            "",
            "# Rotation",
            "TOKENS_SYNC_LOG_MAX_SIZE_MB=50",
            "TOKENS_SYNC_LOG_BACKUP_COUNT=10",
            "TOKENS_SYNC_LOG_MAX_AGE_DAYS=14",
            "",
            "# Format",
            "TOKENS_SYNC_LOG_JSON=false",
            "TOKENS_SYNC_LOG_RATE_LIMIT=true",
            "",
            "# =============================================================================",
            "# QUEUE DE TRAITEMENT",
            "# =============================================================================",
            "",
            "# Activation",
            "TOKENS_SYNC_QUEUE_ENABLED=true",
            "",
            "# Paramètres",
            "TOKENS_SYNC_QUEUE_MAX_SIZE=10000",
            "TOKENS_SYNC_QUEUE_BATCH_SIZE=100",
            "",
            "# Retry logic",
            "TOKENS_SYNC_QUEUE_MAX_RETRIES=3",
            "TOKENS_SYNC_QUEUE_RETRY_DELAY=300",
            "",
            "# Timeouts",
            "TOKENS_SYNC_QUEUE_TIMEOUT_MINUTES=30",
            "TOKENS_SYNC_QUEUE_CLEANUP_INTERVAL=1",
            "",
            "# Rétention",
            "TOKENS_SYNC_QUEUE_COMPLETED_RETENTION=24",
            "TOKENS_SYNC_QUEUE_FAILED_RETENTION_DAYS=7",
            ""
        ]
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(template_lines))
            
            print(f"✅ Template .env exporté vers {file_path}")
            return file_path
        except Exception as e:
            print(f"❌ Erreur export template: {e}")
            return ""
    
    def update_from_main_config(self):
        """Met à jour avec la configuration principale si disponible"""
        if not self.main_config:
            return
        
        try:
            # Synchroniser certains paramètres avec la config principale
            if hasattr(self.main_config, 'database') and hasattr(self.main_config.database, 'timeout'):
                self.database.timeout = self.main_config.database.timeout
            
            if hasattr(self.main_config, 'logging') and hasattr(self.main_config.logging, 'level'):
                if not os.getenv('TOKENS_SYNC_LOG_LEVEL'):
                    self.logging.level = self.main_config.logging.level.value
            
            if hasattr(self.main_config, 'monitoring') and hasattr(self.main_config.monitoring, 'rate_limit_delay'):
                if not os.getenv('TOKENS_SYNC_RATE_LIMIT_DELAY'):
                    self.processing.rate_limit_delay = self.main_config.monitoring.rate_limit_delay
            
            print("📄 Configuration Token Sync synchronisée avec la configuration principale")
            
        except Exception as e:
            print(f"⚠️ Erreur synchronisation avec config principale: {e}")


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def create_tokens_sync_config(
    environment: Optional[Union[Environment, str]] = None,
    config_file: Optional[str] = None,
    env_file: Optional[str] = None
) -> TokenSyncConfig:
    """
    Crée une instance de configuration Token Sync
    
    Args:
        environment: Environnement cible
        config_file: Fichier de configuration JSON (optionnel)
        env_file: Fichier .env à charger (optionnel)
    
    Returns:
        Instance de configuration Token Sync
    """
    # Charger le fichier .env si spécifié
    if env_file:
        load_env_file(env_file)
    
    # Créer la configuration
    config = TokenSyncConfig(environment=environment)
    
    # Charger depuis un fichier JSON si spécifié
    if config_file:
        apply_json_config_overrides(config, config_file)
    
    # Synchroniser avec la config principale
    config.update_from_main_config()
    
    return config


def load_env_file(env_file_path: str):
    """Charge les variables d'environnement depuis un fichier .env"""
    from pathlib import Path
    
    env_path = Path(env_file_path)
    if not env_path.exists():
        print(f"⚠️ Fichier .env non trouvé: {env_file_path}")
        return
    
    loaded_vars = 0
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Ignorer les commentaires et lignes vides
                if not line or line.startswith('#'):
                    continue
                
                # Parser KEY=VALUE
                if '=' not in line:
                    continue
                
                try:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Supprimer les guillemets optionnels
                    if len(value) >= 2:
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                    
                    # Définir la variable d'environnement
                    if key not in os.environ:
                        os.environ[key] = value
                        loaded_vars += 1
                        
                except ValueError:
                    continue
        
        if loaded_vars > 0:
            print(f"✅ Chargé {loaded_vars} variables d'environnement depuis {env_file_path}")
            
    except Exception as e:
        print(f"❌ Erreur lecture fichier .env {env_file_path}: {e}")


def apply_json_config_overrides(config: TokenSyncConfig, config_file: str):
    """Applique des overrides depuis un fichier JSON"""
    import json
    from pathlib import Path
    
    config_path = Path(config_file)
    if not config_path.exists():
        print(f"⚠️ Fichier de configuration non trouvé: {config_file}")
        return
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            json_config = json.load(f)
        
        # Appliquer les overrides par section
        if 'processing' in json_config:
            processing_config = json_config['processing']
            for key, value in processing_config.items():
                if hasattr(config.processing, key):
                    setattr(config.processing, key, value)
        
        if 'database' in json_config:
            db_config = json_config['database']
            for key, value in db_config.items():
                if hasattr(config.database, key):
                    setattr(config.database, key, value)
        
        if 'apis' in json_config:
            api_config = json_config['apis']
            for key, value in api_config.items():
                if hasattr(config.apis, key):
                    setattr(config.apis, key, value)
        
        if 'monitoring' in json_config:
            monitoring_config = json_config['monitoring']
            for key, value in monitoring_config.items():
                if hasattr(config.monitoring, key):
                    setattr(config.monitoring, key, value)
        
        if 'logging' in json_config:
            logging_config = json_config['logging']
            for key, value in logging_config.items():
                if hasattr(config.logging, key):
                    setattr(config.logging, key, value)
        
        print(f"✅ Configuration JSON appliquée depuis {config_file}")
        
    except Exception as e:
        print(f"❌ Erreur application config JSON: {e}")


def get_tokens_sync_config() -> TokenSyncConfig:
    """Fonction helper pour obtenir une configuration Token Sync"""
    return create_tokens_sync_config()


# =============================================================================
# EXPORT DES CLASSES ET FONCTIONS PRINCIPALES
# =============================================================================

__all__ = [
    # Classes de configuration
    'TokenSyncConfig',
    'TokenSyncDatabaseConfig',
    'TokenSyncAPIConfig', 
    'TokenSyncProcessingConfig',
    'TokenSyncHistorizationConfig',
    'TokenSyncMonitoringConfig',
    'TokenSyncLoggingConfig',
    'TokenSyncQueueConfig',
    
    # Fonctions utilitaires
    'create_tokens_sync_config',
    'get_tokens_sync_config',
    'load_env_file',
    'apply_json_config_overrides',
    
    # Exceptions et enums
    'Environment',
    'ConfigurationError'
]


# =============================================================================
# TEST ET VALIDATION
# =============================================================================

if __name__ == "__main__":
    print("🧪 Test de la configuration Token Sync")
    
    # Test de création de configuration
    config = create_tokens_sync_config(Environment.DEVELOPMENT)
    print("\n" + "="*80)
    print(config.get_summary())
    
    # Test d'export template
    template_file = config.export_env_template("test_tokens_sync.env.template")
    if template_file:
        print(f"\n📄 Template exporté: {template_file}")
    
    # Test de sauvegarde
    config.save_to_file("test_tokens_sync_config.json")
    
    print("\n✅ Tests de configuration Token Sync terminés")