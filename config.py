"""
Configuration complète pour le Solana Trading Bot
File: config.py

Ce fichier contient toute la configuration du bot de trading :
- Paramètres de trading
- Configuration des APIs
- Paramètres de base de données
- Seuils de sécurité
- Configuration des notifications
"""

import os
from pathlib import Path


def load_env_file():
    """Charge automatiquement le fichier .env s'il existe"""
    env_file = Path(__file__).parent / '.env'
    
    if env_file.exists():
        print(f"📁 Loading environment from: {env_file}")
        
        try:
            # Méthode 1: Essayer avec python-dotenv si disponible
            from dotenv import load_dotenv
            load_dotenv(env_file)
            print("✅ Environment loaded with python-dotenv")
            return True
        except ImportError:
            # Méthode 2: Chargement manuel si python-dotenv n'est pas installé
            print("⚠️ python-dotenv not found, loading manually...")
            
            try:
                with open(env_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        
                        # Ignorer les commentaires et lignes vides
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Enlever les guillemets si présents
                            if (value.startswith('"') and value.endswith('"')) or \
                               (value.startswith("'") and value.endswith("'")):
                                value = value[1:-1]
                            
                            os.environ[key] = value
                            print(f"   ✅ {key}={'*' * min(len(value), 8) if 'KEY' in key else value}")
                
                print("✅ Environment loaded manually")
                return True
                
            except Exception as e:
                print(f"❌ Error loading .env manually: {e}")
                return False
    else:
        print(f"⚠️ No .env file found at: {env_file}")
        print("💡 Create one with: SOLANA_PRIVATE_KEY=your_key_here")
        return False

# Charger automatiquement au démarrage du module
load_env_file()

# === CHEMINS ET RÉPERTOIRES ===
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
BACKUPS_DIR = DATA_DIR / "backups"

# Créer les répertoires s'ils n'existent pas
for directory in [DATA_DIR, LOGS_DIR, BACKUPS_DIR]:
    directory.mkdir(exist_ok=True)

# === CONFIGURATION PRINCIPALE ===
CONFIG = {
    # === PARAMÈTRES DE TRADING ===
    'trading': {
        # Montants de trading
        'default_trade_amount': 0.1,  # SOL
        'min_trade_amount': 0.01,     # SOL
        'max_trade_amount': 1.0,      # SOL
        'max_daily_trades': 50,
        'max_position_size': 5.0,     # SOL
        
        # Gestion des risques
        'stop_loss_percentage': 15.0,    # %
        'take_profit_percentage': 25.0,  # %
        'max_slippage': 5.0,            # %
        'min_liquidity_usd': 10000,     # USD
        
        # Timing
        'trade_interval_seconds': 30,
        'analysis_interval_seconds': 60,
        'price_update_interval': 15,
        
        # Filtres de trading
        'min_market_cap': 100000,      # USD
        'max_market_cap': 10000000,    # USD
        'min_volume_24h': 50000,       # USD
        'max_token_age_hours': 168,    # 7 jours
        
        # Diversification
        'max_simultaneous_positions': 10,
        'max_allocation_per_token': 0.2,  # 20% du portefeuille max
        
        # Mode de trading
        'paper_trading': True,  # Mode simulation
        'auto_trading': False,  # Trading automatique
        'debug_mode': True
    },
    
    # === CONFIGURATION SOLANA ===
    'solana': {
        # RPC endpoints (utilisez votre propre endpoint pour de meilleures performances)
        'rpc_url': 'https://api.mainnet-beta.solana.com',
        'backup_rpc_urls': [
            'https://solana-api.projectserum.com',
            'https://rpc.ankr.com/solana',
            'https://solana.public-rpc.com'
        ],
        
        # Configuration du portefeuille
        'wallet_private_key': os.getenv('SOLANA_PRIVATE_KEY', ''),  # À définir dans .env
        'wallet_public_key': os.getenv('SOLANA_PUBLIC_KEY', ''),   # À définir dans .env
        
        # Paramètres de transaction
        'transaction_timeout': 60,     # secondes
        'confirmation_timeout': 30,    # secondes
        'max_retries': 3,
        'retry_delay': 2,              # secondes
        
        # Frais et priorité
        'priority_fee_lamports': 10000,  # Frais de priorité
        'compute_unit_limit': 300000,    # Limite d'unités de calcul
        'compute_unit_price': 1000,      # Prix par unité
        
        # Tokens de référence
        'base_token': 'So11111111111111111111111111111111111111112',  # SOL
        'quote_tokens': [
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'   # USDT
        ]
    },
    
    # === CONFIGURATION RUGCHECK ===
    'rugcheck': {
        'api_base_url': 'https://api.rugcheck.xyz/v1',
        'api_timeout': 30,
        'retry_attempts': 3,
        'retry_delay': 2,
        'rate_limit_delay': 5,
        
        # Seuils de détection
        'bundle_detection_threshold': 0.6,
        'required_safety_score': 'Good',
        'min_safety_score': 0.7,
        
        # Cache
        'cache_results_hours': 6,
        'cache_strategy': 'hybrid',  # 'legacy', 'weak_ref', 'hybrid'
        'max_cache_size': 1000,
        
        # Performance
        'max_concurrent_requests': 5,
        'circuit_breaker_failure_threshold': 5,
        'circuit_breaker_recovery_timeout': 300,
        'circuit_breaker_half_open_calls': 3,
        
        # Seuils de risque
        'risk_thresholds': {
            'critical_max': 0,
            'high_max': 2,
            'medium_max': 5,
            'low_max': 10
        },
        
        # Paramètres d'analyse avancée
        'analysis_thresholds': {
            'variance_threshold': 0.1,
            'similarity_threshold': 0.8,
            'frequency_penalty_factor': 0.1,
            'rapid_trade_window': 10,
            'bot_interval_tolerance': 0.1,
            'coordinated_trade_threshold': 0.8,
            'low_liquidity_threshold': 500,
            'very_low_liquidity_threshold': 100,
            'high_volume_ratio_threshold': 10.0
        },
        
        # Patterns de bundle
        'bundle_patterns': {
            'naming_keywords': [
                'v2', 'v3', '2.0', '3.0', 'relaunch', 'new', 'fixed', 
                'updated', 'beta', 'test', 'final', 'official', 'real', 
                'legit', 'copy', 'fork', 'inu', 'moon', 'safe'
            ],
            'template_indicators': [
                'copy', 'paste', 'template', 'example', 'placeholder', 
                'lorem', 'ipsum', 'todo', 'changeme', 'editme'
            ]
        },
        
        # Métriques de santé
        'health_metrics': {
            'enable_system_metrics': True,
            'metrics_retention_hours': 24,
            'alert_thresholds': {
                'error_rate_threshold': 0.1,
                'response_time_threshold': 10.0,
                'cache_hit_rate_threshold': 0.7
            }
        }
    },
    
    # === CONFIGURATION DEXSCREENER ===
    'dexscreener': {
        'api_base_url': 'https://api.dexscreener.com/latest',
        'api_timeout': 20,
        'retry_attempts': 3,
        'retry_delay': 1,
        'rate_limit_delay': 1,
        
        # Cache
        'cache_duration_minutes': 5,
        'cache_pairs': True,
        'cache_tokens': True,
        'cache_strategy': 'hybrid',
        
        # Filtres
        'min_liquidity_usd': 50000,
        'min_volume_24h_usd': 10000,
        'min_volume': 100000,
        'min_txns_24h': 100,
        'max_age_hours': 24,
        'min_price_change': 10, 
        
        # Pagination
        'max_pairs_per_request': 50,
        'default_limit': 20
    },
    
    # === CONFIGURATION BASE DE DONNÉES ===
    'database': {
        'path': str(DATA_DIR / 'trading_bot.db'),
        'backup_enabled': True,
        'backup_interval_hours': 6,
        'backup_retention_days': 30,
        'backup_path': str(BACKUPS_DIR),
        
        # Performance
        'max_connections': 10,
        'connection_timeout': 30,
        'cache_duration': 300,  # 5 minutes
        
        # Maintenance
        'auto_cleanup': True,
        'cleanup_interval_hours': 24,
        'data_retention_days': 90,
        'performance_metrics_retention_days': 7,
        
        # Monitoring
        'enable_performance_monitoring': True,
        'slow_query_threshold_ms': 1000,
        'enable_query_logging': False
    },
    
    # === CONFIGURATION LOGGING ===
    'logging': {
        'level': 'INFO',  # DEBUG, INFO, WARNING, ERROR, CRITICAL
        'log_to_file': True,
        'log_to_console': True,
        'log_file_path': str(LOGS_DIR / 'trading_bot.log'),
        'error_log_path': str(LOGS_DIR / 'errors.log'),
        'max_file_size_mb': 10,
        'backup_count': 5,
        
        # Logs spécialisés
        'trade_log_path': str(LOGS_DIR / 'trades.log'),
        'analysis_log_path': str(LOGS_DIR / 'analysis.log'),
        'api_log_path': str(LOGS_DIR / 'api_calls.log'),
        
        # Format
        'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        'date_format': '%Y-%m-%d %H:%M:%S',
        
        # Logging avancé
        'enable_advanced_logging': True,
        'log_trades': True,
        'log_api_calls': True,
        'log_performance': True,
        'log_cache_operations': False,

        # Logs spécialisés pour le scanner
        'scanner_logs': {
            'discoveries_log': str(LOGS_DIR / 'scanner_discoveries.log'),
            'filtered_log': str(LOGS_DIR / 'scanner_filtered.log'),
            'stats_log': str(LOGS_DIR / 'scanner_stats.log'),
            'errors_log': str(LOGS_DIR / 'scanner_errors.log'),
            'performance_log': str(LOGS_DIR / 'scanner_performance.log')
        },
        
        # Format de log pour le scanner
        'scanner_log_format': '%(asctime)s - SCANNER - %(levelname)s - %(message)s',
        'scanner_log_level': 'INFO',
        'scanner_detailed_logging': True

    },
    
    # === NOTIFICATIONS ===
    'notifications': {
        'enabled': True,
        'channels': ['console', 'file'],  # 'console', 'file', 'discord', 'telegram'
        
        # Discord (optionnel)
        'discord': {
            'enabled': False,
            'webhook_url': os.getenv('DISCORD_WEBHOOK_URL', ''),
            'username': 'Solana Trading Bot',
            'avatar_url': '',
            'mention_role_id': ''  # ID du rôle à mentionner pour les alertes critiques
        },
        
        # Telegram (optionnel)
        'telegram': {
            'enabled': False,
            'bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
            'chat_id': os.getenv('TELEGRAM_CHAT_ID', ''),
            'parse_mode': 'HTML'
        },

        'scanner_notifications': {
            'new_discovery': True,              # Nouvelles découvertes
            'excellent_discovery': True,        # Découvertes excellentes
            'scanner_stats': True,             # Statistiques périodiques
            'scanner_errors': True,            # Erreurs du scanner
            'first_discovery_of_day': True,    # Première découverte du jour
            'discovery_analysis_complete': True # Analyse terminée
        },
        
        # Niveaux de notification pour découvertes
        'discovery_levels': {
            'excellent_threshold': 0.85,       # Seuil découverte excellente
            'good_threshold': 0.7,             # Seuil bonne découverte
            'notify_excellent_immediately': True,
            'notify_good_with_delay': 60,      # Délai pour bonnes découvertes (secondes)
            'batch_regular_discoveries': True   # Grouper découvertes normales
        },
        
        # Niveaux de notification
        'notify_on': {
            'trade_executed': True,  # ✅ Trades executés
            'trade_failed': True,  # ✅ Trades échoués
            'high_profit': True,  # ✅ Gros profits
            'stop_loss_hit': True,  # ✅ Stop loss
            'system_error': True,  # ✅ Erreurs système
            'bundle_detected': True,  # ✅ Bundles détectés
            'api_error': False,  # ❌ Erreurs API (trop verbeux)
            'cache_miss': False  # ❌ Cache miss (trop verbeux)
        },
        
        # Seuils
        'high_profit_threshold': 20.0,  # %
        'critical_error_threshold': 5,   # Nombre d'erreurs consécutives
        'notification_cooldown_minutes': 5  # Éviter le spam
    },
    
    # === SÉCURITÉ ===
    'security': {
        # Validation des tokens
        'strict_address_validation': True,
        'verify_token_decimals': True,
        'check_token_authority': True,
        'verify_metadata': True,
        
        # Limites de sécurité
        'max_daily_loss_sol': 2.0,      # SOL
        'max_consecutive_losses': 5,
        'emergency_stop_loss': 50.0,    # % de perte totale
        'min_wallet_balance_sol': 0.1,  # SOL à garder minimum
        
        # Validation des transactions
        'simulate_before_send': True,
        'verify_slippage': True,
        'check_liquidity_before_trade': True,
        'validate_price_impact': True,
        'max_price_impact': 10.0,       # %
        
        # Blacklist
        'token_blacklist': [
            # Ajouter ici les adresses de tokens à éviter
        ],
        'creator_blacklist': [
            # Ajouter ici les adresses de créateurs suspects
        ]
    },
    
    # === NOUVELLE SECTION: DEX LISTINGS SCANNER ===
    'scanner': {
        # Activation du scanner
        'enabled': True,
        
        # Configuration des DEXs à surveiller
        'enabled_dexs': ['raydium', 'orca'],  # meteora bientôt disponible
        
        # Filtres de qualité
        'min_liquidity_sol': 5.0,           # Liquidité minimum en SOL
        'max_age_minutes': 60,              # Âge maximum des paires à considérer
        'scan_interval_seconds': 30,        # Intervalle entre scans
        
        # Filtres de tokens
        'filters': {
            'require_sol_pair': True,       # Uniquement paires SOL/TOKEN
            'min_symbol_length': 2,         # Longueur minimum du symbole
            'max_symbol_length': 15,        # Longueur maximum du symbole
            'exclude_keywords': [           # Mots-clés à exclure
                'test', 'fake', 'scam', 'rugpull', 'honeypot',
                'demo', 'sample', 'example', 'placeholder'
            ],
            'min_initial_price': 0.000001,  # Prix minimum USD
            'max_initial_price': 1000.0     # Prix maximum USD
        },
        
        # Configuration performance
        'max_concurrent_scans': 3,          # Nombre max de DEXs scannés en parallèle
        'cache_size_limit': 5000,           # Taille max du cache de paires vues
        'cleanup_interval_minutes': 10,     # Nettoyage du cache
        
        # Configuration notifications
        'notifications': {
            'enabled': True,
            'log_discoveries': True,        # Logger les découvertes
            'log_filtered': False,          # Logger les paires filtrées
            'notify_excellent_finds': True, # Notification pour excellentes trouvailles
            'min_confidence_notify': 0.8   # Confiance minimum pour notification
        },
        
        # Configuration Raydium spécifique
        'raydium': {
            'enabled': True,
            'api_endpoint': 'https://api.raydium.io/v2/main/pairs',
            'min_liquidity_usd': 5000,     # Liquidité minimum en USD
            'rate_limit_delay': 2,          # Délai entre requêtes (secondes)
            'timeout_seconds': 10
        },
        
        # Configuration Orca spécifique
        'orca': {
            'enabled': True,
            'api_endpoint': 'https://api.orca.so/v1/whirlpool/list',
            'min_tvl_usd': 5000,           # TVL minimum en USD
            'rate_limit_delay': 2,
            'timeout_seconds': 10
        },
        
        # Configuration Meteora (en développement)
        'meteora': {
            'enabled': False,               # Pas encore d'API publique
            'program_id': 'Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB',
            'websocket_url': None,          # À implémenter avec WebSocket RPC
            'min_liquidity_sol': 5.0
        },
        
        # Statistiques et monitoring
        'monitoring': {
            'enable_stats': True,
            'stats_interval_minutes': 5,   # Affichage stats toutes les 5min
            'log_performance': True,
            'track_discovery_rate': True,
            'alert_on_no_discoveries': True,
            'no_discovery_alert_minutes': 30  # Alerte si pas de découverte en 30min
        },
        
        # Mode développement
        'development': {
            'debug_mode': False,
            'save_raw_responses': False,
            'mock_mode': False,             # Mode simulation pour tests
            'test_tokens': [                # Tokens de test
                'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # Bonk
                'So11111111111111111111111111111111111111112'    # SOL
            ]
        }
    },
    

        # === PARAMÈTRES DE TRADING ===
    'trading': {
        # Montants de trading
        'default_trade_amount': 0.1,  # SOL
        'min_trade_amount': 0.01,     # SOL
        'max_trade_amount': 1.0,      # SOL
        'max_daily_trades': 50,
        'max_position_size': 5.0,     # SOL
        
        # Gestion des risques
        'stop_loss_percentage': 15.0,    # %
        'take_profit_percentage': 25.0,  # %
        'max_slippage': 5.0,            # %
        'min_liquidity_usd': 10000,     # USD
        
        # Timing
        'trade_interval_seconds': 30,
        'analysis_interval_seconds': 60,
        'price_update_interval': 15,
        
        # Filtres de trading
        'min_market_cap': 100000,      # USD
        'max_market_cap': 10000000,    # USD
        'min_volume_24h': 50000,       # USD
        'max_token_age_hours': 168,    # 7 jours
        
        # Diversification
        'max_simultaneous_positions': 10,
        'max_allocation_per_token': 0.2,  # 20% du portefeuille max
        
        # Mode de trading
        'paper_trading': True,  # Mode simulation
        'auto_trading': False,  # Trading automatique
        'debug_mode': True,
        
        # Nouvelles options pour le scanner
        'scanner_integration': {
            'auto_analyze_discoveries': True,    # Analyser automatiquement les découvertes
            'priority_analysis': True,          # Priorité aux découvertes du scanner
            'max_concurrent_analysis': 3,       # Max d'analyses simultanées
            'discovery_analysis_timeout': 120   # Timeout pour analyse de découverte
        },
        
        # Mode de trading avec scanner
        'scanner_trading_mode': {
            'enabled': True,
            'immediate_analysis': True,         # Analyse immédiate des découvertes
            'bypass_trending_analysis': False,  # Garder l'analyse trending aussi
            'discovery_trade_multiplier': 1.2, # Multiplicateur pour découvertes scanner
            'max_discovery_trades_per_hour': 5  # Limite de trades par découverte/heure
        }
    },

    # === STRATÉGIES DE TRADING ===
    'strategies': {
        'default_strategy': 'scanner_enhanced',
        #ANCIENS SEUILS (très stricts)
        #'min_safety_score': 0.8,
        #'max_bundle_confidence': 0.2,
        #'min_liquidity_multiplier': 2.0,
        #'trade_amount_multiplier': 0.5,
        'conservative': {
            'min_safety_score': 0.3,           # Au lieu de 0.8 - permet tokens moyennement sûrs
            'max_bundle_confidence': 0.7,      # Au lieu de 0.2 - permet bundles modérés
            'min_liquidity_multiplier': 0.5,   # Au lieu de 2.0 - liquidité moins stricte
            'trade_amount_multiplier': 0.1,    # Montants plus petits pour compenser
            'stop_loss_percentage': 5.0,
            'take_profit_percentage': 15.0,
            'max_position_time_hours': 24
        },
        
        'aggressive': {
            'min_safety_score': 0.6,
            'max_bundle_confidence': 0.4,
            'min_liquidity_multiplier': 1.5,
            'trade_amount_multiplier': 1.0,
            'stop_loss_percentage': 20.0,
            'take_profit_percentage': 30.0,
            'max_position_time_hours': 48
        },
        
        'experimental': {
            'min_safety_score': 0.4,
            'max_bundle_confidence': 0.6,
            'min_liquidity_multiplier': 1.0,
            'trade_amount_multiplier': 0.3,
            'stop_loss_percentage': 25.0,
            'take_profit_percentage': 40.0,
            'max_position_time_hours': 12
        },
        # Nouvelle stratégie optimisée pour le scanner
        'scanner_enhanced': {
            'min_safety_score': 0.4,           # Plus permissif pour nouveaux tokens
            'max_bundle_confidence': 0.6,      # Tolérance bundle plus élevée
            'min_liquidity_multiplier': 0.8,   # Liquidité moins stricte
            'trade_amount_multiplier': 0.15,   # Montants plus petits
            'stop_loss_percentage': 8.0,       # Stop loss plus serré
            'take_profit_percentage': 20.0,    # Take profit plus conservateur
            'max_position_time_hours': 12,     # Positions plus courtes
            'discovery_bonus': 0.1,            # Bonus pour découvertes scanner
            'freshness_factor': True           # Favoriser les tokens très récents
        },
        
        # Stratégie ultra-rapide pour découvertes immédiates
        'discovery_sniper': {
            'min_safety_score': 0.2,           # Très permissif
            'max_bundle_confidence': 0.8,      # Accepte bundles modérés
            'min_liquidity_multiplier': 0.3,   # Liquidité très flexible
            'trade_amount_multiplier': 0.05,   # Très petits montants
            'stop_loss_percentage': 5.0,       # Stop loss très serré
            'take_profit_percentage': 15.0,    # Take profit rapide
            'max_position_time_hours': 2,      # Positions très courtes
            'immediate_entry': True,           # Entrée immédiate
            'max_age_minutes': 10              # Seulement tokens < 10 min
        }
    },
    
    # === MONITORING ET ANALYTICS ===
    'monitoring': {
        'enabled': True,
        'update_interval_seconds': 60,
        'metrics_retention_hours': 168,  # 7 jours
        
        # Métriques à collecter
        'collect_performance_metrics': True,
        'collect_trading_metrics': True,
        'collect_system_metrics': True,
        'collect_api_metrics': True,
        
        # Alertes système
        'memory_usage_threshold_mb': 500,
        'cpu_usage_threshold_percent': 80,
        'disk_usage_threshold_percent': 85,
        'api_error_rate_threshold': 0.1,
        
        # Dashboard web (optionnel)
        'web_dashboard': {
            'enabled': False,
            'host': '127.0.0.1',
            'port': 8080,
            'password': os.getenv('DASHBOARD_PASSWORD', 'admin123')
        }
    },
    
    # === DÉVELOPPEMENT ET DEBUG ===
    'development': {
        'debug_mode': True,
        'verbose_logging': False,
        'save_api_responses': False,
        'api_response_path': str(DATA_DIR / 'api_responses'),
        
        # Tests
        'enable_unit_tests': False,
        'test_data_path': str(DATA_DIR / 'test_data'),
        'mock_api_calls': False,
        
        # Profiling
        'enable_profiling': False,
        'profile_output_path': str(LOGS_DIR / 'profiling'),
        
        # Simulation
        'simulation_mode': False,
        'simulation_data_path': str(DATA_DIR / 'simulation'),
        'simulation_speed_multiplier': 1.0
    },
    
    # === TOKENS DE RÉFÉRENCE ===
    'reference_tokens': {
        'SOL': {
            'address': 'So11111111111111111111111111111111111111112',
            'symbol': 'SOL',
            'name': 'Solana',
            'decimals': 9,
            'is_base_currency': True
        },
        'USDC': {
            'address': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
            'symbol': 'USDC',
            'name': 'USD Coin',
            'decimals': 6,
            'is_stable': True
        },
        'USDT': {
            'address': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
            'symbol': 'USDT',
            'name': 'Tether USD',
            'decimals': 6,
            'is_stable': True
        }
    }
}

# === CONFIGURATION D'ENVIRONNEMENT ===
ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')  # development, staging, production

# Ajustements selon l'environnement
if ENVIRONMENT == 'production':
    CONFIG['trading']['paper_trading'] = False
    CONFIG['trading']['debug_mode'] = False
    CONFIG['logging']['level'] = 'INFO'
    CONFIG['development']['debug_mode'] = False
    CONFIG['development']['verbose_logging'] = False
    CONFIG['rugcheck']['max_concurrent_requests'] = 10
    CONFIG['database']['max_connections'] = 20
    CONFIG['scanner']['enabled'] = True
    CONFIG['scanner']['scan_interval_seconds'] = 30
    CONFIG['scanner']['min_liquidity_sol'] = 10.0      # Plus strict en prod
    CONFIG['scanner']['filters']['require_sol_pair'] = True
    CONFIG['scanner']['development']['debug_mode'] = False
    CONFIG['strategies']['default_strategy'] = 'scanner_enhanced'

elif ENVIRONMENT == 'staging':
    CONFIG['trading']['paper_trading'] = True
    CONFIG['trading']['debug_mode'] = True
    CONFIG['logging']['level'] = 'DEBUG'
    CONFIG['development']['debug_mode'] = True
    CONFIG['scanner']['enabled'] = True
    CONFIG['scanner']['scan_interval_seconds'] = 60
    CONFIG['scanner']['min_liquidity_sol'] = 5.0
    CONFIG['scanner']['development']['debug_mode'] = True
    CONFIG['scanner']['development']['save_raw_responses'] = True

else:  # development
    CONFIG['trading']['paper_trading'] = True
    CONFIG['trading']['debug_mode'] = True
    CONFIG['logging']['level'] = 'DEBUG'
    CONFIG['development']['debug_mode'] = True
    CONFIG['development']['verbose_logging'] = True
    CONFIG['scanner']['enabled'] = True
    CONFIG['scanner']['scan_interval_seconds'] = 60
    CONFIG['scanner']['min_liquidity_sol'] = 1.0       # Moins strict en dev
    CONFIG['scanner']['development']['debug_mode'] = True
    CONFIG['scanner']['development']['save_raw_responses'] = True
    CONFIG['scanner']['development']['mock_mode'] = False


# ===== NOUVELLES FONCTIONS UTILITAIRES =====
def get_scanner_config():
    """Retourne uniquement la configuration du scanner"""
    return CONFIG['scanner'].copy()

def is_scanner_enabled():
    """Vérifie si le scanner est activé"""
    return CONFIG['scanner'].get('enabled', False)

def get_enabled_dexs():
    """Retourne la liste des DEXs activés"""
    return CONFIG['scanner'].get('enabled_dexs', [])

def update_scanner_config(key: str, value):
    """Met à jour une valeur de configuration du scanner"""
    if key in CONFIG['scanner']:
        CONFIG['scanner'][key] = value
        return True
    return False

def enable_scanner():
    """Active le scanner"""
    CONFIG['scanner']['enabled'] = True

def disable_scanner():
    """Désactive le scanner"""
    CONFIG['scanner']['enabled'] = False

def get_discovery_strategy_config():
    """Retourne la configuration de la stratégie de découverte"""
    strategy_name = CONFIG['strategies'].get('default_strategy', 'conservative')
    if 'scanner' in strategy_name or 'discovery' in strategy_name:
        return CONFIG['strategies'].get(strategy_name, CONFIG['strategies']['scanner_enhanced'])
    return CONFIG['strategies']['scanner_enhanced']


# === VALIDATION DE LA CONFIGURATION ===
def validate_config():
    """Valide la configuration et retourne les erreurs trouvées"""
    errors = []
    
    # Vérifier les clés privées en production
    if ENVIRONMENT == 'production':
        if not CONFIG['solana']['wallet_private_key']:
            errors.append("SOLANA_PRIVATE_KEY manquant pour la production")
        if not CONFIG['solana']['wallet_public_key']:
            errors.append("SOLANA_PUBLIC_KEY manquant pour la production")
    
    # Vérifier les montants de trading
    trading = CONFIG['trading']
    if trading['min_trade_amount'] >= trading['max_trade_amount']:
        errors.append("min_trade_amount doit être < max_trade_amount")
    
    if trading['default_trade_amount'] > trading['max_trade_amount']:
        errors.append("default_trade_amount doit être <= max_trade_amount")
    
    # Vérifier les pourcentages
    if trading['stop_loss_percentage'] <= 0 or trading['stop_loss_percentage'] > 100:
        errors.append("stop_loss_percentage doit être entre 0 et 100")
    
    if trading['take_profit_percentage'] <= 0:
        errors.append("take_profit_percentage doit être > 0")
    
    # Vérifier les répertoires
    required_dirs = [DATA_DIR, LOGS_DIR, BACKUPS_DIR]
    for directory in required_dirs:
        if not directory.exists():
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Impossible de créer le répertoire {directory}: {e}")
    
    # Validation du scanner
    scanner_config = CONFIG.get('scanner', {})
    
    if scanner_config.get('enabled', False):
        # Vérifier DEXs activés
        enabled_dexs = scanner_config.get('enabled_dexs', [])
        if not enabled_dexs:
            errors.append("Scanner activé mais aucun DEX configuré")
        
        valid_dexs = ['raydium', 'orca', 'meteora', 'phoenix', 'openbook']
        for dex in enabled_dexs:
            if dex not in valid_dexs:
                errors.append(f"DEX non supporté: {dex}")
        
        # Vérifier paramètres de liquidité
        min_liquidity = scanner_config.get('min_liquidity_sol', 0)
        if min_liquidity < 0:
            errors.append("min_liquidity_sol doit être >= 0")
        
        # Vérifier intervalles
        scan_interval = scanner_config.get('scan_interval_seconds', 30)
        if scan_interval < 10:
            errors.append("scan_interval_seconds doit être >= 10")
        
        # Vérifier filtres
        filters = scanner_config.get('filters', {})
        min_symbol_len = filters.get('min_symbol_length', 2)
        max_symbol_len = filters.get('max_symbol_length', 15)
        
        if min_symbol_len >= max_symbol_len:
            errors.append("min_symbol_length doit être < max_symbol_length")
        
        # Vérifier configuration des DEXs individuels
        for dex in enabled_dexs:
            dex_config = scanner_config.get(dex, {})
            if dex_config.get('enabled', True):
                if dex in ['raydium', 'orca']:
                    if not dex_config.get('api_endpoint'):
                        errors.append(f"api_endpoint manquant pour {dex}")

    return errors


# ===== FONCTIONS D'AIDE POUR L'INTÉGRATION =====

def get_scanner_integration_config():
    """Configuration spécifique pour l'intégration du scanner"""
    return {
        'scanner': get_scanner_config(),
        'trading_integration': CONFIG['trading'].get('scanner_integration', {}),
        'strategy': get_discovery_strategy_config(),
        'notifications': CONFIG['notifications'].get('scanner_notifications', {}),
        'logging': CONFIG['logging'].get('scanner_logs', {})
    }

def is_discovery_strategy_active():
    """Vérifie si une stratégie de découverte est active"""
    strategy = CONFIG['strategies'].get('default_strategy', '')
    return 'scanner' in strategy or 'discovery' in strategy

def get_scanner_performance_config():
    """Configuration de performance pour le scanner"""
    return {
        'max_concurrent_scans': CONFIG['scanner'].get('max_concurrent_scans', 3),
        'cache_size_limit': CONFIG['scanner'].get('cache_size_limit', 5000),
        'cleanup_interval_minutes': CONFIG['scanner'].get('cleanup_interval_minutes', 10),
        'rate_limits': {
            'raydium': CONFIG['scanner']['raydium'].get('rate_limit_delay', 2),
            'orca': CONFIG['scanner']['orca'].get('rate_limit_delay', 2)
        }
    }

# === FONCTIONS UTILITAIRES ===
def get_config():
    """Retourne la configuration complète"""
    return CONFIG.copy()

def get_trading_config():
    """Retourne uniquement la configuration de trading"""
    return CONFIG['trading'].copy()

def get_database_config():
    """Retourne uniquement la configuration de base de données"""
    return CONFIG['database'].copy()

def get_security_config():
    """Retourne uniquement la configuration de sécurité"""
    return CONFIG['security'].copy()

def update_config(section: str, key: str, value):
    """Met à jour une valeur de configuration"""
    if section in CONFIG and key in CONFIG[section]:
        CONFIG[section][key] = value
        return True
    return False

def get_strategy_config(strategy_name: str = None):
    """Retourne la configuration d'une stratégie"""
    if strategy_name is None:
        strategy_name = CONFIG['strategies']['default_strategy']
    
    return CONFIG['strategies'].get(strategy_name, CONFIG['strategies']['conservative'])

def is_production():
    """Vérifie si on est en environnement de production"""
    return ENVIRONMENT == 'production'

def is_development():
    """Vérifie si on est en environnement de développement"""
    return ENVIRONMENT == 'development'

# === EXPORT ===
__all__ = [
    'CONFIG',
    'ENVIRONMENT',
    'BASE_DIR',
    'DATA_DIR',
    'LOGS_DIR',
    'BACKUPS_DIR',
    'get_config',
    'get_trading_config',
    'get_database_config',
    'get_security_config',
    'get_strategy_config',
    'update_config',
    'validate_config',
    'is_production',
    'is_development'
]

# === VALIDATION AU CHARGEMENT ===
if __name__ == "__main__":
    # Valider la configuration
    config_errors = validate_config()
    
    if config_errors:
        print("❌ ERREURS DE CONFIGURATION:")
        for error in config_errors:
            print(f"   - {error}")
    else:
        print("✅ Configuration valide")
        
    print(f"\n📋 RÉSUMÉ DE LA CONFIGURATION:")
    print(f"   - Environnement: {ENVIRONMENT}")
    print(f"   - Mode paper trading: {CONFIG['trading']['paper_trading']}")
    print(f"   - Mode debug: {CONFIG['trading']['debug_mode']}")
    print(f"   - Base de données: {CONFIG['database']['path']}")
    print(f"   - Logs: {CONFIG['logging']['log_file_path']}")
    print(f"   - Stratégie par défaut: {CONFIG['strategies']['default_strategy']}")