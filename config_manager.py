"""
Configuration Management Module
File: config_manager.py

Handles all configuration loading, validation, and management
for the DexScreener Solana Bot system.
"""

import yaml
import os
import logging
from datetime import datetime

class ConfigManager:
    """
    Comprehensive configuration manager for DexScreener Bot
    
    Handles:
    - YAML configuration loading/saving
    - Default configuration generation
    - Configuration validation
    - Environment variable overrides
    """
    
    def __init__(self, config_path='config.yaml'):
        self.config_path = config_path
        self.config = self.load_config()
        
    def load_config(self):
        """Load configuration from YAML file or create default"""
        if not os.path.exists(self.config_path):
            print(f"⚠️  Configuration file not found: {self.config_path}")
            print("📁 Creating default configuration...")
            self.create_default_config()
            
        try:
            with open(self.config_path, 'r') as file:
                config = yaml.safe_load(file)
                
            # Validate configuration
            self._validate_config(config)
            
            print(f"✅ Configuration loaded from: {self.config_path}")
            return config
            
        except Exception as e:
            print(f"❌ Error loading config: {e}")
            print("📁 Using default configuration...")
            return self.get_default_config()
            
    def create_default_config(self):
        """Create default configuration file"""
        default_config = self.get_default_config()
        
        with open(self.config_path, 'w') as file:
            yaml.dump(default_config, file, default_flow_style=False, indent=2)
            
        print(f"✅ Created default config file: {self.config_path}")
        
    def get_default_config(self):
        """Return comprehensive default configuration"""
        return {
            # API Configuration
            'api': {
                'base_url': 'https://api.dexscreener.com/latest/dex',
                'request_timeout': 15,
                'rate_limit_delay': 1,
                'max_retries': 3
            },
            
            # Database Configuration
            'database': {
                'path': 'solana_tokens.db',
                'backup_interval_hours': 24,
                'cleanup_days': 30,  # Keep data for 30 days
                'batch_size': 1000
            },
            
            # Monitoring Configuration
            'monitoring': {
                'interval_minutes': 5,
                'pairs_per_fetch': 100,
                'retrain_interval_minutes': 60,
                'pattern_analysis_interval_minutes': 120,
                'maintenance_interval_hours': 6
            },
            
            # Advanced Filtering System
            'filters': {
                'min_liquidity_usd': 2000,
                'max_liquidity_usd': 50000000,
                'min_volume_24h': 1000,
                'max_volume_24h': 100000000,
                'min_market_cap': 1000,
                'max_market_cap': 500000000,
                'min_pair_age_minutes': 5,
                'max_pair_age_hours': 168,  # 1 week
                'min_price_change_24h': -98,   # Allow up to -98% dump
                'max_price_change_24h': 2000,  # Allow up to 2000% pump
                'exclude_honeypots': True,
                'only_verified_tokens': False,
                'min_transactions_24h': 10,
                'max_volume_to_liquidity_ratio': 100
            },
            
            # Detection Thresholds
            'detection_thresholds': {
                'rug_confidence_threshold': 0.7,
                'pump_confidence_threshold': 0.6,
                'fake_volume_threshold': 0.7,  # Pocker Universe threshold
                'extreme_pump_5m': 150,    # 150% in 5 minutes
                'extreme_dump_5m': -85,    # -85% in 5 minutes
                'volume_spike_multiplier': 8,  # 8x average volume
                'liquidity_drain_threshold': 0.4  # 40% liquidity decrease
            },
            
            # 🔍 POCKER UNIVERSE CONFIGURATION
            # Advanced fake volume detection system integrated into DexScreener
            'pocker_universe': {
                'enable_fake_volume_detection': True,
                'api_timeout': 15,
                'min_volume_for_analysis': 15000,  # Minimum $15k volume
                'fake_volume_threshold': 0.75,     # Threshold for blacklisting
                'cache_results_hours': 2,          # Cache for 2 hours
                
                # Advanced Wash Trading Detection Indicators
                'wash_trading_indicators': {
                    'circular_trading_threshold': 0.35,     # Detect circular patterns
                    'bot_trading_ratio': 0.6,               # Bot vs human trading ratio
                    'unique_trader_ratio': 0.08,            # Minimum unique traders
                    'volume_concentration_ratio': 0.85,     # Volume concentration limit
                    'price_impact_threshold': 0.02,         # Minimum price impact per volume
                    'regularity_threshold': 0.95,           # Trading regularity detection
                    'liquidity_manipulation_ratio': 40      # Volume to liquidity ratio limit
                },
                
                # Pattern Recognition Settings
                'pattern_recognition': {
                    'enable_time_series_analysis': True,
                    'enable_volume_clustering': True,
                    'enable_price_stability_check': True,
                    'enable_round_number_detection': True
                }
            },
            
            # 🔒 RUGCHECK CONFIGURATION  
            'rugcheck': {
                'enable_rugcheck_verification': True,
                'api_base_url': 'https://api.rugcheck.xyz/v1',
                'api_timeout': 12,
                'required_safety_score': 'Good',  # Only interact with "Good" rated contracts
                'check_for_bundles': True,
                'bundle_detection_threshold': 0.7,  # Bundle confidence threshold
                'cache_results_hours': 8,           # Cache for 8 hours
                'retry_attempts': 4,
                'retry_delay': 3,
                'rate_limit_delay': 2
            },
            
            # 💰 TOXISOL TRADING CONFIGURATION
            'toxisol_trading': {
                'enable_trading': False,  # DISABLED BY DEFAULT - Enable manually
                'trading_mode': 'manual',  # 'manual' or 'auto'
                'toxisol_bot_username': '@ToxiSolBot',
                
                # Auto-trading conditions (very strict by default)
                'auto_trade_conditions': {
                    'min_safety_score': 0.9,           # Require 90%+ safety score
                    'max_fake_volume_score': 0.2,      # Max 20% fake volume
                    'no_bundle_detected': True,         # No bundles allowed
                    'rugcheck_verified': True,          # Must pass RugCheck
                    'min_liquidity_usd': 10000,        # Min $10k liquidity
                    'max_buy_amount_sol': 0.05,        # Max 0.05 SOL per trade
                    'min_holder_count': 50,             # Min 50 holders
                    'max_concentration_risk': 0.1      # Max 10% held by top holder
                },
                
                # Trading commands for ToxiSol integration
                'trade_commands': {
                    'buy_command_template': '/buy {token_address} {amount}',
                    'sell_command_template': '/sell {token_address} {percentage}',
                    'check_balance': '/balance',
                    'get_price': '/price {token_address}',
                    'stop_loss': '/sl {token_address} {percentage}'
                }
            },
            
            # 📱 COMPREHENSIVE NOTIFICATIONS
            'notifications': {
                'telegram': {
                    'enabled': False,  # Set to True and add your credentials
                    'bot_token': 'YOUR_TELEGRAM_BOT_TOKEN_HERE',
                    'chat_ids': [],  # Add your chat IDs here: ['123456789']
                    'notification_types': {
                        'rug_alerts': True,
                        'pump_alerts': True, 
                        'fake_volume_alerts': True,
                        'bundle_alerts': True,
                        'rugcheck_failures': True,
                        'trade_notifications': True,
                        'system_status': True,
                        'hourly_reports': True
                    }
                },
                'discord': {
                    'enabled': False,
                    'webhook_url': 'YOUR_DISCORD_WEBHOOK_URL_HERE',
                    'notification_types': {
                        'rug_alerts': True,
                        'pump_alerts': True,
                        'fake_volume_alerts': True,
                        'bundle_alerts': True,
                        'system_status': True
                    }
                },
                'email': {
                    'enabled': False,
                    'smtp_server': 'smtp.gmail.com',
                    'smtp_port': 587,
                    'username': 'your_email@gmail.com',
                    'password': 'your_app_password',
                    'recipients': ['alert_recipient@gmail.com']
                }
            },
            
            # 🚨 COMPREHENSIVE BLACKLISTS
            'blacklists': {
                'coin_symbols': [
                    # Common scam indicators
                    'SCAM', 'RUG', 'FAKE', 'TEST', 'PONZI', 'PYRAMID', 'EXIT',
                    'HONEY', 'POT', 'RUGPULL', 'SCAMCOIN', 'FAKECOIN', 'TESTCOIN',
                    # Pump & dump patterns  
                    'PUMP', 'DUMP', 'PND', 'SHILL', 'MOON', 'LAMBO', 'ROCKET',
                    # Generic warnings
                    'WARNING', 'DANGER', 'AVOID', 'CAUTION', 'ALERT'
                ],
                
                'coin_names': [
                    # Scam phrases
                    'definitely not a scam', 'guaranteed profit', 'moon guaranteed',
                    'safe rugpull', 'legitimate scam', 'honest ponzi', 'fair rug',
                    'not a honeypot', 'totally legit', 'trust me bro',
                    # Pump phrases
                    'to the moon', 'diamond hands', '100x guaranteed', 'easy money',
                    'get rich quick', 'financial freedom', 'passive income'
                ],
                
                'token_addresses': [
                    # Add specific scam token addresses here
                    # Example: '7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU'
                ],
                
                'dev_addresses': [
                    # Add known scammer/rugger wallet addresses
                    # Example: 'CuieVDEDtLo7FypA9SbLM9saXFdb1dsshEkyErMqkRQq'  
                ],
                
                'pair_addresses': [
                    # Add specific malicious pair addresses
                ],
                
                # 📊 POCKER UNIVERSE AUTO-POPULATED
                'fake_volume_tokens': [
                    # Automatically populated by Pocker Universe algorithm
                ],
                
                # 📦 RUGCHECK AUTO-POPULATED  
                'bundled_tokens': [
                    # Automatically populated by RugCheck bundle detection
                ],
                
                'rugcheck_failed_tokens': [
                    # Automatically populated for failed RugCheck verifications
                ]
            },
            
            # ✅ WHITELISTS (Trusted tokens/devs)
            'whitelists': {
                'trusted_dev_addresses': [
                    # Add verified developer wallet addresses
                ],
                'verified_projects': [
                    # Add verified project token addresses
                ]
            },
            
            # 📝 ADVANCED LOGGING CONFIGURATION
            'alerts': {
                'enable_console_alerts': True,
                'enable_file_logging': True,
                'log_level': 'INFO',
                'log_file': 'solana_bot.log',
                'max_log_file_size_mb': 100,
                'backup_count': 5,
                'detailed_debug_logging': True,
                
                # Component-specific log levels
                'component_log_levels': {
                    'api_calls': 'INFO',      # DexScreener, RugCheck, ToxiSol API calls
                    'filtering': 'INFO',      # Token filtering decisions
                    'analysis': 'INFO',       # Pocker Universe, RugCheck, AI analysis
                    'trading': 'INFO',        # ToxiSol trading decisions
                    'notifications': 'INFO',  # Telegram, Discord, Email notifications
                    'database': 'WARN',       # Database operations
                    'cache': 'WARN'          # Cache operations
                },
                
                # Alert thresholds
                'alert_on_rug_confidence': 0.8,
                'alert_on_pump_confidence': 0.7,
                'alert_on_fake_volume_score': 0.75,
                'alert_on_bundle_confidence': 0.8
            }
        }
        
    def _validate_config(self, config):
        """Validate configuration structure and values"""
        required_sections = [
            'api', 'database', 'monitoring', 'filters', 
            'detection_thresholds', 'pocker_universe', 'rugcheck',
            'toxisol_trading', 'notifications', 'blacklists', 'alerts'
        ]
        
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required config section: {section}")
        
        # Validate critical settings
        if config['monitoring']['interval_minutes'] < 1:
            raise ValueError("Monitoring interval must be at least 1 minute")
            
        if config['filters']['min_liquidity_usd'] < 0:
            raise ValueError("Minimum liquidity cannot be negative")
            
        # Validate Pocker Universe settings
        if config['pocker_universe']['enable_fake_volume_detection']:
            if config['pocker_universe']['fake_volume_threshold'] > 1.0:
                raise ValueError("Fake volume threshold cannot exceed 1.0")
                
        # Validate RugCheck settings
        if config['rugcheck']['enable_rugcheck_verification']:
            valid_ratings = ['Good', 'Warning', 'Caution', 'Dangerous']
            if config['rugcheck']['required_safety_score'] not in valid_ratings:
                raise ValueError(f"Invalid required_safety_score. Must be one of: {valid_ratings}")
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            with open(self.config_path, 'w') as file:
                yaml.dump(self.config, file, default_flow_style=False, indent=2)
            print(f"✅ Configuration saved to: {self.config_path}")
        except Exception as e:
            print(f"❌ Error saving config: {e}")
            
    def update_setting(self, section, key, value):
        """Update a specific configuration setting"""
        if section not in self.config:
            self.config[section] = {}
            
        self.config[section][key] = value
        self.save_config()
        
    def get_setting(self, section, key, default=None):
        """Get a specific configuration setting"""
        return self.config.get(section, {}).get(key, default)

def create_full_sample_config():
    """Create a comprehensive sample configuration with documentation"""
    config_manager = ConfigManager('full_sample_config.yaml')
    
    # Add example blacklist entries
    config_manager.config['blacklists']['coin_symbols'].extend([
        'EXAMPLE_SCAM', 'TEST_RUG', 'DEMO_FAKE'
    ])
    
    # Add example notification settings with placeholders
    config_manager.config['notifications']['telegram']['enabled'] = True
    config_manager.config['notifications']['telegram']['bot_token'] = 'YOUR_BOT_TOKEN_HERE'
    config_manager.config['notifications']['telegram']['chat_ids'] = ['YOUR_CHAT_ID_HERE']
    
    config_manager.config['notifications']['discord']['enabled'] = True 
    config_manager.config['notifications']['discord']['webhook_url'] = 'YOUR_DISCORD_WEBHOOK_HERE'
    
    # Configure ToxiSol for demo (but keep disabled)
    config_manager.config['toxisol_trading']['enable_trading'] = False
    config_manager.config['toxisol_trading']['trading_mode'] = 'manual'
    
    # Enhanced Pocker Universe settings
    config_manager.config['pocker_universe']['enable_fake_volume_detection'] = True
    config_manager.config['pocker_universe']['min_volume_for_analysis'] = 10000
    
    config_manager.save_config()
    
    print("\n" + "="*80)
    print("FULL SAMPLE CONFIGURATION CREATED")  
    print("="*80)
    print(f"📁 File: full_sample_config.yaml")
    print("\n🔧 IMPORTANT SETUP STEPS:")
    print("1. 📱 Add your Telegram bot token and chat ID")
    print("2. 🎮 Add your Discord webhook URL (optional)")
    print("3. 📧 Configure email settings (optional)")
    print("4. 💰 Review ToxiSol trading settings (DISABLED by default)")
    print("5. 📊 Adjust Pocker Universe fake volume detection settings")
    print("6. 🔒 Configure RugCheck bundle detection thresholds")
    print("7. 📝 Set appropriate logging levels for your needs")
    print("\n🚨 SECURITY NOTICE:")
    print("   • Trading is DISABLED by default for safety")
    print("   • Only tokens with 'Good' RugCheck rating are processed")
    print("   • Pocker Universe automatically blacklists fake volume tokens")
    print("   • All detected bundles are automatically blacklisted")
    print("="*80)

if __name__ == "__main__":
    create_full_sample_config()