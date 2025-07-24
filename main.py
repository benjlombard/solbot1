#!/usr/bin/env python3
"""
Solana Trading Bot - Main Application
File: main.py

Comprehensive token analysis and trading system with:
- RugCheck security analysis with advanced bundle detection
- DexScreener market data and price analysis
- Database management with performance monitoring
- Real-time notifications (console/log based)
- Configurable trading strategies
- Advanced logging and error handling

Usage:
    python main.py --log-level DEBUG
    python main.py --test-run
    python main.py --paper-trading
    python main.py --strategy conservative
    python main.py --test-dexscreener TOKEN_ADDRESS
"""

import asyncio
import argparse
import os
import sys
import signal
import json
import time
from datetime import datetime
from typing import Dict, List, Optional

# Import our modular components (updated to use new modules)
from config import (
    get_config, get_trading_config, get_database_config, 
    get_security_config, get_strategy_config, validate_config,
    is_production, is_development, ENVIRONMENT
)
from database import (
    create_database_manager, TokenRecord, TransactionRecord, 
    AnalyticsRecord, TokenStatus, TransactionStatus
)
from rugcheck import RugCheckAnalyzer, AnalysisResult
from dexscreener import DexScreenerAnalyzer, DexScreenerIntegration, TradingPair, ChainId

from dexscreener import (
    DexScreenerAnalyzer, DexScreenerIntegration, TradingPair, 
    ChainId, MarketAnalysis
)

from dex_scanner import (
    DEXListingsScanner, NewPairEvent, DEXProtocol, 
    create_dex_scanner_integration, add_scanner_to_config
)

from solana_client import (
    create_solana_client, SolanaClient, TransactionResult, 
    TransactionStatus, SwapParams, quick_buy, quick_sell,
    InsufficientFundsError, SlippageExceededError
)

from birdeye import BirdeyeAnalyzer, create_birdeye_analyzer, get_newest_birdeye_tokens, BirdeyeToken

# from notifications import NotificationManager  # À créer
# from portfolio import PortfolioManager  # À créer
# from trading_bot import TradingBot  # À créer

class SolanaTradingBot:
    """
    Main Solana Trading Bot
    
    Integrates all components for comprehensive token analysis and trading:
    - Security verification via RugCheck
    - Market data analysis via DexScreener
    - Automated trading with risk management
    - Real-time notifications and logging
    - Database storage and analytics
    """
    
    def __init__(self, config_path=None, log_level='INFO', strategy=None):
        """Initialize the complete bot system"""
        print(f"🤖 Initializing Solana Trading Bot...")
        print(f"🌍 Environment: {ENVIRONMENT}")
        print(f"📝 Log Level: {log_level}")
        
        # Load and validate configuration
        self.config = get_config()
        
        
        # 🆕 NOUVEAU: Mode de scan
        self.scanner_enabled = self.config.get('scanner', {}).get('enabled', True)

        # 🆕 FIXÉ: Ajouter la configuration du scanner à la config existante
        if 'scanner' not in self.config:
            scanner_config = {
                'enabled': True,
                'min_liquidity_sol': 5.0,
                'max_age_minutes': 60,
                'enabled_dexs': ['raydium', 'orca'],
                'scan_interval_seconds': 30,
                'filters': {
                    'require_sol_pair': True,
                    'min_symbol_length': 2,
                    'max_symbol_length': 15,
                    'exclude_keywords': ['test', 'fake', 'scam']
                }
            }
            self.config['scanner'] = scanner_config

        # Système de déduplication
        self.processed_tokens = set()  # Tokens déjà traités
        self.processed_tokens_timestamps = {}  # Horodatage des tokens traités
        self.last_cycle_tokens = set()  # Tokens du dernier cycle

        # Validate configuration
        config_errors = validate_config()
        if config_errors:
            print("❌ CONFIGURATION ERRORS:")
            for error in config_errors:
                print(f"   - {error}")
            raise SystemExit("Fix configuration errors before starting")
        
        print("✅ Configuration validated successfully")
        
        # Override strategy if specified
        if strategy:
            self.strategy_config = get_strategy_config(strategy)
            print(f"🎯 Using strategy: {strategy}")
        else:
            self.strategy_config = get_strategy_config()
            print(f"🎯 Using default strategy: {self.config['strategies']['default_strategy']}")
        
        # Initialize logging (basic for now)
        self._setup_logging(log_level)
        
        # Use print for startup message to avoid encoding issues
        print("Starting Solana Trading Bot initialization...")
        self.logger.info("Starting Solana Trading Bot initialization...")
        
        # Initialize core components
        self._initialize_components()
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
        

        # Runtime state
        self.is_running = False
        self.start_time = datetime.now()
        self.cycles_completed = 0
        self.total_trades = 0
        
        # 🆕 NOUVEAU: Initialiser le scanner (après les autres composants)
        self.dex_scanner = None  # Sera initialisé plus tard

        print("✅ Solana Trading Bot initialized successfully!")
        self.logger.info("Solana Trading Bot initialized successfully!")

    def _setup_logging(self, log_level):
        """Setup logging with Windows-compatible encoding"""
        import logging
        from logging.handlers import RotatingFileHandler
        
        # Create logger
        self.logger = logging.getLogger('SolanaTradingBot')
        self.logger.setLevel(getattr(logging, log_level))
        
        # Create formatters (without emojis for file logging)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console formatter with safe encoding
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # Console handler with UTF-8 encoding
        if self.config['logging']['log_to_console']:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(console_formatter)
            
            # Set UTF-8 encoding for Windows compatibility
            if hasattr(console_handler.stream, 'reconfigure'):
                try:
                    console_handler.stream.reconfigure(encoding='utf-8')
                except:
                    pass  # Fallback if reconfigure fails
            
            self.logger.addHandler(console_handler)
        
        # File handler with UTF-8 encoding
        if self.config['logging']['log_to_file']:
            file_handler = RotatingFileHandler(
                self.config['logging']['log_file_path'],
                maxBytes=self.config['logging']['max_file_size_mb'] * 1024 * 1024,
                backupCount=self.config['logging']['backup_count'],
                encoding='utf-8'  # Explicit UTF-8 encoding for file
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)

    def _initialize_components(self):
        """Initialize all bot components in proper order"""
        
        # 1. Database Manager
        print("🗄️ Initializing database manager...")
        self.logger.info("Initializing database manager...")
        try:
            self.database_manager = create_database_manager(self.config)
            
            # Test database connection
            stats = self.database_manager.get_database_stats()
            print(f"📊 Database ready: {stats['tokens_count']} tokens, {stats['transactions_count']} transactions")
            self.logger.info(f"Database ready: {stats['tokens_count']} tokens, {stats['transactions_count']} transactions")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize database: {e}")
            raise
        
        # 2. RugCheck Analyzer
        print("🔒 Initializing RugCheck analyzer...")
        self.logger.info("Initializing RugCheck analyzer...")
        try:
            self.rugcheck_analyzer = RugCheckAnalyzer(self.config)
            
            # Test RugCheck with SOL address
            test_valid = self.rugcheck_analyzer.validate_token_address(
                'So11111111111111111111111111111111111111112'
            )
            status = "✅" if test_valid else "❌"
            print(f"🔒 RugCheck ready: Address validation test {status}")
            self.logger.info(f"RugCheck ready: Address validation test {'passed' if test_valid else 'failed'}")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize RugCheck: {e}")
            raise
        
        # 3. DexScreener Analyzer
        print("📊 Initializing DexScreener analyzer...")
        self.logger.info("Initializing DexScreener analyzer...")
        try:
            self.dexscreener_analyzer = DexScreenerAnalyzer(self.config)
            
            # Initialize DexScreener integration helper
            self.dexscreener_integration = DexScreenerIntegration(self.config, None)
            
            # Test DexScreener with a basic search
            test_response = self.dexscreener_analyzer.search_pairs("SOL", limit=1)
            status = "✅" if (test_response and test_response.pairs) else "❌"
            print(f"📊 DexScreener ready: API test {status}")
            self.logger.info(f"DexScreener ready: API test {'passed' if status == '✅' else 'failed'}")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize DexScreener: {e}")
            # Don't raise - DexScreener is not critical for basic functionality
            self.dexscreener_analyzer = None
            self.dexscreener_integration = None
            print("⚠️ DexScreener disabled - continuing without market data")

        # 4. Birdeye Analyzer  
        print("🐦 Initializing Birdeye analyzer...")
        self.logger.info("Initializing Birdeye analyzer...")
        try:
            self.birdeye_analyzer = create_birdeye_analyzer(self.config)
            
            # Test Birdeye with a simple request
            birdeye_stats = self.birdeye_analyzer.get_stats()
            status = "✅" if birdeye_stats['api_key_configured'] else "⚠️"
            print(f"🐦 Birdeye ready: API key {status}")
            self.logger.info(f"Birdeye ready: API configured={birdeye_stats['api_key_configured']}")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Birdeye: {e}")
            # Don't raise - Birdeye is not critical
            self.birdeye_analyzer = None
            print("⚠️ Birdeye disabled - continuing without Birdeye data")
    
        # 5. Solana Client
        print("🚀 Initializing Solana client...")
        self.logger.info("Initializing Solana client...")
        try:
            self.solana_client = create_solana_client(self.config, self.logger)
            
            # Test connection
            health = asyncio.run(self.solana_client.health_check())
            status = "✅" if health['status'] == 'healthy' else "❌"
            print(f"🚀 Solana client ready: Connection {status} ({health['rpc_latency_ms']:.1f}ms)")
            self.logger.info(f"Solana client ready: {health['status']} - {health['client_status']}")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Solana client: {e}")
            # Don't raise - continue without trading capability
            self.solana_client = None
            print("⚠️ Solana client disabled - continuing without trading")

        # 6. Portfolio Manager (placeholder for now)
        print("💰 Initializing portfolio manager...")
        self.logger.info("Initializing portfolio manager...")
        self.portfolio = {
            'sol_balance': 0.0,
            'positions': {},
            'total_value_usd': 0.0,
            'daily_pnl': 0.0
        }
        
        # 7. Trading configuration
        self.trading_config = get_trading_config()
        self.security_config = get_security_config()
        
        # 8. DEX Listings Scanner
        if self.scanner_enabled:
            print("🔍 Initializing DEX Listings Scanner...")
            self.logger.info("Initializing DEX Listings Scanner...")
            try:
                # Le scanner sera créé de manière asynchrone
                self.logger.info("DEX Scanner will be started with monitoring")
                self.scanner_stats = {
                    'enabled': True,
                    'status': 'pending_start'
                }
            except Exception as e:
                self.logger.error(f"❌ Failed to prepare DEX scanner: {e}")
                self.scanner_enabled = False
                print("⚠️ DEX Scanner disabled")
        else:
            print("⏸️ DEX Scanner disabled in configuration")
            self.scanner_stats = {'enabled': False}

        # Load and display component status
        self._display_component_status()

    def _display_component_status(self):
        """Display initialization status of all components"""
        components_status = {
            'Database Manager': '✅ Ready',
            'RugCheck Analyzer': '✅ Ready',
            'DexScreener Analyzer': '✅ Ready' if self.dexscreener_analyzer else '❌ Failed',
            'DEX Listings Scanner': '✅ Ready' if self.scanner_enabled else '⏸️ Disabled',
            'Portfolio Manager': '✅ Ready (Basic)',
            'Trading Engine': '✅ Configured',
            'Solana Client': '✅ Ready' if self.solana_client else '❌ Failed',
            'Notification Manager': '⏳ Pending Implementation'
        }
        
        print("\n" + "="*60)
        print("COMPONENT STATUS")
        print("="*60)
        
        for component, status in components_status.items():
            print(f"{component:<22} {status}")
            self.logger.info(f"{component}: {status}")
        
        # Display configuration summary
        print(f"\n📋 CONFIGURATION SUMMARY:")
        print(f"  Environment: {ENVIRONMENT}")
        print(f"  Paper Trading: {'✅' if self.trading_config['paper_trading'] else '❌'}")
        print(f"  Auto Trading: {'✅' if self.trading_config['auto_trading'] else '❌'}")
        print(f"  Strategy: {self.config['strategies']['default_strategy']}")
        print(f"  Max Daily Trades: {self.trading_config['max_daily_trades']}")
        print(f"  Default Trade Amount: {self.trading_config['default_trade_amount']} SOL")
        print(f"  Stop Loss: {self.trading_config['stop_loss_percentage']}%")
        print(f"  Take Profit: {self.trading_config['take_profit_percentage']}%")
        
        # Display security settings
        print(f"\n🔒 SECURITY SETTINGS:")
        print(f"  Min Safety Score: {self.strategy_config['min_safety_score']}")
        print(f"  Max Bundle Confidence: {self.strategy_config['max_bundle_confidence']}")
        print(f"  Min Liquidity: ${self.trading_config['min_liquidity_usd']:,}")
        print(f"  Max Slippage: {self.trading_config['max_slippage']}%")
        print("="*60)

        # 🆕 NOUVEAU: Ajouter info sur le scanner
        if self.scanner_enabled:
            enabled_dexs = self.config.get('scanner', {}).get('enabled_dexs', [])
            min_liquidity = self.config.get('scanner', {}).get('min_liquidity_sol', 5.0)
            print(f"\n🔍 DEX SCANNER SETTINGS:")
            print(f"  Enabled DEXs: {', '.join(enabled_dexs)}")
            print(f"  Min Liquidity: {min_liquidity} SOL")
            print(f"  Real-time Monitoring: Enabled")

    def set_analysis_method(self, method: str):
        """Définir la méthode d'analyse par défaut"""
        self.analysis_method = method
        self.logger.info(f"🔧 Analysis method set to: {method}")

    async def analyze_newest_tokens(self, hours_back: int = 2, limit: int = 10, method: str = 'timestamp') -> List[Dict]:
        """Analyser spécifiquement les tokens les plus récents avec choix de méthode"""
        self.logger.info(f"🆕 Analyzing newest tokens from last {hours_back}h using {method} method...")
    
        if not self.dexscreener_analyzer:
            self.logger.warning("DexScreener not available for newest token analysis")
            return []
    
        try:
            # Choisir la méthode selon le paramètre
            if method == 'timestamp':
                newest_tokens = await self.dexscreener_analyzer.get_newest_tokens_by_timestamp(hours_back)
            elif method == 'optimized':
                newest_tokens = await self.dexscreener_analyzer.get_newest_tokens_optimized(hours_back)
            elif method == 'sorted':
                newest_tokens = await self.dexscreener_analyzer.get_newest_tokens_sorted(hours_back)
            else:  # terms (fallback)
                newest_tokens = await self.dexscreener_analyzer.get_newest_tokens_realtime(hours_back)

            self.logger.info(f"🔍 Found {len(newest_tokens)} newest tokens to analyze")

            if not newest_tokens:
                self.logger.info("ℹ️ No new tokens found in the specified timeframe")
                return []

            analyzed_tokens = []
            
            for token_data in newest_tokens:
                # Filtres de pré-qualification
                if (token_data['liquidity_usd'] < 5000 or 
                    token_data['age_hours'] < 0.1):  # Au moins 6 minutes
                    self.logger.debug(f"Skipping {token_data['symbol']} - insufficient liquidity or too new")
                    continue
                
                token_address = token_data['token_address']
                
                try:
                    self.logger.info(f"🔬 Analyzing newest token: {token_data['symbol']} ({token_address[:8]}...)")
                    # Analyse complète
                    analysis_result = await self.analyze_token_comprehensive(token_address)
                    
                    # Combiner données de découverte + analyse
                    combined_result = {
                        **token_data,
                        'analysis': analysis_result,
                        'freshness_score': self._calculate_freshness_score(token_data, analysis_result)
                    }
                    
                    analyzed_tokens.append(combined_result)

                    # Délai entre analyses
                    await asyncio.sleep(1)

                except Exception as e:
                    self.logger.error(f"Error analyzing newest token {token_address}: {e}")
                    continue
            
            # Trier par score de fraîcheur
            analyzed_tokens.sort(key=lambda x: x.get('freshness_score', 0), reverse=True)
            self.logger.info(f"✅ Completed analysis of {len(analyzed_tokens)} newest tokens")
            return analyzed_tokens
            
        except Exception as e:
            self.logger.error(f"Error in newest tokens analysis: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _cleanup_processed_tokens(self):
        """Nettoyer les tokens traités il y a plus de 2h"""
        from datetime import timedelta
        
        cutoff_time = datetime.now() - timedelta(hours=2)
        tokens_to_remove = [
            token for token, timestamp in self.processed_tokens_timestamps.items()
            if timestamp < cutoff_time
        ]
        
        for token in tokens_to_remove:
            self.processed_tokens.discard(token)
            self.processed_tokens_timestamps.pop(token, None)
        
        if tokens_to_remove:
            self.logger.debug(f"🧹 Cleaned {len(tokens_to_remove)} old tokens from memory")

    async def run_continuous_newest_analysis(self, hours_back: int = 6, interval_minutes: int = 10, method: str = 'timestamp'):
        """Analyse continue des nouveaux tokens avec logging séparé"""
        
        # Setup des loggers séparés
        good_tokens_logger = self._setup_specialized_logger('good_tokens', 'good_tokens.log')
        bad_tokens_logger = self._setup_specialized_logger('bad_tokens', 'bad_tokens.log')
        
        self.logger.info(f"🔄 Starting continuous newest tokens analysis (every {interval_minutes}m)")
        self.is_running = True
        
        cycle_count = 0
        
        try:
            while self.is_running:
                cycle_count += 1
                cycle_start = datetime.now()
                
                print(f"\n{'='*80}")
                print(f"🔄 CYCLE #{cycle_count} - {cycle_start.strftime('%H:%M:%S')}")
                print(f"{'='*80}")
                
                # Analyser les nouveaux tokens
                newest_tokens = await self.analyze_newest_tokens(hours_back, limit=50, method=method)  # Augmenter la limite
                
                if newest_tokens:
                    good_count = 0
                    bad_count = 0
                    new_tokens_count = 0
                    duplicate_count = 0
                    
                    # Nettoyer les anciens tokens (plus de 2h)
                    self._cleanup_processed_tokens()
                    
                    current_cycle_tokens = set()
                    
                    for token_data in newest_tokens:
                        token_address = token_data['token_address']
                        
                        # Éviter les doublons dans le même cycle
                        if token_address in current_cycle_tokens:
                            duplicate_count += 1
                            continue
                        
                        current_cycle_tokens.add(token_address)
                        
                        # Éviter les tokens déjà traités récemment
                        if token_address in self.processed_tokens:
                            duplicate_count += 1
                            continue
                        
                        # Marquer comme traité
                        self.processed_tokens.add(token_address)
                        self.processed_tokens_timestamps[token_address] = datetime.now()
                        new_tokens_count += 1
                        
                        analysis = token_data.get('analysis', {})
                        passed_checks = analysis.get('passed_all_checks', False)
                        trading_rec = analysis.get('trading_recommendation', {})
                        
                        # Log dans les fichiers appropriés
                        if passed_checks and trading_rec.get('action') == 'BUY':
                            self._log_good_token(good_tokens_logger, token_data)
                            good_count += 1
                        else:
                            self._log_bad_token(bad_tokens_logger, token_data)
                            bad_count += 1
                    
                    print(f"📊 Cycle summary: {new_tokens_count} new, {good_count} good, {bad_count} rejected, {duplicate_count} duplicates")
                    
                    # Sauvegarder les tokens de ce cycle
                    self.last_cycle_tokens = current_cycle_tokens

                # Délai avant le prochain cycle
                print(f"\n⏰ Next scan in {interval_minutes} minutes...")
                await asyncio.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            self.logger.info("🛑 Continuous analysis stopped by user")
            print("\n🛑 Continuous analysis stopped")
        except Exception as e:
            self.logger.error(f"❌ Error in continuous analysis: {e}")
            raise


    def _setup_specialized_logger(self, name: str, filename: str):
        """Setup d'un logger spécialisé pour les tokens"""
        import logging  # Import local
        from logging.handlers import RotatingFileHandler
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        
        # Éviter les doublons de handlers
        if not logger.handlers:
            handler = logging.FileHandler(
                self.config['logging']['log_file_path'].replace('trading_bot.log', filename),
                encoding='utf-8'
            )
            formatter = logging.Formatter('%(asctime)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            
        return logger

    def _log_good_token(self, logger, token_data):
        """Log un bon token dans le fichier des bons tokens"""
        analysis = token_data.get('analysis', {})
        trading_rec = analysis.get('trading_recommendation', {})
        
        log_entry = {
            'symbol': token_data.get('symbol', 'UNKNOWN'),
            'address': token_data['token_address'],
            'age_hours': token_data.get('age_hours', 0),
            'liquidity_usd': token_data.get('liquidity_usd', 0),
            'volume_24h': token_data.get('volume_24h', 0),
            'price_usd': token_data.get('price_usd', 0),
            'action': trading_rec.get('action', 'UNKNOWN'),
            'confidence': trading_rec.get('confidence', 0),
            'freshness_score': token_data.get('freshness_score', 0)
        }
        
        logger.info(f"GOOD_TOKEN: {json.dumps(log_entry)}")

    def _log_bad_token(self, logger, token_data):
        """Log un mauvais token dans le fichier des mauvais tokens"""
        analysis = token_data.get('analysis', {})
        risk_assessment = analysis.get('risk_assessment', {})
        alerts = analysis.get('alerts', [])
        
        log_entry = {
            'symbol': token_data.get('symbol', 'UNKNOWN'),
            'address': token_data['token_address'],
            'age_hours': token_data.get('age_hours', 0),
            'liquidity_usd': token_data.get('liquidity_usd', 0),
            'risk_level': risk_assessment.get('overall_risk', 'UNKNOWN'),
            'alerts_count': len(alerts),
            'main_alerts': [alert['type'] for alert in alerts[:3]]  # Top 3 alerts
        }
        
        logger.info(f"BAD_TOKEN: {json.dumps(log_entry)}")

    def _calculate_freshness_score(self, token_data: Dict, analysis_result: Dict) -> float:
        """Calculer un score de fraîcheur pour les nouveaux tokens"""
        try:
            score = 0.0
            
            # Facteur âge (40 points - plus récent = mieux)
            age_hours = token_data.get('age_hours', 0)
            if age_hours <= 1:
                score += 40
            elif age_hours <= 6:
                score += 30
            elif age_hours <= 24:
                score += 20
            elif age_hours <= 72:
                score += 10
            
            # Facteur liquidité (30 points)
            liquidity = token_data.get('liquidity_usd', 0)
            if liquidity >= 100000:
                score += 30
            elif liquidity >= 50000:
                score += 20
            elif liquidity >= 20000:
                score += 15
            elif liquidity >= 10000:
                score += 10
            
            # Facteur volume (20 points)
            volume = token_data.get('volume_24h', 0)
            if volume >= 500000:
                score += 20
            elif volume >= 100000:
                score += 15
            elif volume >= 50000:
                score += 10
            elif volume >= 10000:
                score += 5
            
            # Facteur sécurité (10 points)
            rugcheck_analysis = analysis_result.get('rugcheck_analysis', {})
            safety_score = rugcheck_analysis.get('safety_score', 0)
            score += safety_score * 10
            
            # Malus bundle (-30 points)
            if rugcheck_analysis.get('bundle_detected', False):
                score -= 30
            
            return max(0, score)
            
        except Exception as e:
            self.logger.error(f"Error calculating freshness score: {e}")
            return 0.0

    async def test_dexscreener_endpoints(self):
        """Test des endpoints DexScreener pour debug"""
        print("\n🧪 Test des endpoints DexScreener")
        
        import requests
        
        # Test 1: Search basique
        print("\n1. Test search basique:")
        try:
            response = requests.get(
                "https://api.dexscreener.com/latest/dex/search",
                params={'q': 'SOL'},
                timeout=10
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                print(f"   Pairs trouvées: {len(pairs)}")
                if pairs:
                    print(f"   Exemple: {pairs[0]['baseToken']['symbol']}")
        except Exception as e:
            print(f"   Erreur: {e}")
        
        # Test 2: Token boosts
        print("\n2. Test token boosts:")
        try:
            response = requests.get(
                "https://api.dexscreener.com/token-boosts/latest/v1",
                timeout=10
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Type données: {type(data)}")
                if isinstance(data, list):
                    print(f"   Nombre items: {len(data)}")
                elif isinstance(data, dict):
                    print(f"   Clés: {list(data.keys())}")
        except Exception as e:
            print(f"   Erreur: {e}")
        
        # Test 3: Token pairs pour SOL
        print("\n3. Test token pairs:")
        try:
            sol_address = "So11111111111111111111111111111111111111112"
            response = requests.get(
                f"https://api.dexscreener.com/token-pairs/v1/solana/{sol_address}",
                timeout=10
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Type: {type(data)}, Length: {len(data) if isinstance(data, list) else 'N/A'}")
        except Exception as e:
            print(f"   Erreur: {e}")

    def _setup_signal_handlers(self):
        """Setup graceful shutdown handlers"""
        def signal_handler(sig, frame):
            self.logger.info(f"📴 Received signal {sig}, initiating graceful shutdown...")
            self.shutdown()
            sys.exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def execute_buy_order(self, token_address: str, sol_amount: float, max_slippage: float = 0.01) -> Dict:
        """Execute a buy order with proper logging and error handling"""
        if not self.solana_client:
            return {'success': False, 'error': 'Solana client not available'}
        
        if self.trading_config['paper_trading']:
            self.logger.info(f"📊 PAPER TRADE: Buy {sol_amount} SOL of {token_address[:8]}...")
            return {
                'success': True,
                'paper_trade': True,
                'signature': f"PAPER_{int(time.time())}",
                'amount': sol_amount
            }
        
        try:
            self.logger.info(f"💰 LIVE BUY: {sol_amount} SOL → {token_address[:8]}...")
            
            # Check balance first
            balance = await self.solana_client.get_balance()
            if balance < sol_amount:
                raise InsufficientFundsError(f"Insufficient SOL: {balance} < {sol_amount}")
            
            # Execute trade
            result = await self.solana_client.buy_token(token_address, sol_amount, max_slippage)
            
            if result and result.status == TransactionStatus.CONFIRMED:
                self.total_trades += 1
                self.logger.info(f"✅ BUY SUCCESS: {result.signature}")
                return {
                    'success': True,
                    'signature': result.signature,
                    'amount': sol_amount,
                    'paper_trade': False
                }
            else:
                self.logger.error(f"❌ BUY FAILED: {result.error if result else 'Unknown error'}")
                return {'success': False, 'error': result.error if result else 'Transaction failed'}
                
        except Exception as e:
            self.logger.error(f"❌ BUY ORDER ERROR: {e}")
            return {'success': False, 'error': str(e)}

    async def execute_sell_order(self, token_address: str, amount: float, max_slippage: float = 0.01) -> Dict:
        """Execute a sell order with proper logging and error handling"""
        if not self.solana_client:
            return {'success': False, 'error': 'Solana client not available'}
        
        if self.trading_config['paper_trading']:
            self.logger.info(f"📊 PAPER TRADE: Sell {amount} of {token_address[:8]}...")
            return {
                'success': True,
                'paper_trade': True,
                'signature': f"PAPER_{int(time.time())}",
                'amount': amount
            }
        
        try:
            self.logger.info(f"💸 LIVE SELL: {amount} tokens → SOL")
            
            result = await self.solana_client.sell_token(token_address, amount, max_slippage)
            
            if result and result.status == TransactionStatus.CONFIRMED:
                self.total_trades += 1
                self.logger.info(f"✅ SELL SUCCESS: {result.signature}")
                return {
                    'success': True,
                    'signature': result.signature,
                    'amount': amount,
                    'paper_trade': False
                }
            else:
                self.logger.error(f"❌ SELL FAILED: {result.error if result else 'Unknown error'}")
                return {'success': False, 'error': result.error if result else 'Transaction failed'}
                
        except Exception as e:
            self.logger.error(f"❌ SELL ORDER ERROR: {e}")
            return {'success': False, 'error': str(e)}

    async def get_wallet_info(self) -> Dict:
        """Get current wallet information"""
        if not self.solana_client:
            return {'error': 'Solana client not available'}
        
        try:
            balance = await self.solana_client.get_balance('ALL')
            return {
                'wallet_address': self.solana_client.wallet_address,
                'sol_balance': balance.sol_balance,
                'token_balances': balance.token_balances,
                'total_value_usd': balance.total_value_usd,
                'last_updated': balance.last_updated.isoformat()
            }
        except Exception as e:
            return {'error': str(e)}
            
    async def analyze_token_comprehensive(self, token_address: str) -> Dict:
        """
        Run comprehensive analysis on a token
        
        Analysis includes:
        1. RugCheck security analysis
        2. DexScreener market data analysis
        3. Risk assessment
        4. Trading recommendation
        """
        self.logger.info(f"🔬 Starting comprehensive analysis for {token_address[:8]}...")
        
        analysis_results = {
            'token_address': token_address,
            'timestamp': time.time(),
            'rugcheck_analysis': None,
            'dexscreener_analysis': None,
            'market_analysis': None,
            'risk_assessment': None,
            'trading_recommendation': None,
            'passed_all_checks': False,
            'alerts': []
        }
        
        try:
            # 1. RUGCHECK SECURITY ANALYSIS
            self.logger.info(f"🔒 Running RugCheck analysis...")
            
            rugcheck_result = self.rugcheck_analyzer.analyze_token_safety(token_address)
            analysis_results['rugcheck_analysis'] = rugcheck_result
            
            # Convert AnalysisResult to dict if needed
            if isinstance(rugcheck_result, AnalysisResult):
                rugcheck_dict = {
                    'safety_score': rugcheck_result.safety_score,
                    'safety_rating': rugcheck_result.safety_rating.value if hasattr(rugcheck_result.safety_rating, 'value') else str(rugcheck_result.safety_rating),
                    'is_safe': rugcheck_result.is_safe,
                    'bundle_detected': rugcheck_result.bundle_detected,
                    'bundle_confidence': rugcheck_result.bundle_confidence,
                    'passed_verification': rugcheck_result.passed_verification,
                    'error': rugcheck_result.error,
                    'token_symbol': rugcheck_result.token_symbol,
                    'token_name': rugcheck_result.token_name,
                    'risk_indicators': rugcheck_result.risk_indicators
                }
                analysis_results['rugcheck_analysis'] = rugcheck_dict
                rugcheck_result = rugcheck_dict
            
            # Check for critical issues
            if rugcheck_result.get('error'):
                analysis_results['alerts'].append({
                    'type': 'analysis_error',
                    'message': f"RugCheck analysis failed: {rugcheck_result['error']}"
                })
            
            if rugcheck_result.get('bundle_detected', False):
                analysis_results['alerts'].append({
                    'type': 'bundle_detected',
                    'confidence': rugcheck_result.get('bundle_confidence', 0),
                    'message': f"Bundle detected with {rugcheck_result.get('bundle_confidence', 0):.1%} confidence"
                })
            
            if rugcheck_result.get('safety_score', 0) < self.strategy_config['min_safety_score']:
                analysis_results['alerts'].append({
                    'type': 'low_safety_score',
                    'score': rugcheck_result.get('safety_score', 0),
                    'message': f"Safety score {rugcheck_result.get('safety_score', 0):.3f} below threshold {self.strategy_config['min_safety_score']}"
                })
            

            # 2. DEXSCREENER MARKET ANALYSIS
            self.logger.info(f"📊 Running DexScreener market analysis...")
            dexscreener_data = None
            
            if self.dexscreener_integration:
                try:
                    # Get comprehensive trading data
                    dexscreener_data = self.dexscreener_integration.get_token_trading_data(
                        token_address, 'solana'
                    )
                    
                    if 'error' not in dexscreener_data:
                        analysis_results['dexscreener_analysis'] = dexscreener_data
                        
                        # Check market data quality
                        market_data = dexscreener_data.get('market_data', {})
                        if market_data.get('liquidity_usd', 0) < self.trading_config['min_liquidity_usd']:
                            analysis_results['alerts'].append({
                                'type': 'low_liquidity',
                                'value': market_data.get('liquidity_usd', 0),
                                'message': f"Low liquidity: ${market_data.get('liquidity_usd', 0):,.0f}"
                            })
                        
                        # Check for suspicious volume patterns
                        if market_data.get('volume_to_liquidity_ratio', 0) > 10:
                            analysis_results['alerts'].append({
                                'type': 'high_volume_ratio',
                                'value': market_data.get('volume_to_liquidity_ratio', 0),
                                'message': f"Suspicious volume/liquidity ratio: {market_data.get('volume_to_liquidity_ratio', 0):.1f}"
                            })
                    else:
                        analysis_results['alerts'].append({
                            'type': 'dexscreener_error',
                            'message': f"DexScreener analysis failed: {dexscreener_data.get('error')}"
                        })
                        
                except Exception as e:
                    self.logger.warning(f"DexScreener analysis failed: {e}")
                    analysis_results['alerts'].append({
                        'type': 'dexscreener_error',
                        'message': f"DexScreener analysis error: {str(e)}"
                    })

            # 3. ENHANCED MARKET ANALYSIS (combining both sources)
            self.logger.info(f"📈 Running enhanced market analysis...")
            analysis_results['market_analysis'] = self._create_enhanced_market_analysis(
                rugcheck_result, dexscreener_data
            )
            
            # 4. RISK ASSESSMENT (enhanced with market data)
            self.logger.info(f"⚖️ Running enhanced risk assessment...")
            analysis_results['risk_assessment'] = self._assess_token_risk_enhanced(
                rugcheck_result, dexscreener_data
            )
            
            # 5. TRADING RECOMMENDATION (enhanced with market data)
            self.logger.info(f"💡 Generating enhanced trading recommendation...")
            analysis_results['trading_recommendation'] = self._generate_trading_recommendation_enhanced(
                rugcheck_result, dexscreener_data, analysis_results['risk_assessment']
            )
            
            # Overall pass/fail (enhanced criteria)
            analysis_results['passed_all_checks'] = self._evaluate_overall_suitability(
                rugcheck_result, dexscreener_data, analysis_results
            )
            
            self.logger.info(f"✅ Analysis complete for {token_address[:8]}... - "
                           f"Passed: {'✅' if analysis_results['passed_all_checks'] else '❌'}")
            
            return analysis_results
            
        except Exception as e:
            self.logger.error(f"❌ Error in comprehensive analysis: {e}")
            analysis_results['error'] = str(e)
            analysis_results['alerts'].append({
                'type': 'analysis_error',
                'message': f"Analysis failed: {str(e)}"
            })
            return analysis_results


    def _create_enhanced_market_analysis(self, rugcheck_result: Dict, dexscreener_data: Dict) -> Dict:
        """Create enhanced market analysis combining RugCheck and DexScreener data"""
        market_analysis = {
            'price_usd': None,
            'volume_24h': None,
            'liquidity': None,
            'market_cap': None,
            'age_hours': None,
            'trading_activity': None,
            'market_health_score': 0.0,
            'data_sources': []
        }
        
        try:
            # Extract data from DexScreener if available
            if dexscreener_data and 'error' not in dexscreener_data:
                price_data = dexscreener_data.get('price_data', {})
                market_data = dexscreener_data.get('market_data', {})
                trading_metrics = dexscreener_data.get('trading_metrics', {})
                
                market_analysis.update({
                    'price_usd': price_data.get('current_price_usd'),
                    'volume_24h': market_data.get('volume_24h'),
                    'liquidity': market_data.get('liquidity_usd'),
                    'market_cap': market_data.get('market_cap'),
                    'age_hours': market_data.get('age_hours'),
                    'trading_activity': {
                        'buys_24h': trading_metrics.get('buys_24h', 0),
                        'sells_24h': trading_metrics.get('sells_24h', 0),
                        'volume_to_liquidity_ratio': trading_metrics.get('volume_to_liquidity_ratio', 0)
                    }
                })
                market_analysis['data_sources'].append('DexScreener')
            
            # Calculate market health score
            health_score = 0.0
            max_score = 100.0
            
            # Liquidity factor (30 points max)
            if market_analysis['liquidity']:
                if market_analysis['liquidity'] >= 100000:
                    health_score += 30
                elif market_analysis['liquidity'] >= 50000:
                    health_score += 20
                elif market_analysis['liquidity'] >= 10000:
                    health_score += 10
            
            # Volume factor (25 points max)
            if market_analysis['volume_24h'] and market_analysis['liquidity']:
                volume_ratio = market_analysis['volume_24h'] / market_analysis['liquidity']
                if 0.5 <= volume_ratio <= 5:  # Healthy range
                    health_score += 25
                elif 0.1 <= volume_ratio <= 10:  # Acceptable range
                    health_score += 15
                elif volume_ratio > 0:
                    health_score += 5
            
            # Trading activity factor (20 points max)
            trading_activity = market_analysis.get('trading_activity', {})
            if trading_activity:
                total_txns = trading_activity.get('buys_24h', 0) + trading_activity.get('sells_24h', 0)
                if total_txns >= 100:
                    health_score += 20
                elif total_txns >= 50:
                    health_score += 15
                elif total_txns >= 10:
                    health_score += 10
            
            # Age factor (15 points max)
            if market_analysis['age_hours']:
                if 24 <= market_analysis['age_hours'] <= 720:  # 1 day to 30 days
                    health_score += 15
                elif 1 <= market_analysis['age_hours'] <= 2160:  # Up to 90 days
                    health_score += 10
                elif market_analysis['age_hours'] > 0:
                    health_score += 5
            
            # Price stability factor (10 points max)
            # This would require historical data - placeholder for now
            health_score += 5  # Neutral score
            
            market_analysis['market_health_score'] = min(health_score, max_score)
            market_analysis['status'] = 'enhanced_analysis_complete'
            
        except Exception as e:
            self.logger.error(f"Error creating enhanced market analysis: {e}")
            market_analysis['status'] = 'analysis_error'
            market_analysis['error'] = str(e)
        
        return market_analysis

    def _assess_token_risk_enhanced(self, rugcheck_result: Dict, dexscreener_data: Dict) -> Dict:
        """Enhanced risk assessment combining RugCheck and DexScreener data"""
        risk_factors = []
        risk_score = 0
        
        # RugCheck risk factors (existing logic)
        safety_score = rugcheck_result.get('safety_score', 0)
        bundle_detected = rugcheck_result.get('bundle_detected', False)
        bundle_confidence = rugcheck_result.get('bundle_confidence', 0)
        
        if safety_score < 0.3:
            risk_factors.append("Very low safety score")
            risk_score += 40
        elif safety_score < 0.6:
            risk_factors.append("Low safety score")
            risk_score += 20
        elif safety_score < 0.8:
            risk_factors.append("Moderate safety score")
            risk_score += 10
        
        if bundle_detected:
            if bundle_confidence > 0.8:
                risk_factors.append("High confidence bundle detection")
                risk_score += 50
            elif bundle_confidence > 0.5:
                risk_factors.append("Moderate confidence bundle detection")
                risk_score += 30
            else:
                risk_factors.append("Low confidence bundle detection")
                risk_score += 15
        
        # DexScreener risk factors (new)
        if dexscreener_data and 'error' not in dexscreener_data:
            market_data = dexscreener_data.get('market_data', {})
            trading_metrics = dexscreener_data.get('trading_metrics', {})
            risk_assessment = dexscreener_data.get('risk_assessment', {})
            
            # Liquidity risk
            liquidity = market_data.get('liquidity_usd', 0)
            if liquidity < 5000:
                risk_factors.append("Very low liquidity")
                risk_score += 25
            elif liquidity < 20000:
                risk_factors.append("Low liquidity")
                risk_score += 15
            
            # Volume/liquidity ratio risk
            vol_liq_ratio = trading_metrics.get('volume_to_liquidity_ratio', 0)
            if vol_liq_ratio > 10:
                risk_factors.append("Extremely high volume/liquidity ratio")
                risk_score += 20
            elif vol_liq_ratio > 5:
                risk_factors.append("High volume/liquidity ratio")
                risk_score += 10
            
            # Age risk
            age_hours = market_data.get('age_hours', 0)
            if age_hours and age_hours < 1:
                risk_factors.append("Very new token (< 1 hour)")
                risk_score += 20
            elif age_hours and age_hours < 24:
                risk_factors.append("New token (< 24 hours)")
                risk_score += 10
            
            # DexScreener risk level
            dex_risk_level = risk_assessment.get('risk_level', 'UNKNOWN')
            if dex_risk_level == 'HIGH':
                risk_factors.append("High risk according to DexScreener")
                risk_score += 15
            elif dex_risk_level == 'MEDIUM':
                risk_factors.append("Medium risk according to DexScreener")
                risk_score += 5
        
        # Determine overall risk level
        if risk_score >= 80:
            overall_risk = "CRITICAL"
        elif risk_score >= 60:
            overall_risk = "HIGH"
        elif risk_score >= 35:
            overall_risk = "MEDIUM"
        elif risk_score >= 15:
            overall_risk = "LOW"
        else:
            overall_risk = "MINIMAL"
        
        return {
            'risk_score': risk_score,
            'overall_risk': overall_risk,
            'risk_factors': risk_factors,
            'recommendation': self._get_risk_recommendation(overall_risk),
            'sources': ['RugCheck', 'DexScreener'] if dexscreener_data and 'error' not in dexscreener_data else ['RugCheck']
        }

    def _generate_trading_recommendation_enhanced(self, rugcheck_result: Dict, 
                                                dexscreener_data: Dict, 
                                                risk_assessment: Dict) -> Dict:
        """Enhanced trading recommendation incorporating market data"""
        recommendation = {
            'action': 'HOLD',
            'confidence': 0.0,
            'suggested_amount': 0.0,
            'stop_loss': None,
            'take_profit': None,
            'reasoning': [],
            'market_factors': [],
            'data_quality': 'partial'
        }
        
        # Basic RugCheck factors
        safety_score = rugcheck_result.get('safety_score', 0)
        bundle_detected = rugcheck_result.get('bundle_detected', False)
        overall_risk = risk_assessment['overall_risk']
        
        # Enhanced market factors
        market_suitable = False
        liquidity_adequate = False
        
        if dexscreener_data and 'error' not in dexscreener_data:
            recommendation['data_quality'] = 'complete'
            
            market_data = dexscreener_data.get('market_data', {})
            liquidity = market_data.get('liquidity_usd', 0)
            age_hours = market_data.get('age_hours', 0)
            
            # Market suitability checks
            if liquidity >= self.trading_config['min_liquidity_usd']:
                liquidity_adequate = True
                recommendation['market_factors'].append("Adequate liquidity")
            else:
                recommendation['market_factors'].append("Insufficient liquidity")
            
            if age_hours and age_hours >= 1:  # At least 1 hour old
                recommendation['market_factors'].append("Token has some age")
            else:
                recommendation['market_factors'].append("Very new token")
            
            # Check DexScreener recommendation
            dex_recommendation = dexscreener_data.get('recommendation', '')
            if 'BUY' in dex_recommendation:
                recommendation['market_factors'].append("DexScreener suggests buying")
            elif 'AVOID' in dex_recommendation:
                recommendation['market_factors'].append("DexScreener suggests avoiding")
        
        # Enhanced decision logic
        if overall_risk in ['CRITICAL', 'HIGH']:
            recommendation['action'] = 'AVOID'
            recommendation['reasoning'].append(f"Risk level too high: {overall_risk}")
            
        elif bundle_detected:
            recommendation['action'] = 'AVOID'
            recommendation['reasoning'].append("Bundle detected - avoid potential manipulation")
            
        elif safety_score < self.strategy_config['min_safety_score']:
            recommendation['action'] = 'AVOID'
            recommendation['reasoning'].append(f"Safety score {safety_score:.3f} below threshold")
            
        elif not liquidity_adequate:
            recommendation['action'] = 'AVOID'
            recommendation['reasoning'].append("Insufficient liquidity for safe trading")
            
        elif overall_risk == 'MEDIUM' and safety_score >= 0.7 and liquidity_adequate:
            recommendation['action'] = 'BUY'
            recommendation['confidence'] = 0.6
            recommendation['suggested_amount'] = self.trading_config['default_trade_amount'] * 0.4
            recommendation['reasoning'].append("Moderate risk but acceptable safety score and liquidity")
            
        elif overall_risk == 'LOW' and safety_score >= 0.8 and liquidity_adequate:
            recommendation['action'] = 'BUY'
            recommendation['confidence'] = 0.8
            recommendation['suggested_amount'] = self.trading_config['default_trade_amount'] * 0.7
            recommendation['reasoning'].append("Good safety profile with adequate liquidity")
            
        elif overall_risk == 'MINIMAL' and safety_score >= 0.9 and liquidity_adequate:
            recommendation['action'] = 'BUY'
            recommendation['confidence'] = 0.9
            recommendation['suggested_amount'] = self.trading_config['default_trade_amount']
            recommendation['reasoning'].append("Excellent safety profile with good market conditions")
        
        # Set stop loss and take profit if buying
        if recommendation['action'] == 'BUY':
            recommendation['stop_loss'] = self.strategy_config['stop_loss_percentage']
            recommendation['take_profit'] = self.strategy_config['take_profit_percentage']
        
        return recommendation

    def _evaluate_overall_suitability(self, rugcheck_result: Dict, dexscreener_data: Dict, analysis_results: Dict) -> bool:
        """Evaluate overall token suitability for trading"""
        try:
            # Basic RugCheck requirements
            basic_requirements = (
                rugcheck_result.get('passed_verification', False) and
                not rugcheck_result.get('bundle_detected', False) and
                rugcheck_result.get('safety_score', 0) >= self.strategy_config['min_safety_score']
            )
            
            if not basic_requirements:
                return False
            
            # Enhanced requirements with market data
            if dexscreener_data and 'error' not in dexscreener_data:
                market_data = dexscreener_data.get('market_data', {})
                
                # Liquidity requirement
                liquidity_ok = market_data.get('liquidity_usd', 0) >= self.trading_config['min_liquidity_usd']
                
                # Risk level requirement
                risk_ok = analysis_results['risk_assessment']['overall_risk'] in ['LOW', 'MINIMAL', 'MEDIUM']
                
                # Age requirement (at least 30 minutes old to avoid immediate dumps)
                age_hours = market_data.get('age_hours', 0)
                age_ok = not age_hours or age_hours >= 0.5
                
                return liquidity_ok and risk_ok and age_ok
            else:
                # Fallback to basic requirements if no market data
                return analysis_results['risk_assessment']['overall_risk'] in ['LOW', 'MINIMAL', 'MEDIUM']
                
        except Exception as e:
            self.logger.error(f"Error evaluating suitability: {e}")
            return False

    def _assess_token_risk(self, rugcheck_result: Dict) -> Dict:
        """Legacy risk assessment method (kept for compatibility)"""
        return self._assess_token_risk_enhanced(rugcheck_result, None)

    def _get_risk_recommendation(self, risk_level: str) -> str:
        """Get recommendation based on risk level"""
        recommendations = {
            'CRITICAL': 'AVOID - Do not trade this token',
            'HIGH': 'AVOID - High risk, not recommended',
            'MEDIUM': 'CAUTION - Trade with extreme caution and small amounts',
            'LOW': 'PROCEED - Acceptable risk with proper position sizing',
            'MINIMAL': 'PROCEED - Low risk, suitable for trading'
        }
        return recommendations.get(risk_level, 'UNKNOWN')

    def _generate_trading_recommendation(self, rugcheck_result: Dict, risk_assessment: Dict) -> Dict:
        """Legacy trading recommendation method (kept for compatibility)"""
        return self._generate_trading_recommendation_enhanced(rugcheck_result, None, risk_assessment)

    async def process_alerts(self, analysis_results: Dict):
        """Process and log alerts based on analysis results"""
        alerts = analysis_results.get('alerts', [])
        token_address = analysis_results.get('token_address', 'UNKNOWN')
        
        if not alerts:
            return
        
        self.logger.warning(f"🚨 {len(alerts)} alerts for {token_address[:8]}...")
        
        for alert in alerts:
            alert_type = alert['type']
            message = alert['message']
            
            # Log to console/file
            if alert_type == 'bundle_detected':
                self.logger.warning(f"📦 BUNDLE ALERT: {message}")
            elif alert_type == 'low_safety_score':
                self.logger.warning(f"⚠️ SAFETY ALERT: {message}")
            elif alert_type == 'low_liquidity':
                self.logger.warning(f"💧 LIQUIDITY ALERT: {message}")
            elif alert_type == 'high_volume_ratio':
                self.logger.warning(f"📈 VOLUME ALERT: {message}")
            elif alert_type == 'dexscreener_error':
                self.logger.error(f"📊 DEXSCREENER ERROR: {message}")
            elif alert_type == 'analysis_error':
                self.logger.error(f"❌ ANALYSIS ERROR: {message}")
            else:
                self.logger.warning(f"🚨 ALERT ({alert_type}): {message}")
            
            # Store alert in database
            try:
                alert_record = AnalyticsRecord(
                    metric_name=f"alert_{alert_type}",
                    metric_value=alert.get('confidence', alert.get('value', 1.0)),
                    metric_type="alert",
                    timestamp=datetime.now(),
                    metadata={
                        'token_address': token_address,
                        'alert_details': alert
                    }
                )
                self.database_manager.add_analytics_record(alert_record)
            except Exception as e:
                self.logger.error(f"Failed to store alert in database: {e}")

    async def get_trending_tokens(self, limit: int = 10) -> List[Dict]:
        """Get trending tokens from DexScreener"""
        trending_tokens = []
        
        if not self.dexscreener_analyzer:
            self.logger.warning("DexScreener not available for trending tokens")
            return trending_tokens
        
        try:
            # Get trending pairs for Solana
            trending_pairs = await self.dexscreener_analyzer.get_trending_pairs_async(
                chain_ids=[ChainId.SOLANA.value], 
                limit=limit
            )
            
            for pair in trending_pairs:
                try:
                    # Convert TradingPair to dict format
                    token_data = {
                        'token_address': pair.base_token.address,
                        'symbol': pair.base_token.symbol,
                        'name': pair.base_token.name,
                        'price_usd': float(pair.price_usd) if pair.price_usd else None,
                        'price_change_24h': pair.price_change.h24 if pair.price_change else None,
                        'volume_24h': pair.volume.h24 if pair.volume else None,
                        'liquidity_usd': pair.liquidity.usd if pair.liquidity else None,
                        'market_cap': pair.market_cap,
                        'age_hours': pair.age_hours,
                        'dex_id': pair.dex_id,
                        'pair_address': pair.pair_address
                    }
                    trending_tokens.append(token_data)
                    
                except Exception as e:
                    self.logger.error(f"Error processing trending pair: {e}")
                    continue
        
        except Exception as e:
            self.logger.error(f"Error getting trending tokens: {e}")
        
        return trending_tokens

    async def analyze_trending_tokens(self, limit: int = 5) -> List[Dict]:
        """Get and analyze trending tokens"""
        self.logger.info(f"🔥 Analyzing {limit} trending tokens...")
        
        trending_tokens = await self.get_trending_tokens(limit)
        analyzed_tokens = []
        
        for token_data in trending_tokens:
            token_address = token_data['token_address']
            
            try:
                # Run comprehensive analysis
                analysis_result = await self.analyze_token_comprehensive(token_address)
                
                # Combine trending data with analysis
                combined_result = {
                    **token_data,
                    'analysis': analysis_result,
                    'trending_score': self._calculate_trending_score(token_data, analysis_result)
                }
                
                analyzed_tokens.append(combined_result)
                
            except Exception as e:
                self.logger.error(f"Error analyzing trending token {token_address}: {e}")
                continue
        
        # Sort by trending score
        analyzed_tokens.sort(key=lambda x: x.get('trending_score', 0), reverse=True)
        
        return analyzed_tokens

    def _calculate_trending_score(self, token_data: Dict, analysis_result: Dict) -> float:
        """Calculate a trending score combining market data and safety analysis"""
        try:
            score = 0.0
            
            # Market factors (60% weight)
            price_change = token_data.get('price_change_24h', 0)
            volume = token_data.get('volume_24h', 0)
            liquidity = token_data.get('liquidity_usd', 0)
            age_hours = token_data.get('age_hours', 0)
            
            # Price momentum (20 points)
            if price_change:
                if price_change > 50:
                    score += 20
                elif price_change > 20:
                    score += 15
                elif price_change > 10:
                    score += 10
                elif price_change > 0:
                    score += 5
            
            # Volume factor (20 points)
            if volume:
                if volume > 1000000:  # > $1M
                    score += 20
                elif volume > 500000:  # > $500K
                    score += 15
                elif volume > 100000:  # > $100K
                    score += 10
                elif volume > 50000:   # > $50K
                    score += 5
            
            # Liquidity factor (10 points)
            if liquidity:
                if liquidity > 100000:
                    score += 10
                elif liquidity > 50000:
                    score += 7
                elif liquidity > 20000:
                    score += 5
            
            # Age factor (10 points - newer is trendier)
            if age_hours:
                if age_hours < 24:
                    score += 10
                elif age_hours < 168:
                    score += 7
                elif age_hours < 720:
                    score += 3
            
            # Safety factors (40% weight)
            rugcheck_analysis = analysis_result.get('rugcheck_analysis', {})
            risk_assessment = analysis_result.get('risk_assessment', {})
            
            # Safety score factor (25 points)
            safety_score = rugcheck_analysis.get('safety_score', 0)
            score += safety_score * 25
            
            # Risk level factor (15 points)
            overall_risk = risk_assessment.get('overall_risk', 'HIGH')
            risk_scores = {'MINIMAL': 15, 'LOW': 12, 'MEDIUM': 8, 'HIGH': 3, 'CRITICAL': 0}
            score += risk_scores.get(overall_risk, 0)
            
            # Bundle penalty (-20 points)
            if rugcheck_analysis.get('bundle_detected', False):
                score -= 20
            
            return max(0, score)  # Ensure non-negative
            
        except Exception as e:
            self.logger.error(f"Error calculating trending score: {e}")
            return 0.0

    async def run_monitoring_cycle_old(self):
        """Run a complete monitoring cycle with enhanced analysis"""
        cycle_start = datetime.now()
        self.logger.info(f"🔄 Starting enhanced monitoring cycle {self.cycles_completed + 1} at {cycle_start.strftime('%H:%M:%S')}")
        
        try:
            # Get safe tokens from database for analysis
            safe_tokens = self.database_manager.get_safe_tokens(
                min_safety_score=self.strategy_config['min_safety_score'],
                limit=10
            )

            demo_tokens = []

            # Get trending tokens if DexScreener is available
            if self.dexscreener_analyzer:
                try:
                    trending_tokens = await self.get_trending_tokens(limit=3)
                    demo_tokens.extend([t['token_address'] for t in trending_tokens])
                    self.logger.info(f"📈 Added {len(trending_tokens)} trending tokens to analysis")
                except Exception as e:
                    self.logger.warning(f"Could not get trending tokens: {e}")
            
            # Add database tokens
            if safe_tokens:
                demo_tokens.extend([token.address for token in safe_tokens[:2]])
                self.logger.info(f"📊 Added {len(safe_tokens[:2])} database tokens to analysis")

            # Fallback demo tokens if no other source available
            if not demo_tokens:
                demo_tokens = [
                    'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # Bonk
                    'So11111111111111111111111111111111111111112',   # Wrapped SOL
                    'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So'    # Marinade SOL
                ]
                self.logger.info("📊 Using fallback demo tokens")
            
            # Remove duplicates
            demo_tokens = list(set(demo_tokens))[:5]  # Limit to 5 tokens max
            
            # Process each token
            processed_count = 0
            alerts_count = 0
            trading_opportunities = []

            # 🎯 AJOUT: Compteurs pour les résumés visuels
            excellent_tokens = []
            good_tokens = []
            bundle_detected_count = 0
            
            for token_address in demo_tokens:
                if not token_address:
                    continue
                
                self.logger.info(f"🔬 Analyzing {token_address[:8]}...")

                # Run comprehensive analysis
                analysis_results = await self.analyze_token_comprehensive(token_address)
                
                processed_count += 1
                
                # 🎯 NOUVEAU: Log résumé visuel
                self._log_token_result_summary(analysis_results)

                # Process alerts
                await self.process_alerts(analysis_results)
                alerts_count += len(analysis_results.get('alerts', []))
                
                # Check for trading opportunities
                trading_rec = analysis_results.get('trading_recommendation', {})
                if analysis_results.get('passed_all_checks', False):
                    if trading_rec.get('action') == 'BUY' and trading_rec.get('confidence', 0) > 0.7:
                        trading_opportunities.append({
                        'token_address': token_address,
                        'recommendation': trading_rec,
                        'analysis': analysis_results
                        })

                # 🎯 AJOUT: Compter les résultats pour le résumé final
                if analysis_results.get('passed_all_checks', False):
                    token_symbol = analysis_results.get('rugcheck_analysis', {}).get('token_symbol', 'UNKNOWN')
                    confidence = trading_rec.get('confidence', 0)
                
                    if trading_rec.get('action') == 'BUY' and confidence > 0.8:
                        excellent_tokens.append({
                            'address': token_address,
                            'symbol': token_symbol,
                            'confidence': confidence
                        })
                

                # 🎯 AJOUT: Compter les bundles détectés
                if analysis_results.get('rugcheck_analysis', {}).get('bundle_detected', False):
                    bundle_detected_count += 1

                # Store results in database (create a basic token record)
                try:
                    rugcheck_data = analysis_results.get('rugcheck_analysis', {})
                    dexscreener_data = analysis_results.get('dexscreener_analysis', {})
                    market_analysis = analysis_results.get('market_analysis', {})

                    if not rugcheck_data.get('error'):
                        token_record = TokenRecord(
                            address=token_address,
                            symbol=rugcheck_data.get('token_symbol', 'UNKNOWN'),
                            name=rugcheck_data.get('token_name', 'Unknown'),
                            decimals=9,  # Default for Solana
                            status=TokenStatus.ACTIVE,
                            safety_score=rugcheck_data.get('safety_score', 0.0),
                            bundle_detected=rugcheck_data.get('bundle_detected', False),
                            bundle_confidence=rugcheck_data.get('bundle_confidence', 0.0),
                            risk_indicators=rugcheck_data.get('risk_indicators', {}),
                            market_cap=market_analysis.get('market_cap'),
                            volume_24h=market_analysis.get('volume_24h'),
                            price_usd=market_analysis.get('price_usd'),
                            liquidity=market_analysis.get('liquidity'),
                            rugcheck_data=rugcheck_data,
                            dexscreener_data=dexscreener_data
                        )
                        
                        self.database_manager.add_token(token_record)
                except Exception as e:
                    self.logger.error(f"Failed to store token data: {e}")
                
                # Small delay between analyses
                await asyncio.sleep(1)
            
            # 🎯 AJOUT: Afficher le résumé visuel du cycle
            self._log_cycle_summary(excellent_tokens, good_tokens, bundle_detected_count, processed_count)

            # Log trading opportunities
            if trading_opportunities and self.trading_config['auto_trading']:
                self.logger.info(f"💎 Found {len(trading_opportunities)} trading opportunities!")
                for opp in trading_opportunities:
                    try:
                        token_addr = opp['token_address']
                        confidence = opp['recommendation']['confidence']
                        suggested_amount = recommendation.get('suggested_amount', 0)
                        self.logger.info(f"  📈 {token_addr[:8]}... - Confidence: {confidence:.1%}")

                        if suggested_amount > 0:
                            self.logger.info(f"🎯 AUTO-TRADE: Executing buy for {token_addr[:8]}...")
                            
                            trade_result = await self.execute_buy_order(
                                token_addr, 
                                suggested_amount,
                                self.trading_config['max_slippage']
                            )
                            
                            if trade_result['success']:
                                self.logger.info(f"✅ AUTO-TRADE SUCCESS: {trade_result['signature']}")
                            else:
                                self.logger.error(f"❌ AUTO-TRADE FAILED: {trade_result['error']}")
                            
                            # Small delay between trades
                            await asyncio.sleep(2)

                    except Exception as e:
                        self.logger.error(f"Error in auto-trade execution: {e}")

            # Cycle summary
            cycle_duration = (datetime.now() - cycle_start).total_seconds()
            self.cycles_completed += 1
            
            self.logger.info(f"✅ Enhanced Monitoring cycle {self.cycles_completed} complete:")
            self.logger.info(f"   Processed: {processed_count} tokens")
            self.logger.info(f"   Duration: {cycle_duration:.2f}s")
            self.logger.info(f"   Alerts: {alerts_count}")
            self.logger.info(f"   Trading Opportunities: {len(trading_opportunities)}")
            
            # Store cycle metrics
            cycle_record = AnalyticsRecord(
                metric_name="enhanced_monitoring_cycle",
                metric_value=processed_count,
                metric_type="performance",
                timestamp=datetime.now(),
                metadata={
                    'duration': cycle_duration,
                    'alerts_count': alerts_count,
                    'trading_opportunities': len(trading_opportunities),
                    'cycle_number': self.cycles_completed,
                    'dexscreener_enabled': self.dexscreener_analyzer is not None,
                    # 🎯 AJOUT: Métriques visuelles dans les métadonnées
                    'excellent_tokens_count': len(excellent_tokens),
                    'good_tokens_count': len(good_tokens),
                    'bundle_detected_count': bundle_detected_count
                }
            )
            self.database_manager.add_analytics_record(cycle_record)
            
            return {
                'processed_count': processed_count,
                'duration': cycle_duration,
                'alerts_count': alerts_count,
                'trading_opportunities': len(trading_opportunities),
                # 🎯 AJOUT: Retourner aussi les nouvelles métriques
                'excellent_tokens_count': len(excellent_tokens),
                'good_tokens_count': len(good_tokens),
                'bundle_detected_count': bundle_detected_count
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error in enhanced monitoring cycle: {e}")
            raise

    async def run_monitoring_cycle(self):
        """Run a complete monitoring cycle with enhanced analysis"""
        cycle_start = datetime.now()
        self.logger.info(f"🔄 Starting enhanced monitoring cycle {self.cycles_completed + 1} at {cycle_start.strftime('%H:%M:%S')}")
        
        try:
            # Get safe tokens from database for analysis
            safe_tokens = self.database_manager.get_safe_tokens(
                min_safety_score=self.strategy_config['min_safety_score'],
                limit=10
            )

            demo_tokens = []

            # OPTION A: Trending optimisé (1 seul appel API)
            if self.dexscreener_analyzer:
                try:
                    # Utiliser la NOUVELLE méthode get_trending_pairs
                    trending_data = self.dexscreener_analyzer.get_trending_pairs(
                        chain_ids=['solana'], 
                        limit=5
                    )
                    
                    if trending_data:
                        print(f"🔥 TRENDING TOKENS OPTIMIZED:")
                        for i, pair in enumerate(trending_data, 1):
                            price_change = pair.price_change.h24 if pair.price_change else 0
                            volume = pair.volume.h24 if pair.volume else 0
                            print(f"   {i}. 🔥 {pair.base_token.symbol} - {price_change:+.1f}% - Vol: ${volume:,.0f}")
                            
                            demo_tokens.append(pair.base_token.address)
                        
                        self.logger.info(f"📈 Added {len(trending_data)} trending tokens (optimized)")
                    
                except Exception as e:
                    self.logger.warning(f"Could not get trending tokens: {e}")

            if self.dexscreener_analyzer and len(demo_tokens) < 5:
                try:
                    # Utiliser la méthode get_newest_tokens_realtime
                    #newest_tokens = await self.dexscreener_analyzer.get_newest_tokens_realtime(hours_back=3)
                    hours_back = 3
                    #nouvelle méthode pas basée sur des mots-clés mais sur des timestamps
                    newest_tokens = await self.dexscreener_analyzer.get_newest_tokens_by_timestamp(hours_back)
                    if newest_tokens:
                        print(f"\n🆕 NOUVEAUX TOKENS (dernières {hours_back}h):")
                        for i, token in enumerate(newest_tokens[:3], 1):
                            # Filtres de qualité avant d'ajouter
                            if (token['liquidity_usd'] >= 5000 and 
                                token['age_hours'] >= 0.5 and 
                                token['age_hours'] <= 72):
                                
                                demo_tokens.append(token['token_address'])
                                print(f"   {i}. 🆕 {token['symbol']} - Age: {token['age_hours']:.1f}h - Liq: ${token['liquidity_usd']:,.0f}")
                        
                        self.logger.info(f"🆕 Added {len([t for t in newest_tokens[:3] if t['liquidity_usd'] >= 5000])} newest quality tokens")
                    else:
                        self.logger.info("🆕 No new tokens found in specified timeframe")
                
                except Exception as e:
                    self.logger.warning(f"Could not get newest tokens: {e}")
            
            # Add database tokens
            if safe_tokens:
                demo_tokens.extend([token.address for token in safe_tokens[:2]])
                self.logger.info(f"📊 Added {len(safe_tokens[:2])} database tokens to analysis")

            # Fallback demo tokens if no other source available
            if not demo_tokens:
                demo_tokens = [
                    'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # Bonk
                    'So11111111111111111111111111111111111111112',   # Wrapped SOL
                    'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So'    # Marinade SOL
                ]
                self.logger.info("📊 Using fallback demo tokens")
            
            # Remove duplicates
            demo_tokens = list(set(demo_tokens))[:5]  # Limit to 5 tokens max
            
            # Process each token
            processed_count = 0
            alerts_count = 0
            trading_opportunities = []

            # 🎯 AJOUT: Compteurs pour les résumés visuels
            excellent_tokens = []
            good_tokens = []
            bundle_detected_count = 0
            
            for token_address in demo_tokens:
                if not token_address:
                    continue
                
                self.logger.info(f"🔬 Analyzing {token_address[:8]}...")

                # Run comprehensive analysis
                analysis_results = await self.analyze_token_comprehensive(token_address)
                
                processed_count += 1
                
                # 🎯 NOUVEAU: Log résumé visuel
                self._log_token_result_summary(analysis_results)

                # Process alerts
                await self.process_alerts(analysis_results)
                alerts_count += len(analysis_results.get('alerts', []))
                
                # Check for trading opportunities
                trading_rec = analysis_results.get('trading_recommendation', {})
                if analysis_results.get('passed_all_checks', False):
                    if trading_rec.get('action') == 'BUY' and trading_rec.get('confidence', 0) > 0.7:
                        trading_opportunities.append({
                        'token_address': token_address,
                        'recommendation': trading_rec,
                        'analysis': analysis_results
                        })

                # 🎯 AJOUT: Compter les résultats pour le résumé final
                if analysis_results.get('passed_all_checks', False):
                    token_symbol = analysis_results.get('rugcheck_analysis', {}).get('token_symbol', 'UNKNOWN')
                    confidence = trading_rec.get('confidence', 0)
                
                    if trading_rec.get('action') == 'BUY' and confidence > 0.8:
                        excellent_tokens.append({
                            'address': token_address,
                            'symbol': token_symbol,
                            'confidence': confidence
                        })
                    elif trading_rec.get('action') == 'BUY' and confidence > 0.6:
                        good_tokens.append({
                            'address': token_address,
                            'symbol': token_symbol,
                            'confidence': confidence
                        })
                

                # 🎯 AJOUT: Compter les bundles détectés
                if analysis_results.get('rugcheck_analysis', {}).get('bundle_detected', False):
                    bundle_detected_count += 1

                # Store results in database (create a basic token record)
                try:
                    rugcheck_data = analysis_results.get('rugcheck_analysis', {})
                    dexscreener_data = analysis_results.get('dexscreener_analysis', {})
                    market_analysis = analysis_results.get('market_analysis', {})

                    if not rugcheck_data.get('error'):
                        token_record = TokenRecord(
                            address=token_address,
                            symbol=rugcheck_data.get('token_symbol', 'UNKNOWN'),
                            name=rugcheck_data.get('token_name', 'Unknown'),
                            decimals=9,  # Default for Solana
                            status=TokenStatus.ACTIVE,
                            safety_score=rugcheck_data.get('safety_score', 0.0),
                            bundle_detected=rugcheck_data.get('bundle_detected', False),
                            bundle_confidence=rugcheck_data.get('bundle_confidence', 0.0),
                            risk_indicators=rugcheck_data.get('risk_indicators', {}),
                            market_cap=market_analysis.get('market_cap'),
                            volume_24h=market_analysis.get('volume_24h'),
                            price_usd=market_analysis.get('price_usd'),
                            liquidity=market_analysis.get('liquidity'),
                            rugcheck_data=rugcheck_data,
                            dexscreener_data=dexscreener_data
                        )
                        
                        self.database_manager.add_token(token_record)
                except Exception as e:
                    self.logger.error(f"Failed to store token data: {e}")
                
                # Small delay between analyses
                await asyncio.sleep(1)
            
            # 🎯 AJOUT: Afficher le résumé visuel du cycle
            self._log_cycle_summary(excellent_tokens, good_tokens, bundle_detected_count, processed_count)

            # Log trading opportunities
            if trading_opportunities and self.trading_config['auto_trading']:
                self.logger.info(f"💎 Found {len(trading_opportunities)} trading opportunities!")
                for opp in trading_opportunities:
                    try:
                        token_addr = opp['token_address']
                        confidence = opp['recommendation']['confidence']
                        recommendation = opp['recommendation']
                        suggested_amount = trading_rec.get('suggested_amount', 0)
                        self.logger.info(f"  📈 {token_addr[:8]}... - Confidence: {confidence:.1%}")

                        if suggested_amount > 0:
                            self.logger.info(f"🎯 AUTO-TRADE: Executing buy for {token_addr[:8]}...")
                            
                            trade_result = await self.execute_buy_order(
                                token_addr, 
                                suggested_amount,
                                self.trading_config['max_slippage']
                            )
                            
                            if trade_result['success']:
                                self.logger.info(f"✅ AUTO-TRADE SUCCESS: {trade_result['signature']}")
                            else:
                                self.logger.error(f"❌ AUTO-TRADE FAILED: {trade_result['error']}")
                            
                            # Small delay between trades
                            await asyncio.sleep(2)

                    except Exception as e:
                        self.logger.error(f"Error in auto-trade execution: {e}")

            # Cycle summary
            cycle_duration = (datetime.now() - cycle_start).total_seconds()
            self.cycles_completed += 1
            
            self.logger.info(f"✅ Enhanced Monitoring cycle {self.cycles_completed} complete:")
            self.logger.info(f"   Processed: {processed_count} tokens")
            self.logger.info(f"   Duration: {cycle_duration:.2f}s")
            self.logger.info(f"   Alerts: {alerts_count}")
            self.logger.info(f"   Trading Opportunities: {len(trading_opportunities)}")
            
            # Store cycle metrics
            cycle_record = AnalyticsRecord(
                metric_name="enhanced_monitoring_cycle",
                metric_value=processed_count,
                metric_type="performance",
                timestamp=datetime.now(),
                metadata={
                    'duration': cycle_duration,
                    'alerts_count': alerts_count,
                    'trading_opportunities': len(trading_opportunities),
                    'cycle_number': self.cycles_completed,
                    'dexscreener_enabled': self.dexscreener_analyzer is not None,
                    # 🎯 AJOUT: Métriques visuelles dans les métadonnées
                    'excellent_tokens_count': len(excellent_tokens),
                    'good_tokens_count': len(good_tokens),
                    'bundle_detected_count': bundle_detected_count
                }
            )
            self.database_manager.add_analytics_record(cycle_record)
            
            return {
                'processed_count': processed_count,
                'duration': cycle_duration,
                'alerts_count': alerts_count,
                'trading_opportunities': len(trading_opportunities),
                # 🎯 AJOUT: Retourner aussi les nouvelles métriques
                'excellent_tokens_count': len(excellent_tokens),
                'good_tokens_count': len(good_tokens),
                'bundle_detected_count': bundle_detected_count
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error in enhanced monitoring cycle: {e}")
            raise

    def _log_cycle_summary(self, excellent_tokens: List, good_tokens: List, bundle_count: int, total_processed: int):
        """Log un résumé visuel du cycle"""
        
        print(f"\n{'='*80}")
        print(f"📊 RÉSUMÉ DU CYCLE - {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*80}")
        
        if excellent_tokens:
            print(f"🎯 {len(excellent_tokens)} TOKEN(S) EXCELLENT(S) TROUVÉ(S)!")
            for token in excellent_tokens:
                print(f"   🎯 {token['symbol']} ({token['address'][:8]}...) - {token['confidence']:.1%}")
        
        if good_tokens:
            print(f"✅ {len(good_tokens)} bon(s) token(s) trouvé(s)")
            for token in good_tokens:
                print(f"   ✅ {token['symbol']} ({token['address'][:8]}...) - {token['confidence']:.1%}")
        
        if not excellent_tokens and not good_tokens:
            print(f"❌ Aucun token intéressant trouvé sur {total_processed} analysés")
        
        if bundle_count > 0:
            print(f"🚫 {bundle_count} bundle(s) détecté(s) et évité(s)")
        
        print(f"📈 Total analysé: {total_processed} tokens")
        print(f"{'='*80}\n")
        
        # Log dans le fichier aussi
        self.logger.info(f"📊 CYCLE SUMMARY: {len(excellent_tokens)} excellent, {len(good_tokens)} good, {bundle_count} bundles, {total_processed} total")


    async def get_trending_tokens(self, limit: int = 10) -> List[Dict]:
        """Version modifiée avec log des tokens trending trouvés"""
        trending_tokens = []
        
        if not self.dexscreener_analyzer:
            self.logger.warning("DexScreener not available for trending tokens")
            return trending_tokens
        
        try:
            trending_pairs = await self.dexscreener_analyzer.get_trending_pairs_async(
                chain_ids=[ChainId.SOLANA.value], 
                limit=limit
            )
            
            print(f"\n🔥 TOKENS TRENDING TROUVÉS:")
            for i, pair in enumerate(trending_pairs, 1):
                token_data = {
                    'token_address': pair.base_token.address,
                    'symbol': pair.base_token.symbol,
                    'name': pair.base_token.name,
                    'price_usd': float(pair.price_usd) if pair.price_usd else None,
                    'price_change_24h': pair.price_change.h24 if pair.price_change else None,
                    'volume_24h': pair.volume.h24 if pair.volume else None,
                    'liquidity_usd': pair.liquidity.usd if pair.liquidity else None,
                    'market_cap': pair.market_cap,
                    'age_hours': pair.age_hours,
                    'dex_id': pair.dex_id,
                    'pair_address': pair.pair_address
                }
                trending_tokens.append(token_data)
                
                # Log visuel des tokens trending
                change_str = f"{token_data['price_change_24h']:+.1f}%" if token_data['price_change_24h'] is not None else "N/A"
                volume_str = f"${token_data['volume_24h']:,.0f}" if token_data['volume_24h'] else "N/A"
                print(f"   {i}. 🔥 {token_data['symbol']} - {change_str} - Vol: {volume_str}")
                
        except Exception as e:
            self.logger.error(f"Error getting trending tokens: {e}")
        
        return trending_tokens

    async def initialize_dex_scanner(self):
        """Initialiser le scanner de manière asynchrone"""
        if not self.scanner_enabled:
            return None
        
        try:
            self.logger.info("🔍 Starting DEX Listings Scanner...")
            
            # Créer le scanner avec intégration
            self.dex_scanner = await create_dex_scanner_integration(
                self.config,
                self.database_manager,
                self.rugcheck_analyzer,
                self.analyze_token_comprehensive  # Callback pour analyse complète
            )
            
            # Démarrer le scanner en arrière-plan
            self.scanner_task = asyncio.create_task(
                self.dex_scanner.start_scanning(),
                name="dex_scanner"
            )
            
            self.logger.info("✅ DEX Listings Scanner started successfully")
            self.scanner_stats['status'] = 'running'
            
            return self.dex_scanner
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start DEX scanner: {e}")
            self.scanner_enabled = False
            self.scanner_stats['status'] = 'failed'
            return None

    async def run_scanner_mode(self):
        """Mode scanner uniquement - écoute continue des nouvelles paires"""
        print("\n🔍 STARTING DEX LISTINGS SCANNER MODE")
        print("=" * 60)
        print("🎯 Real-time monitoring of new token listings")
        print("🔄 Automatic analysis and filtering")
        print("💾 Database storage of discoveries")
        print("=" * 60)
        
        self.is_running = True
        
        try:
            # Initialiser le scanner
            scanner = await self.initialize_dex_scanner()
            if not scanner:
                print("❌ Failed to start scanner")
                return
            
            # Afficher les statistiques périodiquement
            async def show_stats():
                while self.is_running:
                    await asyncio.sleep(300)  # Toutes les 5 minutes
                    if scanner:
                        stats = scanner.get_stats()
                        self.logger.info(
                            f"📊 SCANNER STATS: "
                            f"{stats['valid_new_pairs']} new pairs, "
                            f"{stats['duplicate_pairs']} duplicates, "
                            f"{stats['filtered_pairs']} filtered, "
                            f"Uptime: {stats['uptime_hours']:.1f}h"
                        )
            
            # Démarrer l'affichage des stats
            stats_task = asyncio.create_task(show_stats())
            
            print("🔍 Scanner is running... Press Ctrl+C to stop")
            print("📊 Statistics will be shown every 5 minutes")
            
            # Attendre jusqu'à l'arrêt
            await asyncio.gather(
                self.scanner_task,
                stats_task,
                return_exceptions=True
            )
            
        except KeyboardInterrupt:
            print("\n🛑 Scanner stopped by user")
        except Exception as e:
            self.logger.error(f"❌ Scanner error: {e}")
        finally:
            if scanner:
                scanner.stop_scanning()
            self.is_running = False

    async def run_hybrid_mode(self, interval_minutes=None):
        """Mode hybride - scanner + cycles d'analyse traditionnels"""
        if interval_minutes is None:
            interval_minutes = self.trading_config['analysis_interval_seconds'] // 60
            
        print("\n🔄 STARTING HYBRID MODE (Scanner + Traditional Cycles)")
        print("=" * 70)
        print("🔍 Real-time DEX listings monitoring")
        print("🔄 Periodic trending token analysis")
        print("💎 Combined discovery and analysis")
        print("=" * 70)
        
        self.is_running = True
        
        try:
            # Démarrer le scanner
            scanner = await self.initialize_dex_scanner()
            
            # Démarrer les cycles traditionnels
            async def traditional_cycles():
                while self.is_running:
                    try:
                        self.logger.info("🔄 Running traditional analysis cycle...")
                        cycle_results = await self.run_monitoring_cycle()
                        
                        # Afficher les résultats combinés
                        scanner_stats = scanner.get_stats() if scanner else {}
                        print(f"📊 Hybrid Cycle: "
                              f"Traditional: {cycle_results['processed_count']} tokens, "
                              f"Scanner: {scanner_stats.get('valid_new_pairs', 0)} discoveries")
                        
                        await asyncio.sleep(interval_minutes * 60)
                        
                    except Exception as e:
                        self.logger.error(f"Error in traditional cycle: {e}")
                        await asyncio.sleep(60)
            
            # Lancer les deux modes en parallèle
            traditional_task = asyncio.create_task(traditional_cycles())
            
            tasks = [traditional_task]
            if scanner:
                tasks.append(self.scanner_task)
            
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except KeyboardInterrupt:
            print("\n🛑 Hybrid mode stopped by user")
        except Exception as e:
            self.logger.error(f"❌ Hybrid mode error: {e}")
        finally:
            if scanner:
                scanner.stop_scanning()
            self.is_running = False

    async def run_continuous_monitoring(self, interval_minutes=None):
        """Version améliorée avec support du scanner"""
        if interval_minutes is None:
            interval_minutes = self.trading_config['analysis_interval_seconds'] // 60
            
        # Déterminer le mode basé sur la configuration
        if self.scanner_enabled:
            mode = "HYBRID"
            description = f"Scanner + Traditional Cycles (every {interval_minutes}m)"
        else:
            mode = "TRADITIONAL"
            description = f"Traditional Cycles Only (every {interval_minutes}m)"
        
        print(f"\n🤖 Enhanced Bot Started - {mode} MODE")
        print(f"📊 {description}")
        print(f"📊 Paper Trading: {'Enabled' if self.trading_config['paper_trading'] else 'Disabled'}")
        print(f"🎯 Strategy: {self.config['strategies']['default_strategy']}")
        print(f"📈 DexScreener: {'Enabled' if self.dexscreener_analyzer else 'Disabled'}")
        if self.scanner_enabled:
            enabled_dexs = self.config.get('scanner', {}).get('enabled_dexs', [])
            print(f"🔍 Scanner DEXs: {', '.join(enabled_dexs)}")
        print("Press Ctrl+C to stop")
        print("=" * 80)
        
        try:
            if self.scanner_enabled:
                await self.run_hybrid_mode(interval_minutes)
            else:
                # Mode traditionnel existant
                await self.run_continuous_monitoring_traditional(interval_minutes)
                
        except KeyboardInterrupt:
            self.logger.info("🛑 Enhanced Monitoring stopped by user")
            print("\n🛑 Enhanced Bot Stopped by user")
        except Exception as e:
            self.logger.error(f"❌ Error in enhanced continuous monitoring: {e}")
            print(f"\n❌ Enhanced Bot Error: {e}")
            raise

    async def run_continuous_monitoring_traditional(self, interval_minutes=None):
        """Run continuous monitoring with specified interval"""
        if interval_minutes is None:
            interval_minutes = self.trading_config['analysis_interval_seconds'] // 60
            
        self.logger.info(f"🔄 Starting enhanced continuous monitoring (interval: {interval_minutes}m)")
        self.is_running = True
        
        # Send startup notification (console only for now)
        print(f"\n🤖Enhanced Bot Started - Monitoring every {interval_minutes} minutes")
        print(f"📊 Paper Trading: {'Enabled' if self.trading_config['paper_trading'] else 'Disabled'}")
        print(f"🎯 Strategy: {self.config['strategies']['default_strategy']}")
        print(f"📈 DexScreener: {'Enabled' if self.dexscreener_analyzer else 'Disabled'}")
        
        try:
            while self.is_running:
                # Run monitoring cycle
                cycle_results = await self.run_monitoring_cycle()
                
                # Periodic maintenance every 10 cycles
                if self.cycles_completed % 10 == 0:
                    await self.perform_maintenance()
                
                # Display progress
                uptime = datetime.now() - self.start_time
                print(f"🔄 Cycle {self.cycles_completed} | "
                      f"Uptime: {uptime.total_seconds()/3600:.1f}h | "
                      f"Processed: {cycle_results['processed_count']} | "
                      f"Alerts: {cycle_results['alerts_count']} | "
                      f"Opportunities: {cycle_results.get('trading_opportunities', 0)}")
                
                # Sleep until next cycle
                if self.is_running:  # Check if still running
                    await asyncio.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            self.logger.info("🛑 Enhanced Monitoring stopped by user")
            print("\n🛑 Enhanced Bot Stopped by user")
        except Exception as e:
            self.logger.error(f"❌ Error in enthanced continuous monitoring: {e}")
            print(f"\n❌ Enhanced Bot Error: {e}")
            raise

    async def perform_maintenance(self):
        """Perform periodic maintenance tasks with DexScreener support"""
        self.logger.info("🔧 Starting enhanced periodic maintenance...")
        
        try:
            # Clear expired caches (RugCheck)
            if hasattr(self.rugcheck_analyzer, 'clear_expired_cache'):
                cleared = self.rugcheck_analyzer.clear_expired_cache()
                self.logger.info(f"🧹 Cleared {cleared} expired cache entries")
            
            # Clear expired caches (DexScreener)
            if self.dexscreener_analyzer:
                try:
                    if hasattr(self.dexscreener_analyzer, 'clear_cache'):
                        success = self.dexscreener_analyzer.clear_cache()
                        self.logger.info(f"📊 DexScreener cache cleared: {success}")
                except Exception as e:
                    self.logger.warning(f"DexScreener cache clear failed: {e}")

            # Database cleanup
            cleanup_stats = self.database_manager.cleanup_old_data(days_to_keep=30)
            if cleanup_stats:
                self.logger.info(f"🗄️ Database cleanup: {cleanup_stats}")
            
            # Health check
            if hasattr(self.rugcheck_analyzer, 'get_health_status'):
                health = self.rugcheck_analyzer.get_health_status()
                self.logger.info(f"💚 RugCheck health: {health['overall_health']}")
            
            if self.dexscreener_analyzer:
                try:
                    performance_stats = self.dexscreener_analyzer.get_performance_stats()
                    success_rate = performance_stats['performance_metrics']['successful_requests'] / max(performance_stats['performance_metrics']['total_requests'], 1) * 100
                    self.logger.info(f"📊 DexScreener health: {success_rate:.1f}% success rate")
                except Exception as e:
                    self.logger.warning(f"DexScreener health check failed: {e}")
            
            self.logger.info("✅ Enhanced periodic maintenance complete")
            
        except Exception as e:
            self.logger.error(f"❌ Error in enhanced maintenance: {e}")

    def get_comprehensive_statistics(self) -> Dict:
        """Get comprehensive statistics from all components including DexScreener"""
        uptime = datetime.now() - self.start_time
        
        stats = {
            'system': {
                'uptime_seconds': uptime.total_seconds(),
                'uptime_human': f"{uptime.total_seconds()/3600:.1f}h",
                'cycles_completed': self.cycles_completed,
                'environment': ENVIRONMENT,
                'strategy': self.config['strategies']['default_strategy'],
                'paper_trading': self.trading_config['paper_trading'],
                'dexscreener_enabled': self.dexscreener_analyzer is not None
            },
            'database': self.database_manager.get_database_stats(),
            'portfolio': self.portfolio.copy(),
            'rugcheck': None,
            'dexscreener': None,
            'trading': {
                'total_trades': self.total_trades,
                'daily_trades': 0,  # TODO: Calculate from database
                'success_rate': 0.0  # TODO: Calculate from database
            }
        }

        # Solana client stats
        if self.solana_client:
            stats['solana_client'] = self.solana_client.get_performance_metrics()
            # Get current wallet info
            stats['wallet'] = {
                'address': self.solana_client.wallet_address,
                'mode': 'READ_ONLY' if not self.solana_client.keypair else 'FULL',
                'note': 'Use --wallet-info for detailed balance information'
            }

        # Get RugCheck stats if available
        if hasattr(self.rugcheck_analyzer, 'get_analysis_stats'):
            stats['rugcheck'] = self.rugcheck_analyzer.get_analysis_stats()
        
        # 🆕 NOUVEAU: Ajouter les stats du scanner
        if self.scanner_enabled and hasattr(self, 'dex_scanner') and self.dex_scanner:
            try:
                scanner_stats = self.dex_scanner.get_stats()
                stats['dex_scanner'] = {
                    'enabled': True,
                    'status': 'running' if self.is_running else 'stopped',
                    'total_discoveries': scanner_stats['valid_new_pairs'],
                    'filtered_pairs': scanner_stats['filtered_pairs'],
                    'duplicate_pairs': scanner_stats['duplicate_pairs'],
                    'uptime_hours': scanner_stats['uptime_hours'],
                    'enabled_dexs': scanner_stats['enabled_dexs'],
                    'cache_size': scanner_stats['cache_size'],
                    'last_discovery': scanner_stats['last_pair_time']
                }
            except Exception as e:
                stats['dex_scanner'] = {
                    'enabled': True,
                    'status': 'error',
                    'error': str(e)
                }
        else:
            stats['dex_scanner'] = {
                'enabled': False,
                'status': 'disabled'
            }

        return stats

    def _log_token_result_summary(self, analysis_results: Dict):
        """Log un résumé visuel du résultat d'analyse"""
        token_address = analysis_results.get('token_address', 'UNKNOWN')
        passed = analysis_results.get('passed_all_checks', False)
        
        # Récupérer les données principales
        rugcheck_data = analysis_results.get('rugcheck_analysis', {})
        dexscreener_data = analysis_results.get('dexscreener_analysis', {})
        trading_rec = analysis_results.get('trading_recommendation', {})
        risk_assessment = analysis_results.get('risk_assessment', {})
        
        token_symbol = rugcheck_data.get('token_symbol', 'UNKNOWN')
        safety_score = rugcheck_data.get('safety_score', 0)
        bundle_detected = rugcheck_data.get('bundle_detected', False)
        action = trading_rec.get('action', 'UNKNOWN')
        confidence = trading_rec.get('confidence', 0)
        risk_level = risk_assessment.get('overall_risk', 'UNKNOWN')
    
        # Prix et données de marché
        price_data = dexscreener_data.get('price_data', {}) if dexscreener_data else {}
        market_data = dexscreener_data.get('market_data', {}) if dexscreener_data else {}
        
        price_usd = price_data.get('current_price_usd')
        price_change_24h = price_data.get('price_change_24h')
        liquidity = market_data.get('liquidity_usd')
        volume_24h = market_data.get('volume_24h')
    
        # NOUVEAU: Afficher les seuils et scores pour debug
        strategy_config = get_strategy_config()
        min_safety_required = strategy_config['min_safety_score']
        max_bundle_allowed = strategy_config['max_bundle_confidence']

        # Format du message selon le résultat
        if passed and action == 'BUY' and confidence > 0.7:
            # 🎯 TOKEN EXCELLENT - Messages très visibles
            separator = "🎯" + "="*80 + "🎯"
            self.logger.info(separator)
            self.logger.info(f"🎯🎯🎯 EXCELLENT TOKEN DETECTÉ! 🎯🎯🎯")
            self.logger.info(f"📍 Token: {token_symbol} ({token_address[:8]}...{token_address[-8:]})")
            self.logger.info(f"💰 Prix: ${price_usd:.8f}" if price_usd else "💰 Prix: N/A")
            self.logger.info(f"📈 Change 24h: {price_change_24h:+.2f}%" if price_change_24h is not None else "📈 Change 24h: N/A")
            self.logger.info(f"💧 Liquidité: ${liquidity:,.0f}" if liquidity else "💧 Liquidité: N/A")
            self.logger.info(f"📊 Volume 24h: ${volume_24h:,.0f}" if volume_24h else "📊 Volume 24h: N/A")
            self.logger.info(f"🛡️ Safety Score: {safety_score:.3f}")
            self.logger.info(f"⚖️ Risque: {risk_level}")
            self.logger.info(f"🎯 Action: {action} (Confiance: {confidence:.1%})")
            self.logger.info(separator)
            
            # Message console supplémentaire
            print(f"\n🚨🎯 ALERTE TOKEN EXCELLENT! 🎯🚨")
            print(f"📍 {token_symbol} - {token_address[:8]}...{token_address[-8:]}")
            print(f"🎯 {action} - Confiance: {confidence:.1%}")
            print(f"🛡️ Safety: {safety_score:.3f} | Risk: {risk_level}")
            
        elif passed and action == 'BUY':
            # ✅ TOKEN BON - Messages modérément visibles
            self.logger.info("✅" + "="*60 + "✅")
            self.logger.info(f"✅ BON TOKEN TROUVÉ: {token_symbol} ({token_address[:8]}...)")
            self.logger.info(f"🎯 Action: {action} (Confiance: {confidence:.1%})")
            self.logger.info(f"🛡️ Safety: {safety_score:.3f} | Risk: {risk_level}")
            if price_usd:
                self.logger.info(f"💰 Prix: ${price_usd:.8f}")
            if liquidity:
                self.logger.info(f"💧 Liquidité: ${liquidity:,.0f}")
            self.logger.info("✅" + "="*60 + "✅")
            
            print(f"\n✅ BON TOKEN: {token_symbol} - {action} ({confidence:.1%})")
            
        elif action == 'CONSIDER':
            # 🤔 TOKEN À CONSIDÉRER
            self.logger.info(f"🤔 Token à considérer: {token_symbol} ({token_address[:8]}...)")
            self.logger.info(f"🎯 {action} | Safety: {safety_score:.3f} | Risk: {risk_level}")
            
        elif bundle_detected:
            # 🚫 BUNDLE DÉTECTÉ - Avertissement visible
            bundle_confidence = rugcheck_data.get('bundle_confidence', 0)
            self.logger.warning("🚫" + "="*60 + "🚫")
            self.logger.warning(f"🚫 BUNDLE DÉTECTÉ: {token_symbol} ({token_address[:8]}...)")
            self.logger.warning(f"📦 Confiance bundle: {bundle_confidence:.1%}")
            self.logger.warning("🚫" + "="*60 + "🚫")
        
        else:
            # ❌ TOKEN REJETÉ - Log minimal
            self.logger.info(f"❌ Rejeté: {token_symbol} ({token_address[:8]}...) | "
                            f"Safety: {safety_score:.3f} | Risk: {risk_level} | Action: {action}")

    def shutdown(self):
        """Graceful shutdown of all components including DexScreener"""
        self.logger.info("🔄 Initiating graceful shutdown...")
        self.is_running = False
        
        # Arrêter le scanner
        if hasattr(self, 'dex_scanner') and self.dex_scanner:
            try:
                self.dex_scanner.stop_scanning()
                self.logger.info("🔍 DEX Scanner stopped")
            except Exception as e:
                self.logger.warning(f"Error stopping scanner: {e}")
        
        # Annuler la tâche du scanner
        if hasattr(self, 'scanner_task') and self.scanner_task:
            try:
                self.scanner_task.cancel()
                self.logger.info("🔍 Scanner task cancelled")
            except Exception as e:
                self.logger.warning(f"Error cancelling scanner task: {e}")

        try:
            # Close database connections
            if hasattr(self, 'database_manager'):
                self.database_manager.close()
                self.logger.info("🗄️ Database connections closed")
        except Exception as e:
            self.logger.warning(f"Error closing database: {e}")
    
        try:
            # Clear DexScreener caches
            if self.dexscreener_analyzer:
                if hasattr(self.dexscreener_analyzer, 'clear_cache'):
                    self.dexscreener_analyzer.clear_cache()
                    self.logger.info("📊 DexScreener cache cleared")
        except Exception as e:
            self.logger.warning(f"Error clearing DexScreener cache: {e}")

        try:
            # Close Solana client
            if hasattr(self, 'solana_client') and self.solana_client:
                # Si on est déjà dans un contexte async, utiliser await
                # Sinon, utiliser run_until_complete
                try:
                    self.logger.info("🚀 Solana client will be closed automatically")
                except Exception:
                    # Fallback: fermeture simple
                    pass
        except Exception as e:
            self.logger.warning(f"Error closing Solana client: {e}")

        # Export final statistics
        try:
            # Export final statistics
            stats = self.get_comprehensive_statistics()
            stats_file = f'final_stats_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            
            import json
            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2, default=str)
            
            self.logger.info(f"📊 Final enhanced statistics exported to {stats_file}")
        
        except Exception as e:
            self.logger.error(f"Error exporting final stats: {e}")
        
        self.logger.info("✅ Enhanced Shutdown complete")
        # CORRECTION: Forcer la sortie propre
        import sys
        sys.exit(0)


def main():
    """Main application entry point"""
    parser = argparse.ArgumentParser(
        description='Enhanced Solana Trading Bot with RugCheck Analysis, DexScreener Integration and Database Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start with debug logging
    python main.py --log-level DEBUG
    
    # Run single test cycle
    python main.py --test-run
    
    # Use specific strategy
    python main.py --strategy aggressive
    
    # Paper trading mode
    python main.py --paper-trading
    
    # Show bot statistics
    python main.py --stats

    # Test DexScreener integration
    python main.py --test-dexscreener So11111111111111111111111111111111111111112
    
    # 🆕 NOUVEAU: Scanner modes
    python main.py --scanner-mode
    python main.py --hybrid-mode
    python main.py --test-scanner
    python main.py --scanner-stats

        """
    )
    
    parser.add_argument('--quick-test', action='store_true',
                   help='Quick 30-second scanner test')

    parser.add_argument('--test-methods', action='store_true',
                   help='Test all newest token methods and compare results')

    parser.add_argument('--method', choices=['timestamp', 'terms', 'optimized'], 
                   default='timestamp',
                   help='Method to find newest tokens (default: timestamp)')

    parser.add_argument('--continuous-newest', metavar='HOURS', type=int, nargs='?', 
                   const=6, help='Continuous analysis of newest tokens (default: 6h lookback)')
    parser.add_argument('--scan-interval', metavar='MINUTES', type=int, default=10,
                   help='Interval between scans in minutes (default: 10)')

    # Configuration options
    parser.add_argument('--config', help='Configuration override (not used with config.py)')
    
    # Logging options  
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help='Set logging level (default: INFO)')
    
    # Operation modes
    parser.add_argument('--test-run', action='store_true', 
                       help='Run single test cycle without continuous monitoring')
    parser.add_argument('--stats', action='store_true',
                       help='Show comprehensive bot statistics and exit')
    parser.add_argument('--maintenance', action='store_true',
                       help='Run maintenance tasks and exit')
    parser.add_argument('--paper-trading', action='store_true',
                       help='Force paper trading mode (overrides config)')

    parser.add_argument('--test-endpoints', action='store_true',
                   help='Test DexScreener API endpoints')
    # Solana client
    parser.add_argument('--test-solana', action='store_true',
                   help='Test Solana client connection and features')
    parser.add_argument('--wallet-info', action='store_true',
                    help='Show wallet information and exit')

    # Ajout dans la section "Analysis tools"
    parser.add_argument('--newest-analysis', metavar='HOURS', type=int, nargs='?', 
                   const=3, help='Analyze newest tokens from last N hours (default: 3)')

    # Strategy options
    parser.add_argument('--strategy', choices=['conservative', 'aggressive', 'experimental'],
                       help='Trading strategy to use (overrides config)')
    
    # Analysis tools
    parser.add_argument('--test-rugcheck', metavar='TOKEN_ADDRESS', 
                       help='Test RugCheck analysis on specific token')
    parser.add_argument('--test-dexscreener', metavar='TOKEN_ADDRESS', 
                       help='Test DexScreener analysis on specific token')
    parser.add_argument('--trending-analysis', action='store_true',
                       help='Analyze trending tokens and exit')
    parser.add_argument('--validate-config', action='store_true',
                       help='Validate configuration and exit')
    
    # Database tools
    parser.add_argument('--init-db', action='store_true',
                       help='Initialize database and exit')
    parser.add_argument('--backup-db', action='store_true',
                       help='Create database backup and exit')
    
    # 🆕 NOUVEAUX ARGUMENTS
    parser.add_argument('--scanner-mode', action='store_true',
                       help='Run in scanner-only mode (real-time DEX listings monitoring)')
    parser.add_argument('--hybrid-mode', action='store_true',
                       help='Run in hybrid mode (scanner + traditional cycles)')
    parser.add_argument('--disable-scanner', action='store_true',
                       help='Disable DEX listings scanner')
    parser.add_argument('--scanner-stats', action='store_true',
                       help='Show DEX scanner statistics and exit')
    parser.add_argument('--test-scanner', action='store_true',
                       help='Test DEX scanner for 5 minutes')

    args = parser.parse_args()
    
    # Handle configuration validation
    if args.validate_config:
        print("🔧 Validating configuration...")
        config_errors = validate_config()
        if config_errors:
            print("❌ CONFIGURATION ERRORS:")
            for error in config_errors:
                print(f"   - {error}")
            return 1
        else:
            print("✅ Configuration is valid!")
            return 0
    
    # Handle database initialization
    if args.init_db:
        print("🗄️ Initializing database...")
        try:
            config = get_config()
            db = create_database_manager(config)
            stats = db.get_database_stats()
            db.close()
            print(f"✅ Database initialized: {stats['database_path']}")
            print(f"📊 Schema version: {stats['schema_version']}")
            return 0
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            return 1
    
    # Handle database backup
    if args.backup_db:
        print("💾 Creating database backup...")
        try:
            config = get_config()
            db = create_database_manager(config)
            backup_path = db.create_backup()
            db.close()
            print(f"✅ Backup created: {backup_path}")
            return 0
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return 1
    
    # Initialize bot
    try:
        # Override config for paper trading if specified
        if args.paper_trading:
            from config import update_config
            update_config('trading', 'paper_trading', True)
            print("📊 Paper trading mode ENABLED via command line")
        
        # 🆕 NOUVEAU: Override scanner settings
        if args.disable_scanner:
            from config import update_config
            update_config('scanner', 'enabled', False)
            print("🔍 DEX Scanner DISABLED via command line")

        bot = SolanaTradingBot(
            config_path=args.config,
            log_level=args.log_level,
            strategy=args.strategy
        )
        
    except Exception as e:
        print(f"❌ Failed to initialize bot: {e}")
        return 1
    
    # Handle different operation modes
    try:
        if args.stats:
            # Show comprehensive statistics
            stats = bot.get_comprehensive_statistics()
            print("\n" + "="*80)
            print("COMPREHENSIVE BOT STATISTICS")
            print("="*80)
            
            # System stats
            system = stats['system']
            print(f"🤖 SYSTEM:")
            print(f"   Uptime: {system['uptime_human']}")
            print(f"   Environment: {system['environment']}")
            print(f"   Strategy: {system['strategy']}")
            print(f"   Paper Trading: {'Yes' if system['paper_trading'] else 'No'}")
            print(f"   Cycles Completed: {system['cycles_completed']}")
            
            # 🆕 NOUVEAU: Scanner stats
            scanner_stats = stats.get('dex_scanner', {})
            print(f"\n🔍 DEX SCANNER:")
            if scanner_stats.get('enabled', False):
                print(f"   Status: {scanner_stats.get('status', 'Unknown')}")
                print(f"   Discoveries: {scanner_stats.get('total_discoveries', 0)}")
                print(f"   Filtered: {scanner_stats.get('filtered_pairs', 0)}")
                print(f"   Duplicates: {scanner_stats.get('duplicate_pairs', 0)}")
                print(f"   Uptime: {scanner_stats.get('uptime_hours', 0):.1f}h")
                print(f"   DEXs: {', '.join(scanner_stats.get('enabled_dexs', []))}")
            else:
                print("   Status: Disabled")

            # Database stats
            db_stats = stats['database']
            print(f"\n🗄️ DATABASE:")
            print(f"   Size: {db_stats.get('database_size_mb', 0):.2f} MB")
            print(f"   Tokens: {db_stats.get('tokens_count', 0):,}")
            print(f"   Transactions: {db_stats.get('transactions_count', 0):,}")
            print(f"   Analytics: {db_stats.get('analytics_count', 0):,}")
            
            # Portfolio stats
            portfolio = stats['portfolio']
            print(f"\n💰 PORTFOLIO:")
            print(f"   SOL Balance: {portfolio['sol_balance']:.4f}")
            print(f"   Positions: {len(portfolio['positions'])}")
            print(f"   Total Value: ${portfolio['total_value_usd']:.2f}")
            print(f"   Daily P&L: ${portfolio['daily_pnl']:.2f}")
            
            # Trading stats
            trading = stats['trading']
            print(f"\n📈 TRADING:")
            print(f"   Total Trades: {trading['total_trades']}")
            print(f"   Daily Trades: {trading['daily_trades']}")
            print(f"   Success Rate: {trading['success_rate']:.1%}")
            
            # RugCheck stats
            if stats['rugcheck']:
                rugcheck = stats['rugcheck']
                print(f"\n🔒 RUGCHECK:")
                print(f"   Total Analyses: {rugcheck.get('total_analyses', 0)}")
                print(f"   Bundles Detected: {rugcheck.get('bundles_detected', 0)}")
                print(f"   Average Safety Score: {rugcheck.get('average_safety_score', 0):.3f}")
            
            return 0
        
        elif args.quick_test:
            # Test rapide de 30 secondes
            print("⚡ Quick 30-second scanner test...")
            
            async def quick_test():
                scanner = await bot.initialize_dex_scanner()
                if scanner:
                    print("✅ Scanner started, monitoring for 30 seconds...")
                    await asyncio.sleep(30)
                    scanner.stop_scanning()
                    
                    stats = scanner.get_stats()
                    print(f"📊 Quick Test Results: {stats['valid_new_pairs']} discoveries")
                else:
                    print("❌ Failed to start scanner")
            
            asyncio.run(quick_test())
            return 0

        # 🆕 NOUVEAU: Scanner-specific commands
        elif args.scanner_stats:
            # Afficher les statistiques du scanner
            stats = bot.get_comprehensive_statistics()
            scanner_stats = stats.get('dex_scanner', {})
            
            print("\n" + "="*60)
            print("DEX SCANNER STATISTICS")
            print("="*60)
            
            if scanner_stats.get('enabled', False):
                print(f"Status: {scanner_stats.get('status', 'Unknown')}")
                print(f"Total Discoveries: {scanner_stats.get('total_discoveries', 0)}")
                print(f"Filtered Pairs: {scanner_stats.get('filtered_pairs', 0)}")
                print(f"Duplicate Pairs: {scanner_stats.get('duplicate_pairs', 0)}")
                print(f"Uptime: {scanner_stats.get('uptime_hours', 0):.2f}h")
                print(f"Enabled DEXs: {', '.join(scanner_stats.get('enabled_dexs', []))}")
                print(f"Last Discovery: {scanner_stats.get('last_discovery', 'Never')}")
            else:
                print("Scanner is disabled")
            
            return 0

        elif args.test_scanner:
            # Test du scanner pendant 5 minutes
            print("🧪 Testing DEX Scanner for 5 minutes...")
            print("⚠️ Note: APIs might be slow, please wait...")
            async def test_scanner():
                scanner = await bot.initialize_dex_scanner()
                if scanner:
                    print("✅ Scanner started, monitoring for 5 minutes...")
                    print("📊 Monitoring new token discoveries...")
                    print("🕒 Running for 5 minutes (be patient with slow APIs)...")
                    # Afficher des stats intermédiaires
                    for minute in range(5):
                        await asyncio.sleep(60)  # 1 minute
                        stats = scanner.get_stats()
                        print(f"   Minute {minute+1}: {stats['valid_new_pairs']} discoveries, "
                            f"{stats['duplicate_pairs']} duplicates")

                    scanner.stop_scanning()
                    
                    stats = scanner.get_stats()
                    print(f"\n📊 Final Test Results:")
                    print(f"   ✅ Valid Discoveries: {stats['valid_new_pairs']}")
                    print(f"   🔄 Duplicates: {stats['duplicate_pairs']}")
                    print(f"   🚫 Filtered: {stats['filtered_pairs']}")
                    print(f"   ⏱️ Uptime: {stats['uptime_hours']:.2f}h")
                else:
                    print("❌ Failed to start scanner")
            
            asyncio.run(test_scanner())
            return 0

        elif args.scanner_mode:
            # Mode scanner uniquement
            print("🔍 Starting DEX Scanner Mode...")
            asyncio.run(bot.run_scanner_mode())
            return 0

        elif args.hybrid_mode:
            # Mode hybride
            print("🔄 Starting Hybrid Mode...")
            interval_minutes = bot.trading_config['analysis_interval_seconds'] // 60
            asyncio.run(bot.run_hybrid_mode(interval_minutes))
            return 0

        elif args.maintenance:
            # Run maintenance tasks
            print("🔧 Running maintenance tasks...")
            
            async def run_maintenance():
                await bot.perform_maintenance()
                print("✅ Maintenance complete")
            
            asyncio.run(run_maintenance())
            return 0

        elif args.test_methods:
            # Tester toutes les méthodes
            print("🧪 Testing all newest token methods...")
            
            async def test_all_methods():
                methods = ['timestamp', 'optimized', 'terms']
                results = {}
                
                for method in methods:
                    print(f"\n🔧 Testing method: {method}")
                    try:
                        tokens = await bot.analyze_newest_tokens(hours_back=6, limit=20)
                        results[method] = len(tokens)
                        print(f"✅ {method}: Found {len(tokens)} tokens")
                    except Exception as e:
                        results[method] = f"Error: {e}"
                        print(f"❌ {method}: {e}")
                
                print(f"\n📊 RESULTS SUMMARY:")
                for method, result in results.items():
                    print(f"   {method}: {result}")
            
            asyncio.run(test_all_methods())
            return 0

        elif args.test_endpoints:
            async def test_endpoints():
                await bot.test_dexscreener_endpoints()
            
            asyncio.run(test_endpoints())
            return 0

        elif args.continuous_newest:
            # Analyse continue des nouveaux tokens
            hours = args.continuous_newest
            interval = args.scan_interval
            print(f"🔄 Starting continuous newest tokens analysis...")
            print(f"📊 Lookback: {hours}h | Interval: {interval}m")
            print(f"📁 Logs: good_tokens.log & bad_tokens.log")
            print("Press Ctrl+C to stop")
            
            async def continuous_newest():
                try:
                    await bot.run_continuous_newest_analysis(
                        hours_back=hours, 
                        interval_minutes=interval, 
                        method=args.method
                    )

                except Exception as e:
                    print(f"❌ Continuous analysis failed: {e}")
            
            asyncio.run(continuous_newest())
            return 0

        elif args.test_rugcheck:
            # Test RugCheck on specific token
            print(f"🔒 Testing RugCheck analysis on {args.test_rugcheck}")
            
            async def test_rugcheck():
                try:
                    result = await bot.analyze_token_comprehensive(args.test_rugcheck)
                    
                    print(f"\n🔒 RUGCHECK RESULTS:")
                    rugcheck_data = result.get('rugcheck_analysis', {})
                    
                    if rugcheck_data.get('error'):
                        print(f"❌ Error: {rugcheck_data['error']}")
                        return
                    
                    print(f"   Token: {rugcheck_data.get('token_symbol', 'UNKNOWN')} - {rugcheck_data.get('token_name', 'Unknown')}")
                    print(f"   Safety Score: {rugcheck_data.get('safety_score', 0):.3f}")
                    print(f"   Safety Rating: {rugcheck_data.get('safety_rating', 'Unknown')}")
                    print(f"   Bundle Detected: {'Yes' if rugcheck_data.get('bundle_detected', False) else 'No'}")
                    print(f"   Passed Verification: {'Yes' if rugcheck_data.get('passed_verification', False) else 'No'}")
                    
                    if rugcheck_data.get('bundle_detected'):
                        print(f"   Bundle Confidence: {rugcheck_data.get('bundle_confidence', 0):.3f}")
                    
                    # Risk assessment
                    risk = result.get('risk_assessment', {})
                    print(f"\n⚖️ RISK ASSESSMENT:")
                    print(f"   Overall Risk: {risk.get('overall_risk', 'UNKNOWN')}")
                    print(f"   Risk Score: {risk.get('risk_score', 0)}/100")
                    print(f"   Recommendation: {risk.get('recommendation', 'Unknown')}")
                    
                    if risk.get('risk_factors'):
                        print(f"   Risk Factors:")
                        for factor in risk['risk_factors']:
                            print(f"     • {factor}")
                    
                    # Trading recommendation
                    trading_rec = result.get('trading_recommendation', {})
                    print(f"\n💡 TRADING RECOMMENDATION:")
                    print(f"   Action: {trading_rec.get('action', 'UNKNOWN')}")
                    print(f"   Confidence: {trading_rec.get('confidence', 0):.1%}")
                    
                    if trading_rec.get('action') == 'BUY':
                        print(f"   Suggested Amount: {trading_rec.get('suggested_amount', 0):.4f} SOL")
                        print(f"   Stop Loss: {trading_rec.get('stop_loss', 0)}%")
                        print(f"   Take Profit: {trading_rec.get('take_profit', 0)}%")
                    
                    if trading_rec.get('reasoning'):
                        print(f"   Reasoning:")
                        for reason in trading_rec['reasoning']:
                            print(f"     • {reason}")
                    
                    # Alerts
                    alerts = result.get('alerts', [])
                    if alerts:
                        print(f"\n🚨 ALERTS ({len(alerts)}):")
                        for alert in alerts:
                            print(f"     • {alert['type']}: {alert['message']}")
                    
                except Exception as e:
                    print(f"❌ Test failed: {e}")
            
            asyncio.run(test_rugcheck())
            return 0

        elif args.test_dexscreener:
            # Test DexScreener on specific token
            print(f"📊 Testing DexScreener analysis on {args.test_dexscreener}")
            
            async def test_dexscreener():
                try:
                    if not bot.dexscreener_integration:
                        print("❌ DexScreener not available")
                        return
                    
                    # Get comprehensive trading data
                    result = bot.dexscreener_integration.get_token_trading_data(
                        args.test_dexscreener, 'solana'
                    )
                    
                    print(f"\n📊 DEXSCREENER RESULTS:")
                    
                    if 'error' in result:
                        print(f"❌ Error: {result['error']}")
                        return
                    
                    # Token info
                    pair_info = result.get('pair_info', {})
                    print(f"   Token: {pair_info.get('base_token', 'UNKNOWN')}/{pair_info.get('quote_token', 'UNKNOWN')}")
                    print(f"   DEX: {pair_info.get('dex', 'Unknown')}")
                    print(f"   Chain: {pair_info.get('chain', 'Unknown')}")
                    
                    # Price data
                    price_data = result.get('price_data', {})
                    if price_data.get('current_price_usd'):
                        print(f"   Current Price: ${price_data['current_price_usd']:.8f}")
                    if price_data.get('price_change_24h') is not None:
                        change = price_data['price_change_24h']
                        print(f"   24h Change: {change:+.2f}%")
                    
                    # Market data
                    market_data = result.get('market_data', {})
                    if market_data.get('liquidity_usd'):
                        print(f"   Liquidity: ${market_data['liquidity_usd']:,.0f}")
                    if market_data.get('volume_24h'):
                        print(f"   24h Volume: ${market_data['volume_24h']:,.0f}")
                    if market_data.get('market_cap'):
                        print(f"   Market Cap: ${market_data['market_cap']:,.0f}")
                    if market_data.get('age_hours'):
                        print(f"   Age: {market_data['age_hours']:.1f} hours")
                    
                    # Trading metrics
                    trading_metrics = result.get('trading_metrics', {})
                    if trading_metrics:
                        buys = trading_metrics.get('buys_24h', 0)
                        sells = trading_metrics.get('sells_24h', 0)
                        print(f"   24h Transactions: {buys} buys, {sells} sells")
                        
                        vol_liq_ratio = trading_metrics.get('volume_to_liquidity_ratio')
                        if vol_liq_ratio:
                            print(f"   Volume/Liquidity Ratio: {vol_liq_ratio:.2f}")
                    
                    # Risk assessment
                    risk_assessment = result.get('risk_assessment', {})
                    if risk_assessment:
                        print(f"\n⚖️ DEXSCREENER RISK ASSESSMENT:")
                        print(f"   Risk Level: {risk_assessment.get('risk_level', 'Unknown')}")
                        print(f"   Risk Score: {risk_assessment.get('risk_score', 0)}")
                        
                        risk_factors = risk_assessment.get('risk_factors', [])
                        if risk_factors:
                            print(f"   Risk Factors:")
                            for factor in risk_factors:
                                print(f"     • {factor}")
                    
                    # Trading signals
                    trading_signals = result.get('trading_signals', {})
                    if trading_signals:
                        print(f"\n💡 TRADING SIGNALS:")
                        signals = trading_signals.get('signals', [])
                        if signals:
                            for signal in signals:
                                print(f"     • {signal}")
                        
                        strength = trading_signals.get('signal_strength', 0)
                        print(f"   Signal Strength: {strength}")
                    
                    # Recommendation
                    recommendation = result.get('recommendation', 'Unknown')
                    print(f"   Recommendation: {recommendation}")
                    
                except Exception as e:
                    print(f"❌ DexScreener test failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            asyncio.run(test_dexscreener())
            return 0
        
        elif args.test_solana:
            # Test Solana client
            print("🚀 Testing Solana client...")
            
            async def test_solana():
                try:
                    if not bot.solana_client:
                        print("❌ Solana client not available")
                        return
                    
                    # Health check
                    health = await bot.solana_client.health_check()
                    print(f"🏥 Health: {health['status']}")
                    print(f"📍 Wallet: {health['wallet_address']}")
                    print(f"💰 Balance: {health['sol_balance']:.6f} SOL")
                    print(f"🔧 Latency: {health['rpc_latency_ms']:.1f}ms")
                    
                    # Performance metrics
                    metrics = bot.solana_client.get_performance_metrics()
                    print(f"📊 Mode: {metrics['mode']}")
                    print(f"📈 Success Rate: {metrics['success_rate_percent']:.1f}%")
                    
                except Exception as e:
                    print(f"❌ Solana test failed: {e}")
    
            asyncio.run(test_solana())
            return 0


        elif args.newest_analysis:
            # Analyser les tokens les plus récents
            hours = args.newest_analysis
            print(f"🆕 Analyzing newest tokens from last {hours} hours...")
            
            async def analyze_newest():
                try:
                    print(f"🔧 Using method: {args.method}")
                    
                    # Choisir la méthode selon l'argument
                    if args.method == 'timestamp':
                        method_name = 'get_newest_tokens_by_timestamp'
                    elif args.method == 'optimized':
                        method_name = 'get_newest_tokens_optimized'
                    else:  # terms
                        method_name = 'get_newest_tokens_realtime'
                    
                    print(f"📡 Method selected: {method_name}")
                    newest_tokens = await bot.analyze_newest_tokens(hours_back=hours, limit=50)
                    
                    if not newest_tokens:
                        print("❌ No new tokens found or analyzed")
                        return
                    
                    print(f"\n🆕 NEWEST TOKENS ANALYSIS ({len(newest_tokens)} found):")
                    print("="*80)
                    
                    for i, token_data in enumerate(newest_tokens, 1):
                        print(f"\n{i}. {token_data.get('symbol', 'UNKNOWN')} - {token_data.get('name', 'Unknown')}")
                        print(f"   Address: {token_data['token_address'][:8]}...{token_data['token_address'][-8:]}")
                        print(f"   Age: {token_data.get('age_hours', 0):.1f} hours")
                        
                        if token_data.get('price_usd'):
                            print(f"   Price: ${token_data['price_usd']:.8f}")
                        
                        print(f"   Liquidity: ${token_data.get('liquidity_usd', 0):,.0f}")
                        print(f"   Volume 24h: ${token_data.get('volume_24h', 0):,.0f}")
                        
                        freshness_score = token_data.get('freshness_score', 0)
                        print(f"   Freshness Score: {freshness_score:.1f}/100")
                        
                        # Résultats d'analyse
                        analysis = token_data.get('analysis', {})
                        if analysis:
                            risk_assessment = analysis.get('risk_assessment', {})
                            if risk_assessment:
                                risk_level = risk_assessment.get('overall_risk', 'Unknown')
                                print(f"   Risk Level: {risk_level}")
                            
                            trading_rec = analysis.get('trading_recommendation', {})
                            if trading_rec:
                                action = trading_rec.get('action', 'Unknown')
                                confidence = trading_rec.get('confidence', 0)
                                print(f"   Recommendation: {action} (Confidence: {confidence:.1%})")
                        
                        print(f"   DEX: {token_data.get('dex_id', 'Unknown')}")
                        print("-" * 40)
                    
                except Exception as e:
                    print(f"❌ Newest tokens analysis failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            asyncio.run(analyze_newest())
            return 0

        elif args.wallet_info:
            # Show wallet info
            print("💰 Getting wallet information...")
    
            async def show_wallet():
                try:
                    wallet_info = await bot.get_wallet_info()
                    if 'error' in wallet_info:
                        print(f"❌ Error: {wallet_info['error']}")
                        return
                    
                    print(f"📍 Address: {wallet_info['wallet_address']}")
                    print(f"💰 SOL Balance: {wallet_info['sol_balance']:.6f}")
                    print(f"💵 USD Value: ${wallet_info['total_value_usd']:.2f}")
                    print(f"📊 Token Positions: {len(wallet_info['token_balances'])}")
                    
                except Exception as e:
                    print(f"❌ Failed to get wallet info: {e}")
            
            asyncio.run(show_wallet())
            return 0

        elif args.trending_analysis:
            # Analyze trending tokens
            print("🔥 Analyzing trending tokens...")
            
            async def analyze_trending():
                try:
                    if not bot.dexscreener_analyzer:
                        print("❌ DexScreener not available for trending analysis")
                        return
                    
                    trending_tokens = await bot.analyze_trending_tokens(limit=10)
                    
                    print(f"\n🔥 TRENDING TOKENS ANALYSIS ({len(trending_tokens)} found):")
                    print("="*80)
                    
                    for i, token_data in enumerate(trending_tokens, 1):
                        print(f"\n{i}. {token_data.get('symbol', 'UNKNOWN')} - {token_data.get('name', 'Unknown')}")
                        print(f"   Address: {token_data['token_address'][:8]}...{token_data['token_address'][-8:]}")
                        
                        if token_data.get('price_usd'):
                            print(f"   Price: ${token_data['price_usd']:.8f}")
                        
                        if token_data.get('price_change_24h') is not None:
                            change = token_data['price_change_24h']
                            print(f"   24h Change: {change:+.2f}%")
                        
                        if token_data.get('volume_24h'):
                            print(f"   Volume: ${token_data['volume_24h']:,.0f}")
                        
                        if token_data.get('liquidity_usd'):
                            print(f"   Liquidity: ${token_data['liquidity_usd']:,.0f}")
                        
                        trending_score = token_data.get('trending_score', 0)
                        print(f"   Trending Score: {trending_score:.1f}/100")
                        
                        # Analysis results
                        analysis = token_data.get('analysis', {})
                        if analysis:
                            risk_assessment = analysis.get('risk_assessment', {})
                            if risk_assessment:
                                risk_level = risk_assessment.get('overall_risk', 'Unknown')
                                print(f"   Risk Level: {risk_level}")
                            
                            trading_rec = analysis.get('trading_recommendation', {})
                            if trading_rec:
                                action = trading_rec.get('action', 'Unknown')
                                confidence = trading_rec.get('confidence', 0)
                                print(f"   Recommendation: {action} (Confidence: {confidence:.1%})")
                        
                        print(f"   DEX: {token_data.get('dex_id', 'Unknown')}")
                        print("-" * 40)
                    
                except Exception as e:
                    print(f"❌ Trending analysis failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            asyncio.run(analyze_trending())
            return 0

        elif args.test_run:
            # Run single test cycle
            print("🧪 Running test cycle...")
            
            async def test_cycle():
                try:
                    result = await bot.run_monitoring_cycle()
                    print(f"\n✅ Test cycle complete:")
                    print(f"   Processed: {result['processed_count']} tokens")
                    print(f"   Duration: {result['duration']:.2f}s")
                    print(f"   Alerts: {result['alerts_count']}")
                    
                    # Show some database stats
                    db_stats = bot.database_manager.get_database_stats()
                    print(f"\n📊 Database Updated:")
                    print(f"   Total Tokens: {db_stats.get('tokens_count', 0)}")
                    print(f"   Total Analytics: {db_stats.get('analytics_count', 0)}")
                    
                except Exception as e:
                    print(f"❌ Test cycle failed: {e}")
            
            asyncio.run(test_cycle())
            return 0
            
        else:
            # Run continuous monitoring (default mode)
            print("\n" + "="*80)
            print("STARTING SOLANA TRADING BOT")
            print("="*80)
            
            # Display configuration
            config = get_config()
            trading_config = get_trading_config()
            
            print(f"🌍 Environment: {ENVIRONMENT}")
            print(f"📊 Paper Trading: {'ENABLED' if trading_config['paper_trading'] else 'DISABLED'}")
            print(f"🤖 Auto Trading: {'ENABLED' if trading_config['auto_trading'] else 'DISABLED'}")
            print(f"🎯 Strategy: {config['strategies']['default_strategy']}")
            print(f"💰 Default Trade Amount: {trading_config['default_trade_amount']} SOL")
            print(f"🔄 Analysis Interval: {trading_config['analysis_interval_seconds']}s")
            
            # 🆕 NOUVEAU: Affichage du mode scanner
            if bot.scanner_enabled:
                enabled_dexs = bot.config.get('scanner', {}).get('enabled_dexs', [])
                min_liquidity = bot.config.get('scanner', {}).get('min_liquidity_sol', 5.0)
                scan_interval = bot.config.get('scanner', {}).get('scan_interval_seconds', 30)
                
                print(f"\n🔍 DEX SCANNER FEATURES:")
                print(f"  ✅ Real-time listings monitoring")
                print(f"  ✅ Automatic duplicate filtering")
                print(f"  ✅ Instant analysis pipeline")
                print(f"  ✅ Multi-DEX support")
                print(f"  📊 Monitoring: {', '.join(enabled_dexs)}")
                print(f"  💧 Min Liquidity: {min_liquidity} SOL")
                print(f"  ⏱️ Scan Interval: {scan_interval}s")
                
                # Déterminer le mode
                mode = "HYBRID MODE (Scanner + Traditional Cycles)"
            else:
                print(f"\n🔍 DEX SCANNER: Disabled")
                mode = "TRADITIONAL MODE (Cycles Only)"

            # Security features
            print(f"\n🛡️ Active Security Features:")
            print(f"  ✅ RugCheck Security Analysis")
            print(f"  ✅ Advanced Bundle Detection")
            print(f"  ✅ Risk Assessment Engine")
            print(f"  ✅ Database Storage & Analytics")
            print(f"  ✅ Real-time Monitoring")
            
            # Safety warnings
            if not trading_config['paper_trading']:
                print(f"\n⚠️ WARNING: LIVE TRADING ENABLED!")
                print(f"   Make sure you understand the risks!")
                print(f"   Maximum daily trades: {trading_config['max_daily_trades']}")
                print(f"   Stop loss: {trading_config['stop_loss_percentage']}%")
            else:
                print(f"\n✅ PAPER TRADING MODE - No real trades will be executed")
            
            print("="*80)
            print("Press Ctrl+C to stop the bot")
            print("="*80)
            
            # Start continuous monitoring
            interval_minutes = trading_config['analysis_interval_seconds'] // 60
            asyncio.run(bot.run_continuous_monitoring(interval_minutes))
            
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        if 'bot' in locals():
            bot.shutdown()
        return 0
        
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        if 'bot' in locals():
            bot.logger.error(f"Critical application error: {e}")
            bot.shutdown()
        return 1
    
    finally:
        if 'bot' in locals():
            bot.shutdown()
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
