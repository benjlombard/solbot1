#!/usr/bin/env python3
"""
Configuration dédiée pour l'interface Streamlit
Module de configuration léger et spécialisé pour les dashboards
"""

import os
import sqlite3
from typing import Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import logging

# Logging simple pour la config Streamlit
logger = logging.getLogger('streamlit_config')

class StreamlitEnvironment(Enum):
    """Environnements pour Streamlit"""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    DEMO = "demo"

@dataclass
class StreamlitDatabaseConfig:
    """Configuration base de données pour Streamlit"""
    # Chemins spécifiques par page
    main_dashboard: str = "database/data/solana_wallet_monitor.db"
    opportunities: str = "database/data/solana_wallet_monitor.db"
    monitoring_realtime: str = "database/data/solana_wallet_monitor.db"
    historic_detail: str = "database/data/solana_wallet_monitor.db"
    performance_wallets: str = "database/data/solana_wallet_monitor.db"
    
    # Paramètres de connexion
    timeout: float = 30.0
    check_same_thread: bool = False
    
    def get_db_path(self, page: str = "main") -> str:
        """Retourne le chemin de la DB pour une page donnée"""
        mapping = {
            "main": self.main_dashboard,
            "opportunities": self.opportunities,
            "monitoring": self.monitoring_realtime,
            "historic": self.historic_detail,
            "performance": self.performance_wallets
        }
        # CORRECTION: Convertir en chemin absolu basé sur la position du fichier config.py
        relative_path = mapping.get(page, self.main_dashboard)
        
        # Si le chemin ne commence pas par ../, l'ajouter
        if not relative_path.startswith('../') and not os.path.isabs(relative_path):
            relative_path = f"../{relative_path}"
        
        # Résoudre le chemin absolu depuis le répertoire du fichier config.py
        config_dir = Path(__file__).parent  # Répertoire où se trouve config.py (streamlit/)
        absolute_path = (config_dir / relative_path).resolve()
        
        return str(absolute_path)
    
    def validate_db_path(self, db_path: str) -> bool:
        """Valide qu'une base de données est accessible"""
        try:
            path_obj = Path(db_path)
            if not path_obj.exists():
                logger.warning(f"Base de données non trouvée: {db_path}")
                return False
            
            # Test de connexion rapide
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.execute("SELECT 1").fetchone()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Erreur validation DB {db_path}: {e}")
            return False

@dataclass
class StreamlitUIConfig:
    """Configuration interface utilisateur"""
    refresh_interval: int = 30  # secondes
    max_tokens_display: int = 100
    auto_refresh_default: bool = False
    
    # Pagination
    items_per_page: int = 20
    max_items_per_page: int = 200
    
    # Cache
    cache_ttl_seconds: int = 60
    cache_max_entries: int = 1000
    
    # Thème et apparence
    page_icon: str = "🪙"
    layout: str = "wide"
    initial_sidebar_state: str = "expanded"

@dataclass
class StreamlitPerformanceConfig:
    """Configuration performance et optimisation"""
    # Limites de données
    max_chart_points: int = 1000
    max_dataframe_rows: int = 5000
    chart_height_default: int = 400
    
    # Optimisations
    enable_caching: bool = True
    enable_compression: bool = True
    lazy_loading: bool = True
    
    # Timeouts
    query_timeout: int = 30
    chart_render_timeout: int = 10

@dataclass
class StreamlitFeaturesConfig:
    """Configuration des fonctionnalités disponibles"""
    # Modules activés
    opportunities_enabled: bool = True
    monitoring_enabled: bool = True
    historic_enabled: bool = True
    performance_enabled: bool = True
    
    # Fonctionnalités avancées
    export_enabled: bool = True
    advanced_filters: bool = True
    real_time_updates: bool = True
    
    # Développement
    debug_mode: bool = False
    show_sql_queries: bool = False

class StreamlitConfig:
    """Configuration principale pour Streamlit"""
    
    def __init__(self, environment: StreamlitEnvironment = StreamlitEnvironment.DEVELOPMENT):
        self.environment = environment
        
        # Charger les configurations
        self.database = self._load_database_config()
        self.ui = self._load_ui_config()
        self.performance = self._load_performance_config()
        self.features = self._load_features_config()
        
        # Appliquer les ajustements d'environnement
        self._apply_environment_settings()
        
        # Validation
        self._validate_configuration()
    
    def _load_database_config(self) -> StreamlitDatabaseConfig:
        """Charge la configuration base de données"""
        return StreamlitDatabaseConfig(
            main_dashboard=os.getenv('STREAMLIT_DB_PATH', 'database/data/solana_wallet_monitor.db'),
            opportunities=os.getenv('TRADING_OPPORTUNITIES_DB_PATH', 'database/data/solana_wallet_monitor.db'),
            monitoring_realtime=os.getenv('MONITORING_REALTIME_DB_PATH', 'database/data/solana_wallet_monitor.db'),
            historic_detail=os.getenv('DETAIL_HISTORIC_DB_PATH', 'database/data/solana_wallet_monitor.db'),
            performance_wallets=os.getenv('PERFORMANCE_WALLET_DB_PATH', 'database/data/solana_wallet_monitor.db'),
            timeout=float(os.getenv('STREAMLIT_DB_TIMEOUT', 30.0)),
            check_same_thread=False
        )
    
    def _load_ui_config(self) -> StreamlitUIConfig:
        """Charge la configuration UI"""
        return StreamlitUIConfig(
            refresh_interval=int(os.getenv('STREAMLIT_REFRESH_INTERVAL', 30)),
            max_tokens_display=int(os.getenv('STREAMLIT_MAX_TOKENS_DISPLAY', 100)),
            auto_refresh_default=self._get_bool_env('STREAMLIT_AUTO_REFRESH_DEFAULT', False),
            items_per_page=int(os.getenv('STREAMLIT_ITEMS_PER_PAGE', 20)),
            max_items_per_page=int(os.getenv('STREAMLIT_MAX_ITEMS_PER_PAGE', 200)),
            cache_ttl_seconds=int(os.getenv('STREAMLIT_CACHE_TTL', 60)),
            page_icon=os.getenv('STREAMLIT_PAGE_ICON', '🪙'),
            layout=os.getenv('STREAMLIT_LAYOUT', 'wide'),
            initial_sidebar_state=os.getenv('STREAMLIT_SIDEBAR_STATE', 'expanded')
        )
    
    def _load_performance_config(self) -> StreamlitPerformanceConfig:
        """Charge la configuration performance"""
        return StreamlitPerformanceConfig(
            max_chart_points=int(os.getenv('STREAMLIT_MAX_CHART_POINTS', 1000)),
            max_dataframe_rows=int(os.getenv('STREAMLIT_MAX_DATAFRAME_ROWS', 5000)),
            chart_height_default=int(os.getenv('STREAMLIT_CHART_HEIGHT', 400)),
            enable_caching=self._get_bool_env('STREAMLIT_ENABLE_CACHING', True),
            enable_compression=self._get_bool_env('STREAMLIT_ENABLE_COMPRESSION', True),
            lazy_loading=self._get_bool_env('STREAMLIT_LAZY_LOADING', True),
            query_timeout=int(os.getenv('STREAMLIT_QUERY_TIMEOUT', 30)),
            chart_render_timeout=int(os.getenv('STREAMLIT_CHART_TIMEOUT', 10))
        )
    
    def _load_features_config(self) -> StreamlitFeaturesConfig:
        """Charge la configuration des fonctionnalités"""
        return StreamlitFeaturesConfig(
            opportunities_enabled=self._get_bool_env('STREAMLIT_OPPORTUNITIES_ENABLED', True),
            monitoring_enabled=self._get_bool_env('STREAMLIT_MONITORING_ENABLED', True),
            historic_enabled=self._get_bool_env('STREAMLIT_HISTORIC_ENABLED', True),
            performance_enabled=self._get_bool_env('STREAMLIT_PERFORMANCE_ENABLED', True),
            export_enabled=self._get_bool_env('STREAMLIT_EXPORT_ENABLED', True),
            advanced_filters=self._get_bool_env('STREAMLIT_ADVANCED_FILTERS', True),
            real_time_updates=self._get_bool_env('STREAMLIT_REAL_TIME_UPDATES', True),
            debug_mode=self._get_bool_env('STREAMLIT_DEBUG_MODE', False),
            show_sql_queries=self._get_bool_env('STREAMLIT_SHOW_SQL_QUERIES', False)
        )
    
    def _apply_environment_settings(self):
        """Applique les paramètres spécifiques à l'environnement"""
        if self.environment == StreamlitEnvironment.DEVELOPMENT:
            self.features.debug_mode = True
            self.features.show_sql_queries = True
            self.ui.cache_ttl_seconds = 30  # Cache plus court en dev
            self.performance.enable_compression = False  # Désactiver pour debug
            
        elif self.environment == StreamlitEnvironment.PRODUCTION:
            self.features.debug_mode = False
            self.features.show_sql_queries = False
            self.ui.cache_ttl_seconds = 120  # Cache plus long en prod
            self.performance.enable_compression = True
            self.ui.max_tokens_display = 50  # Limiter en prod
            
        elif self.environment == StreamlitEnvironment.DEMO:
            self.ui.auto_refresh_default = True
            self.ui.refresh_interval = 60  # Plus lent pour demo
            self.ui.max_tokens_display = 25
            self.performance.max_chart_points = 500  # Limiter pour performance
    
    def _validate_configuration(self):
        """Valide la configuration"""
        errors = []
        warnings = []
        
        # Validation bases de données
        db_paths = [
            self.database.main_dashboard,
            self.database.opportunities,
            self.database.monitoring_realtime,
            self.database.historic_detail,
            self.database.performance_wallets
        ]
        
        for db_path in set(db_paths):  # Unique paths only
            if not self.database.validate_db_path(db_path):
                warnings.append(f"Base de données non accessible: {db_path}")
        
        # Validation UI
        if self.ui.refresh_interval < 10:
            warnings.append("Intervalle de rafraîchissement très court (< 10s)")
        
        if self.ui.max_tokens_display > 500:
            warnings.append("Nombre max de tokens très élevé (> 500)")
        
        # Validation performance
        if self.performance.max_chart_points > 5000:
            warnings.append("Trop de points dans les graphiques (> 5000)")
        
        if self.performance.query_timeout < 10:
            warnings.append("Timeout de requête très court (< 10s)")
        
        # Stocker les avertissements
        self._warnings = warnings
        self._errors = errors
        
        # Log des problèmes
        for warning in warnings:
            logger.warning(warning)
        
        for error in errors:
            logger.error(error)
    
    def _get_bool_env(self, key: str, default: bool = False) -> bool:
        """Récupère une variable d'environnement booléenne"""
        value = os.getenv(key, str(default)).lower()
        return value in ('true', '1', 'yes', 'on', 'enabled')
    
    def get_db_connection(self, page: str = "main") -> sqlite3.Connection:
        """Obtient une connexion à la base de données"""
        db_path = self.database.get_db_path(page)
        
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Base de données non trouvée: {db_path}")
        
        conn = sqlite3.connect(
            db_path,
            timeout=self.database.timeout,
            check_same_thread=self.database.check_same_thread
        )
        
        # Configuration SQLite optimisée pour lecture
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=memory")
        
        return conn
    
    def get_page_config(self) -> Dict[str, Any]:
        """Retourne la configuration pour st.set_page_config()"""
        return {
            "page_title": "Token Analysis Dashboard",
            "page_icon": self.ui.page_icon,
            "layout": self.ui.layout,
            "initial_sidebar_state": self.ui.initial_sidebar_state
        }
    
    def get_warnings(self):
        """Retourne les avertissements de configuration"""
        return getattr(self, '_warnings', [])
    
    def get_errors(self):
        """Retourne les erreurs de configuration"""
        return getattr(self, '_errors', [])
    
    def is_feature_enabled(self, feature: str) -> bool:
        """Vérifie si une fonctionnalité est activée"""
        return getattr(self.features, f"{feature}_enabled", False)
    
    def get_summary(self) -> str:
        """Retourne un résumé de la configuration"""
        db_status = "✅" if self.database.validate_db_path(self.database.main_dashboard) else "❌"
        
        return f"""
🔧 Configuration Streamlit
   Environnement: {self.environment.value.upper()}
   Base de données: {db_status} {self.database.main_dashboard}
   Rafraîchissement: {self.ui.refresh_interval}s
   Max tokens affichés: {self.ui.max_tokens_display}
   Cache TTL: {self.ui.cache_ttl_seconds}s
   Fonctionnalités: {sum([
       self.features.opportunities_enabled,
       self.features.monitoring_enabled,
       self.features.historic_enabled,
       self.features.performance_enabled
   ])}/4 activées
   Mode debug: {'✅' if self.features.debug_mode else '❌'}
"""

# Instance globale
_global_streamlit_config: Optional[StreamlitConfig] = None

def get_streamlit_config(environment: Optional[StreamlitEnvironment] = None) -> StreamlitConfig:
    """Retourne l'instance globale de configuration Streamlit"""
    global _global_streamlit_config
    
    if _global_streamlit_config is None:
        if environment is None:
            # Déterminer l'environnement depuis les variables
            env_name = os.getenv('STREAMLIT_ENVIRONMENT', 'development').lower()
            try:
                environment = StreamlitEnvironment(env_name)
            except ValueError:
                environment = StreamlitEnvironment.DEVELOPMENT
        
        _global_streamlit_config = StreamlitConfig(environment)
    
    return _global_streamlit_config

def reload_streamlit_config():
    """Recharge la configuration Streamlit"""
    global _global_streamlit_config
    _global_streamlit_config = None
    return get_streamlit_config()

# Fonctions utilitaires pour l'intégration
def get_db_path(page: str = "main") -> str:
    """Fonction utilitaire pour obtenir le chemin DB d'une page"""
    config = get_streamlit_config()
    return config.database.get_db_path(page)

def get_refresh_interval() -> int:
    """Fonction utilitaire pour obtenir l'intervalle de rafraîchissement"""
    config = get_streamlit_config()
    return config.ui.refresh_interval

def is_debug_mode() -> bool:
    """Fonction utilitaire pour vérifier le mode debug"""
    config = get_streamlit_config()
    return config.features.debug_mode

# Export des principales classes et fonctions
__all__ = [
    'StreamlitConfig',
    'StreamlitEnvironment', 
    'StreamlitDatabaseConfig',
    'StreamlitUIConfig',
    'StreamlitPerformanceConfig',
    'StreamlitFeaturesConfig',
    'get_streamlit_config',
    'reload_streamlit_config',
    'get_db_path',
    'get_refresh_interval',
    'is_debug_mode'
]

if __name__ == "__main__":
    # Test de la configuration
    print("🧪 Test de la configuration Streamlit")
    
    config = get_streamlit_config()
    print(config.get_summary())
    
    if config.get_warnings():
        print("\n⚠️ Avertissements:")
        for warning in config.get_warnings():
            print(f"  - {warning}")